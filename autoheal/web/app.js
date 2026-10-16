"use strict";
const $ = (id) => document.getElementById(id);
const state = { presets: [], service: null, run: null, active: false, selected: null, view: "source", traceIndex: -1, traceTimer: null, pollTimer: null, renderKey: "", customTask: "", customData: "{}", advancing: false, announcement: "" };
const terminal = new Set(["succeeded", "exhausted", "cancelled", "provider_error", "failed"]);
const phaseName = { generate: "Generate", execute: "Execute", evaluate: "Evaluate", reflect: "Reflect", done: "Stop", repair: "Repair" };
const keywordPattern = /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|#.*$|\b(?:False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b|\b\d+(?:\.\d+)?\b|\b(?:print|range|len|sum|round|sorted|float|int|str|dict|list|set|zip|max|min|enumerate)\b)/g;
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined && text !== null) node.textContent = text; return node; }
function json(value) { return value === undefined ? "(missing)" : typeof value === "string" ? value : JSON.stringify(value, null, 2); }
function custom() { return $("presetSelect").value === "custom"; }
function preset() { return state.presets.find((item) => item.id === $("presetSelect").value); }
function provider() { return $("providerSelect").value; }
function runLabel(run) { if (run.status === "succeeded") return run.validation_kind === "structural" || !run.preset_id ? "STRUCTURE PASSED" : "VALIDATED"; return ({ queued: "QUEUED", running: run.awaiting_step ? "WAITING FOR STEP" : "RUNNING", exhausted: "LIMIT REACHED", cancelled: "STOPPED", provider_error: "MODEL ERROR" })[run.status] || String(run.status).toUpperCase(); }
function announce(message) { if (state.announcement !== message) { $("announcer").textContent = message; state.announcement = message; } }
function formError(message = "") { $("formError").textContent = message; $("formError").hidden = !message; }
async function api(path, options = {}) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
  try { const response = await fetch(path, { ...options, signal: controller.signal, headers: { "Content-Type": "application/json", ...options.headers } }); const body = await response.json(); if (!response.ok) throw new Error(typeof body.error === "string" ? body.error : body.error?.message || body.message || `Request failed (${response.status})`); return body; }
  catch (error) { if (error.name === "AbortError") throw new Error("The local server did not respond in time. Refresh connection to retry."); if (error instanceof TypeError) throw new Error("Cannot reach the local server. Start AutoHeal Studio and refresh connection."); throw error; }
  finally { clearTimeout(timer); }
}
function providerConfig(id) {
  const supplied = state.service?.providers?.find((item) => item.id === id);
  if (supplied) return supplied;
  if (id === "ollama") return { available: !!state.service?.ollama_available, models: state.service?.models || [], default_model: state.service?.default_model };
  return { available: !!state.service?.api_configured, models: state.service?.api_models || [], default_model: state.service?.api_model };
}
function setProvider() {
  const source = provider(), config = providerConfig(source), previous = $("modelSelect").value;
  $("modelSelect").replaceChildren();
  if (source === "replay") { const option = el("option", "", "Fixed replay programs"); option.value = "scripted-replay"; $("modelSelect").append(option); $("seedFailure").checked = true; }
  else { (config.models || []).forEach((item) => { const name = typeof item === "string" ? item : item.name || item.model; if (name) { const option = el("option", "", name); option.value = name; $("modelSelect").append(option); } }); if (!$("modelSelect").options.length) { const option = el("option", "", source === "api" ? "API not configured" : "No local model available"); option.value = ""; $("modelSelect").append(option); } else if (Array.from($("modelSelect").options).some((o) => o.value === previous)) $("modelSelect").value = previous; else if (Array.from($("modelSelect").options).some((o) => o.value === config.default_model)) $("modelSelect").value = config.default_model; }
  $("providerHint").textContent = source === "replay" ? "SCRIPTED REPLAY: fixed source, actual Python execution. No AI calls." : source === "api" ? "A locally configured API generates code. Input and failure feedback leave this laptop." : "LIVE OLLAMA: the installed model generates and repairs code locally.";
  if (!providerConfig("api").available) $("providerHint").textContent += " API mode requires local environment configuration; keys are never entered here.";
  updateControls(); if (!state.run) renderSelected();
}
function updateControls() {
  const source = provider(), config = providerConfig(source);
  const ready = source === "replay" ? !custom() : config.available && $("modelSelect").value;
  $("runButton").disabled = state.active || !ready || !$("taskInput").value.trim();
  $("runButton").textContent = state.active ? "Run in progress…" : "▶ Start run";
  $("stopButton").disabled = !state.active;
  $("newRunButton").disabled = state.active;
  $("exportButton").disabled = !state.run;
  ["presetSelect", "taskInput", "dataInput", "providerSelect", "attemptLimit", "timeoutSelect"].forEach((id) => { $(id).disabled = state.active; });
  $("modelSelect").disabled = state.active || source === "replay";
  $("seedFailure").disabled = state.active || custom() || source === "replay";
  $("providerSelect").querySelector('option[value="api"]').disabled = !providerConfig("api").available;
  $("providerSelect").querySelector('option[value="replay"]').disabled = custom();
  document.querySelectorAll('input[name="runStyle"]').forEach((input) => { input.disabled = state.active; });
  if (custom()) $("seedFailure").checked = false;
  $("seedHint").textContent = custom() ? "Controlled samples are available for verified presets only." : source === "replay" ? "Replay always starts with its fixed, documented fault." : "Attempt 1 uses a labelled, prewritten faulty sample.";
  const waiting = state.active && state.run?.awaiting_step;
  document.querySelector(".control-window").classList.toggle("manual-active", state.active && state.run?.control_mode === "manual");
  $("advanceButton").disabled = !waiting || state.advancing;
  $("advanceButton").textContent = waiting ? `Next: ${phaseName[state.run.next_phase] || state.run.next_phase || "stage"} →` : "Next stage →";
}
async function refresh() {
  $("refreshButton").disabled = true;
  try { state.service = await api("/api/status"); const local = providerConfig("ollama"); $("serviceStatus").textContent = local.available ? "Ollama connected · local execution" : "Ollama unavailable · replay available"; $("serviceStatus").className = `system-pill ${local.available ? "connected" : "unavailable"}`; $("safetyDetails").textContent = state.service.safety || ""; setProvider(); }
  catch (error) { state.service = null; $("serviceStatus").textContent = error.message; $("serviceStatus").className = "system-pill unavailable"; setProvider(); }
  finally { $("refreshButton").disabled = false; }
}
async function loadPresets() {
  try { const response = await api("/api/presets"); state.presets = Array.isArray(response) ? response : response.presets || []; }
  catch (error) { state.presets = []; formError(`${error.message} You can define a custom task; refresh to retry presets.`); }
  const previous = $("presetSelect").value; $("presetSelect").replaceChildren();
  [...state.presets].sort((a, b) => a.id === "grades" ? -1 : b.id === "grades" ? 1 : 0).forEach((item) => { const option = el("option", "", item.title); option.value = item.id; $("presetSelect").append(option); });
  const option = el("option", "", "Custom Python task"); option.value = "custom"; $("presetSelect").append(option);
  $("presetSelect").value = state.presets.some((item) => item.id === previous) || previous === "custom" ? previous : state.presets[0]?.id || "custom";
  selectTask();
}
function selectTask() {
  const isCustom = custom(), selected = preset();
  $("taskInput").readOnly = !isCustom; $("dataInput").readOnly = !isCustom;
  $("taskLabel").replaceChildren(document.createTextNode(isCustom ? "Task instructions " : "Task contract "), el("span", "field-note", isCustom ? "EDITABLE" : "READ ONLY"));
  $("taskInput").value = isCustom ? state.customTask : selected?.task || selected?.prompt || "";
  $("dataInput").value = isCustom ? state.customData : JSON.stringify(selected?.data ?? {}, null, 2);
  $("dataCaption").textContent = isCustom ? "EDITABLE JSON" : "FIXED PRESET / DATA";
  $("dataHint").textContent = isCustom ? "Optional JSON supplied as DATA. Custom output receives structural checks only; no independent answer oracle." : "Provided to Python as DATA. Preset answers are independently checked.";
  if (isCustom) { $("seedFailure").checked = false; if (provider() === "replay") $("providerSelect").value = "ollama"; } else $("seedFailure").checked = true;
  formError(); setProvider();
}
function sample() { const preview = preset()?.seed_preview; return typeof preview === "string" ? { code: preview } : preview; }
function selectedAttempt() { const attempts = state.run?.attempts || []; return attempts[state.selected ?? attempts.length - 1]; }
function selectedIndex() { return state.selected ?? Math.max(0, (state.run?.attempts?.length || 1) - 1); }
function syntax(line) {
  const fragment = document.createDocumentFragment(); let cursor = 0;
  for (const match of line.matchAll(keywordPattern)) { if (match.index > cursor) fragment.append(document.createTextNode(line.slice(cursor, match.index))); const token = match[0]; const type = /^['"]/.test(token) ? "string" : token.startsWith("#") ? "comment" : /^\d/.test(token) ? "number" : /^(print|range|len|sum|round|sorted|float|int|str|dict|list|set|zip|max|min|enumerate)$/.test(token) ? "function" : "keyword"; fragment.append(el("span", `token-${type}`, token)); cursor = match.index + token.length; }
  if (cursor < line.length) fragment.append(document.createTextNode(line.slice(cursor))); return fragment;
}
function diffLines(before, after) {
  const a = before.split("\n"), b = after.split("\n");
  if (a.length * b.length > 500000) {
    let prefix = 0, suffix = 0; while (prefix < a.length && prefix < b.length && a[prefix] === b[prefix]) prefix++; while (suffix < a.length - prefix && suffix < b.length - prefix && a[a.length - suffix - 1] === b[b.length - suffix - 1]) suffix++;
    const rows = []; for (let i = 0; i < prefix; i++) rows.push({ type: "same", text: a[i], old: i + 1, next: i + 1 }); for (let i = prefix; i < a.length - suffix; i++) rows.push({ type: "removed", text: a[i], old: i + 1, next: "" }); for (let i = prefix; i < b.length - suffix; i++) rows.push({ type: "added", text: b[i], old: "", next: i + 1 }); for (let i = suffix; i > 0; i--) rows.push({ type: "same", text: a[a.length - i], old: a.length - i + 1, next: b.length - i + 1 }); return rows;
  }
  const matrix = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) matrix[i][j] = a[i] === b[j] ? matrix[i + 1][j + 1] + 1 : Math.max(matrix[i + 1][j], matrix[i][j + 1]);
  const rows = []; let i = 0, j = 0;
  while (i < a.length || j < b.length) { if (i < a.length && j < b.length && a[i] === b[j]) { rows.push({ type: "same", text: a[i], old: ++i, next: ++j }); } else if (j < b.length && (i === a.length || matrix[i][j + 1] >= matrix[i + 1][j])) { rows.push({ type: "added", text: b[j], old: "", next: ++j }); } else { rows.push({ type: "removed", text: a[i], old: ++i, next: "" }); } }
  return rows;
}
function renderCode(attempt, preview) {
  const code = attempt?.code || preview?.code || "", index = selectedIndex(), trace = attempt?.exec_steps || [], traceEvent = trace[state.traceIndex];
  const previous = state.run?.attempts?.[index - 1]?.code;
  const pane = $("codePane"), scrollTop = pane.scrollTop, scrollLeft = pane.scrollLeft; pane.replaceChildren();
  $("sourceTab").classList.toggle("selected", state.view === "source"); $("sourceTab").setAttribute("aria-pressed", String(state.view === "source"));
  $("diffTab").classList.toggle("selected", state.view === "diff"); $("diffTab").setAttribute("aria-pressed", String(state.view === "diff"));
  $("diffTab").disabled = !previous || !attempt?.code;
  if (!code) { pane.append(el("div", "code-empty", state.active ? "Python source appears when this stage produces a complete candidate. No code has been executed for this attempt yet." : "No source yet. Choose a verified preset to inspect its labelled sample, or start a custom task.")); return; }
  if (state.view === "diff" && previous) diffLines(previous, code).forEach((item) => { const row = el("div", `code-line diff-line ${item.type}`); row.append(el("span", "line-gutter", `${item.old || "·"} ${item.next || "·"}`), el("span", "diff-sign", item.type === "added" ? "+" : item.type === "removed" ? "−" : " ")); const text = el("span", "line-text"); text.append(syntax(item.text)); row.append(text); pane.append(row); });
  else code.split("\n").forEach((line, i) => { const row = el("div", "code-line"); row.dataset.line = i + 1; if (attempt?.error?.line === i + 1) row.classList.add("error-line"); if (traceEvent?.line === i + 1) row.classList.add("trace-selected"); row.append(el("span", "line-gutter", i + 1)); const text = el("span", "line-text"); text.append(syntax(line || " ")); row.append(text); pane.append(row); });
  pane.scrollTop = scrollTop; pane.scrollLeft = scrollLeft;
}
function renderAttemptOptions() {
  const attempts = state.run?.attempts || [], previous = $("attemptSelect").value;
  $("attemptSelect").replaceChildren();
  if (!attempts.length) { const option = el("option", "", state.run ? "Awaiting first candidate" : "Controlled-fault sample"); option.value = "sample"; $("attemptSelect").append(option); }
  attempts.forEach((attempt, index) => { const label = attempt.status === "success" ? "passed checks" : attempt.status === "failed" ? "failed" : attempt.status === "cancelled" ? "stopped" : "in progress"; const option = el("option", "", `Attempt ${attempt.number || index + 1} / ${label}`); option.value = index; $("attemptSelect").append(option); });
  if (attempts.length) $("attemptSelect").value = selectedIndex(); else $("attemptSelect").value = previous === "sample" ? previous : "sample";
  $("prevAttempt").disabled = !attempts.length || selectedIndex() <= 0; $("nextAttempt").disabled = !attempts.length || selectedIndex() >= attempts.length - 1;
}
function renderTrace(attempt) {
  const trace = attempt?.exec_steps || [];
  if (trace.length && state.traceIndex < 0) state.traceIndex = 0;
  if (state.traceIndex >= trace.length) state.traceIndex = trace.length - 1;
  const event = trace[state.traceIndex];
  $("traceCaption").textContent = trace.length ? `CAPTURED LINE EVENTS · ${trace.length}${attempt.trace_truncated ? " (capped)" : ""} · replay is not a live debugger` : attempt?.trace_enabled === false ? "Execution tracing disabled for this attempt." : "Captured line events appear after Python executes.";
  $("tracePosition").textContent = event ? `Event ${state.traceIndex + 1} / ${trace.length} · ${event.event} · line ${event.line}` : "No event selected";
  $("localsContent").textContent = event ? JSON.stringify({ timing: event.event === "line" ? "Before this source line executes" : "Exception at this source line", ...event }, null, 2) : "No captured line event selected.";
  $("prevTrace").disabled = !trace.length || state.traceIndex <= 0; $("nextTrace").disabled = !trace.length || state.traceIndex >= trace.length - 1; $("playTrace").disabled = !trace.length;
  $("playTrace").textContent = state.traceTimer ? "Ⅱ Pause replay" : "▶ Replay lines";
}
function equal(actual, expected) { if (typeof actual === "number" && typeof expected === "number") return Math.abs(actual - expected) <= Math.max(1e-8, Math.abs(expected) * 1e-8); if (Array.isArray(expected)) return Array.isArray(actual) && actual.length === expected.length && expected.every((v, i) => equal(actual[i], v)); if (expected && typeof expected === "object") return actual && typeof actual === "object" && !Array.isArray(actual) && Object.keys(actual).length === Object.keys(expected).length && Object.entries(expected).every(([key, value]) => Object.hasOwn(actual, key) && equal(actual[key], value)); return actual === expected; }
function checkRow(field, expected, actual, passed, assessed = true) { const row = el("tr"); row.append(el("td", "", field), el("td", "", json(expected)), el("td", "", json(actual)), el("td", passed ? "pass" : "fail", assessed ? passed ? "PASS" : "FAIL" : "NOT CHECKED")); $("checksBody").append(row); }
function renderEvaluation(attempt) {
  const validation = attempt?.validation, isCustom = state.run ? !state.run.preset_id || state.run.validation_kind === "structural" : custom();
  $("checksBody").replaceChildren();
  $("validationStatus").textContent = validation ? validation.passed ? isCustom ? "STRUCTURE PASSED" : "RESULT CHECKS PASSED" : "RESULT CHECKS FAILED" : "NOT EVALUATED";
  $("errorCause").textContent = attempt?.error ? `${attempt.error.type || "Error"}${attempt.error.line ? ` at line ${attempt.error.line}` : ""}: ${attempt.error.message}` : validation?.passed ? isCustom ? "Python returned a non-empty JSON object. Task correctness has not been independently verified." : "Python execution succeeded and all independent reference checks passed." : attempt?.returncode === 0 ? "Process exited with code 0. The answer still requires a separate validation stage." : "A successful exit code confirms execution. The validator separately checks the answer.";
  $("repairDiagnosis").textContent = attempt?.reflection || (attempt?.feedback ? attempt.feedback.suggestion : "After a failed evaluation, structured evidence informs the next candidate. No repair diagnosis yet.");
  $("validationNotice").hidden = !validation;
  $("validationNotice").className = `validation-notice ${validation?.passed ? "pass" : ""}`;
  $("validationNotice").textContent = validation ? `${validation.message || "Validation complete."}${isCustom ? " No independent answer oracle is available for custom tasks." : ""}` : "";
  const presetForRun = state.presets.find((item) => item.id === state.run?.preset_id), expected = validation?.expected || presetForRun?.expected || (!state.run ? preset()?.expected : null), actual = validation?.actual;
  if (!validation) { const row = el("tr"); const cell = el("td", "empty-cell", "Result checks appear after the Evaluate stage. Process success alone does not pass the task."); cell.colSpan = 4; row.append(cell); $("checksBody").append(row); }
  else if (isCustom) checkRow("JSON structure", "Non-empty JSON object", actual, validation.passed);
  else if (expected && typeof expected === "object") [...new Set([...Object.keys(expected), ...Object.keys(actual && typeof actual === "object" ? actual : {})])].forEach((field) => checkRow(field, expected[field], actual?.[field], equal(actual?.[field], expected[field]), validation.kind !== "execution"));
  else checkRow("Execution / JSON parsing", "Successful execution and valid JSON", attempt?.error?.type || actual, validation.passed);
  $("feedbackJSON").textContent = attempt?.feedback ? JSON.stringify(attempt.feedback, null, 2) : "No structured repair feedback has been prepared for this attempt.";
  $("resultJSON").textContent = state.run?.result != null ? JSON.stringify(state.run.result, null, 2) : "No validated final result yet.";
}
function renderSelected() {
  const attempt = selectedAttempt(), preview = !state.run && $("seedFailure").checked ? sample() : null;
  renderAttemptOptions(); renderTrace(attempt); renderCode(attempt, preview); renderEvaluation(attempt);
  $("sampleNotice").hidden = !preview;
  if (preview) $("sampleNotice").textContent = `PREWRITTEN CONTROLLED-FAULT SAMPLE · Not generated by the model. ${preview.description || preview.expected_failure || "Start a run to execute it."}`;
  $("sourceOrigin").textContent = preview ? "PREWRITTEN / NOT EXECUTED" : attempt?.code ? attempt.seeded ? "CONTROLLED FAULT / PREWRITTEN" : state.run.mode === "replay" ? "SCRIPTED REPLAY / FIXED SOURCE" : "MODEL-GENERATED PYTHON" : "NO CANDIDATE YET";
  $("stdout").textContent = attempt ? attempt.stdout || "(empty stdout)" : "No process output yet."; $("stderr").textContent = attempt ? attempt.stderr || "(empty stderr)" : "No process diagnostics yet.";
  $("exitMetric").textContent = `Exit ${attempt?.returncode ?? "—"}`; $("durationMetric").textContent = attempt?.duration_ms ? `${Math.round(attempt.duration_ms)} ms` : "— ms";
  $("processStatus").textContent = attempt?.returncode === 0 ? "EXECUTED / EXIT 0" : attempt?.returncode != null ? "EXECUTION FAILED" : attempt?.error ? "NOT COMPLETED" : "NOT EXECUTED";
  const generating = state.active && state.run.phase === "generate" && !state.run.awaiting_step && selectedIndex() === (state.run.attempts?.length || 1) - 1;
  const raw = state.run?.generation_output;
  $("generationProgress").hidden = !generating || !raw;
  $("generationProgress").className = "source-notice live-progress";
  $("generationProgress").textContent = generating && raw ? `ACTUAL PROVIDER RESPONSE (partial; not executed)\n${typeof raw === "string" ? raw.slice(-1500) : json(raw)}` : "";
}
function renderHistory(run) {
  const events = run.events || []; $("eventCount").textContent = `${events.length} captured events`; $("eventHistory").replaceChildren();
  events.forEach((event) => { const row = el("li"); const time = event.time ? new Date(event.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "—"; row.append(el("time", "", time), el("strong", "", `${String(event.phase).toUpperCase()}${event.attempt ? ` / ${event.attempt}` : ""}`), el("p", "", event.message)); $("eventHistory").append(row); });
}
function renderRun(run) {
  const phase = run.awaiting_step ? run.next_phase : run.phase;
  const visited = new Set((run.stage_history || []).filter((stage) => stage.status === "complete").map((stage) => stage.phase));
  (run.events || []).filter((event) => event.kind === "stage_completed").forEach((event) => visited.add(event.phase));
  document.querySelectorAll(".stage").forEach((node) => { const key = node.dataset.phase; const current = key === (phase === "done" ? "repair" : phase); node.className = `stage${current ? " current" : visited.has(key) || key === "repair" && visited.has("done") ? " complete" : ""}`; if (current) node.setAttribute("aria-current", "step"); else node.removeAttribute("aria-current"); });
  $("runStatus").textContent = runLabel(run);
  const actions = { generate: "The task, input data, and previous error feedback produce a complete Python candidate.", execute: "The current candidate runs in a constrained Python subprocess; stdout, stderr, exit code, duration, and line events are captured.", evaluate: "The returned JSON is checked independently from the process exit code.", reflect: "The precise exception or failed result fields are assembled into structured repair feedback.", done: run.status === "succeeded" ? "The configured result checks passed. The loop stopped immediately." : "This run has stopped. Inspect its attempts and captured evidence." };
  $("stageExplanation").textContent = run.awaiting_step ? `PAUSED BEFORE ${String(phaseName[run.next_phase] || run.next_phase).toUpperCase()} / ATTEMPT ${run.next_attempt || run.attempts?.length || 1}. ${actions[run.next_phase] || "Inspect the current outputs, then advance."}` : actions[run.phase] || "Waiting for the next recorded stage.";
  $("runFootnote").textContent = `Run ${run.id} · ${run.mode === "replay" ? "SCRIPTED REPLAY / NO AI CALLS" : `LIVE ${String(run.provider || "ollama").toUpperCase()} / ${run.model}`} · ${runLabel(run)}`;
  renderHistory(run);
  const key = JSON.stringify({ attempts: run.attempts, result: run.result, generation: run.generation_output, phase: run.phase, waiting: run.awaiting_step, status: run.status, selected: state.selected });
  if (key !== state.renderKey) { renderSelected(); state.renderKey = key; }
  updateControls(); announce(`${runLabel(run)}. ${run.awaiting_step ? `Paused before ${phaseName[run.next_phase] || run.next_phase}.` : phaseName[run.phase] || run.phase}`);
}
async function startRun(event) {
  event.preventDefault(); if (state.active) return; formError();
  let data; try { data = JSON.parse($("dataInput").value.trim() || "{}"); const values = [data]; while (values.length) { const value = values.pop(); if (typeof value === "number" && !Number.isFinite(value)) throw new Error("Non-finite numeric input"); if (value && typeof value === "object") values.push(...Object.values(value)); } } catch { formError("Input data must be valid JSON with finite numeric values. Fix the JSON before starting the run."); $("dataInput").focus(); return; }
  const source = provider(); const body = { preset_id: custom() ? "custom" : $("presetSelect").value, task: $("taskInput").value.trim(), data, mode: source === "replay" ? "replay" : "live", provider: source === "api" ? "api" : "ollama", model: $("modelSelect").value, control_mode: document.querySelector('input[name="runStyle"]:checked').value, max_attempts: Number($("attemptLimit").value), timeout: Number($("timeoutSelect").value), seed_failure: $("seedFailure").checked, trace_execution: true };
  if (!body.task) { formError("Describe a task before starting the run."); return; }
  state.active = true; updateControls(); stopTrace();
  try { const response = await api("/api/runs", { method: "POST", body: JSON.stringify(body) }); state.run = { id: response.run_id || response.id, ...body, status: "queued", phase: "generate", attempts: [], events: [], result: null }; state.selected = null; state.traceIndex = -1; state.view = "source"; state.renderKey = ""; renderRun(state.run); await poll(); }
  catch (error) { state.active = false; formError(error.message); updateControls(); }
}
async function poll() {
  clearTimeout(state.pollTimer); if (!state.run) return;
  const runId = state.run.id;
  try { const run = await api(`/api/runs/${encodeURIComponent(runId)}`); if (state.run?.id !== runId) return; const previousCount = state.run.attempts?.length || 0; state.run = run; state.active = !terminal.has(run.status); if (state.selected === null && (run.attempts?.length || 0) !== previousCount) { stopTrace(); state.traceIndex = -1; } renderRun(run); if (state.active) state.pollTimer = setTimeout(poll, run.awaiting_step ? 900 : 450); }
  catch (error) { formError(`${error.message} Connection retries continue; the run may still be active.`); if (state.active) state.pollTimer = setTimeout(poll, 2500); }
}
async function advance() {
  if (!state.run?.awaiting_step || state.advancing) return; state.advancing = true; updateControls();
  try { const run = await api(`/api/runs/${encodeURIComponent(state.run.id)}/advance`, { method: "POST", body: JSON.stringify({ step_token: state.run.step_token }) }); if (run.id) { state.run = run; state.active = !terminal.has(run.status); renderRun(run); } await poll(); }
  catch (error) { formError(error.message); await poll(); }
  finally { state.advancing = false; updateControls(); }
}
async function stopRun() { if (!state.active || !state.run) return; $("stopButton").disabled = true; try { await api(`/api/runs/${encodeURIComponent(state.run.id)}/cancel`, { method: "POST", body: "{}" }); await poll(); } catch (error) { formError(error.message); } finally { updateControls(); } }
function resetRun() { if (state.active) return; clearTimeout(state.pollTimer); stopTrace(); state.run = null; state.selected = null; state.view = "source"; state.traceIndex = -1; state.renderKey = ""; $("runStatus").textContent = "READY"; $("stageExplanation").textContent = "Choose a task, inspect its input, then start an automatic or step-through run."; $("runFootnote").textContent = "Ready · No new model calls or subprocesses started"; $("eventHistory").replaceChildren(); $("eventCount").textContent = "No run started"; document.querySelectorAll(".stage").forEach((node) => { node.className = "stage"; node.removeAttribute("aria-current"); }); formError(); renderSelected(); updateControls(); }
async function exportRun() { if (!state.run) return; try { const trace = await api(`/api/runs/${encodeURIComponent(state.run.id)}/export`); const url = URL.createObjectURL(new Blob([JSON.stringify(trace, null, 2)], { type: "application/json" })); const link = el("a"); link.href = url; link.download = `autoheal-${state.run.id}.json`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); } catch (error) { formError(error.message); } }
function selectAttempt(index) { const attempts = state.run?.attempts || []; if (!attempts.length) return; stopTrace(); state.selected = Math.max(0, Math.min(attempts.length - 1, Number(index))); state.traceIndex = -1; state.view = "source"; renderSelected(); }
function moveTrace(index, scroll = true) { const trace = selectedAttempt()?.exec_steps || []; if (!trace.length) return; state.traceIndex = Math.max(0, Math.min(trace.length - 1, index)); renderTrace(selectedAttempt()); renderCode(selectedAttempt()); if (scroll && state.view === "source") { const row = $("codePane").querySelector(".trace-selected"); if (row) { const pane = $("codePane"); const top = row.offsetTop - pane.offsetTop; if (top < pane.scrollTop || top + row.offsetHeight > pane.scrollTop + pane.clientHeight) pane.scrollTop = Math.max(0, top - pane.clientHeight / 2); } } }
function stopTrace() { if (state.traceTimer) clearInterval(state.traceTimer); state.traceTimer = null; if ($("playTrace")) $("playTrace").textContent = "▶ Replay lines"; }
function playTrace() { if (state.traceTimer) { stopTrace(); return; } const trace = selectedAttempt()?.exec_steps || []; if (!trace.length) return; if (state.traceIndex >= trace.length - 1) state.traceIndex = -1; $("localsDisclosure").open = true; state.traceTimer = setInterval(() => { moveTrace(state.traceIndex + 1); if (state.traceIndex >= (selectedAttempt()?.exec_steps?.length || 0) - 1) stopTrace(); }, 650); $("playTrace").textContent = "Ⅱ Pause replay"; }
$("runForm").addEventListener("submit", startRun); $("stopButton").addEventListener("click", stopRun); $("advanceButton").addEventListener("click", advance); $("newRunButton").addEventListener("click", resetRun); $("exportButton").addEventListener("click", exportRun);
$("refreshButton").addEventListener("click", async () => { await Promise.allSettled([refresh(), ...(!state.presets.length ? [loadPresets()] : [])]); });
$("presetSelect").addEventListener("change", () => { resetRun(); selectTask(); }); $("providerSelect").addEventListener("change", setProvider); $("modelSelect").addEventListener("change", updateControls); $("seedFailure").addEventListener("change", () => { if (!state.run) renderSelected(); });
$("taskInput").addEventListener("input", () => { if (custom()) state.customTask = $("taskInput").value; updateControls(); }); $("dataInput").addEventListener("input", () => { if (custom()) state.customData = $("dataInput").value; });
$("attemptSelect").addEventListener("change", () => selectAttempt($("attemptSelect").value)); $("prevAttempt").addEventListener("click", () => selectAttempt(selectedIndex() - 1)); $("nextAttempt").addEventListener("click", () => selectAttempt(selectedIndex() + 1));
$("wrapLines").addEventListener("change", () => { $("codePane").classList.toggle("wrap-lines", $("wrapLines").checked); });
$("sourceTab").addEventListener("click", () => { state.view = "source"; renderSelected(); }); $("diffTab").addEventListener("click", () => { stopTrace(); state.view = "diff"; renderSelected(); }); $("prevTrace").addEventListener("click", () => { stopTrace(); moveTrace(state.traceIndex - 1); }); $("nextTrace").addEventListener("click", () => { stopTrace(); moveTrace(state.traceIndex + 1); }); $("playTrace").addEventListener("click", playTrace);
$("aboutButton").addEventListener("click", () => $("aboutDialog").showModal()); $("safetyButton").addEventListener("click", () => $("safetyDialog").showModal()); document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
updateControls(); Promise.allSettled([loadPresets(), refresh()]);
