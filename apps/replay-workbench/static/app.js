"use strict";
// All imported text (logs, reasons, paths, records) is rendered with textContent only.
(function () {
  const $ = (id) => document.getElementById(id);
  let token = "";
  try {
    const m = /token=([A-Za-z0-9_-]+)/.exec(location.hash);
    if (m) { token = m[1]; sessionStorage.setItem("p10wb-token", token); }
    else token = sessionStorage.getItem("p10wb-token") || "";
  } catch (e) { /* storage may be unavailable */ }
  const state = { module: null, packageId: null, readyKey: null, jobId: null, after: 0, timer: null, ready: null };

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
  function inputsKey() { return [state.packageId, $("leanbin").value, $("signers").value].join("\u0000"); }
  function fmt(sec) { sec = Math.floor(sec); return Math.floor(sec / 60) + "m " + (sec % 60) + "s"; }

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

  function invalidateReadiness() {
    if (state.readyKey !== null && state.readyKey !== inputsKey()) {
      text($("ready-note"), "Inputs changed: readiness result is out of date.");
      state.readyKey = null;
    }
  }

  async function loadModule() {
    const j = await api("GET", "/api/modules");
    state.module = j.modules[0];
    text($("workspace"), "Workspace: " + state.module.workspace + " | Profile: " + state.module.profile_id + " | Profile SHA-256: " + state.module.profile_sha256);
    $("deadline").value = state.module.default_deadline_minutes;
    await loadSettings();
    if (state.module.synthetic) { const b = $("banner"); b.hidden = false; text(b, state.module.execution_kind); }
    if (state.module.packages.length === 1) { state.packageId = state.module.packages[0]; text($("import-status"), "Approved package already imported: " + state.packageId); }
  }

  async function doImport() {
    const f = $("pkgfile").files[0];
    if (!f) { text($("import-status"), "Choose the package archive first."); return; }
    text($("import-status"), "Uploading and hashing " + f.name + " ...");
    $("btn-import").disabled = true;
    try {
      const r = await api("POST", "/api/packages", f);
      if (r.app_status === "SUPPORTED") { state.packageId = r.package_id; text($("import-status"), "SUPPORTED. SHA-256 " + r.sha256 + (r.reused ? " (already imported; reused)" : " (" + r.members + " members, " + r.bytes + " bytes extracted)")); }
      else if (r.app_status === "UNSUPPORTED_PACKAGE") { state.packageId = null; text($("import-status"), "UNSUPPORTED_PACKAGE (application status, not a P10 outcome). SHA-256 " + r.sha256 + ". " + r.detail); }
      else { state.packageId = null; text($("import-status"), (r.app_status || "IMPORT_REJECTED") + ": " + (r.reason || "") + " " + (r.detail || "")); }
    } catch (e) { text($("import-status"), "Import failed: " + e.message); }
    $("btn-import").disabled = false; invalidateReadiness();
  }

  function body() {
    const o = { package_id: state.packageId, lean_bin: $("leanbin").value.trim() };
    const s = $("signers").value.trim(); if (s) o.allowed_signers = s;
    const d = parseInt($("deadline").value, 10); if (d) o.deadline_minutes = d;
    return o;
  }
  async function start(path) {
    if (!state.packageId) { text($("run-line"), "Import the approved package first."); return; }
    try {
      const r = await api("POST", path, body());
      state.jobId = r.job_id; state.after = 0; text($("log-out"), ""); text($("log-err"), ""); text($("jobid"), r.job_id); resetResults();
      $("btn-ready").disabled = $("btn-run").disabled = true; $("btn-stop").disabled = false;
      text($("run-line"), r.kind === "readiness" ? "Readiness started." : "Replay started.");
      poll();
    } catch (e) { text($("run-line"), "Not started: " + e.message); }
  }
  function resetResults() {
    for (const k of ["exec", "p10", "repro"]) { text($("v-" + k), "-"); $("v-" + k).className = "val"; text($("d-" + k), ""); }
    text($("wrapper-exit"), ""); text($("checks"), ""); text($("hashes"), ""); text($("raw"), "");
    for (const b of ["btn-export", "btn-raw-verdict", "btn-raw-info", "btn-raw-report"]) $(b).disabled = true;
  }

  async function poll() {
    clearTimeout(state.timer);
    if (!state.jobId) return;
    try {
      const st = await api("GET", "/api/runs/" + state.jobId);
      const ev = await api("GET", "/api/runs/" + state.jobId + "/events?after=" + state.after);
      state.after = ev.next;
      text($("log-out"), ev.stdout.text); text($("log-err"), ev.stderr.text);
      $("log-out").scrollTop = $("log-out").scrollHeight;
      const s = st.status;
      text($("phase"), s.phase || "-");
      if (s.started) text($("elapsed"), fmt((Date.now() - Date.parse(s.started)) / 1000));
      if (s.state === "DONE") { finish(st); return; }
    } catch (e) { text($("run-line"), "Status unavailable: " + e.message); }
    state.timer = setTimeout(poll, 1000);
  }

  function setVal(id, value, cls) { const v = $("v-" + id); text(v, value); v.className = "val " + (cls || ""); }
  function finish(st) {
    const r = st.result || {};
    $("btn-ready").disabled = $("btn-run").disabled = false; $("btn-stop").disabled = true;
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
    renderReady(r.readiness || []);
    const cl = $("checks"); cl.textContent = "";
    for (const c of rp.checks || []) cl.append(li(c.ok ? "pass" : "fail", c.id, c.detail));
    const arts = r.artifacts || {}; text($("hashes"), Object.keys(arts).map((k) => k + ": " + (arts[k].present ? arts[k].sha256 + " (" + arts[k].bytes + " bytes)" : "absent") + (arts[k].problem ? " [" + arts[k].problem + "]" : "")).join("\n"));
    $("btn-export").disabled = false; $("btn-raw-report").disabled = false;
    $("btn-raw-verdict").disabled = !(arts["verdict.json"] && arts["verdict.json"].present);
    $("btn-raw-info").disabled = !(arts["run-info.json"] && arts["run-info.json"].present);
    state.readyKey = inputsKey(); if (st.kind === "readiness") text($("ready-note"), "Readiness checked " + new Date().toLocaleTimeString() + (r.readiness_blocking && r.readiness_blocking.length ? "; blocking: " + r.readiness_blocking.join(", ") : "; nothing blocking"));
    loadJobs();
  }
  function renderReady(rows) {
    const ul = $("ready-rows"); ul.textContent = "";
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
      const live = j.runs.find((r) => r.state !== "DONE");
      if (live && !state.jobId) {   // re-attach to a job that is still running after a page reload
        state.jobId = live.job_id; state.after = 0; text($("jobid"), live.job_id);
        $("btn-ready").disabled = $("btn-run").disabled = true; $("btn-stop").disabled = false; text($("run-line"), "Re-attached to the active job."); poll();
      }
      for (const r of j.runs) { const e = li(r.execution === "COMPLETED" ? "pass" : (r.state === "DONE" ? "warn" : "info"), r.job_id, r.kind + " | " + r.execution); e.style.cursor = "pointer"; e.addEventListener("click", () => { state.jobId = r.job_id; state.after = 0; text($("jobid"), r.job_id); poll(); }); ul.append(e); }
    } catch (e) { /* ignore */ }
  }

  $("btn-import").addEventListener("click", doImport);
  $("btn-ready").addEventListener("click", () => start("/api/inspect"));
  $("btn-run").addEventListener("click", () => start("/api/runs"));
  $("btn-stop").addEventListener("click", async () => { try { await api("POST", "/api/runs/" + state.jobId + "/cancel", {}); text($("run-line"), "Stop requested; waiting for the process group to end."); } catch (e) { text($("run-line"), "Stop failed: " + e.message); } });
  $("btn-export").addEventListener("click", exportReport);
  $("btn-raw-verdict").addEventListener("click", () => showRaw("verdict.json"));
  $("btn-raw-info").addEventListener("click", () => showRaw("run-info.json"));
  $("btn-raw-report").addEventListener("click", () => showRaw("app-report.json"));
  $("btn-save-settings").addEventListener("click", saveSettings);
  for (const id of ["leanbin", "signers"]) $(id).addEventListener("input", () => { invalidateReadiness(); text($("settings-status"), "Unsaved changes."); });
  $("deadline").addEventListener("input", () => text($("settings-status"), "Unsaved changes."));
  loadModule().then(loadJobs).catch((e) => { text($("run-line"), "Cannot reach the application: " + e.message + " (open the URL printed by run.py, including its #token part)"); });
})();
