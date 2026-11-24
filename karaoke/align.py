"""Forced alignment and transcription on the vocal stem with stable-ts + faster-whisper (D3)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

MODELS = {"he": "ivrit-ai/whisper-large-v3-turbo-ct2", "en": "large-v3-turbo"}


@lru_cache(maxsize=2)
def _model(language: str):
    import stable_whisper

    from .tls import use_system_trust

    use_system_trust()
    return stable_whisper.load_faster_whisper(MODELS.get(language, MODELS["en"]), device="cpu", compute_type="int8")


def align_words(vocals: Path, text: str, language: str) -> tuple[list[tuple[float, str]], float]:
    """Align text to the vocal stem. Return ([(start, word)], mean word probability)."""
    model = _model(language)
    result = model.align(str(vocals), text, language=language)
    words = [(float(w.start), w.word.strip()) for w in result.all_words() if w.word.strip()]
    probs = [w.probability for w in result.all_words() if w.probability is not None]
    return words, (sum(probs) / len(probs) if probs else 0.0)


def transcribe_lines(vocals: Path, language: str) -> list[tuple[float, str]]:
    """Transcribe the vocal stem into (start, line) pairs, one per segment."""
    model = _model(language)
    result = model.transcribe(str(vocals), language=language, vad=True, word_timestamps=True)
    result.split_by_length(max_chars=42)
    return [(float(s.start), s.text.strip()) for s in result.segments if s.text.strip()]


def detect_language(vocals: Path) -> str:
    model = _model("en")
    segs, info = model.model.transcribe(str(vocals), language=None, beam_size=1, vad_filter=True)
    return "he" if info.language in ("he", "iw", "yi") else "en"
