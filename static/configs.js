/* Configs page: browse mod configs, search inside them, edit as text with mistake-checking, history.
   The form-style "Settings" view comes from the optional Pro add-on (Pro.hooks.configForm). */
"use strict";

// ------------------------------------------------------------------- page
Pages.configs = async (el) => {
  clearHooks();
  const st = { data: null, file: null, text: "", saved: "", mtime: null, view: "form", fieldFilter: "", jump: null };
  el.innerHTML = `<div class="page-head"><h3>Configs</h3>
    <p>Every mod config on the server, grouped by mod. Pick one to edit it. Files are checked for mistakes before saving, and every save can be undone.</p></div>
    <div class="cfg-layout">
      <aside class="panel cfg-side">
        <input id="cfgq" placeholder="Find a mod, file or setting" spellcheck="false" autocomplete="off">
        <div class="hint" id="cfgcount"></div>
        <div id="cfghits"></div>
        <div id="cfglist"></div>
      </aside>
      <section class="panel cfg-main" id="cfgmain"><div class="empty">Pick a config on the left.<br><span class="hint">Tip: search for a setting name like <b>spawn</b> or <b>maxEnergy</b> to find which file has it.</span></div></section>
    </div>`;

  const dirty = () => st.file && st.text !== st.saved;
  window.onbeforeunload = () => (dirty() ? true : undefined);
  const guard = async () => !dirty() || (await confirmBox("Discard your changes?", `You have unsaved changes in <b>${esc(st.file.name)}</b>.`, "Discard", true));

  // ---- list
  const renderList = () => {
    const q = $("#cfgq").value.trim().toLowerCase();
    const open = new Set(JSON.parse(localStorageGet("cfgOpen") || "[]"));
    const groups = st.data.groups.map((g) => {
      const nameHit = !q || g.name.toLowerCase().includes(q) || g.id.includes(q);
      const files = nameHit ? g.files : g.files.filter((f) => f.name.toLowerCase().includes(q));
      return { ...g, files };
    }).filter((g) => g.files.length);
    $("#cfglist").innerHTML = groups.map((g) => `<details class="cfg-group" data-g="${esc(g.id)}" ${q || open.has(g.id) || groups.length < 4 ? "open" : ""}>
      <summary><span>${esc(g.name)}</span><span class="muted">${g.files.length}</span></summary>
      ${g.files.map((f) => `<button class="cfg-file ${st.file?.path === f.path ? "active" : ""}" data-path="${esc(f.path)}" title="${esc(f.path)}">
        <span>${esc(f.name)}</span>
        <span class="cfg-tags">${f.where !== "config" ? `<span class="tag ${f.where === "world" ? "accent" : ""}">${f.where === "world" ? "world" : esc(f.where)}</span>` : ""}${f.side === "client" ? '<span class="tag" title="Only changes how the game looks or feels for players. Editing it on the server does nothing.">client</span>' : ""}</span>
      </button>`).join("")}</details>`).join("") || (q.length >= 2 ? "" : '<div class="empty">No config files found.</div>');
    $$(".cfg-group", el).forEach((d) => d.addEventListener("toggle", () => {
      const s = new Set(JSON.parse(localStorageGet("cfgOpen") || "[]"));
      d.open ? s.add(d.dataset.g) : s.delete(d.dataset.g);
      localStorageSet("cfgOpen", JSON.stringify([...s]));
    }));
    $$(".cfg-file", el).forEach((b) => (b.onclick = () => openFile(b.dataset.path)));
  };

  let searchTimer;
  const runSearch = () => {
    clearTimeout(searchTimer);
    const q = $("#cfgq").value.trim();
    if (q.length < 3) { $("#cfghits").innerHTML = ""; return; }
    searchTimer = setTimeout(async () => {
      const hits = (await api(`/api/configs/search?q=${encodeURIComponent(q)}`)).filter((h) => h.lines.length);
      if ($("#cfgq").value.trim() !== q) return;
      $("#cfghits").innerHTML = hits.length ? `<div class="cfg-hits-head">Settings containing “${esc(q)}”</div>` + hits.slice(0, 40).map((h) => `
        <button class="cfg-hit" data-path="${esc(h.path)}" data-line="${h.lines[0].line}"><b>${esc(h.path.replace(/^config\//, ""))}</b>
        ${h.lines.slice(0, 3).map((l) => `<code>${esc(l.text)}</code>`).join("")}${h.lines.length > 3 ? `<span class="hint">+${h.lines.length - 3} more</span>` : ""}</button>`).join("") : "";
      $$(".cfg-hit", el).forEach((b) => (b.onclick = () => openFile(b.dataset.path, { filter: q, line: +b.dataset.line })));
    }, 350);
  };
  $("#cfgq").oninput = () => { renderList(); runSearch(); };

  // ---- editor
  const openFile = async (path, opts = {}) => {
    if (st.file?.path !== path && !(await guard())) return;
    let f;
    try { f = await api(`/api/files/read?path=${encodeURIComponent(path)}`); } catch (e) { return toast(e.message, true); }
    const meta = st.data.groups.flatMap((g) => g.files).find((x) => x.path === path) || { path, name: path.split("/").pop(), side: "", where_label: "" };
    Object.assign(st, { file: meta, text: f.content, saved: f.content, mtime: f.mtime, fieldFilter: opts.filter || "", jump: opts.line || null });
    const ext = path.split(".").pop().toLowerCase();
    st.formable = ext === "toml" || ext === "json";
    st.view = st.formable && Pro.hooks.configForm ? "form" : "text";
    renderEditor();
    renderList();
    if (innerWidth < 860) $("#cfgmain").scrollIntoView({ behavior: "smooth" });
  };

  const renderEditor = () => {
    const f = st.file;
    const ext = f.path.split(".").pop().toLowerCase();
    $("#cfgmain").innerHTML = `<div class="cfg-sticky"><div class="cfg-head">
        <div style="min-width:0"><h4 style="margin:0">${esc(f.name)}</h4>
          <div class="hint">${esc(f.path)}${f.where_label ? " · " + esc(f.where_label) : ""}</div>
          ${f.side === "client" ? '<div class="cfg-note">This is a client config. It only affects how the game looks or feels on each player\'s own computer, so changing it here does nothing for players.</div>' : ""}
          ${f.where === "defaults" ? '<div class="cfg-note">Files here are only copied into <b>new</b> worlds. To change the current world, edit the copy marked “world”.</div>' : ""}
        </div>
        <div class="cfg-actions">
          ${st.formable ? `<div class="seg"><button data-v="form" class="${st.view === "form" ? "on" : ""}">Settings${Pro.hooks.configForm ? "" : ' <span class="tag accent">Pro</span>'}</button><button data-v="text" class="${st.view === "text" ? "on" : ""}">Text</button></div>` : ""}
          <button class="btn ghost small" id="cfghist">History</button>
          <button class="btn ghost small" id="cfgdisc" ${dirty() ? "" : "disabled"}>Discard</button>
          <button class="btn primary" id="cfgsave" ${dirty() ? "" : "disabled"}>Save</button>
        </div></div>
      <div id="cfgstatus" class="cfg-status"></div></div>
      <div id="cfgbody"></div>`;
    $$(".seg button", $("#cfgmain")).forEach((b) => (b.onclick = () => { st.view = b.dataset.v; renderEditor(); }));
    $("#cfgsave").onclick = save;
    $("#cfgdisc").onclick = () => { st.text = st.saved; renderEditor(); };
    $("#cfghist").onclick = history;
    if (st.view === "form") {
      if (Pro.hooks.configForm) Pro.hooks.configForm({ st, ext, updateStatus, renderEditor });
      else renderLocked();
    } else renderText();
    updateStatus();
  };

  const updateStatus = () => {
    const d = dirty();
    $("#cfgsave").disabled = !d;
    $("#cfgdisc").disabled = !d;
    const changed = d ? countChanges() : 0;
    $("#cfgstatus").innerHTML = d ? `<span class="dot"></span>${changed ? `${changed} unsaved change${changed > 1 ? "s" : ""}` : "Unsaved changes"} <span class="hint" style="display:inline;margin-left:8px">Ctrl+S to save</span>` : "";
  };
  const countChanges = () => {
    const a = st.text.split("\n"), b = st.saved.split("\n");
    let n = Math.abs(a.length - b.length);
    for (let i = 0; i < Math.min(a.length, b.length); i++) if (a[i] !== b[i]) n++;
    return n;
  };

  // ---- settings view (Pro add-on); free users get a pointer to it
  const renderLocked = () => {
    $("#cfgbody").innerHTML = `<div class="pro-lock"><h4>Settings view is part of Pro</h4>
      <p>Pro turns this file into switches, dropdowns and number boxes that know the allowed range, with descriptions and one-click reset to default.</p>
      <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap"><a class="btn primary" href="#/settings?tab=Pro">See Pro</a><button class="btn" id="totext">Edit as text</button></div></div>`;
    $("#totext").onclick = () => { st.view = "text"; renderEditor(); };
  };

  // ---- text view
  let vTimer;
  const renderText = () => {
    $("#cfgbody").innerHTML = `<div class="cfg-text"><pre class="gutter" id="gut" aria-hidden="true"></pre><textarea id="cfgta" class="mono" spellcheck="false" wrap="off"></textarea></div>`;
    const ta = $("#cfgta"), gut = $("#gut");
    ta.value = st.text;
    const nums = () => { gut.textContent = Array.from({ length: ta.value.split("\n").length }, (_, i) => i + 1).join("\n"); };
    nums();
    ta.onscroll = () => (gut.scrollTop = ta.scrollTop);
    ta.oninput = () => { st.text = ta.value; nums(); updateStatus(); clearTimeout(vTimer); vTimer = setTimeout(check, 500); };
    ta.onkeydown = (e) => { if (e.key === "Tab") { e.preventDefault(); ta.setRangeText("  ", ta.selectionStart, ta.selectionEnd, "end"); ta.oninput(); } };
    if (st.jump) { gotoLine(st.jump); st.jump = null; }
    check();
  };
  const gotoLine = (n) => {
    const ta = $("#cfgta");
    if (!ta) return;
    const lines = ta.value.split("\n");
    const start = lines.slice(0, n - 1).reduce((s, l) => s + l.length + 1, 0);
    ta.focus();
    ta.setSelectionRange(start, start + (lines[n - 1] || "").length);
    ta.scrollTop = Math.max(0, (n - 6) * parseFloat(getComputedStyle(ta).lineHeight));
  };
  const check = async () => {
    const box = $("#cfgvalid") || (() => { $("#cfgbody").insertAdjacentHTML("beforeend", '<div id="cfgvalid" class="cfg-valid"></div>'); return $("#cfgvalid"); })();
    const r = await api("/api/configs/validate", { body: { path: st.file.path, content: st.text } });
    if (!$("#cfgvalid")) return;
    const ext = st.file.path.split(".").pop().toUpperCase();
    box.className = "cfg-valid " + (r.ok ? "good" : "bad");
    box.innerHTML = r.ok ? (r.checked ? `No mistakes found in this ${ext} file.` : "This file type isn't checked - double-check your edits.")
      : `Mistake found: ${esc(r.error)} ${r.line ? `<button class="linkish" id="goerr">Go to line ${r.line}</button>` : ""}`;
    $("#goerr")?.addEventListener("click", () => gotoLine(r.line));
  };

  // ---- save / history
  const save = async () => {
    if (!dirty()) return;
    const body = { path: st.file.path, content: st.text, mtime: st.mtime };
    try {
      const r = await api("/api/configs/save", { method: "PUT", body });
      done(r);
    } catch (e) {
      if (/changed on disk/.test(e.message)) return toast(e.message, true);
      const go = await confirmBox("This file has a mistake in it", `${esc(e.message)}<br><br>A broken config can stop the server or the mod from loading. Save anyway?`, "Save anyway", true);
      if (!go) { if (st.view !== "text") { st.view = "text"; renderEditor(); } return; }
      done(await act(api("/api/configs/save", { method: "PUT", body: { ...body, force: true } }), false));
    }
  };
  const done = (r) => {
    st.saved = st.text; st.mtime = r.mtime;
    toast(r.restart_needed ? "Saved. Restart the server for it to take effect." : "Saved");
    renderEditor();
  };
  const history = async () => {
    const vs = await api(`/api/configs/versions?path=${encodeURIComponent(st.file.path)}`);
    const m = modal(`<h4>Earlier versions of ${esc(st.file.name)}</h4>
      <p class="muted">A copy is kept every time this file is saved from the panel (last 10).</p>
      ${vs.length ? `<table class="table"><tbody>${vs.map((v) => `<tr><td>Before the save on ${when(v.saved)}</td><td class="r muted">${bytes(v.size)}</td>
        <td class="r"><button class="btn small" data-load="${esc(v.id)}">Load into editor</button></td></tr>`).join("")}</tbody></table>`
        : '<div class="empty">No earlier versions yet. They appear after you save this file from the panel.</div>'}
      <div class="foot"><button class="btn ghost" data-x>Close</button></div>`, { wide: true });
    $("[data-x]", m.el).onclick = m.close;
    $$("[data-load]", m.el).forEach((b) => (b.onclick = async () => {
      const r = await api(`/api/configs/version?path=${encodeURIComponent(st.file.path)}&id=${encodeURIComponent(b.dataset.load)}`);
      st.text = r.content; m.close(); renderEditor();
      toast("Old version loaded - press Save to keep it");
    }));
  };

  el.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); } });
  Pages.leaveGuard = guard;

  st.data = await api("/api/configs");
  $("#cfgcount").textContent = `${st.data.count} files from ${st.data.groups.length} mods`;
  renderList();
  const pre = new URLSearchParams(location.hash.split("?")[1] || "").get("file");
  if (pre) openFile(pre);
};
