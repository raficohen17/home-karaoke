"""Lyrics waterfall: synced (LRCLIB, offset-corrected) -> aligned text -> transcribed -> teleprompter/none."""
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
ALIGNED_LEAD = 0.0  # anchored word times already run ~0.28s early vs hand-synced LRC (vampire, D-lyrics-engine-3)


@dataclass
class LyricsResult:
    mode: str  # synced | aligned | transcribed | teleprompter | none
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


MIN_COVERAGE = 0.35  # share of words anchored in order needed to trust an alignment (D-lyrics-engine-6)


def decide_alignment(coverage: float | None, error: bool) -> str:
    """Mode after an alignment attempt: 'aligned', or 'fallback' (try transcription, then teleprompter).

    Gated on anchor coverage, not mean probability: a live recording with talking between verses
    has a low mean even where the singing aligns well, and a mean can look fine while the aligner
    has lost the song after its first minute.
    """
    if error or coverage is None or coverage < MIN_COVERAGE:
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
    from . import align

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
            res.mode, res.lines, res.source, res.offset = "synced", lines, "lrclib", off
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
            words, prob = _with_timeout(align.align_words, ALIGN_TIMEOUT, vocals_path, "\n".join(lines_text), language)
            err = False
        except Exception as e:
            log.warning("alignment failed: %s", e)
            words, prob, err = [], None, True
        res.align_prob = prob
        res.source = src
        stats: dict = {}
        lines = timed_lines(lines_text, words, stats) if not err else []
        res.align_coverage = stats.get("coverage")
        if decide_alignment(res.align_coverage, err) == "aligned":
            res.mode, res.lines = "aligned", lines
            return res
        log.info("alignment coverage %.2f too low; transcribing instead", res.align_coverage or 0)
        if transcribe_into(res, vocals_path, language):
            return res
        res.mode, res.text, res.source = "teleprompter", "\n".join(lines_text), src
        return res

    transcribe_into(res, vocals_path, language)
    return res


def transcribe_into(res: LyricsResult, vocals_path: Path, language: str) -> bool:
    """Fill res with Whisper's transcription of the vocals (per-word times); False if it fails."""
    from . import align

    try:
        lines = _with_timeout(align.transcribe_lines, ALIGN_TIMEOUT * 2, vocals_path, language)
    except Exception as e:
        log.warning("transcription failed: %s", e)
        return False
    if not lines:
        return False
    res.mode, res.lines, res.source = "transcribed", lines, "whisper"
    return True


def timed_lines(lines_text: list[str], words: list[tuple[float, str, float]], stats: dict | None = None) -> list[Line]:
    """Per-word times anchored on confident words (D-lyrics-engine-6); line-level mapping when
    fewer than two words are confident. Shifted by ALIGNED_LEAD."""
    lines = lrc.anchor_words(lines_text, words, stats=stats)
    if not lines:
        lines = lrc.map_words_to_lines(lines_text, [(t, w) for t, w, _ in words])
    return lrc.shift(lines, -ALIGNED_LEAD)


def classify_pasted(text: str) -> str:
    """'lrc' when the paste is timestamped (3+ timed lines), else 'text'."""
    return "lrc" if len([line for line in lrc.parse_lrc(text) if line.text]) >= 3 else "text"


def lyrics_from_paste(text: str, vocals_path: Path, language: str | None = None) -> LyricsResult:
    """Lyrics a guest pasted: LRC is offset-corrected (D6), plain text is aligned to the vocals."""
    from . import align

    act = vocals.load_activity(vocals_path)
    v_start, v_end = vocals.onsets(act)
    language = language or guess_language(text) or "en"
    res = LyricsResult(mode="none", vocal_start=v_start, vocal_end=v_end, language=language, source="pasted")
    if classify_pasted(text) == "lrc":
        res.lines, res.offset = correct_synced(lrc.parse_lrc(text), act, vocals.HOP)
        res.mode = "synced"
        return res
    lines_text = lrc.plain_lines(text)
    if not lines_text:
        return res
    try:
        words, prob, err = *_with_timeout(align.align_words, ALIGN_TIMEOUT, vocals_path, "\n".join(lines_text), language), False
    except Exception as e:
        log.warning("alignment of pasted lyrics failed: %s", e)
        words, prob, err = [], None, True
    res.align_prob = prob
    stats: dict = {}
    lines = timed_lines(lines_text, words, stats) if not err else []
    res.align_coverage = stats.get("coverage")
    if decide_alignment(res.align_coverage, err) == "aligned":
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
