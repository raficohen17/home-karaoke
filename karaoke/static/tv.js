import { parseLrc, wordsSung, activeIndex, songPosition, driftAction, teleprompterRate, teleprompterOffset, sliderToGain } from "./core.js";

const $ = (id) => document.getElementById(id);
const video = $("video");
const ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: "playback" });
const vocalGain = ctx.createGain();
const instGain = ctx.createGain();
vocalGain.connect(ctx.destination);
instGain.connect(ctx.destination);
instGain.gain.value = 1;

let ws;
let state = {};
let song = null; // {vid, meta, inst, voc, lines, text}
let sources = [];
let startedAt = 0, offset = 0, playing = false;
let lastSeekAt = -Infinity;
let lineEls = [], lastActive = -2, lastSung = -1;
let prompter = { px: 0, rate: 0, lastT: 0 };
let loadingVid = null;
let lastReport = 0;
let active = false; // this screen plays audio only after a tap, and only while no other TV took over

// ---------- audio ----------
function position() {
  return playing ? songPosition(ctx.currentTime, startedAt, offset, ctx.outputLatency) : offset;
}

function stopSources() {
  for (const s of sources) { s.onended = null; try { s.stop(); } catch {} s.disconnect(); }
  sources = [];
}

function startAt(pos) {
  stopSources();
  if (!song) return;
  const when = ctx.currentTime + 0.08;
  const mk = (buf, gain) => { const s = ctx.createBufferSource(); s.buffer = buf; s.connect(gain); s.start(when, pos); return s; };
  const inst = mk(song.inst, instGain);
  const voc = mk(song.voc, vocalGain);
  sources = [inst, voc];
  startedAt = when; offset = pos; playing = true;
  inst.onended = () => { if (playing && position() >= song.inst.duration - 0.5) finished(); };
  video.currentTime = pos + (ctx.outputLatency || 0);
  video.play().catch(() => {});
  document.body.classList.remove("paused");
}

function pause() {
  if (!playing) return;
  offset = position(); playing = false; stopSources(); video.pause();
  document.body.classList.add("paused");
  report(true);
}

function resume() { if (active && song && !playing) startAt(offset); }

function seekBy(delta) { if (song) { const p = Math.max(0, Math.min(song.inst.duration - 1, position() + delta)); playing && active ? startAt(p) : (offset = p); } }

function setVocal(level, fromServer) {
  vocalGain.gain.setTargetAtTime(sliderToGain(level * 100), ctx.currentTime, 0.05 / 3);
  $("vocal").value = Math.round(level * 100);
  $("vocal-pct").textContent = Math.round(level * 100) + "%";
  if (!fromServer) send({ type: "vocal", level });
}

function finished() {
  playing = false; stopSources();
  send({ type: "ended", video_id: song?.vid });
}

// ---------- loading ----------
async function fetchBuf(url, cache = "no-cache") {
  const r = await fetch(url, { cache });
  if (!r.ok) throw new Error(url + " " + r.status);
  return ctx.decodeAudioData(await r.arrayBuffer());
}

async function loadSong(vid, resumeAt = 0) {
  if (loadingVid === vid) return;
  loadingVid = vid;
  stopSources(); playing = false;
  $("loading").hidden = false;
  const base = `/media/${vid}/`;
  const meta = await (await fetch(base + "meta.json", { cache: "no-store" })).json();
  // Both stems carry the same version, so a cached old stem can never be paired with a new one.
  const v = `?v=${meta.stems_version || 0}`;
  let [inst, voc] = await Promise.all([fetchBuf(base + "instrumental.flac" + v), fetchBuf(base + "vocals.flac" + v)]);
  if (inst.length !== voc.length) { // mismatched pair: refetch both straight from the server
    console.warn("stem length mismatch", inst.length, voc.length);
    [inst, voc] = await Promise.all([fetchBuf(base + "instrumental.flac" + v, "no-store"), fetchBuf(base + "vocals.flac" + v, "no-store")]);
  }
  const { lines, text } = await fetchLyrics(base, meta);
  if (loadingVid !== vid) return; // superseded while loading
  song = { vid, meta, inst, voc, lines, text };
  video.src = base + "video.mp4";
  renderSong();
  $("loading").hidden = true;
  document.body.classList.add("playing");
  if (active && ctx.state === "running" && !state.paused) startAt(resumeAt);
  else offset = resumeAt;
}

