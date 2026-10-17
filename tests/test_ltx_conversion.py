"""LTX contracts: exact dialogue, prose, image semantics and continuity."""

import copy
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import conversion, engine, guides, library, prompt_renderer
from storyboard.schema import ValidationError

ROOT = Path(__file__).resolve().parents[1]


class LTXConversionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = patch.object(library, "ROOT", Path(temporary.name))
        root.start()
        self.addCleanup(root.stop)
        brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        self.document = engine.generate({"brief": brief, "provider": "demo"})
        for shot, duration in zip(self.document["story"]["shots"], [4, 4, 4, 5, 7, 6]):
            shot["duration"] = duration
        self.document["story"]["shots"][0]["dialogue"][0]["text"] = "まだ降ってるね。"
        self.key = library.save(self.document)["id"]
        self.payload = {"id": self.key, "selected": [s["id"] for s in self.document["story"]["shots"]],
                        "guide_id": "ltx-2.5-text", "split_mode": "fixed", "limit": 15,
                        "provider": "openai", "model": "fake", "references": []}

    def generate(self, provider, model, system, user, schema):
        data = json.loads(user)
        self.assertIn("LTX 2.5 direction compiler policy", system)
        self.assertNotIn("H3 animation direction supplement", system)
        self.assertEqual(data["target_model"], "LTX 2.5")
        return direction_output(data["plan"])

    def test_text_and_image_modes_preserve_dialogue_in_prose_and_exports(self):
        original = copy.deepcopy(self.document)
        for mode in ("text", "image"):
            with self.subTest(mode=mode):
                self.payload["guide_id"] = f"ltx-2.5-{mode}"
                with patch("storyboard.providers.generate_json", side_effect=self.generate) as ai:
                    result = conversion.compile_prompts(self.document, self.payload)
                ai.assert_called_once()
                self.assertEqual([c["duration"] for c in result["plan"]["clips"]], [15, 15])
                self.assertEqual(result["guide_checked_at"], "2026-10-18")
                self.assertEqual(result["references"], [])
                prompts = [c["prompt"] for c in result["output"]["clips"]]
                self.assertIn('says in Japanese, Very quietly: "まだ降ってるね。"', prompts[0])
                self.assertIn("transitions as follows", prompts[0])
                self.assertIn("without a cut or replay", prompts[1])
                self.assertIn("without an added pause", prompts[0])
                for prompt in prompts:
                    for forbidden in ("[Shot", "<d>", "<Picture", "<Subject", "Incoming connection", "shared boundary", "00:"):
                        self.assertNotIn(forbidden, prompt)
                    self.assertNotIn("\n", prompt)
                exported = prompt_renderer.export_text(result)
                counts = Counter(entry["text"] for entry in result["dialogue_manifest"])
                for entry in result["dialogue_manifest"]:
                    self.assertEqual(sum(p.count(f'"{entry["text"]}"') for p in prompts), counts[entry["text"]])
                    self.assertIn(entry["text"], exported)
                self.assertEqual(self.document, original)
                if mode == "image":
                    self.assertIn("IMAGE-TO-VIDEO", ai.call_args.args[2])

    def test_image_mode_does_not_accept_identity_reference_attachments(self):
        self.payload.update(guide_id="ltx-2.5-image", references=[{"id": "unused"}])
        with patch("storyboard.providers.generate_json") as ai, self.assertRaises(ValidationError):
            conversion.compile_prompts(self.document, self.payload)
        ai.assert_not_called()

    def test_english_policy_and_other_model_syntax_cannot_leak(self):
        layout = conversion.plan(self.document, self.payload["selected"], split_mode="fixed")
        for bad in ("カメラが動く。", "[Shot 1] A camera moves.", "<Subject 1> turns.", "Image 1 shows a face."):
            with self.subTest(bad=bad):
                draft = direction_output(layout)
                draft["clips"][0]["shots"][0]["direction"] = bad
                with self.assertRaises(ValidationError):
                    prompt_renderer.assemble(self.document, layout, draft, guides.profile("ltx-2.5-text"), [])

    def test_ltx_policy_is_versioned_in_profile_hash(self):
        profile = guides.profile("ltx-2.5-image")
        system = guides.ROOT / "ltx-system.md"
        with patch.object(guides.Path, "read_text", autospec=True) as read:
            read.side_effect = lambda path, **kwargs: Path.read_bytes(path).decode("utf-8") + ("\nChanged policy." if path == system else "")
            self.assertNotEqual(profile["sha256"], guides.profile(profile["id"])["sha256"])

    def test_camera_of_split_source_is_bound_once(self):
        layout = conversion.plan(self.document, self.payload["selected"], split_mode="fixed")
        draft = direction_output(layout)
        draft["clips"][0]["shots"][-1]["camera"]["movement"] = "A slow push toward the listener"
        draft["clips"][1]["shots"][0]["camera"]["movement"] = "A contradictory orbit"
        output, _ = prompt_renderer.assemble(self.document, layout, draft, guides.profile("ltx-2.5-text"), [])
        self.assertIn("A slow push toward the listener", output["clips"][1]["prompt"])
        self.assertNotIn("A contradictory orbit", output["clips"][1]["prompt"])
