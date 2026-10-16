import copy
import json
import unittest
from unittest.mock import patch

from storyboard import batch_generation, engine, providers
from storyboard.schema import ValidationError
from test_engine import brief


class BatchGenerationTests(unittest.TestCase):
    def source(self, count=60):
        value = brief()
        value.update(shot_count=count, duration=count * 3)
        return value, engine.demo_story(value)

    def upstream(self, story, calls, corrupt=None):
        def respond(provider, model, system, user, schema):
            request = json.loads(user)
            calls.append(request)
            self.assertIn(engine.SHOT_DIRECTION, system)
            if request["task"] == "storyboard_outline":
                return {**{k: copy.deepcopy(story[k]) for k in ("summary", "beats", "assumptions")},
                        "shots": [{**{k: s[k] for k in ("id", "scene_id", "duration", "purpose")},
                                   "action": " / ".join(s["actions"])} for s in story["shots"]]}
            ids = request["batch"]["shot_ids"]
            self.assertLessEqual(len(ids), 6)
            self.assertEqual(len(request["full_outline"]["shots"]), len(story["shots"]))
            result = copy.deepcopy(story)
            result["shots"] = [s for s in result["shots"] if s["id"] in ids]
            if corrupt:
                corrupt(result, request)
            return result
        return respond

    def test_sixty_shots_use_full_plan_and_bounded_calls_on_all_providers(self):
        value, story = self.source()
        for provider in ("openai", "claude", "ollama"):
            calls = []
            with self.subTest(provider=provider), patch("storyboard.providers.generate_json", side_effect=self.upstream(story, calls)):
                doc = engine.generate({"brief": value, "provider": provider, "model": "test"})
            engine.validate_document(doc)
            self.assertEqual(len(calls), 11)
            self.assertEqual(doc["story"]["shots"], story["shots"])
            self.assertEqual(calls[2]["previous_generated_shots"][-1], story["shots"][5])
            self.assertFalse(calls[2]["batch"]["is_final"])
            self.assertTrue(calls[-1]["batch"]["is_final"])

    def test_regeneration_skips_locked_shots_and_preserves_input(self):
        value, story = self.source(13)
        previous = engine.generate({"brief": value, "provider": "demo"})
        for index in (2, 8, 12):
            previous["story"]["shots"][index]["locked"] = True
            previous["story"]["shots"][index]["visual"] = "사용자가 고정한 화면"
        before = copy.deepcopy(previous)
        calls = []
        with patch("storyboard.providers.generate_json", side_effect=self.upstream(story, calls)):
            result = engine.generate({"brief": value, "provider": "openai", "model": "test", "previous": previous})
        self.assertEqual(previous, before)
        ids = [key for call in calls[1:] for key in call["batch"]["shot_ids"]]
        for index in (2, 8, 12):
            self.assertEqual(result["story"]["shots"][index], before["story"]["shots"][index])
            self.assertNotIn(before["story"]["shots"][index]["id"], ids)
        self.assertEqual(calls[1]["next_locked_shot"], before["story"]["shots"][2])

    def test_invalid_batch_is_not_retried_or_returned_as_partial_story(self):
        value, story = self.source(13)
        previous = engine.generate({"brief": value, "provider": "demo"})
        before = copy.deepcopy(previous)
        def corrupt(result, request):
            if request["batch"]["shot_ids"][0] == "S07":
                result["shots"][0]["id"] = "S01"
        calls = []
        with patch("storyboard.providers.generate_json", side_effect=self.upstream(story, calls, corrupt)):
            with self.assertRaisesRegex(ValidationError, "S07~S12"):
                engine.generate({"brief": value, "provider": "openai", "model": "test", "previous": previous})
        self.assertEqual(previous, before)
        self.assertEqual(len(calls), 3)

    def test_bad_outline_stops_before_any_batch(self):
        value, _ = self.source(13)
        with patch("storyboard.providers.generate_json", return_value={"summary": "x", "beats": ["x"], "assumptions": [], "shots": []}) as upstream:
            with self.assertRaises(ValidationError):
                batch_generation.generate(value, "openai", "test", engine.DIRECTOR)
        upstream.assert_called_once()

    def test_transport_failure_is_not_retried(self):
        value, story = self.source(13)
        calls = []
        def fail(result, request):
            raise providers.ProviderError("AI 서버 응답 시간이 초과되었습니다.")
        with patch("storyboard.providers.generate_json", side_effect=self.upstream(story, calls, fail)):
            with self.assertRaisesRegex(providers.ProviderError, "S01~S06"):
                engine.generate({"brief": value, "provider": "openai", "model": "test"})
        self.assertEqual(len(calls), 2)

    def test_batch_cannot_change_planned_timing_or_scene(self):
        value, story = self.source(13)
        for field, replacement in (("duration", 4), ("scene_id", "OTHER")):
            calls = []
            def corrupt(result, request):
                result["shots"][0][field] = replacement
            with self.subTest(field=field), patch("storyboard.providers.generate_json", side_effect=self.upstream(story, calls, corrupt)):
                with self.assertRaisesRegex(ValidationError, "S01~S06"):
                    engine.generate({"brief": value, "provider": "openai", "model": "test"})
            self.assertEqual(len(calls), 2)
