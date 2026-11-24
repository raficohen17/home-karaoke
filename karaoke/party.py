"""Party queue state machine (pure; the server wires it to a worker and WebSockets)."""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field

STATUSES = ("QUEUED", "DOWNLOADING", "SEPARATING", "ALIGNING", "READY", "FAILED")
_ids = itertools.count(1)


@dataclass
class Entry:
    video_id: str
    title: str = ""
    added_by: str = ""
    status: str = "QUEUED"
    progress: float | None = None
    reason: str | None = None
    id: int = field(default_factory=lambda: next(_ids))


class Duplicate(Exception):
    pass


@dataclass
class Party:
    queue: list[Entry] = field(default_factory=list)
    current: Entry | None = None
    vocal_level: float = 0.3
    paused: bool = False
    position: float = 0.0
    audio_ready: bool = False
    scroll_speed: float = 1.0

    # ----- queue edits -----
    def add(self, video_id: str, title: str = "", added_by: str = "", ready: bool = False) -> Entry:
        if (self.current and self.current.video_id == video_id) or any(e.video_id == video_id for e in self.queue):
            raise Duplicate("Already in queue")
        e = Entry(video_id, title, added_by, status="READY" if ready else "QUEUED")
        self.queue.append(e)
        return e

    def remove(self, entry_id: int) -> bool:
        before = len(self.queue)
        self.queue = [e for e in self.queue if e.id != entry_id]
        return len(self.queue) != before

    def move(self, entry_id: int, delta: int) -> bool:
        idx = next((i for i, e in enumerate(self.queue) if e.id == entry_id), None)
        if idx is None:
            return False
        j = max(0, min(len(self.queue) - 1, idx + delta))
        self.queue.insert(j, self.queue.pop(idx))
        return True

    def set_status(self, video_id: str, status: str, progress: float | None = None, reason: str | None = None) -> None:
        assert status in STATUSES
        for e in self._all():
            if e.video_id == video_id:
                e.status, e.progress, e.reason = status, progress, reason

    # ----- worker -----
    def next_to_process(self) -> Entry | None:
        """FIFO, one at a time (D7): the first QUEUED entry, current song first if it isn't ready."""
        for e in self._all():
            if e.status == "QUEUED":
                return e
        return None

    # ----- playback -----
    def advance(self) -> Entry | None:
        """End/skip the current song: play the first READY entry, drop FAILED ones before it.

        Returns the new current entry or None (nothing ready; `upcoming` tells /tv what's coming).
        """
        self.current = None
        self.position = 0.0
        self.paused = False
        self.queue = [e for e in self.queue if e.status != "FAILED"]
        for i, e in enumerate(self.queue):
            if e.status == "READY":
                self.current = self.queue.pop(i)
                return self.current
        return None

    def upcoming(self) -> Entry | None:
        return next((e for e in self.queue if e.status != "FAILED"), None)

    def snapshot(self) -> dict:
        up = self.upcoming()
        return {
            "current": asdict(self.current) if self.current else None,
            "queue": [asdict(e) for e in self.queue],
            "upcoming": asdict(up) if up else None,
            "vocal_level": self.vocal_level,
            "paused": self.paused,
            "position": self.position,
            "audio_ready": self.audio_ready,
            "scroll_speed": self.scroll_speed,
        }

    def _all(self):
        return ([self.current] if self.current else []) + self.queue
