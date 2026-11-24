# Lyrics engine

Finds lyrics for a song and times them to the singer in this particular video. Code:
`karaoke/engine.py`, `karaoke/sources.py`, `karaoke/align.py`, `karaoke/lrc.py`, `karaoke/vocals.py`.

## Requirements

### Song name and aliases

The engine derives artist and title from the YouTube metadata, plus aliases lyrics databases may use.

- WHEN the title is `נועה קירל - מיליון דולר מארחת את שחר סאול - Million Dollar (Prod. by Jordi) | Noa Kirel`
  THEN the name is `נועה קירל` / `מיליון דולר`, with alias title `Million Dollar` and alias artist
  `Noa Kirel`.
- WHEN YouTube provides music metadata (track, artist) THEN it is the primary name.

### Language

`meta.json` records `language` (`he` or `en`).

- WHEN the title, channel or artist contains Hebrew letters THEN `language` is `he`; otherwise Whisper
  detects the language from the vocal stem.

### Lyrics waterfall

The engine tries, in order: synced lyrics, plain text aligned to the vocals, transcription of the
vocals. Playback never waits on lyrics after `READY`.

- WHEN LRCLIB (searched under every title/artist alias) returns synced lyrics with a matching title
  and artist whose duration is within ±2s of the audio THEN they are shifted by the offset that best
  lines the lyric lines up with vocal activity in `vocals.flac` (D-lyrics-engine-1), written to
  `lyrics.lrc`, and `lyrics_mode` is `synced`.
- WHEN no synced lyrics fit THEN plain text from LRCLIB (any duration) or, for `he`, Shironet is aligned
  to `vocals.flac` with stable-ts; lines start 0.3s before their first aligned word
  (D-lyrics-engine-3); `lyrics_mode` is `aligned`.
- WHEN alignment raises, runs past 300s, or its mean word probability is below 0.5 THEN the text is
  written to `lyrics.txt` and `lyrics_mode` is `teleprompter`.
- WHEN no lyrics text is found THEN Whisper transcribes the vocal stem into timed lines and
  `lyrics_mode` is `transcribed`.
- WHEN nothing works THEN `lyrics_mode` is `none` and the song still plays.
- `meta.json` always records `vocal_start` and `vocal_end`, the first and last vocal activity.

### Pasted lyrics

A guest can replace a ready song's lyrics from `/remote`.

- WHEN the paste has 3 or more timestamped LRC lines THEN it is offset-corrected like LRCLIB lyrics and
  `lyrics_mode` is `synced`.
- WHEN the paste is plain text THEN it is aligned to the vocals (or becomes a teleprompter when
  alignment is weak), `lyrics_source` is `pasted`, and the TV reloads the lyrics without restarting
  the song.

## Design notes

- **D-lyrics-engine-1 — Synced lyrics are offset-corrected against the vocal stem.** LRCLIB timings are
  for the album recording; music videos add intros. The offset (±30s, 0.1s steps) maximises overlap
  between lyric lines and vocal activity minus a penalty for lyrics over silence. Rejects using LRCLIB
  timestamps as they are.
- **D-lyrics-engine-2 — stable-ts on faster-whisper (CPU, int8, cores − 4 threads):** `ivrit-ai/whisper-large-v3-turbo-ct2`
  for Hebrew, `large-v3-turbo` for English. Rejects openai-whisper large-v3 on MPS (uneven support).
- **D-lyrics-engine-3 — Aligned lines lead by 0.3s.** On "vampire", aligned line starts ran a median
  0.46s later than the hand-synced LRCLIB times (mean word probability 0.82).
- **D-lyrics-engine-4 — No Genius.** Its API and pages sit behind a Cloudflare bot challenge; the app
  does not work around bot checks. Transcription and pasted lyrics cover the gap.
- **D-lyrics-engine-5 — Artist must match too.** A different artist's song with the same title and
  length (e.g. two Hebrew "מיליון דולר" songs) is rejected; title ≥0.6 and artist ≥0.5 similarity
  on Hebrew-normalised text (niqqud and ו/י removed, so מליון = מיליון).
