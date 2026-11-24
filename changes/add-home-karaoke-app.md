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
- [ ] 1.1 `uv` project: `yt-dlp`, `audio-separator`, `stable-ts`, `faster-whisper`, `httpx`,
  `beautifulsoup4`, `soundfile`, `pytest`; README notes `ffmpeg`.
- [ ] 1.2 Tests, then `resolver.py`: YouTube URL forms, Spotify OG parsing (fixture HTML),
  candidate scoring and `no_match` as pure functions.
- [ ] 1.3 Tests, then `cache.py`: staging path, completeness check on `meta.json` status,
  atomic rename, staging cleanup.
- [ ] 1.4 `separator.py`: download with the 720p avc1 selector, separate to FLAC, assert equal
  sample counts.
- [ ] 1.5 Tests, then `lyrics.py`: language rule, waterfall choice, LRC duration match, offset
  shift, confidence/timeout fallback, vocal onset detection — each a pure function over
  fixtures; network fetchers stay thin.
- [ ] 1.6 `process_song.py <input>`; benchmark one English and one Hebrew song: total time,
  separation time, and lyric lines within 0.3s of the singer (spot-check 10 lines). Pass if
  each song is under 5 minutes end to end and at least 8/10 lines are in time.

### M2 — Player
- [ ] 2.1 Tests, then `clock.js` (song position, drift decision) and `lrc.js` (parser, active
  line) as pure functions.
- [ ] 2.2 `/tv` tap-to-start, dual-stem loader, gain ramp, seek/resume, video sync loop.
- [ ] 2.3 BiDi lyric renderer and teleprompter scroll with speed nudges.
- [ ] 2.4 On-screen vocal guide slider and play/pause/seek.

### M3 — Party mode
- [ ] 3.1 Tests, then the queue state machine (statuses, dedupe, reorder/remove, skip past
  `FAILED`, "preparing").
- [ ] 3.2 FastAPI app: serial `asyncio` worker, static `cache/`, `/ws` broadcasting queue,
  progress, vocal level, `audio_ready`, and playback position.
- [ ] 3.3 `/remote`: URL paste, search results picker, queue with status badges and reasons,
  reorder/remove, vocal slider, pause/skip, teleprompter nudges.
- [ ] 3.4 Host-IP detection with `--host-ip` override; QR overlay on `/tv`.

## Surface review

Surface review: N/A — no surface review is declared; the only users are guests on the home LAN.

## Verification

Pending.
