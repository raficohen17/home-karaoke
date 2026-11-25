"""Lyrics waterfall: synced (LRCLIB, offset-corrected) -> aligned text -> teleprompter -> none.

There is no transcription: a song with no lyrics found waits for a guest to paste them (D-lyrics-engine-9)."""
from __future__ import annotations

import concurrent.futures as cf
import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import lrc, sources, vocals
from .lrc import Line

log = logging.getLogger(__name__)

ALIGN_TIMEOUT = 300.0
MAX_OFFSET = 30.0
ALIGNED_LEAD = 0.0  # CTC word times are centred on hand-synced LRC (median signed error within ±0.13s, D-lyrics-engine-10)


@dataclass
class LyricsResult:
    mode: str  # synced | aligned | teleprompter | none
    lines: list[Line] = field(default_factory=list)
    text: str | None = None
    source: str | None = None
    offset: float = 0.0
    align_prob: float | None = None
    align_coverage: float | None = None
    vocal_start: float | None = None
    vocal_end: float | None = None
    language: str = "en"
    artist: str = ""
    title: str = ""


def guess_language(*texts: str) -> str | None:
    """'he' if any metadata has Hebrew letters; None means 'detect from audio'."""
    return "he" if any(sources.has_hebrew(t or "") for t in texts) else None


# Mean CTC confidence needed to trust an alignment of plain text (D-lyrics-engine-10). Measured
# 2026-11-25: right lyrics English 0.10-0.27, Hebrew 0.39-0.75; wrong song's lyrics English
# 0.04-0.09, Hebrew 0.24. Hebrew's adapter is surer of itself, so it needs its own bar.
MIN_CONFIDENCE = {"en": 0.10, "he": 0.33}
ANCHOR_PROB = 0.0  # every CTC word is an anchor: its times are monotonic and exact enough (D-lyrics-engine-10)


def decide_alignment(confidence: float | None, language: str, error: bool) -> str:
    """Mode after an alignment attempt: 'aligned', or 'fallback' (show the text as a teleprompter).

    A forced aligner always places every word, so coverage can't tell right lyrics from wrong ones;
    the mean confidence of the placed words can.
    """
    if error or confidence is None or confidence < MIN_CONFIDENCE.get(language, MIN_CONFIDENCE["en"]):
        return "fallback"
    return "aligned"


def correct_synced(lines: list[Line], activity, hop: float) -> tuple[list[Line], float]:
    off = lrc.best_offset([line.t for line in lines], list(activity), hop, search=MAX_OFFSET)
    return (lrc.shift(lines, off) if off else lines), off


def _with_timeout(fn, timeout: float, *args):
    ex = cf.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, *args)
    try:
        return fut.result(timeout=timeout)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def build_lyrics(meta: dict, vocals_path: Path, progress=None) -> LyricsResult:
    from . import align, ctc_align

    name = sources.song_name_from_youtube(meta.get("title", ""), meta.get("channel", ""), meta.get("track"), meta.get("artist"))
    act = vocals.load_activity(vocals_path)
    v_start, v_end = vocals.onsets(act)
    language = guess_language(meta.get("title", ""), meta.get("channel", ""), name.artist) or align.detect_language(vocals_path, v_start, v_end)
    res = LyricsResult(mode="none", vocal_start=v_start, vocal_end=v_end, language=language, artist=name.artist, title=name.title)
    log.info("lyrics for %s / %s (%s)", name.artist, name.title, language)

    try:
        hits = sources.fetch_lrclib(name, meta.get("duration"))
    except Exception as e:  # network trouble must not block playback
        log.warning("lrclib failed: %s", e)
        hits = []
    synced, plain = sources.choose_lrclib(hits, name, meta.get("duration"))
    if synced:
        lines, off = correct_synced(lrc.parse_lrc(synced.synced), act, vocals.HOP)
        if lines:
            res.mode, res.source, res.offset = "synced", "lrclib", off
            res.lines, res.align_coverage = add_word_times(lines, vocals_path, language)
            return res

    text, src = (plain.plain, "lrclib") if plain else (None, None)
    if not text and language == "he":
        try:
            text, src = sources.fetch_shironet(name), "shironet"
        except Exception as e:
            log.warning("shironet failed: %s", e)
    if progress:
        progress()

    if text:
        lines_text = lrc.plain_lines(text)
        try:
            words, prob = _with_timeout(ctc_align.align_words, ALIGN_TIMEOUT, vocals_path, "\n".join(lines_text), language)
            err = False
        except Exception as e:
            log.warning("alignment failed: %s", e)
            words, prob, err = [], None, True
        res.align_prob = prob
        res.source = src
        stats: dict = {}
        lines = timed_lines(lines_text, words, stats) if not err else []
        res.align_coverage = stats.get("coverage")
        if decide_alignment(prob, language, err) == "aligned":
            res.mode, res.lines = "aligned", lines
            return res
        log.info("alignment confidence %.2f too low; showing the text as a teleprompter", prob or 0)
        res.mode, res.text, res.source = "teleprompter", "\n".join(lines_text), src
        return res

    log.info("no lyrics found for %s / %s; a guest can paste them", name.artist, name.title)
    return res


