"""Observable, bounded generate/execute/evaluate/reflect state machine."""
import copy
from datetime import datetime, timezone
import json
import threading
import time
import uuid

from .executor import compact_output, execute_code
from .presets import PRESETS, validate_result
from .provider import DEFAULT_MODEL, ProviderError, generate

TERMINAL = {"succeeded", "exhausted", "cancelled", "provider_error"}


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class RunManager:
    def __init__(self, generator=generate):
        self.generator = generator
        self.runs = {}
        self.lock = threading.RLock()

    def create(self, config):
        if not isinstance(config, dict):
            raise ValueError("Request body must be a JSON object.")
        preset_id = config.get("preset_id", "sales")
        if preset_id == "custom" or preset_id is None:
            preset_id = ""
        if preset_id and preset_id not in PRESETS:
            raise ValueError("Unknown preset.")
        preset = PRESETS.get(preset_id)
        task = preset["prompt"] if preset else str(config.get("task", "")).strip()
        if not task or len(task) > 5000:
            raise ValueError("Task must contain 1–5000 characters.")
        mode = config.get("mode", "live")
        if mode not in {"live", "replay"}:
            raise ValueError("Mode must be live or replay.")
        if mode == "replay" and not preset:
            raise ValueError("Scripted replay is available only for the three verified presets.")
        try:
            attempts = config.get("max_attempts", 5)
            if not isinstance(attempts, int) or isinstance(attempts, bool):
                raise ValueError("Attempt count must be an integer.")
            timeout = float(config.get("timeout", 5))
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Invalid attempt count or timeout.") from None
        if not 1 <= attempts <= 5 or not 1 <= timeout <= 5:
            raise ValueError("Attempt count and execution timeout must be between 1 and 5.")
        model = str(config.get("model") or DEFAULT_MODEL)
        if len(model) > 150 or any(c in model for c in "\n\r\x00"):
            raise ValueError("Invalid model name.")
        seed = config.get("seed_failure", False)
        if not isinstance(seed, bool):
            raise ValueError("seed_failure must be true or false.")
        if seed and not preset:
            raise ValueError("A controlled first failure is available only for verified presets.")
        with self.lock:
            # Cancellation changes UI status immediately, but the generator may
            # still be unwinding. Keep its capacity slot until worker cleanup.
            if sum(not run["worker_done"] for run in self.runs.values()) >= 2:
                raise ValueError("Two run workers are still active. Wait for a run to finish or finish cancelling.")
            if len(self.runs) >= 40:
                old = next((key for key, run in self.runs.items() if run["worker_done"] and run["state"]["status"] in TERMINAL), None)
                if old:
                    del self.runs[old]
            run_id = uuid.uuid4().hex[:16]
            state = {"id": run_id, "status": "queued", "phase": "generate", "task": task, "preset_id": preset_id, "mode": mode, "model": model if mode == "live" else "scripted-replay", "max_attempts": attempts, "timeout": timeout, "seed_failure": seed, "attempts": [], "events": [], "result": None, "started_at": timestamp(), "finished_at": None, "metrics": {"attempts": 0, "repairs": 0, "passed": False, "duration_ms": 0}, "validation_kind": "semantic" if preset else "structural", "notice": "Scripted replay uses predetermined code; it does not demonstrate model intelligence." if mode == "replay" else "Live local Ollama generation. Controlled first failure is explicitly labelled if enabled."}
            run = {"state": state, "cancel": threading.Event(), "connection": None, "worker_done": False, "start": time.monotonic(), "data": copy.deepcopy(preset["data"] if preset else {})}
            self.runs[run_id] = run
            thread = threading.Thread(target=self._work, args=(run_id,), daemon=True, name=f"autoheal-{run_id}")
            thread.start()
            return run_id

    def snapshot(self, run_id):
        with self.lock:
            run = self.runs.get(run_id)
            if not run:
                return None
            result = copy.deepcopy(run["state"])
            result["metrics"]["duration_ms"] = round((time.monotonic() - run["start"]) * 1000) if result["status"] not in TERMINAL else result["metrics"]["duration_ms"]
            return result

    def cancel(self, run_id):
        with self.lock:
            run = self.runs.get(run_id)
            if not run:
                return None
            if run["state"]["status"] not in TERMINAL:
                run["cancel"].set()
                if run["state"]["attempts"] and run["state"]["attempts"][-1]["status"] == "running":
                    run["state"]["attempts"][-1].update(status="cancelled", error={"type": "Cancelled", "message": "Run cancelled by the user.", "line": None})
                self._finish(run, "cancelled")
                self._event(run, "done", "Run cancelled by the user.")
                connection = run["connection"]
            else:
                connection = None
        if connection:
            # Closing a blocking stream is moved off the HTTP/UI thread.
            threading.Thread(target=connection.close, daemon=True).start()
        return self.snapshot(run_id)

    def _event(self, run, phase, message, attempt=None):
        with self.lock:
            if run["cancel"].is_set() and phase != "done":
                return
            run["state"]["phase"] = phase
            run["state"]["events"].append({"phase": phase, "message": message, "time": timestamp(), "attempt": attempt})

    def _finish(self, run, status):
        with self.lock:
            if run["state"]["status"] == "cancelled" and status != "cancelled":
                return
            run["state"].update(status=status, phase="done", finished_at=timestamp())
            run["state"]["metrics"]["duration_ms"] = round((time.monotonic() - run["start"]) * 1000)

    def _connection(self, run, value):
        with self.lock:
            run["connection"] = value

    def _feedback(self, attempt):
        validation = attempt["validation"] or {}
        return {
            "attempt": attempt["number"],
            "error": attempt["error"],
            "execution": {"exit_code": attempt["returncode"], "stdout": compact_output(attempt["stdout"], 1200), "stderr": compact_output(attempt["stderr"], 1800), "duration_ms": attempt["duration_ms"]},
            "validation": {"passed": validation.get("passed", False), "kind": validation.get("kind"), "message": validation.get("message"), "mismatches": validation.get("mismatches", []), "actual": validation.get("actual")},
            "suggestion": "Correct the precise exception or semantic mismatch. Compute the result from DATA, respect all task rules, and print one JSON object. The next candidate must be complete Python source.",
        }

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
                if run["cancel"].is_set():
                    return
                seeded = number == 1 and bool(preset) and (state["seed_failure"] or state["mode"] == "replay")
                self._event(run, "generate", "Using declared controlled first failure." if seeded else "Generating a complete candidate." if state["mode"] == "live" else "Loading the predetermined repaired candidate for scripted replay.", number)
                attempt = {"number": number, "code": "", "reflection": "", "status": "running", "stdout": "", "stderr": "", "returncode": None, "duration_ms": 0, "generation_ms": 0, "error": None, "feedback": None, "validation": None, "seeded": seeded}
                with self.lock:
                    state["attempts"].append(attempt)
                    state["metrics"]["attempts"] = number
                    state["metrics"]["repairs"] = number - 1
                if seeded:
                    candidate = {"code": preset["seed_code"], "reflection": "Controlled fault injected by the user-selected demonstration scenario. This candidate was not generated by the model.", "duration_ms": 0}
                elif state["mode"] == "replay":
                    candidate = {"code": preset["replay_code"], "reflection": {"sales": "The failed sum used strings. Parse valid numeric amounts, reject empty or invalid values, and aggregate by region.", "text": "The failed program called lowercase(), which does not exist. Use lower() and a letter-only regular expression before counting.", "grades": "The first candidate used a simple mean. Apply the required 20%, 30%, and 50% weights before classification and averaging."}[state["preset_id"]], "duration_ms": 0}
                else:
                    candidate = self.generator(state["model"], state["task"], run["data"], previous=previous, feedback=feedback, cancel_event=run["cancel"], connection_callback=lambda value: self._connection(run, value))
                if run["cancel"].is_set():
                    return
                with self.lock:
                    attempt.update(code=candidate["code"], reflection=candidate["reflection"], generation_ms=candidate.get("duration_ms", 0))
                self._event(run, "execute", "Executing in a constrained temporary Python subprocess.", number)
                execution = execute_code(candidate["code"], run["data"], state["timeout"], run["cancel"])
                if run["cancel"].is_set():
                    with self.lock:
                        attempt.update(status="cancelled", error=execution["error"])
                    return
                with self.lock:
                    attempt.update({key: execution[key] for key in ("stdout", "stderr", "returncode", "duration_ms", "error", "job_limit_active")})
                self._event(run, "evaluate", "Checking executable output against the independent reference." if preset else "Checking that output is a non-empty JSON object; custom correctness is not independently verified.", number)
                if execution["error"]:
                    validation = {"passed": False, "kind": "execution", "message": "Execution or JSON parsing failed.", "actual": None}
                else:
                    validation = validate_result(execution["output"], state["preset_id"])
                with self.lock:
                    if run["cancel"].is_set():
                        return
                    attempt["validation"] = validation
                    attempt["status"] = "success" if validation["passed"] else "failed"
                    if not validation["passed"] and not attempt["error"]:
                        attempt["error"] = {"type": "ValidationError", "message": validation["message"], "line": None}
                if validation["passed"]:
                    with self.lock:
                        if run["cancel"].is_set():
                            return
                        state["result"] = execution["output"]
                        state["metrics"]["passed"] = True
                        self._finish(run, "succeeded")
                    self._event(run, "done", "Validation passed. The loop stopped immediately.", number)
                    return
                feedback = self._feedback(attempt)
                with self.lock:
                    attempt["feedback"] = feedback
                error = attempt["error"]
                detail = f"{error['type']}" + (f" on line {error['line']}" if error.get("line") else "") + f": {error['message']}"
                self._event(run, "reflect", "Failure evidence prepared: " + detail[:450], number)
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
            self._event(run, "done", "Local model request failed: " + str(exc)[:500])
        except Exception as exc:
            if run["cancel"].is_set():
                return
            self._finish(run, "provider_error")
            self._event(run, "done", f"Run stopped after an internal error: {type(exc).__name__}: {str(exc)[:300]}")
