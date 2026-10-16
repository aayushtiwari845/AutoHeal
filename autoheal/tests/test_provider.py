import io
import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from autoheal import provider


class Response(io.BytesIO):
    def __init__(self, value, content_type="application/x-ndjson"):
        super().__init__(value)
        self.headers = {"Content-Type": content_type}


class ProviderTests(unittest.TestCase):
    def test_catalog_never_exposes_api_secret(self):
        with patch.dict(os.environ, {"AUTOHEAL_API_KEY": "private-test-secret", "AUTOHEAL_API_MODEL": "test-model"}):
            result = provider.provider_catalog({"ollama_available": False, "models": []})
        self.assertTrue(result["api_configured"])
        self.assertNotIn("private-test-secret", json.dumps(result))

    def test_unconfigured_api_never_sends_request(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(provider, "build_opener") as opener:
            with self.assertRaisesRegex(provider.ProviderError, "not configured"):
                provider.generate("test-model", "task", {}, provider="api")
        opener.assert_not_called()

    def test_ollama_stream_and_bounded_conversation(self):
        candidate = json.dumps({"code": "print(json.dumps({'x': 1}))", "reflection": "Compute x."})
        chunks = [{"message": {"content": candidate[:20]}, "done": False}, {"message": {"content": candidate[20:]}, "done": True}]
        response = Response(b"\n".join(json.dumps(c).encode() for c in chunks))
        seen = []
        with patch.object(provider, "urlopen", return_value=response) as opener:
            result = provider.generate("test-model", "task", {}, progress_callback=lambda text, kind: seen.append(text))
        self.assertEqual(result["code"], "print(json.dumps({'x': 1}))")
        self.assertEqual("".join(seen), candidate)
        body = json.loads(opener.call_args.args[0].data)
        self.assertEqual(body["options"]["num_ctx"], 8192)

    def test_api_sse_request_and_key_is_header_only(self):
        content = json.dumps({"code": "print('{}')", "reflection": "Return an object."})
        response = Response(b"data: " + json.dumps({"choices": [{"delta": {"content": content}}]}).encode() + b"\n\ndata: [DONE]\n", "text/event-stream")
        with patch.dict(os.environ, {"AUTOHEAL_API_KEY": "private-test-secret", "AUTOHEAL_API_MODEL": "test-model"}), patch.object(provider, "build_opener") as factory:
            factory.return_value.open.return_value = response
            result = provider.generate("test-model", "task", {}, provider="api")
            request = factory.return_value.open.call_args.args[0]
        self.assertEqual(result["provider"], "api")
        self.assertEqual(request.headers["Authorization"], "Bearer private-test-secret")
        self.assertNotIn(b"private-test-secret", request.data)
        self.assertNotIn("private-test-secret", json.dumps(result))

    def test_api_nonstream_response(self):
        content = json.dumps({"code": "print('{}')", "reflection": "Return object."})
        response = Response(json.dumps({"choices": [{"message": {"content": content}}]}).encode(), "application/json")
        with patch.dict(os.environ, {"AUTOHEAL_API_KEY": "private-test-secret", "AUTOHEAL_API_MODEL": "test-model"}), patch.object(provider, "build_opener") as factory:
            factory.return_value.open.return_value = response
            self.assertEqual(provider.generate("test-model", "task", {}, provider="api")["code"], "print('{}')")

    def test_api_errors_redact_credentials(self):
        error = HTTPError("https://api.groq.com/openai/v1/chat/completions", 401, "Unauthorized", {}, io.BytesIO(b"bad private-test-secret"))
        with patch.dict(os.environ, {"AUTOHEAL_API_KEY": "private-test-secret", "AUTOHEAL_API_MODEL": "test-model"}), patch.object(provider, "build_opener") as factory:
            factory.return_value.open.side_effect = error
            with self.assertRaises(provider.ProviderError) as caught:
                provider.generate("test-model", "task", {}, provider="api")
        self.assertNotIn("private-test-secret", str(caught.exception))

    def test_api_rejects_unsafe_base_and_arbitrary_model(self):
        with patch.dict(os.environ, {"AUTOHEAL_API_KEY": "secret", "AUTOHEAL_API_MODEL": "test-model", "AUTOHEAL_API_BASE": "http://example.com/v1"}):
            self.assertFalse(provider._api_settings()["configured"])
        with patch.dict(os.environ, {"AUTOHEAL_API_KEY": "secret", "AUTOHEAL_API_MODEL": "test-model", "AUTOHEAL_API_BASE": "https://example.com/v1"}):
            with self.assertRaisesRegex(provider.ProviderError, "configured API model"):
                provider.generate("another-model", "task", {}, provider="api")

    def test_api_redirect_refused(self):
        with self.assertRaisesRegex(provider.ProviderError, "redirects"):
            provider._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://another-host")

    def test_cancel_before_connection(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(provider, "urlopen") as opener:
            with self.assertRaisesRegex(provider.ProviderError, "cancelled"):
                provider.generate("test-model", "task", {}, cancel_event=cancel)
        opener.assert_not_called()

    def test_response_source_limit(self):
        payload = json.dumps({"message": {"content": "a" * 26001}, "done": True}).encode() + b"\n"
        with patch.object(provider, "urlopen", return_value=Response(payload)):
            with self.assertRaisesRegex(provider.ProviderError, "budget"):
                provider.generate("test-model", "task", {})

    def test_repair_history_preserves_roles_and_valid_json(self):
        messages = provider.build_messages("task", {"x": 1}, previous="print('bad')", feedback={"attempt": 1, "error": {"type": "ValueError"}, "validation": {"mismatches": []}})
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user"])
        self.assertEqual(json.loads(messages[2]["content"])["code"], "print('bad')")


if __name__ == "__main__":
    unittest.main()
