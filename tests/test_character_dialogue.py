import copy
import json
import unittest
from unittest.mock import patch

from storyboard import dialogue, engine, providers
from storyboard.schema import ValidationError, validate_brief
from test_engine import brief


class CharacterDialogueTests(unittest.TestCase):
    def test_large_proofreading_is_bounded_and_atomic_on_late_failure(self):
        source = brief()
        source.update(shot_count=25, duration=75)
        story = engine.demo_story(source)
        for shot in story["shots"]:
            shot["dialogue"][0]["text"] = "そうだったんだね。"
        before = copy.deepcopy(story)
        for failure in (False, True):
            calls = []
            def upstream(provider, model, system, user, schema):
                request = json.loads(user)
                calls.append(request)
                self.assertLessEqual(len(request["lines"]), 12)
                if failure and len(calls) == 3:
                    raise providers.ProviderError("mock timeout")
                return {"lines": [{"id": line["id"], "text": "そうだったんだね。なるほど。"} for line in request["lines"]]}
            with self.subTest(failure=failure), patch("storyboard.providers.generate_json", side_effect=upstream):
                if failure:
                    with self.assertRaises(providers.ProviderError):
                        dialogue.polish_japanese(story, source, "openai", "fake")
                else:
                    result, status = dialogue.polish_japanese(story, source, "openai", "fake")
                    self.assertEqual(status, "completed")
                    self.assertTrue(all(s["dialogue"][0]["text"].endswith("なるほど。") for s in result["shots"]))
            self.assertEqual(story, before)
            self.assertEqual(len(calls), 3)

    def setUp(self):
        self.brief = brief()
        self.brief["characters"][0].update(gender="여성", age="17세, 고등학생", speech="일본어. 친한 친구에게 편하게, 1인칭은私.")
        self.story = engine.demo_story(self.brief)
        self.story["shots"][0]["dialogue"][0]["text"] = "昨日、スマホを忘れるでした。"

    def corrected(self, provider, model, system, user, schema):
        request = json.loads(user)
        self.assertEqual(request["task"], "japanese_dialogue_proofread")
        self.assertEqual(request["brief"]["characters"][0]["age"], "17세, 고등학생")
        self.assertIn(dialogue.VOICE_RULES, system)
        return {"lines": [{"id": line["id"], "text": "昨日、スマホを忘れちゃった。" if line["id"] == "S01:D01" else line["text"]}
                          for line in request["lines"]]}

    def test_optional_traits_preserve_legacy_and_remain_strict(self):
        legacy = brief()
        before = copy.deepcopy(legacy)
        validate_brief(legacy)
        self.assertEqual(legacy, before)
        validate_brief(self.brief)
        for key, value in (("age", 17), ("gender", []), ("unknown", "value")):
            invalid = copy.deepcopy(self.brief)
            invalid["characters"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                validate_brief(invalid)

    def test_generated_japanese_gets_one_text_only_pass_and_retains_character_metadata(self):
        before = copy.deepcopy(self.story)

        def upstream(provider, model, system, user, schema):
            request = json.loads(user)
            return self.corrected(provider, model, system, user, schema) if request.get("task") else copy.deepcopy(self.story)

        with patch("storyboard.providers.generate_json", side_effect=upstream) as calls:
            result = engine.generate({"brief": self.brief, "provider": "openai", "model": "fake"})
        self.assertEqual(calls.call_count, 2)
        self.assertEqual(result["brief"], self.brief)
        expected = copy.deepcopy(before)
        expected["shots"][0]["dialogue"][0]["text"] = "昨日、スマホを忘れちゃった。"
        self.assertEqual(result["story"], expected)
        self.assertTrue(any(h["event"].startswith("일본어 대사 교정 완료") for h in result["history"]))

    def test_locked_and_user_supplied_wording_are_not_editable(self):
        self.story["shots"][0]["locked"] = True
        exact = '「えっ？」\n本当に？'
        self.brief["required"] = "이 대사는 그대로 유지: " + exact
        self.story["shots"][1]["dialogue"][0]["text"] = exact
        self.story["shots"][2]["dialogue"][0]["text"] = "それで、どうなったの？"
        before = copy.deepcopy(self.story)

        def upstream(provider, model, system, user, schema):
            request = json.loads(user)
            ids = [line["id"] for line in request["lines"]]
            self.assertNotIn("S01:D01", ids)
            self.assertNotIn("S02:D01", ids)
            return {"lines": [{"id": line["id"], "text": line["text"]} for line in request["lines"]]}

        with patch("storyboard.providers.generate_json", side_effect=upstream):
            result, status = dialogue.polish_japanese(self.story, self.brief, "claude", "fake")
        self.assertEqual(status, "completed")
        self.assertEqual(result, before)
        self.assertEqual(self.story, before)

    def test_non_japanese_and_demo_do_not_add_a_provider_call(self):
        with patch("storyboard.providers.generate_json") as upstream:
            result, status = dialogue.polish_japanese(engine.demo_story(brief()), brief(), "ollama", "fake")
            engine.generate({"brief": self.brief, "provider": "demo"})
        self.assertIsNone(status)
        upstream.assert_not_called()

    def test_invalid_polish_is_atomic_and_original_draft_survives_with_warning(self):
        before = copy.deepcopy(self.story)
        for error in (providers.ProviderError("mock timeout"), {"lines": []}):
            with self.subTest(error=error), patch("storyboard.providers.generate_json", side_effect=[copy.deepcopy(self.story), error]):
                result = engine.generate({"brief": self.brief, "provider": "openai", "model": "fake"})
            self.assertEqual(result["story"], before)
            self.assertTrue(any(f["category"] == "일본어" for f in engine.review(result)["findings"]))

    def test_polisher_rejects_blank_translation_and_changed_non_japanese_lines(self):
        for kind in ("blank", "translation", "other_language", "reorder"):
            def invalid(provider, model, system, user, schema):
                lines = [{"id": line["id"], "text": line["text"]} for line in json.loads(user)["lines"]]
                if kind == "reorder":
                    lines.reverse()
                elif kind == "other_language":
                    lines[1]["text"] = "This was not Japanese."
                else:
                    lines[0]["text"] = "" if kind == "blank" else "I forgot my phone."
                return {"lines": lines}

            before = copy.deepcopy(self.story)
            with self.subTest(kind=kind), patch("storyboard.providers.generate_json", side_effect=invalid), self.assertRaises(ValidationError):
                dialogue.polish_japanese(self.story, self.brief, "openai", "fake")
            self.assertEqual(self.story, before)
