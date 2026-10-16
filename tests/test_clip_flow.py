import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import clip_flow, conversion, engine, guides, library, prompt_renderer
from storyboard.schema import ValidationError


class ClipFlowTests(unittest.TestCase):
    def setUp(self):
        brief = json.loads((Path(__file__).resolve().parent.parent / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        self.doc = engine.generate({"brief": brief, "provider": "demo"})
        for shot in self.doc["story"]["shots"]:
            shot.update(duration=7.5, dialogue=[], scene_id="same")
        self.ids = [s["id"] for s in self.doc["story"]["shots"]]
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        storage = patch.object(library, "ROOT", Path(root.name))
        storage.start()
        self.addCleanup(storage.stop)
        self.key = library.save(self.doc)["id"]
        self.payload = {"id": self.key, "selected": self.ids, "split_mode": "auto",
                        "clip_durations": {"C01": 13, "C02": 13, "C03": 13},
                        "guide_id": "minimax-h3-text", "provider": "openai", "model": "fake"}

    def line(self, text):
        return {"speaker": self.doc["brief"]["characters"][0]["id"], "text": text, "delivery": ""}

    def test_first_fitting_line_is_not_delayed_just_because_exchange_fits_later(self):
        for shot, duration in zip(self.doc["story"]["shots"], [4, 4, 4, 8]):
            shot["duration"] = duration
        self.doc["story"]["shots"][3]["dialogue"] = [self.line("あ" * 10), self.line("い" * 15)]
        plan = conversion.plan(self.doc, self.ids[:4], split_mode="fixed")
        first, second = plan["clips"]
        self.assertEqual(first["shots"][-1]["dialogue_indices"], [1])
        self.assertEqual(second["shots"][0]["dialogue_indices"], [2])
        self.assertEqual(first["shots"][-1]["source"]["dialogue"][0]["text"], "あ" * 10)

    def test_thirteen_second_budgets_and_source_stay_unchanged_while_silent_tail_shrinks(self):
        for shot in self.doc["story"]["shots"][::2]:
            shot["dialogue"] = [self.line("あ" * 20)]
        before = copy.deepcopy(self.doc)
        preview = conversion.preflight(self.doc, self.payload)[0]

        def fake(provider, model, system, user, schema):
            request = json.loads(user)
            self.assertIn("Conversational flow", system)
            self.assertEqual([c["duration"] for c in request["plan"]["clips"]], [13, 13, 13])
            draft = direction_output(request["plan"])
            for clip in draft["clips"]:
                clip["shots"][0]["pacing_weight"] = 4
                clip["shots"][1]["pacing_weight"] = .1
                clip["shots"][0]["speech_cues"] = ["Begin as the existing hand gesture continues toward the listener."]
            return draft

        with patch("storyboard.providers.generate_json", side_effect=fake) as ai:
            result = conversion.compile_prompts(self.doc, self.payload)
        ai.assert_called_once()
        self.assertEqual([c["duration"] for c in result["plan"]["clips"]], [13, 13, 13])
        self.assertEqual(self.doc, before)
        for original, final in zip(preview["clips"], result["plan"]["clips"]):
            tail = final["shots"][-1]
            self.assertLess(tail["end"] - tail["start"], 1)
            self.assertEqual(tail["end"], 13)
            self.assertEqual([s["id"] for s in original["shots"]], [s["id"] for s in final["shots"]])
        self.assertEqual([line["text"] for line in result["dialogue_manifest"]], ["あ" * 20] * 3)
        self.assertIn("Speech onset: Begin as", result["output"]["clips"][0]["prompt"])
        self.assertNotIn("Timing: 0", result["output"]["clips"][0]["prompt"])

    def test_matching_connection_is_inserted_on_both_sides_but_not_at_final_ending(self):
        plan = conversion.preflight(self.doc, self.payload)[0]
        draft = direction_output(plan)
        draft["handoffs"][0]["bridge"] = "Carry the lifted-hand response across the approved edit."
        output, _ = prompt_renderer.assemble(self.doc, plan, draft, guides.profile("minimax-h3-text"), [])
        text = draft["handoffs"][0]["bridge"]
        self.assertIn(text, output["clips"][0]["prompt"])
        self.assertIn(text, output["clips"][1]["prompt"])
        self.assertIn("not a scene ending", output["clips"][0]["prompt"])
        self.assertNotIn("Outgoing connection", output["clips"][-1]["prompt"])

    def test_continuation_cut_scene_change_and_selection_gap_are_distinct(self):
        self.doc["story"]["shots"][0]["duration"] = 20
        plan = conversion.plan(self.doc, self.ids[:1], split_mode="fixed")
        self.assertEqual(plan["handoffs"][0]["kind"], "continuous_shot")
        self.assertEqual(plan["handoffs"][0]["boundary_id"], plan["boundaries"][0]["id"])
        self.doc["story"]["shots"][0]["duration"] = 7.5
        plan = conversion.plan(self.doc, [self.ids[0], self.ids[2]], limit=8)
        self.assertEqual(plan["handoffs"], [])
        self.doc["story"]["shots"][1]["scene_id"] = "new"
        plan = conversion.plan(self.doc, self.ids[:2], limit=8)
        self.assertEqual(plan["handoffs"][0]["kind"], "scene_change")
        output, _ = prompt_renderer.assemble(self.doc, plan, direction_output(plan), None, [])
        self.assertNotIn("scene is already underway", output["clips"][1]["prompt"])

    def test_explicit_nonautomatic_timing_and_all_zero_preferences_remain_intact(self):
        plan = conversion.plan(self.doc, self.ids, split_mode="fixed")
        before = copy.deepcopy(plan)
        clip_flow.refine(plan, direction_output(plan))
        self.assertEqual(plan, before)
        plan = conversion.preflight(self.doc, self.payload)[0]
        positions = [[(s["start"], s["end"]) for s in c["shots"]] for c in plan["clips"]]
        draft = direction_output(plan)
        for clip in draft["clips"]:
            for shot in clip["shots"]:
                shot["pacing_weight"] = 0
        clip_flow.refine(plan, draft)
        self.assertEqual(positions, [[(s["start"], s["end"]) for s in c["shots"]] for c in plan["clips"]])

    def test_invalid_handoff_and_nonenglish_speech_cue_are_rejected(self):
        self.doc["story"]["shots"][0]["dialogue"] = [self.line("あ")]
        plan = conversion.preflight(self.doc, self.payload)[0]
        for issue in ("handoff", "cue", "weight"):
            draft = direction_output(plan)
            if issue == "handoff":
                draft["handoffs"] = []
            elif issue == "cue":
                draft["clips"][0]["shots"][0]["speech_cues"] = ["갑자기 말한다"]
            else:
                draft["clips"][0]["shots"][0]["pacing_weight"] = -1
            with self.assertRaises(ValidationError):
                clip_flow.refine(copy.deepcopy(plan), draft)
                prompt_renderer.assemble(self.doc, plan, draft, None, [])
