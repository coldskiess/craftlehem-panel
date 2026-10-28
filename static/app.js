/* Craftlehem Panel - single page UI (no build step). */
"use strict";

// ------------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function bytes(n, d = 1) {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i < 2 ? 0 : d)} ${u[i]}`;
}
function dur(s) {
  if (s == null) return "—";
  s = Math.max(0, Math.floor(s));
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${s}s`;
}
function when(t) {
  if (!t) return "never";
  const d = new Date(t * 1000), now = new Date();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `today ${time}`;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `yesterday ${time}`;
  return d.toLocaleDateString([], { day: "numeric", month: "short", year: d.getFullYear() !== now.getFullYear() ? "numeric" : undefined }) + " " + time;
}
function ago(t) {
  if (!t) return "never";
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  return dur(s) + " ago";
}

async function api(path, opts = {}) {
  const o = { method: opts.method || (opts.body !== undefined ? "POST" : "GET"), headers: { "x-panel": "1" } };
  if (S.server) o.headers["x-server"] = S.server;
  if (opts.body instanceof FormData) o.body = opts.body;
  else if (opts.body !== undefined) { o.body = JSON.stringify(opts.body); o.headers["content-type"] = "application/json"; }
  const r = await fetch(path, o);
  if (r.status === 401 && path !== "/api/login") { showLogin(); throw new Error("Logged out"); }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) || `Request failed (${r.status})`);
  return data;
}
async function act(promise, success) {
  try {
    const r = await promise;
    if (success !== false) toast(success || r?.message || "Done");
    if (r?.restart_needed) toast("Restart the server to apply this change");
    return r;
  } catch (e) {
    if (e.message !== "Logged out") toast(e.message, true);
    throw e;
  }
}
function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  $("#toasts").append(t);
  setTimeout(() => t.remove(), err ? 7000 : 3500);
}
function modal(html, { wide = false } = {}) {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal${wide ? " wide" : ""}" role="dialog" aria-modal="true">${html}</div>`;
  document.body.append(back);
  const close = () => back.remove();
  back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });
  back.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  setTimeout(() => ($("input,select,textarea,button.primary", back) || $("button", back))?.focus(), 30);
  return { el: back, close };
}
function confirmBox(title, text, okLabel = "Confirm", danger = false) {
  return new Promise((res) => {
    const m = modal(`<h4>${esc(title)}</h4><p class="muted">${text}</p>
      <div class="foot"><button class="btn ghost" data-x>Cancel</button><button class="btn ${danger ? "danger solid" : "primary"}" data-ok>${esc(okLabel)}</button></div>`);
    $("[data-x]", m.el).onclick = () => { m.close(); res(false); };
    $("[data-ok]", m.el).onclick = () => { m.close(); res(true); };
  });
}
function promptBox(title, label, value = "", okLabel = "Save", hint = "") {
  return new Promise((res) => {
    const m = modal(`<h4>${esc(title)}</h4><form><label class="field"><span>${esc(label)}</span><input name="v" value="${esc(value)}">${hint ? `<small>${hint}</small>` : ""}</label>
      <div class="foot"><button type="button" class="btn ghost" data-x>Cancel</button><button class="btn primary">${esc(okLabel)}</button></div></form>`);
    $("[data-x]", m.el).onclick = () => { m.close(); res(null); };
    $("form", m.el).onsubmit = (e) => { e.preventDefault(); m.close(); res($("[name=v]", m.el).value); };
  });
}

