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

### Library

`/remote` lists already-processed songs ("Ready to sing") for one-tap re-adding.

## Design notes

- **D-party-queue-1 — One serial worker.** One GPU runs one separation well; parallel jobs slow both.
- **D-party-queue-2 — No auth on `/remote`.** Home LAN party; anyone on the Wi-Fi is a guest.
