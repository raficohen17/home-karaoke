"""FastAPI host: /tv, /remote, /ws, a serial background worker (D7), static cache.

Access (D-party-queue-3): guests join with the party key in the QR code (stored as a cookie); the TV
role is this machine or a holder of the TV key; every request must name this server in its Host
header and every WebSocket must come from this server's own pages.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import netinfo, pipeline, resolver, security
from .cache import Cache
from .party import Duplicate, Party
from .security import GUEST_COOKIE, TV_COOKIE, AddRequest, Keys, LyricsRequest, RateLimiter
from .tls import use_system_trust

log = logging.getLogger("karaoke.server")
STATIC = Path(__file__).parent / "static"


JOIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Karaoke</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0d0d16;color:#f1effa;
font:18px system-ui,sans-serif;text-align:center;padding:24px}h1{color:#ffd34d}</style></head>
<body><div><h1>Karaoke</h1><p>Scan the QR code on the TV to join the party.</p>
<p style="font-size:12px;color:#9a97b0;max-width:420px">Educational experiment, provided as is. You're
responsible for making sure your use complies with local law and the terms of use of the services
involved.</p></div></body></html>"""
COOKIE_AGE = 12 * 3600
PUBLIC_PREFIXES = ("/static/",)
TV_ONLY = ("/tv", "/api/info", "/qr.svg")


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
        q = self.party.queue
        if len(q) >= security.MAX_QUEUE:
            raise HTTPException(429, "The queue is full")
        mine = sum(1 for e in q if e.added_by == added_by and e.status not in ("READY", "FAILED"))
        if mine >= security.MAX_PENDING_PER_CLIENT:
            raise HTTPException(429, f"You already have {mine} songs being prepared")
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
                self.party.set_status(vid, "FAILED", reason=security.public_reason(ex))
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
            p.vocal_level = msg["level"]
            await self.broadcast({"type": "vocal", "level": p.vocal_level})
            return
        if t == "nudge":
            p.scroll_speed = max(0.25, min(3.0, p.scroll_speed + (0.1 if msg["dir"] == "+" else -0.1)))
        elif t in ("pause", "resume"):
            p.paused = t == "pause"
            await self.to_tv({"type": t})
        elif t == "seek":
            await self.to_tv({"type": "seek", "delta": msg["delta"]})
        elif t in ("skip", "ended"):
            if t == "ended" and (not p.current or msg["video_id"] != p.current.video_id):
                return
            p.advance()
        elif t == "remove":
            p.remove(msg["id"])
        elif t == "move":
            p.move(msg["id"], msg["delta"])
        elif t == "position":
            if p.current and msg["video_id"] == p.current.video_id:
                p.position = msg["t"]
                p.paused = msg["paused"]
            return  # position reports are not re-broadcast
        elif t == "audio_ready":
            p.audio_ready = msg["ready"]
            if p.audio_ready:  # the TV that was tapped last plays; any other TV goes silent
                self.active_tv = ws
                await self.standby_others(ws)
        await self.broadcast()


