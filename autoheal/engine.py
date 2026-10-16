"""Observable automatic or manually advanced code-repair state machine."""
import copy
from datetime import datetime, timezone
import inspect
import json
import threading
import time
import uuid

from .executor import compact_output, execute_code
from .presets import PRESETS, FIELD_RULES, validate_result
from .provider import DEFAULT_MODEL, ProviderError, generate, provider_default_model

TERMINAL = {"succeeded", "exhausted", "cancelled", "provider_error"}
MAX_CUSTOM_DATA = 12000


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AdvanceConflict(ValueError):
    """A request did not identify the currently waiting stage."""


class RunManager:
    def __init__(self, generator=generate):
        self.generator = generator
        self.runs = {}
        self.lock = threading.RLock()

    def create(self, config):
        if not isinstance(config, dict):
            raise ValueError("Request body must be a JSON object.")
        preset_id = config.get("preset_id", "sales")
        if preset_id in ("custom", None):
            preset_id = ""
        if not isinstance(preset_id, str) or (preset_id and preset_id not in PRESETS):
            raise ValueError("Unknown preset.")
        preset = PRESETS.get(preset_id)
        task = preset["prompt"] if preset else config.get("task", "")
        if not isinstance(task, str) or not task.strip() or len(task) > 5000:
            raise ValueError("Task must contain 1–5000 characters.")
        task = task.strip()
        mode = config.get("mode", "live")
        if not isinstance(mode, str) or mode not in {"live", "replay"}:
            raise ValueError("Mode must be live or replay.")
        if mode == "replay" and not preset:
            raise ValueError("Scripted replay is available only for verified presets.")
        provider = config.get("provider", "ollama")
        if not isinstance(provider, str) or provider not in {"ollama", "api"}:
            raise ValueError("Provider must be ollama or api.")
        control_mode = config.get("control_mode", "auto")
        if not isinstance(control_mode, str) or control_mode not in {"auto", "manual"}:
            raise ValueError("control_mode must be auto or manual.")
        trace_execution = config.get("trace_execution", True)
        if not isinstance(trace_execution, bool):
            raise ValueError("trace_execution must be true or false.")
        try:
            attempts = config.get("max_attempts", 5)
            if not isinstance(attempts, int) or isinstance(attempts, bool):
                raise ValueError("Attempt count must be an integer.")
            timeout = float(config.get("timeout", 5))
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Invalid attempt count or timeout.") from None
        if not 1 <= attempts <= 5 or not 1 <= timeout <= 5:
            raise ValueError("Attempt count and execution timeout must be between 1 and 5.")
        model = config.get("model") or provider_default_model(provider)
        if not isinstance(model, str) or len(model) > 150 or any(c in model for c in "\n\r\x00"):
            raise ValueError("Invalid model name.")
        seed = config.get("seed_failure", False)
        if not isinstance(seed, bool) or (seed and not preset):
            raise ValueError("seed_failure must be true or false and requires a verified preset.")
        if any(key in config for key in ("api_key", "access_token", "authorization")):
            raise ValueError("Configure API credentials in the server environment, never in run requests.")
        data = preset["data"] if preset else config.get("data", {})
        if preset and "data" in config and config["data"] != data:
            raise ValueError("Verified preset data is fixed; use a custom task for another dataset.")
        try:
            serialized = json.dumps(data, ensure_ascii=True, allow_nan=False)
            if len(serialized) > MAX_CUSTOM_DATA:
                raise ValueError("DATA exceeds the 12000-character limit.")
            data = json.loads(serialized)
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise ValueError("DATA must be finite, serializable JSON of at most 12000 characters.") from None
        with self.lock:
            if sum(not run["worker_done"] for run in self.runs.values()) >= 2:
                raise ValueError("Two run workers are still active. Wait for completion or cancellation cleanup.")
            if len(self.runs) >= 40:
                old = next((key for key, run in self.runs.items() if run["worker_done"] and run["state"]["status"] in TERMINAL), None)
                if old:
                    del self.runs[old]
            run_id = uuid.uuid4().hex[:16]
            notice = "Scripted replay uses predetermined programs; execution observations are real, model generation is not performed." if mode == "replay" else "Live model generation. A controlled first failure, if selected, is prewritten and explicitly marked."
            state = {
                "id": run_id, "status": "queued", "phase": "generate", "phase_status": "queued",
                "task": task, "preset_id": preset_id, "mode": mode, "provider": provider,
                "model": model if mode == "live" else "scripted-replay", "control_mode": control_mode,
                "max_attempts": attempts, "timeout": timeout, "seed_failure": seed, "trace_execution": trace_execution,
                "input_data": copy.deepcopy(data), "task_contract": {"validation_kind": "semantic" if preset else "structural", "expected_keys": list(preset["expected"]) if preset else [], "rules": copy.deepcopy(FIELD_RULES.get(preset_id, {})), "description": "Independently checked against this preset's fixed reference." if preset else "Execution and non-empty JSON object only; domain correctness is unverified."},
                "awaiting_step": False, "next_phase": None, "next_attempt": None, "step_sequence": 0, "step_token": None,
                "attempts": [], "events": [], "stage_history": [], "generation_output": "", "result": None,
                "started_at": timestamp(), "finished_at": None,
                "metrics": {"attempts": 0, "repairs": 0, "passed": False, "duration_ms": 0, "generation_ms": 0, "execution_ms": 0, "waiting_ms": 0},
                "validation_kind": "semantic" if preset else "structural", "notice": notice,
            }
            run = {"state": state, "cancel": threading.Event(), "advance": threading.Event(), "consumed_tokens": set(), "connection": None, "worker_done": False, "start": time.monotonic(), "wait_start": None, "stage_start": None, "data": data}
            self.runs[run_id] = run
            threading.Thread(target=self._work, args=(run_id,), daemon=True, name=f"autoheal-{run_id}").start()
            return run_id

    def snapshot(self, run_id):
        with self.lock:
            run = self.runs.get(run_id)
            if not run:
                return None
            result = copy.deepcopy(run["state"])
            if result["status"] not in TERMINAL:
                result["metrics"]["duration_ms"] = round((time.monotonic() - run["start"]) * 1000)
            if run["wait_start"] is not None:
                result["metrics"]["waiting_ms"] += round((time.monotonic() - run["wait_start"]) * 1000)
            return result

    def advance(self, run_id, step_token):
        with self.lock:
            run = self.runs.get(run_id)
            if not run:
                return None
            state = run["state"]
            if not isinstance(step_token, str) or not step_token or len(step_token) > 100:
                raise AdvanceConflict("Supply the exact step_token from the waiting run snapshot.")
            if step_token in run["consumed_tokens"]:
                result = self.snapshot(run_id)
                result["advance"] = {"accepted": False, "duplicate": True}
                return result
            if state["control_mode"] != "manual" or not state["awaiting_step"] or step_token != state["step_token"] or state["status"] in TERMINAL:
                raise AdvanceConflict("This token does not identify the currently waiting stage. Refresh the snapshot.")
            run["consumed_tokens"].add(step_token)
            state.update(awaiting_step=False, next_phase=None, next_attempt=None, step_token=None, phase_status="running")
            run["advance"].set()
            result = self.snapshot(run_id)
            result["advance"] = {"accepted": True, "duplicate": False}
            return result

    def cancel(self, run_id):
        with self.lock:
            run = self.runs.get(run_id)
            if not run:
                return None
            if run["state"]["status"] not in TERMINAL:
                run["cancel"].set()
                run["advance"].set()
                if run["state"]["attempts"] and run["state"]["attempts"][-1]["status"] == "running":
                    run["state"]["attempts"][-1].update(status="cancelled", error={"type": "Cancelled", "message": "Run cancelled by the user.", "line": None})
                self._finish(run, "cancelled")
                self._event(run, "done", "Run cancelled by the user.")
                connection = run["connection"]
            else:
                connection = None
        if connection:
            threading.Thread(target=connection.close, daemon=True).start()
        return self.snapshot(run_id)

    def _event(self, run, phase, message, attempt=None, kind="phase"):
        with self.lock:
            if run["cancel"].is_set() and phase != "done":
                return
            run["state"]["phase"] = phase
            run["state"]["events"].append({"phase": phase, "message": message, "time": timestamp(), "attempt": attempt, "kind": kind, "sequence": len(run["state"]["events"]) + 1})

    def _gate(self, run, phase, message, attempt):
        with self.lock:
            if run["cancel"].is_set():
                return False
            state = run["state"]
            state["step_sequence"] += 1
            sequence = state["step_sequence"]
            manual = state["control_mode"] == "manual"
            run["advance"].clear()
            state.update(phase=phase, phase_status="waiting" if manual else "running", awaiting_step=manual, next_phase=phase if manual else None, next_attempt=attempt if manual else None, step_token=f"{state['id']}:{sequence}" if manual else None)
            stage = {"sequence": sequence, "phase": phase, "attempt": attempt, "status": "waiting" if manual else "running", "ready_at": timestamp(), "started_at": None, "finished_at": None, "duration_ms": 0}
            state["stage_history"].append(stage)
            self._event(run, phase, "Ready for Next stage. " + message if manual else message, attempt, "stage_ready" if manual else "stage_started")
            if manual:
                run["wait_start"] = time.monotonic()
        if manual:
            while not run["advance"].wait(0.15):
                if run["cancel"].is_set():
                    return False
        with self.lock:
            if run["cancel"].is_set():
                return False
            if run["wait_start"] is not None:
                state["metrics"]["waiting_ms"] += round((time.monotonic() - run["wait_start"]) * 1000)
                run["wait_start"] = None
            state.update(awaiting_step=False, next_phase=None, next_attempt=None, step_token=None, phase_status="running")
            stage.update(status="running", started_at=timestamp())
            run["stage_start"] = time.monotonic()
            if manual:
                self._event(run, phase, message, attempt, "stage_started")
            return True

    def _complete_stage(self, run, phase, message, attempt):
        with self.lock:
            if run["cancel"].is_set():
                return
            state = run["state"]
            state["phase_status"] = "complete"
            if state["stage_history"]:
                state["stage_history"][-1].update(status="complete", finished_at=timestamp(), duration_ms=round((time.monotonic() - (run["stage_start"] or time.monotonic())) * 1000))
            self._event(run, phase, message, attempt, "stage_completed")

    def _finish(self, run, status):
        with self.lock:
            state = run["state"]
            if state["status"] == "cancelled" and status != "cancelled":
                return
            if run["wait_start"] is not None:
                state["metrics"]["waiting_ms"] += round((time.monotonic() - run["wait_start"]) * 1000)
                run["wait_start"] = None
            state.update(status=status, phase="done", phase_status="complete", finished_at=timestamp(), awaiting_step=False, next_phase=None, next_attempt=None, step_token=None)
            if state["stage_history"] and state["stage_history"][-1]["status"] in {"waiting", "running"}:
                state["stage_history"][-1].update(status=status, finished_at=timestamp())
            state["metrics"]["duration_ms"] = round((time.monotonic() - run["start"]) * 1000)

    def _connection(self, run, value):
        with self.lock:
            run["connection"] = value

    def _generation_progress(self, run, attempt, chunk, kind="generation"):
        if isinstance(chunk, dict):
            chunk = chunk.get("text", "")
        if not isinstance(chunk, str):
            return
        with self.lock:
            if run["cancel"].is_set():
                return
            attempt["generation_output"] = (attempt["generation_output"] + chunk)[:26000]
            run["state"]["generation_output"] = attempt["generation_output"]

    def _generate(self, run, previous, feedback, attempt):
        state = run["state"]
        kwargs = {"previous": previous, "feedback": feedback, "cancel_event": run["cancel"], "connection_callback": lambda value: self._connection(run, value)}
        parameters = inspect.signature(self.generator).parameters
        accepts_extra = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values())
        optional = {"provider": state["provider"], "progress_callback": lambda chunk, kind="generation": self._generation_progress(run, attempt, chunk, kind)}
        kwargs.update({key: value for key, value in optional.items() if accepts_extra or key in parameters})
        return self.generator(state["model"], state["task"], run["data"], **kwargs)

    def _execution_progress(self, run, attempt, observation):
        with self.lock:
            attempt.update(observation)

    def _feedback(self, attempt):
        validation = attempt["validation"] or {}
        return {"attempt": attempt["number"], "error": attempt["error"], "execution": {"exit_code": attempt["returncode"], "stdout": compact_output(attempt["stdout"], 1200), "stderr": compact_output(attempt["stderr"], 1800), "duration_ms": attempt["duration_ms"]}, "validation": {"passed": validation.get("passed", False), "kind": validation.get("kind"), "message": validation.get("message"), "mismatches": validation.get("mismatches", []), "actual": validation.get("actual")}, "suggestion": "Correct the precise exception or semantic mismatch. Compute the result from DATA, respect all task rules, and print one JSON object. Return complete corrected Python source."}

    def _work(self, run_id):
        with self.lock:
            run = self.runs[run_id]
        try:
            self._run_loop(run)
        finally:
            with self.lock:
                run["worker_done"] = True

    def _run_loop(self, run):
        state = run["state"]
        with self.lock:
            if run["cancel"].is_set():
                return
            state["status"] = "running"
        preset = PRESETS.get(state["preset_id"])
        previous = feedback = None
        try:
            for number in range(1, state["max_attempts"] + 1):
                seeded = number == 1 and bool(preset) and (state["seed_failure"] or state["mode"] == "replay")
                message = "Loading the declared controlled first failure." if seeded else "Generating a repaired candidate." if previous else "Generating the first candidate."
                if not self._gate(run, "generate", message, number):
                    return
                attempt = {"number": number, "code": "", "reflection": "", "status": "running", "stdout": "", "stderr": "", "returncode": None, "duration_ms": 0, "generation_ms": 0, "generation_output": "", "error": None, "feedback": None, "validation": None, "seeded": seeded, "exec_steps": [], "trace_enabled": state["trace_execution"], "trace_truncated": False}
                with self.lock:
                    state["attempts"].append(attempt)
                    state["generation_output"] = ""
                    state["metrics"].update(attempts=number, repairs=number - 1)
                if seeded:
                    candidate = {"code": preset["seed_code"], "reflection": "Declared controlled fault. This first candidate is prewritten, not model generated.", "duration_ms": 0}
                elif state["mode"] == "replay":
                    candidate = {"code": preset["replay_code"], "reflection": {"sales": "Parse numeric strings, reject invalid rows, retain signed adjustments and aggregate before ranking.", "text": "Use lower() and alphabetic tokenization, then count and sort deterministically.", "grades": "Apply the assessment weights before classifying and averaging scores."}[state["preset_id"]], "duration_ms": 0}
                else:
                    candidate = self._generate(run, previous, feedback, attempt)
                if run["cancel"].is_set():
                    return
                with self.lock:
                    attempt.update(code=candidate["code"], reflection=candidate["reflection"], generation_ms=candidate.get("duration_ms", 0))
                    state["metrics"]["generation_ms"] += candidate.get("duration_ms", 0)
                self._complete_stage(run, "generate", "Complete candidate source is ready for inspection.", number)
                if not self._gate(run, "execute", "Executing in a constrained temporary Python subprocess.", number):
                    return
                execution = execute_code(candidate["code"], run["data"], state["timeout"], run["cancel"], trace_execution=state["trace_execution"], progress_callback=lambda observation: self._execution_progress(run, attempt, observation))
                with self.lock:
                    attempt.update({key: execution[key] for key in ("stdout", "stderr", "returncode", "duration_ms", "error", "job_limit_active", "exec_steps", "trace_enabled", "trace_truncated", "execution_observation")})
                    state["metrics"]["execution_ms"] += execution["duration_ms"]
                    if run["cancel"].is_set():
                        attempt["status"] = "cancelled"
                        return
                self._complete_stage(run, "execute", "Execution finished. Captured streams and source observations are available.", number)
                if not self._gate(run, "evaluate", "Checking the independent preset reference." if preset else "Checking structure only; custom domain correctness has no independent oracle.", number):
                    return
                validation = {"passed": False, "kind": "execution", "message": "Execution or JSON parsing failed.", "actual": None} if execution["error"] else validate_result(execution["output"], state["preset_id"])
                with self.lock:
                    if run["cancel"].is_set():
                        return
                    attempt["validation"] = validation
                    attempt["status"] = "success" if validation["passed"] else "failed"
                    if not validation["passed"] and not attempt["error"]:
                        attempt["error"] = {"type": "ValidationError", "message": validation["message"], "line": None}
                self._complete_stage(run, "evaluate", validation["message"], number)
                if validation["passed"]:
                    with self.lock:
                        if run["cancel"].is_set():
                            return
                        state["result"] = execution["output"]
                        state["metrics"]["passed"] = True
                        self._finish(run, "succeeded")
                    self._event(run, "done", "Validation passed. The loop stopped immediately.", number)
                    return
                if not self._gate(run, "reflect", "Preparing concise execution and contract feedback for the next candidate.", number):
                    return
                feedback = self._feedback(attempt)
                with self.lock:
                    attempt["feedback"] = feedback
                error = attempt["error"]
                detail = error["type"] + (f" on line {error['line']}" if error.get("line") else "") + ": " + error["message"]
                self._complete_stage(run, "reflect", "Failure evidence prepared: " + detail[:450], number)
                previous = candidate["code"]
            self._finish(run, "exhausted")
            self._event(run, "done", f"Attempt limit ({state['max_attempts']}) reached. No further execution.")
        except ProviderError as exc:
            if run["cancel"].is_set():
                return
            with self.lock:
                if state["attempts"]:
                    state["attempts"][-1].update(status="failed", error={"type": "ProviderError", "message": str(exc), "line": None})
            self._finish(run, "provider_error")
            self._event(run, "done", "Model request failed: " + str(exc)[:500])
        except Exception as exc:
            if run["cancel"].is_set():
                return
            with self.lock:
                if state["attempts"]:
                    state["attempts"][-1].update(status="failed", error={"type": "InternalError", "message": f"{type(exc).__name__}: {str(exc)[:300]}", "line": None})
            self._finish(run, "provider_error")
            self._event(run, "done", f"Run stopped after an internal error: {type(exc).__name__}: {str(exc)[:300]}")
