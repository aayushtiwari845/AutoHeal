import copy
from decimal import Decimal, ROUND_HALF_UP
import http.client
import json
import re
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from autoheal.engine import RunManager, TERMINAL
from autoheal.executor import compact_output, execute_code, inspect_code
from autoheal.presets import PRESETS, validate_result
from autoheal.provider import ProviderError
from autoheal.server import Handler


def finish(manager, run_id, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = manager.snapshot(run_id)
        if result["status"] in TERMINAL:
            return result
        time.sleep(0.02)
    raise AssertionError("Run did not finish within the test deadline.")


class ReferenceTests(unittest.TestCase):
    """Independently calculate targets; do not reuse candidate implementation."""

    def test_sales_reference(self):
        data = PRESETS["sales"]["data"]
        accepted = [(row["region"], Decimal(row["amount"].strip())) for row in data if row["amount"].strip() not in {"", "N/A"}]
        regions = {region: float(sum(value for candidate, value in accepted if candidate == region)) for region in {row["region"] for row in data}}
        expected = {"total": float(sum(value for _, value in accepted)), "valid_rows": len(accepted), "rejected_rows": len(data) - len(accepted), "by_region": regions, "top_region": min(regions, key=lambda key: (-regions[key], key))}
        self.assertEqual(PRESETS["sales"]["expected"], expected)

    def test_text_reference(self):
        words = re.findall("[a-z]+", " ".join(PRESETS["text"]["data"]).lower())
        counts = {word: words.count(word) for word in set(words)}
        expected = {"document_count": 3, "token_count": len(words), "unique_tokens": len(set(words)), "frequencies": counts, "top_tokens": [{"token": word, "count": counts[word]} for word in sorted(counts, key=lambda word: (-counts[word], word))[:3]]}
        self.assertEqual(PRESETS["text"]["expected"], expected)

    def test_grade_reference(self):
        raw = {row["name"]: sum(Decimal(score) * weight for score, weight in zip(row["scores"], map(Decimal, ["0.2", "0.3", "0.5"]))) for row in PRESETS["grades"]["data"]}
        expected = {"averages": {name: float(value) for name, value in raw.items()}, "class_average": float((sum(raw.values()) / 4).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)), "passed": sorted(name for name, score in raw.items() if score >= 60), "highest": max(raw, key=raw.get)}
        self.assertEqual(PRESETS["grades"]["expected"], expected)

    def test_semantic_validation_rejects_plausible_wrong_and_unrounded_outputs(self):
        wrong = copy.deepcopy(PRESETS["grades"]["expected"])
        wrong["class_average"] = 75.275
        self.assertFalse(validate_result(wrong, "grades")["passed"])
        wrong = copy.deepcopy(PRESETS["sales"]["expected"])
        wrong["total"] = 560
        self.assertFalse(validate_result(wrong, "sales")["passed"])

    def test_custom_validation_explicitly_only_structural(self):
        result = validate_result({"answer": "unverified"}, "")
        self.assertTrue(result["passed"])
        self.assertEqual(result["kind"], "structural")
        self.assertFalse(validate_result([], "")["passed"])

    def test_semantic_mismatch_identifies_exact_fields_without_answer(self):
        wrong = copy.deepcopy(PRESETS["grades"]["expected"])
        wrong["highest"] = "Asha"
        result = validate_result(wrong, "grades")
        self.assertEqual(len(result["mismatches"]), 1)
        self.assertEqual(result["mismatches"][0]["path"], "$.highest")
        self.assertEqual(result["mismatches"][0]["issue"], "value or type differs")
        self.assertIn("GREATEST", result["mismatches"][0]["rule"])
        self.assertNotIn("Mira", result["message"])
        self.assertNotIn("Mira", json.dumps(result["mismatches"]))

        # A real candidate can print valid JSON while preserving Counter pairs
        # as arrays instead of the task's required token/count objects.
        source = """import re
from collections import Counter
tokens = re.findall('[A-Za-z]+', ' '.join(DATA).lower())
counts = Counter(tokens)
ranking = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
print(json.dumps({
    'document_count': len(DATA),
    'token_count': len(tokens),
    'unique_tokens': len(counts),
    'frequencies': counts,
    'top_tokens': ranking,
}))"""
        execution = execute_code(source, PRESETS["text"]["data"])
        self.assertIsNone(execution["error"])
        self.assertEqual(execution["returncode"], 0)
        validation = validate_result(execution["output"], "text")
        self.assertFalse(validation["passed"])
        self.assertEqual(len(validation["mismatches"]), 3)
        for index, mismatch in enumerate(validation["mismatches"]):
            self.assertEqual(mismatch["path"], f"$.top_tokens[{index}]")
            self.assertEqual(mismatch["expected_type"], "object")
            self.assertEqual(mismatch["actual_type"], "array")
            self.assertNotIn("expected", mismatch)
            self.assertNotIn("actual", mismatch)
        serialized = json.dumps(validation["mismatches"])
        for answer in ('"code"', '"ai"', '"reliable"'):
            self.assertNotIn(answer, serialized)


