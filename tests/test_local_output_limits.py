import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyboard import diagnostics, providers
from storyboard.schema import TEXT, ValidationError, obj


class LocalOutputLimitsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for context in (patch.object(providers, "ROOT", Path(temporary.name)), patch.dict(os.environ, {}, clear=True)):
            context.start()
            self.addCleanup(context.stop)
        self.schema = obj(message=TEXT)
        self.chat = {"choices": [{"finish_reason": "stop", "message": {"content": '{"message":"ok"}'}}]}
        self.response = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"message":"ok"}'}]}]}

    def save(self, values):
        return providers.save_settings({"values": values, "clear_keys": []})

    def test_ollama_budget_persists_and_reaches_payload_and_diagnostics(self):
        config = self.save({"OLLAMA_MAX_TOKENS": "32000"})
        self.assertEqual(config["ollama_max_tokens"], 32000)
        self.assertEqual(providers.local_settings()["OLLAMA_MAX_TOKENS"], "32000")
        result = {"done": True, "message": {"content": '{"message":"ok"}'}}
        with patch.object(providers, "request_json", return_value=result) as request:
            self.assertEqual(providers.generate_json("ollama", "local", "s", "u", self.schema), {"message": "ok"})
        self.assertEqual(request.call_args.args[1]["options"]["num_predict"], 32000)
        self.assertEqual(diagnostics.listing()["entries"][0]["output_limit"], 32000)

    def test_compatible_budget_both_api_modes_ipv6_and_streaming(self):
        for host in ("localhost", "127.0.0.1", "[::1]"):
            for mode in ("chat_completions", "responses"):
                for stream in ("false", "true"):
                    with self.subTest(host=host, mode=mode, stream=stream):
                        self.save({"OPENAI_BASE_URL": f"http://{host}:1234/v1", "OPENAI_API_KEY": "fake-key",
                                   "OPENAI_API_MODE": mode, "OPENAI_CHAT_STREAM": stream, "OPENAI_LOCAL_MAX_TOKENS": "24000"})
                        result = self.chat if mode == "chat_completions" else self.response
                        with patch.object(providers, "request_json", return_value=result) as request:
                            providers.generate_json("openai", "local", "s", "u", self.schema)
                        payload = request.call_args.args[1]
                        self.assertEqual(payload["max_tokens" if mode == "chat_completions" else "max_output_tokens"], 24000)
                        self.assertEqual(diagnostics.listing()["entries"][0]["output_limit"], 24000)

    def test_cloud_limits_remain_unchanged_and_provider_budgets_are_isolated(self):
        self.save({"OPENAI_API_KEY": "fake-key", "OPENAI_LOCAL_MAX_TOKENS": "24000",
                   "OLLAMA_MAX_TOKENS": "32000", "LMSTUDIO_MAX_TOKENS": "48000"})
        for base in ("https://api.openai.com/v1", "https://gateway.example/v1", "https://localhost.example/v1"):
            for mode in ("responses", "chat_completions"):
                self.save({"OPENAI_BASE_URL": base, "OPENAI_API_KEY": "fake-key", "OPENAI_API_MODE": mode})
                with patch.object(providers, "request_json", return_value=self.chat if mode == "chat_completions" else self.response) as request:
                    providers.generate_json("openai", "model", "s", "u", self.schema)
                field = "max_output_tokens" if mode == "responses" else "max_completion_tokens" if "api.openai.com" in base else "max_tokens"
                self.assertEqual(request.call_args.args[1][field], 16000)
                self.assertEqual(diagnostics.listing()["entries"][0]["output_limit"], 16000)
        with patch.object(providers, "request_json", return_value=self.chat) as request:
            providers.generate_json("lmstudio", "model", "s", "u", self.schema)
        self.assertEqual(request.call_args.args[1]["max_tokens"], 48000)

    def test_invalid_values_no_partial_save_environment_precedence_and_defaults(self):
        for key in ("OLLAMA_MAX_TOKENS", "OPENAI_LOCAL_MAX_TOKENS"):
            for value in ("-1", "0", "255", "131073", "NaN", "1.5", "1e4", "９９９"):
                with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                    self.save({"OLLAMA_MODEL": "must-not-save", key: value})
                self.assertEqual(providers.local_settings(), {})
        self.assertEqual(providers.configuration()["ollama_max_tokens"], 16000)
        self.assertEqual(self.save({"OPENAI_LOCAL_MAX_TOKENS": ""})["openai_local_max_tokens"], 16000)
        for key, public in (("OLLAMA_MAX_TOKENS", "ollama_max_tokens"), ("OPENAI_LOCAL_MAX_TOKENS", "openai_local_max_tokens")):
            with patch.dict(os.environ, {key: "24000"}):
                self.assertEqual(providers.configuration()[public], 24000)
                with self.assertRaises(ValidationError):
                    self.save({key: "32000"})
        for provider, key in (("ollama", "OLLAMA_MAX_TOKENS"), ("openai", "OPENAI_LOCAL_MAX_TOKENS")):
            with patch.dict(os.environ, {key: "invalid", "OPENAI_BASE_URL": "http://localhost:1234/v1"}), \
                 patch.object(providers, "request_json") as request:
                with self.assertRaises(ValidationError):
                    providers.generate_json(provider, "model", "s", "u", self.schema)
                request.assert_not_called()

    def test_ollama_length_error_keeps_partial_output_unsaved_and_does_not_retry(self):
        with patch.object(providers, "request_json", return_value={"done": True, "done_reason": "length",
                                                                 "message": {"content": '{"message":"PRIVATE"}'}}) as request:
            with self.assertRaises(providers.ProviderError) as error:
                providers.generate_json("ollama", "local", "s", "u", self.schema)
            request.assert_called_once()
        self.assertIn("출력 한도에 도달", str(error.exception))
        self.assertNotIn("PRIVATE", str(error.exception))
