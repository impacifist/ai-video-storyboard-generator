import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyboard import providers
from storyboard.schema import ValidationError


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(providers, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def save(self, values=None, clear=None):
        return providers.save_settings({"values": values or {}, "clear_keys": clear or []})

    def test_save_reload_and_redacted_response_without_network(self):
        with patch.object(providers, "request_json") as request:
            result = self.save({"OPENAI_API_KEY": "fake-secret-openai", "ANTHROPIC_API_KEY": "fake-secret-claude",
                                "OPENAI_MODEL": "model-a", "OLLAMA_BASE_URL": "http://localhost:11435/"})
            request.assert_not_called()
        self.assertNotIn("fake-secret", json.dumps(result))
        self.assertEqual(providers.load_settings()["OPENAI_API_KEY"], "fake-secret-openai")
        self.assertEqual(result["ollama_base_url"], "http://localhost:11435")
        self.assertTrue(next(p for p in result["providers"] if p["id"] == "claude")["configured"])

    def test_blank_preserves_and_delete_masks_dotenv_without_modifying_it(self):
        original = "# leave untouched\nOPENAI_API_KEY=fake-env-file-key\nOTHER_SETTING=keep-me\n"
        (self.root / ".env").write_text(original, encoding="utf-8")
        self.save({"OPENAI_API_KEY": "fake-ui-key"})
        self.save({"OPENAI_API_KEY": ""})
        self.assertEqual(providers.load_settings()["OPENAI_API_KEY"], "fake-ui-key")
        self.save(clear=["OPENAI_API_KEY"])
        self.assertEqual(providers.load_settings()["OPENAI_API_KEY"], "")
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"), original)

    def test_openai_only_save_with_blank_ollama_address(self):
        result = self.save({"OPENAI_API_KEY": "fake-openai-only", "OPENAI_MODEL": "test-model",
                            "OLLAMA_BASE_URL": "", "OLLAMA_MODEL": "", "CLAUDE_MODEL": ""})
        self.assertTrue(next(p for p in result["providers"] if p["id"] == "openai")["configured"])
        self.assertEqual(result["ollama_base_url"], "http://127.0.0.1:11434")
        self.assertNotIn("OLLAMA_BASE_URL", providers.local_settings())
        self.save({"OLLAMA_BASE_URL": "http://localhost:11435"})
        self.save({"OLLAMA_BASE_URL": " "})
        self.assertEqual(providers.configuration()["ollama_base_url"], "http://localhost:11435")

    def test_environment_precedence_and_no_partial_write(self):
        self.save({"OPENAI_MODEL": "original"})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-process-key"}):
            self.assertEqual(providers.load_settings()["OPENAI_API_KEY"], "fake-process-key")
            self.assertIn("OPENAI_API_KEY", providers.configuration()["environment_fields"])
            with self.assertRaises(ValidationError):
                self.save({"OPENAI_MODEL": "should-not-save"}, ["OPENAI_API_KEY"])
        self.assertEqual(providers.load_settings()["OPENAI_MODEL"], "original")

    def test_gateway_change_requires_its_own_key(self):
        self.save({"OPENAI_API_KEY": "fake-official-key"})
        with self.assertRaises(ValidationError):
            self.save({"OPENAI_BASE_URL": "https://gateway.example/v1"})
        self.assertNotIn("OPENAI_BASE_URL", providers.local_settings())
        result = self.save({"OPENAI_BASE_URL": "https://gateway.example/v1", "OPENAI_API_KEY": "fake-gateway-key",
                            "OPENAI_API_MODE": "chat_completions", "OPENAI_OUTPUT_MODE": "prompt"})
        self.assertEqual(result["openai_api_mode"], "chat_completions")
        self.assertEqual(providers.load_settings()["OPENAI_API_KEY"], "fake-gateway-key")

    def test_invalid_gateway_modes_do_not_change_settings(self):
        for key, value in [("OPENAI_API_MODE", "wrong"), ("OPENAI_OUTPUT_MODE", "wrong"),
                           ("OPENAI_BASE_URL", "http://evil.example")]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                self.save({key: value})
            self.assertEqual(providers.local_settings(), {})

    def test_bad_values_do_not_change_saved_file_or_echo_key(self):
        self.save({"OPENAI_MODEL": "original"})
        for values, clear in [({"OPENAI_API_KEY": "fake-secret\nINJECTED=value"}, []),
                              ({"OPENAI_API_KEY": "fake secret"}, []),
                              ({"OLLAMA_BASE_URL": "http://evil.example"}, []),
                              ({"OLLAMA_BASE_URL": "http://localhost:99999"}, []),
                              ({"OLLAMA_BASE_URL": "http://[broken"}, []),
                              ({"UNKNOWN": "fake-secret"}, []),
                              ({"OPENAI_API_KEY": "fake-secret"}, ["OPENAI_API_KEY"]),
                              ({}, ["OPENAI_MODEL"])]:
            with self.subTest(values=values), self.assertRaises(ValidationError) as error:
                self.save(values, clear)
            self.assertNotIn("fake-secret", str(error.exception))
            self.assertEqual(providers.local_settings(), {"OPENAI_MODEL": "original"})

    def test_failed_atomic_replace_preserves_old_file(self):
        self.save({"OPENAI_MODEL": "original"})
        with patch.object(providers.os, "replace", side_effect=PermissionError("test")):
            with self.assertRaises(PermissionError):
                self.save({"OPENAI_MODEL": "new"})
        self.assertEqual(providers.local_settings(), {"OPENAI_MODEL": "original"})
        self.assertEqual(list((self.root / ".local-secrets").glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
