# Home Karaoke

Turn any YouTube link, Spotify track link or song name (Hebrew or English) into karaoke on your TV:
AI vocal removal, an adjustable vocal guide, a dimmed music video in the background, and lyrics that
follow the singer. Guests queue songs from their phones by scanning a QR code.

## Run

Needs macOS or Linux, [`uv`](https://docs.astral.sh/uv/), and `ffmpeg` on `PATH`.

```bash
uv sync
uv run python -m karaoke.server            # http://<this-machine>:8765
```

1. On the machine connected to the TV, open `http://localhost:8765/tv` full screen and tap **Tap to start**.
2. Guests scan the QR code (or open `/remote`), search for a song, and tap the right result.
3. The first song takes about 3–4 minutes to prepare; later songs are prepared while the current one plays.

Options: `--fast` (vocal removal in ~35s instead of ~2.5min, lower quality), `--host-ip 192.168.1.20`
(the address in the QR code, if auto-detection picks the wrong network), `--port`.

Process a single song without the server:

```bash
uv run python process_song.py "olivia rodrigo vampire"
```

## How lyrics are found

1. **LRCLIB synced lyrics** — tried under the Hebrew and English names of the song; used only if the
   recording length matches, and shifted to the singer's first notes (videos often have longer intros).
2. **Plain text + forced alignment** — LRCLIB plain lyrics or Shironet (Hebrew), aligned to the
   isolated vocal track with Whisper (`ivrit-ai` model for Hebrew).
3. **Transcription** — Whisper transcribes the isolated vocals when no lyrics text is found.
4. **Paste lyrics** — on the remote, "Lyrics wrong or missing? Paste them": plain text is aligned
   automatically; LRC is shifted to fit the video.

If alignment confidence is low, the TV shows a scrolling teleprompter with speed controls.

## Test

```bash
uv run pytest
node --test tests/js/
node check-layout.mjs
```

Personal use only: downloading from YouTube may break its terms of service.