const I = {
  dash: '<path d="M3 13a9 9 0 0 1 18 0"/><path d="M12 13l4-4"/><circle cx="12" cy="13" r="1.4"/><path d="M5 19h14"/>',
  console: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
  players: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.4"/><path d="M16 14.2c2.8.3 5 2.6 5 5.8"/>',
  mods: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/>',
  files: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
  backups: '<path d="M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z"/><path d="M4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  schedule: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  logs: '<path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
  activity: '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  play: '<path d="M7 4l13 8-13 8z" fill="currentColor"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor"/>',
  restart: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  kill: '<path d="M6 6l12 12M18 6L6 18"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v4h16v-4"/>',
  download: '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 20h16"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
};
const icon = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[n]}</svg>`;

// -------------------------------------------------------------------- state
const S = {
  me: null, status: null, history: [], console: [], lastLine: 0, ws: null, page: null,
  cmdHistory: JSON.parse(localStorageGet("cmdHistory") || "[]"), cmdPos: -1, job: null,
  server: null, servers: [],
};
// Extension points for the optional Pro add-on (pro.js fills these in).
const Pro = { hooks: { settingsTabs: [] } };
const srvq = () => (S.server ? `&server=${encodeURIComponent(S.server)}` : "");
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch {} }
const can = (role) => ({ viewer: 0, moderator: 1, admin: 2 })[S.me?.role] >= ({ viewer: 0, moderator: 1, admin: 2 })[role];

// ------------------------------------------------------------------- login
function showLogin() {
  S.me = null;
  if (S.ws) { S.ws.onclose = null; S.ws.close(); S.ws = null; }
  document.title = "Sign in";
  $("#app").innerHTML = `<div class="login"><form>
    <h1>${esc(document.querySelector("title").textContent || "Server panel")}</h1>
    <p>Sign in to manage the server.</p>
    <label class="field"><span>Username</span><input name="u" autocomplete="username" required></label>
    <label class="field"><span>Password</span><input name="p" type="password" autocomplete="current-password" required></label>
    <button class="btn primary" style="width:100%;justify-content:center">Sign in</button>
    <p class="err" id="err"></p></form></div>`;
  $(".login form").onsubmit = async (e) => {
    e.preventDefault();
    $("#err").textContent = "";
    try {
      await api("/api/login", { body: { username: e.target.u.value, password: e.target.p.value } });
      boot();
    } catch (err) { $("#err").textContent = err.message; }
  };
  $(".login [name=u]").focus();
}

// -------------------------------------------------------------------- shell
const PAGES = [
  ["dashboard", "Dashboard", "dash", "viewer"],
  ["console", "Console", "console", "viewer"],
  ["players", "Players", "players", "viewer"],
  ["mods", "Mods", "mods", "viewer"],
  ["configs", "Configs", "sliders", "admin"],
  ["files", "Files", "files", "admin"],
  ["backups", "Backups", "backups", "viewer"],
  ["schedule", "Schedule", "schedule", "viewer"],
  ["logs", "Logs", "logs", "viewer"],
  ["settings", "Settings", "settings", "viewer"],
  ["activity", "Activity", "activity", "viewer"],
];

async function boot() {
  try { S.me = await api("/api/me"); } catch { return showLogin(); }
  document.title = S.me.title;
  $("#app").innerHTML = `<div class="shell">
    <nav class="rail" aria-label="Sections">
      <div class="brand">${esc(S.me.title)}<small>v${esc(S.me.version)}</small></div>
      ${PAGES.filter((p) => can(p[3])).map(([id, label, ic]) => `<a href="#/${id}" data-page="${id}">${icon(ic)}<span>${label}</span></a>`).join("")}
      <div class="spacer"></div>
      <div class="who">Signed in as <b>${esc(S.me.username)}</b> (${esc(S.me.role)})<br><button id="logout">Sign out</button>
        ${S.me.update ? `<div class="credit"><a href="${esc(S.me.update.url)}" target="_blank" rel="noopener">Version ${esc(S.me.update.version)} is out</a> - run <code>sudo bash update.sh</code></div>` : ""}
        <div class="credit">Craftlehem Panel${S.me.pro?.licensed ? " Pro" : ""} by coldskiess${!S.me.pro?.licensed && can("admin") ? '<br><a href="#/settings?tab=Pro">Get Pro</a>' : ""}</div></div>
    </nav>
    <main><header class="nameplate" id="nameplate"></header><div id="countdown"></div><div id="page"></div></main>
  </div>`;
  $("#logout").onclick = async () => { await api("/api/logout", { body: {} }); showLogin(); };
  S.servers = await api("/api/servers");
  const saved = localStorageGet("server");
  S.server = (S.servers.find((x) => x.id === saved) || S.servers[0] || {}).id || null;
  await loadServerState();
  connectWS();
  window.onhashchange = route;
  route();
}

async function loadServerState() {
  S.history = await api("/api/history");
  S.console = await api("/api/console");
  S.lastLine = S.console.length ? S.console[S.console.length - 1][0] : 0;
  S.status = await api("/api/status");
  S.job = null;
  renderNameplate();
}

async function switchServer(id) {
  if (id === S.server) return;
  if (Pages.leaveGuard && !(await Pages.leaveGuard())) return renderNameplate();
  S.server = id;
  localStorageSet("server", id);
  await loadServerState();
  lastHash = location.hash = "#/" + (S.page || "dashboard");
  route(true);
}

let lastHash = location.hash;
async function route(force) {
  if (!force && Pages.leaveGuard && location.hash !== lastHash && !(await Pages.leaveGuard())) {
    history.replaceState(null, "", lastHash);
    return;
  }
  lastHash = location.hash;
  const id = (location.hash.replace("#/", "") || "dashboard").split("?")[0];
  const page = PAGES.find((p) => p[0] === id && can(p[3])) ? id : "dashboard";
  $$(".rail a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  S.page = page;
  const el = $("#page");
  el.innerHTML = "";
  Pages[page](el);
  window.scrollTo(0, 0);
}

const STATE_TEXT = {
  online: "Online", offline: "Offline", starting: "Starting up…", stopping: "Shutting down…", crashed: "Crashed",
};
function renderNameplate() {
  const s = S.status;
  if (!s) return;
  const running = ["online", "starting"].includes(s.status);
  const alive = running || s.status === "stopping";
  let sub = STATE_TEXT[s.status];
  if (s.status === "online" && s.started_at) sub += ` for ${dur(Date.now() / 1000 - s.started_at)}`;
  if (s.status === "online") sub += ` · ${s.players.length}${s.max_players ? "/" + s.max_players : ""} players`;
  if (s.status === "starting" && s.started_at) sub += ` (${dur(Date.now() / 1000 - s.started_at)})`;
  if (s.busy) sub += ` · ${s.busy} is running`;
  const m = can("moderator");
  $("#nameplate").innerHTML = `
    <span class="lamp ${s.status}" aria-hidden="true"></span>
    <div>${S.servers.length > 1 ? `<label class="srv-pick" title="Switch server"><select id="srvpick" aria-label="Server">${S.servers.map((x) => `<option value="${esc(x.id)}" ${x.id === S.server ? "selected" : ""}>${esc(x.id === S.server ? s.name : x.name)}${x.id !== S.server && x.status === "online" ? " ●" : ""}</option>`).join("")}</select></label>` : `<h2>${esc(s.name)}</h2>`}<div class="state">${esc(sub)}${s.address ? ` · <span class="muted">${esc(s.address)}</span>` : ""}</div></div>
    ${m ? `<div class="controls">
      <button class="btn go" data-p="start" ${alive || s.busy ? "disabled" : ""}>${icon("play")}Start</button>
      <button class="btn" data-p="restart" ${!running ? "disabled" : ""}>${icon("restart")}Restart</button>
      <button class="btn" data-p="stop" ${!running ? "disabled" : ""}>${icon("stop")}Stop</button>
      ${alive ? `<button class="btn danger" data-p="kill" title="Force the process to end without saving">${icon("kill")}Kill</button>` : ""}
    </div>` : ""}`;
  document.documentElement.style.setProperty("--np", $("#nameplate").offsetHeight + "px");
  $$("[data-p]", $("#nameplate")).forEach((b) => (b.onclick = () => power(b.dataset.p)));
  $("#srvpick")?.addEventListener("change", (e) => switchServer(e.target.value));
  const cd = s.countdown;
  $("#countdown").innerHTML = cd ? `<div class="countdown-bar"><span>Server ${cd.action === "restart" ? "restarts" : "stops"} in</span><b id="cdleft"></b>
    ${m ? '<button class="btn small" id="cdcancel" style="margin-left:auto">Cancel</button>' : ""}</div>` : "";
  if (cd) {
    const tick = () => { const el = $("#cdleft"); if (el) el.textContent = dur(cd.ends_at - Date.now() / 1000); };
    tick();
    if (m) $("#cdcancel").onclick = () => act(api("/api/countdown", { method: "DELETE" }), "Countdown cancelled");
  }
}
setInterval(() => { if (S.status?.countdown && $("#cdleft")) $("#cdleft").textContent = dur(S.status.countdown.ends_at - Date.now() / 1000); }, 500);

async function power(action) {
  const s = S.status;
  const n = s.players.length;
  if (action === "restart" || action === "stop") {
    const verb = action === "restart" ? "Restart" : "Stop";
    const m = modal(`<h4>${verb} the server</h4>
      <p class="muted">${n ? `${n} player${n > 1 ? "s are" : " is"} online.` : "Nobody is online."} Give players a warning first?</p>
      <form><label class="field"><span>Warning</span><select name="secs">
        <option value="0" ${n ? "" : "selected"}>${verb} now</option><option value="30">30 seconds</option>
        <option value="60" ${n ? "selected" : ""}>1 minute</option><option value="300">5 minutes</option><option value="600">10 minutes</option>
      </select></label>
      <label class="field"><span>Reason (optional, shown to players)</span><input name="reason" maxlength="80" placeholder="e.g. Updating mods"></label>
      <div class="foot"><button type="button" class="btn ghost" data-x>Cancel</button><button class="btn primary">${verb}</button></div></form>`);
    $("[data-x]", m.el).onclick = m.close;
    $("form", m.el).onsubmit = (e) => {
      e.preventDefault();
      const secs = +e.target.secs.value;
      m.close();
      if (secs) act(api("/api/countdown", { body: { action, seconds: secs, reason: e.target.reason.value } }), `${verb} countdown started`);
      else act(api("/api/power", { body: { action } }));
    };
    return;
  }
  if (action === "kill" && !(await confirmBox("Force kill the server?", "The Java process is ended immediately. Anything not yet saved is lost and chunks can corrupt. Only use this when the server is frozen.", "Kill it", true))) return;
  act(api("/api/power", { body: { action } }), action === "start" ? "Starting the server" : undefined);
}

// ---------------------------------------------------------------- websocket
function connectWS() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  S.ws = ws;
  let ping;
  ws.onopen = () => {
    $("#connbar")?.remove();
    ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000);
    // catch up on console lines missed while disconnected
    api(`/api/console?since=${S.lastLine}`).then(onConsole).catch(() => {});
  };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.server && m.server !== S.server) {
      // another server: only keep the switcher's status dots fresh
      const x = S.servers.find((v) => v.id === m.server);
      if (x && m.status && x.status !== m.status.status) { x.status = m.status.status; renderNameplate(); }
      return;
    }
    if (m.type === "console") onConsole(m.lines);
    else if (m.type === "status") onStatus(m.status);
    else if (m.type === "stats") { S.history.push(m.point); if (S.history.length > 720) S.history.shift(); onStatus(m.status); Pages.onStats?.(); }
    else if (m.type === "players") { if (S.status) S.status.players = m.players; renderNameplate(); Pages.onPlayers?.(); }
    else if (m.type === "job") { S.job = m.job; Pages.onJob?.(); }
    else if (m.type === "schedule") Pages.onSchedule?.();
    else if (m.type === "activity") Pages.onActivity?.(m.entry);
  };
  ws.onclose = (e) => {
    clearInterval(ping);
    if (e.code === 4401) return showLogin();
    if (!$("#connbar")) document.body.insertAdjacentHTML("beforeend", '<div class="conn" id="connbar">Lost connection to the panel - reconnecting…</div>');
    setTimeout(() => S.me && connectWS(), 2500);
  };
}
function onStatus(st) {
  const prev = S.status?.status;
  const me = S.servers.find((v) => v.id === S.server);
  if (me) me.status = st.status;
  S.status = st;
  renderNameplate();
  if (prev && prev !== st.status) {
    if (st.status === "online") toast(`Server is online${st.startup_seconds ? ` (started in ${Math.round(st.startup_seconds)}s)` : ""}`);
    if (st.status === "crashed") toast("The server crashed" + (st.auto_restart ? " - restarting automatically" : ""), true);
  }
  Pages.onStatus?.();
}
function onConsole(lines) {
  const fresh = lines.filter((l) => l[0] > S.lastLine);
  if (!fresh.length) return;
  S.lastLine = fresh[fresh.length - 1][0];
  S.console.push(...fresh);
  if (S.console.length > 3000) S.console.splice(0, S.console.length - 3000);
  Pages.onConsole?.(fresh);
}

// ------------------------------------------------------------ console view
function lineClass(t) {
  if (t.startsWith("[Panel]")) return "panel-l";
  if (t.startsWith("> ")) return "cmd";
  if (/\/(ERROR|FATAL)\]|Exception|^\s+at /.test(t)) return "error";
  if (/\/WARN\]/.test(t)) return "warn";
  if (/ (joined|left) the game/.test(t)) return "join";
  if (/\]: <\w+> /.test(t)) return "chat";
  if (/\/DEBUG\]/.test(t)) return "dim";
  return "";
}
function lineHTML([n, t]) { return `<span class="l ${lineClass(t)}">${esc(t)}</span>`; }

function mountConsole(box, { filterInput, levelSelect } = {}) {
  let filter = "", level = "all";
  const matches = (l) => {
    const t = l[1];
    if (filter && !t.toLowerCase().includes(filter)) return false;
    if (level === "warn") return /WARN|ERROR|FATAL|Exception|^\s+at /.test(t);
    if (level === "error") return /ERROR|FATAL|Exception|^\s+at /.test(t);
    if (level === "chat") return /joined the game|left the game|\]: <\w+> |^> /.test(t);
    return true;
  };
  const nearBottom = () => box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  const all = () => { box.innerHTML = S.console.filter(matches).slice(-1500).map(lineHTML).join(""); box.scrollTop = box.scrollHeight; };
  all();
  if (filterInput) filterInput.oninput = () => { filter = filterInput.value.toLowerCase(); all(); };
  if (levelSelect) levelSelect.onchange = () => { level = levelSelect.value; all(); };
  return (fresh) => {
    if (!box.isConnected) return;
    const stick = nearBottom();
    box.insertAdjacentHTML("beforeend", fresh.filter(matches).map(lineHTML).join(""));
    while (box.childElementCount > 2000) box.firstElementChild.remove();
    if (stick) box.scrollTop = box.scrollHeight;
  };
}

function mountCommandInput(form) {
  const input = $("input", form);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const cmd = input.value.trim();
    if (!cmd) return;
    try {
      await api("/api/console", { body: { command: cmd } });
      S.cmdHistory = [cmd, ...S.cmdHistory.filter((c) => c !== cmd)].slice(0, 50);
      localStorageSet("cmdHistory", JSON.stringify(S.cmdHistory));
      S.cmdPos = -1;
      input.value = "";
    } catch (err) { toast(err.message, true); }
  };
  input.onkeydown = (e) => {
    if (e.key === "ArrowUp" && S.cmdHistory.length) { S.cmdPos = Math.min(S.cmdPos + 1, S.cmdHistory.length - 1); input.value = S.cmdHistory[S.cmdPos]; e.preventDefault(); }
    if (e.key === "ArrowDown") { S.cmdPos = Math.max(S.cmdPos - 1, -1); input.value = S.cmdPos < 0 ? "" : S.cmdHistory[S.cmdPos]; e.preventDefault(); }
  };
}

// ------------------------------------------------------------------ gauges
function gauge({ value, max, label, unit, sub, zones }) {
  const frac = value == null ? 0 : Math.max(0, Math.min(1, value / max));
  const cx = 120, cy = 118, r = 96;
  const pt = (f, rr) => { const a = Math.PI * (1 - f); return [cx + rr * Math.cos(a), cy - rr * Math.sin(a)]; };
  const arc = (f0, f1, rr) => { const [x0, y0] = pt(f0, rr), [x1, y1] = pt(f1, rr); return `M${x0.toFixed(1)},${y0.toFixed(1)} A${rr},${rr} 0 0 1 ${x1.toFixed(1)},${y1.toFixed(1)}`; };
  let ticks = "";
  for (let i = 0; i <= 20; i++) {
    const f = i / 20, major = i % 5 === 0;
    const [x0, y0] = pt(f, r - 2), [x1, y1] = pt(f, r - (major ? 16 : 9));
    ticks += `<line x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}" stroke="${major ? "#a66cff" : "#4b4262"}" stroke-width="${major ? 2.4 : 1.4}"/>`;
  }
  const zoneArcs = zones.map(([a, b, c]) => `<path d="${arc(a, b, r + 7)}" stroke="${c}" stroke-width="5" fill="none" opacity=".85"/>`).join("");
  const [nx, ny] = pt(frac, r - 22);
  const col = value == null ? "#4b4262" : (zones.find(([a, b]) => frac >= a && frac <= b) || [0, 0, "#a66cff"])[2];
  return `<div class="gauge">
    <svg viewBox="0 0 240 132" role="img" aria-label="${esc(label)} ${value == null ? "unknown" : value.toFixed(1) + " " + unit}">
      <path d="${arc(0, 1, r)}" stroke="#262036" stroke-width="3" fill="none"/>
      ${zoneArcs}${ticks}
      <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="${col}" stroke-width="4" stroke-linecap="round" style="transition:all .6s"/>
      <circle cx="${cx}" cy="${cy}" r="9" fill="#a66cff"/><circle cx="${cx}" cy="${cy}" r="3.5" fill="#09080c"/>
    </svg>
    <div class="read" style="color:${col}">${value == null ? "—" : (max <= 20 ? value.toFixed(1) : Math.round(value))}<small>${value == null ? "" : unit}</small></div>
    <div class="name">${esc(label)}</div><div class="sub">${sub || "&nbsp;"}</div></div>`;
}
const G = "#6fcf8e", A = "#e9b44c", R = "#ef6461";

