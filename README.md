# Home Karaoke

> **Educational experiment.** This project explores audio source separation, lyric alignment and
> local web apps. It is not a product or a service. You are responsible for making sure your use
> complies with the laws where you live and with the terms of use of every site and service it
> touches (YouTube, Spotify, LRCLIB, Shironet and others), including copyright in songs, videos
> and lyrics. See [Disclaimer](#disclaimer).

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
3. The first song takes about 2–3 minutes to prepare; later songs are prepared while the current one plays.

Options: `--fast` (vocal removal in ~35s instead of ~1.5min, lower quality), `--host-ip 192.168.1.20`
(the address in the QR code, if auto-detection picks the wrong network), `--port`.

Process a single song without the server:

```bash
uv run python process_song.py "olivia rodrigo vampire"
uv run python process_song.py --restem-all   # redo vocal removal for every cached song
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

## Safety

The server prints a TV link and a guest link on start. Guests join only through the QR code (it carries
a random key that changes every run); other devices on the network, VPN peers and websites can't
control the party. The TV is this computer, or any device opened with the printed TV link. Song ids,
messages and uploads are validated and rate-limited; see `specs/party-queue.md` → "Access and safety".

## Disclaimer

This is an educational experiment, provided as is, without warranty of any kind (see
[LICENSE](LICENSE)).

- **Your responsibility.** Before using it, check that downloading, processing, displaying or
  sharing media and lyrics is allowed for you. That depends on local law, including copyright, and
  on the terms of use of the services involved. Downloading from YouTube, for example, may be
  against its terms of service.
- **No content included.** The repository ships no songs, videos, lyrics or model weights. Anything
  the app fetches comes from third-party services at your request, under their terms. The machine
  learning models are downloaded from their publishers under their own licenses.
- **Private, non-commercial use.** It is meant for a home setting. Don't use it to host public or
  paid events, redistribute content, or run it as a service.
- **No affiliation.** Not affiliated with, endorsed by or connected to YouTube, Google, Spotify,
  LRCLIB, Shironet/Mako or any artist or rights holder. Names are used only to identify the
  services the software works with.

## License

The source code is released under the [MIT License](LICENSE). The license covers this code only.
It does not cover the content you process with it or the third-party models and libraries it uses,
which keep their own licenses and terms.
