"""Download a YouTube video and split its audio into instrumental + vocals stems (FLAC, D2)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

VIDEO_FORMAT = "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=720][vcodec^=avc1]+ba/b[height<=720]"
# D1 (measured on a 60s clip, M4 Pro / MPS; vocals SDR vs full-overlap BS-RoFormer as reference):
#   quality: BS-RoFormer, overlap 2, fp16 autocast  -> 41s per 60s audio, 23.5 dB
#   fast:    MDX-Net Inst HQ 3                       ->  8s per 60s audio, 14.7 dB
# (htdemucs: 6s but 10.8 dB and four stems; BS-RoFormer default overlap 8: ~100s per 60s.)
SEPARATORS = {
    "quality": (
        "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        {"use_autocast": True, "mdxc_params": {"segment_size": 256, "override_model_segment_size": False, "batch_size": 1, "overlap": 2, "pitch_shift": 0}},
    ),
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
    """Split audio (D1); write instrumental.flac and vocals.flac with equal sample counts."""
    from audio_separator.separator import Separator

    from .tls import use_system_trust

    use_system_trust()
    MODEL_DIR.mkdir(exist_ok=True)
    work = out_dir / "sep"
    work.mkdir(exist_ok=True)
    model, opts = SEPARATORS[mode]
    sep = Separator(log_level=40, model_file_dir=str(MODEL_DIR), output_dir=str(work), output_format="FLAC", **opts)
    sep.load_model(model_filename=model)
    files = [work / Path(f).name for f in sep.separate(str(audio_wav))]
    vocals = next(f for f in files if "(Vocals)" in f.name)
    instr = next(f for f in files if "(Instrumental)" in f.name)
    v_out, i_out = out_dir / "vocals.flac", out_dir / "instrumental.flac"
    shutil.move(str(vocals), v_out)
    shutil.move(str(instr), i_out)
    shutil.rmtree(work, ignore_errors=True)
    equalize_lengths(i_out, v_out)
    return i_out, v_out


def equalize_lengths(a: Path, b: Path) -> int:
    """Trim the longer stem so both have the same sample count; return that count."""
    import soundfile as sf

    na, nb = sf.info(str(a)).frames, sf.info(str(b)).frames
    n = min(na, nb)
    for p, cur in ((a, na), (b, nb)):
        if cur != n:
            data, sr = sf.read(str(p), frames=n, always_2d=True)
            sf.write(str(p), data, sr, format="FLAC")
    return n


def sample_counts(*paths: Path) -> list[int]:
    import soundfile as sf

    return [sf.info(str(p)).frames for p in paths]