// ------------------------------------------------------------------- chart
function drawChart(canvas, series, { max = 100, min = 0 } = {}) {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w) return;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const c = canvas.getContext("2d");
  c.scale(dpr, dpr);
  c.clearRect(0, 0, w, h);
  c.strokeStyle = "#262036"; c.lineWidth = 1;
  c.fillStyle = "#9b94ae"; c.font = "11px Barlow, sans-serif";
  for (let i = 0; i <= 4; i++) {
    const y = 6 + (h - 20) * i / 4;
    c.beginPath(); c.moveTo(30, y); c.lineTo(w, y); c.stroke();
    c.fillText(String(Math.round(max - (max - min) * i / 4)), 0, y + 4);
  }
  const pts = S.history;
  if (pts.length < 2) return;
  const t0 = pts[0].t, t1 = pts[pts.length - 1].t, span = Math.max(1, t1 - t0);
  c.fillText(`${Math.round(span / 60)} min ago`, 30, h - 1);
  c.textAlign = "right"; c.fillText("now", w, h - 1); c.textAlign = "left";
  for (const s of series) {
    c.strokeStyle = s.color; c.lineWidth = 2; c.beginPath();
    let started = false;
    for (const p of pts) {
      const v = s.get(p);
      if (v == null) { started = false; continue; }
      const x = 30 + (w - 30) * (p.t - t0) / span;
      const y = 6 + (h - 20) * (1 - (Math.min(max, v) - min) / (max - min));
      if (!started) { c.moveTo(x, y); started = true; } else c.lineTo(x, y);
    }
    c.stroke();
  }
}

function head(name, uuid, size = 32) {
  return `<img src="https://mc-heads.net/avatar/${encodeURIComponent(uuid || name)}/${size}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`;
}

// ------------------------------------------------------------------- pages
const Pages = {};
function clearHooks() { for (const k of ["onStatus", "onStats", "onConsole", "onPlayers", "onJob", "onSchedule", "onActivity", "leaveGuard"]) delete Pages[k]; window.onresize = null; window.onbeforeunload = null; }
const _route = route;

Pages.dashboard = (el) => {
  clearHooks();
  el.innerHTML = `<div class="gauges" id="gauges"></div>
    <div class="stats-strip" id="strip"></div>
    <div class="grid cols-2" style="margin-top:16px">
      <section class="panel"><h4>Players on board</h4><div id="dplayers"></div></section>
      <section class="panel"><h4>Last hour</h4>
        <div class="legend"><span><i style="background:#a66cff"></i>CPU %</span><span><i style="background:#d68cf0"></i>Memory %</span><span><i style="background:#6fcf8e"></i>TPS (×5)</span></div>
        <canvas class="chart" id="chart1"></canvas></section>
    </div>
    <section class="panel" style="margin-top:16px"><div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
      <h4 style="margin:0">Console</h4><a href="#/console" style="margin-left:auto">Open full console</a></div>
      <div class="console mini" id="mini"></div>
      ${can("moderator") ? `<form class="console-input"><input placeholder="Type a command (no slash needed) and press Enter" autocomplete="off" spellcheck="false"><button class="btn primary">Send</button></form>` : ""}
    </section>`;
  const paint = () => {
    const s = S.status;
    const memPct = s.mem && s.mem_max ? s.mem / s.mem_max * 100 : null;
    const on = s.status === "online";
    $("#gauges").innerHTML =
      gauge({ value: on ? s.tps : null, max: 20, label: "Ticks per second", unit: "TPS",
        sub: on ? (s.tps == null ? (s.rcon ? "Measuring…" : "Turn on RCON in Settings to measure") : `${s.mspt?.toFixed(1)} ms per tick`) : "Server offline",
        zones: [[0, .5, R], [.5, .85, A], [.85, 1, G]] }) +
      gauge({ value: s.cpu, max: 100, label: "Server CPU", unit: "%", sub: s.cpu != null ? `${s.cores} cores · whole machine ${Math.round(s.sys_cpu ?? 0)}%` : "", zones: [[0, .6, G], [.6, .85, A], [.85, 1, R]] }) +
      gauge({ value: memPct, max: 100, label: "Server memory", unit: "%", sub: s.mem ? `${bytes(s.mem)} of ${bytes(s.mem_max)} allocated` : "", zones: [[0, .75, G], [.75, .9, A], [.9, 1, R]] });
    const disk = s.disk;
    $("#strip").innerHTML = `
      <div class="stat"><div class="k">Uptime</div><div class="v">${on && s.started_at ? dur(Date.now() / 1000 - s.started_at) : "—"}</div></div>
      <div class="stat"><div class="k">Machine memory</div><div class="v">${bytes(s.sys_mem.used)} / ${bytes(s.sys_mem.total, 0)}</div><div class="bar"><i style="width:${s.sys_mem.percent}%"></i></div></div>
      <div class="stat"><div class="k">Disk free</div><div class="v">${disk ? bytes(disk.free) : "—"}</div>${disk ? `<div class="bar"><i style="width:${(disk.used / disk.total * 100).toFixed(0)}%"></i></div>` : ""}</div>
      <div class="stat"><div class="k">World size</div><div class="v">${bytes(s.world_size)}</div></div>`;
    const ps = s.players;
    $("#dplayers").innerHTML = ps.length ? ps.map((p) => `<div class="player">${head(p.name, p.uuid)}<div><div class="n">${esc(p.name)}</div><div class="meta">online for ${dur(p.online_for)}</div></div></div>`).join("")
      : `<div class="empty">${on ? "Nobody is online right now." : "Server is offline."}</div>`;
  };
  const chart = () => drawChart($("#chart1"), [
    { color: "#a66cff", get: (p) => p.cpu },
    { color: "#d68cf0", get: (p) => (p.mem && S.status.mem_max ? p.mem / S.status.mem_max * 100 : null) },
    { color: "#6fcf8e", get: (p) => (p.tps == null ? null : p.tps * 5) },
  ]);
  paint(); chart();
  const add = mountConsole($("#mini"));
  if (can("moderator")) mountCommandInput($(".console-input", el));
  Pages.onStatus = paint;
  Pages.onStats = chart;
  Pages.onPlayers = paint;
  Pages.onConsole = add;
  window.onresize = chart;
};

