"""Access control and input validation for the party server (pure, unit-tested).

Threat model: anyone on the same network (guests, other devices, a VPN peer), and any website a
guest or the host has open in a browser (cross-site requests, WebSocket hijacking, DNS rebinding).
"""
from __future__ import annotations

import ipaddress
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

VIDEO_ID_RE = r"^[A-Za-z0-9_-]{11}$"
VideoId = Annotated[str, Field(pattern=VIDEO_ID_RE)]
_VIDEO_ID = re.compile(VIDEO_ID_RE)

GUEST_COOKIE = "karaoke_guest"
TV_COOKIE = "karaoke_tv"
MAX_LYRICS_CHARS = 20_000
MAX_QUEUE = 40
MAX_PENDING_PER_CLIENT = 5
MAX_VIDEO_SECONDS = 15 * 60
WS_MAX_BYTES = 64 * 1024


def is_video_id(value: str) -> bool:
    return bool(_VIDEO_ID.match(value or ""))


def require_video_id(value: str) -> str:
    """Raise ValueError unless value is a YouTube video id (blocks path traversal like '../')."""
    if not is_video_id(value):
        raise ValueError(f"not a video id: {value!r}")
    return value


# ---------- keys and roles ----------

@dataclass(frozen=True)
class Keys:
    guest: str = field(default_factory=lambda: secrets.token_urlsafe(9))
    tv: str = field(default_factory=lambda: secrets.token_urlsafe(18))


def is_loopback(client_host: str | None) -> bool:
    try:
        return ipaddress.ip_address(client_host or "").is_loopback
    except ValueError:
        return False


def role_for(client_host: str | None, cookies: dict, keys: Keys) -> str | None:
    """'tv' for this machine or a holder of the TV key, 'guest' for a holder of the party key,
    else None. Keys are compared in constant time."""
    if is_loopback(client_host) or secrets.compare_digest(cookies.get(TV_COOKIE, ""), keys.tv):
        return "tv"
    if secrets.compare_digest(cookies.get(GUEST_COOKIE, ""), keys.guest):
        return "guest"
    return None


def allowed_hosts(lan_ip: str, port: int) -> set[str]:
    names = {lan_ip, "localhost", "127.0.0.1", "[::1]"}
    return names | {f"{n}:{port}" for n in names}


def host_ok(host_header: str | None, allowed: set[str]) -> bool:
    """Reject DNS-rebinding requests: the Host header must name this server."""
    return (host_header or "").lower() in allowed


def origin_ok(origin: str | None, allowed: set[str]) -> bool:
    """WebSocket Origin must be one of this server's own pages (blocks cross-site hijacking)."""
    if not origin:
        return False
    m = re.fullmatch(r"https?://([^/]+)", origin.lower())
    return bool(m) and m.group(1) in allowed


# ---------- request bodies ----------

class AddRequest(BaseModel):
    input: str | None = Field(default=None, max_length=500)
    video_id: VideoId | None = None
    title: str = Field(default="", max_length=200)


class LyricsRequest(BaseModel):
    video_id: VideoId
    text: str = Field(min_length=10, max_length=MAX_LYRICS_CHARS)


# ---------- WebSocket messages ----------

class _Vocal(BaseModel):
    type: Literal["vocal"]
    level: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


class _Simple(BaseModel):
    type: Literal["pause", "resume", "skip"]


class _Seek(BaseModel):
    type: Literal["seek"]
    delta: float = Field(ge=-600, le=600, allow_inf_nan=False)


class _Nudge(BaseModel):
    type: Literal["nudge"]
    dir: Literal["+", "-"]


class _Remove(BaseModel):
    type: Literal["remove"]
    id: int = Field(ge=0, le=10**9)


class _Move(BaseModel):
    type: Literal["move"]
    id: int = Field(ge=0, le=10**9)
    delta: int = Field(ge=-100, le=100)


class _Ended(BaseModel):
    type: Literal["ended"]
    video_id: VideoId


class _Position(BaseModel):
    type: Literal["position"]
    video_id: VideoId
    t: float = Field(ge=0, le=36_000, allow_inf_nan=False)
    paused: bool = False


class _AudioReady(BaseModel):
    type: Literal["audio_ready"]
    ready: bool


GUEST_TYPES = {"vocal", "pause", "resume", "skip", "seek", "nudge", "remove", "move"}
TV_TYPES = GUEST_TYPES | {"ended", "position", "audio_ready"}

_Message = Annotated[
    Union[_Vocal, _Simple, _Seek, _Nudge, _Remove, _Move, _Ended, _Position, _AudioReady],
    Field(discriminator="type"),
]
_ADAPTER = TypeAdapter(_Message)


def parse_message(raw: str, role: str) -> dict | None:
    """Validated message dict, or None if malformed, out of range, or not allowed for this role.

    NaN/Infinity tokens are refused outright (they are not JSON and break browsers' JSON.parse).
    """
    if len(raw) > WS_MAX_BYTES or re.search(r"\b(?:NaN|Infinity)\b", raw):
        return None
    try:
        msg = _ADAPTER.validate_json(raw)
    except ValidationError:
        return None
    allowed = TV_TYPES if role == "tv" else GUEST_TYPES
    return msg.model_dump() if msg.type in allowed else None


# ---------- rate limiting ----------

class RateLimiter:
    """Token bucket per key: `rate` actions per `per` seconds, bursts up to `rate`."""

    def __init__(self, rate: int, per: float, clock=time.monotonic):
        self.rate, self.per, self.clock = rate, per, clock
        self._b: dict[str, tuple[float, float]] = {}

    def allow(self, key: str) -> bool:
        now = self.clock()
        tokens, last = self._b.get(key, (float(self.rate), now))
        tokens = min(float(self.rate), tokens + (now - last) * self.rate / self.per)
        ok = tokens >= 1.0
        self._b[key] = (tokens - 1.0 if ok else tokens, now)
        return ok


# ---------- safe error text for guests ----------

_PATH = re.compile(r"(?:/[^\s'\"]+)+")


def public_reason(exc: Exception) -> str:
    """Short failure reason for the queue, without local file paths or internals."""
    from .media import DownloadError, TooLong

    if isinstance(exc, TooLong):
        return f"Longer than {MAX_VIDEO_SECONDS // 60} minutes or a live stream"
    if isinstance(exc, DownloadError):
        text = _PATH.sub("…", str(exc)).strip()
        text = re.sub(r"^\[[^\]]+\]\s*[\w-]+:\s*", "", text)  # "[youtube] id: " prefix
        return (text or "Download failed")[:160]
    return "Processing failed"
