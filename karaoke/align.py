"""Forced alignment and language detection on the vocal stem with stable-ts + faster-whisper (D3)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

MODELS = {"he": "ivrit-ai/whisper-large-v3-turbo-ct2", "en": "large-v3-turbo"}
# faster-whisper defaults to 4 threads; using the cores halves alignment time (55s -> 28s, vampire).
CPU_THREADS = max(4, (os.cpu_count() or 8) - 4)


@lru_cache(maxsize=2)
def _model(language: str):
    import stable_whisper

    from .tls import use_system_trust

    use_system_trust()
    name = MODELS.get(language, MODELS["en"])
    try:  # cached copy first: no network round-trip, works offline
        return stable_whisper.load_faster_whisper(name, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS, local_files_only=True)
    except Exception:
        return stable_whisper.load_faster_whisper(name, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS)


def align_words(vocals: Path, text: str, language: str) -> tuple[list[tuple[float, str, float]], float]:
    """Align text to the vocal stem. Return ([(start, word, probability)], mean word probability)."""
    model = _model(language)
    result = model.align(str(vocals), text, language=language)
    words = [
        (float(w.start), w.word.strip(), float(w.probability or 0.0))
        for w in result.all_words()
        if w.word.strip()
    ]
    probs = [p for _, _, p in words]
    return words, (sum(probs) / len(probs) if probs else 0.0)


def detect_language(vocals: Path, start: float | None = None, end: float | None = None) -> str:
    """Whisper language id voted over three 30s windows spread across the singing."""
    from faster_whisper import decode_audio

    model = _model("en")
    audio = decode_audio(str(vocals), sampling_rate=16000)
    s, e = start or 0.0, end or len(audio) / 16000
    votes = []
    for frac in (0.2, 0.5, 0.8):
        t = s + (e - s) * frac - 15
        a = audio[max(0, int(t * 16000)) : max(0, int(t * 16000)) + 30 * 16000]
        if len(a) > 16000:
            _, info = model.transcribe_original(a, language=None, beam_size=1)
            votes.append(info.all_language_probs or [(info.language, 1.0)])
    return vote_language(votes)


def vote_language(windows: list[list[tuple[str, float]]]) -> str:
    """'he' when Hebrew (he/iw/yi) outweighs English summed over windows; else 'en'."""
    he = sum(p for w in windows for lang, p in w if lang in ("he", "iw", "yi"))
    en = sum(p for w in windows for lang, p in w if lang == "en")
    return "he" if he > en else "en"
