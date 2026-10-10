"use strict";
// All imported text (logs, reasons, paths, records, module descriptors) is rendered with textContent only.
// Navigation is client-side (URL fragment); it never starts, stops or restarts a job. Jobs run in the server's worker processes.
(function () {
  const $ = (id) => document.getElementById(id);
  const MODULE_SCREENS = { s3: "view-s3" };            // screens this UI knows how to show; the server decides which modules exist
  const MODULE_ID_RE = /^[a-z][a-z0-9-]{0,31}$/;
  let token = "";
  try {
    const m = /token=([A-Za-z0-9_-]+)/.exec(location.hash);
    if (m) { token = m[1]; sessionStorage.setItem("p10wb-token", token); }
    else token = sessionStorage.getItem("p10wb-token") || "";
  } catch (e) { /* storage may be unavailable */ }
  const state = { module: null, packageId: null, readyKey: null, jobId: null, past: false, after: 0, timer: null, active: null, activeTimer: null, view: null };

  function api(method, path, body, raw) {
    const opts = { method, headers: { "X-Workbench-Token": token } };
    if (body !== undefined && !(body instanceof Blob)) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    if (body instanceof Blob) { opts.headers["Content-Type"] = "application/octet-stream"; opts.body = body; }
    return fetch(path, opts).then(async (r) => {
      if (raw && r.ok) return r;
      let j = null;
      try { j = await r.json(); } catch (e) { /* not JSON */ }
      if (!r.ok && !(j && j.app_status)) throw new Error((j && (j.error + (j.detail ? ": " + j.detail : ""))) || ("HTTP " + r.status));
      return j;
    });
  }
  function text(node, s) { node.textContent = s == null ? "" : String(s); return node; }
  function li(status, label, detail) {
    const e = document.createElement("li");
    const a = document.createElement("span"); a.className = "st " + status; a.textContent = status.replace("_", " ");
    const b = document.createElement("span"); b.className = "lb"; b.textContent = label;
    const c = document.createElement("span"); c.className = "dt"; c.textContent = detail || "";
    e.append(a, b, c); return e;
  }
  function fmt(sec) { sec = Math.floor(sec); return Math.floor(sec / 60) + "m " + (sec % 60) + "s"; }
  function inputsKey() { return [state.packageId, $("leanbin").value, $("signers").value].join("\u0000"); }

  // ---------------------------------------------------------------------------------------------------------- navigation
  function parseHash() {
    const p = new URLSearchParams(location.hash.replace(/^#/, ""));
    return { view: p.get("view") || "home", id: p.get("id") || "", job: p.get("job") || "" };
  }
  function hashFor(view, id, job) {
    const p = new URLSearchParams();
    if (token) p.set("token", token);
    p.set("view", view);
    if (id) p.set("id", id);
    if (job) p.set("job", job);
    return "#" + p.toString();
  }
  function navigate(view, id, job) { history.pushState(null, "", hashFor(view, id, job)); render(); }
  function show(sectionId) {
    for (const s of document.querySelectorAll("main > section")) s.hidden = s.id !== sectionId;
    const cur = sectionId === "view-home" ? "nav-home" : (sectionId === "view-settings" ? "nav-settings" : "");
    for (const a of document.querySelectorAll("nav a")) { if (a.id === cur) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); }
  }
  async function render() {
    const h = parseHash();
    stopDetailPolling();
    if (h.view === "home") { state.view = "home"; show("view-home"); await renderHome(); return; }
    if (h.view === "settings") { state.view = "settings"; show("view-settings"); return; }
    if (h.view === "module") {
      if (!MODULE_ID_RE.test(h.id)) return unknown("This module identifier is not valid.");
      let d = null;
      try { d = (await api("GET", "/api/modules/" + encodeURIComponent(h.id))).module; }
      catch (e) { return unknown("There is no module with the identifier “" + h.id.slice(0, 40) + "” in this application."); }
      if (!MODULE_SCREENS[h.id]) return unknown("This module has no screen in this version of the interface.");
      state.view = "module"; state.module = d; show(MODULE_SCREENS[h.id]); openS3(d, h.job); return;
    }
    unknown("This page does not exist.");
  }
  function unknown(msg) { state.view = "unknown"; text($("unknown-text"), msg); show("view-unknown"); }

  async function renderHome() {
    const box = $("module-cards"); box.textContent = "";
    let mods = [];
    try { mods = (await api("GET", "/api/modules")).modules; } catch (e) { text(box, "Cannot reach the application: " + e.message); return; }
    for (const d of mods) {
      if (!d.available || !MODULE_SCREENS[d.id]) continue;
      const card = document.createElement("article"); card.className = "card";
      const h = document.createElement("h2"); h.textContent = d.title;
      const p = document.createElement("p"); p.textContent = d.summary;
      const a = document.createElement("a"); a.className = "button primary"; a.href = "#"; a.textContent = d.action; a.dataset.module = d.id;
      a.addEventListener("click", (ev) => { ev.preventDefault(); navigate("module", d.id); });
      card.append(h, p, a); box.append(card);
    }
  }

  // ---------------------------------------------------------------------------------------------------------- active job indicator
  async function refreshActive() {
    try {
      const j = await api("GET", "/api/runs");
      const live = j.runs.find((r) => r.state !== "DONE") || null;
      state.active = live;
      const bar = $("active-bar");
      if (live) {
        bar.hidden = false;
        text($("active-text"), "Job " + live.job_id + " (" + (live.kind === "readiness" ? "readiness check" : "replay") + ") is running.");
        $("active-link").dataset.job = live.job_id;
      } else { bar.hidden = true; }
      updateButtons();
    } catch (e) { /* the next tick tries again */ }
    clearTimeout(state.activeTimer);
    state.activeTimer = setTimeout(refreshActive, 2000);
  }
  function updateButtons() {
    const busy = !!state.active;
    $("btn-ready").disabled = busy; $("btn-run").disabled = busy; $("btn-stop").disabled = !busy;
  }

  // ---------------------------------------------------------------------------------------------------------- host settings
  function currentSettings() {
    const o = { lean_bin: $("leanbin").value.trim(), allowed_signers: $("signers").value.trim() };
    const d = Number($("deadline").value);
    o.deadline_minutes = $("deadline").value.trim() === "" || !isFinite(d) ? NaN : d;
    return o;
  }
  async function loadSettings() {
    const w = $("settings-warning");
    try {
      const r = await api("GET", "/api/settings");
      $("leanbin").value = r.settings.lean_bin; $("signers").value = r.settings.allowed_signers; $("deadline").value = r.settings.deadline_minutes;
      if (r.warning) { w.hidden = false; text(w, r.warning); } else { w.hidden = true; text(w, ""); }
      const any = r.settings.lean_bin || r.settings.allowed_signers;
      text($("settings-status"), r.warning ? "Saved host settings could not be used; defaults are shown." : (any ? "Saved host settings restored (fields only; readiness has not been checked)." : "No saved host settings yet."));
    } catch (e) { text($("settings-status"), "Host settings unavailable: " + e.message); }
  }
  async function saveSettings() {
    const o = currentSettings();
    if (Number.isNaN(o.deadline_minutes)) { text($("settings-status"), "Not saved: the deadline must be a number."); return; }
    try { await api("POST", "/api/settings", o); $("settings-warning").hidden = true; text($("settings-status"), "Host settings saved."); }
    catch (e) { text($("settings-status"), "Not saved: " + e.message); }
  }
  function refreshSummary() {
    const lean = $("leanbin").value.trim(), sig = $("signers").value.trim();
    text($("sum-lean"), lean || "not set"); text($("sum-signers"), sig || "not set (tag signatures will show “Signature not checked”)");
    text($("sum-deadline"), ($("deadline").value || "?") + " minutes");
    text($("sum-note"), lean ? "" : "The Lean bin directory is not set. Open Host settings, enter it and save it before checking readiness or running.");
  }
  function invalidateReadiness() {
    if (state.readyKey !== null && state.readyKey !== inputsKey()) {
      text($("ready-note"), "Inputs changed: the readiness result is out of date.");
      state.readyKey = null;
    }
  }

  // ---------------------------------------------------------------------------------------------------------- S3 screen
  function openS3(d, jobFromLink) {
    refreshSummary();
    text($("workspace"), "Workspace: " + d.workspace + " | Profile: " + d.profile_id + " | Profile SHA-256: " + d.profile_sha256);
    if (d.packages.length === 1 && !state.packageId) { state.packageId = d.packages[0]; text($("import-status"), "Approved package already imported: " + state.packageId); }
    loadJobs();
    updateButtons();
    if (jobFromLink) { viewJob(jobFromLink); return; }
    if (state.active) { viewJob(state.active.job_id); return; }                      // looking at the running job; nothing is started
    if (state.jobId) { resumeJob(); }
  }
  function stopDetailPolling() { clearTimeout(state.timer); state.timer = null; }       // only the browser stops polling; the job is untouched

  function showPastBanner(id, created) {
    const b = $("past-banner");
    if (!state.past) { b.hidden = true; text(b, ""); return; }
    b.hidden = false;
    text(b, "Viewing an earlier job (" + id + (created ? ", started " + created : "") + "). It describes only that job: not this host today, not a new run and not the module.");
  }
  // A job shown on this screen is CURRENT when it was started in this page session or was still running when we first looked at it
  // (we are watching a live job). A job that is already finished when first fetched, and was not started in this page session, is HISTORICAL,
  // whichever way it was opened (history list, indicator link, URL, reload). The classification comes from the fetched status.
  function classify(st) {
    const done = !!(st.status && st.status.state === "DONE");
    if (state.fresh === st.job_id) state.past = false;
    else if (!done) { state.fresh = st.job_id; state.past = false; }
    else state.past = true;
    showPastBanner(st.job_id, st.created);
  }
  function setJobInUrl(id) {         // keeps the address bar in step with the viewed job, so a reload shows the same job (replace: no history entry)
    if (state.view === "module") history.replaceState(null, "", hashFor("module", "s3", id));
  }
  function viewJob(id) {
    state.jobId = id; state.after = 0; state.past = false; setJobInUrl(id);
    text($("jobid"), id); text($("log-out"), ""); text($("log-err"), ""); resetResults();
    showPastBanner(id, "");
    poll();
  }
  function resumeJob() { poll(); }

  async function doImport() {
    const f = $("pkgfile").files[0];
    if (!f) { text($("import-status"), "Choose the package archive first."); return; }
    text($("import-status"), "Uploading and hashing " + f.name + " ...");
    $("btn-import").disabled = true;
    try {
      const r = await api("POST", "/api/packages?module=s3", f);
      if (r.app_status === "SUPPORTED") { state.packageId = r.package_id; text($("import-status"), "SUPPORTED. SHA-256 " + r.sha256 + (r.reused ? " (already imported; reused)" : " (" + r.members + " members, " + r.bytes + " bytes extracted)")); }
      else if (r.app_status === "UNSUPPORTED_PACKAGE") { state.packageId = null; text($("import-status"), "UNSUPPORTED_PACKAGE (application status, not a P10 outcome). SHA-256 " + r.sha256 + ". " + r.detail); }
      else { state.packageId = null; text($("import-status"), (r.app_status || "IMPORT_REJECTED") + ": " + (r.reason || "") + " " + (r.detail || "")); }
    } catch (e) { text($("import-status"), "Import failed: " + e.message); }
    $("btn-import").disabled = false; invalidateReadiness();
  }

  function body() {
    const o = { module: "s3", package_id: state.packageId, lean_bin: $("leanbin").value.trim() };
    const s = $("signers").value.trim(); if (s) o.allowed_signers = s;
    const d = parseInt($("deadline").value, 10); if (d) o.deadline_minutes = d;
    return o;
  }
  async function start(path) {
    if (!state.packageId) { text($("run-line"), "Import the approved package first."); return; }
    try {
      const r = await api("POST", path, body());
      state.past = false; showPastBanner();
      state.jobId = r.job_id; state.after = 0; state.fresh = r.job_id; setJobInUrl(r.job_id);
      text($("log-out"), ""); text($("log-err"), ""); text($("jobid"), r.job_id); resetResults();
      text($("run-line"), r.kind === "readiness" ? "Readiness started." : "Replay started.");
      refreshActive(); poll();
    } catch (e) { text($("run-line"), "Not started: " + e.message); }
  }
  function resetResults() {
    for (const k of ["exec", "p10", "repro"]) { text($("v-" + k), "-"); $("v-" + k).className = "val"; text($("d-" + k), ""); }
    text($("wrapper-exit"), ""); text($("checks"), ""); text($("hashes"), ""); text($("raw"), ""); text($("past-ready-rows"), "");
    for (const b of ["btn-export", "btn-raw-verdict", "btn-raw-info", "btn-raw-report"]) $(b).disabled = true;
  }

  async function poll() {
    stopDetailPolling();
    if (!state.jobId || state.view !== "module") return;
    const jid = state.jobId;
    try {
      const st = await api("GET", "/api/runs/" + jid);
      const ev = await api("GET", "/api/runs/" + jid + "/events?after=" + state.after);
      if (jid !== state.jobId || state.view !== "module") return;
      state.after = ev.next;
      text($("log-out"), ev.stdout.text); text($("log-err"), ev.stderr.text);
      $("log-out").scrollTop = $("log-out").scrollHeight;
      const s = st.status;
      text($("phase"), s.phase || "-");
      if (s.started) text($("elapsed"), fmt((Date.now() - Date.parse(s.started)) / 1000));
      classify(st);
      if (s.state === "DONE") { finish(st); return; }
    } catch (e) { text($("run-line"), "Status unavailable: " + e.message); }
    state.timer = setTimeout(poll, 1000);
  }

  function setVal(id, value, cls) { const v = $("v-" + id); text(v, value); v.className = "val " + (cls || ""); }
  function finish(st) {
    const r = st.result || {};
    const fresh = !state.past && state.fresh === st.job_id;          // only a current job may count as this session's readiness
    const ex = r.execution || {};
    setVal("exec", ex.status || "?", ex.status === "COMPLETED" ? "good" : (ex.status === "RUNNING" ? "" : "bad"));
    text($("d-exec"), (ex.reason ? "Reason: " + ex.reason + ". " : "") + (st.execution_kind || "") + (r.elapsed_seconds != null ? " | " + fmt(r.elapsed_seconds) : ""));
    const p = r.p10 || {};
    if (st.kind === "readiness") { setVal("p10", "Not applicable", "neutral"); text($("d-p10"), "Readiness has no P10 outcome."); }
    else if (p.state === "AVAILABLE") {
      setVal("p10", p.outcome, p.outcome === "BINDING_MATCH" ? "good" : "bad");
      text($("d-p10"), "stage: " + p.stage + " | reason: " + JSON.stringify(p.reason) + (p.record_problems && p.record_problems["run-info.json"] ? " | run-info.json: " + p.record_problems["run-info.json"] : ""));
    } else { setVal("p10", "NOT EVALUATED", "neutral"); text($("d-p10"), p.record_problems ? "verdict.json: " + (p.record_problems["verdict.json"] || "n/a") : ""); }
    const rp = r.reproduction || {};
    if (rp.badge) setVal("repro", "Accepted replay reproduced", "good");
    else if (rp.status === "MATCH") setVal("repro", "MATCH (synthetic test run, no badge)", "neutral");
    else setVal("repro", rp.status || "NOT_EVALUATED", rp.status === "DIFFERENT" ? "bad" : "neutral");
    text($("d-repro"), (rp.reasons || []).join(" "));
    if (r.wrapper_exit !== undefined && st.kind !== "readiness") text($("wrapper-exit"), "Wrapper exit status: " + (r.wrapper_exit === null ? "none (signal " + (r.supervision && r.supervision.signal) + ")" : r.wrapper_exit) + (r.wrapper_exit_meaning ? " (" + r.wrapper_exit_meaning + ")" : "") + ". This is not a P10 outcome.");
    if (fresh) renderRows($("ready-rows"), r.readiness || []);
    else renderRows($("past-ready-rows"), r.readiness || []);          // the current Readiness section is left exactly as it is
    const cl = $("checks"); cl.textContent = "";
    for (const c of rp.checks || []) cl.append(li(c.ok ? "pass" : "fail", c.id, c.detail));
    const arts = r.artifacts || {}; text($("hashes"), Object.keys(arts).map((k) => k + ": " + (arts[k].present ? arts[k].sha256 + " (" + arts[k].bytes + " bytes)" : "absent") + (arts[k].problem ? " [" + arts[k].problem + "]" : "")).join("\n"));
    $("btn-export").disabled = false; $("btn-raw-report").disabled = false;
    $("btn-raw-verdict").disabled = !(arts["verdict.json"] && arts["verdict.json"].present);
    $("btn-raw-info").disabled = !(arts["run-info.json"] && arts["run-info.json"].present);
    if (fresh) {
      state.readyKey = inputsKey();
      if (st.kind === "readiness") text($("ready-note"), "Readiness checked " + new Date().toLocaleTimeString() + (r.readiness_blocking && r.readiness_blocking.length ? "; blocking: " + r.readiness_blocking.join(", ") : "; nothing blocking"));
    }
    refreshActive(); loadJobs();
  }
  function renderRows(ul, rows) {
    ul.textContent = "";
    for (const r of rows) {
      ul.append(li(r.status, r.label, r.detail));
      if (r.rows) for (const s of r.rows) ul.append(li(s.ok ? "pass" : (s.required ? "fail" : "info"), "  " + s.id, s.detail));
    }
  }
  async function showRaw(name) {
    if (!state.jobId) return;
    try { const r = await api("GET", "/api/runs/" + state.jobId + "/artifacts/" + name, undefined, true); text($("raw"), await r.text()); }
    catch (e) { text($("raw"), "Unavailable: " + e.message); }
  }
  async function exportReport() {
    try {
      const r = await api("GET", "/api/runs/" + state.jobId + "/report", undefined, true);
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a"); a.href = url; a.download = "replay-report-" + state.jobId + ".tar.gz"; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) { text($("run-line"), "Export failed: " + e.message); }
  }
  async function loadJobs() {
    try {
      const j = await api("GET", "/api/runs"); const ul = $("jobs"); ul.textContent = "";
      for (const r of j.runs) {
        if (r.module && r.module !== "s3") continue;
        const e = li(r.state === "DONE" ? (r.execution === "COMPLETED" ? "pass" : "warn") : "info", r.job_id, r.kind + " | " + (r.state === "DONE" ? "finished: " : "") + r.execution);
        e.style.cursor = "pointer"; e.tabIndex = 0;
        const open = () => viewJob(r.job_id);
        e.addEventListener("click", open); e.addEventListener("keydown", (ev) => { if (ev.key === "Enter") open(); });
        ul.append(e);
      }
    } catch (e) { /* ignore */ }
  }

  // ---------------------------------------------------------------------------------------------------------- wiring
  for (const a of document.querySelectorAll("[data-nav]")) a.addEventListener("click", (ev) => { ev.preventDefault(); navigate(a.dataset.nav); });
  $("active-link").addEventListener("click", (ev) => { ev.preventDefault(); navigate("module", "s3", $("active-link").dataset.job); });
  window.addEventListener("popstate", render);
  $("btn-import").addEventListener("click", doImport);
  $("btn-ready").addEventListener("click", () => start("/api/inspect"));
  $("btn-run").addEventListener("click", () => start("/api/runs"));
  $("btn-stop").addEventListener("click", async () => {      // explicit user action on the active job
    const target = state.active && state.active.job_id;
    if (!target) return;
    try { await api("POST", "/api/runs/" + target + "/cancel", {}); text($("run-line"), "Stop requested for " + target + "; waiting for the process group to end."); }
    catch (e) { text($("run-line"), "Stop failed: " + e.message); }
  });
  $("btn-export").addEventListener("click", exportReport);
  $("btn-raw-verdict").addEventListener("click", () => showRaw("verdict.json"));
  $("btn-raw-info").addEventListener("click", () => showRaw("run-info.json"));
  $("btn-raw-report").addEventListener("click", () => showRaw("app-report.json"));
  $("btn-save-settings").addEventListener("click", saveSettings);
  for (const id of ["leanbin", "signers"]) $(id).addEventListener("input", () => { invalidateReadiness(); refreshSummary(); text($("settings-status"), "Unsaved changes."); });
  $("deadline").addEventListener("input", () => { refreshSummary(); text($("settings-status"), "Unsaved changes."); });

  (async function init() {
    try {
      const mods = (await api("GET", "/api/modules")).modules;
      if (mods[0]) {
        $("deadline").value = mods[0].default_deadline_minutes;
        if (mods[0].synthetic) { const b = $("banner"); b.hidden = false; text(b, mods[0].execution_kind); }
      }
      await loadSettings();
    } catch (e) { /* render() reports unreachable application on Home */ }
    await refreshActive();
    await render();
  })();
})();
