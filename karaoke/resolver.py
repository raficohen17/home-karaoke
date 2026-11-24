"""Resolve a YouTube URL, Spotify track URL or free-text query to a YouTube video id.

Pure functions (parsing, scoring) are separate from network calls so they can be tested.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


@dataclass(frozen=True)
class Candidate:
    video_id: str
    title: str
    channel: str
    duration: float | None
    view_count: int | None = None
    thumbnail: str | None = None

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "channel": self.channel,
            "duration": self.duration,
            "thumbnail": self.thumbnail or f"https://i.ytimg.com/vi/{self.video_id}/mqdefault.jpg",
        }


@dataclass(frozen=True)
class TrackInfo:
    title: str
    artist: str
    duration: float | None


class NoMatch(Exception):
    """No YouTube candidate is close enough to the requested track."""


def classify_input(text: str) -> str:
    """Return 'youtube', 'spotify' or 'query'."""
    t = text.strip()
    if youtube_video_id(t):
        return "youtube"
    if spotify_track_id(t):
        return "spotify"
    return "query"


def youtube_video_id(url: str) -> str | None:
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if host in ("youtu.be", "www.youtu.be"):
        vid = u.path.lstrip("/").split("/")[0]
        return vid if _YT_ID.match(vid) else None
    if host in _YT_HOSTS:
        if u.path == "/watch":
            vid = parse_qs(u.query).get("v", [""])[0]
            return vid if _YT_ID.match(vid) else None
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
            return parts[1] if _YT_ID.match(parts[1]) else None
    return None


def spotify_track_id(url: str) -> str | None:
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    if (u.hostname or "").lower() != "open.spotify.com":
        return None
    parts = [p for p in u.path.split("/") if p]
    if parts and parts[0].startswith("intl-"):
        parts = parts[1:]
    if len(parts) >= 2 and parts[0] == "track" and re.match(r"^[A-Za-z0-9]{22}$", parts[1]):
        return parts[1]
    return None


def parse_spotify_page(html: str) -> TrackInfo:
    """Read title/artist/duration from a Spotify track page's Open Graph tags (D5)."""
    soup = BeautifulSoup(html, "html.parser")

    def meta(prop: str) -> str | None:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return tag.get("content") if tag else None

    title = meta("og:title") or ""
    desc = meta("og:description") or ""
    # og:description looks like "Artist · Album · Song · 2023"
    artist = desc.split("·")[0].strip() if "·" in desc else ""
    if not artist:
        artist = (meta("music:musician_description") or "").strip()
    dur = meta("music:duration")
    duration = float(dur) if dur and dur.replace(".", "", 1).isdigit() else None
    if not title:
        raise ValueError("Spotify page has no og:title")
    return TrackInfo(title=title.strip(), artist=artist, duration=duration)


_GOOD_HINTS = ("official audio", "audio", "- topic")
_BAD_HINTS = ("live", "cover", "karaoke", "instrumental", "remix", "sped up", "slowed", "8d", "reaction")


def score_candidate(c: Candidate, want_duration: float | None) -> float:
    """Higher is better. Duration match dominates, then upload type, then popularity."""
    s = 0.0
    text = f"{c.title} {c.channel}".lower()
    if want_duration and c.duration:
        diff = abs(c.duration - want_duration)
        s += max(0.0, 100.0 - diff * 10.0)
    if any(h in text for h in _GOOD_HINTS):
        s += 15
    if any(h in text for h in _BAD_HINTS):
        s -= 40
    if c.view_count:
        s += min(10.0, len(str(c.view_count)))  # ~log10 of views
    return s


def pick_candidate(cands: list[Candidate], want_duration: float | None, max_diff: float = 10.0) -> Candidate:
    """Pick the best candidate; raise NoMatch when no duration is within max_diff."""
    if not cands:
        raise NoMatch("no search results")
    pool = cands
    if want_duration:
        pool = [c for c in cands if c.duration and abs(c.duration - want_duration) <= max_diff]
        if not pool:
            raise NoMatch(f"no result within {max_diff:.0f}s of {want_duration:.0f}s")
    return max(pool, key=lambda c: score_candidate(c, want_duration))


# ---------- network ----------

def search_youtube(query: str, n: int = 5) -> list[Candidate]:
    import yt_dlp

    from .tls import use_system_trust

    use_system_trust()
    with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True, "skip_download": True}) as y:
        info = y.extract_info(f"ytsearch{n}:{query}", download=False)
    out = []
    for e in info.get("entries") or []:
        if not e or not e.get("id"):
            continue
        thumbs = e.get("thumbnails") or []
        out.append(
            Candidate(
                video_id=e["id"],
                title=e.get("title") or "",
                channel=e.get("channel") or e.get("uploader") or "",
                duration=e.get("duration"),
                view_count=e.get("view_count"),
                thumbnail=thumbs[-1]["url"] if thumbs else None,
            )
        )
    return out


def fetch_spotify_track(url: str) -> TrackInfo:
    import httpx

    from .tls import use_system_trust

    use_system_trust()
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=20)
    r.raise_for_status()
    return parse_spotify_page(r.text)


def resolve(text: str) -> str:
    """Resolve any input to a video id; free text takes the best-scored search hit."""
    kind = classify_input(text)
    if kind == "youtube":
        return youtube_video_id(text)  # type: ignore[return-value]
    if kind == "spotify":
        t = fetch_spotify_track(text)
        cands = search_youtube(f"{t.artist} - {t.title}".strip(" -"), n=5)
        return pick_candidate(cands, t.duration, max_diff=10.0).video_id
    cands = search_youtube(text, n=5)
    return pick_candidate(cands, None).video_id
