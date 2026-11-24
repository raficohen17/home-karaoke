# Media pipeline

Turns what a guest typed into a cached, playable song: one YouTube video, an instrumental stem and a
vocal stem. Code: `karaoke/resolver.py`, `karaoke/media.py`, `karaoke/cache.py`, `karaoke/pipeline.py`.

## Requirements

### Source resolution

The pipeline resolves a YouTube URL, a Spotify track URL, or free text (Hebrew or English) to one
YouTube `video_id`.

- WHEN a guest submits a YouTube URL (`watch?v=`, `youtu.be/`, `shorts/`, `embed/`, `music.youtube.com`)
  THEN its `video_id` is used without searching.
- WHEN a guest submits a Spotify track URL THEN the track title, artist and duration are read from the
  track page's Open Graph tags (D-media-pipeline-3), YouTube is searched for `<artist> - <title>`
  (5 results), and the result whose duration is closest (within ±10s) wins, preferring "Official
  Audio" / "- Topic" uploads and penalising live, cover, karaoke, remix, sped-up and slowed uploads.
- WHEN no result is within ±10s of the Spotify duration THEN adding fails with `no_match`.
- WHEN a guest types free text on `/remote` THEN the top 5 YouTube results (thumbnail, title,
  channel, duration, "ready" if cached) are shown and the tapped one is queued.
- WHEN free text is given to `process_song.py` THEN the best-scored search result is used.

### Download

The pipeline downloads video capped at 720p H.264 with audio
(`bv*[height<=720][vcodec^=avc1]+ba`) as `video.mp4`, and extracts 44.1 kHz stereo audio.

- WHEN yt-dlp fails (age-restricted, region-blocked, removed, extractor error) THEN the song ends
  `FAILED` with yt-dlp's reason and the queue moves on.

### Stem separation

The audio is split into `instrumental.flac` and `vocals.flac` with the same sample rate and the same
sample count (D-media-pipeline-2).

- WHEN separation finishes THEN both stems have equal sample counts and instrumental + vocals
  reproduce the original mix's balance (D-media-pipeline-5).
- WHEN `process_song.py --restem-all` runs THEN every cached song's stems are redone with the current
  separator, keeping its video and lyrics.
- WHEN the server runs with `--fast` THEN MDX-Net is used instead of the Mel-Band RoFormer (D-media-pipeline-1).

### Atomic cache

`cache/<video_id>/` exists only once it is complete.

- WHEN a song is processed THEN work happens in `cache/.staging/<video_id>/`, `meta.json` is written
  last with `"status": "complete"`, and the directory is renamed into place.
- WHEN `cache/<video_id>/meta.json` has `"status": "complete"` and the stems and video exist THEN a
  request for that song is `READY` immediately, with no download or separation.
- WHEN the server starts THEN `cache/.staging/` is deleted.

### TLS

All Python HTTPS (yt-dlp, LRCLIB, Shironet, model downloads) uses the operating system's trust store,
so the app works behind TLS-inspecting proxies.

## Design notes

- **D-media-pipeline-1 — Mel-Band RoFormer Kim FT2 "bleedless" (overlap 2) by default, MDX-Net with
  `--fast`.** Chosen after a guest heard the electric guitars vanish with the vocal guide down on
  "vampire". On its guitar bridge (60s, M4 Pro), the share of a reference guitar track (htdemucs_6s)
  landing in the vocal stem: Kim FT2 bleedless 23% (22% on the full song), BS-RoFormer ep317 27%,
  Mel-Band instrumental v7 21% but voice left in the instrumental −18.3 dB vs −21.6 dB (Kim) and
  −23.8 dB (BS-RoFormer). Kim FT2 is also 2× faster (20s vs 43s per minute of audio; ~90s per
  song). fp16 autocast changed nothing measurable. Rejects BS-RoFormer ep317 (more guitar bleed,
  slower), instrumental-first models (more voice left), htdemucs (lowest quality, four stems).
- **D-media-pipeline-2 — FLAC stems, not MP3.** MP3 encoder delay/padding differs between decoders and
  breaks sample alignment between the stems; FLAC decodes to the same sample count in every browser.
  Rejects MP3 with a timing tolerance.
- **D-media-pipeline-3 — Spotify metadata from Open Graph tags.** oEmbed doesn't reliably carry the
  artist and the Web API needs credentials. Rejects oEmbed-only and a Spotify developer app.
- **D-media-pipeline-5 — Stems are rebalanced against the mix.** audio-separator peak-normalised each
  stem on its own (instrumental ×1/1.19, vocals ×1/1.11 on "vampire"), shifting the band/voice
  balance. Normalisation is off; one least-squares gain per stem makes instrumental + vocals match
  the mix, and if that would clip, both stems share one reduction so the balance holds.
- **D-media-pipeline-4 — OS trust store via `truststore`.** certifi rejects proxy-issued certificates
  that curl and browsers accept. Rejects disabling certificate checks.
