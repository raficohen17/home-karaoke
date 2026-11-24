"""FastAPI host: /tv, /remote, /ws, a serial background worker (D7), static cache."""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import netinfo, pipeline, resolver
from .cache import Cache
from .party import Duplicate, Party
from .tls import use_system_trust

log = logging.getLogger("karaoke.server")
STATIC = Path(__file__).parent / "static"


class AddRequest(BaseModel):
    input: str | None = None
    video_id: str | None = None
    title: str = ""
    added_by: str = ""


class LyricsRequest(BaseModel):
    video_id: str
    text: str


class Hub:
    """Holds party state, connected sockets and the worker."""

    def __init__(self, cache: Cache, mode: str = "quality"):
        self.cache = cache
        self.mode = mode
        self.party = Party()
        self.sockets: dict[WebSocket, str] = {}
        self.wake = asyncio.Event()
        self.active_tv: WebSocket | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def broadcast(self, msg: dict | None = None) -> None:
        payload = json.dumps(msg or {"type": "state", **self.party.snapshot()}, ensure_ascii=False)
        for ws in list(self.sockets):
            try:
                await ws.send_text(payload)
            except Exception:
                self.sockets.pop(ws, None)

    async def standby_others(self, active: WebSocket) -> None:
        payload = json.dumps({"type": "standby"})
        for ws, role in list(self.sockets.items()):
            if role == "tv" and ws is not active:
                try:
                    await ws.send_text(payload)
                except Exception:
                    self.sockets.pop(ws, None)

    async def to_tv(self, msg: dict) -> None:
        payload = json.dumps(msg)
        for ws, role in list(self.sockets.items()):
            if role == "tv":
                try:
                    await ws.send_text(payload)
                except Exception:
                    self.sockets.pop(ws, None)

    def add(self, video_id: str, title: str, added_by: str):
        ready = self.cache.is_complete(video_id)
        if ready and not title:
            title = self.cache.read_meta(video_id).get("title", "")
        e = self.party.add(video_id, title, added_by, ready=ready)
        if self.party.current is None and ready:
            self.party.advance()
        self.wake.set()
        return e

    async def worker(self) -> None:
        while True:
            entry = self.party.next_to_process()
            if entry is None:
                self.wake.clear()
                await self.wake.wait()
                continue
            vid = entry.video_id

            def status(s, p=None, vid=vid):
                self.loop.call_soon_threadsafe(self._on_status, vid, s, p)

            try:
                meta = await asyncio.to_thread(pipeline.process, vid, self.cache, status, self.mode)
                for e in self.party._all():
                    if e.video_id == vid and not e.title:
                        e.title = meta.get("title", "")
                self.party.set_status(vid, "READY")
            except Exception as ex:  # any failure ends this song, never the worker
                log.exception("processing %s failed", vid)
                self.party.set_status(vid, "FAILED", reason=str(ex)[:200])
            if self.party.current is None:
                self.party.advance()
            await self.broadcast()

    def _on_status(self, vid: str, s: str, p: float | None) -> None:
        if s != "READY":
            self.party.set_status(vid, s, p)
            asyncio.ensure_future(self.broadcast())

    async def handle(self, ws: WebSocket, msg: dict) -> None:
        p = self.party
        t = msg.get("type")
        if t == "vocal":
            p.vocal_level = max(0.0, min(1.0, float(msg["level"])))
            await self.broadcast({"type": "vocal", "level": p.vocal_level})
            return
        if t == "nudge":
            p.scroll_speed = max(0.25, min(3.0, p.scroll_speed + (0.1 if msg.get("dir") == "+" else -0.1)))
        elif t in ("pause", "resume"):
            p.paused = t == "pause"
            await self.to_tv({"type": t})
        elif t == "seek":
            await self.to_tv({"type": "seek", "delta": float(msg.get("delta", 0))})
        elif t in ("skip", "ended"):
            if t == "ended" and (not p.current or msg.get("video_id") != p.current.video_id):
                return
            p.advance()
        elif t == "remove":
            p.remove(int(msg["id"]))
        elif t == "move":
            p.move(int(msg["id"]), int(msg["delta"]))
        elif t == "position":
            if p.current and msg.get("video_id") == p.current.video_id:
                p.position = float(msg["t"])
                p.paused = bool(msg.get("paused", False))
            return  # position reports are not re-broadcast
        elif t == "audio_ready":
            p.audio_ready = bool(msg.get("ready"))
            if p.audio_ready:  # the TV that was tapped last plays; any other TV goes silent
                self.active_tv = ws
                await self.standby_others(ws)
        await self.broadcast()


