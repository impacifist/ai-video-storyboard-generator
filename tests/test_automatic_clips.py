import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import conversion, engine, library, prompt_renderer
from storyboard.schema import ValidationError


class AutomaticClipTests(unittest.TestCase):
    def setUp(self):
        brief = json.loads((Path(__file__).resolve().parent.parent / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        self.doc = engine.generate({"brief": brief, "provider": "demo"})
        for shot in self.doc["story"]["shots"]:
            shot.update(dialogue=[], duration=4, scene_id="scene")
        self.ids = [s["id"] for s in self.doc["story"]["shots"]]
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        storage = patch.object(library, "ROOT", Path(root.name))
        storage.start()
        self.addCleanup(storage.stop)
        self.key = library.save(self.doc)["id"]
        self.payload = {"id": self.key, "selected": self.ids, "split_mode": "auto",
                        "guide_id": "minimax-h3-text", "provider": "openai", "model": "fake"}

    def line(self, text):
        return {"speaker": self.doc["brief"]["characters"][0]["id"], "text": text, "delivery": ""}

    def planned(self, **overrides):
        return conversion.preflight(self.doc, {**self.payload, **overrides})[0]

    def test_shot_boundaries_instead_of_forced_fifteen_second_windows(self):
        before = copy.deepcopy(self.doc)
        plan = self.planned(selected=self.ids[:5])
        self.assertEqual(sum(c["duration"] for c in plan["clips"]), 20)
        self.assertEqual(plan["boundaries"], [])
        self.assertTrue(all(c["duration"] < 15 for c in plan["clips"]))
        self.assertEqual([s["id"] for c in plan["clips"] for s in c["shots"]], self.ids[:5])
        self.assertEqual(self.doc, before)

    def test_lookahead_avoids_a_one_second_tail(self):
        for shot, duration in zip(self.doc["story"]["shots"], [8, 7, 1]):
            shot["duration"] = duration
        plan = self.planned(selected=self.ids[:3])
        self.assertEqual([c["duration"] for c in plan["clips"]], [8, 8])
        self.assertTrue(all("content_duration" not in c for c in plan["clips"]))

    def test_dialogue_gets_time_instead_of_being_pushed_into_short_source_shot(self):
        self.doc["story"]["shots"][0]["dialogue"] = [self.line("あ" * 49)]
        before = copy.deepcopy(self.doc)
        plan = self.planned(selected=self.ids[:2])
        self.assertEqual(sum(c["duration"] for c in plan["clips"]), 15)
        first = plan["clips"][0]["shots"][0]
        self.assertEqual(first["end"] - first["start"], 11)
        self.assertEqual(plan["notes"], [])
        self.assertEqual(self.doc, before)

    def test_scene_changes_and_selection_gaps_are_not_combined(self):
        self.doc["story"]["shots"][1]["scene_id"] = "other"
        plan = self.planned(selected=[self.ids[0], self.ids[1], self.ids[3]])
        self.assertEqual(len(plan["clips"]), 3)
        self.assertEqual([c["timeline_start"] for c in plan["clips"]], [0, 4, 12])

    def test_long_shot_prefers_an_utterance_boundary_and_preserves_dialogue_once(self):
        self.doc["story"]["shots"][0].update(duration=20, dialogue=[self.line("あ" * 60), self.line("い" * 10)])
        plan = self.planned(selected=self.ids[:1])
        self.assertEqual([c["duration"] for c in plan["clips"]], [13, 8])
        self.assertEqual(len(plan["boundaries"]), 1)
        self.assertFalse(plan["notes"])
        output, manifest = prompt_renderer.assemble(self.doc, plan, direction_output(plan), None, [])
        self.assertEqual([line["text"] for line in manifest], ["あ" * 60, "い" * 10])
        self.assertEqual([line["line"] for line in manifest], [1, 2])
        self.assertTrue(all("hold the final frame" not in c["prompt"] for c in output["clips"]))

    def test_manual_length_changes_preview_compilation_and_export_without_changing_source(self):
        before = copy.deepcopy(self.doc)
        for guide in ("minimax-h3-text", "seedance-2-text"):
            payload = {**self.payload, "guide_id": guide, "clip_durations": {"C01": 10}}
            preview = self.planned(guide_id=guide, clip_durations={"C01": 10})

            def fake(provider, model, system, user, schema):
                request = json.loads(user)
                self.assertIn("APPROVED CONVERSION TIMING", system)
                self.assertEqual(request["plan"], preview)
                return direction_output(request["plan"])

            with patch("storyboard.providers.generate_json", side_effect=fake):
                result = conversion.compile_prompts(self.doc, payload)
            first = result["plan"]["clips"][0]
            self.assertEqual(first["duration"], 10)
            self.assertEqual(first["shots"][-1]["end"], 10)
            self.assertTrue(first["manually_adjusted"])
            self.assertIn("C01 | 10s", prompt_renderer.export_text(result))
            self.assertIn("Timing: ", result["output"]["clips"][0]["prompt"])
        self.assertEqual(self.doc, before)

    def test_fractional_rounding_is_performance_time_not_dead_frame_padding(self):
        self.doc["story"]["shots"][0]["duration"] = 7.4
        plan = self.planned(selected=self.ids[:1])
        self.assertEqual(plan["clips"][0]["duration"], 8)
        self.assertEqual(plan["clips"][0]["shots"][0]["end"], 8)
        self.assertNotIn("content_duration", plan["clips"][0])

    def test_impossible_long_utterance_is_disclosed_without_shortening_or_duplicating_it(self):
        self.doc["story"]["shots"][0]["dialogue"] = [self.line("あ" * 100)]
        plan = self.planned(selected=self.ids[:1])
        self.assertTrue(plan["notes"])
        lines = [line["text"] for c in plan["clips"] for s in c["shots"] for line in s["source"]["dialogue"]]
        self.assertEqual(lines, ["あ" * 100])
        self.assertTrue(all(4 <= c["duration"] <= 15 for c in plan["clips"]))

    def test_invalid_overrides_stop_before_ai(self):
        for value in (None, [], {"C99": 10}, {"C01": True}, {"C01": 3}, {"C01": 16},
                      {"C01": 5.5}, {"C01": float("nan")}, {"C01": "10"}):
            with self.subTest(value=value), patch("storyboard.providers.generate_json") as ai:
                with self.assertRaises(ValidationError):
                    conversion.compile_prompts(self.doc, {**self.payload, "clip_durations": value})
                ai.assert_not_called()
