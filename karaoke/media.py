"""Download a YouTube video and split its audio into instrumental + vocals stems (FLAC, D2)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

VIDEO_FORMAT = "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=720][vcodec^=avc1]+ba/b[height<=720]"
# D-media-pipeline-1 (60s clips, M4 Pro / MPS). Guitar test on the "vampire" bridge, share of a
# reference guitar track (htdemucs_6s) that ends up in the VOCAL stem:
#   quality: Mel-Band RoFormer Kim FT2 bleedless, overlap 2 -> 20s per 60s audio, 23% guitar in
#            vocals, voice left in instrumental -21.6 dB
#   (was BS-RoFormer ep317 overlap 2 + fp16: 43s, 27%, -23.8 dB; fp16 made no difference)
#   fast:    MDX-Net Inst HQ 3 -> 8s per 60s audio
_MDXC = {"segment_size": 256, "override_model_segment_size": False, "batch_size": 1, "overlap": 2, "pitch_shift": 0}
SEPARATORS = {
    "quality": ("mel_band_roformer_kim_ft2_bleedless_unwa.ckpt", {"mdxc_params": _MDXC}),
    "fast": ("UVR-MDX-NET-Inst_HQ_3.onnx", {}),
}
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


class DownloadError(Exception):
    pass


def download(video_id: str, out_dir: Path, progress=None) -> dict:
    """Download video.mp4 (720p H.264, with audio) and audio.wav. Return yt-dlp info subset."""
    import yt_dlp

    from .tls import use_system_trust

    use_system_trust()

    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(d.get("downloaded_bytes", 0) / total)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": VIDEO_FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "video.%(ext)s"),
        "progress_hooks": [hook],
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e).replace("ERROR: ", "")) from e
    video = out_dir / "video.mp4"
    if not video.exists():
        raise DownloadError("video.mp4 missing after download")
    extract_audio(video, out_dir / "audio.wav")
    return {
        "video_id": video_id,
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "track": info.get("track"),
        "artist": info.get("artist") or (info.get("artists") or [None])[0],
        "duration": info.get("duration"),
    }


def extract_audio(video: Path, wav: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "2", "-ar", "44100", str(wav)],
        check=True,
    )


def separate(audio_wav: Path, out_dir: Path, mode: str = "quality") -> tuple[Path, Path]:
    """Split audio (D1); write instrumental.flac and vocals.flac with equal sample counts whose
    sum reproduces the original mix (D-media-pipeline-5)."""
    import soundfile as sf
    from audio_separator.separator import Separator

    from .tls import use_system_trust

    use_system_trust()
    MODEL_DIR.mkdir(exist_ok=True)
    work = out_dir / "sep"
    work.mkdir(exist_ok=True)
    model, opts = SEPARATORS[mode]
    # normalization_threshold=1.0: don't peak-normalise each stem separately (that shifted the
    # instrumental/vocal balance); rebalance() restores true levels against the mix instead.
    sep = Separator(
        log_level=40, model_file_dir=str(MODEL_DIR), output_dir=str(work), output_format="WAV",
        normalization_threshold=1.0, **opts,
    )
    sep.load_model(model_filename=model)
    files = [work / Path(f).name for f in sep.separate(str(audio_wav))]
    mix, sr = sf.read(str(audio_wav), always_2d=True, dtype="float32")
    inst_file, voc_file = pick_stems(files)
    voc = _read_like(voc_file, mix) if voc_file else None
    inst = _read_like(inst_file, mix) if inst_file else None
    if inst is None and voc is None:
        raise RuntimeError(f"separator wrote no usable stems: {[f.name for f in files]}")
    if inst is None:
        inst = mix[: len(voc)] - voc
    if voc is None:
        voc = mix[: len(inst)] - inst
    inst, voc = rebalance(mix, inst, voc)
    v_out, i_out = out_dir / "vocals.flac", out_dir / "instrumental.flac"
    sf.write(str(i_out), inst, sr, format="FLAC", subtype="PCM_24")
    sf.write(str(v_out), voc, sr, format="FLAC", subtype="PCM_24")
    shutil.rmtree(work, ignore_errors=True)
    return i_out, v_out


def pick_stems(files: list[Path]) -> tuple[Path | None, Path | None]:
    """(instrumental, vocals) among a separator's output files, by the stem name in parentheses."""
    inst = voc = None
    for f in files:
        m = re.search(r"\(([^)]*)\)", f.name)
        stem = (m.group(1) if m else f.stem).lower()
        if stem in ("vocals", "vocal", "voice"):
            voc = f
        elif stem in ("instrumental", "inst", "other", "no vocals", "karaoke"):
            inst = f
    return inst, voc


def _read_like(path: Path, mix):
    import numpy as np
    import soundfile as sf

    data, _ = sf.read(str(path), always_2d=True, dtype="float32")
    if data.shape[1] != mix.shape[1]:
        data = np.repeat(data[:, :1], mix.shape[1], axis=1)
    return data


def rebalance(mix, inst, voc, ceiling: float = 0.999):
    """Trim to a common length and fit one gain per stem so inst + voc matches the mix (least
    squares); if a stem would clip, scale both by the same factor so their balance is kept."""
    import numpy as np

    n = min(len(mix), len(inst), len(voc))
    mix, inst, voc = mix[:n], inst[:n], voc[:n]
    a = np.stack([inst.ravel(), voc.ravel()], 1).astype(np.float64)
    gains, *_ = np.linalg.lstsq(a, mix.ravel().astype(np.float64), rcond=None)
    gains = np.clip(gains, 0.25, 4.0)  # a sane range; a wild fit means a bad stem, not a level error
    inst, voc = inst * gains[0], voc * gains[1]
    peak = max(float(np.abs(inst).max(initial=0)), float(np.abs(voc).max(initial=0)))
    if peak > ceiling:
        inst, voc = inst * (ceiling / peak), voc * (ceiling / peak)
    return inst.astype(np.float32), voc.astype(np.float32)


def sample_counts(*paths: Path) -> list[int]:
    import soundfile as sf

    return [sf.info(str(p)).frames for p in paths]
