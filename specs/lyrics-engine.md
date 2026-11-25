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

The engine tries, in order: synced lyrics, then plain text aligned to the vocals. It never makes
lyrics up from the audio: a song with no lyrics found waits for a guest to paste them
(D-lyrics-engine-9). Playback never waits on lyrics after `READY`.

- WHEN LRCLIB (searched under every title/artist alias) returns synced lyrics with a matching title
  and artist whose duration is within ±2s of the audio THEN they are shifted by the offset that best
  lines the lyric lines up with vocal activity in `vocals.flac` (D-lyrics-engine-1), written to
  `lyrics.lrc`, and `lyrics_mode` is `synced`.
- WHEN lyrics are synced THEN the line text is also aligned to `vocals.flac` and each word gets a
  time inside its own line (D-lyrics-engine-8); line start times never move. WHEN fewer than 35% of
  the words align inside their lines, or alignment fails, THEN the lines keep line times only.
- WHEN no synced lyrics fit THEN plain text from LRCLIB (any duration) or, for `he`, Shironet is aligned
  to `vocals.flac` with a wav2vec2 CTC forced aligner (D-lyrics-engine-10), every word gets a time
  (D-lyrics-engine-6), `lyrics.lrc` is written in enhanced LRC (`[mm:ss.xx]<mm:ss.xx>word …`), and
  `lyrics_mode` is `aligned`.
- WHEN alignment raises, runs past 300s, or the mean word confidence is below 0.10 (English) or
  0.33 (Hebrew) THEN the text is shown as a `teleprompter`.
- WHEN no lyrics text is found THEN `lyrics_mode` is `none`; nothing is transcribed.
- `process_song.py --relyric-all` re-runs this for every cached song, keeping pasted lyrics (their
  word times are added or redone with the current aligner). WHEN a redo would give a worse kind of
  lyrics (synced > aligned > teleprompter > none), e.g. because LRCLIB is unreachable, THEN the old
  lyrics are kept and only their word times are refreshed.
- LRCLIB requests retry dropped connections and timeouts twice (after 1s, then 2s).
- WHEN `lyrics_mode` is `none` THEN the song still plays and the TV asks for the lyrics to be pasted.
- `meta.json` always records `vocal_start` and `vocal_end`, the first and last vocal activity.

### Pasted lyrics

A guest can replace a ready song's lyrics from `/remote`.

- WHEN a song in the library has `lyrics_mode` `none` THEN the remote's paste box lists it first,
  marked "(no lyrics)", preselects it, and opens by itself when that song is playing.

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
- **D-lyrics-engine-2 — Whisper detects the language only:** stable-ts on faster-whisper (CPU, int8,
  cores − 4 threads), `large-v3-turbo`. It aligned lyrics too until D-lyrics-engine-10. Rejects
  openai-whisper large-v3 on MPS (uneven support).
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
  so it is not trusted; "פנתרה" 74%, "ירח" 67%.
- **D-lyrics-engine-8 — Synced lyrics get word times inside their line windows.** Hand-synced line
  starts are better than the aligner's, so they stay; the aligner only places words within them.
  A line's first word starts at the line start, and a confident word (probability ≥ 0.5) is an
  anchor only when it falls between its line's start and the next line's start, so a word aligned
  into a neighbouring line can't drag it. Words after the last anchor run on at the song's singing
  rate and are squeezed to end 0.15s before the next line. Rejects replacing synced lines with the
  aligned ones (their line starts are worse: median 0.29s off on "vampire", D-lyrics-engine-3).
- **D-lyrics-engine-9 — No transcription; guests paste missing lyrics.** Whisper transcriptions of
  sung vocals mishear words, and wrong words on screen are worse for karaoke than none. A song with
  no lyrics found is `none`, and the TV and remote ask for a paste, which is then aligned. Whisper
  still detects the language and aligns known text. Removing it also drops the Silero VAD download
  that broke transcription behind TLS-inspecting proxies (formerly D-lyrics-engine-7).
- **D-lyrics-engine-10 — Lyrics are aligned with wav2vec2 CTC models, not Whisper.** English uses
  torchaudio's MMS_FA (letters a–z and '); Hebrew uses `facebook/mms-1b-all` with its native `heb`
  adapter (Hebrew letters, niqqud stripped). Emissions are computed in 30s chunks with 1s context.
  Every aligned word is an anchor (threshold 0): CTC times are monotonic, and dropping low-confidence
  words made results worse (Dancing Queen: 7% anchored, median 1.17s). Scored on the first word of
  each line against hand-synced LRC lines, with only the plain text given (2026-11-25):

  | Song | Whisper | wav2vec2 |
  |---|---|---|
  | Getaway Car | 0.34s, 14% >1s | 0.07s, 1% >1s |
  | vampire | 0.29s, 13% | 0.27s, 0% |
  | Dancing Queen | 0.94s, 46% | 0.07s, 19% |
  | Bohemian Rhapsody | 0.65s, 36% | 0.18s, 10% |
  | Electric Avenue | 0.86s, 44% | 0.28s, 9% |
  | יש בי אהבה | 0.72s, 32% | 0.20s, 2% (heb adapter) |
  | מיליון דולר | 0.19s, 9% | 0.10s, 5% (heb adapter) |

  Whisper ran early (median −0.3 to −0.75s); CTC is centred (±0.13s), so no lead is applied. It is
  also faster (7–15s a song against 20–60s). Because a forced aligner places every word, coverage
  can't flag wrong lyrics; the gate is mean word confidence per language (right lyrics: English
  0.10–0.27, Hebrew 0.39–0.75; another song's lyrics: English 0.04–0.09, Hebrew 0.24). Rejected:
  uroman romanisation for Hebrew (29% of lines over 1s on מיליון דולר) and Phonikud IPA into
  `wav2vec2-lv-60-espeak-cv-ft` (best on the ballad, 0% over 1s, but 16% on the rap song, and two
  more dependencies). The MMS weights are CC-BY-NC 4.0, which suits a non-commercial home app.
