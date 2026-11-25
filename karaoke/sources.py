"""Lyrics sources: LRCLIB (synced + plain) and Shironet (Hebrew plain text).

Parsing and matching are pure functions; fetchers are thin.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HEBREW = re.compile(r"[֐-׿]")


@dataclass(frozen=True)
class SongName:
    artist: str
    title: str
    alt_artists: tuple[str, ...] = ()
    alt_titles: tuple[str, ...] = ()

    def artists(self) -> list[str]:
        return _uniq([self.artist, *self.alt_artists])

    def titles(self) -> list[str]:
        return _uniq([self.title, *self.alt_titles])


def _uniq(items) -> list[str]:
    seen, out = set(), []
    for i in items:
        k = normalize(i)
        if i and k and k not in seen:
            seen.add(k)
            out.append(i)
    return out


@dataclass(frozen=True)
class LrclibHit:
    track: str
    artist: str
    duration: float | None
    synced: str | None
    plain: str | None


def has_hebrew(s: str) -> bool:
    return bool(HEBREW.search(s or ""))


def normalize(s: str) -> str:
    """Lowercase, strip niqqud/punctuation, and drop Hebrew matres lectionis (י, ו) so that
    spelling variants such as מליון / מיליון compare equal."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"[יו]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


_NOISE = re.compile(
    r"\((?:[^)]*)\)|\[(?:[^\]]*)\]|official\s*(?:music\s*)?(?:video|audio|lyric video)|lyrics?|"
    r"קליפ(?: רשמי)?|מילים|prod\.?.*$|\bhd\b|\b4k\b",
    re.I,
)


def _clean_title(part: str) -> str:
    part = _NOISE.sub(" ", part)
    part = re.split(r"\s(?:מארח(?:ת|ים)? את|feat\.?|ft\.?|featuring|x)\s", part, flags=re.I)[0]
    return re.sub(r"\s+", " ", part).strip(" -")


def song_name_from_youtube(title: str, channel: str, track: str | None = None, artist: str | None = None) -> SongName:
    """Best guess of artist/title from YouTube metadata, plus aliases (English names of Hebrew
    songs, the channel name, the part after '|') that lyrics databases may file the song under."""
    channel_artist = re.sub(r"\s*-\s*topic$", "", channel or "", flags=re.I).strip()
    head, _, tail = title.partition("|")
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", head) if p.strip()]
    if len(parts) >= 2:
        a, rest, extra = parts[0], parts[1], parts[2:]
    else:
        a, rest, extra = channel_artist, parts[0] if parts else head, []
    cleaned = _clean_title(rest)
    alt_titles = [_clean_title(x) for x in extra]
    if has_hebrew(cleaned):  # "מיליון דולר Million Dollar" -> both
        m = re.search(r"\s([A-Za-z][A-Za-z' ]+)$", cleaned)
        if m:
            alt_titles.append(m.group(1).strip())
            cleaned = cleaned[: m.start()].strip()
    if "&" in cleaned:  # medley: "song A & song B" -> try each song too
        alt_titles += [x.strip() for x in cleaned.split("&") if x.strip()]
    alt_artists = [channel_artist, tail.strip()]
    if track and artist:
        alt_titles.insert(0, cleaned)
        alt_artists.insert(0, a)
        a, cleaned = artist.strip(), track.strip()
    return SongName(a.strip(), cleaned, tuple(x for x in _uniq(alt_artists) if x), tuple(x for x in _uniq(alt_titles) if x))


# ---------- LRCLIB ----------

def parse_lrclib(items: list[dict]) -> list[LrclibHit]:
    return [
        LrclibHit(
            track=i.get("trackName") or "",
            artist=i.get("artistName") or "",
            duration=i.get("duration"),
            synced=i.get("syncedLyrics") or None,
            plain=i.get("plainLyrics") or None,
        )
        for i in items
        if not i.get("instrumental")
    ]


def choose_lrclib(hits: list[LrclibHit], name: SongName, duration: float | None, tol: float = 2.0):
    """Return (synced_hit, plain_hit). Both need a matching title and artist (any alias);
    synced_hit also needs its duration within tol of the audio (D6)."""

    def artist_sim(h):
        return max(similarity(h.artist, a) for a in name.artists())

    relevant = [
        h for h in hits if max(similarity(h.track, t) for t in name.titles()) >= 0.6 and artist_sim(h) >= 0.5
    ]
    synced = [h for h in relevant if h.synced and duration and h.duration and abs(h.duration - duration) <= tol]
    synced.sort(key=lambda h: (abs(h.duration - duration), -artist_sim(h)))
    plain = [h for h in relevant if h.plain]
    plain.sort(key=lambda h: (-artist_sim(h), abs((h.duration or 0) - (duration or 0))))
    return (synced[0] if synced else None), (plain[0] if plain else None)


def lrclib_queries(name: SongName, limit: int = 6) -> list[dict]:
    """Query params to try, primary name first, then aliases (English title, channel artist)."""
    out = []
    for t in name.titles():
        for a in name.artists():
            out.append({"track_name": t, "artist_name": a})
    out += [{"q": f"{a} {t}"} for t in name.titles() for a in name.artists()[:1]]
    return out[:limit]


