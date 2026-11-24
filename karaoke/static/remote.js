const $ = (id) => document.getElementById(id);
let ws, state = {};
let sliderBusyUntil = 0;

function send(msg) { if (ws?.readyState === 1) ws.send(JSON.stringify(msg)); }
function el(tag, props = {}, ...kids) { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; }
function fmtDur(s) { if (!s) return ""; s = Math.round(s); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
function msg(text, err = false) { $("msg").textContent = text; $("msg").className = err ? "err" : ""; }
const STATUS = { QUEUED: "queued", DOWNLOADING: "downloading", SEPARATING: "removing vocals", ALIGNING: "syncing lyrics", READY: "ready", FAILED: "failed" };

function render(s) {
  state = s;
  $("now-title").textContent = s.current ? s.current.title || s.current.video_id : "Nothing playing";
  $("btn-pause").textContent = s.paused ? "Resume" : "Pause";
  $("btn-pause").dataset.cmd = s.paused ? "resume" : "pause";
  const tv = $("tv-status");
  const tvOnline = s.audio_ready !== undefined;
  tv.textContent = s.audio_ready ? "TV ready" : "TV needs a tap";
  tv.className = "pill " + (s.audio_ready ? "on" : "warn");
  if (Date.now() > sliderBusyUntil) { $("vocal").value = Math.round(s.vocal_level * 100); $("vocal-out").textContent = $("vocal").value + "%"; }

  const q = $("queue");
  q.replaceChildren(...s.queue.map((e, i) => {
    const pct = e.progress ? ` ${Math.round(e.progress * 100)}%` : "";
    const li = el("li", { className: "qi" },
      el("span", { className: "t", dir: "auto", textContent: e.title || e.video_id }),
      el("span", { className: "badge " + e.status, textContent: STATUS[e.status] + pct }),
      el("button", { textContent: "↑", ariaLabel: "Move up", disabled: i === 0, onclick: () => send({ type: "move", id: e.id, delta: -1 }) }),
      el("button", { textContent: "✕", ariaLabel: "Remove", onclick: () => send({ type: "remove", id: e.id }) }));
    if (e.reason) li.append(el("div", { className: "reason", dir: "auto", textContent: e.reason }));
    li.style.flexWrap = "wrap";
    return li;
  }));
  $("queue-empty").hidden = s.queue.length > 0;
  $("nudge").hidden = !s.current;
  renderPasteTargets();
}

async function add(body) {
  msg("Adding…");
  const r = await fetch("/api/add", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { msg(j.detail || "Could not add", true); return; }
  msg(j.status === "READY" ? "Added — ready to sing" : "Added — preparing (a few minutes)");
  $("results").replaceChildren(); $("q").value = "";
  loadLibrary();
}

async function search(q) {
  msg("Searching…");
  const r = await fetch("/api/search?q=" + encodeURIComponent(q));
  if (!r.ok) { msg("Search failed", true); return; }
  const items = await r.json();
  msg(items.length ? "Tap the right one:" : "No results", !items.length);
  $("results").replaceChildren(...items.map((c) => el("li", { className: "result", onclick: () => add({ video_id: c.video_id, title: c.title }) },
    el("img", { src: c.thumbnail, alt: "", loading: "lazy" }),
    el("div", {}, el("div", { className: "t", dir: "auto", textContent: c.title }),
      el("div", { className: "s", dir: "auto", textContent: `${c.channel} · ${fmtDur(c.duration)}${c.cached ? " · ready" : ""}` })))));
}

let library = [];
function renderPasteTargets() {
  const sel = $("paste-song"), prev = sel.value;
  const opts = [];
  if (state.current) opts.push([state.current.video_id, "Now playing: " + (state.current.title || state.current.video_id)]);
  for (const s of library) if (s.video_id !== state.current?.video_id) opts.push([s.video_id, s.title]);
  sel.replaceChildren(...opts.map(([v, t]) => el("option", { value: v, textContent: t })));
  if (opts.some(([v]) => v === prev)) sel.value = prev;
  $("paste-box").hidden = !opts.length;
}

$("paste-form").onsubmit = async (e) => {
  e.preventDefault();
  const video_id = $("paste-song").value, text = $("paste-text").value;
  if (!video_id || !text.trim()) return;
  $("paste-msg").textContent = "Syncing lyrics to the singer… (about a minute)";
  const r = await fetch("/api/lyrics", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_id, text }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { $("paste-msg").textContent = j.detail || "Failed"; return; }
  $("paste-msg").textContent = j.lyrics_mode === "teleprompter" ? "Couldn't sync line by line — showing them as a scrolling teleprompter." : "Done — lyrics updated on the TV.";
  $("paste-text").value = "";
};

async function loadLibrary() {
  const items = await (await fetch("/api/library")).json().catch(() => []);
  library = items;
  renderPasteTargets();
  $("library").replaceChildren(...items.map((s) => el("li", {},
    el("span", { className: "t", dir: "auto", textContent: s.title }),
    el("button", { textContent: "Add", onclick: () => add({ video_id: s.video_id, title: s.title }) }))));
  $("library-box").hidden = !items.length;
}

$("add-form").onsubmit = (e) => {
  e.preventDefault();
  const q = $("q").value.trim();
  if (!q) return;
  if (/^https?:\/\//i.test(q)) add({ input: q }); else search(q);
};
$("vocal").oninput = (e) => { sliderBusyUntil = Date.now() + 800; $("vocal-out").textContent = e.target.value + "%"; send({ type: "vocal", level: e.target.value / 100 }); };
document.querySelectorAll("[data-cmd]").forEach((b) => (b.onclick = () => {
  const m = { type: b.dataset.cmd };
  if (b.dataset.delta) m.delta = Number(b.dataset.delta);
  if (b.dataset.dir) m.dir = b.dataset.dir;
  send(m);
}));

function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?role=remote`);
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "state") render(m);
    else if (m.type === "vocal" && Date.now() > sliderBusyUntil) { $("vocal").value = Math.round(m.level * 100); $("vocal-out").textContent = $("vocal").value + "%"; }
  };
  ws.onclose = () => { $("tv-status").textContent = "Reconnecting…"; setTimeout(connect, 1000); };
}
connect();
loadLibrary();
