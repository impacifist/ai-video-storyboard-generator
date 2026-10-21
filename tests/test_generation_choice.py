"""A complete count-only mismatch is a user choice, never a validation bypass."""

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from storyboard import conversion, engine, providers
from storyboard.schema import ValidationError

ROOT = Path(__file__).resolve().parents[1]


class GenerationChoiceTests(unittest.TestCase):
    def setUp(self):
        self.brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        self.payload = {"brief": self.brief, "provider": "openai", "model": "mock", "offer_count_choice": True}

    def story(self, count):
        story = engine.demo_story(self.brief)
        while len(story["shots"]) < count:
            story["shots"].append(copy.deepcopy(story["shots"][-1]))
        story["shots"] = story["shots"][:count]
        for index, shot in enumerate(story["shots"], 1):
            shot["id"] = f"S{index:02d}"
        return story

    def test_shorter_and_longer_valid_drafts_are_offered_without_changing_request(self):
        for count in (4, 8):
            with self.subTest(count=count):
                original = copy.deepcopy(self.payload)
                story = self.story(count)
                with patch.object(providers, "generate_json", return_value=story) as ai:
                    response = engine.generate_response(self.payload)
                    pending = response["pending_generation"]
                    self.assertNotIn("document", response)
                    self.assertEqual((pending["requested_count"], pending["actual_count"]), (6, count))
                    self.assertEqual(pending["document"]["brief"]["shot_count"], count)
                    self.assertEqual(pending["document"]["story"], story)
                    accepted = engine.accept_generation({"document": pending["document"], "requested_brief": self.brief})
                    ai.assert_called_once()
                engine.validate_document(accepted["document"])
                self.assertIn(f"요청 6개 · 생성 {count}개", accepted["document"]["history"][-1]["event"])
                plan = conversion.plan(accepted["document"], [s["id"] for s in story["shots"]])
                self.assertEqual(sum(len(c["shots"]) for c in plan["clips"]), count)
                self.assertEqual(self.payload, original)

    def test_matching_result_keeps_existing_response_shape(self):
        with patch.object(providers, "generate_json", return_value=self.story(6)):
            result = engine.generate_response(self.payload)
        self.assertEqual(set(result), {"document", "review"})

    def test_default_engine_and_old_clients_still_reject_mismatched_counts_with_numbers(self):
        for call in (engine.generate, engine.generate_response):
            payload = {k: v for k, v in self.payload.items() if k != "offer_count_choice"}
            with patch.object(providers, "generate_json", return_value=self.story(5)):
                with self.assertRaisesRegex(ValidationError, "요청 6개.*생성 5개"):
                    call(payload)

    def test_other_invalid_fields_cannot_be_accepted_as_a_count_difference(self):
        for issue in ("speaker", "id", "state", "duration", "empty"):
            story = self.story(5)
            shot = story["shots"][0]
            if issue == "speaker":
                shot["dialogue"][0]["speaker"] = "unknown"
            elif issue == "id":
                shot["id"] = "S02"
            elif issue == "state":
                shot["start_state"]["characters"] = []
            elif issue == "duration":
                shot["duration"] = 0
            else:
                story["summary"] = ""
            with self.subTest(issue=issue), patch.object(providers, "generate_json", return_value=story):
                with self.assertRaises(ValidationError):
                    engine.generate_response(self.payload)

    def test_outside_supported_count_range_reports_actual_count_without_candidate(self):
        for count in (0, 2, 61):
            with self.subTest(count=count), patch.object(providers, "generate_json", return_value=self.story(count)):
                with self.assertRaisesRegex(ValidationError, f"요청 6개.*생성 {count}개"):
                    engine.generate_response(self.payload)

    def test_missing_locked_shot_is_rejected_and_present_locked_shot_is_restored(self):
        previous = engine.generate({"brief": self.brief, "provider": "demo"})
        previous["story"]["shots"][-1]["locked"] = True
        self.payload["previous"] = previous
        with patch.object(providers, "generate_json", return_value=self.story(5)):
            with self.assertRaisesRegex(ValidationError, "고정 컷이 누락"):
                engine.generate_response(self.payload)
        previous["story"]["shots"][-1]["locked"] = False
        previous["story"]["shots"][1]["locked"] = True
        story = self.story(5)
        story["shots"][1]["purpose"] = "Changed by the AI"
        with patch.object(providers, "generate_json", return_value=story):
            pending = engine.generate_response(self.payload)["pending_generation"]
        self.assertEqual(pending["document"]["story"]["shots"][1], previous["story"]["shots"][1])
        engine.accept_generation({"document": pending["document"], "requested_brief": self.brief, "previous": previous})
        invalid = copy.deepcopy(pending["document"])
        invalid["story"]["shots"][1]["purpose"] = "Tampered before acceptance"
        with self.assertRaisesRegex(ValidationError, "고정 컷"):
            engine.accept_generation({"document": invalid, "requested_brief": self.brief, "previous": previous})

    def test_accept_revalidates_source_settings_and_story(self):
        with patch.object(providers, "generate_json", return_value=self.story(5)):
            draft = engine.generate_response(self.payload)["pending_generation"]["document"]
        for issue in ("brief", "speaker"):
            invalid = copy.deepcopy(draft)
            if issue == "brief":
                invalid["brief"]["location"] = "Changed location"
            else:
                invalid["story"]["shots"][0]["dialogue"][0]["speaker"] = "unknown"
            with self.subTest(issue=issue), self.assertRaises(ValidationError):
                engine.accept_generation({"document": invalid, "requested_brief": self.brief})

    def test_full_history_remains_valid_through_polish_pending_and_acceptance(self):
        previous = engine.generate({"brief": self.brief, "provider": "demo"})
        previous["history"] = [{"at": engine.now(), "event": f"Previous edit {i}"} for i in range(100)]
        story = self.story(5)
        with patch.object(providers, "generate_json", return_value=story), \
             patch.object(engine.dialogue, "polish_japanese", return_value=(story, "completed")):
            pending = engine.generate_response({**self.payload, "previous": previous})["pending_generation"]
        self.assertEqual(len(pending["document"]["history"]), 100)
        self.assertIn("요청 6개 · 생성 5개", pending["document"]["history"][-1]["event"])
        accepted = engine.accept_generation({"document": pending["document"], "requested_brief": self.brief, "previous": previous})
        self.assertEqual(len(accepted["document"]["history"]), 100)
        engine.validate_document(accepted["document"])

    def test_provider_failure_is_not_converted_into_a_draft_or_retried(self):
        with patch.object(providers, "generate_json", side_effect=providers.ProviderError("truncated")) as ai:
            with self.assertRaises(providers.ProviderError):
                engine.generate_response(self.payload)
        ai.assert_called_once()

    def test_incomplete_outline_reports_counts_without_offering_partial_story(self):
        brief = {**self.brief, "shot_count": 13}
        outline = {"summary": "A whole-story outline", "beats": ["Start", "End"], "assumptions": [],
                   "shots": [{"id": f"S{i:02d}", "scene_id": "scene", "duration": 2.5,
                              "purpose": "A beat", "action": "An approved action"} for i in range(1, 13)]}
        with patch.object(providers, "generate_json", return_value=outline) as ai:
            with self.assertRaisesRegex(ValidationError, "요청 13개.*생성 12개.*상세 컷"):
                engine.generate_response({**self.payload, "brief": brief})
        ai.assert_called_once()


if __name__ == "__main__":
    unittest.main()