def get_with_retry(client, url: str, tries: int = 3, wait: float = 1.0, sleep=None, **kw):
    """GET that retries transport errors (dropped connections, timeouts) with growing waits.
    LRCLIB sometimes disconnects without a response; one blip must not cost a song its lyrics."""
    import time

    import httpx

    sleep = sleep or time.sleep
    for attempt in range(tries):
        try:
            return client.get(url, **kw)
        except httpx.TransportError:
            if attempt == tries - 1:
                raise
            sleep(wait * (attempt + 1))


def fetch_lrclib(name: SongName, duration: float | None = None) -> list[LrclibHit]:
    """Collect hits across aliases; stop once a synced hit fits the duration."""
    import httpx

    from .tls import use_system_trust

    use_system_trust()

    hits: list[LrclibHit] = []
    with httpx.Client(timeout=20, headers={"User-Agent": "home-karaoke/0.1"}) as c:
        for params in lrclib_queries(name):
            r = get_with_retry(c, "https://lrclib.net/api/search", params=params)
            if r.status_code == 200:
                hits += parse_lrclib(r.json())
            synced, _ = choose_lrclib(hits, name, duration)
            if synced:
                break
    return hits


# ---------- Shironet ----------

@dataclass(frozen=True)
class ShironetResult:
    title: str
    artist: str
    href: str


def parse_shironet_search(html: str) -> list[ShironetResult]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for td in soup.find_all("td"):
        links = td.find_all("a", class_="search_link_name_big", recursive=False)
        if len(links) == 2 and "wrkid" in links[0].get("href", ""):
            out.append(
                ShironetResult(
                    title=links[0].get_text(" ", strip=True),
                    artist=links[1].get_text(" ", strip=True),
                    href=links[0]["href"],
                )
            )
    return out


def parse_shironet_lyrics(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(".artist_lyrics_text")
    if not el:
        return None
    text = el.get_text("\n", strip=True)
    return text or None


def choose_shironet(results: list[ShironetResult], name: SongName) -> ShironetResult | None:
    def ts(r):
        return max(similarity(r.title, t) for t in name.titles())

    def as_(r):
        return max(similarity(r.artist, a) for a in name.artists())

    scored = [(ts(r) + as_(r), r) for r in results if ts(r) >= 0.7 and as_(r) >= 0.6]
    return max(scored, key=lambda x: x[0])[1] if scored else None


def parse_shironet_artists(html: str) -> list[tuple[str, str]]:
    """[(artist name, prfid)] from a Shironet search page, in page order, unique."""
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a.search_link_name_big"):
        m = re.fullmatch(r"/artist\?lang=1&prfid=(\d+)", a.get("href", ""))
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append((a.get_text(" ", strip=True), m.group(1)))
    return out


def parse_shironet_works(html: str) -> tuple[list[ShironetResult], list[str]]:
    """(songs on an artist's works page, links to further pages)."""
    soup = BeautifulSoup(html, "html.parser")
    songs = [
        ShironetResult(a.get_text(" ", strip=True), "", a["href"])
        for a in soup.select("a.artist_player_songlist")
        if "wrkid=" in a.get("href", "")
    ]
    hrefs = {a["href"] for a in soup.select('a[href*="type=works&page="]')}
    pages = sorted(hrefs, key=lambda h: int(re.search(r"page=(\d+)", h).group(1)))
    return songs, pages


def pick_artist(artists: list[tuple[str, str]], name: SongName) -> str | None:
    """prfid of the best-matching artist (≥0.8 similarity to any alias)."""
    best = max(
        ((max(similarity(n, a) for a in name.artists()), pid) for n, pid in artists),
        default=(0.0, None),
    )
    return best[1] if best[0] >= 0.8 else None


def pick_work(songs: list[ShironetResult], name: SongName) -> ShironetResult | None:
    scored = [(max(similarity(s.title, t) for t in name.titles()), s) for s in songs]
    best = max(scored, key=lambda x: x[0], default=(0.0, None))
    return best[1] if best[0] >= 0.8 else None


def fetch_shironet(name: SongName) -> str | None:
    import httpx

    from .tls import use_system_trust

    use_system_trust()

    base = "https://shironet.mako.co.il"
    headers = {"User-Agent": UA, "Accept": "text/html", "Accept-Language": "he,en;q=0.8"}
    with httpx.Client(timeout=20, headers=headers, follow_redirects=True) as c:
        for q in (f"{name.artist} {name.title}", name.title):
            r = c.get(f"{base}/search", params={"q": q})
            if r.status_code != 200:
                continue
            hit = choose_shironet(parse_shironet_search(r.text), name)
            if hit:
                page = c.get(base + hit.href)
                return parse_shironet_lyrics(page.text) if page.status_code == 200 else None
        # Search is loose full-text; fall back to the artist's own song list.
        r = c.get(f"{base}/search", params={"q": name.artist})
        prfid = pick_artist(parse_shironet_artists(r.text), name) if r.status_code == 200 else None
        if not prfid:
            return None
        url, seen = f"{base}/artist?type=works&lang=1&prfid={prfid}", set()
        for _ in range(15):  # at most 15 pages (~45 songs each)
            seen.add(url)
            page = c.get(url)
            if page.status_code != 200:
                return None
            songs, pages = parse_shironet_works(page.text)
            work = pick_work(songs, name)
            if work:
                lyr = c.get(base + work.href)
                return parse_shironet_lyrics(lyr.text) if lyr.status_code == 200 else None
            nxt = [base + p for p in pages if base + p not in seen]
            if not nxt:
                return None
            url = nxt[0]
    return None
