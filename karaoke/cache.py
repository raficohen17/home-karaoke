"""Song cache: cache/<video_id>/ exists only when complete (written via cache/.staging/)."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .security import require_video_id

REQUIRED_FILES = ("video.mp4", "instrumental.flac", "vocals.flac", "meta.json")
STAGING = ".staging"
OWNER = ".owner_pid"


class Cache:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def song_dir(self, video_id: str) -> Path:
        return self.root / require_video_id(video_id)

    def staging_dir(self, video_id: str) -> Path:
        return self.root / STAGING / require_video_id(video_id)

    def is_complete(self, video_id: str) -> bool:
        return is_complete_dir(self.song_dir(video_id))

    def read_meta(self, video_id: str) -> dict:
        return json.loads((self.song_dir(video_id) / "meta.json").read_text("utf-8"))

    def begin(self, video_id: str) -> Path:
        """Return a fresh staging dir for a song (any previous partial work is removed)."""
        d = self.staging_dir(video_id)
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        (d / OWNER).write_text(str(os.getpid()))
        return d

    def commit(self, video_id: str, meta: dict) -> Path:
        """Write meta.json (status complete) last, then atomically move staging into place."""
        src = self.staging_dir(video_id)
        write_meta(src, {**meta, "status": "complete"})
        (src / OWNER).unlink(missing_ok=True)
        missing = [f for f in REQUIRED_FILES if not (src / f).exists()]
        if missing:
            raise RuntimeError(f"cannot commit {video_id}: missing {missing}")
        dst = self.song_dir(video_id)
        if dst.exists():
            shutil.rmtree(dst)
        src.rename(dst)
        return dst

    def clear_staging(self) -> None:
        """Remove abandoned work dirs; keep ones whose owner process is still running."""
        base = self.root / STAGING
        if not base.exists():
            return
        for d in base.iterdir():
            if d.is_dir() and not owner_alive(d):
                shutil.rmtree(d, ignore_errors=True)

    def list_complete(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and is_complete_dir(p))


def write_meta(directory: Path, meta: dict) -> None:
    tmp = directory / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    tmp.rename(directory / "meta.json")


def is_complete_dir(d: Path) -> bool:
    meta = d / "meta.json"
    if not meta.exists():
        return False
    try:
        status = json.loads(meta.read_text("utf-8")).get("status")
    except (json.JSONDecodeError, OSError):
        return False
    return status == "complete" and all((d / f).exists() for f in REQUIRED_FILES)


def owner_alive(d: Path) -> bool:
    try:
        pid = int((d / OWNER).read_text())
    except (OSError, ValueError):
        return False
    if pid == os.getpid():
        return False  # our own leftovers from before a restart can't be in progress
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
