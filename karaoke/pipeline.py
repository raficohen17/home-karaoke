"""Process one song: resolve -> download -> separate -> lyrics -> commit to cache."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from . import ctc_align, engine, media
from .cache import Cache

log = logging.getLogger(__name__)

StatusFn = Callable[[str, float | None], None]


def process(video_id: str, cache: Cache, status: StatusFn | None = None, mode: str = "quality") -> dict:
    """Make cache/<video_id>/ complete and return its meta. Raises on failure."""
    say = status or (lambda s, p=None: None)
    if cache.is_complete(video_id):
        say("READY", None)
        return cache.read_meta(video_id)

    timings: dict[str, float] = {}
    work = cache.begin(video_id)
    t0 = time.time()
    say("DOWNLOADING", 0.0)
    info = media.download(video_id, work, progress=lambda f: say("DOWNLOADING", f))
    timings["download"] = round(time.time() - t0, 1)

    t1 = time.time()
    say("SEPARATING", None)
    media.separate(work / "audio.wav", work, mode)
    (work / "audio.wav").unlink(missing_ok=True)
    timings["separate"] = round(time.time() - t1, 1)

    t2 = time.time()
    say("ALIGNING", None)
    res = engine.build_lyrics(info, work / "vocals.flac")
    engine.write_lyrics(res, work)
    timings["lyrics"] = round(time.time() - t2, 1)

    meta = {
        **info,
        "artist_guess": res.artist,
        "title_guess": res.title,
        "language": res.language,
        "lyrics_mode": res.mode,
        "lyrics_source": res.source,
        "lyrics_offset": res.offset,
        "align_prob": res.align_prob,
        "align_coverage": res.align_coverage,
        "word_aligner": ctc_align.NAME,
        "vocal_start": res.vocal_start,
        "vocal_end": res.vocal_end,
        "separator": mode,
        "separator_model": media.SEPARATORS[mode][0],
        "stems_version": int(time.time()),
        "timings": timings,
    }
    cache.commit(video_id, meta)
    log.info("%s ready in %.0fs: %s", video_id, time.time() - t0, timings)
    say("READY", None)
    return meta


def replace_lyrics(video_id: str, cache: Cache, text: str) -> dict:
    """Swap a cached song's lyrics for pasted ones; meta.json is rewritten last."""
    from .cache import write_meta

    d = cache.song_dir(video_id)
    if not cache.is_complete(video_id):
        raise FileNotFoundError(f"{video_id} is not ready yet")
    meta = cache.read_meta(video_id)
    res = engine.lyrics_from_paste(text, d / "vocals.flac", meta.get("language"))
    if res.mode == "none":
        raise ValueError("no lyric lines in the pasted text")
    engine.write_lyrics(res, d)
    meta.update(lyrics_mode=res.mode, lyrics_source="pasted", lyrics_offset=res.offset, align_prob=res.align_prob,
                align_coverage=res.align_coverage, word_aligner=ctc_align.NAME)
    write_meta(d, meta)
    return meta


def restem(video_id: str, cache: Cache, mode: str = "quality") -> dict:
    """Redo a cached song's stems with the current separator; keep its video and lyrics.

    New stems are made in a scratch dir and swapped in, meta.json is rewritten last.
    """
    import shutil

    from . import vocals
    from .cache import write_meta

    d = cache.song_dir(video_id)
    if not cache.is_complete(video_id):
        raise FileNotFoundError(f"{video_id} is not a complete cached song")
    work = d / ".restem"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    t = time.time()
    media.extract_audio(d / "video.mp4", work / "audio.wav")
    media.separate(work / "audio.wav", work, mode)
    for stem in ("instrumental.flac", "vocals.flac"):
        (work / stem).replace(d / stem)
    shutil.rmtree(work, ignore_errors=True)
    meta = cache.read_meta(video_id)
    v_start, v_end = vocals.onsets(vocals.load_activity(d / "vocals.flac"))
    meta.update(
        separator=mode, separator_model=media.SEPARATORS[mode][0], vocal_start=v_start, vocal_end=v_end,
        stems_version=int(time.time()),  # new URL for the pair: the TV never mixes old and new stems
    )
    meta.setdefault("timings", {})["separate"] = round(time.time() - t, 1)
    write_meta(d, meta)
    return meta


def redo_lyrics(video_id: str, cache: Cache) -> dict:
    """Re-run the lyrics engine on a cached song (keeps pasted lyrics); meta.json is rewritten last."""
    from .cache import write_meta

    d = cache.song_dir(video_id)
    if not cache.is_complete(video_id):
        raise FileNotFoundError(f"{video_id} is not a complete cached song")
    meta = cache.read_meta(video_id)
    if meta.get("lyrics_source") == "pasted":
        return refresh_word_times(d, meta)
    t = time.time()
    res = engine.build_lyrics(meta, d / "vocals.flac")
    if is_downgrade(meta.get("lyrics_mode"), res.mode):
        # e.g. LRCLIB unreachable this time: keep the lyrics we have, only refresh their word times
        log.warning("%s: redo gave %s, worse than %s; keeping the old lyrics", video_id, res.mode, meta.get("lyrics_mode"))
        return refresh_word_times(d, meta)
    engine.write_lyrics(res, d)
    meta.update(
        language=res.language, lyrics_mode=res.mode, lyrics_source=res.source, lyrics_offset=res.offset,
        align_prob=res.align_prob, align_coverage=res.align_coverage, word_aligner=ctc_align.NAME, vocal_start=res.vocal_start,
        vocal_end=res.vocal_end,
    )
    meta.setdefault("timings", {})["lyrics"] = round(time.time() - t, 1)
    write_meta(d, meta)
    return meta


MODE_RANK = {"none": 0, "teleprompter": 1, "aligned": 2, "synced": 3}


def is_downgrade(old: str | None, new: str) -> bool:
    """True when a redo would replace lyrics with a worse kind (synced > aligned > teleprompter > none)."""
    return MODE_RANK.get(new, 0) < MODE_RANK.get(old or "none", 0)


def refresh_word_times(d: Path, meta: dict) -> dict:
    """Keep a song's lyrics. Synced lines get word times added, or redone when an older aligner made
    them (meta word_aligner); word times a guest pasted themselves are kept."""
    from . import lrc
    from .cache import write_meta

    f = d / "lyrics.lrc"
    if meta.get("lyrics_mode") != "synced" or not f.exists():
        return meta
    lines = lrc.parse_lrc(f.read_text("utf-8"))
    if needs_new_word_times(meta, lines):
        lines = [lrc.Line(line.t, line.text) for line in lines]
    out, coverage = engine.add_word_times(lines, d / "vocals.flac", meta.get("language") or "en")
    if out is not lines and any(line.words for line in out):
        f.write_text(lrc.format_lrc(out), "utf-8")
        meta["word_aligner"] = ctc_align.NAME
        meta["align_coverage"] = coverage
    write_meta(d, meta)
    return meta


def needs_new_word_times(meta: dict, lines) -> bool:
    """True when the word times in these lines came from an aligner other than the current one.
    Songs from before word_aligner was recorded with word times were timed by Whisper."""
    has_words = any(line.words for line in lines)
    return has_words and meta.get("word_aligner", "whisper" if meta.get("align_coverage") is not None else None) not in (None, ctc_align.NAME)
