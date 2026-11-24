# Party queue

The FastAPI host that holds the queue, prepares songs in the background and relays control between
phones and the TV. Code: `karaoke/server.py`, `karaoke/party.py`, `karaoke/netinfo.py`,
`karaoke/static/remote.*`.

## Requirements

### Serial background worker

One worker prepares queued songs in FIFO order, one at a time, while the current song plays.

- WHEN a song is queued THEN every client sees it move through `QUEUED`, `DOWNLOADING` (with %),
  `SEPARATING`, `ALIGNING`, then `READY` or `FAILED` with a reason.
- WHEN the same `video_id` is already queued or playing THEN nothing is added and the guest sees
  "Already in queue".
- WHEN a cached song is added THEN it is `READY` at once.

### Queue control

Guests can move up and remove songs that aren't playing, pause/resume, skip, seek ±10s, set the vocal
guide, and nudge the teleprompter. The server holds the queue; playback commands go to `/tv`.

- WHEN the current song ends or is skipped THEN the first `READY` song plays; `FAILED` songs are
  dropped; WHEN nothing is ready THEN `/tv` shows "Up next — preparing (<status>)".

### Join by QR

`/tv` shows a QR code for `http://<host-ip>:<port>/remote`.

- WHEN the host has several interfaces THEN `<host-ip>` is a private IPv4 on a physical interface
  (Wi-Fi/Ethernet, 192.168.* first), skipping VPN tunnels and bridges, or `--host-ip` when given.

### Access and safety

Threat model: anyone on the same network or a VPN peer, and any website open in a guest's or the
host's browser.

- WHEN a phone opens `/remote` without the party key THEN it sees "Scan the QR code on the TV to join"
  and every API, media and WebSocket request gets 403.
- WHEN a guest scans the QR code (`/remote?k=<party key>`) THEN an HttpOnly, SameSite=Lax cookie lets
  that browser use the remote for 12 hours.
- WHEN a page is the TV THEN it runs on this machine (loopback) or was opened with the TV link the
  server prints (`/tv?tv=<TV key>`); `/tv`, `/qr.svg` and `/api/info` refuse guests, and a guest's
  `?role=tv` socket is downgraded so it can't silence the TV, report positions or end songs.
- WHEN a request's Host header doesn't name this server THEN it gets 421 (DNS rebinding); WHEN a
  WebSocket's Origin isn't one of this server's pages THEN it is refused (cross-site hijacking).
- WHEN a song id isn't an 11-character YouTube id THEN the request gets 422 and the cache layer
  refuses it too, so `../` can never reach the filesystem.
- WHEN WebSocket messages are malformed, out of range, NaN/Infinity, over 64 KB, or over 30 per second
  THEN they are dropped and the socket stays open.
- Limits: queue 40 songs; 5 songs in preparation per guest; videos ≤ 15 minutes and no live streams;
  pasted lyrics ≤ 20,000 characters, one sync at a time; per guest per minute 20 searches, 10 adds,
  4 lyric pastes. Failure reasons shown to guests carry no local paths. No API docs are served.

### Library

`/remote` lists already-processed songs ("Ready to sing") for one-tap re-adding.

## Design notes

- **D-party-queue-1 — One serial worker.** One GPU runs one separation well; parallel jobs slow both.
- **D-party-queue-2 — superseded by D-party-queue-3.**
- **D-party-queue-3 — Party key in the QR code, not open access** (overrides D-party-queue-2). The
  2026-11-24 red team showed open access let any device on the network, or any website in a guest's
  browser, delete folders on the host (`video_id` path traversal), hijack the control socket and
  silence the TV. A per-run random key in the QR code is as easy for guests as before and stops
  strangers; the cookie is SameSite=Lax and HttpOnly. Loopback is trusted as the TV because a
  browser can't forge it and the Host/Origin checks stop rebinding. Rejects a typed PIN (friction)
  and accounts (overkill for a party).