Pages.console = (el) => {
  clearHooks();
  const quick = ["list", "save-all", "neoforge tps", "time set day", "weather clear", "whitelist list"];
  el.innerHTML = `<div class="page-head"><h3>Console</h3>
    <div class="actions console-tools"><input id="cfilter" placeholder="Filter lines" spellcheck="false">
    <select id="clevel" style="width:auto"><option value="all">Everything</option><option value="warn">Warnings and errors</option><option value="error">Errors only</option><option value="chat">Chat and joins</option></select>
    <button class="btn" id="cdown">Download</button></div></div>
    <div class="console full" id="full"></div>
    ${can("moderator") ? `<form class="console-input"><input placeholder="Type a command (no slash needed) and press Enter. ↑ for history" autocomplete="off" spellcheck="false"><button class="btn primary">Send</button></form>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">${quick.map((q) => `<button class="btn small ghost" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : ""}`;
  Pages.onConsole = mountConsole($("#full"), { filterInput: $("#cfilter"), levelSelect: $("#clevel") });
  if (can("moderator")) {
    mountCommandInput($(".console-input", el));
    $$("[data-q]", el).forEach((b) => (b.onclick = () => { const i = $(".console-input input"); i.value = b.dataset.q; i.focus(); }));
  }
  $("#cdown").onclick = () => {
    const blob = new Blob([S.console.map((l) => l[1]).join("\n")], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `console-${new Date().toISOString().slice(0, 16)}.log`; a.click();
  };
};

Pages.players = async (el) => {
  clearHooks();
  let tab = "online";
  el.innerHTML = `<div class="page-head"><h3>Players</h3>
    <div class="actions">${can("moderator") ? '<button class="btn" id="wladd">Add to whitelist</button>' : ""}</div></div>
    <div class="tabs" id="ptabs"></div><div class="panel" id="plist"></div>`;
  let data;
  const load = async () => { data = await api("/api/players"); render(); };
  const m = can("moderator"), a = can("admin");
  const btn = (action, name, label, cls = "") => `<button class="btn small ${cls}" data-a="${action}" data-n="${esc(name)}">${label}</button>`;
  const render = () => {
    const opNames = new Set(data.ops.map((o) => o.name.toLowerCase()));
    const wl = new Set(data.whitelist.map((o) => o.name.toLowerCase()));
    const tabs = [["online", `Online (${data.online.length})`], ["known", `Everyone (${data.known.length})`],
      ["whitelist", `Whitelist (${data.whitelist.length})`], ["ops", `Operators (${data.ops.length})`], ["banned", `Banned (${data.banned.length})`]];
    $("#ptabs").innerHTML = tabs.map(([id, l]) => `<button class="${tab === id ? "active" : ""}" data-t="${id}">${l}</button>`).join("");
    $$("[data-t]").forEach((b) => (b.onclick = () => { tab = b.dataset.t; render(); }));
    const tags = (n) => `${opNames.has(n.toLowerCase()) ? '<span class="tag accent">operator</span> ' : ""}${data.whitelist_enabled && wl.has(n.toLowerCase()) ? '<span class="tag">whitelisted</span>' : ""}`;
    let html = "";
    if (tab === "online") {
      html = data.online.map((p) => `<div class="player">${head(p.name, p.uuid)}<div><div class="n">${esc(p.name)} ${tags(p.name)}</div><div class="meta">online for ${dur(p.online_for)}</div></div>
        ${m ? `<div class="acts">${btn("message", p.name, "Message")}${btn("kick", p.name, "Kick")}${btn("ban", p.name, "Ban", "danger")}</div>` : ""}</div>`).join("")
        || `<div class="empty">${S.status.status === "online" ? "Nobody is online right now." : "Server is offline."}</div>`;
    } else if (tab === "known") {
      html = data.known.map((p) => `<div class="player">${head(p.name, p.uuid)}<div><div class="n">${esc(p.name)} ${p.online ? '<span class="tag on">online</span>' : ""} ${tags(p.name)}</div>
        <div class="meta">Played ${dur(p.playtime)} over ${p.sessions || 0} sessions · last seen ${p.online ? "now" : ago(p.last_seen)} · first joined ${when(p.first_seen)}</div></div>
        ${m ? `<div class="acts">${a ? (opNames.has(p.name.toLowerCase()) ? btn("deop", p.name, "Remove operator") : btn("op", p.name, "Make operator")) : ""}${btn("ban", p.name, "Ban", "danger")}</div>` : ""}</div>`).join("")
        || '<div class="empty">Players show up here after they join for the first time.</div>';
    } else if (tab === "whitelist") {
      html = `<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;flex-wrap:wrap"><label class="switch"><input type="checkbox" id="wlon" ${data.whitelist_enabled ? "checked" : ""} ${a ? "" : "disabled"}> Whitelist ${data.whitelist_enabled ? "on - only these players can join" : "off - anyone can join"}</label></div>` +
        (data.whitelist.map((p) => `<div class="player">${head(p.name, p.uuid)}<div class="n">${esc(p.name)}</div>${m ? `<div class="acts">${btn("whitelist_remove", p.name, "Remove")}</div>` : ""}</div>`).join("") || '<div class="empty">The whitelist is empty.</div>');
    } else if (tab === "ops") {
      html = data.ops.map((p) => `<div class="player">${head(p.name, p.uuid)}<div><div class="n">${esc(p.name)}</div><div class="meta">Permission level ${p.level}</div></div>${a ? `<div class="acts">${btn("deop", p.name, "Remove operator")}</div>` : ""}</div>`).join("") || '<div class="empty">No operators.</div>';
    } else {
      html = data.banned.map((p) => `<div class="player">${head(p.name, p.uuid)}<div><div class="n">${esc(p.name)}</div><div class="meta">${esc(p.reason || "")} · by ${esc(p.source || "?")} · ${esc((p.created || "").slice(0, 10))}</div></div>${m ? `<div class="acts">${btn("pardon", p.name, "Unban")}</div>` : ""}</div>`).join("") || '<div class="empty">Nobody is banned.</div>';
    }
    $("#plist").innerHTML = html;
    $("#wlon")?.addEventListener("change", async (e) => { await act(api("/api/players/whitelist-mode", { body: { enabled: e.target.checked } }), e.target.checked ? "Whitelist on" : "Whitelist off"); setTimeout(load, 800); });
    $$("[data-a]", $("#plist")).forEach((b) => (b.onclick = () => playerAction(b.dataset.a, b.dataset.n).then(() => setTimeout(load, 800))));
  };
  $("#wladd")?.addEventListener("click", async () => {
    const n = await promptBox("Add to whitelist", "Minecraft username", "", "Add");
    if (n) { await act(api("/api/players/action", { body: { action: "whitelist_add", name: n.trim() } })); setTimeout(load, 800); }
  });
  Pages.onPlayers = () => load();
  await load();
};

async function playerAction(action, name) {
  let reason = "";
  if (action === "message") {
    reason = await promptBox(`Message ${name}`, "Message", "", "Send");
    if (!reason) return;
  } else if (action === "kick" || action === "ban") {
    reason = await promptBox(`${action === "kick" ? "Kick" : "Ban"} ${name}`, "Reason (shown to the player)", "", action === "kick" ? "Kick" : "Ban");
    if (reason === null) return;
  } else if (action === "op" && !(await confirmBox(`Make ${name} an operator?`, "Operators can run every command, including stopping the server and changing other players' permissions."))) return;
  await act(api("/api/players/action", { body: { action, name, reason } }));
}

Pages.mods = async (el) => {
  clearHooks();
  const a = can("admin");
  el.innerHTML = `<div class="page-head"><h3>Mods</h3><p id="modsum">Loading…</p>
    <div class="actions"><input id="msearch" placeholder="Search mods" style="width:220px">
    <select id="mshow" style="width:auto"><option value="all">All</option><option value="on">Enabled</option><option value="off">Disabled</option></select>
    ${a ? `<label class="btn primary">${icon("upload")}Upload .jar<input type="file" accept=".jar" multiple hidden id="mup"></label>` : ""}</div></div>
    <div id="mpro"></div><div class="panel dropzone" id="mlist"></div>`;
  let list = [];
  const render = () => {
    const q = $("#msearch").value.toLowerCase(), show = $("#mshow").value;
    const rows = list.filter((m) => (!q || `${m.name} ${m.id} ${m.file}`.toLowerCase().includes(q)) && (show === "all" || (show === "on") === m.enabled));
    $("#mlist").innerHTML = rows.map((m) => `<div class="mod ${m.enabled ? "" : "off"}">
      ${m.has_logo ? `<img src="/api/mods/logo?file=${encodeURIComponent(m.file)}${srvq()}" alt="" loading="lazy">` : `<div class="noimg">${esc((m.name || "?")[0].toUpperCase())}</div>`}
      <div style="min-width:0"><b>${esc(m.name)}</b> <span class="muted">${esc(m.version || "")}</span>${m.error ? ` <span class="tag red">${esc(m.error)}</span>` : ""}
        <div class="d" title="${esc(m.description || "")}">${esc(m.file)} · ${bytes(m.size)}${m.description ? " · " + esc(m.description) : ""}</div></div>
      <div class="right">${a ? `<label class="switch" title="${m.enabled ? "Disable" : "Enable"}"><input type="checkbox" data-tog="${esc(m.file)}" ${m.enabled ? "checked" : ""}></label>
        <button class="btn small ghost danger" data-del="${esc(m.file)}" aria-label="Delete ${esc(m.name)}">${icon("kill")}</button>` : (m.enabled ? "" : '<span class="tag">disabled</span>')}</div></div>`).join("")
      || '<div class="empty">No mods match.</div>';
    $$("[data-tog]").forEach((c) => (c.onchange = async () => { await act(api("/api/mods/toggle", { body: { file: c.dataset.tog, enabled: c.checked } }), c.checked ? "Mod enabled" : "Mod disabled"); load(); }));
    $$("[data-del]").forEach((b) => (b.onclick = async () => {
      if (await confirmBox("Delete this mod?", `<b>${esc(b.dataset.del)}</b> moves to the recycle bin (Files → Recycle bin) for 14 days.`, "Delete", true)) {
        await act(api("/api/mods/delete", { body: { file: b.dataset.del } }), "Mod moved to the recycle bin"); load();
      }
    }));
  };
  const load = async () => {
    list = await api("/api/mods");
    const on = list.filter((m) => m.enabled).length;
    $("#modsum").textContent = `${on} enabled${list.length - on ? `, ${list.length - on} disabled` : ""} · ${bytes(list.reduce((s, m) => s + m.size, 0))}. Changes apply after a restart. Players need matching mods on their client.`;
    render();
  };
  const upload = async (files) => {
    const fd = new FormData();
    [...files].forEach((f) => fd.append("upload", f));
    toast(`Uploading ${files.length} file${files.length > 1 ? "s" : ""}…`);
    await act(api("/api/mods/upload", { body: fd }), "Uploaded");
    load();
  };
  $("#msearch").oninput = render; $("#mshow").onchange = render;
  if (Pro.hooks.modUpdates) Pro.hooks.modUpdates($("#mpro"), { reload: () => load() });
  else if (a) $("#mpro").innerHTML = `<p class="hint pro-hint">Want to know when mods have updates? The <a href="#/settings?tab=Pro">Pro mod update checker</a> checks Modrinth and CurseForge and installs them for you.</p>`;
  if (a) {
    $("#mup").onchange = (e) => upload(e.target.files);
    dropzone($("#mlist"), (files) => upload([...files].filter((f) => f.name.endsWith(".jar"))));
  }
  await load();
};

function dropzone(zone, onFiles) {
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("drag"); if (e.dataTransfer.files.length) onFiles(e.dataTransfer.files); });
}

