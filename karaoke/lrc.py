"""LRC parsing/formatting and timing helpers (pure functions)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_TAG = re.compile(r"\[(\d+):(\d{1,2}(?:[.:]\d{1,3})?)\]")
_WTAG = re.compile(r"<(\d+):(\d{1,2}(?:[.:]\d{1,3})?)>")
_META = re.compile(r"^\[[a-z]+:.*\]$", re.I)


@dataclass(frozen=True)
class Line:
    t: float
    text: str
    words: tuple[tuple[float, str], ...] = ()  # (start, word) per word; empty when only the line is timed


def _secs(m: re.Match) -> float:
    return int(m.group(1)) * 60 + float(m.group(2).replace(":", "."))


def _parse_words(body: str) -> tuple[str, tuple[tuple[float, str], ...]]:
    """Enhanced LRC body "<00:01.00>one <00:01.50>two" -> ("one two", ((1.0, "one"), (1.5, "two")))."""
    marks = list(_WTAG.finditer(body))
    if not marks:
        return body.strip(), ()
    words = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        w = body[m.end():end].strip()
        if w:
            words.append((_secs(m), w))
    return " ".join(w for _, w in words), tuple(words)


def parse_lrc(text: str) -> list[Line]:
    """Parse LRC into time-sorted lines. Lines with several tags repeat; metadata is skipped."""
    out: list[Line] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or (_META.match(raw) and not _TAG.match(raw)):
            continue
        tags = list(_TAG.finditer(raw))
        if not tags:
            continue
        lyric, words = _parse_words(_TAG.sub("", raw))
        for m in tags:
            out.append(Line(_secs(m), lyric, words if len(tags) == 1 else ()))
    out.sort(key=lambda line: line.t)
    return out


def format_time(t: float) -> str:
    t = max(0.0, t)
    m = int(t // 60)
    s = t - m * 60
    return f"{m:02d}:{s:05.2f}"


def format_lrc(lines: list[Line]) -> str:
    """LRC; lines with word times use the enhanced form "[mm:ss.xx]<mm:ss.xx>word <mm:ss.xx>word"."""
    out = []
    for line in lines:
        body = " ".join(f"<{format_time(t)}>{w}" for t, w in line.words) if line.words else line.text
        out.append(f"[{format_time(line.t)}]{body}")
    return "\n".join(out) + "\n"


def shift(lines: list[Line], offset: float) -> list[Line]:
    return [
        Line(max(0.0, line.t + offset), line.text, tuple((max(0.0, t + offset), w) for t, w in line.words))
        for line in lines
    ]


_LABEL = re.compile(
    r"(?:pre-?chorus|chorus|verse|bridge|intro|outro|hook|refrain|interlude|instrumental|"
    r"פזמון|בית|גשר|פתיחה|סיום)[\s\d:.-]*(?:x\s*\d+)?|x\s*\d+|\d+\s*x",
    re.I,
)


_HEADER = re.compile(
    r"(?:pre-?chorus|chorus|verse|bridge|intro|outro|hook|refrain|פזמון|בית|גשר|פתיחה|סיום|מעבר)"
    r"(?:\s*[\dא-ת]['׳]?)?\s*(?:x\s*\d+|\d+\s*x)?\s*:",
    re.I,
)


def plain_lines(text: str) -> list[str]:
    """Non-empty lyric lines from plain text. Drops [anything] and (section labels) such as
    (Chorus) or (x2), but keeps sung parentheticals like "(מיליון דולר)"."""
    out = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or re.fullmatch(r"\[.*\]", s):
            continue
        m = re.fullmatch(r"\((.*)\)", s)
        if m and _LABEL.fullmatch(m.group(1).strip()):
            continue
        if _HEADER.fullmatch(s):  # Shironet-style "בית א:", "פזמון:", "Chorus:"
            continue
        out.append(s)
    return out


_WORDCHAR = re.compile(r"\w")


def map_words_to_lines(lines: list[str], words: list[tuple[float, str]]) -> list[Line]:
    """Give each lyric line the start time of the first aligned word inside it.

    Words are located by character position in the joined text, not by counting tokens: the
    aligner may merge or split tokens (e.g. "-" + "נושכת" -> "- נושכת"), and counting tokens
    then shifts every later line onto the wrong word. Punctuation-only words are skipped, a word is
    placed at its first letter, and lines with no aligned word are dropped.
    """
    text = "\n".join(lines)
    spans, pos = [], 0
    for line in lines:
        spans.append((pos, pos + len(line)))
        pos += len(line) + 1
    starts: list[tuple[int, float]] = []  # (char index of the word's first letter, time)
    cursor = 0
    for t, w in words:
        w = w.strip()
        m = _WORDCHAR.search(w)
        if not m:
            continue  # punctuation only
        core = w[m.start():]
        idx = text.find(core, cursor)
        if idx < 0:  # aligner normalised the word differently; try its first letter-run
            first = re.match(r"\w+", core).group(0)
            idx = text.find(first, cursor)
            if idx < 0:
                continue
        starts.append((idx, t))
        cursor = idx + 1
    out: list[Line] = []
    k = 0
    for (lo, hi), line in zip(spans, lines):
        while k < len(starts) and starts[k][0] < lo:
            k += 1
        if k < len(starts) and starts[k][0] < hi:
            out.append(Line(starts[k][1], line))
    return out


ANCHOR_PROB = 0.5  # aligner word probability at or above which a word is trusted as an anchor


def anchor_words(
    lines: list[str], words: list[tuple[float, str, float]], min_prob: float = ANCHOR_PROB,
    stats: dict | None = None,
) -> list[Line]:
    """Time every word of every line from the aligner's words (start, text, probability).

    Confident words that keep moving forward in time are anchors. Every other word, including
    whole lines the aligner got nothing confident for, is placed by its character position
    between the anchors around it, so a few badly aligned words can't drag a line off.
    Each line starts at its first word. Lines are returned for every input line when there are
    at least two anchors; with fewer, nothing can be anchored and an empty list is returned.
    """
    text = "\n".join(lines)
    tokens, tok_time, tok_prob = _token_times(text, words)
    if not tokens:
        if stats is not None:
            stats.update(anchors=0, tokens=0, coverage=0.0)
        return []
    anchors = monotonic_anchors(
        [(tokens[i][0], tok_time[i]) for i in range(len(tokens)) if tok_time[i] is not None and tok_prob[i] >= min_prob]
    )
    if stats is not None:  # share of the lyrics' words anchored in order (the alignment quality gate)
        stats.update(anchors=len(anchors), tokens=len(tokens), coverage=len(anchors) / len(tokens))
    if len(anchors) < 2:
        return []
    times = [interpolate(anchors, lo) for lo, _, _ in tokens]
    out, ti, pos = [], 0, 0
    for line in lines:
        hi = pos + len(line)
        ws = []
        while ti < len(tokens) and tokens[ti][0] < hi:
            ws.append((round(times[ti], 2), tokens[ti][2]))
            ti += 1
        if ws:
            out.append(Line(ws[0][0], line, tuple(ws)))
        pos = hi + 1
    return out



def _locate(text: str, words: list[tuple[float, str, float]]) -> list[tuple[int, float, float]]:
    """(char index of the word's first letter, time, probability) for each aligner word found in
    text, searching forward only. Punctuation-only words are skipped (same rule as map_words_to_lines)."""
    located: list[tuple[int, float, float]] = []
    cursor = 0
    for t, w, p in words:
        w = w.strip()
        m = _WORDCHAR.search(w)
        if not m:
            continue
        core = w[m.start():]
        idx = text.find(core, cursor)
        if idx < 0:
            first = re.match(r"\w+", core).group(0)
            idx = text.find(first, cursor)
            if idx < 0:
                continue
        located.append((idx, t, p))
        cursor = idx + 1
    return located


def _token_times(text: str, words: list[tuple[float, str, float]]):
    """Whitespace tokens of text with the time of the first aligner word inside each (or None)
    and the best probability among them."""
    tokens = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\S+", text)]
    located = _locate(text, words)
    tok_time: list[float | None] = [None] * len(tokens)
    tok_prob = [0.0] * len(tokens)
    j = 0
    for i, (lo, hi, _) in enumerate(tokens):
        while j < len(located) and located[j][0] < lo:
            j += 1
        k = j
        while k < len(located) and located[k][0] < hi:
            if tok_time[i] is None:
                tok_time[i] = located[k][1]
            tok_prob[i] = max(tok_prob[i], located[k][2])
            k += 1
    return tokens, tok_time, tok_prob


SYNCED_MIN_COVERAGE = 0.35  # share of words aligned inside their own line needed to add word times
DEFAULT_SEC_PER_CHAR = 0.07  # used when no line has two anchors to measure the singing rate from


def words_in_synced(
    lines: list[Line], words: list[tuple[float, str, float]], min_prob: float = ANCHOR_PROB,
    min_coverage: float = SYNCED_MIN_COVERAGE, stats: dict | None = None,
) -> list[Line]:
    """Add per-word times to synced lyrics, keeping every line's start time.

    Synced line starts are trusted (hand-made). Each line's first word starts at its line start;
    other confident aligner words become anchors only inside their own line's window (line start to
    next line start), so a word the aligner placed in another line can't pull it. Words between
    anchors are interpolated by character position; words after a line's last anchor run on at the
    singing rate and are squeezed to finish before the next line. When too few words align inside
    their lines (coverage below min_coverage) the lines are returned unchanged.
    """
    text = "\n".join(line.text for line in lines)
    tokens, tok_time, tok_prob = _token_times(text, words)
    spans, pos = [], 0
    for line in lines:
        spans.append((pos, pos + len(line.text)))
        pos += len(line.text) + 1
    per_line: list[tuple[list[int], list[tuple[int, float]], float]] = []  # (token ids, chain, window end)
    confident, ti = 0, 0
    for i, ((lo, hi), line) in enumerate(zip(spans, lines)):
        ids = []
        while ti < len(tokens) and tokens[ti][0] < hi:
            ids.append(ti)
            ti += 1
        later = [x.t for x in lines[i + 1:] if x.t > line.t]
        end = later[0] if later else line.t + 10.0
        if not ids:
            per_line.append((ids, [], end))
            continue
        good = [k for k in ids if tok_time[k] is not None and tok_prob[k] >= min_prob and line.t - 0.5 <= tok_time[k] < end]
        confident += sum(1 for k in good if k == ids[0])
        start = (tokens[ids[0]][0], line.t)
        chain = monotonic_anchors([start] + [(tokens[k][0], tok_time[k]) for k in good if k != ids[0]])
        if chain[0] != start:
            chain = [start] + [c for c in chain if c[1] >= line.t + 0.05]
        confident += len(chain) - 1
        per_line.append((ids, chain, end))
    coverage = confident / len(tokens) if tokens else 0.0
    if stats is not None:
        stats.update(tokens=len(tokens), anchors=confident, coverage=coverage)
    if coverage < min_coverage:
        return list(lines)
    rates = sorted(
        (c[-1][1] - c[0][1]) / (c[-1][0] - c[0][0]) for _, c, _ in per_line if len(c) >= 2 and c[-1][0] > c[0][0]
    )
    global_rate = rates[len(rates) // 2] if rates else DEFAULT_SEC_PER_CHAR
    out = []
    for (ids, chain, end), line in zip(per_line, lines):
        if not ids:
            out.append(line)
            continue
        out.append(Line(line.t, line.text, tuple(zip(_line_word_times([tokens[k][0] for k in ids], chain, end, global_rate),
                                                     (tokens[k][2] for k in ids)))))
    return out


def _line_word_times(positions: list[int], chain: list[tuple[int, float]], end: float, global_rate: float) -> list[float]:
    """Word times for one synced line: interpolated inside the anchor chain, extrapolated after its
    last anchor at the line's own rate (or the song's), squeezed to end 0.15s before `end`."""
    last_c, last_t = chain[-1]
    rate = (last_t - chain[0][1]) / (last_c - chain[0][0]) if len(chain) >= 2 and last_c > chain[0][0] else global_rate
    cap = max(last_t, end - 0.15)
    tail = [p for p in positions if p > last_c]
    over = last_t + (tail[-1] - last_c) * rate if tail else last_t
    scale = (cap - last_t) / (over - last_t) if over > cap and over > last_t else 1.0
    times, prev = [], chain[0][1]
    for p in positions:
        t = interpolate(chain, p) if p <= last_c else last_t + (p - last_c) * rate * scale
        prev = max(prev, t)
        times.append(round(prev, 2))
    return times


def monotonic_anchors(points: list[tuple[int, float]], min_gap: float = 0.05) -> list[tuple[int, float]]:
    """Longest run of (char, time) points whose times increase with position (drops outliers that
    jump backwards or far ahead), keeping at least min_gap seconds between consecutive anchors.
    Between equally long runs, the one that ends later in the text wins."""
    n = len(points)
    if n == 0:
        return []
    best = [1] * n
    prev = [-1] * n
    for i in range(n):
        for k in range(i):
            if points[i][1] >= points[k][1] + min_gap and best[k] + 1 > best[i]:
                best[i], prev[i] = best[k] + 1, k
    i = max(range(n), key=lambda x: (best[x], points[x][0]))  # tie: the chain reaching further into the text
    chain = []
    while i >= 0:
        chain.append(points[i])
        i = prev[i]
    return chain[::-1]


def interpolate(anchors: list[tuple[int, float]], pos: int) -> float:
    """Time at character `pos`, linear between the anchors around it; outside them, extrapolated at
    the song's average seconds per character."""
    (c0, t0), (c1, t1) = anchors[0], anchors[-1]
    rate = (t1 - t0) / (c1 - c0) if c1 > c0 else 0.0
    if pos <= c0:
        return max(0.0, t0 - (c0 - pos) * rate)
    if pos >= c1:
        return t1 + (pos - c1) * rate
    lo, hi = 0, len(anchors) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if anchors[mid][0] <= pos:
            lo = mid
        else:
            hi = mid
    (a, ta), (b, tb) = anchors[lo], anchors[hi]
    return ta + (tb - ta) * (pos - a) / (b - a) if b > a else ta


