"""Reproduce rejected shared states through real adapters; no external API calls."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import conversion, engine, library, prompt_renderer, providers
from storyboard.schema import ValidationError, validate

ROOT = Path(__file__).resolve().parent.parent


class ConversionRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        storage = patch.object(library, "ROOT", Path(temporary.name))
        storage.start()
        self.addCleanup(storage.stop)
        brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        self.document = engine.generate({"brief": brief, "provider": "demo"})
        for shot, duration in zip(self.document["story"]["shots"], [4, 4, 4, 5, 7, 6]):
            shot["duration"] = duration
        split = self.document["story"]["shots"][3]
        for field in ("start_state", "end_state"):
            split[field]["props"] = [{"name": "phone", "holder": "", "position": "on the seat"}]
        self.payload = {"selected": [s["id"] for s in self.document["story"]["shots"]],
                        "split_mode": "fixed", "guide_id": "minimax-h3-text", "provider": "openai", "model": "fake"}
        self.payload["id"] = library.save(self.document)["id"]
        self.layout = conversion.plan(self.document, self.payload["selected"], split_mode="fixed")
        self.valid = direction_output(self.layout)

    def test_dynamic_schema_binds_only_reference_fields_and_preserves_base(self):
        before = copy.deepcopy(prompt_renderer.DIRECTOR_OUTPUT)
        schema = prompt_renderer.output_schema(self.document, self.layout)
        validate(self.valid, schema)
        invalid = copy.deepcopy(self.valid)
        invalid["boundaries"][0]["state"]["props"][0]["holder"] = self.document["brief"]["characters"][0]["name"]
        with self.assertRaisesRegex(ValidationError, "holder"):
            validate(invalid, schema)
        self.assertEqual(prompt_renderer.DIRECTOR_OUTPUT, before)
        self.assertNotIn("enum", schema["properties"]["clips"]["items"]["properties"]["context"])

    def test_each_rejected_state_is_repaired_once_with_precise_paths(self):
        for issue in ("holder-name", "missing-character", "duplicate-character", "empty-emotion", "missing-prop"):
            with self.subTest(issue=issue):
                invalid = copy.deepcopy(self.valid)
                state = invalid["boundaries"][0]["state"]
                if issue == "holder-name":
                    state["props"][0]["holder"] = self.document["brief"]["characters"][0]["name"]
                elif issue == "missing-character":
                    state["characters"].pop()
                elif issue == "duplicate-character":
                    state["characters"][1] = copy.deepcopy(state["characters"][0])
                elif issue == "empty-emotion":
                    state["characters"][0]["emotion"] = " "
                else:
                    state["props"] = []
                before = copy.deepcopy(self.document)
                calls = []

                def generate(provider, model, system, user, schema):
                    request = json.loads(user)
                    calls.append(request)
                    if len(calls) == 1:
                        return invalid
                    self.assertIn("boundaries.B01.state", request["repair"]["validation_errors"][0])
                    self.assertEqual(request["repair"]["previous_output"], invalid)
                    self.assertEqual(request["plan"], calls[0]["plan"])
                    self.assertEqual(request["boundary_contract"]["persistent_props"], {"B01": ["phone"]})
                    corrected = copy.deepcopy(self.valid)
                    corrected["boundaries"][0]["state"]["characters"][0]["pose"] = "Holding a phone mid-gesture"
                    return corrected

                with patch.object(providers, "generate_json", side_effect=generate):
                    result = conversion.compile_prompts(self.document, self.payload)
                self.assertEqual(len(calls), 2)
                self.assertTrue(result["validation_report"]["repaired"])
                left, right = [c["prompt"] for c in result["output"]["clips"]]
                self.assertEqual(left.split("End at shared boundary B01: ")[1].split("\n")[0],
                                 right.split("Start at shared boundary B01: ")[1].split("\n")[0])
                self.assertEqual([c["duration"] for c in result["plan"]["clips"]], [15, 15])
                self.assertEqual(self.document, before)
                self.assertEqual([d["text"] for d in result["dialogue_manifest"]],
                                 [line["text"] for s in self.document["story"]["shots"] for line in s["dialogue"]])

    def test_all_three_real_adapters_pass_schema_failures_to_repair(self):
        invalid = copy.deepcopy(self.valid)
        invalid["boundaries"][0]["state"]["props"][0]["holder"] = "N/A"
        settings = {"OPENAI_API_KEY": "fake", "ANTHROPIC_API_KEY": "fake"}
        for provider in ("openai", "claude", "ollama"):
            with self.subTest(provider=provider):
                count = 0

                def response(url, payload, headers):
                    nonlocal count
                    count += 1
                    content = json.dumps(invalid if count == 1 else self.valid)
                    if provider == "openai":
                        return {"status": "completed", "output": [{"type": "message", "content": [
                            {"type": "output_text", "text": content}]}]}
                    if provider == "claude":
                        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": content}]}
                    return {"done": True, "message": {"content": content}}

                with patch.object(providers, "load_settings", return_value=settings), \
                     patch.object(providers, "request_json", side_effect=response):
                    result = conversion.compile_prompts(self.document, {**self.payload, "provider": provider})
                self.assertEqual(count, 2)
                self.assertTrue(result["validation_report"]["repaired"])

    def test_repair_limit_and_failure_detail(self):
        invalid = copy.deepcopy(self.valid)
        invalid["boundaries"][0]["state"]["characters"][0]["pose"] = ""
        with patch.object(providers, "generate_json", return_value=invalid) as upstream:
            with self.assertRaisesRegex(ValidationError, r"1회.*boundaries.B01.state.characters\[0\].pose"):
                conversion.compile_prompts(self.document, self.payload)
        self.assertEqual(upstream.call_count, 2)

    def test_valid_output_and_transport_or_setup_failure_never_retry(self):
        with patch.object(providers, "generate_json", return_value=self.valid) as upstream:
            result = conversion.compile_prompts(self.document, self.payload)
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(result["validation_report"], {"attempts": 1, "repaired": False, "issues": []})
        for error in (providers.ProviderError("timeout"), ValidationError("missing API key")):
            with patch.object(providers, "generate_json", side_effect=error) as upstream:
                with self.assertRaises(type(error)):
                    conversion.compile_prompts(self.document, self.payload)
            self.assertEqual(upstream.call_count, 1)

    def test_real_warning_cannot_be_erased_by_repair(self):
        invalid = copy.deepcopy(self.valid)
        invalid["boundaries"][0]["state"]["characters"][0]["emotion"] = ""
        invalid["warnings"] = ["Unsupported requirement"]
        with patch.object(providers, "generate_json", side_effect=[invalid, self.valid]):
            with self.assertRaisesRegex(ValidationError, "Unsupported requirement"):
                conversion.compile_prompts(self.document, self.payload)

    def test_non_english_directions_are_translated_by_the_same_bounded_repair(self):
        invalid = copy.deepcopy(self.valid)
        invalid["clips"][0]["shots"][0]["direction"] = "ゆっくり振り返る。"
        with patch.object(providers, "generate_json", side_effect=[invalid, self.valid]) as upstream:
            result = conversion.compile_prompts(self.document, self.payload)
        self.assertEqual(upstream.call_count, 2)
        self.assertIn("English-only", result["validation_report"]["issues"][0])
        self.assertEqual(result["output_language"], "english_except_dialogue")


if __name__ == "__main__":
    unittest.main()
