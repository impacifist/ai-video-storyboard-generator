"""Synthetic, non-user-content regressions for multi-character attribution."""

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import conversion, engine, guides, prompt_renderer, speech
from storyboard.schema import ValidationError, validate

ROOT = Path(__file__).resolve().parents[1]
TARGETS = tuple(guides.PROFILES)


class SpeakerBindingTests(unittest.TestCase):
    def setUp(self):
        brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        brief["characters"] = [dict(brief["characters"][0], id=f"person{i}", name=f"인물{i}") for i in range(1, 4)]
        self.doc = engine.generate({"brief": brief, "provider": "demo"})
        for shot in self.doc["story"]["shots"]:
            shot["duration"] = 5
            shot["dialogue"] = []
        self.lines = [
            {"speaker": "person3", "text": "こんにちは。", "delivery": ""},
            {"speaker": "person1", "text": "반갑습니다!", "delivery": ""},
            {"speaker": "person3", "text": "Character 1 is a label, not my speaker.", "delivery": ""},
        ]
        self.doc["story"]["shots"][0]["dialogue"] = copy.deepcopy(self.lines)
        self.doc["story"]["shots"][3]["dialogue"] = [dict(self.lines[0], speaker="person1")]
        self.plan = conversion.plan(self.doc, [s["id"] for s in self.doc["story"]["shots"]], split_mode="fixed")

    def assets(self, target):
        if not target.endswith("reference"):
            return []
        label = (lambda i: f"<Picture {i}>") if target.startswith("minimax") else (lambda i: f"Image {i}")
        return [{"character_id": person, "label": label(i), "note": "", "role": role}
                for i, (person, role) in enumerate([("person3", "face"), ("person1", "appearance"),
                                                    ("person3", "outfit"), ("", "environment")], 1)]

    def test_every_target_preserves_exact_speaker_words_order_and_source(self):
        original = copy.deepcopy(self.doc)
        for target in TARGETS:
            with self.subTest(target=target):
                assets = self.assets(target)
                draft = direction_output(self.plan, assets)
                draft["clips"][0]["shots"][0]["direction"] = "Character 3 greets Character 1 while Character 2 listens."
                before = copy.deepcopy(draft)
                output, manifest = prompt_renderer.assemble(self.doc, self.plan, draft, guides.profile(target), assets)
                self.assertEqual([(m["speaker"], m["text"]) for m in manifest[:3]],
                                 [(line["speaker"], line["text"]) for line in self.lines])
                first = output["clips"][0]["prompt"]
                self.assertIn(self.lines[2]["text"], first)  # Never normalize spoken Character aliases.
                for line in self.lines:
                    self.assertEqual(first.count(line["text"]), 1)
                self.assertIn("without speaking or lip-syncing it", first)
                if target == "minimax-h3-reference":
                    self.assertIn("<Subject 3> (S1) says", first)
                    self.assertIn("<Subject 1> (S2) says", first)
                    self.assertIn("<Subject 3> greets <Subject 1> while <Subject 2> listens.", first)
                    self.assertIn("<Subject 2> is Character 2.", first)  # No image required for every actor.
                    self.assertIn("<Subject 3> Character 3 — <Picture 1>", first)
                    self.assertIn("<Subject 3> Character 3 — <Picture 3>", first)
                    self.assertNotIn("<Subject 4>", first)  # Background is not another actor.
                    self.assertIn("<Subject 1> (S1) says", output["clips"][1]["prompt"])
                elif target == "seedance-2-reference":
                    self.assertIn("Character 3 (appearance from Image 1, Image 3) says", first)
                    self.assertNotIn("<Subject", first)
                    self.assertNotIn("(S1)", first)
                elif target.startswith("ltx"):
                    self.assertIn('Character 3 says in Japanese: "こんにちは。"', first)
                    for marker in ("<Subject", "<Picture", "[Shot", "(S1)"):
                        self.assertNotIn(marker, first)
                self.assertEqual(draft, before)
        self.assertEqual(self.doc, original)

    def test_wrong_speaker_and_explicit_other_actor_cues_are_rejected_for_all_targets(self):
        for target in TARGETS:
            for issue in ("wrong-speaker", "other-actor", "missing", "bad-mode"):
                with self.subTest(target=target, issue=issue):
                    assets = self.assets(target)
                    draft = direction_output(self.plan, assets)
                    cue = draft["clips"][0]["shots"][0]["speech_cues"][0]
                    if issue == "wrong-speaker":
                        cue["speaker"] = "person1"
                    elif issue == "other-actor":
                        cue["onset"] = "Character 1 opens their mouth and starts speaking."
                    elif issue == "missing":
                        draft["clips"][0]["shots"][0]["speech_cues"].pop()
                    else:
                        cue["mode"] = "invented"
                    with self.assertRaisesRegex(ValidationError, "speech_cues"):
                        prompt_renderer.assemble(self.doc, self.plan, draft, guides.profile(target), assets)

    def test_offscreen_and_voiceover_never_assign_lips_to_the_visible_listener(self):
        for target in TARGETS:
            for mode in ("on_screen", "off_screen", "voiceover"):
                with self.subTest(target=target, mode=mode):
                    assets = self.assets(target)
                    draft = direction_output(self.plan, assets)
                    draft["clips"][0]["shots"][0]["speech_cues"][0]["mode"] = mode
                    draft["clips"][0]["shots"][0]["camera"]["layout"] = "The listener occupies the frame."
                    output, manifest = prompt_renderer.assemble(self.doc, self.plan, draft, guides.profile(target), assets)
                    text = output["clips"][0]["prompt"]
                    self.assertIn({"on_screen": "says on screen", "off_screen": "says off-screen",
                                   "voiceover": "says in an off-screen voiceover"}[mode], text)
                    if mode == "voiceover":
                        self.assertIn("on-screen lips remain completely closed", text)
                    elif mode == "off_screen":
                        self.assertIn("speaker remains outside the frame", text)
                    self.assertEqual(manifest[0]["speaker"], "person3")

    def test_unknown_speakers_rejected_by_dynamic_schema(self):
        draft = direction_output(self.plan)
        draft["clips"][0]["shots"][0]["speech_cues"][0]["speaker"] = "unknown"
        with self.assertRaisesRegex(ValidationError, "speaker"):
            validate(draft, prompt_renderer.output_schema(self.doc, self.plan))

    def test_bounded_repair_corrects_binding_without_changing_source_for_each_model(self):
        for target in ("minimax-h3-text", "ltx-2.5-text", "seedance-2-text"):
            with self.subTest(target=target):
                valid = direction_output(self.plan)
                invalid = copy.deepcopy(valid)
                invalid["clips"][0]["shots"][0]["speech_cues"][0]["speaker"] = "person1"
                plan = copy.deepcopy(self.plan)
                before = copy.deepcopy(self.doc)
                with patch("storyboard.providers.generate_json", side_effect=[invalid, valid]) as ai:
                    _, _, manifest, report = conversion.compile_directions(
                        self.doc, plan, guides.profile(target), [], "openai", "mock", "", {"plan": plan})
                self.assertEqual(ai.call_count, 2)
                self.assertTrue(report["repaired"])
                self.assertIn("speech_cues[0].speaker", report["issues"][0])
                self.assertEqual(manifest[0]["speaker"], "person3")
                self.assertEqual(self.doc, before)

    def test_ltx_duplicate_names_still_have_distinct_speaker_labels(self):
        names = {"a": "Alex [a]", "b": "Alex [b]", "c": "Robin [c]"}
        self.assertEqual(speech.prose_labels(names), {"a": "Alex (Character 1)", "b": "Alex (Character 2)", "c": "Robin"})


if __name__ == "__main__":
    unittest.main()