def add_word_times(lines: list[Line], vocals_path: Path, language: str) -> tuple[list[Line], float | None]:
    """Synced lines plus per-word times from the aligner (D-lyrics-engine-8); line starts never move.

    Returns (lines, coverage). Lines that already carry word times (pasted enhanced LRC) are kept
    as they are; on failure or low coverage the lines come back with line times only.
    """
    from . import ctc_align

    if not lines or any(line.words for line in lines):
        return lines, None
    try:
        words, _ = _with_timeout(ctc_align.align_words, ALIGN_TIMEOUT, vocals_path, "\n".join(l.text for l in lines), language)
    except Exception as e:
        log.warning("word alignment of synced lyrics failed: %s", e)
        return lines, None
    stats: dict = {}
    out = lrc.words_in_synced(lines, words, min_prob=ANCHOR_PROB, stats=stats)
    log.info("synced word timing: coverage %.2f", stats.get("coverage", 0.0))
    return out, stats.get("coverage")


def timed_lines(lines_text: list[str], words: list[tuple[float, str, float]], stats: dict | None = None) -> list[Line]:
    """Per-word times anchored on the aligner's words (D-lyrics-engine-6, -10); line-level mapping
    when fewer than two words can be anchored. Shifted by ALIGNED_LEAD."""
    lines = lrc.anchor_words(lines_text, words, min_prob=ANCHOR_PROB, stats=stats)
    if not lines:
        lines = lrc.map_words_to_lines(lines_text, [(t, w) for t, w, _ in words])
    return lrc.shift(lines, -ALIGNED_LEAD)


def classify_pasted(text: str) -> str:
    """'lrc' when the paste is timestamped (3+ timed lines), else 'text'."""
    return "lrc" if len([line for line in lrc.parse_lrc(text) if line.text]) >= 3 else "text"


def lyrics_from_paste(text: str, vocals_path: Path, language: str | None = None) -> LyricsResult:
    """Lyrics a guest pasted: LRC is offset-corrected (D6), plain text is aligned to the vocals."""
    from . import ctc_align

    act = vocals.load_activity(vocals_path)
    v_start, v_end = vocals.onsets(act)
    language = language or guess_language(text) or "en"
    res = LyricsResult(mode="none", vocal_start=v_start, vocal_end=v_end, language=language, source="pasted")
    if classify_pasted(text) == "lrc":
        lines, res.offset = correct_synced(lrc.parse_lrc(text), act, vocals.HOP)
        res.lines, res.align_coverage = add_word_times(lines, vocals_path, language)
        res.mode = "synced"
        return res
    lines_text = lrc.plain_lines(text)
    if not lines_text:
        return res
    try:
        words, prob, err = *_with_timeout(ctc_align.align_words, ALIGN_TIMEOUT, vocals_path, "\n".join(lines_text), language), False
    except Exception as e:
        log.warning("alignment of pasted lyrics failed: %s", e)
        words, prob, err = [], None, True
    res.align_prob = prob
    stats: dict = {}
    lines = timed_lines(lines_text, words, stats) if not err else []
    res.align_coverage = stats.get("coverage")
    if decide_alignment(prob, language, err) == "aligned":
        res.mode, res.lines = "aligned", lines
    else:
        res.mode, res.text = "teleprompter", "\n".join(lines_text)
    return res


def write_lyrics(res: LyricsResult, song_dir: Path) -> None:
    for old in ("lyrics.lrc", "lyrics.txt"):
        (song_dir / old).unlink(missing_ok=True)
    if res.lines:
        (song_dir / "lyrics.lrc").write_text(lrc.format_lrc(res.lines), "utf-8")
    elif res.text:
        (song_dir / "lyrics.txt").write_text(res.text, "utf-8")