async function fetchLyrics(base, meta) {
  if (meta.lyrics_mode === "teleprompter") return { lines: null, text: await (await fetch(base + "lyrics.txt", { cache: "no-store" })).text() };
  if (meta.lyrics_mode === "none") return { lines: null, text: null };
  return { lines: parseLrc(await (await fetch(base + "lyrics.lrc", { cache: "no-store" })).text()), text: null };
}

async function reloadLyrics() {
  const base = `/media/${song.vid}/`;
  const meta = await (await fetch(base + "meta.json", { cache: "no-store" })).json();
  Object.assign(song, { meta }, await fetchLyrics(base, meta));
  renderSong();
}

function unloadSong() {
  stopSources(); playing = false; song = null; loadingVid = null;
  video.removeAttribute("src"); video.load();
  $("lyrics").replaceChildren(); $("prompter").hidden = true; $("nowplaying").hidden = true;
  document.body.classList.remove("playing");
}

// ---------- lyrics ----------
function renderSong() {
  const { meta, lines, text } = song;
  $("np-title").textContent = meta.title || "";
  $("np-mode").textContent = { synced: "synced lyrics", aligned: "auto-aligned lyrics", teleprompter: "teleprompter", none: "no lyrics found" }[meta.lyrics_mode] || "";
  $("nowplaying").hidden = false;
  $("lyrics").replaceChildren();
  lineEls = []; lastActive = -2; lastSung = -1;
  $("prompter").hidden = !text;
  $("nudge").hidden = !text;
  if (meta.lyrics_mode === "none") {
    // no transcription fallback (D-lyrics-engine-9): ask the room for the words
    $("lyrics").append(Object.assign(document.createElement("div"), {
      className: "line notice", textContent: "No lyrics found. Paste them from a phone: Lyrics missing? Paste them",
    }));
  }
  if (text) {
    $("prompter-text").textContent = text;
    $("prompter-text").style.transform = "translateY(0)";
    requestAnimationFrame(() => {
      const el = $("prompter-text");
      prompter = { px: 0, lastT: 0, rate: teleprompterRate(el.scrollHeight - $("prompter").clientHeight, meta.vocal_start, meta.vocal_end, meta.duration) };
    });
  }
  if (lines) {
    for (const l of lines) {
      const d = document.createElement("div");
      d.className = "line" + (l.text ? "" : " empty");
      d.dir = "auto"; // BiDi: each line picks its own direction
      if (l.words?.length) {
        // one span per word, separated by plain spaces, so the line still reads as one BiDi paragraph
        l.words.forEach((w, k) => {
          if (k) d.append(" ");
          d.append(Object.assign(document.createElement("span"), { className: "w", textContent: w.w }));
        });
      } else d.textContent = l.text;
      lineEls.push(d);
    }
  }
}

const WINDOW = 2; // lines shown before/after the active one
function updateWords(i, t) {
  // karaoke wipe: words already reached light up, word by word
  const words = i >= 0 ? song.lines[i].words : null;
  if (!words?.length) return;
  const n = wordsSung(words, t);
  if (n === lastSung) return;
  lastSung = n;
  [...lineEls[i].querySelectorAll(".w")].forEach((el, k) => el.classList.toggle("sung", k < n));
}

function updateLyrics(t) {
  if (!song?.lines) return;
  const i = activeIndex(song.lines, t + 0.15);
  if (i === lastActive) { updateWords(i, t); return; }
  if (lastActive >= 0) lineEls[lastActive]?.querySelectorAll(".w.sung").forEach((el) => el.classList.remove("sung"));
  lastActive = i;
  lastSung = -1;
  updateWords(i, t);
  const box = $("lyrics");
  const from = Math.max(0, i - WINDOW), to = Math.min(lineEls.length, Math.max(i, 0) + WINDOW + 2);
  box.replaceChildren(...lineEls.slice(from, to));
  lineEls.forEach((el, k) => { el.classList.toggle("active", k === i); el.classList.toggle("far", Math.abs(k - i) >= 2); });
}

function updatePrompter(t) {
  if (!song?.text || !prompter.rate) return;
  const dt = Math.max(0, t - prompter.lastT);
  prompter.lastT = t;
  if (dt > 1) return; // seek: keep position
  prompter.px = teleprompterOffset(prompter.px, dt, prompter.rate, state.scroll_speed || 1, t, song.meta.vocal_start);
  $("prompter-text").style.transform = `translateY(${-prompter.px}px)`;
}

