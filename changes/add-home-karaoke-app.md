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

### `specs/media-pipeline.md` (new)

**Requirement: Source resolution.** The pipeline resolves a YouTube URL, a Spotify track URL,
or a free-text query (Hebrew or English) to one YouTube `video_id`.

- WHEN a guest submits a YouTube URL (`watch?v=`, `youtu.be/`, `shorts/`, `music.youtube.com`)
  THEN the pipeline uses that URL's `video_id` without searching.
- WHEN a guest submits a Spotify track URL THEN the pipeline reads the track title, artist and
  duration from the Spotify page metadata (`og:title`, `og:description`, `music:duration`),
  searches YouTube for `<artist> - <title>` (`ytsearch5:`), and picks the candidate with the
  best score: duration within ±3s of Spotify's first, then "Topic"/"Official Audio" uploads,
  then view count.
- WHEN no candidate is within ±10s of the Spotify duration THEN the job ends `FAILED` with
  reason `no_match`.
- WHEN a guest submits free text THEN `/remote` shows the top 5 YouTube results (title,
  channel, duration, thumbnail) and queues the one the guest taps.

**Requirement: Download.** The pipeline downloads video capped at 720p H.264
(`bv*[height<=720][vcodec^=avc1]+ba`) and the best audio into a staging directory.

- WHEN yt-dlp fails (age-restricted, region-blocked, removed, extractor error) THEN the job
  ends `FAILED` with yt-dlp's reason, and the queue moves on.

**Requirement: Stem separation.** The pipeline separates the audio into `instrumental.flac`
and `vocals.flac` with the same sample rate and the same sample count.

- WHEN separation finishes THEN both stems decode to equal sample counts (a check in code, not
  a tolerance).

**Requirement: Atomic cache.** A song directory `cache/<video_id>/` exists only once it is
complete.

- WHEN the pipeline works on a song THEN it writes to `cache/.staging/<video_id>/` and renames
  it to `cache/<video_id>/` as its last step, with `meta.json` carrying `"status": "complete"`.
- WHEN `cache/<video_id>/meta.json` has `"status": "complete"` THEN a request for that song is
  `READY` immediately, with no download or separation.
- WHEN the host process starts THEN it deletes `cache/.staging/`.

### `specs/lyrics-engine.md` (new)

**Requirement: Language.** The engine records `language` (`he` or `en`) in `meta.json`.

- WHEN the title or artist contains Hebrew letters THEN `language` is `he`; otherwise the
  engine runs Whisper language detection on the first 30s of vocals and records the result.

**Requirement: Lyrics waterfall.** The engine tries synced lyrics, then plain text with
forced alignment, then a teleprompter, and playback never waits on lyrics past `READY`.

- WHEN LRCLIB returns synced lyrics whose duration is within ±2s of the downloaded audio THEN
  the engine shifts them by the measured offset (first LRC timestamp vs the first vocal onset
  in `vocals.flac`), writes `lyrics.lrc`, and sets `lyrics_mode: "synced"`.
- WHEN no synced match fits THEN the engine fetches plain text from Shironet (`he`) or Genius
  (`en`, and the fallback for `he`), aligns it to `vocals.flac` with stable-ts, writes
  `lyrics.lrc`, and sets `lyrics_mode: "aligned"`.
- WHEN alignment raises, runs past 180s, or its mean word probability is below 0.5 THEN the
  engine writes the plain text to `lyrics.txt`, records the first and last vocal onsets
  (`vocal_start`, `vocal_end`) in `meta.json`, and sets `lyrics_mode: "teleprompter"`.
- WHEN no source returns lyrics THEN `lyrics_mode` is `"none"` and the song still plays.

### `specs/karaoke-player.md` (new)

**Requirement: Audio unlock.** `/tv` starts behind a full-screen "Tap to start" that resumes
the `AudioContext`; later songs start without a gesture.

- WHEN `/tv` loads THEN it shows "Tap to start" until tapped, and the server marks the TV
  `audio_ready: false`, which `/remote` shows as "TV needs a tap".

**Requirement: Dual-stem playback.** `/tv` plays both stems from one `AudioContext`, each
through its own `GainNode`, started with one `start(when, offset)` call so they stay aligned to
the sample.

- WHEN the vocal guide moves between 0% and 100% (TV or remote) THEN the vocals gain ramps to
  the new value over 50ms (`setTargetAtTime`) with no click, and the instrumental stays at 100%.
- WHEN the singer seeks or resumes THEN the player makes new source nodes for both stems at
  the same `when` and offset.

**Requirement: Song clock.** Song position is
`ctx.currentTime - startedAt + offset - ctx.outputLatency`; lyrics and video both follow it.