class ExecutorTests(unittest.TestCase):
    def test_all_repaired_programs_execute_and_match(self):
        for key, preset in PRESETS.items():
            with self.subTest(key=key):
                result = execute_code(preset["replay_code"], preset["data"])
                self.assertIsNone(result["error"], result)
                self.assertEqual(result["returncode"], 0)
                self.assertTrue(validate_result(result["output"], key)["passed"])

    def test_exception_type_and_exact_line(self):
        result = execute_code("x = 1\ny = 0\nprint(x / y)", {})
        self.assertEqual(result["error"]["type"], "ZeroDivisionError")
        self.assertEqual(result["error"]["line"], 3)
        self.assertNotEqual(result["returncode"], 0)

    def test_syntax_location(self):
        result = execute_code("x = 1\nif True print(x)", {})
        self.assertEqual(result["error"]["type"], "SyntaxError")
        self.assertEqual(result["error"]["line"], 2)
        self.assertIsNone(result["returncode"])

    def test_infinite_loop_is_killed(self):
        started = time.monotonic()
        result = execute_code("while True:\n    pass", {}, timeout=1)
        self.assertEqual(result["error"]["type"], "TimeoutError")
        self.assertLess(time.monotonic() - started, 3)

    def test_output_flood_is_bounded(self):
        result = execute_code("for i in range(100000):\n    print('noise')", {}, timeout=2)
        self.assertIsNotNone(result["error"])
        self.assertLess(len(result["stdout"]), 16500)
        self.assertIn("repeated", result["stdout"])

    def test_file_network_process_and_introspection_denied(self):
        forbidden = ["open('secret.txt', 'w')", "import socket\nsocket.socket()", "import subprocess", "print(DATA.__class__)", "getattr(DATA, '__class__')", "import json as j\nprint(j.decoder)", "from statistics import sys", "x = json\nprint(x.codecs)", "print('{0.__class__}'.format(DATA))", "import os\nprint(os.environ)"]
        for source in forbidden:
            with self.subTest(source=source):
                result = execute_code(source, {})
                self.assertEqual(result["error"]["type"], "CodePolicyError")
                self.assertIsNone(result["returncode"])

    def test_json_contract_invalid_duplicates_nan_multiple_results(self):
        for source in ["print('hello')", "print('{\"a\":1,\"a\":2}')", "print('{\"a\":NaN}')", "print('{}')\nprint('{}')"]:
            with self.subTest(source=source):
                self.assertEqual(execute_code(source, {})["error"]["type"], "OutputFormatError")

    def test_nonfinite_json_exponents_are_rejected(self):
        for value in ("1e309", "-1e309"):
            with self.subTest(value=value):
                result = execute_code(f"print('{{\"nested\": [{{\"x\": {value}}}]}}')", {})
                self.assertEqual(result["returncode"], 0)
                self.assertEqual(result["error"]["type"], "OutputFormatError")
                self.assertIsNone(result["output"])

    def test_cancellation_kills_running_program(self):
        cancel = threading.Event()
        timer = threading.Timer(0.15, cancel.set)
        timer.start()
        result = execute_code("while True:\n    pass", {}, cancel_event=cancel)
        timer.join()
        self.assertEqual(result["error"]["type"], "Cancelled")

    def test_output_compacts_adjacent_repeats(self):
        self.assertIn("repeated 2 times", compact_output("a\na\na\nb"))


