"""LRC parsing/formatting and timing helpers (pure functions)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_TAG = re.compile(r"\[(\d+):(\d{1,2}(?:[.:]\d{1,3})?)\]")
_META = re.compile(r"^\[[a-z]+:.*\]$", re.I)


@dataclass(frozen=True)
class Line:
    t: float
    text: str


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
        lyric = _TAG.sub("", raw).strip()
        for m in tags:
            sec = float(m.group(2).replace(":", "."))
            out.append(Line(int(m.group(1)) * 60 + sec, lyric))
    out.sort(key=lambda line: line.t)
    return out


def format_time(t: float) -> str:
    t = max(0.0, t)
    m = int(t // 60)
    s = t - m * 60
    return f"{m:02d}:{s:05.2f}"


def format_lrc(lines: list[Line]) -> str:
    return "\n".join(f"[{format_time(line.t)}]{line.text}" for line in lines) + "\n"


def shift(lines: list[Line], offset: float) -> list[Line]:
    return [Line(max(0.0, line.t + offset), line.text) for line in lines]


def plain_lines(text: str) -> list[str]:
    """Non-empty lyric lines from plain text, without section labels like [Chorus]."""
    out = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or re.fullmatch(r"[\[(].*[\])]", s):
            continue
        out.append(s)
    return out


def map_words_to_lines(lines: list[str], words: list[tuple[float, str]]) -> list[Line]:
    """Assign aligned words (start, text) to lyric lines in order; a line starts at its first word.

    Words are consumed by matching each line's whitespace-token count, which holds because the
    aligner returns the same tokens it was given. Lines left without words are dropped.
    """
    out: list[Line] = []
    i = 0
    for text in lines:
        n = len(text.split())
        chunk = words[i : i + n]
        i += n
        if chunk:
            out.append(Line(chunk[0][0], text))
    return out


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