def create_app(cache_dir: str = "cache", host_ip: str | None = None, port: int = 8765, mode: str = "quality") -> FastAPI:
    use_system_trust()
    cache = Cache(cache_dir)
    cache.root.mkdir(parents=True, exist_ok=True)
    cache.clear_staging()
    hub = Hub(cache, mode)
    app = FastAPI(title="Home Karaoke")
    app.state.hub = hub
    remote_url = f"http://{host_ip or netinfo.lan_ip()}:{port}/remote"

    @app.on_event("startup")
    async def _start():
        hub.loop = asyncio.get_running_loop()
        app.state.worker = asyncio.create_task(hub.worker())

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.mount("/media", StaticFiles(directory=cache.root), name="media")

    @app.get("/")
    async def root():
        return RedirectResponse("/remote")

    @app.get("/tv")
    async def tv():
        return FileResponse(STATIC / "tv.html")

    @app.get("/remote")
    async def remote():
        return FileResponse(STATIC / "remote.html")

    @app.get("/api/info")
    async def info():
        return {"remote_url": remote_url}

    @app.get("/qr.svg")
    async def qr():
        import qrcode
        import qrcode.image.svg

        buf = io.BytesIO()
        qrcode.make(remote_url, image_factory=qrcode.image.svg.SvgPathFillImage, box_size=12, border=2).save(buf)
        return Response(buf.getvalue(), media_type="image/svg+xml")

    @app.get("/api/search")
    async def search(q: str):
        if resolver.classify_input(q) != "query":
            raise HTTPException(400, "use /api/add for links")
        cands = await asyncio.to_thread(resolver.search_youtube, q, 5)
        return [c.to_dict() | {"cached": cache.is_complete(c.video_id)} for c in cands]

    @app.get("/api/library")
    async def library():
        out = []
        for vid in cache.list_complete():
            m = cache.read_meta(vid)
            out.append({"video_id": vid, "title": m.get("title", ""), "lyrics_mode": m.get("lyrics_mode")})
        return out

    @app.post("/api/add")
    async def add(req: AddRequest):
        vid, title = req.video_id, req.title
        if not vid and req.input:
            kind = resolver.classify_input(req.input)
            if kind == "query":
                raise HTTPException(400, "pick a search result")
            try:
                vid = await asyncio.to_thread(resolver.resolve, req.input)
            except resolver.NoMatch as e:
                raise HTTPException(404, f"no_match: {e}")
            except Exception as e:
                raise HTTPException(502, str(e)[:200])
        if not vid:
            raise HTTPException(400, "nothing to add")
        try:
            e = hub.add(vid, title, req.added_by)
        except Duplicate as d:
            raise HTTPException(409, str(d))
        await hub.broadcast()
        return {"id": e.id, "video_id": vid, "status": e.status}

    @app.post("/api/lyrics")
    async def paste_lyrics(req: LyricsRequest):
        if not cache.is_complete(req.video_id):
            raise HTTPException(409, "song is still being prepared")
        if len(req.text.strip()) < 10:
            raise HTTPException(400, "paste the song's lyrics")
        try:
            meta = await asyncio.to_thread(pipeline.replace_lyrics, req.video_id, cache, req.text)
        except ValueError as e:
            raise HTTPException(400, str(e))
        await hub.broadcast({"type": "lyrics_updated", "video_id": req.video_id})
        return {"lyrics_mode": meta["lyrics_mode"], "align_prob": meta.get("align_prob"), "offset": meta.get("lyrics_offset")}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket, role: str = "remote"):
        await ws.accept()
        hub.sockets[ws] = role
        await ws.send_text(json.dumps({"type": "state", **hub.party.snapshot()}, ensure_ascii=False))
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                await hub.handle(ws, msg)
        except WebSocketDisconnect:
            pass
        finally:
            hub.sockets.pop(ws, None)
            if role == "tv" and hub.active_tv is ws:
                hub.active_tv = None
                hub.party.audio_ready = False
                await hub.broadcast()

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host-ip", default=None, help="address shown in the QR code (default: auto)")
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--fast", action="store_true", help="faster, lower-quality vocal removal (MDX-Net)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(args.cache, args.host_ip, args.port, "fast" if args.fast else "quality")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
