"""Unit tests for karaoke.security and attack tests against the real app (in-process)."""
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from karaoke import media, pipeline, security
from karaoke.security import (
    GUEST_COOKIE,
    Keys,
    RateLimiter,
    allowed_hosts,
    host_ok,
    is_video_id,
    origin_ok,
    parse_message,
    public_reason,
    require_video_id,
    role_for,
)

# ---------- unit ----------


@pytest.mark.parametrize("vid", ["../../canary", "../../canary/", "abc", "RlPNh_PBZb4/..", "", "RlPNh_PBZb4x", "a b c d e f"])
def test_video_id_rejects_traversal_and_junk(vid):
    assert not is_video_id(vid)
    with pytest.raises(ValueError):
        require_video_id(vid)


def test_video_id_accepts_real_ids():
    assert is_video_id("RlPNh_PBZb4") and is_video_id("oQbh5Kvet04")


def test_roles():
    k = Keys()
    assert role_for("127.0.0.1", {}, k) == "tv" and role_for("::1", {}, k) == "tv"
    assert role_for("10.0.0.9", {"karaoke_tv": k.tv}, k) == "tv"
    assert role_for("10.0.0.9", {GUEST_COOKIE: k.guest}, k) == "guest"
    assert role_for("10.0.0.9", {GUEST_COOKIE: "wrong"}, k) is None
    assert role_for("10.0.0.9", {}, k) is None
    assert role_for(None, {}, k) is None


def test_host_and_origin_checks():
    allowed = allowed_hosts("10.0.0.4", 8765)
    assert host_ok("10.0.0.4:8765", allowed) and host_ok("localhost:8765", allowed)
    assert not host_ok("evil.example:8765", allowed) and not host_ok(None, allowed)
    assert origin_ok("http://10.0.0.4:8765", allowed)
    assert not origin_ok("http://evil.example", allowed)
    assert not origin_ok("http://10.0.0.4:8765.evil.example", allowed)
    assert not origin_ok(None, allowed) and not origin_ok("null", allowed)


@pytest.mark.parametrize(
    "raw",
    [
        '{"type":"vocal","level":NaN}',
        '{"type":"vocal","level":Infinity}',
        '{"type":"vocal","level":5}',
        '{"type":"seek","delta":1e308}',
        '{"type":"remove","id":"abc"}',
        '{"type":"move","id":1,"delta":1000000}',
        '{"type":"nudge","dir":"x"}',
        '{"type":"shutdown"}',
        "not json",
        '{"type":"vocal","level":0.5,"x":"' + "a" * 70000 + '"}',
    ],
)
def test_parse_message_rejects_bad_input(raw):
    assert parse_message(raw, "tv") is None


def test_parse_message_roles():
    assert parse_message('{"type":"vocal","level":0.4}', "guest") == {"type": "vocal", "level": 0.4}
    for tv_only in ('{"type":"audio_ready","ready":true}', '{"type":"ended","video_id":"RlPNh_PBZb4"}',
                    '{"type":"position","video_id":"RlPNh_PBZb4","t":3}'):
        assert parse_message(tv_only, "guest") is None
        assert parse_message(tv_only, "tv") is not None


