# Add home karaoke app

Source: converted from `~/Downloads/openspec/changes/add-home-karaoke-app/` (OpenSpec), with
the 2026-11-24 review applied.

## Why

Browser karaoke can't remove vocals from YouTube or Spotify: cross-origin YouTube iframes
can't be routed through Web Audio, and Spotify's Web Playback SDK is DRM-protected. Hebrew
songs rarely have synced lyrics in public databases. For a home party, the host wants to paste
any song from a phone and have it play on the TV a few minutes later: backing track, an
adjustable vocal guide, a muted background video and lyrics that follow the singer, in Hebrew
or English. Observable outcome: on a karaoke night, guests queue songs from their phones by
QR code, and each song plays on the TV with lyrics in time, without waiting between songs that
were queued a few minutes earlier.

## Specs

All four specs are new and now carry their requirements (moved in 0ac876f):
`specs/media-pipeline.md`, `specs/lyrics-engine.md`, `specs/karaoke-player.md`, `specs/party-queue.md`.

Changed from the plan while building:
- Lyrics are looked up under English/alternate names too ("מיליון דולר" is on LRCLIB only as
  "Million Dollar" by "Noa Kirel"), and an LRCLIB hit must match the artist as well as the title.
- Genius is dropped (Cloudflare bot check); Whisper transcription of the vocal stem and
  **pasted lyrics** from `/remote` fill the gap.
- `--fast` separation mode (MDX-Net) next to the default BS-RoFormer.

## Prior art

- New repository: no specs, ideas or open changes exist. Nothing to keep or override.
- OpenSpec source `add-home-karaoke-app` — keep its architecture (local FastAPI host, Web Audio
  clock, `cache/<video_id>/`, `/tv` + `/remote`); override its open "A or B" choices, MP3 stems,
  0.15s hard-seek drift fix, `ytsearch1:`, and `lyrics.lrc` holding plain text (D1–D7).

## Decisions

- D1 → D-media-pipeline-1 in specs/media-pipeline.md (revised: BS-RoFormer overlap 2 + fp16; the
  90s budget was missed — ~150s per song — but songs prepare while the previous one plays; `--fast`
  is ~35s)
- D2 → D-media-pipeline-2 in specs/media-pipeline.md
- D3 → D-lyrics-engine-2 in specs/lyrics-engine.md
- D4 → D-karaoke-player-1 in specs/karaoke-player.md
- D5 → D-media-pipeline-3 in specs/media-pipeline.md
- D6 → D-lyrics-engine-1 in specs/lyrics-engine.md
- D7 → D-party-queue-1 in specs/party-queue.md
- D8 Sequencing: CLI engine (M1), then player (M2), then party mode (M3). Governs the work only.
- D9 → D-party-queue-2 in specs/party-queue.md
- D10 → D-lyrics-engine-4 in specs/lyrics-engine.md (no Genius)
- D11 → D-media-pipeline-4 in specs/media-pipeline.md (OS trust store)

## Tasks

### M1 — CLI engine
- [x] 1.1 `uv` project with yt-dlp, audio-separator, stable-ts, faster-whisper, httpx, bs4,
  soundfile, truststore, pytest — 0ac876f
- [x] 1.2 `resolver.py` (URL forms, Spotify OG parsing, scoring, `no_match`) — 0ac876f;
  live Spotify check 2026-11-24: vampire → 220s lyric video over the 245s music video
- [x] 1.3 `cache.py` staging/atomic commit — 0ac876f; live-process-safe staging cleanup — 17e10a1
- [x] 1.4 `media.py` 720p avc1 download + FLAC stems, equal sample counts (9,696,256 = 9,696,256)
  — 0ac876f
- [x] 1.5 Lyrics engine (`sources.py`, `engine.py`, `lrc.py`, `vocals.py`, `align.py`) with
  aliases, offset correction, alignment, transcription, paste — 0ac876f + this branch; 78 pytest
- [x] 1.6 Benchmark 2026-11-24 (M4 Pro), `process_song.py`:
  - vampire (245s music video): 189s; LRCLIB synced, offset −0.4s; 54/54 line starts on singing;
    independent re-alignment median 0.22s
  - מיליון דולר: 142s; LRCLIB synced via English alias, offset +0.1s; 56/56 on singing;
    re-alignment median 0.22s
  - פנתרה: 211s; LRCLIB plain + ivrit-ai alignment, prob 0.73; 52/52 on singing
  - שלמה ארצי — ירח (via server queue): 229s; Shironet + alignment, prob 0.76
  - Pass on "<5 min end to end"; the 0.3s target is met as a median (0.22s) on synced songs,
    plain-text Hebrew alignment is median 0.41s (46/56 lines within 1s).

### M2 — Player
- [x] 2.1 `core.js` pure logic (LRC, active line, clock, drift, teleprompter, gain) — 6 node tests
- [x] 2.2 `/tv` tap-to-start, dual-stem playback, seek/resume, video sync — browser check
  2026-11-24: drift −7 to −102ms during playback, rate nudge only
- [x] 2.3 BiDi lyric renderer (`dir=auto`, `unicode-bidi: plaintext`) and teleprompter — Hebrew
  and English lines checked on screen 2026-11-24
- [x] 2.4 On-screen vocal slider and transport — 0ac876f

### M3 — Party mode
- [x] 3.1 Queue state machine — 7 pytest (`tests/test_party.py`)
- [x] 3.2 FastAPI app, serial worker, `/ws` — browser check 2026-11-24: status QUEUED →
  DOWNLOADING → … → READY broadcast, auto-play when ready, dedupe 409 "Already in queue"
- [x] 3.3 `/remote` search picker, queue badges, vocal slider, pause/resume/skip/seek, library,
  **paste lyrics** — browser check 2026-11-24: pasted LRC shifted +5s corrected by −4.9s, TV
  reloaded lyrics mid-song; pasted Hebrew plain text aligned 56/56 lines in 97s
- [x] 3.4 LAN IP (skips VPN `utun`, `bridge`) + QR — QR showed `http://10.0.0.4:8765/remote` (en0)

### Left for a person
- [ ] (waiting: Raphael on tv-sitting — the TV, a phone on the same Wi-Fi) 4.1 Sing one
  Hebrew and one English song on the real TV; the build was verified in a browser on this
  machine, not over HDMI with a phone

## Surface review

Surface review: N/A — no surface review is declared; the only users are guests on the home LAN.

## Verification

Pending.