Pages.files = async (el) => {
  clearHooks();
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  let path = params.get("path") || "";
  el.innerHTML = `<div class="page-head"><h3>Files</h3><p>Everything inside the server folder. Deleted files go to the recycle bin for 14 days; edited files keep their last 5 versions.</p>
    <div class="actions"><button class="btn" id="fnew">${icon("plus")}New</button>
    <label class="btn primary">${icon("upload")}Upload<input type="file" multiple hidden id="fup"></label>
    <button class="btn ghost" id="ftrash">Recycle bin</button></div></div>
    <div class="panel dropzone" id="fbox"></div>`;
  const go = async (p) => {
    path = p;
    history.replaceState(null, "", `#/files${p ? "?path=" + encodeURIComponent(p) : ""}`);
    let data;
    try { data = await api(`/api/files?path=${encodeURIComponent(p)}`); } catch (e) { toast(e.message, true); return go(""); }
    const parts = data.path ? data.path.split("/") : [];
    const crumbs = `<div class="crumbs"><button data-go="">server</button>${parts.map((x, i) => `/<button data-go="${esc(parts.slice(0, i + 1).join("/"))}">${esc(x)}</button>`).join("")}</div>`;
    const rows = data.entries.map((e) => {
      const full = (data.path ? data.path + "/" : "") + e.name;
      return `<tr class="file-row ${e.dir ? "dir" : ""}" data-path="${esc(full)}" data-dir="${e.dir ? 1 : ""}" data-text="${e.text ? 1 : ""}">
        <td>${icon(e.dir ? "files" : "file")}<span>${esc(e.name)}</span></td><td class="r muted">${e.dir ? "" : bytes(e.size)}</td><td class="r muted">${when(e.mtime)}</td>
        <td class="r"><button class="btn small ghost" data-menu="${esc(full)}" aria-label="Actions for ${esc(e.name)}">•••</button></td></tr>`;
    }).join("");
    $("#fbox").innerHTML = `${crumbs}<div class="table-wrap"><table class="table" style="margin-top:10px"><thead><tr><th>Name</th><th class="r">Size</th><th class="r">Modified</th><th></th></tr></thead>
      <tbody>${parts.length ? `<tr class="file-row dir" data-path="${esc(parts.slice(0, -1).join("/"))}" data-dir="1"><td>${icon("files")}..</td><td></td><td></td><td></td></tr>` : ""}${rows}</tbody></table></div>
      ${data.entries.length ? "" : '<div class="empty">Empty folder - drop files here to upload.</div>'}`;
    $$("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
    $$(".file-row").forEach((r) => (r.onclick = (e) => {
      if (e.target.closest("[data-menu]")) return;
      if (r.dataset.dir) go(r.dataset.path);
      else if (r.dataset.text) openEditor(r.dataset.path);
      else location.href = `/api/files/download?path=${encodeURIComponent(r.dataset.path)}${srvq()}`;
    }));
    $$("[data-menu]").forEach((b) => (b.onclick = () => fileMenu(b.dataset.menu, data.entries.find((x) => x.name === b.dataset.menu.split("/").pop()), () => go(path))));
  };
  const upload = async (files) => {
    const fd = new FormData();
    [...files].forEach((f) => fd.append("upload", f, f.webkitRelativePath || f.name));
    toast(`Uploading ${files.length} file${files.length > 1 ? "s" : ""}…`);
    await act(api(`/api/files/upload?path=${encodeURIComponent(path)}`, { body: fd }), "Uploaded");
    go(path);
  };
  $("#fup").onchange = (e) => upload(e.target.files);
  dropzone($("#fbox"), upload);
  $("#fnew").onclick = async () => {
    const m = modal(`<h4>Create new</h4><form><label class="field"><span>Name</span><input name="n" placeholder="e.g. notes.txt or configs"></label>
      <div class="foot"><button type="button" class="btn ghost" data-x>Cancel</button><button type="button" class="btn" data-folder>Folder</button><button class="btn primary">File</button></div></form>`);
    const target = () => (path ? path + "/" : "") + $("[name=n]", m.el).value.trim();
    $("[data-x]", m.el).onclick = m.close;
    $("[data-folder]", m.el).onclick = async () => { await act(api("/api/files/mkdir", { body: { path: target() } }), "Folder created"); m.close(); go(path); };
    $("form", m.el).onsubmit = async (e) => { e.preventDefault(); const t = target(); await act(api("/api/files/write", { method: "PUT", body: { path: t, content: "" } }), "File created"); m.close(); openEditor(t); };
  };
  $("#ftrash").onclick = () => trashModal(() => go(path));
  await go(path);
};

function fileMenu(full, entry, refresh) {
  const isZip = /\.zip$/i.test(full);
  const m = modal(`<h4>${esc(full.split("/").pop())}</h4><div style="display:grid;gap:8px">
    ${entry?.text && /\.(toml|json|json5|cfg|ya?ml|properties|snbt)$/i.test(full) ? '<button class="btn primary" data-x="configs">Open in Configs</button>' : ""}
    ${entry?.text ? '<button class="btn" data-x="edit">Edit as plain text</button>' : ""}
    <button class="btn" data-x="download">${icon("download")}Download${entry?.dir ? " as zip" : ""}</button>
    <button class="btn" data-x="rename">Rename</button>
    <button class="btn" data-x="move">Move to folder…</button>
    ${isZip ? '<button class="btn" data-x="extract">Extract here</button>' : ""}
    <button class="btn danger" data-x="delete">Delete</button></div>
    <div class="foot"><button class="btn ghost" data-close>Close</button></div>`);
  $("[data-close]", m.el).onclick = m.close;
  $$("[data-x]", m.el).forEach((b) => (b.onclick = async () => {
    m.close();
    const x = b.dataset.x;
    if (x === "edit") openEditor(full);
    if (x === "configs") location.hash = `#/configs?file=${encodeURIComponent(full)}`;
    if (x === "download") location.href = `/api/files/download?path=${encodeURIComponent(full)}${srvq()}`;
    if (x === "rename") { const n = await promptBox("Rename", "New name", full.split("/").pop(), "Rename"); if (n) { await act(api("/api/files/rename", { body: { path: full, name: n } }), "Renamed"); refresh(); } }
    if (x === "move") { const d = await promptBox("Move", "Destination folder (inside the server folder)", full.split("/").slice(0, -1).join("/"), "Move", "e.g. config or world/datapacks. Leave blank for the top level."); if (d !== null) { await act(api("/api/files/move", { body: { path: full, dest: d } }), "Moved"); refresh(); } }
    if (x === "extract") { await act(api("/api/files/extract", { body: { path: full } }), "Extracted"); refresh(); }
    if (x === "delete" && await confirmBox("Delete?", `<b>${esc(full)}</b> moves to the recycle bin for 14 days.`, "Delete", true)) { await act(api("/api/files/delete", { body: { path: full } }), "Moved to the recycle bin"); refresh(); }
  }));
}

async function openEditor(path) {
  let f;
  try { f = await api(`/api/files/read?path=${encodeURIComponent(path)}`); } catch (e) { return toast(e.message, true); }
  const m = modal(`<h4 style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">${esc(path)}<span class="muted" style="font:13px var(--body)" id="edstate"></span></h4>
    <textarea class="editor" spellcheck="false" id="ed"></textarea>
    <div class="foot"><span class="hint" style="margin-right:auto">Ctrl+S saves. Most config changes need a server restart.</span><button class="btn ghost" data-x>Close</button><button class="btn primary" data-save>Save</button></div>`, { wide: true });
  const ta = $("#ed", m.el);
  ta.value = f.content;
  let mtime = f.mtime, dirty = false;
  ta.oninput = () => { dirty = true; $("#edstate").textContent = "unsaved changes"; };
  ta.onkeydown = (e) => {
    if (e.key === "Tab") { e.preventDefault(); const s = ta.selectionStart; ta.setRangeText("  ", s, ta.selectionEnd, "end"); ta.oninput(); }
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
  };
  const save = async () => {
    const r = await act(api("/api/files/write", { method: "PUT", body: { path, content: ta.value, mtime } }), "Saved");
    mtime = r.mtime; dirty = false; $("#edstate").textContent = "saved";
  };
  $("[data-save]", m.el).onclick = save;
  $("[data-x]", m.el).onclick = async () => { if (!dirty || await confirmBox("Discard changes?", "You have unsaved edits.", "Discard", true)) m.close(); };
  ta.focus();
}

async function trashModal(refresh) {
  const items = await api("/api/trash");
  const m = modal(`<h4>Recycle bin</h4><p class="muted">Items are removed for good after 14 days.</p>
    ${items.length ? `<table class="table"><tbody>${items.map((i) => `<tr><td>${esc(i.original)}</td><td class="r muted">${when(i.deleted)}</td><td class="r"><button class="btn small" data-r="${esc(i.id)}">Restore</button></td></tr>`).join("")}</tbody></table>` : '<div class="empty">The recycle bin is empty.</div>'}
    <div class="foot">${items.length ? '<button class="btn danger" data-empty>Empty now</button>' : ""}<button class="btn ghost" data-x>Close</button></div>`, { wide: true });
  $("[data-x]", m.el).onclick = m.close;
  $$("[data-r]", m.el).forEach((b) => (b.onclick = async () => { await act(api("/api/trash/restore", { body: { id: b.dataset.r } }), "Restored"); m.close(); refresh(); }));
  $("[data-empty]", m.el)?.addEventListener("click", async () => { if (await confirmBox("Empty the recycle bin?", "Everything in it is deleted permanently.", "Empty", true)) { await act(api("/api/trash/empty", { body: {} })); m.close(); } });
}

Pages.backups = async (el) => {
  clearHooks();
  const m = can("moderator"), a = can("admin");
  el.innerHTML = `<div class="page-head"><h3>Backups</h3><p id="bsum"></p>
    <div class="actions">${m ? `<button class="btn primary" id="bnew">Back up now</button>` : ""}</div></div>
    <div id="bjob"></div><div class="panel" id="blist"></div>`;
  let data;
  const renderJob = () => {
    const j = S.job || data?.job;
    $("#bjob").innerHTML = j ? `<div class="job"><b>${j.kind === "backup" ? "Backing up" : "Restoring"}</b> · ${esc(j.stage)}${j.progress ? ` · ${j.progress}%` : ""}
      <div class="bar"><i style="width:${j.progress || 3}%"></i></div></div>` : "";
    if ($("#bnew")) $("#bnew").disabled = !!j;
  };
  const load = async () => {
    data = await api("/api/backups");
    S.job = data.job;
    const total = data.backups.reduce((s, b) => s + b.size, 0);
    $("#bsum").textContent = `${data.backups.length} backups using ${bytes(total)} · ${bytes(data.disk_free)} free · stored in ${data.dir}. Automatic backups beyond the newest ${data.keep} are deleted unless locked.`;
    renderJob();
    $("#blist").innerHTML = data.backups.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Backup</th><th>Made</th><th class="r">Size</th><th></th></tr></thead><tbody>
      ${data.backups.map((b) => `<tr><td><b>${esc(b.note || (b.auto ? "Automatic backup" : "Manual backup"))}</b>
        ${b.auto ? '<span class="tag">auto</span>' : '<span class="tag accent">manual</span>'} ${b.locked ? '<span class="tag on">locked</span>' : ""}
        <div class="muted" style="font-size:13px">${esc(b.file)}${b.by ? " · by " + esc(b.by) : ""}</div></td>
        <td>${when(b.created)}<div class="muted" style="font-size:13px">${ago(b.created)}</div></td><td class="r">${bytes(b.size)}</td>
        <td class="r" style="white-space:nowrap">
          ${m ? `<button class="btn small ghost" data-lock="${esc(b.file)}" data-v="${b.locked ? "" : 1}">${b.locked ? "Unlock" : "Lock"}</button>` : ""}
          ${a ? `<a class="btn small ghost" href="/api/backups/${encodeURIComponent(b.file)}/download?x=1${srvq()}">${icon("download")}</a>
          <button class="btn small" data-restore="${esc(b.file)}">Restore</button>
          <button class="btn small ghost danger" data-del="${esc(b.file)}" aria-label="Delete">${icon("kill")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`
      : '<div class="empty">No backups yet. Make one now, or set up automatic backups on the Schedule page.</div>';
    $$("[data-lock]").forEach((b) => (b.onclick = async () => { await act(api(`/api/backups/${encodeURIComponent(b.dataset.lock)}`, { method: "PATCH", body: { locked: !!b.dataset.v } }), b.dataset.v ? "Locked - it won't be auto-deleted" : "Unlocked"); load(); }));
    $$("[data-del]").forEach((b) => (b.onclick = async () => { if (await confirmBox("Delete backup?", `<b>${esc(b.dataset.del)}</b> is deleted permanently.`, "Delete", true)) { await act(api(`/api/backups/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" }), "Backup deleted"); load(); } }));
    $$("[data-restore]").forEach((b) => (b.onclick = async () => {
      if (S.status.status !== "offline" && S.status.status !== "crashed") return toast("Stop the server before restoring a backup", true);
      if (await confirmBox("Restore this backup?", `The world is replaced with <b>${esc(b.dataset.restore)}</b>. Your current world isn't deleted - it's renamed to <i>world.before-restore-…</i> in the server folder so you can go back.`, "Restore", true)) {
        await act(api(`/api/backups/${encodeURIComponent(b.dataset.restore)}/restore`, { body: {} }), "Backup restored"); load();
      }
    }));
  };
  $("#bnew")?.addEventListener("click", async () => {
    const note = await promptBox("Back up now", "Label (optional)", "", "Start backup", "The world keeps running - saving is paused for a moment while the backup is taken.");
    if (note === null) return;
    await act(api("/api/backups", { body: { note } }));
  });
  Pages.onJob = () => { renderJob(); if (!S.job) load(); };
  await load();
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
Pages.schedule = async (el) => {
  clearHooks();
  const a = can("admin");
  el.innerHTML = `<div class="page-head"><h3>Schedule</h3><p id="ssum"></p>
    <div class="actions">${a ? `<button class="btn primary" id="snew">${icon("plus")}New task</button>` : ""}</div></div><div class="panel" id="slist"></div>`;
  let data;
  const describe = (t) => {
    const timing = t.mode === "interval" ? `Every ${t.every_minutes >= 60 && t.every_minutes % 60 === 0 ? `${t.every_minutes / 60} hour${t.every_minutes === 60 ? "" : "s"}` : `${t.every_minutes} minutes`}`
      : `${t.days.length === 7 ? "Every day" : t.days.map((d) => DAYS[d]).join(", ")} at ${t.times.join(", ")}`;
    const extra = t.kind === "restart" || t.kind === "stop" ? ` · ${t.warn_minutes || 0} min warning` : t.arg ? ` · ${t.arg}` : "";
    return timing + extra;
  };
  const load = async () => {
    data = await api("/api/schedule");
    $("#ssum").textContent = `Times are in ${data.timezone} (change it in Settings).`;
    $("#slist").innerHTML = data.tasks.map((t) => `<div class="task">
      ${a ? `<label class="switch"><input type="checkbox" data-en="${esc(t.id)}" ${t.enabled ? "checked" : ""} aria-label="Enabled"></label>` : `<span class="lamp ${t.enabled ? "online" : ""}"></span>`}
      <div><b>${esc(t.name)}</b> <span class="tag">${esc(t.kind)}</span><div class="when">${esc(describe(t))}</div>
        <div class="when">Next: ${t.next_run ? when(t.next_run) : "—"} · Last: ${t.last_run ? `${when(t.last_run)} (${esc(t.last_result || "")})` : "never"}</div></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:end">${can("moderator") ? `<button class="btn small" data-run="${esc(t.id)}">Run now</button>` : ""}
        ${a ? `<button class="btn small ghost" data-ed="${esc(t.id)}">Edit</button><button class="btn small ghost danger" data-del="${esc(t.id)}" aria-label="Delete">${icon("kill")}</button>` : ""}</div></div>`).join("")
      || '<div class="empty">No scheduled tasks yet.</div>';
    $$("[data-en]").forEach((c) => (c.onchange = async () => { const t = data.tasks.find((x) => x.id === c.dataset.en); await act(api("/api/schedule", { body: { ...t, enabled: c.checked } }), c.checked ? "Task on" : "Task off"); load(); }));
    $$("[data-run]").forEach((b) => (b.onclick = async () => { await act(api(`/api/schedule/${b.dataset.run}/run`, { body: {} })); load(); }));
    $$("[data-ed]").forEach((b) => (b.onclick = () => editTask(data.tasks.find((x) => x.id === b.dataset.ed))));
    $$("[data-del]").forEach((b) => (b.onclick = async () => { if (await confirmBox("Delete task?", "", "Delete", true)) { await act(api(`/api/schedule/${b.dataset.del}`, { method: "DELETE" }), "Task deleted"); load(); } }));
  };
  const editTask = (t = { kind: "restart", mode: "daily", times: ["05:00"], days: [0, 1, 2, 3, 4, 5, 6], warn_minutes: 5, enabled: true, only_if_online: true }) => {
    const m = modal(`<h4>${t.id ? "Edit task" : "New task"}</h4><form>
      <label class="field"><span>What to do</span><select name="kind">${Object.entries(data.kinds).map(([k, v]) => `<option value="${k}" ${t.kind === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
      <label class="field"><span>Name</span><input name="name" value="${esc(t.name || "")}" placeholder="e.g. Nightly restart"></label>
      <label class="field" data-show="command broadcast restart stop"><span data-arglabel>Command</span><input name="arg" value="${esc(t.arg || "")}"></label>
      <label class="field" data-show="restart stop"><span>Warn players this many minutes before</span><input name="warn_minutes" type="number" min="0" max="30" value="${t.warn_minutes ?? 5}"></label>
      <label class="field"><span>When</span><select name="mode"><option value="daily" ${t.mode !== "interval" ? "selected" : ""}>At set times</option><option value="interval" ${t.mode === "interval" ? "selected" : ""}>Repeat every…</option></select></label>
      <div data-mode="daily"><label class="field"><span>Times (comma separated, 24-hour)</span><input name="times" value="${esc((t.times || []).join(", "))}" placeholder="05:00, 17:00"></label>
        <div class="field"><span style="font-weight:600;display:block;margin-bottom:5px">Days</span><div class="days">${DAYS.map((d, i) => `<label><input type="checkbox" name="day" value="${i}" ${(t.days || []).includes(i) ? "checked" : ""}><span>${d}</span></label>`).join("")}</div></div></div>
      <div data-mode="interval"><label class="field"><span>Every (minutes)</span><input name="every_minutes" type="number" min="5" value="${t.every_minutes || 360}"></label></div>
      <label class="switch field" data-show="backup"><input type="checkbox" name="only_if_played" ${t.only_if_played ? "checked" : ""}> Skip if nobody has played since the last run</label>
      <label class="switch field" data-show="command broadcast restart"><input type="checkbox" name="only_if_online" ${t.only_if_online !== false ? "checked" : ""}> Only when the server is online</label>
      <div class="foot"><button type="button" class="btn ghost" data-x>Cancel</button><button class="btn primary">Save task</button></div></form>`);
    const f = $("form", m.el);
    const sync = () => {
      $$("[data-show]", f).forEach((x) => (x.hidden = !x.dataset.show.split(" ").includes(f.kind.value)));
      $$("[data-mode]", f).forEach((x) => (x.hidden = x.dataset.mode !== f.mode.value));
      $("[data-arglabel]", f).textContent = { command: "Command (no slash)", broadcast: "Message", restart: "Reason shown to players (optional)", stop: "Reason shown to players (optional)" }[f.kind.value] || "";
    };
    f.kind.onchange = f.mode.onchange = sync; sync();
    $("[data-x]", m.el).onclick = m.close;
    f.onsubmit = async (e) => {
      e.preventDefault();
      const body = { id: t.id, enabled: t.enabled ?? true, kind: f.kind.value, name: f.name.value, arg: f.arg.value, mode: f.mode.value,
        warn_minutes: +f.warn_minutes.value, every_minutes: +f.every_minutes.value,
        times: f.times.value.split(",").map((x) => x.trim()).filter(Boolean), days: $$("[name=day]:checked", f).map((x) => +x.value),
        only_if_played: f.only_if_played.checked, only_if_online: f.only_if_online.checked };
      await act(api("/api/schedule", { body }), "Task saved");
      m.close(); load();
    };
  };
  $("#snew")?.addEventListener("click", () => editTask());
  Pages.onSchedule = load;
  await load();
};

Pages.logs = async (el) => {
  clearHooks();
  el.innerHTML = `<div class="page-head"><h3>Logs</h3><p>Past server logs and crash reports. Today's live output is on the Console page.</p></div>
    <div class="grid" style="grid-template-columns:minmax(220px,300px) 1fr"><div class="panel" id="llist" style="max-height:calc(100vh - 260px);overflow:auto"></div>
    <div><div class="console-tools" style="margin-bottom:8px"><b id="lname" style="font:600 18px var(--display)">Pick a log</b><input id="lfilter" placeholder="Filter lines" style="margin-left:auto"></div>
    <div class="console full" id="lview"></div></div></div>`;
  if (innerWidth < 860) $(".grid", el).style.gridTemplateColumns = "1fr";
  const logs = await api("/api/logs");
  let content = "";
  const show = () => {
    const q = $("#lfilter").value.toLowerCase();
    const lines = content.split("\n").filter((l) => !q || l.toLowerCase().includes(q));
    $("#lview").innerHTML = lines.slice(-5000).map((t, i) => lineHTML([i, t])).join("");
  };
  $("#llist").innerHTML = logs.map((l) => `<div class="player" style="cursor:pointer" data-f="${esc(l.file)}"><div><div class="n" style="font-weight:500">${esc(l.file.split("/").pop())} ${l.crash ? '<span class="tag red">crash</span>' : ""}</div><div class="meta">${when(l.mtime)} · ${bytes(l.size)}</div></div></div>`).join("") || '<div class="empty">No logs yet.</div>';
  $$("[data-f]", el).forEach((d) => (d.onclick = async () => {
    $("#lname").textContent = d.dataset.f;
    $("#lview").textContent = "Loading…";
    content = (await api(`/api/logs/view?file=${encodeURIComponent(d.dataset.f)}`)).content;
    show();
    $("#lview").scrollTop = d.dataset.f.startsWith("crash") ? 0 : $("#lview").scrollHeight;
  }));
  $("#lfilter").oninput = show;
  const crash = logs.find((l) => l.crash);
  (crash && S.status.status === "crashed" ? $(`[data-f="${CSS.escape(crash.file)}"]`) : $("[data-f]"))?.click();
};

Pages.settings = async (el) => {
  clearHooks();
  const a = can("admin");
  const d = await api("/api/settings");
  const p = d.properties;
  const groups = {};
  d.fields.forEach((f) => (groups[f.group] ||= []).push(f));
  const input = (f) => {
    const v = p[f.key] ?? "";
    const dis = a ? "" : "disabled";
    if (f.type === "bool") return `<label class="switch field"><input type="checkbox" name="${f.key}" ${v === "true" ? "checked" : ""} ${dis}> <span><b>${esc(f.key)}</b><small class="hint" style="margin:0">${esc(f.help)}</small></span></label>`;
    let ctl;
    if (Array.isArray(f.type)) ctl = `<select name="${f.key}" ${dis}>${f.type.map((o) => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
    else ctl = `<input name="${f.key}" type="${f.type === "number" ? "number" : f.type === "password" ? "password" : "text"}" value="${esc(v)}" ${dis}>`;
    return `<label class="field"><span>${esc(f.key)}</span>${ctl}<small>${esc(f.help)}</small></label>`;
  };
  const ramGB = Math.floor(d.system_ram / 1024 ** 3);
  el.innerHTML = `<div class="page-head"><h3>Settings</h3><p>Server settings apply after a restart.</p></div>
    <div class="tabs" id="stabs">${["Server", "Memory", ...(a ? ["Panel", "Users", ...Pro.hooks.settingsTabs.map((t) => t.name), "Pro"] : []), "My account"].map((t, i) => `<button data-t="${esc(t)}" class="${i ? "" : "active"}">${t === "Pro" ? `Pro${S.me.pro?.licensed ? "" : ' <span class="tag accent">new</span>'}` : esc(t)}</button>`).join("")}</div>
    <div data-tab="Server"><form id="propform">
      ${!p["enable-rcon"] || p["enable-rcon"] !== "true" ? `<div class="job">RCON is off, so the panel can't measure TPS or check the player list. ${a ? '<button type="button" class="btn small primary" id="rconon">Turn on RCON</button>' : ""}</div>` : ""}
      <div class="grid cols-2">${Object.entries(groups).map(([g, fs]) => `<section class="panel"><h4>${esc(g)}</h4>${fs.map(input).join("")}</section>`).join("")}
      <section class="panel"><h4>Other</h4><p class="hint" style="margin-top:0">Everything else in server.properties.</p>${d.other.map((k) => `<label class="field"><span>${esc(k)}</span><input name="${esc(k)}" value="${esc(p[k])}" ${a ? "" : "disabled"}></label>`).join("")}</section></div>
      ${a ? '<div style="margin-top:16px"><button class="btn primary">Save server.properties</button></div>' : ""}</form></div>
    <div data-tab="Memory" hidden><section class="panel" style="max-width:560px"><h4>Server memory (RAM)</h4>
      ${d.jvm.available ? `<form id="jvmform"><label class="field"><span>Maximum memory: <b id="xmxv">${d.jvm.xmx_gb ?? "not set"}</b> GB</span>
        <input type="range" name="xmx" min="2" max="${ramGB}" value="${d.jvm.xmx_gb || Math.min(10, ramGB)}" style="width:100%" ${a ? "" : "disabled"}>
        <small>This machine has ${ramGB} GB. Big modpacks run well with 8–12 GB; leave 2–3 GB for Linux and the panel. Saved to user_jvm_args.txt.</small></label>
        <label class="switch field"><input type="checkbox" name="same" ${d.jvm.xms_gb ? "checked" : ""} ${a ? "" : "disabled"}> Reserve it all at startup (-Xms, smoother on a dedicated machine)</label>
        ${a ? '<button class="btn primary">Save memory</button>' : ""}</form>`
      : `<p class="muted">No user_jvm_args.txt in the server folder, so memory is set in your start command (the -Xmx flag).</p>`}</section></div>
    ${a ? `<div data-tab="Panel" hidden><form id="panelform" class="grid cols-2">
      <section class="panel"><h4>Server</h4>
        <label class="field"><span>Display name</span><input name="name" value="${esc(d.server.name)}"></label>
        <label class="field"><span>Address players join with</span><input name="address" value="${esc(d.server.address || "")}"></label>
        <label class="field"><span>Server folder</span><input name="dir" value="${esc(d.server.dir)}"></label>
        <label class="field"><span>Start command</span><input name="start_command" value="${esc(d.server.start_command)}"><small>Run inside the server folder. For NeoForge packs use <code>bash run.sh nogui</code>, not a start script that restarts itself.</small></label>
        <label class="field"><span>Seconds to wait for a clean stop</span><input name="stop_timeout" type="number" value="${d.server.stop_timeout}"></label>
        <label class="switch field"><input type="checkbox" name="auto_restart_on_crash" ${d.server.auto_restart_on_crash ? "checked" : ""}> Restart automatically after a crash (gives up after ${d.server.max_crash_restarts} crashes in 10 minutes)</label></section>
      <section class="panel"><h4>Backups and panel</h4>
        <label class="field"><span>Backup folder</span><input name="bdir" value="${esc(d.backups.dir || "")}" placeholder="${esc(d.backups.dir_effective)}"><small>Leave blank to use ${esc(d.backups.dir_effective)}</small></label>
        <label class="field"><span>Automatic backups to keep</span><input name="keep" type="number" min="1" value="${d.backups.keep}"></label>
        <label class="field"><span>Also back up (comma separated, relative to the server folder)</span><input name="include" value="${esc((d.backups.include || []).join(", "))}"><small>The world is always included. Useful: config, serverconfig, defaultconfigs</small></label>
        <label class="field"><span>Compression</span><select name="compression"><option value="gzip" ${d.backups.compression !== "zstd" ? "selected" : ""}>gzip (works everywhere)</option><option value="zstd" ${d.backups.compression === "zstd" ? "selected" : ""}>zstd (much faster, needs zstd installed)</option></select></label>
        <label class="field"><span>Panel title</span><input name="title" value="${esc(d.panel.title)}"></label>
        <label class="field"><span>Time zone for schedules</span><input name="timezone" value="${d.panel.timezone_set ? esc(d.panel.timezone) : ""}" placeholder="${esc(d.panel.timezone)} (this machine's)"><small>Leave blank to use this machine's time zone. Names look like America/New_York or Europe/London.</small></label></section>
      <div><button class="btn primary">Save panel settings</button></div></form></div>
    <div data-tab="Users" hidden><section class="panel" style="max-width:720px"><h4>Panel users</h4><div id="ulist"></div>
      <button class="btn" id="uadd" style="margin-top:12px">${icon("plus")}Add user</button>
      <div class="hint" style="margin-top:14px">${Object.entries(S.me.roles).map(([r, h]) => `<b>${r}</b>: ${esc(h)}`).join("<br>")}</div></section></div>` : ""}
    ${a ? Pro.hooks.settingsTabs.map((t) => `<div data-tab="${esc(t.name)}" hidden></div>`).join("") + `<div data-tab="Pro" hidden></div>` : ""}
    <div data-tab="My account" hidden><section class="panel" style="max-width:480px"><h4>Change password</h4><form id="pwform">
      <label class="field"><span>Current password</span><input type="password" name="current" autocomplete="current-password"></label>
      <label class="field"><span>New password</span><input type="password" name="new" autocomplete="new-password" minlength="8"></label>
      <button class="btn primary">Change password</button></form></section></div>`;
  const showTab = (name) => {
    $$("#stabs button").forEach((x) => x.classList.toggle("active", x.dataset.t === name));
    $$("[data-tab]", el).forEach((t) => (t.hidden = t.dataset.tab !== name));
    const box = $(`[data-tab="${CSS.escape(name)}"]`, el);
    if (box && !box.dataset.rendered) {
      const hook = Pro.hooks.settingsTabs.find((t) => t.name === name);
      if (hook) { box.dataset.rendered = 1; hook.render(box); }
      if (name === "Pro") { box.dataset.rendered = 1; renderProTab(box); }
    }
  };
  $$("#stabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.t)));
  const want = new URLSearchParams(location.hash.split("?")[1] || "").get("tab");
  if (want && $(`#stabs [data-t="${CSS.escape(want)}"]`)) showTab(want);
  $("#rconon")?.addEventListener("click", async () => { await act(api("/api/settings/enable-rcon", { body: {} }), "RCON turned on"); Pages.settings(el); });
  $("#propform").onsubmit = async (e) => {
    e.preventDefault();
    // only send what actually changed, so keys missing from the file aren't written as blanks
    const out = {};
    $$("[name]", e.target).forEach((i) => {
      const v = i.type === "checkbox" ? String(i.checked) : i.value;
      const was = p[i.name];
      if (was === undefined ? (i.type === "checkbox" ? i.checked : v !== "") : v !== was) out[i.name] = v;
    });
    if (!Object.keys(out).length) return toast("Nothing changed");
    await act(api("/api/settings/properties", { method: "PUT", body: out }), "server.properties saved");
    Object.assign(p, out);
  };
  const jf = $("#jvmform");
  if (jf) {
    jf.xmx.oninput = () => ($("#xmxv").textContent = jf.xmx.value);
    jf.onsubmit = async (e) => { e.preventDefault(); await act(api("/api/settings/jvm", { method: "PUT", body: { xmx_gb: +jf.xmx.value, xms_gb: jf.same.checked ? +jf.xmx.value : null } }), "Memory saved"); };
  }
  $("#panelform")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    await act(api("/api/settings/panel", { method: "PUT", body: {
      server: { name: f.name.value, address: f.address.value, dir: f.dir.value, start_command: f.start_command.value, stop_timeout: +f.stop_timeout.value, auto_restart_on_crash: f.auto_restart_on_crash.checked },
      backups: { dir: f.bdir.value, keep: +f.keep.value, include: f.include.value.split(",").map((x) => x.trim()).filter(Boolean), compression: f.compression.value },
      panel: { title: f.title.value, timezone: f.timezone.value } } }), "Panel settings saved");
  });
  $("#pwform").onsubmit = async (e) => { e.preventDefault(); await act(api("/api/me/password", { body: { current: e.target.current.value, new: e.target.new.value } }), "Password changed"); e.target.reset(); };
  if (a) {
    const loadUsers = async () => {
      const us = await api("/api/users");
      $("#ulist").innerHTML = `<table class="table"><tbody>${us.map((u) => `<tr><td><b>${esc(u.username)}</b></td><td>${esc(u.role)}</td><td class="r">
        <button class="btn small ghost" data-ue="${esc(u.username)}" data-r="${esc(u.role)}">Edit</button>
        ${u.username !== S.me.username ? `<button class="btn small ghost danger" data-ud="${esc(u.username)}">Remove</button>` : ""}</td></tr>`).join("")}</tbody></table>`;
      $$("[data-ue]").forEach((b) => (b.onclick = () => userModal(b.dataset.ue, b.dataset.r)));
      $$("[data-ud]").forEach((b) => (b.onclick = async () => { if (await confirmBox(`Remove ${b.dataset.ud}?`, "They won't be able to sign in any more.", "Remove", true)) { await act(api(`/api/users/${encodeURIComponent(b.dataset.ud)}`, { method: "DELETE" }), "User removed"); loadUsers(); } }));
    };
    const userModal = (name = "", role = "moderator") => {
      const m = modal(`<h4>${name ? "Edit " + esc(name) : "Add user"}</h4><form>
        <label class="field"><span>Username</span><input name="username" value="${esc(name)}" ${name ? "readonly" : ""}></label>
        <label class="field"><span>Role</span><select name="role">${["viewer", "moderator", "admin"].map((r) => `<option ${r === role ? "selected" : ""}>${r}</option>`).join("")}</select></label>
        <label class="field"><span>${name ? "New password (leave blank to keep)" : "Password"}</span><input type="password" name="password" autocomplete="new-password"></label>
        <div class="foot"><button type="button" class="btn ghost" data-x>Cancel</button><button class="btn primary">Save user</button></div></form>`);
      $("[data-x]", m.el).onclick = m.close;
      $("form", m.el).onsubmit = async (e) => { e.preventDefault(); const f = e.target; await act(api("/api/users", { body: { username: f.username.value, role: f.role.value, password: f.password.value } }), "User saved"); m.close(); loadUsers(); };
    };
    $("#uadd").onclick = () => userModal();
    loadUsers();
  }
};

// Settings -> Pro: what Pro adds, installing the add-on and activating a licence key
async function renderProTab(box) {
  const st = await api("/api/pro");
  S.me.pro = st;
  const feats = st.features.map((f) => `<div class="pro-feat ${st.active?.includes(f.id) ? "on" : ""}"><b>${esc(f.name)}</b><span>${esc(f.text)}</span></div>`).join("");
  let main;
  if (!st.installed) {
    main = `<p>Pro is an optional add-on that adds the features below. The free panel keeps working exactly as it is.</p>
      <ol class="steps"><li><a class="btn primary" href="${esc(st.buy_url)}" target="_blank" rel="noopener">Get Pro on Gumroad</a> <span class="hint" style="display:inline">US$14.99 once, includes updates</span></li>
      <li>Download <b>craftlehem-pro.zip</b> from your Gumroad receipt and upload it here:
        <div style="margin-top:8px"><label class="btn">${icon("upload")}Upload craftlehem-pro.zip<input type="file" accept=".zip" hidden id="proup"></label></div></li>
      <li>Paste the licence key from your receipt to activate it.</li></ol>`;
  } else if (!st.loaded) {
    main = `<div class="cfg-valid bad">The Pro add-on is installed but didn't load: ${esc(st.error || "unknown error")}. Re-upload the latest zip from your Gumroad library.</div>
      <label class="btn" style="margin-top:10px">${icon("upload")}Upload craftlehem-pro.zip<input type="file" accept=".zip" hidden id="proup"></label>`;
  } else if (!st.licensed) {
    main = `<p>The Pro add-on (v${esc(st.version || "?")}) is installed. Paste the licence key from your Gumroad receipt to turn it on.</p>
      ${st.licence_error ? `<div class="cfg-valid bad">${esc(st.licence_error)}</div>` : ""}
      <form id="proact" class="pro-key"><input name="key" placeholder="XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX" autocomplete="off" spellcheck="false" required>
      <button class="btn primary">Activate</button></form>
      <p class="hint">Don't have a key? <a href="${esc(st.buy_url)}" target="_blank" rel="noopener">Get Pro on Gumroad</a>.</p>`;
  } else {
    main = `<div class="cfg-valid good">Pro is active${st.email ? ` - licensed to ${esc(st.email)}` : ""}. Thanks for supporting the panel!</div>
      <p class="hint">Add-on v${esc(st.version || "?")} · licence last checked ${when(st.checked_at)}${st.offline_until ? ` · works offline until ${when(st.offline_until)}` : ""}</p>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px"><label class="btn">${icon("upload")}Update Pro (upload new zip)<input type="file" accept=".zip" hidden id="proup"></label>
      <button class="btn ghost danger" id="prodeact">Remove licence from this panel</button></div>`;
  }
  box.innerHTML = `<div class="grid cols-2"><section class="panel"><h4>Craftlehem Pro</h4>${main}</section>
    <section class="panel"><h4>What Pro adds</h4><div class="pro-feats">${feats}</div></section></div>`;
  $("#proup", box)?.addEventListener("change", async (e) => {
    const fd = new FormData(); fd.append("upload", e.target.files[0]);
    const r = await act(api("/api/pro/upload", { body: fd }), false);
    if (r.restarting) { toast(`${r.message}. The panel is restarting - this page reloads in a few seconds.`); setTimeout(() => location.reload(), 6000); }
    else toast(`${r.message}. Restart the panel to load it: sudo systemctl restart craftlehem-panel`);
  });
  $("#proact", box)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const r = await act(api("/api/pro/activate", { body: { key: e.target.key.value.trim() } }), false);
    toast(r.message || "Pro activated");
    setTimeout(() => location.reload(), 1200);
  });
  $("#prodeact", box)?.addEventListener("click", async () => {
    if (await confirmBox("Remove the licence from this panel?", "Pro features turn off here. You can activate the same key again later, for example on a new machine.", "Remove", true)) {
      await act(api("/api/pro/deactivate", { body: {} }), "Licence removed"); setTimeout(() => location.reload(), 800);
    }
  });
}

Pages.activity = async (el) => {
  clearHooks();
  el.innerHTML = `<div class="page-head"><h3>Activity</h3><p>Who did what in the panel, plus crashes and scheduled tasks.</p></div><div class="panel" id="alist"></div>`;
  const sname = (id) => (S.servers.length > 1 && id ? `<span class="tag">${esc(S.servers.find((x) => x.id === id)?.name || id)}</span> ` : "");
  const row = (e) => `<div class="act"><span class="t">${when(e.t)}</span><span class="u">${esc(e.user)}</span><span>${sname(e.server)}${esc(e.action)} ${e.detail ? `<span class="muted">${esc(e.detail)}</span>` : ""}</span></div>`;
  const list = await api("/api/activity");
  $("#alist").innerHTML = list.map(row).join("") || '<div class="empty">Nothing yet.</div>';
  Pages.onActivity = (e) => { $(".empty", $("#alist"))?.remove(); $("#alist").insertAdjacentHTML("afterbegin", row(e)); };
};

// keep the uptime text in the nameplate ticking
setInterval(() => { if (S.status && ["online", "starting"].includes(S.status.status)) renderNameplate(); }, 30000);

boot();