def best_offset(
    line_times: list[float],
    activity: list[float],
    hop: float,
    search: float = 30.0,
    hold: float = 3.0,
) -> float:
    """Shift (seconds) that best lines lyric intervals up with vocal activity (D6).

    activity[k] is 1 when vocals are present at time k*hop. Each lyric line is treated as
    vocal for `hold` seconds (or until the next line). Returns the shift in [-search, search]
    maximising overlap minus a penalty for lyrics placed over silence.
    """
    import numpy as np

    act = np.asarray(activity, dtype=float)
    if not line_times or act.size == 0:
        return 0.0
    n = act.size
    starts = np.asarray(line_times)
    ends = np.minimum(np.append(starts[1:], starts[-1] + hold), starts + hold)
    best, best_score = 0.0, -np.inf
    steps = int(search / hop)
    for k in range(-steps, steps + 1):
        off = k * hop
        mask = np.zeros(n)
        for s, e in zip(starts + off, ends + off):
            a, b = int(max(0, s) / hop), int(max(0, e) / hop)
            if b > 0 and a < n:
                mask[a:min(b, n)] = 1
        score = float((mask * act).sum() - 0.5 * (mask * (1 - act)).sum())
        if score > best_score + 1e-9 or (abs(score - best_score) <= 1e-9 and abs(off) < abs(best)):
            best, best_score = off, score
    return round(best, 2)
