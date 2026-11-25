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

Needs macOS or Linux, [`uv`](https://docs.astral.sh/uv/), `ffmpeg` and [Deno](https://deno.com) on
`PATH`: `brew install ffmpeg deno` on macOS; on Debian/Ubuntu `sudo apt install ffmpeg` and the
[Deno installer](https://docs.deno.com/runtime/getting_started/installation/). YouTube protects many
official music videos with a JavaScript challenge that yt-dlp solves with Deno; without it those
videos fail to download. Node is needed only to run the JavaScript tests.

```bash
git clone https://github.com/raficohen17/home-karaoke.git
cd home-karaoke
uv sync
uv run python -m karaoke.server            # http://<this-machine>:8765
```

On start the server prints three links: the TV page on this computer, a TV link for another
device, and the guest link that the QR code carries.

1. On the machine connected to the TV, open `http://localhost:8765/tv` full screen and tap **Tap to start**.
   To use a smart TV or another computer as the TV instead, open the printed
   `http://<this-machine>:8765/tv?tv=...` link on it. Only one TV plays at a time.
2. Guests scan the QR code on the TV, search for a song, and tap the right result. Phones must be on
   the same Wi-Fi as the computer running the server. On macOS, allow incoming connections when the
   firewall asks.
3. A song takes about 2–3 minutes to prepare; later songs are prepared while the current one plays.

**First run is slow.** Models download the first time they're needed: about 2.5 GB into `models/`
for vocal removal, about 1.2 GB for English lyric alignment (torch hub cache), about 4 GB for Hebrew
lyric alignment and 1.6 GB for Whisper language detection (Hugging Face cache). Expect the first
song to take several extra minutes.

The party keys change every time the server starts, so guests rescan the QR code after a restart.

Server options:

| Flag | Meaning |
|---|---|
| `--port 8765` | Port to listen on |
| `--host-ip 192.168.1.20` | Address put in the QR code, if auto-detection picks the wrong network |
| `--fast` | Vocal removal in ~35s instead of ~1.5min, lower quality |
| `--cache cache` | Folder where prepared songs are stored |

Process songs without the server:

```bash
uv run python process_song.py "olivia rodrigo vampire"   # one song, by name or link
uv run python process_song.py --restem-all    # redo vocal removal for every cached song (keeps lyrics)
uv run python process_song.py --relyric-all   # redo lyrics for every cached song (keeps pasted ones)
```

`process_song.py` takes `--fast` and `--cache` too.

## How lyrics are found

1. **LRCLIB synced lyrics** — tried under the Hebrew and English names of the song; used only if the
   recording length matches, and shifted to the singer's first notes (videos often have longer intros).
2. **Plain text + forced alignment** — LRCLIB plain lyrics or Shironet (Hebrew), aligned to the
   isolated vocal track with Meta's MMS wav2vec2 aligners (Hebrew adapter for Hebrew). Synced
   lyrics get per-word times the same way.
3. **Paste lyrics** — on the remote, "Lyrics wrong or missing? Paste them": plain text is aligned
   automatically; LRC is shifted to fit the video.

If the alignment is unsure (the lyrics may be for another version or song), the TV shows the text as a scrolling teleprompter with speed controls.
The app never transcribes lyrics from the audio: when none are found, the TV says so and the remote
puts that song first in the paste box.

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
