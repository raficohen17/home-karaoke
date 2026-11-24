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

- WHEN separation finishes THEN both stems have equal sample counts (the longer is trimmed).
- WHEN the server runs with `--fast` THEN MDX-Net is used instead of BS-RoFormer (D-media-pipeline-1).

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

- **D-media-pipeline-1 — BS-RoFormer (overlap 2, fp16) by default, MDX-Net with `--fast`.** Measured on
  a 60s clip on an M4 Pro (MPS), vocals SDR against full-overlap BS-RoFormer: RoFormer overlap 2 41s,
  23.5 dB; MDX-Net Inst HQ 3 8s, 14.7 dB; htdemucs 6s, 10.8 dB and four stems instead of two;
  RoFormer default overlap 8 ≈100s. Quality wins by default because songs are prepared while the
  previous one plays. Rejects htdemucs and full-overlap RoFormer.
- **D-media-pipeline-2 — FLAC stems, not MP3.** MP3 encoder delay/padding differs between decoders and
  breaks sample alignment between the stems; FLAC decodes to the same sample count in every browser.
  Rejects MP3 with a timing tolerance.
- **D-media-pipeline-3 — Spotify metadata from Open Graph tags.** oEmbed doesn't reliably carry the
  artist and the Web API needs credentials. Rejects oEmbed-only and a Spotify developer app.
- **D-media-pipeline-4 — OS trust store via `truststore`.** certifi rejects proxy-issued certificates
  that curl and browsers accept. Rejects disabling certificate checks.
