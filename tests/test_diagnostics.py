import io
import json
import unittest
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from storyboard import diagnostics, providers
from storyboard.schema import TEXT, obj


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        context = patch.object(diagnostics, "_entries", deque(maxlen=diagnostics.LIMIT))
        context.start()
        self.addCleanup(context.stop)

    def generate(self, result, model="local-model"):
        with patch.object(providers, "load_settings", return_value={"LMSTUDIO_API_KEY": "private-key-value"}), \
             patch.object(providers, "request_json", return_value=result):
            return providers.generate_json("lmstudio", model, "PRIVATE SYSTEM TEXT", "PRIVATE DIALOGUE", obj(message=TEXT))

    def test_length_usage_and_safe_model_redaction_without_content(self):
        response = {"choices": [{"finish_reason": "length", "message": {"content": "PRIVATE RESPONSE TEXT"}}],
                    "usage": {"prompt_tokens": 12000, "completion_tokens": 16000, "total_tokens": 28000,
                              "completion_tokens_details": {"reasoning_tokens": 15000}, "secret": "PRIVATE USAGE"}}
        with self.assertRaises(providers.ProviderError):
            self.generate(response, "local-private-key-value")
        value = diagnostics.listing()
        entry = value["entries"][0]
        self.assertEqual(entry["outcome"], "length")
        self.assertEqual(entry["finish_reason"], "length")
        self.assertEqual(entry["input_tokens"], 12000)
        self.assertEqual(entry["reasoning_tokens"], 15000)
        self.assertEqual(entry["output_limit"], 16000)
        self.assertEqual(entry["model"], "local-[redacted]")
        self.assertGreaterEqual(entry["elapsed_ms"], 0)
        encoded = json.dumps(value)
        for secret in ("private-key-value", "PRIVATE SYSTEM", "PRIVATE DIALOGUE", "PRIVATE RESPONSE", "PRIVATE USAGE"):
            self.assertNotIn(secret, encoded)

    def test_response_reasons_and_usage_are_allowlisted(self):
        response = {"choices": [{"finish_reason": "PRIVATE SERVER ERROR", "message": {"content": "{}"}}],
                    "usage": {"prompt_tokens": "private-key-value", "completion_tokens": -2, "total_tokens": True}}
        with self.assertRaises(providers.ProviderError):
            self.generate(response)
        entry = diagnostics.listing()["entries"][0]
        self.assertEqual(entry["finish_reason"], "other")
        self.assertNotIn("input_tokens", entry)
        self.assertNotIn("output_tokens", entry)
        self.assertNotIn("total_tokens", entry)
        self.assertNotIn("PRIVATE SERVER", json.dumps(entry))

    def test_success_schema_error_and_tool_call_are_separate(self):
        cases = [("stop", '{"message":"ok"}', "ok"), ("stop", "{}", "schema_error"), ("tool_calls", "{}", "tool_call"),
                 (None, "{}", "missing_finish"), ("content_filter", "{}", "refused"), ("stop", "not-json", "invalid_json")]
        for reason, content, outcome in cases:
            with self.subTest(outcome=outcome):
                try:
                    self.generate({"choices": [{"finish_reason": reason, "message": {"content": content}}]})
                except (providers.ProviderError, providers.OutputValidationError):
                    self.assertNotEqual(outcome, "ok")
                self.assertEqual(diagnostics.listing()["entries"][0]["outcome"], outcome)

    def test_http_status_and_timeout_do_not_include_exception_bodies_or_addresses(self):
        for error, outcome in ((HTTPError("https://private.example/?key=secret", 504, "PRIVATE BODY", {}, None), "http_error"),
                               (TimeoutError("PRIVATE BODY"), "timeout"), (OSError("PRIVATE BODY"), "connection_error")):
            opener = Mock()
            opener.open.side_effect = error
            with patch.object(providers, "load_settings", return_value={}), patch.object(providers, "build_opener", return_value=opener), self.assertRaises(providers.ProviderError):
                providers.generate_json("lmstudio", "local", "private prompt", "private user", obj(message=TEXT))
            row = diagnostics.listing()["entries"][0]
            self.assertEqual(row["outcome"], outcome)
            self.assertIsNone(row["timeout_seconds"])
            self.assertTrue(row["local"])
            self.assertNotIn("PRIVATE BODY", json.dumps(row))
            self.assertNotIn("private.example", json.dumps(row))
        self.assertEqual(diagnostics.listing()["entries"][-1]["http_status"], 504)

    def test_stream_usage_is_retained_and_missing_usage_stays_unknown(self):
        events = [{"choices": [{"delta": {"content": '{"message":"ok"}'}, "finish_reason": "stop"}]},
                  {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 20}}]
        body = b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events) + b"data: [DONE]\n\n"
        opener = Mock()
        opener.open.return_value = io.BytesIO(body)
        settings = {"OPENAI_BASE_URL": "http://127.0.0.1:1234/v1", "OPENAI_API_KEY": "private-key-value",
                    "OPENAI_API_MODE": "chat_completions", "OPENAI_CHAT_STREAM": "true"}
        with patch.object(providers, "load_settings", return_value=settings), patch.object(providers, "build_opener", return_value=opener):
            providers.generate_json("openai", "local", "system", "user", obj(message=TEXT))
        row = diagnostics.listing()["entries"][0]
        self.assertEqual(row["output_tokens"], 20)
        self.assertTrue(row["streaming"])
        self.generate({"choices": [{"finish_reason": "stop", "message": {"content": '{"message":"ok"}'}}]})
        self.assertNotIn("output_tokens", diagnostics.listing()["entries"][0])

    def test_bounded_history_and_clear_keep_running_request(self):
        for _ in range(diagnostics.LIMIT + 3):
            trace = diagnostics.Trace("lmstudio")
            trace.finish("ok")
        self.assertEqual(len(diagnostics.listing()["entries"]), diagnostics.LIMIT)
        trace = diagnostics.Trace("lmstudio")
        try:
            diagnostics.clear_completed()
            self.assertEqual([e["status"] for e in diagnostics.listing()["entries"]], ["running"])
        finally:
            trace.finish("ok")
        diagnostics.clear_completed()
        self.assertEqual(diagnostics.listing()["entries"], [])

    def test_concurrent_request_contexts_remain_separate(self):
        barrier = Barrier(2)

        def worker(operation, model):
            scope = diagnostics.begin_operation(operation)
            try:
                trace = diagnostics.Trace("lmstudio")
                trace.configure(model, [])
                barrier.wait(timeout=2)
                diagnostics.response_metadata({"choices": [{"finish_reason": "stop"}], "usage": {"completion_tokens": 7 if model == "one" else 9}})
                trace.finish("ok")
            finally:
                diagnostics.end_operation(scope)

        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(worker, "/api/generate", "one")
            b = executor.submit(worker, "/api/review", "two")
            a.result()
            b.result()
        rows = {e["model"]: e for e in diagnostics.listing()["entries"]}
        self.assertEqual((rows["one"]["operation"], rows["one"]["output_tokens"]), ("generate", 7))
        self.assertEqual((rows["two"]["operation"], rows["two"]["output_tokens"]), ("review", 9))
