import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyboard import providers
from storyboard.schema import TEXT, ValidationError, obj


class LMStudioTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        for context in (patch.object(providers, "ROOT", Path(root.name)), patch.dict(os.environ, {}, clear=True)):
            context.start()
            self.addCleanup(context.stop)
        self.schema = obj(message=TEXT)
        self.response = {"choices": [{"finish_reason": "stop", "message": {"content": '{"message":"ok"}'}}]}

    def save(self, values, clear=None):
        return providers.save_settings({"values": values, "clear_keys": clear or []})

    def test_default_local_request_never_reuses_openai_credentials(self):
        self.save({"OPENAI_API_KEY": "fake-openai-secret"})
        with patch.object(providers, "request_json", return_value=self.response) as request:
            self.assertEqual(providers.generate_json("lmstudio", "local-model", "system", "user", self.schema), {"message": "ok"})
        url, payload, headers = request.call_args.args
        self.assertEqual(url, "http://127.0.0.1:1234/v1/chat/completions")
        self.assertEqual(headers, {})
        self.assertEqual(payload["response_format"]["json_schema"]["schema"], self.schema)
        self.assertEqual(payload["max_tokens"], 16000)
        self.assertFalse(payload["stream"])

    def test_optional_token_and_output_modes_are_isolated_and_redacted(self):
        for mode in ("json_schema", "json_object", "prompt"):
            config = self.save({"LMSTUDIO_API_KEY": "fake-local-secret", "LMSTUDIO_MODEL": "local",
                                "LMSTUDIO_BASE_URL": "http://localhost:1234/v1", "LMSTUDIO_OUTPUT_MODE": mode})
            self.assertNotIn("fake-local-secret", json.dumps(config))
            self.assertTrue(next(p for p in config["providers"] if p["id"] == "lmstudio")["key_configured"])
            with patch.object(providers, "request_json", return_value=self.response) as request:
                providers.generate_json("lmstudio", "local", "s", "u", self.schema)
            _, payload, headers = request.call_args.args
            self.assertEqual(headers, {"Authorization": "Bearer fake-local-secret"})
            self.assertEqual("response_format" in payload, mode != "prompt")
            self.assertNotIn("OPENAI_API_KEY", providers.local_settings())

    def test_save_without_key_or_address_and_clear_preserves_other_providers(self):
        with patch.object(providers, "request_json") as request:
            config = self.save({"LMSTUDIO_BASE_URL": "", "LMSTUDIO_MODEL": "local", "OPENAI_API_KEY": "fake-cloud"})
            request.assert_not_called()
        self.assertEqual(config["lmstudio_base_url"], providers.DEFAULT_LMSTUDIO_BASE)
        self.save({"LMSTUDIO_API_KEY": "fake-token"})
        self.save({"LMSTUDIO_API_KEY": ""})
        self.assertEqual(providers.load_settings()["LMSTUDIO_API_KEY"], "fake-token")
        self.save({}, ["LMSTUDIO_API_KEY"])
        self.assertEqual(providers.load_settings()["LMSTUDIO_API_KEY"], "")
        self.assertEqual(providers.load_settings()["OPENAI_API_KEY"], "fake-cloud")

    def test_invalid_or_remote_endpoints_and_output_modes_fail_before_network(self):
        for address in ("http://remote.example/v1", "https://remote.example/v1", "http://localhost:1234/v1/chat/completions",
                        "http://key@localhost:1234/v1", "http://localhost:1234/v1?key=secret", "http://localhost:99999/v1"):
            with self.subTest(address=address), patch.object(providers, "request_json") as request:
                with self.assertRaises(ValidationError):
                    self.save({"LMSTUDIO_BASE_URL": address})
                with patch.object(providers, "load_settings", return_value={"LMSTUDIO_BASE_URL": address}):
                    with self.assertRaises(ValidationError):
                        providers.generate_json("lmstudio", "local", "s", "u", self.schema)
                request.assert_not_called()
        with self.assertRaises(ValidationError):
            self.save({"LMSTUDIO_OUTPUT_MODE": "invalid"})

    def test_endpoint_change_does_not_send_saved_token_to_another_server(self):
        self.save({"LMSTUDIO_API_KEY": "fake-token"})
        with self.assertRaises(ValidationError):
            self.save({"LMSTUDIO_BASE_URL": "http://127.0.0.1:1235/v1"})
        self.save({"LMSTUDIO_BASE_URL": "http://127.0.0.1:1235/v1"}, ["LMSTUDIO_API_KEY"])

    def test_managed_environment_and_unfinished_responses_are_not_bypassed(self):
        with patch.dict(os.environ, {"LMSTUDIO_MODEL": "managed"}):
            with self.assertRaises(ValidationError):
                self.save({"LMSTUDIO_MODEL": "override"})
        for reason in ("length", "tool_calls", None):
            response = {"choices": [{"finish_reason": reason, "message": {"content": '{"message":"ok"}'}}]}
            with patch.object(providers, "request_json", return_value=response) as request:
                with self.assertRaises(providers.ProviderError):
                    providers.generate_json("lmstudio", "local", "s", "u", self.schema)
                request.assert_called_once()
