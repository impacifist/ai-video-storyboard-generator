import copy
import json
import unittest
from pathlib import Path

from conversion_fixtures import direction_output
from storyboard import conversion, engine, guides, prompt_renderer
from storyboard.schema import ValidationError

ROOT = Path(__file__).resolve().parent.parent


class PromptRendererTests(unittest.TestCase):
    def setUp(self):
        brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        self.doc = engine.generate({"brief": brief, "provider": "demo"})
        self.ids = [s["id"] for s in self.doc["story"]["shots"]]

    def test_camera_and_layout_are_rendered_for_both_targets(self):
        layout = conversion.plan(self.doc, self.ids)
        for target in ("minimax-h3-text", "seedance-2-text"):
            draft = direction_output(layout)
            draft["clips"][0]["shots"][0]["camera"] = {
                "size": "Close-up on the listening character", "angle": "Eye level from the same side of the axis",
                "movement": "Locked camera", "transition": "Hard cut after the listener looks up",
                "layout": "Character 2 occupies the right third, looking screen-left; leave space toward the gaze."}
            before = copy.deepcopy(draft)
            output, _ = prompt_renderer.assemble(self.doc, layout, draft, guides.profile(target), [])
            prompt = output["clips"][0]["prompt"]
            for value in draft["clips"][0]["shots"][0]["camera"].values():
                self.assertIn(value, prompt)
            self.assertEqual(draft, before)

    def test_split_preserves_camera_view_and_delays_transition_until_source_shot_ends(self):
        for shot, seconds in zip(self.doc["story"]["shots"], [8, 8, 8, 2, 2, 2]):
            shot["duration"] = seconds
        layout = conversion.plan(self.doc, self.ids, split_mode="fixed")
        draft = direction_output(layout)
        for clip in draft["clips"]:
            for shot in clip["shots"]:
                if shot["id"] == "S02":
                    shot["camera"]["transition"] = "Hard cut on the sleeve release"
                    shot["camera"]["movement"] = "Locked camera on the listener"
        draft["clips"][1]["shots"][0]["camera"]["movement"] = "Unrequested orbit around the listener"
        output, _ = prompt_renderer.assemble(self.doc, layout, draft, guides.profile("minimax-h3-text"), [])
        first, second = [clip["prompt"] for clip in output["clips"]]
        self.assertNotIn("Hard cut on the sleeve release", first)
        self.assertIn("without an edit or camera reset", first)
        self.assertIn("Hard cut on the sleeve release", second)
        self.assertIn("do not replay its opening or add a cut", second)
        self.assertIn("Locked camera on the listener", first)
        self.assertIn("Locked camera on the listener", second)
        self.assertNotIn("Unrequested orbit", second)

    def test_camera_fields_cannot_be_missing_empty_non_english_or_contain_speech(self):
        layout = conversion.plan(self.doc, self.ids)
        for invalid in (None, "", "카메라 고정", "<d>[English] Invented speech</d>"):
            draft = direction_output(layout)
            camera = draft["clips"][0]["shots"][0]["camera"]
            if invalid is None:
                del camera["movement"]
            else:
                camera["movement"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                prompt_renderer.assemble(self.doc, layout, draft, guides.profile("minimax-h3-text"), [])

    def test_director_outputs_no_speech_but_all_original_lines_are_assembled(self):
        # Whitespace, punctuation, multilingual words and short lines are kept literally.
        unusual = ['  응…  정말?\n"Yes..." 日本語も!  ', "a", "I", "좋아!"]
        a, b = [c["id"] for c in self.doc["brief"]["characters"]]
        self.doc["story"]["shots"][0]["dialogue"] = [
            {"speaker": speaker, "text": text, "delivery": "아주 조용히"}
            for speaker, text in zip([b, a, b, a], unusual)]
        before = copy.deepcopy(self.doc)
        layout = conversion.plan(self.doc, self.ids, split_mode="fixed")
        for key in (None, "seedance-2-text", "minimax-h3-text"):
            profile = guides.profile(key) if key else None
            draft = direction_output(layout)
            output, manifest = prompt_renderer.assemble(self.doc, layout, draft, profile, [])
            self.assertEqual([d["text"] for d in manifest[:4]], unusual)
            self.assertEqual([d["speaker"] for d in manifest[:4]], [b, a, b, a])
            for text in unusual:
                self.assertIn(text, output["clips"][0]["prompt"])
            prompt = output["clips"][0]["prompt"]
            if key == "minimax-h3-text":
                self.assertIn("(S1) Character 2", prompt)
                self.assertIn("(S2) Character 1", prompt)
                self.assertEqual(prompt.count("<d>"), len([d for d in manifest if d["clip_id"] == "C01"]))
                self.assertIn("[Shot 2] At 00:05.000,", prompt)
            self.assertNotIn("prompt", draft["clips"][0])
        self.assertEqual(self.doc, before)

    def test_split_shot_dialogue_is_assigned_once_in_all_rendered_clips(self):
        for shot, seconds in zip(self.doc["story"]["shots"], [8, 8, 8, 2, 2, 2]):
            shot["duration"] = seconds
        layout = conversion.plan(self.doc, self.ids, split_mode="fixed")
        output, manifest = prompt_renderer.assemble(self.doc, layout, direction_output(layout),
                                                   guides.profile("minimax-h3-text"), [])
        expected = [d["text"] for s in self.doc["story"]["shots"] for d in s["dialogue"] if d["text"]]
        self.assertEqual([d["text"] for d in manifest], expected)
        self.assertEqual(len(output["clips"]), 2)
        for item in manifest:
            prompt = next(c["prompt"] for c in output["clips"] if c["id"] == item["clip_id"])
            self.assertIn(item["text"], prompt)

    def test_director_cannot_supply_changed_dialogue_or_replace_entire_prompt(self):
        layout = conversion.plan(self.doc, self.ids)
        for injected in ('<d>[English]Changed speech</d>', '{invented speech}', '(S9) Hello'):
            draft = direction_output(layout)
            draft["clips"][0]["shots"][0]["direction"] = injected
            with self.assertRaises(ValidationError):
                prompt_renderer.assemble(self.doc, layout, draft, None, [])
        draft = direction_output(layout)
        draft["clips"][0]["shots"][0]["text"] = "AI rewrote this"
        with self.assertRaises(ValidationError):
            prompt_renderer.assemble(self.doc, layout, draft, None, [])

    def test_missing_reordered_and_empty_directions_rejected(self):
        layout = conversion.plan(self.doc, self.ids)
        for modification in ("missing", "reordered", "empty"):
            draft = direction_output(layout)
            if modification == "missing":
                draft["clips"][0]["shots"].pop()
            elif modification == "reordered":
                draft["clips"][0]["shots"].reverse()
            else:
                draft["clips"][0]["shots"][0]["direction"] = " "
            with self.assertRaises(ValidationError):
                prompt_renderer.assemble(self.doc, layout, draft, None, [])