def test_rate_limiter():
    t = [0.0]
    rl = RateLimiter(2, 10, clock=lambda: t[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    assert rl.allow("b")
    t[0] = 5.0
    assert rl.allow("a") and not rl.allow("a")


def test_public_reason_hides_paths():
    r = public_reason(media.DownloadError("[youtube] abcdefghijk: Video unavailable /Users/me/projects/x.py"))
    assert "/Users" not in r and "Video unavailable" in r
    assert public_reason(RuntimeError("/Users/me/secret")) == "Processing failed"
    assert "minutes" in public_reason(media.TooLong("live"))


def test_check_length():
    media.check_length({"duration": 200}, 900)
    for info in ({"duration": 4000}, {"is_live": True, "duration": 100}, {"live_status": "is_upcoming"}, {}):
        with pytest.raises(media.TooLong):
            media.check_length(info, 900)


# ---------- attacks against the app ----------


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    from karaoke.server import create_app

    calls = []

    def fake_process(vid, cache, status=None, mode="quality"):
        calls.append(vid)
        raise media.DownloadError("Video unavailable")

    monkeypatch.setattr(pipeline, "process", fake_process)
    keys = Keys()
    app = create_app(str(tmp_path / "cache"), host_ip="testserver", port=80, keys=keys)
    with TestClient(app) as c:
        yield c, keys, calls, tmp_path


def guest(c, keys):
    r = c.get(f"/remote?k={keys.guest}")
    assert r.status_code == 200 and GUEST_COOKIE in r.cookies
    return c


def test_no_key_no_access(app_env):
    c, keys, calls, _ = app_env
    for path in ("/api/library", "/api/search?q=x", "/media/x", "/qr.svg", "/api/info", "/tv"):
        assert c.get(path).status_code == 403, path
    assert c.post("/api/add", json={"video_id": "dQw4w9WgXcQ"}).status_code == 403
    assert "Scan the QR code" in c.get("/remote").text
    assert c.get("/remote?k=wrong").status_code == 403
    assert calls == []


def test_docs_are_off(app_env):
    c, keys, _, _ = app_env
    guest(c, keys)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404


def test_dns_rebinding_host_rejected(app_env):
    c, keys, _, _ = app_env
    guest(c, keys)
    assert c.get("/api/library", headers={"host": "evil.example"}).status_code == 421


def test_path_traversal_rejected(app_env):
    c, keys, calls, tmp_path = app_env
    guest(c, keys)
    canary = tmp_path / "canary"
    canary.mkdir()
    (canary / "keep.txt").write_text("precious")
    for vid in ("../../canary", "../../canary/", "../canary"):
        assert c.post("/api/add", json={"video_id": vid}).status_code == 422
        assert c.post("/api/lyrics", json={"video_id": vid, "text": "x" * 20}).status_code == 422
    assert (canary / "keep.txt").read_text() == "precious" and calls == []


def test_guest_cannot_reach_tv_endpoints(app_env):
    c, keys, _, _ = app_env
    guest(c, keys)
    assert c.get("/api/info").status_code == 403 and c.get("/qr.svg").status_code == 403


def test_queue_limits_and_rate_limit(app_env):
    c, keys, _, _ = app_env
    guest(c, keys)
    ids = [f"vid{n:08d}" for n in range(12)]
    codes = [c.post("/api/add", json={"video_id": v}).status_code for v in ids]
    assert 429 in codes  # per-client pending cap or the 10/min add limit kicks in
    assert codes[:5].count(200) >= 1


def test_lyrics_size_limit(app_env):
    c, keys, _, _ = app_env
    guest(c, keys)
    r = c.post("/api/lyrics", json={"video_id": "RlPNh_PBZb4", "text": "a" * (security.MAX_LYRICS_CHARS + 1)})
    assert r.status_code == 422


def test_websocket_cross_site_and_unauthenticated_rejected(app_env):
    c, keys, _, _ = app_env
    with pytest.raises(WebSocketDisconnect):  # no key
        with c.websocket_connect("/ws", headers={"origin": "http://testserver"}) as w:
            w.receive_text()
    guest(c, keys)
    with pytest.raises(WebSocketDisconnect):  # key, but a foreign page opened the socket
        with c.websocket_connect("/ws", headers={"origin": "http://evil.example"}) as w:
            w.receive_text()


def test_guest_cannot_act_as_tv(app_env):
    c, keys, _, _ = app_env
    guest(c, keys)
    hub = c.app.state.hub
    with c.websocket_connect("/ws?role=tv", headers={"origin": "http://testserver"}) as w:
        json.loads(w.receive_text())
        assert hub.sockets[next(iter(hub.sockets))] == "guest"  # role=tv was downgraded
        w.send_text('{"type":"audio_ready","ready":true}')
        w.send_text('{"type":"vocal","level":NaN}')
        w.send_text('{"type":"vocal","level":0.7}')
        msg = json.loads(w.receive_text())
        assert msg == {"type": "vocal", "level": 0.7}  # bad messages ignored, socket alive
    assert hub.party.audio_ready is False and hub.active_tv is None
