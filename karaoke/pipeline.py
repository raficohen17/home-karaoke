"""Process one song: resolve -> download -> separate -> lyrics -> commit to cache."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from . import engine, media
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
        "vocal_start": res.vocal_start,
        "vocal_end": res.vocal_end,
        "separator": mode,
        "separator_model": media.SEPARATORS[mode][0],
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
    meta.update(lyrics_mode=res.mode, lyrics_source="pasted", lyrics_offset=res.offset, align_prob=res.align_prob)
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
    meta.update(separator=mode, separator_model=media.SEPARATORS[mode][0], vocal_start=v_start, vocal_end=v_end)
    meta.setdefault("timings", {})["separate"] = round(time.time() - t, 1)
    write_meta(d, meta)
    return meta
