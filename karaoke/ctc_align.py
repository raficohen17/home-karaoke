"""Forced alignment of known lyrics with wav2vec2 CTC models (D-lyrics-engine-10).

English: torchaudio's MMS_FA (multilingual, Latin letters). Hebrew: facebook/mms-1b-all with its
native Hebrew adapter (Hebrew letters, no transliteration). Both run on the isolated vocal stem.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

NAME = "mms-ctc"  # recorded in meta.json as word_aligner
SR = 16000
HOP = 320  # wav2vec2 frame = 20ms at 16kHz
CHUNK_S, OVERLAP_S = 30, 1  # attention over a whole song doesn't fit in memory
_NIKUD = re.compile(r"[֑-ׇ]")


def english_tokens(word: str, vocab: dict[str, int]) -> list[int]:
    """Letters of an English word as MMS_FA token ids; digits and punctuation are dropped."""
    return [vocab[c] for c in word.lower().replace("’", "'") if c in vocab and (c.isalpha() or c == "'")]


def hebrew_tokens(word: str, vocab: dict[str, int]) -> list[int]:
    """Letters of a Hebrew word (niqqud and punctuation removed) as MMS Hebrew-adapter token ids."""
    return [vocab[c] for c in _NIKUD.sub("", word) if c in vocab and c.isalpha()]


def chunk_plan(n_samples: int) -> list[tuple[int, int, int, int]]:
    """(audio start, audio end, first kept frame, last kept frame) per chunk: each chunk sees 1s of
    context on both sides, and only its own 30s of frames are kept, so frames line up end to end."""
    chunk, ov, out = CHUNK_S * SR, OVERLAP_S * SR, []
    for s in range(0, n_samples, chunk):
        a, b = max(0, s - ov), min(n_samples, s + chunk + ov)
        f0 = (s - a) // HOP
        out.append((a, b, f0, f0 + (min(n_samples, s + chunk) - s) // HOP))
    return out


def word_starts(spans_per_token: list[tuple[int, float]], words: list[tuple[str, list[int]]], sec_per_frame: float):
    """Map token spans (start frame, score) back to words: [(start seconds, word, mean token score)].
    Words without tokens are skipped."""
    out, k = [], 0
    for w, toks in words:
        if not toks:
            continue
        seg = spans_per_token[k:k + len(toks)]
        out.append((round(seg[0][0] * sec_per_frame, 3), w, sum(s for _, s in seg) / len(seg)))
        k += len(toks)
    return out


@lru_cache(maxsize=2)
def _model(language: str):
    """(run(wave) -> logits (T, V), vocab, blank id) for the language's model; loaded once."""
    import torchaudio

    from .tls import use_system_trust

    use_system_trust()
    if language == "he":
        from transformers import AutoProcessor, Wav2Vec2ForCTC

        proc = AutoProcessor.from_pretrained("facebook/mms-1b-all", target_lang="heb")
        model = Wav2Vec2ForCTC.from_pretrained("facebook/mms-1b-all", target_lang="heb", ignore_mismatched_sizes=True).eval()
        vocab = proc.tokenizer.get_vocab()

        def run(x):
            return model(proc(x.numpy(), sampling_rate=SR, return_tensors="pt").input_values).logits[0]

        return run, vocab, vocab.get(proc.tokenizer.pad_token, 0)
    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model()
    vocab = bundle.get_dict()

    def run(x):
        return model(x.unsqueeze(0))[0][0]

    return run, vocab, 0


def _wave(vocals: Path):
    import soundfile as sf
    import torch
    import torchaudio.functional as AF

    y, sr = sf.read(str(vocals), dtype="float32", always_2d=True)
    return AF.resample(torch.from_numpy(y.mean(1)), sr, SR)


def align_words(vocals: Path, text: str, language: str) -> tuple[list[tuple[float, str, float]], float]:
    """Align known lyrics to the vocal stem. Return ([(start, word, confidence)], mean confidence);
    same shape as the Whisper aligner it replaces, so lrc.anchor_words takes it as is."""
    import torch
    import torchaudio.functional as AF

    run, vocab, blank = _model("he" if language == "he" else "en")
    tok = hebrew_tokens if language == "he" else english_tokens
    words = [(w, tok(w, vocab)) for w in text.split()]
    flat = [i for _, t in words for i in t]
    if not flat:
        return [], 0.0
    wave = _wave(vocals)
    with torch.inference_mode():
        em = torch.log_softmax(torch.cat([run(wave[a:b])[f0:f1] for a, b, f0, f1 in chunk_plan(len(wave))]), dim=-1)
    ali, scores = AF.forced_align(em.unsqueeze(0), torch.tensor([flat], dtype=torch.int32), blank=blank)
    spans = AF.merge_tokens(ali[0], scores[0].exp())
    out = word_starts([(s.start, float(s.score)) for s in spans], words, len(wave) / em.shape[0] / SR)
    return out, (sum(p for _, _, p in out) / len(out) if out else 0.0)
