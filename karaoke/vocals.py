"""Vocal activity from the isolated vocal stem (pure numpy over samples)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

HOP = 0.1  # seconds per activity frame


def activity_from_samples(mono: np.ndarray, sr: int, hop: float = HOP, rel_db: float = -30.0) -> np.ndarray:
    """1 where frame RMS is within rel_db of the loud (95th percentile) level, else 0."""
    size = max(1, int(sr * hop))
    n = len(mono) // size
    if n == 0:
        return np.zeros(0)
    frames = mono[: n * size].reshape(n, size).astype(np.float64)
    rms = np.sqrt((frames**2).mean(axis=1)) + 1e-12
    ref = np.percentile(rms, 95)
    db = 20 * np.log10(rms / ref)
    act = (db > rel_db).astype(float)
    return smooth(act, 3)


def smooth(act: np.ndarray, k: int) -> np.ndarray:
    """Close gaps shorter than k frames and drop blips shorter than k frames."""
    a = act.copy()
    for val in (0, 1):  # fill short 0-gaps, then remove short 1-blips
        i = 0
        while i < len(a):
            if a[i] == val:
                j = i
                while j < len(a) and a[j] == val:
                    j += 1
                if j - i < k and i > 0 and j < len(a):
                    a[i:j] = 1 - val
                i = j
            else:
                i += 1
    return a


def onsets(act: np.ndarray, hop: float = HOP) -> tuple[float | None, float | None]:
    idx = np.flatnonzero(act)
    if idx.size == 0:
        return None, None
    return round(idx[0] * hop, 2), round((idx[-1] + 1) * hop, 2)


def load_activity(vocals_path: Path, hop: float = HOP) -> np.ndarray:
    import soundfile as sf

    data, sr = sf.read(str(vocals_path), always_2d=True)
    return activity_from_samples(data.mean(axis=1), sr, hop)
