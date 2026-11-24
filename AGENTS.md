# Home Karaoke

A single local process on the machine connected to the TV: a Python (FastAPI, `uv`) host that
turns a YouTube URL, Spotify track URL or search query into cached karaoke stems and synced
lyrics, a full-screen `/tv` player, and a phone `/remote` on the same Wi-Fi.

Run: `uv run python -m karaoke.server` (Milestone 3) or `uv run python process_song.py <input>`
(Milestone 1). Test: `uv run pytest`. System dependency: `ffmpeg` on `PATH`.

## Method declarations

- Principles: METHOD.md only.
- Release: none. The product runs from a local checkout; "released" means `master` at a
  tagged commit, started on the TV machine.
- Person acts:
  - `tv-sitting` — the owner, at the TV machine with the TV on and a phone on the same
    Wi-Fi: start the server, open `/tv`, tap to start audio, scan the QR code. Per-sitting.

## Rules

- Work on a feature branch; never commit to `master` directly.
- Tests first for pure logic (pytest for Python, a pure function per decision in the player's JS).
- Keep functions small enough to unit-test on their own.
