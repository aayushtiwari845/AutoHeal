"""Behavioral regression tests for real observations and manual phase control."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from http.server import ThreadingHTTPServer
import threading
import time
import unittest
from unittest.mock import patch

from autoheal.engine import AdvanceConflict, RunManager, TERMINAL
from autoheal.executor import MAX_TRACE_BYTES, MAX_TRACE_STEPS, execute_code
from autoheal.presets import PRESETS, public_presets
from autoheal.server import Handler


def wait_for(manager, run_id, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = manager.snapshot(run_id)
        if predicate(snapshot):
            return snapshot
        time.sleep(0.01)
    raise AssertionError("Expected state was not reached: " + json.dumps(manager.snapshot(run_id)))


class ObservationTests(unittest.TestCase):
    def test_preloaded_data_cannot_be_rebound_but_read_aliases_are_allowed(self):
        for source in ["DATA = []", "DATA += [1]", "del DATA", "for DATA in [1]:\n    pass", "values = [DATA for DATA in [1, 2]]", "import math as DATA", "def f(DATA):\n    return DATA"]:
            with self.subTest(source=source):
                result = execute_code(source, [2, 3])
                self.assertEqual(result["error"]["type"], "CodePolicyError")
                self.assertIn("cannot be rebound", result["error"]["message"])
                self.assertIsNone(result["returncode"])
                self.assertIsInstance(result["error"]["line"], int)
        result = execute_code("data = DATA\nprint(json.dumps({'sum': sum(data)}))", [2, 3])
        self.assertIsNone(result["error"])
        self.assertEqual(result["output"], {"sum": 5})

    def test_real_trace_records_locals_before_each_source_line(self):
        result = execute_code("x = 2\ny = x + 3\nprint(json.dumps({'total': y}))", {})
        self.assertIsNone(result["error"])
        self.assertEqual(result["output"], {"total": 5})
        lines = [step for step in result["exec_steps"] if step["event"] == "line"]
        self.assertEqual([step["line"] for step in lines], [1, 2, 3])
        self.assertNotIn("x", lines[0]["locals"])
        self.assertEqual(lines[1]["locals"], {"x": 2})
        self.assertEqual(lines[2]["locals"], {"x": 2, "y": 5})
        self.assertEqual(result["stderr"], "")
        self.assertFalse(result["trace_truncated"])

    def test_exception_trace_has_actual_location_and_prior_values(self):
        result = execute_code("dividend = 8\ndivisor = 0\nanswer = dividend / divisor", {})
        step = next(step for step in result["exec_steps"] if step["event"] == "exception")
        self.assertEqual(step["line"], 3)
        self.assertEqual(step["exception"]["type"], "ZeroDivisionError")
        self.assertEqual(step["locals"], {"dividend": 8, "divisor": 0})
        self.assertEqual(result["error"]["line"], 3)
        self.assertNotIn("AUTOHEAL_", result["stderr"])
        self.assertIn("ZeroDivisionError", result["stderr"])

    def test_trace_limits_never_change_actual_program_result(self):
        source = "total = 0\nfor number in range(2000):\n    total += number\nprint(json.dumps({'total': total}))"
        result = execute_code(source, {})
        self.assertIsNone(result["error"])
        self.assertEqual(result["output"], {"total": 1999000})
        self.assertLessEqual(len(result["exec_steps"]), MAX_TRACE_STEPS)
        self.assertLessEqual(sum(len(json.dumps(step, ensure_ascii=True)) for step in result["exec_steps"]), MAX_TRACE_BYTES)
        self.assertTrue(result["trace_truncated"])

    def test_trace_bytes_are_bounded_independently_of_step_count(self):
        source = "values = ['x' * 400] * 100\nfor number in range(60):\n    copied = values[:]\nprint(json.dumps({'size': len(copied)}))"
        result = execute_code(source, {})
        self.assertIsNone(result["error"])
        self.assertTrue(result["trace_truncated"])
        self.assertLess(len(result["exec_steps"]), MAX_TRACE_STEPS)
        self.assertLessEqual(sum(len(json.dumps(step, ensure_ascii=True)) for step in result["exec_steps"]), MAX_TRACE_BYTES)

    def test_sensitive_names_and_data_are_excluded_from_local_snapshots(self):
        source = "api_key = 'private-value'\ninfo = {'password': 'hidden', 'public': 'visible'}\nvalues = [[['deep']]]\nlarge = 2 ** 1000\nnonfinite = float('inf')\nprint(json.dumps({'ok': True}))"
        result = execute_code(source, {"private": "input data is separate"})
        self.assertIsNone(result["error"])
        snapshot = result["exec_steps"][-1]["locals"]
        self.assertEqual(snapshot["api_key"], "<redacted>")
        self.assertEqual(snapshot["info"]["password"], "<redacted>")
        self.assertEqual(snapshot["info"]["public"], "visible")
        self.assertEqual(snapshot["large"], "<large integer>")
        self.assertEqual(snapshot["nonfinite"], "<non-finite number>")
        self.assertNotIn("DATA", snapshot)
        self.assertNotIn("json", snapshot)
        self.assertNotIn("private-value", json.dumps(snapshot))
        json.dumps(result, allow_nan=False)

    def test_trace_can_be_disabled_and_cannot_be_spoofed_by_stderr_like_stdout(self):
        result = execute_code("print(json.dumps({'text': 'AUTOHEAL_fake: trace'}))", {}, trace_execution=False)
        self.assertIsNone(result["error"])
        self.assertFalse(result["trace_enabled"])
        self.assertEqual(result["exec_steps"], [])
        self.assertEqual(result["output"]["text"], "AUTOHEAL_fake: trace")

    def test_execution_observers_receive_real_output_before_timeout_finishes(self):
        observed = threading.Event()
        finished = threading.Event()
        before_finish = []
        result = {}
        def callback(item):
            if item["stdout"] and item["exec_steps"]:
                before_finish.append(not finished.is_set())
                observed.set()
        def worker():
            result.update(execute_code("print('{}')\nwhile True:\n    pass", {}, timeout=2, progress_callback=callback))
            finished.set()
        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(observed.wait(1.5), "No actual stream observation arrived while the child was running.")
        self.assertFalse(finished.is_set())
        thread.join(4)
        self.assertTrue(all(before_finish))
        self.assertEqual(result["error"]["type"], "TimeoutError")

    def test_observer_exception_does_not_break_execution(self):
        def broken(_):
            raise RuntimeError("Observer is unavailable")
        result = execute_code("print(json.dumps({'ok': True}))", {}, progress_callback=broken)
        self.assertIsNone(result["error"])
        self.assertEqual(result["output"], {"ok": True})


class ManualStageTests(unittest.TestCase):
    def test_manual_replay_requires_every_phase_and_stops_immediately_on_success(self):
        manager = RunManager()
        run_id = manager.create({"preset_id": "grades", "mode": "replay", "control_mode": "manual"})
        phases = []
        tokens = []
        for index in range(7):
            run = wait_for(manager, run_id, lambda item: item["awaiting_step"] or item["status"] in TERMINAL)
            self.assertTrue(run["awaiting_step"], run)
            phases.append(run["next_phase"])
            tokens.append(run["step_token"])
            if index == 1:
                self.assertTrue(run["attempts"][0]["code"])
                self.assertIsNone(run["attempts"][0]["returncode"])
                self.assertEqual(run["attempts"][0]["exec_steps"], [])
            if index == 2:
                self.assertEqual(run["attempts"][0]["returncode"], 0)
                self.assertIsNone(run["attempts"][0]["validation"])
                self.assertTrue(run["attempts"][0]["exec_steps"])
            if index == 3:
                self.assertEqual(run["attempts"][0]["error"]["type"], "ValidationError")
                self.assertIsNone(run["attempts"][0]["feedback"])
            self.assertTrue(manager.advance(run_id, run["step_token"])["advance"]["accepted"])
        run = wait_for(manager, run_id, lambda item: item["status"] in TERMINAL)
        self.assertEqual(phases, ["generate", "execute", "evaluate", "reflect", "generate", "execute", "evaluate"])
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(len(run["attempts"]), 2)
        self.assertEqual(run["step_sequence"], 7)
        self.assertTrue(all(stage["status"] == "complete" for stage in run["stage_history"]))
        self.assertFalse(run["awaiting_step"])
        self.assertIsNone(run["next_phase"])
        self.assertTrue(manager.advance(run_id, tokens[0])["advance"]["duplicate"])

    def test_duplicate_concurrent_advances_never_skip_the_next_gate(self):
        manager = RunManager()
        run_id = manager.create({"mode": "replay", "control_mode": "manual"})
        run = wait_for(manager, run_id, lambda item: item["awaiting_step"])
        token = run["step_token"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: manager.advance(run_id, token), range(2)))
        self.assertEqual(sum(item["advance"]["accepted"] for item in responses), 1)
        current = wait_for(manager, run_id, lambda item: item["awaiting_step"])
        self.assertEqual(current["next_phase"], "execute")
        self.assertEqual(current["step_sequence"], 2)
        manager.advance(run_id, token)
        self.assertEqual(manager.snapshot(run_id)["step_token"], current["step_token"])
        with self.assertRaises(AdvanceConflict):
            manager.advance(run_id, "wrong-token")
        self.assertEqual(manager.snapshot(run_id)["next_phase"], "execute")
        manager.cancel(run_id)

    def test_cancellation_wakes_waiting_worker_without_generating_any_code(self):
        calls = []
        def generator(*args, **kwargs):
            calls.append(True)
            raise AssertionError("A waiting manual stage must not generate.")
        manager = RunManager(generator)
        run_id = manager.create({"control_mode": "manual"})
        wait_for(manager, run_id, lambda item: item["awaiting_step"])
        self.assertEqual(manager.cancel(run_id)["status"], "cancelled")
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with manager.lock:
                if manager.runs[run_id]["worker_done"]:
                    break
            time.sleep(0.01)
        else:
            self.fail("Cancelled waiting worker did not clean up.")
        self.assertEqual(calls, [])
        self.assertFalse(manager.snapshot(run_id)["awaiting_step"])

    def test_custom_data_provider_and_real_generation_fragments_reach_trace(self):
        received = []
        def generator(model, task, data, provider, progress_callback, **kwargs):
            received.append((provider, data))
            progress_callback('{"code":', kind="content")
            progress_callback('"candidate"}', kind="content")
            return {"code": "print(json.dumps({'sum': sum(DATA)}))", "reflection": "Sum the supplied input.", "duration_ms": 12}
        manager = RunManager(generator)
        run_id = manager.create({"preset_id": "custom", "task": "Sum the input", "data": [4, 5], "provider": "api", "model": "configured-model"})
        run = wait_for(manager, run_id, lambda item: item["status"] in TERMINAL)
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["result"], {"sum": 9})
        self.assertEqual(received, [("api", [4, 5])])
        self.assertEqual(run["input_data"], [4, 5])
        self.assertEqual(run["generation_output"], '{"code":"candidate"}')
        self.assertEqual(run["validation_kind"], "structural")
        self.assertEqual(run["metrics"]["generation_ms"], 12)
        self.assertTrue(run["attempts"][0]["exec_steps"])

    def test_legacy_generator_signature_remains_compatible(self):
        def generator(model, task, data, previous=None, feedback=None, cancel_event=None, connection_callback=None):
            return {"code": PRESETS["grades"]["replay_code"], "reflection": "Weighted scores."}
        manager = RunManager(generator)
        run_id = manager.create({"preset_id": "grades"})
        self.assertEqual(wait_for(manager, run_id, lambda item: item["status"] in TERMINAL)["status"], "succeeded")

    def test_invalid_controls_nonfinite_or_excess_data_and_preset_edits_rejected(self):
        manager = RunManager()
        bad = [{"control_mode": "line-debugger"}, {"control_mode": []}, {"mode": {}}, {"provider": []}, {"provider": "other"}, {"trace_execution": "yes"}, {"preset_id": "custom", "task": "x", "data": {"x": float("inf")}}, {"preset_id": "custom", "task": "x", "data": "x" * 12001}, {"data": []}, {"api_key": "do-not-record"}]
        for config in bad:
            with self.subTest(config={key: value for key, value in config.items() if key != "data"}), self.assertRaises(ValueError):
                manager.create(config)

    def test_public_initial_code_is_explicitly_predeclared(self):
        item = next(item for item in public_presets() if item["id"] == "grades")
        self.assertEqual(item["seed_preview"]["code"], PRESETS["grades"]["seed_code"])
        self.assertIn("Prewritten", item["seed_preview"]["provenance"])
        self.assertNotIn("replay_code", item)


class AdvanceAPITests(unittest.TestCase):
    def test_http_advance_requires_exact_token_and_is_idempotent(self):
        manager = RunManager()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, payload):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
            connection.request("POST", path, json.dumps(payload), {"Content-Type": "application/json"})
            response = connection.getresponse()
            result = (response.status, json.loads(response.read()))
            connection.close()
            return result
        try:
            with patch("autoheal.server.MANAGER", manager):
                status, created = request("/api/runs", {"mode": "replay", "control_mode": "manual"})
                self.assertEqual(status, 202)
                run_id = created["run_id"]
                snapshot = wait_for(manager, run_id, lambda item: item["awaiting_step"])
                status, _ = request(f"/api/runs/{run_id}/advance", {"step_token": "wrong"})
                self.assertEqual(status, 409)
                body = {"step_token": snapshot["step_token"]}
                status, accepted = request(f"/api/runs/{run_id}/advance", body)
                self.assertEqual(status, 200)
                self.assertTrue(accepted["advance"]["accepted"])
                status, duplicate = request(f"/api/runs/{run_id}/advance", body)
                self.assertEqual(status, 200)
                self.assertTrue(duplicate["advance"]["duplicate"])
                request(f"/api/runs/{run_id}/cancel", {})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