class LoopTests(unittest.TestCase):
    def test_replay_failure_then_success_for_all_scenarios(self):
        for preset_id in PRESETS:
            manager = RunManager()
            run = finish(manager, manager.create({"preset_id": preset_id, "mode": "replay"}))
            self.assertEqual(run["status"], "succeeded", run)
            self.assertEqual(len(run["attempts"]), 2)
            self.assertTrue(run["attempts"][0]["seeded"])
            self.assertFalse(run["attempts"][0]["validation"]["passed"])
            self.assertTrue(run["attempts"][1]["validation"]["passed"])
            self.assertIn("reflect", [event["phase"] for event in run["events"]])

    def test_stop_on_first_success_and_live_seed_is_sent_to_model(self):
        calls = []
        def generator(model, task, data, **kwargs):
            calls.append(kwargs)
            return {"code": PRESETS["sales"]["replay_code"], "reflection": "Converted dirty strings to numbers."}
        manager = RunManager(generator)
        clean = finish(manager, manager.create({"preset_id": "sales", "mode": "live"}))
        self.assertEqual(len(clean["attempts"]), 1)
        repaired = finish(manager, manager.create({"preset_id": "sales", "mode": "live", "seed_failure": True}))
        self.assertEqual(len(repaired["attempts"]), 2)
        self.assertEqual(calls[-1]["feedback"]["error"]["type"], "TypeError")
        self.assertEqual(calls[-1]["feedback"]["error"]["line"], 1)
        self.assertEqual(calls[-1]["previous"], PRESETS["sales"]["seed_code"])

    def test_exhaustion_never_exceeds_five(self):
        def broken(*args, **kwargs):
            return {"code": "print(1 / 0)", "reflection": "Still broken."}
        manager = RunManager(broken)
        run = finish(manager, manager.create({"mode": "live", "max_attempts": 5}))
        self.assertEqual(run["status"], "exhausted")
        self.assertEqual(len(run["attempts"]), 5)

    def test_single_attempt_replay_exhausts(self):
        manager = RunManager()
        run = finish(manager, manager.create({"mode": "replay", "max_attempts": 1}))
        self.assertEqual(run["status"], "exhausted")
        self.assertEqual(len(run["attempts"]), 1)

    def test_provider_error_does_not_fake_success(self):
        def broken(*args, **kwargs):
            raise ProviderError("Model unavailable")
        manager = RunManager(broken)
        run = finish(manager, manager.create({"mode": "live"}))
        self.assertEqual(run["status"], "provider_error")
        self.assertFalse(run["metrics"]["passed"])
        self.assertIsNone(run["result"])

    def test_cancelled_status_wins_over_delayed_model_result(self):
        entered = threading.Event()
        released = threading.Event()
        def slow(*args, **kwargs):
            entered.set()
            released.wait(2)
            return {"code": PRESETS["sales"]["replay_code"], "reflection": "Late candidate."}
        manager = RunManager(slow)
        run_id = manager.create({"mode": "live"})
        self.assertTrue(entered.wait(2))
        self.assertEqual(manager.cancel(run_id)["status"], "cancelled")
        released.set()
        time.sleep(0.1)
        self.assertEqual(manager.snapshot(run_id)["status"], "cancelled")
        self.assertIsNone(manager.snapshot(run_id)["result"])

    def test_cancelled_generators_keep_capacity_until_their_workers_exit(self):
        entered = [threading.Event(), threading.Event()]
        release = threading.Event()
        counter_lock = threading.Lock()
        calls = []
        def blocked(*args, **kwargs):
            with counter_lock:
                index = len(calls)
                calls.append(index)
            if index < 2:
                entered[index].set()
                release.wait(3)
            return {"code": PRESETS["sales"]["replay_code"], "reflection": "Candidate."}
        manager = RunManager(blocked)
        try:
            for event in entered:
                run_id = manager.create({"mode": "live"})
                self.assertTrue(event.wait(2))
                self.assertEqual(manager.cancel(run_id)["status"], "cancelled")
            with self.assertRaises(ValueError):
                manager.create({"mode": "live"})
            self.assertEqual(len(calls), 2)
        finally:
            release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with manager.lock:
                if all(run["worker_done"] for run in manager.runs.values()):
                    break
            time.sleep(.01)
        else:
            self.fail("Cancelled workers did not release their capacity slots.")
        fresh = finish(manager, manager.create({"mode": "live"}))
        self.assertEqual(fresh["status"], "succeeded")

    def test_cancel_before_worker_start_releases_capacity_after_cleanup(self):
        generator = unittest.mock.Mock(return_value={"code": PRESETS["sales"]["replay_code"], "reflection": "Candidate."})
        manager = RunManager(generator)
        # Hold worker startup to exercise cancellation of a genuinely queued run.
        with patch("autoheal.engine.threading.Thread.start"):
            queued = [manager.create({"mode": "live"}) for _ in range(2)]
            for run_id in queued:
                self.assertEqual(manager.cancel(run_id)["status"], "cancelled")
            with self.assertRaises(ValueError):
                manager.create({"mode": "live"})
            for run_id in queued:
                manager._work(run_id)
            generator.assert_not_called()
            fresh_id = manager.create({"mode": "live"})
        manager._work(fresh_id)
        self.assertEqual(manager.snapshot(fresh_id)["status"], "succeeded")

    def test_history_eviction_preserves_cancelled_unfinished_worker(self):
        entered = threading.Event()
        release = threading.Event()
        def provider(*args, **kwargs):
            if not entered.is_set():
                entered.set()
                release.wait(3)
                return {"code": PRESETS["sales"]["replay_code"], "reflection": "Late result."}
            raise ProviderError("Immediate completed failure")
        manager = RunManager(provider)
        first_id = manager.create({"mode": "live"})
        self.assertTrue(entered.wait(2))
        manager.cancel(first_id)
        try:
            for _ in range(40):
                run_id = manager.create({"mode": "live"})
                self.assertEqual(finish(manager, run_id)["status"], "provider_error")
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    with manager.lock:
                        if manager.runs[run_id]["worker_done"]:
                            break
                    time.sleep(.01)
                else:
                    self.fail("Completed provider worker did not release its slot.")
            with manager.lock:
                self.assertIn(first_id, manager.runs)
                self.assertEqual(len(manager.runs), 40)
                self.assertFalse(manager.runs[first_id]["worker_done"])
        finally:
            release.set()

    def test_custom_exponent_overflow_never_poisons_trace_exports(self):
        def overflow(*args, **kwargs):
            return {"code": "print('{\"x\":1e309}')", "reflection": "Overflowed number."}
        manager = RunManager(overflow)
        run = finish(manager, manager.create({"preset_id": "custom", "task": "Return a numeric result", "mode": "live", "max_attempts": 1}))
        self.assertEqual(run["status"], "exhausted")
        self.assertEqual(run["attempts"][0]["error"]["type"], "OutputFormatError")
        self.assertIsNone(run["result"])
        json.dumps(run, allow_nan=False)

    def test_invalid_configuration_rejected(self):
        manager = RunManager()
        for config in [{"max_attempts": 6}, {"max_attempts": 1.5}, {"max_attempts": True}, {"timeout": 6}, {"timeout": "NaN"}, {"mode": "fake"}, {"preset_id": "unknown"}, {"preset_id": "custom", "task": "x", "mode": "replay"}]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                manager.create(config)

    def test_semantic_feedback_contains_fields_and_never_reference_answers(self):
        calls = []
        def generator(model, task, data, **kwargs):
            calls.append(kwargs)
            return {"code": PRESETS["grades"]["replay_code"], "reflection": "Applied assessment weights."}
        manager = RunManager(generator)
        run = finish(manager, manager.create({"preset_id": "grades", "mode": "live", "seed_failure": True}))
        self.assertEqual(run["status"], "succeeded")
        feedback = calls[0]["feedback"]
        self.assertTrue(feedback["validation"]["mismatches"])
        self.assertNotIn("expected", feedback["validation"])
        self.assertNotIn('"expected"', json.dumps(feedback))
        self.assertIn("greatest", run["task"])


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        status = response.status
        payload = json.loads(response.read())
        connection.close()
        return status, payload

    def test_status_service_identity(self):
        with patch("autoheal.server.ollama_status", return_value={"ollama_available": True, "models": [], "default_model": "qwen2.5-coder:7b"}):
            status, data = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(data["service"], "autoheal-studio")

    def test_cross_origin_mutation_is_denied(self):
        for _ in range(5):
            status, _ = self.request("POST", "/api/runs", "{}", {"Content-Type": "application/json", "Origin": "https://attacker.example"})
            self.assertEqual(status, 403)

    def test_simple_form_post_is_denied(self):
        for _ in range(5):
            status, _ = self.request("POST", "/api/runs", "{" + "x" * 2048 + "}", {"Content-Type": "text/plain"})
            self.assertEqual(status, 415)
        # A declared but incomplete rejected body must not prevent a response.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.putrequest("POST", "/api/runs")
            connection.putheader("Content-Type", "text/plain")
            connection.putheader("Content-Length", "10")
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 415)
            response.read()
        finally:
            connection.close()

    def test_rebinding_host_is_denied(self):
        status, _ = self.request("GET", "/api/presets", headers={"Host": "attacker.example"})
        self.assertEqual(status, 403)
        for _ in range(5):
            status, _ = self.request("POST", "/api/runs", "{}", {"Host": "attacker.example", "Content-Type": "application/json"})
            self.assertEqual(status, 403)

    def test_presets_exclude_replay_sources(self):
        status, data = self.request("GET", "/api/presets")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["presets"]), 3)
        self.assertNotIn("replay_code", data["presets"][0])


if __name__ == "__main__":
    unittest.main()