// ---------- loop ----------
function fmt(s) { s = Math.max(0, Math.floor(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }

function tick() {
  requestAnimationFrame(tick);
  if (!song) return;
  const t = position();
  updateLyrics(t);
  updatePrompter(t);
  $("time").textContent = `${fmt(t)} / ${fmt(song.inst.duration)}`;
  if (document.activeElement !== $("seek")) $("seek").value = Math.round((t / song.inst.duration) * 1000);
  if (playing && !video.paused && video.readyState >= 2) {
    const now = ctx.currentTime;
    const act = driftAction(video.currentTime - t, now, lastSeekAt);
    if (act.seek) { video.currentTime = t; lastSeekAt = now; video.playbackRate = 1; }
    else if (video.playbackRate !== act.rate) video.playbackRate = act.rate;
  }
  if (video.ended && playing) video.currentTime = Math.min(t, video.duration - 0.1);
  report(false);
}

function report(force) {
  const now = performance.now();
  if (!active || !song || (!force && now - lastReport < 1000)) return; // only the playing screen reports
  lastReport = now;
  send({ type: "position", video_id: song.vid, t: position(), paused: !playing });
}

// ---------- server ----------
function send(msg) { if (ws?.readyState === 1) ws.send(JSON.stringify(msg)); }

function onState(s) {
  const prevVid = state.current?.video_id;
  state = s;
  setVocal(s.vocal_level, true);
  const vid = s.current?.video_id;
  if (vid && vid !== (song?.vid ?? loadingVid)) loadSong(vid, vid === prevVid || !prevVid ? s.position || 0 : 0).catch(showError);
  if (!vid && (song || loadingVid)) unloadSong();
  if (!vid) {
    const up = s.upcoming;
    $("idle-msg").textContent = up ? `Up next — preparing (${up.status.toLowerCase()}${up.progress ? " " + Math.round(up.progress * 100) + "%" : ""}): ${up.title || up.video_id}` : "Scan the code to add a song";
  }
}

function showError(e) { console.error(e); $("loading").textContent = "Failed to load: " + e.message; }

function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?role=tv`);
  ws.onopen = () => { if (active) send({ type: "audio_ready", ready: true }); };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "state") onState(m);
    else if (m.type === "vocal") setVocal(m.level, true);
    else if (m.type === "standby") standby();
    else if (m.type === "pause") pause();
    else if (m.type === "resume") resume();
    else if (m.type === "seek") seekBy(m.delta);
    else if (m.type === "lyrics_updated" && m.video_id === song?.vid) reloadLyrics().catch(showError);
  };
  ws.onclose = () => setTimeout(connect, 1000);
}

// ---------- UI ----------
function standby() {
  // Another TV screen was tapped: go silent here so the song never plays from two places.
  active = false;
  if (playing) { offset = position(); playing = false; stopSources(); video.pause(); }
  document.body.classList.remove("unlocked");
  $("unlock-btn").textContent = "Play on this screen";
  $("unlock-note").textContent = "The song is playing on another screen.";
}

$("unlock-btn").onclick = async () => {
  await ctx.resume();
  active = true;
  document.body.classList.add("unlocked");
  send({ type: "audio_ready", ready: true });
  if (song && !playing && !state.paused) startAt(offset);
};
$("btn-play").onclick = () => (playing ? send({ type: "pause" }) : send({ type: "resume" }));
$("btn-skip").onclick = () => send({ type: "skip" });
$("vocal").oninput = (e) => setVocal(e.target.value / 100, false);
$("seek").onchange = (e) => { if (song) seekBy((e.target.value / 1000) * song.inst.duration - position()); };
document.querySelectorAll("[data-nudge]").forEach((b) => (b.onclick = () => send({ type: "nudge", dir: b.dataset.nudge })));
document.addEventListener("keydown", (e) => {
  if (e.key === " ") { e.preventDefault(); $("btn-play").click(); }
  if (e.key === "ArrowRight") seekBy(5);
  if (e.key === "ArrowLeft") seekBy(-5);
});
fetch("/api/info").then((r) => r.json()).then((i) => ($("join-url").textContent = i.remote_url)).catch(() => {});

window.__karaoke = { position, get song() { return song; }, get playing() { return playing; }, ctx, video };
connect();
tick();