- WHEN video drift from the song clock is between 0.05s and 0.5s THEN the player sets
  `video.playbackRate` to 0.95 or 1.05 until drift is under 0.05s.
- WHEN drift exceeds 0.5s THEN the player seeks the video once and waits 1s before checking
  again.

**Requirement: BiDi-safe lyrics.** Each lyric line has `dir="auto"` and
`unicode-bidi: plaintext`; the active line is highlighted and centered over the video dimmed
to `brightness(0.35)`.

- WHEN a Hebrew, English or mixed line is shown THEN its punctuation sits on the reading side
  of that line's own direction.

**Requirement: Teleprompter.** In `teleprompter` mode the text scrolls from `vocal_start` to
`vocal_end`, with `+` / `-` speed nudges on `/tv` and `/remote`.

**Requirement: Resume after reload.** WHEN `/tv` reloads mid-song THEN it resumes the current
song from the position the server last received, after the tap.

### `specs/party-queue.md` (new)

**Requirement: Serial background worker.** One worker processes queued songs in FIFO order,
one at a time, while the current song plays.

- WHEN a song is queued THEN every client sees its status move through `QUEUED`,
  `DOWNLOADING`, `SEPARATING`, `ALIGNING`, then `READY` or `FAILED` (with a reason).
- WHEN the same `video_id` is already queued or playing THEN the queue adds nothing and the
  guest sees "Already in queue".

**Requirement: Queue control.** Guests can remove and reorder songs that aren't playing,
pause/resume, skip, and set the vocal guide; the server holds the queue and relays playback
commands to `/tv`.

- WHEN the current song ends or is skipped THEN the next `READY` song plays; `FAILED` songs are
  passed over, and a song still processing shows "Up next — preparing (<status>)" on `/tv`
  until it is ready.

**Requirement: Join by QR.** `/tv` shows a QR code for `http://<host-ip>:<port>/remote`.

- WHEN the host has several interfaces THEN `<host-ip>` is the private IPv4 address of the
  default-route interface, or `--host-ip` when given.
- WHEN a guest scans the QR code on the same Wi-Fi THEN `/remote` opens with the live queue.

## Prior art

- New repository: no specs, ideas or open changes exist. Nothing to keep or override.
- OpenSpec source `add-home-karaoke-app` — keep its architecture (local FastAPI host, Web Audio
  clock, `cache/<video_id>/`, `/tv` + `/remote`); override its open "A or B" choices, MP3 stems,
  0.15s hard-seek drift fix, `ytsearch1:`, and `lyrics.lrc` holding plain text (D1–D7).

## Decisions

- **D1 Separator: `audio-separator` with a BS-RoFormer vocal model.** It is one Python
  dependency that also runs MDX-Net and Demucs models, so swapping is a config line. Rejects
  carrying both `audio-separator` and `demucs` as undecided options. Task 1.6 measures time
  per song; if it's over 90s for a 4-minute song on the host, switch the model, not the library.
- **D2 Stems are FLAC, not MP3.** MP3 encoder delay and padding vary by decoder and break
  sample alignment; FLAC decodes to the same sample count everywhere `decodeAudioData` runs.
  Rejects MP3 with a 20ms tolerance. Cost is about 25MB per stem on local disk.
- **D3 Alignment: stable-ts on faster-whisper**, using `ivrit-ai/whisper-large-v3-turbo-ct2` for
  `he` and `large-v3-turbo` for `en`. faster-whisper runs on CPU at usable speed where PyTorch
  MPS support is uneven. Rejects openai-whisper `large-v3` as one model for both languages.
- **D4 Video drift: rate nudge, then a rare hard seek** (thresholds in karaoke-player). Seeking
  H.264 lands on keyframes, so seeking at every 0.15s of drift stutters. Rejects the source's
  hard seek at 0.15s.
- **D5 Spotify metadata from the track page's Open Graph tags.** oEmbed doesn't reliably carry
  the artist, and the Web API needs credentials. Rejects oEmbed-only and a Spotify developer app.
- **D6 Synced lyrics are offset-corrected against the vocal stem.** LRCLIB timestamps are for
  the album audio, and YouTube uploads add intros. Rejects trusting LRCLIB timestamps as-is.
- **D7 One serial worker.** One GPU/MPS device runs one separation well; parallel jobs slow
  both. Rejects a worker per queued song.
- **D8 Sequencing: CLI engine (M1), then player (M2), then party mode (M3).** Each milestone is
  usable alone and the benchmark gates the model choices before UI work. Governs the work only.
- **D9 No auth on `/remote`.** Home LAN party; anyone on the Wi-Fi is a guest. Rejects PINs.
  Not a goal: hosting, licensing, mic scoring, native apps.

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
