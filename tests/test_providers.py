import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from storyboard import providers
from storyboard.schema import TEXT, ValidationError, obj

SCHEMA = obj(message=TEXT)
BODY = {"message": "콘티 응답"}
SETTINGS = {"OPENAI_API_KEY": "fake-openai-test-key", "ANTHROPIC_API_KEY": "fake-claude-test-key"}


class AdapterTests(unittest.TestCase):
    def run_adapter(self, provider, response):
        with patch.object(providers, "load_settings", return_value=SETTINGS), \
             patch.object(providers, "request_json", return_value=response) as request:
            result = providers.generate_json(provider, "test-model", "지시", "입력", SCHEMA)
        self.assertEqual(result, BODY)
        return request.call_args.args

    def test_ollama_native_schema_request(self):
        url, payload, headers = self.run_adapter("ollama", {
            "done": True, "message": {"content": json.dumps(BODY)}})
        self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(payload["format"], SCHEMA)
        self.assertIs(payload["stream"], False)
        self.assertEqual(headers, {})

    def test_openai_responses_request_and_output_extraction(self):
        url, payload, headers = self.run_adapter("openai", {"status": "completed", "output": [
            {"type": "reasoning", "summary": []}, {"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(BODY)}]}]})
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(payload["text"]["format"]["schema"], SCHEMA)
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertFalse(payload["store"])
        self.assertEqual(headers["Authorization"], "Bearer fake-openai-test-key")

    def test_claude_messages_request_and_output_extraction(self):
        url, payload, headers = self.run_adapter("claude", {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(BODY)}]})
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(payload["output_config"]["format"]["schema"], SCHEMA)
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(headers["x-api-key"], "fake-claude-test-key")

    def test_compatible_chat_request_and_all_output_modes(self):
        for output in ("json_schema", "json_object", "prompt"):
            settings = {**SETTINGS, "OPENAI_BASE_URL": "https://gateway.example/v1/",
                        "OPENAI_API_MODE": "chat_completions", "OPENAI_OUTPUT_MODE": output}
            response = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(BODY)}}]}
            with self.subTest(output=output), patch.object(providers, "load_settings", return_value=settings), \
                 patch.object(providers, "request_json", return_value=response) as request:
                self.assertEqual(providers.generate_json("openai", "gateway-model", "sys", "user", SCHEMA), BODY)
                url, payload, headers = request.call_args.args
                self.assertEqual(url, "https://gateway.example/v1/chat/completions")
                self.assertEqual(headers["Authorization"], "Bearer fake-openai-test-key")
                self.assertEqual(payload["model"], "gateway-model")
                self.assertFalse(payload["stream"])
                self.assertEqual(payload["max_tokens"], 16000)
                self.assertNotIn("store", payload)
                self.assertIn("JSON Schema", payload["messages"][0]["content"])
                if output == "prompt":
                    self.assertNotIn("response_format", payload)
                else:
                    self.assertEqual(payload["response_format"]["type"], output)

    def test_chat_rejects_truncation_refusal_tools_and_missing_choices(self):
        settings = {**SETTINGS, "OPENAI_API_MODE": "chat_completions"}
        responses = [{"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
                     {"choices": [{"finish_reason": "stop", "message": {"refusal": "refused", "content": "{}"}}]},
                     {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{}]}}]},
                     {"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}]}]
        for response in responses:
            with self.subTest(response=response), patch.object(providers, "load_settings", return_value=settings), \
                 patch.object(providers, "request_json", return_value=response) as request:
                with self.assertRaises(providers.ProviderError):
                    providers.generate_json("openai", "m", "s", "u", SCHEMA)
                self.assertEqual(request.call_count, 1)

    def test_prompt_json_fence_is_validated_and_arbitrary_prose_is_rejected(self):
        settings = {**SETTINGS, "OPENAI_API_MODE": "chat_completions", "OPENAI_OUTPUT_MODE": "prompt"}
        with patch.object(providers, "load_settings", return_value=settings):
            for content, valid in [("```json\n" + json.dumps(BODY) + "\n```", True),
                                   ("Here is JSON: " + json.dumps(BODY), False)]:
                with patch.object(providers, "request_json", return_value={"choices": [
                        {"finish_reason": "stop", "message": {"content": content}}]}):
                    if valid:
                        self.assertEqual(providers.generate_json("openai", "m", "s", "u", SCHEMA), BODY)
                    else:
                        with self.assertRaises(providers.ProviderError):
                            providers.generate_json("openai", "m", "s", "u", SCHEMA)

    def test_gateway_configuration_displays_actual_endpoint(self):
        settings = {**SETTINGS, "OPENAI_BASE_URL": "https://gateway.example/v1", "OPENAI_API_MODE": "chat_completions"}
        with patch.object(providers, "load_settings", return_value=settings):
            config = providers.configuration()
        destination = next(p for p in config["providers"] if p["id"] == "openai")["destination"]
        self.assertIn("https://gateway.example/v1/chat/completions", destination)
        self.assertNotIn("fake-openai-test-key", json.dumps(config))

    def test_invalid_gateway_addresses_fail_before_network(self):
        for base in ("http://gateway.example/v1", "https://secret@example.com/v1", "https://example.com/v1?key=secret",
                     "https://example.com/v1/chat/completions", "file:///private", "https://example.com:99999/v1"):
            with self.subTest(base=base), patch.object(providers, "load_settings", return_value={**SETTINGS, "OPENAI_BASE_URL": base}), \
                 patch.object(providers, "request_json") as request:
                with self.assertRaises(ValidationError):
                    providers.generate_json("openai", "m", "s", "u", SCHEMA)
                request.assert_not_called()

    def test_missing_key_fails_without_network(self):
        for provider in ("openai", "claude"):
            with self.subTest(provider=provider), patch.object(providers, "load_settings", return_value={}), \
                 patch.object(providers, "request_json") as request:
                with self.assertRaises(ValidationError):
                    providers.generate_json(provider, "test", "system", "user", SCHEMA)
                request.assert_not_called()

    def test_truncation_refusal_and_invalid_json_never_fall_back_to_demo(self):
        responses = [
            ("openai", {"status": "incomplete", "output": []}),
            ("openai", {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]}),
            ("claude", {"stop_reason": "max_tokens", "content": []}),
            ("claude", {"stop_reason": "refusal", "content": []}),
            ("ollama", {"done": False, "message": {"content": "{}"}}),
            ("ollama", {"done": True, "done_reason": "length", "message": {"content": "{}"}}),
            ("ollama", {"done": True, "message": {"content": "invalid-json"}}),
        ]
        for provider, response in responses:
            with self.subTest(provider=provider, response=response), \
                 patch.object(providers, "load_settings", return_value=SETTINGS), \
                 patch.object(providers, "request_json", return_value=response):
                with self.assertRaises(providers.ProviderError):
                    providers.generate_json(provider, "test", "system", "user", SCHEMA)

    def test_local_ollama_url_restriction(self):
        for url in ("https://example.com", "http://127.0.0.1:11434/private", "http://key@localhost:11434", "http://localhost:11434?x=1"):
            with self.subTest(url=url), patch.object(providers, "load_settings", return_value={"OLLAMA_BASE_URL": url}), \
                 patch.object(providers, "request_json") as request:
                with self.assertRaises(ValidationError):
                    providers.generate_json("ollama", "test", "s", "u", SCHEMA)
                request.assert_not_called()

    def test_configuration_does_not_expose_keys(self):
        with patch.object(providers, "load_settings", return_value=SETTINGS):
            config = providers.configuration()
        text = json.dumps(config)
        self.assertNotIn("fake-openai-test-key", text)
        self.assertNotIn("fake-claude-test-key", text)
        self.assertEqual(len(config["providers"]), 4)

    def test_http_error_and_timeout_do_not_echo_upstream_secrets(self):
        for error in (HTTPError("url", 401, "secret-from-upstream", {}, None),
                      URLError("secret-from-upstream"), TimeoutError("secret-from-upstream")):
            opener = unittest.mock.Mock()
            opener.open.side_effect = error
            with self.subTest(error=type(error)), patch.object(providers, "build_opener", return_value=opener):
                with self.assertRaises(providers.ProviderError) as result:
                    providers.request_json("https://api.openai.com/v1/responses", {}, {})
                self.assertNotIn("secret-from-upstream", str(result.exception))
                self.assertEqual(opener.open.call_count, 1)

    def test_redirects_are_not_followed(self):
        self.assertIsNone(providers.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.example"))


if __name__ == "__main__":
    unittest.main()
