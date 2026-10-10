"""English instructions across rendering/export, with verbatim multilingual speech."""

import copy
import json
import re
import unittest
from pathlib import Path

from conversion_fixtures import direction_output
from storyboard import conversion, engine, guides, prompt_renderer
from storyboard.schema import ValidationError

ROOT = Path(__file__).resolve().parent.parent


class EnglishOutputTests(unittest.TestCase):
    def setUp(self):
        brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        brief["characters"][0].update(id="소녀1", name="소라")
        brief["characters"][1].update(id="소녀2", name="ハル")
        self.document = engine.generate({"brief": brief, "provider": "demo"})
        for shot, duration in zip(self.document["story"]["shots"], [4, 4, 4, 5, 7, 6]):
            shot["duration"] = duration
            shot["dialogue"] = [{"speaker": "소녀1", "text": "안녕! こんにちは。", "delivery": "아주 조용히"}]
        for key in ("start_state", "end_state"):
            self.document["story"]["shots"][3][key]["props"] = [
                {"name": "휴대전화", "holder": "소녀1", "position": "오른손"}]
        ids = [s["id"] for s in self.document["story"]["shots"]]
        self.layout = conversion.plan(self.document, ids, split_mode="fixed")
        self.assets = [{"label": "<Picture 1>", "character_id": "소녀1", "role": "outfit", "note": "빨간 재킷만 참조"}]

    def test_all_rendered_instruction_channels_are_english(self):
        before = copy.deepcopy(self.document)
        for key in (None, "seedance-2-reference", "minimax-h3-reference"):
            with self.subTest(key=key):
                draft = direction_output(self.layout, self.assets)
                draft["reference_notes"][0]["note"] = "Use only the red jacket as an outfit reference."
                output, manifest = prompt_renderer.assemble(self.document, self.layout, draft,
                    guides.profile(key) if key else None, self.assets)
                for clip in output["clips"]:
                    directions = clip["prompt"]
                    for line in manifest:
                        if line["clip_id"] == clip["id"]:
                            self.assertIn(line["text"], clip["prompt"])
                            directions = directions.replace(line["text"], "")
                    prompt_renderer.require_english(directions, "final prompt outside dialogue")
                    self.assertIn("Character 1", directions)
                    self.assertIn("Very quietly", directions)
                    self.assertIn("red jacket", directions)
                    self.assertNotIn("아주 조용히", directions)
                self.assertTrue(all("Character 1" in c["prompt"] for c in output["clips"]))
        self.assertEqual(self.document, before)

    def test_non_english_output_in_each_instruction_slot_is_rejected(self):
        draft = direction_output(self.layout, self.assets)
        slots = [
            (draft["clips"][0], "context"), (draft["clips"][0], "subject_definitions"),
            (draft["clips"][0], "summary"), (draft["clips"][0], "retention_analysis"),
            (draft["clips"][0], "overall_soundscape"), (draft["clips"][0], "non_diegetic_music"),
            (draft["clips"][0]["shots"][0], "direction"),
            (draft["clips"][0]["shots"][0]["deliveries"], 0),
            (draft["reference_notes"][0], "note"),
            (draft["boundaries"][0]["state"]["characters"][0], "pose"),
            (draft["boundaries"][0]["state"]["props"][0], "english_name"),
            (draft["boundaries"][0]["state"]["props"][0], "position")]
        for container, key in slots:
            original = container[key]
            container[key] = "Close-up. 작은 미소 / 小さな笑顔"
            with self.subTest(key=key), self.assertRaisesRegex(ValidationError, "English-only"):
                prompt_renderer.assemble(self.document, self.layout, draft, None, self.assets)
            container[key] = original

    def test_english_export_headers_notes_references_and_spoken_exception(self):
        draft = direction_output(self.layout, self.assets)
        output, manifest = prompt_renderer.assemble(self.document, self.layout, draft,
            guides.profile("minimax-h3-reference"), self.assets)
        result = {"target_model": "직접 입력 모델", "output_language": "english_except_dialogue", "output": output,
                  "plan": self.layout, "english_reference_notes": draft["reference_notes"],
                  "render_labels": prompt_renderer.render_labels(self.document),
                  "references": [{**self.assets[0], "order": 1, "name": "의상 이미지.png"}]}
        text = prompt_renderer.export_text(result)
        spoken = re.findall(r"<d>\[[A-Za-z]+\] ([\s\S]*?)</d>", text)
        self.assertEqual(spoken, [d["text"] for d in manifest])
        without_speech = re.sub(r"<d>\[[A-Za-z]+\] [\s\S]*?</d>", "", text)
        prompt_renderer.require_english(without_speech, "export")
        self.assertIn("REFERENCE ATTACHMENT ORDER", text)
        self.assertIn("Custom video model", text)
        self.assertNotIn("의상 이미지", text)
        self.assertNotIn("빨간 재킷", text)

    def test_legacy_export_requires_reconversion(self):
        with self.assertRaisesRegex(ValidationError, "다시 변환"):
            prompt_renderer.export_text({"output": {"clips": []}})