def create_app(
    cache_dir: str = "cache", host_ip: str | None = None, port: int = 8765, mode: str = "quality",
    keys: Keys | None = None,
) -> FastAPI:
    use_system_trust()
    cache = Cache(cache_dir)
    cache.root.mkdir(parents=True, exist_ok=True)
    cache.clear_staging()
    hub = Hub(cache, mode)
    keys = keys or Keys()
    lan_ip = host_ip or netinfo.lan_ip()
    allowed = security.allowed_hosts(lan_ip, port)
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.loop = asyncio.get_running_loop()
        worker = asyncio.create_task(hub.worker())
        yield
        worker.cancel()

    app = FastAPI(title="Home Karaoke", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.hub, app.state.keys = hub, keys
    app.state.remote_url = remote_url = f"http://{lan_ip}:{port}/remote?k={keys.guest}"
    app.state.tv_url = f"http://{lan_ip}:{port}/tv?tv={keys.tv}"
    limits = {"search": RateLimiter(20, 60), "add": RateLimiter(10, 60), "lyrics": RateLimiter(4, 60)}
    lyrics_lock = asyncio.Lock()

    def client_ip(request: Request | WebSocket) -> str:
        return request.client.host if request.client else ""

    def throttle(kind: str, request: Request) -> None:
        if not limits[kind].allow(client_ip(request)):
            raise HTTPException(429, "Too many requests, try again in a minute")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not security.host_ok(request.headers.get("host"), allowed):
            return JSONResponse({"detail": "unknown host"}, status_code=421)
        path = request.url.path
        if path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        # Joining: the key from the QR code (or the TV link) becomes a cookie.
        if path == "/remote" and request.query_params.get("k"):
            if security.secrets.compare_digest(request.query_params["k"], keys.guest):
                resp = FileResponse(STATIC / "remote.html")
                resp.set_cookie(GUEST_COOKIE, keys.guest, max_age=COOKIE_AGE, httponly=True, samesite="lax")
                return resp
            return HTMLResponse(JOIN_PAGE, status_code=403)
        if path == "/tv" and request.query_params.get("tv"):
            if security.secrets.compare_digest(request.query_params["tv"], keys.tv):
                resp = RedirectResponse("/tv", status_code=303)
                resp.set_cookie(TV_COOKIE, keys.tv, max_age=COOKIE_AGE, httponly=True, samesite="lax")
                return resp
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        role = security.role_for(client_ip(request), request.cookies, keys)
        if role is None:
            if path in ("/", "/remote"):
                return HTMLResponse(JOIN_PAGE, status_code=403)
            return JSONResponse({"detail": "Scan the QR code on the TV to join"}, status_code=403)
        if role != "tv" and path in TV_ONLY:
            return JSONResponse({"detail": "TV only"}, status_code=403)
        resp = await call_next(request)
        if path.startswith("/media/"):
            resp.headers["Cache-Control"] = "no-cache"  # always revalidate (ETag), never trust a stale stem
        return resp

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
        return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

    @app.get("/api/search")
    async def search(request: Request, q: str):
        throttle("search", request)
        q = q.strip()[:200]
        if not q or resolver.classify_input(q) != "query":
            raise HTTPException(400, "type a song name, or paste a link to add it")
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
    async def add(request: Request, req: AddRequest):
        throttle("add", request)
        vid, title = req.video_id, req.title
        if not vid and req.input:
            kind = resolver.classify_input(req.input)
            if kind == "query":
                raise HTTPException(400, "pick a search result")
            try:
                vid = await asyncio.to_thread(resolver.resolve, req.input)
            except resolver.NoMatch as e:
                raise HTTPException(404, f"No matching video: {e}")
            except Exception:
                log.exception("resolving %r failed", req.input)
                raise HTTPException(502, "Couldn't look that link up")
        if not vid or not security.is_video_id(vid):
            raise HTTPException(400, "nothing to add")
        try:
            e = hub.add(vid, title, client_ip(request))
        except Duplicate as d:
            raise HTTPException(409, str(d))
        await hub.broadcast()
        return {"id": e.id, "video_id": vid, "status": e.status}

    @app.post("/api/lyrics")
    async def paste_lyrics(request: Request, req: LyricsRequest):
        throttle("lyrics", request)
        if not cache.is_complete(req.video_id):
            raise HTTPException(409, "song is still being prepared")
        if lyrics_lock.locked():
            raise HTTPException(429, "Another song's lyrics are being synced, try again in a minute")
        async with lyrics_lock:
            try:
                meta = await asyncio.to_thread(pipeline.replace_lyrics, req.video_id, cache, req.text)
            except ValueError as e:
                raise HTTPException(400, str(e))
        await hub.broadcast({"type": "lyrics_updated", "video_id": req.video_id})
        return {"lyrics_mode": meta["lyrics_mode"], "align_prob": meta.get("align_prob"), "offset": meta.get("lyrics_offset")}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket, role: str = "remote"):
        if not (security.host_ok(ws.headers.get("host"), allowed) and security.origin_ok(ws.headers.get("origin"), allowed)):
            await ws.close(code=1008)
            return
        granted = security.role_for(client_ip(ws), ws.cookies, keys)
        if granted is None:
            await ws.close(code=1008)
            return
        role = "tv" if role == "tv" and granted == "tv" else "guest"
        await ws.accept()
        hub.sockets[ws] = role
        msg_limit = RateLimiter(30, 1.0)
        await ws.send_text(json.dumps({"type": "state", **hub.party.snapshot()}, ensure_ascii=False))
        try:
            while True:
                raw = await ws.receive_text()
                if not msg_limit.allow("ws"):
                    continue
                msg = security.parse_message(raw, role)
                if msg is not None:
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
    print(f"\n  TV (this computer):   http://localhost:{args.port}/tv")
    print(f"  TV (another device):  {app.state.tv_url}")
    print(f"  Guests: scan the QR code on the TV  ({app.state.remote_url})\n", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning", ws_max_size=security.WS_MAX_BYTES)


if __name__ == "__main__":
    main()
