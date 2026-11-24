// Pure player logic shared by /tv and tested with `node --test` (no DOM here).

export function parseLrc(text) {
  const tag = /\[(\d+):(\d{1,2}(?:[.:]\d{1,3})?)\]/g;
  const out = [];
  for (const raw of text.split(/\r?\n/)) {
    const tags = [...raw.matchAll(tag)];
    if (!tags.length) continue;
    const lyric = raw.replace(tag, "").trim();
    for (const m of tags) out.push({ t: Number(m[1]) * 60 + Number(m[2].replace(":", ".")), text: lyric });
  }
  return out.sort((a, b) => a.t - b.t);
}

// Index of the line active at time t (last line with start <= t), or -1 before the first.
export function activeIndex(lines, t) {
  let lo = 0, hi = lines.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].t <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

// Song position on the shared Web Audio clock, corrected for output latency (HDMI/Bluetooth).
export function songPosition(ctxTime, startedAt, offset, outputLatency = 0) {
  return Math.max(0, ctxTime - startedAt + offset - (outputLatency || 0));
}

// D4: nudge the video's playbackRate for small drift, hard-seek rarely for large drift.
// drift = video.currentTime - audioTime (seconds). Returns {rate} or {seek} or {rate: 1}.
export function driftAction(drift, now, lastSeekAt = -Infinity) {
  const a = Math.abs(drift);
  if (a > 0.5) {
    if (now - lastSeekAt < 1.0) return { rate: 1 };
    return { seek: true };
  }
  if (a > 0.05) return { rate: drift > 0 ? 0.95 : 1.05 };
  return { rate: 1 };
}

// Teleprompter: pixels per second so the text scrolls from vocalStart to vocalEnd.
export function teleprompterRate(scrollPx, vocalStart, vocalEnd, duration) {
  const start = vocalStart ?? 0;
  const end = vocalEnd ?? duration;
  const span = Math.max(1, end - start);
  return scrollPx / span;
}

// Teleprompter scroll position at time t with speed factor applied from now on.
export function teleprompterOffset(prevPx, dt, rate, speed, t, vocalStart) {
  if (t < (vocalStart ?? 0)) return 0;
  return prevPx + dt * rate * speed;
}

// Map slider percent (0-100) to gain; squared for a perceptually even slider.
export function sliderToGain(pct) {
  const x = Math.max(0, Math.min(100, Number(pct))) / 100;
  return x * x;
}
