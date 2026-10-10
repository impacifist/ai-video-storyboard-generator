import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import conversion, engine, guides, library, prompt_renderer
from storyboard.schema import ValidationError

ROOT = Path(__file__).resolve().parent.parent


class ClipPlanningTests(unittest.TestCase):
    def setUp(self):
        brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        self.doc = engine.generate({"brief": brief, "provider": "demo"})
        self.ids = [s["id"] for s in self.doc["story"]["shots"]]
        for s, duration in zip(self.doc["story"]["shots"], [4, 4, 4, 5, 7, 6]):
            s["duration"] = duration
        self.shot = self.doc["story"]["shots"][3]
        self.shot["dialogue"] = [{"speaker": self.doc["brief"]["characters"][0]["id"],
                                  "text": "あ" * 49, "delivery": "自然な速さ"}]

    def test_source_start_is_not_reapplied_at_three_second_offset(self):
        before = copy.deepcopy(self.doc)
        layout = conversion.plan(self.doc, self.ids, split_mode="fixed")
        first, second = layout["clips"]
        end, start = first["shots"][-1], second["shots"][0]
        self.assertEqual(start["source_offset"], 3)
        self.assertNotIn("end_state", end["source"])
        self.assertNotIn("start_state", start["source"])
        self.assertEqual(end["exit_boundary_id"], start["entry_boundary_id"])
        draft = direction_output(layout)
        shared = draft["boundaries"][0]["state"]
        shared["characters"][0]["pose"] = "Holding the phone in one hand mid-gesture"
        output, _ = prompt_renderer.assemble(self.doc, layout, draft, guides.profile("minimax-h3-text"), [])
        left = output["clips"][0]["prompt"].split("End at shared boundary B01: ")[1].split("\n")[0]
        right = output["clips"][1]["prompt"].split("Start at shared boundary B01: ")[1].split("\n")[0]
        self.assertEqual(left, right)
        self.assertIn("Holding the phone in one hand", right)
        self.assertEqual(self.doc, before)

    def test_dialogue_moves_to_larger_fitting_segment_once(self):
        # S04 is 3 seconds before the boundary and 5 seconds after it.
        self.shot["duration"] = 8
        self.shot["dialogue"][0]["text"] = "あ" * 20
        layout = conversion.plan(self.doc, self.ids[:4], split_mode="fixed")
        first, second = layout["clips"]
        self.assertEqual(first["shots"][-1]["source"]["dialogue"], [])
        self.assertEqual(second["shots"][0]["source"]["dialogue"], self.shot["dialogue"])
        self.assertEqual(second["shots"][0]["dialogue_indices"], [1])
        self.assertFalse(any("S04" in note for note in layout["notes"]))

    def test_multiple_lines_keep_original_order_and_line_ids(self):
        self.shot["dialogue"] = [{**self.shot["dialogue"][0], "text": "あ" * 15},
                                 {**self.shot["dialogue"][0], "text": "い" * 10}]
        layout = conversion.plan(self.doc, self.ids, split_mode="fixed")
        output, manifest = prompt_renderer.assemble(self.doc, layout, direction_output(layout),
                                                   guides.profile("seedance-2-text"), [])
        lines = [d for d in manifest if d["shot_id"] == "S04"]
        self.assertEqual([d["line"] for d in lines], [1, 2])
        self.assertEqual([d["clip_id"] for d in lines], ["C01", "C02"])
        self.assertEqual([d["text"] for d in lines], ["あ" * 15, "い" * 10])
        self.assertEqual(len(output["clips"]), 2)

    def test_estimated_timing_is_saved_as_note_actual_conflicts_still_block(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(library, "ROOT", Path(temp)):
            key = library.save(self.doc)["id"]
            payload = {"id": key, "selected": self.ids, "split_mode": "fixed", "guide_id": "minimax-h3-text",
                       "provider": "openai", "model": "fake"}

            def response(provider, model, system, user, schema):
                self.assertIn("not competing constraints", system)
                self.assertIn("notes, not blocking warnings", system)
                draft = direction_output(json.loads(user)["plan"])
                draft["notes"] = ["Review actual speech pacing."]
                return draft

            with patch("storyboard.providers.generate_json", side_effect=response):
                result = conversion.compile_prompts(self.doc, payload)
            self.assertEqual(result["output"]["warnings"], [])
            self.assertTrue(any("S04" in note for note in result["output"]["notes"]))
            self.assertIn("Review actual speech pacing.", result["output"]["notes"])
            self.assertEqual(len(library.save_conversion(key, result)), 32)
            draft = direction_output(result["plan"])
            draft["warnings"] = ["A genuinely unsupported input requirement."]
            with patch("storyboard.providers.generate_json", return_value=draft), self.assertRaises(ValidationError):
                conversion.compile_prompts(self.doc, payload)

    def test_missing_or_unknown_boundary_states_rejected(self):
        layout = conversion.plan(self.doc, self.ids, split_mode="fixed")
        for issue in ("missing", "unknown-character", "invalid-holder", "speech-tag"):
            draft = direction_output(layout)
            if issue == "missing":
                draft["boundaries"] = []
            elif issue == "unknown-character":
                draft["boundaries"][0]["state"]["characters"][0]["character_id"] = "missing"
            elif issue == "invalid-holder":
                draft["boundaries"][0]["state"]["props"] = [{"name": "phone", "holder": "missing", "position": "hand"}]
            else:
                draft["boundaries"][0]["state"]["characters"][0]["pose"] = "<d>Invented speech</d>"
            with self.assertRaises(ValidationError):
                prompt_renderer.assemble(self.doc, layout, draft, None, [])

    def test_speech_mode_explicitly_extends_duration_and_preserves_original(self):
        for shot, count in zip(self.doc["story"]["shots"], [33, 39, 13, 49, 57, 32]):
            shot["dialogue"] = [{**self.shot["dialogue"][0], "text": "あ" * count}]
        before = copy.deepcopy(self.doc)
        fixed = conversion.plan(self.doc, self.ids, split_mode="fixed")
        adaptive = conversion.plan(self.doc, self.ids, split_mode="speech")
        self.assertEqual([c["duration"] for c in fixed["clips"]], [15, 15])
        self.assertEqual(adaptive["original_selected_duration"], 30)
        self.assertEqual(sum(c["duration"] for c in adaptive["clips"]), 51)
        self.assertTrue(all(c["duration"] <= 15 for c in adaptive["clips"]))
        self.assertEqual(adaptive["notes"], [])
        self.assertEqual(adaptive["source_sha256"], fixed["source_sha256"])
        self.assertEqual(self.doc, before)
