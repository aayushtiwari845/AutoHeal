"use strict";

const $ = (id) => document.getElementById(id);
const state = { presets: [], presetId: "grades", customTask: "", service: null, run: null, active: false, timer: null, attemptHash: "", eventHash: "", expanded: new Set(), view: "table", lastAnnouncement: "" };
const terminal = new Set(["succeeded", "exhausted", "cancelled", "provider_error", "failed"]);
const labels = { queued: "Queued", running: "Running", succeeded: "Validated", exhausted: "Limit reached", cancelled: "Stopped", provider_error: "Model error", failed: "Failed" };
const phaseLabels = { generate: "Generating Python with the local model…", execute: "Executing Python in a constrained subprocess…", evaluate: "Checking the structured result against task requirements…", reflect: "Preparing structured feedback for the next repair…", done: "Run complete." };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
function stringify(value) {
  if (value === undefined || value === null) return "—";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
function announce(message) {
  if (message !== state.lastAnnouncement) { $("announcer").textContent = message; state.lastAnnouncement = message; }
}
function runLabel(run) {
  return run.status === "succeeded" && (run.validation_kind === "structural" || !run.preset_id || run.preset_id === "custom") ? "Structure passed" : labels[run.status] || run.status;
}
async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, headers: { "Content-Type": "application/json", ...options.headers } });
    const body = await response.json();
    if (!response.ok) throw new Error(typeof body.error === "string" ? body.error : body.error?.message || body.message || `Request failed (${response.status}).`);
    return body;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The local server took too long to respond. Refresh the connection and try again.");
    if (error instanceof TypeError) throw new Error("Cannot reach the local server. Make sure AutoHeal Studio is running.");
    throw error;
  } finally { clearTimeout(timeout); }
}
function mode() { return document.querySelector('input[name="mode"]:checked').value; }
function currentPreset() { return state.presets.find((preset) => preset.id === state.presetId); }
function setFormError(message) { $("formError").textContent = message || ""; $("formError").hidden = !message; }
function setMode() {
  const replay = mode() === "replay";
  $("modeHint").textContent = replay ? "Fixed programs, real execution. No AI model is called." : "Ollama generates and repairs the code locally.";
  if (replay) $("seedFailure").checked = true;
  $("modelSelect").disabled = replay || state.active;
  updateControls();
}
function updateControls() {
  const custom = describeTask() === "custom";
  const ready = mode() === "replay" ? !custom : state.service?.ollama_available && $("modelSelect").value;
  $("runButton").disabled = state.active || !ready || !$("taskInput").value.trim();
  $("runButton").replaceChildren(el("span", "", state.active ? "◌" : "▶"), document.createTextNode(state.active ? "Run in progress" : "Start run"));
  $("cancelButton").hidden = !state.active;
  $("cancelButton").disabled = !state.active;
  $("exportButton").disabled = !state.run;
  $("taskInput").disabled = state.active;
  $("attemptLimit").disabled = state.active;
  $("timeoutSelect").disabled = state.active;
  $("seedFailure").disabled = state.active || custom || mode() === "replay";
  $("seedHint").textContent = custom ? "Controlled faults are available for presets only." : mode() === "replay" ? "Replay always begins with its documented fixed fault." : "Inject a documented fault to show the repair loop.";
  if (custom) $("seedFailure").checked = false;
  if (custom && mode() === "replay") $("modeHint").textContent = "Replay supports the three presets. Choose one to run it.";
  document.querySelectorAll('input[name="mode"], input[name="preset"]').forEach((input) => { input.disabled = state.active; });
  document.querySelector('input[name="mode"][value="replay"]').disabled = state.active || custom;
  $("modelSelect").disabled = mode() === "replay" || state.active;
}
async function refreshStatus() {
  $("refreshStatus").disabled = true;
  $("serviceMessage").textContent = "Checking Ollama…";
  try {
    const service = await request("/api/status");
    state.service = service;
    const models = service.models || [];
    const previous = $("modelSelect").value;
    $("modelSelect").replaceChildren();
    models.forEach((item) => {
      const name = typeof item === "string" ? item : item.name || item.model;
      if (name) { const option = el("option", "", name); option.value = name; $("modelSelect").append(option); }
    });
    if (!models.length) { const option = el("option", "", "No local model available"); option.value = ""; $("modelSelect").append(option); }
    if (models.some((m) => (typeof m === "string" ? m : m.name) === previous)) $("modelSelect").value = previous;
    else if (models.some((m) => (typeof m === "string" ? m : m.name) === service.default_model)) $("modelSelect").value = service.default_model;
    $("serviceDot").className = `service-dot ${service.ollama_available && models.length ? "connected" : "error"}`;
    $("serviceMessage").textContent = service.ollama_available ? (models.length ? `${models.length} local model${models.length === 1 ? "" : "s"} available` : "Ollama connected. No model installed.") : "Ollama is unavailable. Replay is available.";
  } catch (error) {
    state.service = null;
    $("serviceDot").className = "service-dot error";
    $("serviceMessage").textContent = error.message;
    $("modelSelect").replaceChildren(el("option", "", "Connection unavailable"));
    $("modelSelect").firstChild.value = "";
  } finally { $("refreshStatus").disabled = false; updateControls(); }
}
async function loadPresets() {
  try {
    const data = await request("/api/presets");
    state.presets = Array.isArray(data) ? data : data.presets || [];
    if (state.presetId !== "custom" && !state.presets.some((preset) => preset.id === state.presetId)) state.presetId = state.presets[0]?.id || "custom";
    $("presets").replaceChildren();
    const titles = { grades: "Grade analytics", sales: "Sales summary", text: "Text statistics" };
    const descriptions = { grades: "Weighted scores and passing students", sales: "Clean amounts and aggregate by region", text: "Normalized token frequencies" };
    const sorted = [...state.presets].sort((a, b) => (a.id === "grades" ? -1 : b.id === "grades" ? 1 : 0));
    sorted.push({ id: "custom", title: "Custom Python task", description: "Include inputs in your instructions" });
    sorted.forEach((preset) => {
      const label = el("label", "preset-option");
      const input = el("input"); input.type = "radio"; input.name = "preset"; input.value = preset.id; input.checked = preset.id === state.presetId;
      const copy = el("span"); copy.append(el("strong", "", titles[preset.id] || preset.title), el("small", "", descriptions[preset.id] || preset.description));
      label.append(input, copy, el("span", "preset-arrow", "↗"));
      input.addEventListener("change", () => selectPreset(preset.id));
      $("presets").append(label);
    });
    selectPreset(state.presetId);
  } catch (error) {
    $("presets").replaceChildren(el("div", "loading-copy", `${error.message} Refresh connection to retry the preset list.`));
    const label = el("label", "preset-option"); const input = el("input"); input.type = "radio"; input.name = "preset"; input.value = "custom"; input.checked = true;
    const copy = el("span"); copy.append(el("strong", "", "Custom Python task"), el("small", "", "Include inputs in your instructions")); label.append(input, copy); input.addEventListener("change", () => selectPreset("custom")); $("presets").append(label);
    selectPreset("custom");
  }
}
function selectPreset(id) {
  state.presetId = id;
  const preset = currentPreset();
  const custom = id === "custom";
  $("taskInput").readOnly = !custom;
  $("taskLabel").textContent = custom ? "Task instructions" : "Task contract";
  $("editNotice").textContent = custom ? "Editable" : "Preset";
  $("taskData").hidden = custom;
  if (preset) { $("taskInput").value = preset.task || preset.prompt; $("taskHint").textContent = "Preset results are checked against an independent expected result."; $("inputData").textContent = stringify(preset.data); $("expectedFields").textContent = `Required fields: ${(preset.expected_keys || Object.keys(preset.expected || {})).join(", ")}`; $("seedFailure").checked = true; }
  if (custom) { $("taskInput").value = state.customTask; $("taskHint").textContent = "DATA is empty. Include input values above. Output checks are structural only, with no independent answer oracle."; $("seedFailure").checked = false; document.querySelector('input[name="mode"][value="live"]').checked = true; }
  setMode();
}
function describeTask() {
  if (state.presetId === "custom") return "custom";
  const preset = currentPreset();
  const original = (preset?.task || preset?.prompt || "").trim();
  return $("taskInput").value.trim() === original ? state.presetId : "custom";
}
async function startRun(event) {
  event.preventDefault();
  if (state.active) return;
  setFormError("");
  const body = { preset_id: describeTask(), task: $("taskInput").value.trim(), mode: mode(), model: $("modelSelect").value, max_attempts: Number($("attemptLimit").value), timeout: Number($("timeoutSelect").value), seed_failure: $("seedFailure").checked };
  if (!body.task) { setFormError("Enter a task before starting the run."); return; }
  state.active = true; updateControls();
  try {
    const response = await request("/api/runs", { method: "POST", body: JSON.stringify(body) });
    state.run = { id: response.run_id || response.id, status: "queued", phase: "generate", attempts: [], task: body.task, mode: body.mode, model: body.model, preset_id: body.preset_id };
    $("attempts").replaceChildren();
    state.attemptHash = ""; state.eventHash = ""; state.expanded.clear(); state.view = "table";
    renderRun(state.run);
    $("activity").scrollIntoView({block:"start", behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"});
    await pollRun();
  } catch (error) { state.active = false; setFormError(error.message); updateControls(); }
}
async function pollRun() {
  clearTimeout(state.timer);
  if (!state.run) return;
  try {
    const run = await request(`/api/runs/${encodeURIComponent(state.run.id)}`);
    state.run = run; state.active = !terminal.has(run.status);
    renderRun(run); updateControls();
    if (state.active) state.timer = setTimeout(pollRun, 800);
  } catch (error) {
    $("runError").textContent = `${error.message} The connection will be retried; the server may still be executing the run.`;
    $("runError").hidden = false;
    if (state.active) state.timer = setTimeout(pollRun, 3000);
  }
}
function renderRun(run) {
  const complete = terminal.has(run.status);
  $("emptyState").hidden = true;
  $("runStatus").className = `status-badge ${run.status}`;
  $("runStatus").textContent = runLabel(run);
  const visitedPhases = new Set((run.events || []).map((event) => event.phase));
  document.querySelectorAll(".phase-flow>div").forEach((node) => {
    const current = node.dataset.phase === run.phase;
    node.className = current ? "current" : visitedPhases.has(node.dataset.phase) ? "complete" : "";
    if (current) node.setAttribute("aria-current", "step"); else node.removeAttribute("aria-current");
  });
  $("runContext").hidden = false;
  const custom = !run.preset_id || run.preset_id === "custom";
  const preset = state.presets.find((p) => p.id === run.preset_id);
  const contextTitle = custom ? "Custom task · structural validation" : preset?.title || "Python execution task";
  $("runContext").replaceChildren(el("strong", "", contextTitle), el("p", run.mode === "replay" ? "replay-label" : "", run.mode === "replay" ? "SCRIPTED REPLAY · Fixed programs; no AI model calls" : `LIVE LOCAL MODEL · ${run.model || "Ollama"}`));
  $("progressMessage").hidden = complete;
  $("progressMessage").textContent = run.mode === "replay" && run.phase === "generate" ? "Loading the next fixed replay program…" : phaseLabels[run.phase] || "Waiting for execution…";
  const hash = JSON.stringify(run.attempts || []);
  if (hash !== state.attemptHash) { renderAttempts(run.attempts || []); state.attemptHash = hash; }
  const events = run.events || [];
  const eventHash = JSON.stringify(events);
  $("eventTrace").hidden = !events.length;
  if (state.eventHash !== eventHash) { $("eventLog").replaceChildren(); events.forEach((event) => { const item = el("li"); let time = ""; if (event.time) time = new Date(event.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }); const heading = el("div", "event-heading"); heading.append(el("span", "", `${event.phase.toUpperCase()}${event.attempt ? ` / ${event.attempt}` : ""}`), el("time", "", time)); item.append(heading, el("p", "", event.message)); $("eventLog").append(item); }); state.eventHash = eventHash; }
  const error = run.error || run.provider_error;
  $("runError").hidden = !error;
  $("runError").textContent = error ? typeof error === "object" ? error.message || stringify(error) : error : "";
  if (complete) {
    if (run.status === "exhausted" && !error) { $("runError").hidden = false; $("runError").textContent = "The attempt limit was reached before the result passed every check. Inspect the captured failures below."; }
    if (run.status === "provider_error" && !error) { $("runError").hidden = false; $("runError").textContent = "The model provider could not complete the request. Inspect the trace, then refresh the connection and retry."; }
    if (run.status === "cancelled" && !error) { $("runError").hidden = false; $("runError").textContent = "This run was stopped. Its completed attempts remain available for inspection."; }
    renderMetrics(run);
  } else $("runMetrics").hidden = true;
  renderResult(run);
  $("traceNote").textContent = complete ? `Run ${run.id?.slice(0, 8) || ""} · ${runLabel(run)} · stored locally` : "Capturing the execution trace on this laptop.";
  const count = run.attempts?.length || 0;
  announce(complete ? `Run ${runLabel(run)}. ${count} attempts captured.` : `${runLabel(run)}. ${run.phase}. Attempt ${count || 1}.`);
}
function disclosure(title, number, kind) {
  const details = el("details"); const key = `${number}-${kind}`;
  details.dataset.disclosure = key;
  details.open = state.expanded.has(key);
  details.append(el("summary", "", title));
  details.addEventListener("toggle", () => { if (!details.isConnected) return; if (details.open) state.expanded.add(key); else state.expanded.delete(key); });
  return details;
}
function renderAttempts(attempts) {
  const focusedDisclosure = document.activeElement?.tagName === "SUMMARY" && $("attempts").contains(document.activeElement) ? document.activeElement.parentElement.dataset.disclosure : null;
  $("attempts").querySelectorAll("details[data-disclosure]").forEach((details) => { if (details.open) state.expanded.add(details.dataset.disclosure); else state.expanded.delete(details.dataset.disclosure); });
  $("attempts").replaceChildren();
  attempts.forEach((attempt, index) => {
    const number = attempt.number || index + 1;
    const card = el("article", `attempt-card ${attempt.status || "running"}`); card.setAttribute("role", "listitem");
    const top = el("div", "attempt-top");
    top.append(el("span", "attempt-symbol", attempt.status === "success" ? "✓" : attempt.status === "failed" ? "!" : attempt.status === "cancelled" ? "■" : "·"), el("h3", "", `Attempt ${String(number).padStart(2, "0")}`));
    if (attempt.seeded) top.append(el("span", "seed-tag", "CONTROLLED FAULT"));
    const stopped = attempt.status === "cancelled" || (state.run?.status === "cancelled" && attempt.status === "running");
    top.append(el("span", "attempt-state", attempt.status === "success" ? "Passed" : attempt.status === "failed" ? "Needs repair" : stopped ? "Stopped" : "In progress")); card.append(top);
    const stats = el("div", "attempt-stats");
    [["EXIT CODE", attempt.returncode ?? "—"], ["DURATION", attempt.returncode == null && !attempt.duration_ms ? "—" : `${Math.round(attempt.duration_ms)} ms`], ["PROCESS", attempt.returncode == null ? attempt.error || stopped ? "Not executed" : "Pending" : attempt.returncode === 0 ? "Succeeded" : "Failed"]].forEach(([key, value]) => { const item = el("span", "", key); item.append(el("b", "", String(value))); stats.append(item); });
    card.append(stats);
    if (attempt.validation) {
      const validation = attempt.validation;
      const line = el("div", `validation-line ${validation.passed ? "pass" : "fail"}`);
      line.append(el("span", "", validation.passed ? "✓" : "!"), el("span", "", `${validation.passed ? "Result check passed" : "Result check failed"} · ${validation.message || validation.kind || "Validation complete"}`)); card.append(line);
    }
    if (attempt.code) {
      const details = disclosure("Inspect Python source", number, "code");
      const source = el("div", "code-content"); source.setAttribute("aria-label", `Python source for attempt ${number}`);
      attempt.code.split("\n").forEach((line, lineIndex) => { const row = el("div", "code-line"); row.append(el("span", "line-number", lineIndex + 1), el("span", "line-code", line || " ")); source.append(row); });
      details.append(source); card.append(details);
    }
    const hasOutput = attempt.stdout !== undefined || attempt.stderr !== undefined;
    if (hasOutput) {
      const details = disclosure("Execution output · stdout & stderr", number, "output");
      [["STDOUT", attempt.stdout || "(empty)", false], ["STDERR", attempt.stderr || "(empty)", !!attempt.stderr]].forEach(([label, text, error]) => { const block = el("div", `output-block ${error ? "error-output" : ""}`); block.append(el("div", "output-label", label), el("pre", "", text)); details.append(block); }); card.append(details);
    }
    if (attempt.error || attempt.reflection || attempt.feedback) {
      const feedback = el("div", "feedback-box");
      feedback.append(el("strong", "", attempt.error ? `ERROR FEEDBACK · ${attempt.error.type || "Execution/validation"}${attempt.error.line ? ` · LINE ${attempt.error.line}` : ""}` : "REFLECTION / REPAIR FEEDBACK"));
      const reflection = attempt.reflection;
      if (attempt.error?.message) feedback.append(el("p", "", attempt.error.message));
      if (reflection) feedback.append(el("p", "", typeof reflection === "object" ? reflection.summary || reflection.message || stringify(reflection) : reflection));
      if (!reflection && attempt.feedback?.suggestion) feedback.append(el("p", "", attempt.feedback.suggestion));
      const mismatches = attempt.validation?.mismatches || [];
      if (mismatches.length) { const list = el("ul", "mismatch-list"); mismatches.forEach((mismatch) => list.append(el("li", "", typeof mismatch === "string" ? mismatch : `${mismatch.path || mismatch.field || "Result"}: ${mismatch.issue || "Check failed"}${mismatch.rule ? ` · ${mismatch.rule}` : ""}`))); feedback.append(list); }
      card.append(feedback);
      if (attempt.feedback) { const details = disclosure("Structured feedback JSON", number, "feedback"); details.append(el("pre", "result-json", stringify(attempt.feedback))); card.append(details); }
    }
    $("attempts").append(card);
  });
  if (focusedDisclosure) Array.from($("attempts").querySelectorAll("details[data-disclosure]")).find((details) => details.dataset.disclosure === focusedDisclosure)?.querySelector("summary").focus({ preventScroll: true });
}
function renderMetrics(run) {
  const metrics = run.metrics || {};
  $("runMetrics").hidden = false; $("runMetrics").replaceChildren();
  const duration = metrics.duration_ms ?? run.duration_ms;
  [["Attempts", metrics.attempts ?? run.attempts?.length ?? 0], ["Repairs", metrics.repairs ?? Math.max(0, (run.attempts?.length || 0) - 1)], ["Run time", duration != null ? `${(duration / 1000).toFixed(1)}s` : "—"]].forEach(([name, value]) => { const metric = el("div", "metric"); metric.append(el("span", "", name), el("b", "", value)); $("runMetrics").append(metric); });
}
function flattenResult(value, prefix = "", rows = []) {
  if (value && typeof value === "object" && !Array.isArray(value)) Object.entries(value).forEach(([key, child]) => flattenResult(child, prefix ? `${prefix}.${key}` : key, rows));
  else rows.push([prefix || "result", value]);
  return rows;
}
function renderResult(run) {
  const result = run.result;
  $("resultPanel").hidden = result === undefined || result === null;
  if ($("resultPanel").hidden) return;
  const validation = (run.attempts || []).at(-1)?.validation || run.validation;
  const passed = validation?.passed === true;
  $("resultValidation").className = `result-validation ${passed ? "" : "failed"}`;
  const custom = !run.preset_id || run.preset_id === "custom";
  $("resultValidation").textContent = `${passed ? "✓" : "!"} ${passed ? custom ? "Structure check passed" : "Validated result" : "Unvalidated result"}${validation?.kind ? ` · ${validation.kind}` : ""}${custom ? " · No independent answer oracle" : ""}`;
  $("tableView").classList.toggle("selected", state.view === "table"); $("jsonView").classList.toggle("selected", state.view === "json");
  $("tableView").setAttribute("aria-pressed", String(state.view === "table")); $("jsonView").setAttribute("aria-pressed", String(state.view === "json"));
  $("resultContent").replaceChildren();
  if (state.view === "json") { $("resultContent").append(el("pre", "result-json", stringify(result))); return; }
  const table = el("table", "result-table"); const head = el("thead"); const headRow = el("tr"); headRow.append(el("th", "", "Field"), el("th", "", "Value")); head.append(headRow); table.append(head);
  const body = el("tbody"); flattenResult(result).forEach(([key, value]) => { const row = el("tr"); row.append(el("td", "", key), el("td", "", stringify(value))); body.append(row); }); table.append(body); $("resultContent").append(table);
}
async function cancelRun() {
  if (!state.run || !state.active) return;
  $("cancelButton").disabled = true; $("cancelButton").textContent = "Stopping…";
  try { await request(`/api/runs/${encodeURIComponent(state.run.id)}/cancel`, { method: "POST", body: "{}" }); await pollRun(); }
  catch (error) { setFormError(error.message); }
  finally { $("cancelButton").textContent = "Stop run"; updateControls(); }
}
async function exportRun() {
  if (!state.run) return;
  try {
    const trace = await request(`/api/runs/${encodeURIComponent(state.run.id)}/export`);
    const url = URL.createObjectURL(new Blob([JSON.stringify(trace, null, 2)], { type: "application/json" }));
    const link = el("a"); link.href = url; link.download = `autoheal-${state.run.id}.json`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { setFormError(error.message); }
}
$("runForm").addEventListener("submit", startRun);
$("cancelButton").addEventListener("click", cancelRun);
$("refreshStatus").addEventListener("click", async () => { await Promise.allSettled([refreshStatus(), ...(state.presets.length ? [] : [loadPresets()])]); });
$("exportButton").addEventListener("click", exportRun);
$("modelSelect").addEventListener("change", updateControls);
document.querySelectorAll('input[name="mode"]').forEach((input) => input.addEventListener("change", setMode));
$("taskInput").addEventListener("input", () => { if (state.presetId === "custom") state.customTask = $("taskInput").value; updateControls(); });
$("tableView").addEventListener("click", () => { state.view = "table"; if (state.run) renderResult(state.run); });
$("jsonView").addEventListener("click", () => { state.view = "json"; if (state.run) renderResult(state.run); });
$("helpButton").addEventListener("click", () => $("helpDialog").showModal());
$("closeHelp").addEventListener("click", () => $("helpDialog").close());
$("closeHelpBottom").addEventListener("click", () => $("helpDialog").close());
$("helpDialog").addEventListener("click", (event) => { if (event.target === $("helpDialog")) { const rect = $("helpDialog").getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $("helpDialog").close(); } });
updateControls();
Promise.allSettled([loadPresets(), refreshStatus()]);
