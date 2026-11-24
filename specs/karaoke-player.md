# Karaoke player

The full-screen `/tv` page. Code: `karaoke/static/tv.html`, `tv.js`, `tv.css`, `core.js` (pure logic,
tested with `node --test tests/js/`).

## Requirements

### Audio unlock

`/tv` starts behind a full-screen "Tap to start" that resumes the `AudioContext`; later songs start
without a gesture.

- WHEN `/tv` loads THEN it shows "Tap to start" until tapped, and `/remote` shows "TV needs a tap".

### Dual-stem playback

Both stems play from one `AudioContext`, each through its own `GainNode`, started with the same
`start(when, offset)` so they stay sample-aligned.

- WHEN the vocal guide moves between 0% and 100% (TV or remote) THEN the vocal gain glides to
  (level)² over ~50ms with no click; the instrumental stays at full gain.
- WHEN the singer seeks, pauses or resumes THEN both stems are recreated at the same `when` and offset.

### Song clock

Song position is `ctx.currentTime − startedAt + offset − ctx.outputLatency`; lyrics and video follow it.

- WHEN video drift from the song clock is between 0.05s and 0.5s THEN `video.playbackRate` is 0.95 or
  1.05 until it is back under 0.05s.
- WHEN drift exceeds 0.5s THEN the video seeks once, and not again for 1s.

### BiDi-safe lyrics

Each lyric line has `dir="auto"` and `unicode-bidi: plaintext`; the active line is highlighted,
enlarged and centred, with two lines of context, over the video dimmed to `brightness(0.35)`.

### Teleprompter

In `teleprompter` mode the text scrolls from `vocal_start` to `vocal_end`, with speed nudges on `/tv`
and `/remote`.

### Resume after reload

- WHEN `/tv` reloads mid-song THEN it resumes the current song from the last position it reported
  (every second).

## Design notes

- **D-karaoke-player-1 — Rate nudge before seeking.** Seeking H.264 lands on keyframes, so seeking at
  every small drift stutters. Rejects a hard seek at 0.15s.
- **D-karaoke-player-2 — Decoded AudioBuffers, not media elements.** `AudioBufferSourceNode.start(when)`
  is the only browser API that starts two tracks on the same sample. Costs ~170MB RAM per 4-minute song.
