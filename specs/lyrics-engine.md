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
- WHEN lyrics are synced THEN the line text is also aligned to `vocals.flac` and each word gets a
  time inside its own line (D-lyrics-engine-8); line start times never move. WHEN fewer than 35% of
  the words align inside their lines, or alignment fails, THEN the lines keep line times only.
- WHEN no synced lyrics fit THEN plain text from LRCLIB (any duration) or, for `he`, Shironet is aligned
  to `vocals.flac` with stable-ts, every word gets a time anchored on the confident words
  (D-lyrics-engine-6), `lyrics.lrc` is written in enhanced LRC (`[mm:ss.xx]<mm:ss.xx>word …`), and
  `lyrics_mode` is `aligned`.
- WHEN alignment raises, runs past 300s, or anchors fewer than 35% of the words in order THEN Whisper
  transcribes the vocal stem instead (`transcribed`, with word times); only if that also fails is the
  text shown as a `teleprompter`.
- WHEN no lyrics text is found THEN Whisper transcribes the vocal stem into timed lines with word times
  and `lyrics_mode` is `transcribed`.
- `process_song.py --relyric-all` re-runs this for every cached song, keeping pasted lyrics (pasted
  synced lyrics without word times get them added).
- WHEN nothing works THEN `lyrics_mode` is `none` and the song still plays.
- `meta.json` always records `vocal_start` and `vocal_end`, the first and last vocal activity.

### Pasted lyrics

A guest can replace a ready song's lyrics from `/remote`.

- WHEN the paste has 3 or more timestamped LRC lines THEN it is offset-corrected like LRCLIB lyrics,
  gets word times the same way unless it already has them, and `lyrics_mode` is `synced`.
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
- **D-lyrics-engine-3 — No lead on aligned times** (was 0.3s). The 0.3s lead was tuned on the buggy
  token-count mapping. With anchored word times, "vampire" against its hand-synced LRCLIB timings:
  median |error| 0.29s at lead 0 (signed −0.28s: slightly early, good for karaoke), 0.58s at 0.3s.
- **D-lyrics-engine-4 — No Genius.** Its API and pages sit behind a Cloudflare bot challenge; the app
  does not work around bot checks. Transcription and pasted lyrics cover the gap.
- **D-lyrics-engine-5 — Artist must match too.** A different artist's song with the same title and
  length (e.g. two Hebrew "מיליון דולר" songs) is rejected; title ≥0.6 and artist ≥0.5 similarity
  on Hebrew-normalised text (niqqud and ו/י removed, so מליון = מיליון).
- **D-lyrics-engine-6 — Words are placed by character position and anchored on confident words.**
  The aligner merges and splits tokens ("-" + "נושכת" → "- נושכת"), so counting tokens shifted every
  later line onto the wrong word: on "פנתרה" lines were a median 2.27s off and 22 of 52 more than 2s
  off. Now each aligner word is located by character position; words with probability ≥ 0.5 that
  keep moving forward in time (longest increasing run) are anchors, and every other word is placed
  by character position between anchors. Against a Whisper transcription of the vocals: median
  0.20s, 30 lines within 0.5s, 5 over 2s. The quality gate is the share of words anchored (≥ 35%), not
  mean probability: "עטור מצחך" (a live recording with talking) had 4% anchors, all in its first 11s,
  so it is transcribed instead; "פנתרה" 74%, "ירח" 67%.
- **D-lyrics-engine-7 — No Silero VAD in transcription.** stable-ts downloads it from GitHub at run
  time, which fails behind TLS-inspecting proxies; its built-in loudness-based silence detection is
  enough on an isolated vocal stem.
- **D-lyrics-engine-8 — Synced lyrics get word times inside their line windows.** Hand-synced line
  starts are better than the aligner's, so they stay; the aligner only places words within them.
  A line's first word starts at the line start, and a confident word (probability ≥ 0.5) is an
  anchor only when it falls between its line's start and the next line's start, so a word aligned
  into a neighbouring line can't drag it. Words after the last anchor run on at the song's singing
  rate and are squeezed to end 0.15s before the next line. Rejects replacing synced lines with the
  aligned ones (their line starts are worse: median 0.29s off on "vampire", D-lyrics-engine-3).
