import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyboard import conversion, engine, library, prompt_renderer
from storyboard.schema import ValidationError
from conversion_fixtures import direction_output

ROOT = Path(__file__).resolve().parent.parent


class LibraryConversionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = patch.object(library, "ROOT", Path(self.temporary.name))
        self.root.start()
        self.addCleanup(self.root.stop)
        brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        self.document = engine.generate({"brief": brief, "provider": "demo"})
        self.ids = [s["id"] for s in self.document["story"]["shots"]]

    def test_snapshots_persist_separately_and_restore(self):
        original = library.save(self.document)
        edited = copy.deepcopy(self.document)
        edited["story"]["summary"] = "편집한 사본"
        second = library.save(edited)
        self.assertNotEqual(original["id"], second["id"])
        self.assertEqual(library.load(original["id"]), self.document)
        self.assertEqual(len(library.listing()), 2)
        library.trash(original["id"])
        with self.assertRaises(ValidationError):
            library.load(original["id"])
        self.assertEqual(len(library.listing(True)), 1)
        library.trash(original["id"], False)
        self.assertEqual(library.load(original["id"]), self.document)

    def test_path_traversal_and_bad_documents_rejected(self):
        for key in ("../private", "a" * 31, None, "' OR 1=1"):
            with self.assertRaises(ValidationError):
                library.load(key)
        with self.assertRaises(ValidationError):
            library.save({})
        self.assertEqual(library.listing(), [])

    def test_split_covers_all_shots_once_with_local_timestamps(self):
        before = copy.deepcopy(self.document)
        plan = conversion.plan(self.document, self.ids)
        self.assertEqual([s["id"] for c in plan["clips"] for s in c["shots"]], self.ids)
        self.assertEqual(sum(c["duration"] for c in plan["clips"]),
                         sum(s["duration"] for s in self.document["story"]["shots"]))
        for clip in plan["clips"]:
            self.assertLessEqual(clip["duration"], 15)
            self.assertEqual(clip["shots"][0]["start"], 0)
            self.assertEqual(clip["shots"][-1]["end"], clip["duration"])
        self.assertEqual(self.document, before)

    def test_scene_and_selection_gaps_force_boundaries(self):
        self.document["story"]["shots"][1]["scene_id"] = "another"
        plan = conversion.plan(self.document, self.ids[:2] + self.ids[3:4])
        self.assertEqual(len(plan["clips"]), 3)

    def test_fixed_30_seconds_split_15_15_across_shots_and_scenes(self):
        for shot, duration in zip(self.document["story"]["shots"], [8, 8, 8, 2, 2, 2]):
            shot["duration"] = duration
        self.document["story"]["shots"][1]["scene_id"] = "another"
        before = copy.deepcopy(self.document)
        layout = conversion.plan(self.document, self.ids, split_mode="fixed")
        self.assertEqual([c["duration"] for c in layout["clips"]], [15, 15])
        self.assertEqual([(c["timeline_start"], c["timeline_end"]) for c in layout["clips"]], [(0, 15), (15, 30)])
        first, second = layout["clips"]
        self.assertTrue(first["shots"][-1]["continues_in_next"])
        self.assertTrue(second["shots"][0]["continues_from_previous"])
        self.assertEqual(second["shots"][0]["source_offset"], 7)
        self.assertEqual(second["shots"][0]["source"]["dialogue"], [])
        expected = [line for s in self.document["story"]["shots"] for line in s["dialogue"]]
        actual = [line for c in layout["clips"] for s in c["shots"] for line in s["source"]["dialogue"]]
        self.assertEqual(actual, expected)
        self.assertEqual(self.document, before)

    def test_fixed_long_shot_continuations_and_selection_gaps(self):
        self.document["story"]["shots"][0]["duration"] = 30
        layout = conversion.plan(self.document, [self.ids[0]], split_mode="fixed")
        self.assertEqual([c["duration"] for c in layout["clips"]], [15, 15])
        self.assertEqual(layout["clips"][1]["shots"][0]["source_offset"], 15)
        layout = conversion.plan(self.document, [self.ids[1], self.ids[3]], split_mode="fixed")
        self.assertEqual(len(layout["clips"]), 2)
        with self.assertRaises(ValidationError):
            conversion.plan(self.document, self.ids, split_mode="unknown")

    def test_partial_twelve_second_plan_uses_global_brief_only_as_context(self):
        for shot in self.document["story"]["shots"][:3]:
            shot["duration"] = 4
        payload = {**self.payload(), "selected": self.ids[:3]}

        def compile_subset(provider, model, system, user, schema):
            data = json.loads(user)
            self.assertEqual(data["brief"]["duration"], 30)
            self.assertEqual(data["scope"]["planned_duration"], 12)
            self.assertTrue(data["scope"]["partial_selection"])
            self.assertIn("not a guide violation", system)
            self.assertIn("global context", system)
            return direction_output(data["plan"])

        key = library.save(self.document)["id"]
        for guide_id in (None, "seedance-2-text", "minimax-h3-text"):
            with self.subTest(guide_id=guide_id), patch.object(
                    conversion.providers, "generate_json", side_effect=compile_subset):
                result = conversion.compile_prompts(self.document, {**payload, "id": key, "guide_id": guide_id})
            self.assertEqual(len(result["output"]["clips"]), 1)
            self.assertEqual(result["plan"]["clips"][0]["duration"], 12)

    def test_invalid_selection_limits_and_long_shots_blocked(self):
        for selected, limit in (([], 15), (["unknown"], 15), ([self.ids[0]] * 2, 15),
                                (self.ids, 16), (self.ids, True), (self.ids, float("nan"))):
            with self.assertRaises(ValidationError):
                conversion.plan(self.document, selected, limit)
        self.document["story"]["shots"][0]["duration"] = 16
        with self.assertRaisesRegex(ValidationError, "먼저"):
            conversion.plan(self.document, self.ids)

    def payload(self):
        return {"selected": self.ids, "target_model": "test-video-v1", "guide_source": "test guide v1",
                "guide": "Use timeline. Preserve dialogue.", "provider": "openai", "model": "test-llm"}

    def output(self):
        layout = conversion.plan(self.document, self.ids)
        return direction_output(layout)

    def test_compilation_persists_guide_provenance_and_original(self):
        saved = library.save(self.document)
        with patch.object(conversion.providers, "generate_json", return_value=self.output()):
            result = conversion.compile_prompts(self.document, self.payload())
        library.save_conversion(saved["id"], result)
        self.assertEqual(library.conversions(saved["id"])[0]["result"], result)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(library.load(saved["id"]), self.document)
        library.trash(saved["id"])
        with self.assertRaises(ValidationError):
            library.save_conversion(saved["id"], result)
        library.trash(saved["id"], False)
        self.assertEqual(len(library.conversions(saved["id"])), 1)

    def test_saved_v3_prompt_still_loads_and_exports_without_camera_response_fields(self):
        saved = library.save(self.document)
        legacy = {"assembly_version": 3, "output_language": "english_except_dialogue",
                  "target_model": "MiniMax H3", "plan": {"clips": [{"id": "C01", "duration": 15}]},
                  "output": {"clips": [{"id": "C01", "prompt": "Previously approved animation prompt."}]}}
        library.save_conversion(saved["id"], legacy)
        loaded = library.conversions(saved["id"])[0]["result"]
        self.assertEqual(loaded, legacy)
        self.assertIn("Previously approved animation prompt.", prompt_renderer.export_text(loaded))

    def test_bad_ai_clip_mapping_missing_shots_and_conflicts_blocked(self):
        bad_id, bad_dialogue, conflict = self.output(), self.output(), self.output()
        bad_id["clips"][0]["id"] = "wrong"
        bad_dialogue["clips"][0]["shots"].pop()
        conflict["warnings"] = ["guide duration conflict"]
        for output in (bad_id, bad_dialogue, conflict):
            with patch.object(conversion.providers, "generate_json", return_value=output):
                with self.assertRaises(ValidationError):
                    conversion.compile_prompts(self.document, self.payload())

    def test_missing_guide_prevents_paid_request(self):
        with patch.object(conversion.providers, "generate_json") as request:
            payload = self.payload()
            payload["guide"] = ""
            with self.assertRaises(ValidationError):
                conversion.compile_prompts(self.document, payload)
            request.assert_not_called()
