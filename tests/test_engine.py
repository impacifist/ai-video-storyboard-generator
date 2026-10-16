import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from storyboard import engine
from storyboard.schema import ValidationError, validate_brief, validate_story

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "rainy-classroom.json"


def brief():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def document():
    return engine.generate({"brief": brief(), "provider": "demo"})


class ContractTests(unittest.TestCase):
    def test_large_storyboards_generate_and_reload(self):
        for count in (13, 30, 60):
            with self.subTest(count=count):
                value = brief()
                value.update(shot_count=count, duration=180)
                result = engine.generate({"brief": value, "provider": "demo"})
                restored = json.loads(json.dumps(result))
                engine.validate_document(restored)
                self.assertEqual(len(restored["story"]["shots"]), count)
                self.assertEqual(restored["story"]["shots"][-1]["id"], f"S{count:02d}")

    def test_variable_cast_generation_and_document_roundtrip(self):
        for count in range(1, 6):
            with self.subTest(count=count):
                value = brief()
                template = value["characters"][0]
                value["characters"] = [dict(template, id=f"actor_{i}", name=f"Actor {i}") for i in range(count)]
                doc = engine.generate({"brief": value, "provider": "demo"})
                engine.validate_document(json.loads(json.dumps(doc)))
                ids = {c["id"] for c in value["characters"]}
                for shot in doc["story"]["shots"]:
                    for key in ("start_state", "end_state"):
                        self.assertEqual({c["character_id"] for c in shot[key]["characters"]}, ids)
                self.assertEqual({s["dialogue"][0]["speaker"] for s in doc["story"]["shots"]}, ids)
                doc["story"]["shots"][0]["start_state"]["characters"].pop()
                with self.assertRaises(ValidationError):
                    engine.validate_document(doc)

    def test_cast_bounds_and_duplicate_ids(self):
        for count in (0, 6):
            value = brief()
            value["characters"] = [dict(value["characters"][0], id=f"actor_{i}") for i in range(count)]
            with self.assertRaisesRegex(ValidationError, "1~5"):
                validate_brief(value)
        value = brief()
        value["characters"] = [value["characters"][0]] * 5
        with self.assertRaisesRegex(ValidationError, "ID"):
            validate_brief(value)

    def test_direction_contract_reaches_every_generation_provider_with_original_schema(self):
        for provider in ("openai", "claude", "ollama", "lmstudio"):
            with self.subTest(provider=provider):
                source = brief()
                before = copy.deepcopy(source)
                response = engine.demo_story(source)
                with patch("storyboard.providers.generate_json", return_value=response) as upstream:
                    result = engine.generate({"brief": source, "provider": provider, "model": "test-model"})
                upstream.assert_called_once()
                _, _, system, user, schema = upstream.call_args.args
                self.assertIn(engine.SHOT_DIRECTION, system)
                self.assertEqual(json.loads(user)["brief"], before)
                self.assertEqual(schema, engine.STORY)
                self.assertEqual(source, before)
                engine.validate_document(result)
                self.assertEqual(len(result["story"]["shots"]), source["shot_count"])

    def test_semantic_review_uses_same_direction_contract_without_rewriting_story(self):
        doc = document()
        before = copy.deepcopy(doc)
        response = {"summary": "전환 계기 검토", "findings": [{"severity": "warning", "category": "연출",
                    "shot_id": "S02", "message": "상대의 반응으로 전환할 이유를 구체화하세요."}]}
        with patch("storyboard.providers.generate_json", return_value=response) as upstream:
            result = engine.semantic_review(doc, "openai", "test-model")
        upstream.assert_called_once()
        _, _, system, user, schema = upstream.call_args.args
        self.assertIn(engine.SHOT_DIRECTION, system)
        self.assertEqual(json.loads(user)["story"], before["story"])
        self.assertEqual(schema, engine.AI_REVIEW)
        self.assertEqual(result["result"], response)
        self.assertEqual(doc, before)

    def test_demo_has_explicit_provenance_and_valid_references(self):
        doc = document()
        engine.validate_document(doc)
        self.assertEqual(doc["provenance"]["provider"], "demo")
        self.assertIn("예시", doc["story"]["summary"])
        self.assertTrue(engine.review(doc)["structure_valid"])

    def test_reject_duplicate_character_ids(self):
        value = brief()
        value["characters"][1]["id"] = value["characters"][0]["id"]
        with self.assertRaises(ValidationError):
            validate_brief(value)

    def test_missing_location_has_user_facing_label(self):
        value = brief()
        value["location"] = " "
        with self.assertRaisesRegex(ValidationError, "장소 항목을 입력해주세요"):
            validate_brief(value)

    def test_reject_wrong_counts_numbers_and_missing_intent(self):
        for key, value in [("shot_count", 2), ("shot_count", 61), ("shot_count", True), ("duration", float("nan")),
                           ("duration", 181), ("intent", "")]:
            with self.subTest(key=key, value=value):
                data = brief()
                data[key] = value
                with self.assertRaises(ValidationError):
                    validate_brief(data)

    def test_reject_unknown_speaker_and_prop_holder(self):
        for kind in ("speaker", "holder"):
            with self.subTest(kind=kind):
                doc = document()
                shot = doc["story"]["shots"][0]
                if kind == "speaker":
                    shot["dialogue"][0]["speaker"] = "unknown"
                else:
                    shot["end_state"]["props"] = [{"name": "우산", "holder": "unknown", "position": "손"}]
                with self.assertRaises(ValidationError):
                    engine.validate_document(doc)

    def test_reject_duplicate_shot_missing_state_and_nonpositive_duration(self):
        for kind in ("id", "state", "duration", "visual"):
            with self.subTest(kind=kind):
                doc = document()
                shot = doc["story"]["shots"][1]
                if kind == "id":
                    shot["id"] = "S01"
                elif kind == "state":
                    shot["start_state"]["characters"].pop()
                elif kind == "duration":
                    shot["duration"] = 0
                else:
                    shot["visual"] = ""
                with self.assertRaises(ValidationError):
                    engine.validate_document(doc)

    def test_locked_shot_preserved_even_when_model_changes_it(self):
        previous = document()
        previous["story"]["shots"][2]["locked"] = True
        previous["story"]["shots"][2]["visual"] = "사용자가 고정한 화면"
        original = copy.deepcopy(previous)
        response = engine.demo_story(brief())
        response["shots"][2]["visual"] = "모델이 임의로 변경한 화면"
        with patch("storyboard.providers.generate_json", return_value=response) as call:
            result = engine.generate({"brief": brief(), "provider": "openai", "model": "test-model", "previous": previous})
        self.assertEqual(result["story"]["shots"][2], original["story"]["shots"][2])
        self.assertEqual(previous, original)
        self.assertIn(engine.SHOT_DIRECTION, call.call_args.args[2])
        self.assertIn("사용자가 고정한 화면", call.call_args.args[3])

    def test_locked_input_change_and_all_locked_fail_before_provider(self):
        previous = document()
        previous["story"]["shots"][0]["locked"] = True
        changed = brief()
        changed["location"] = "다른 장소"
        with patch("storyboard.providers.generate_json") as call:
            with self.assertRaises(ValidationError):
                engine.generate({"brief": changed, "provider": "claude", "model": "x", "previous": previous})
            for shot in previous["story"]["shots"]:
                shot["locked"] = True
            with self.assertRaises(ValidationError):
                engine.generate({"brief": brief(), "provider": "claude", "model": "x", "previous": previous})
            call.assert_not_called()

    def test_model_wrong_count_rejected_before_lock_merge(self):
        response = engine.demo_story(brief())
        response["shots"].pop()
        with self.assertRaises(ValidationError):
            validate_story(response, brief())

    def test_continuity_review_checks_following_cut_after_edit(self):
        doc = document()
        doc["story"]["shots"][0]["end_state"]["characters"][0]["position"] = "출입문"
        result = engine.review(doc)
        self.assertTrue(any(f["category"] == "연속성" and f["shot_id"] == "S02" for f in result["findings"]))

    def test_state_order_does_not_create_false_continuity_warning(self):
        doc = document()
        doc["story"]["shots"][1]["start_state"]["characters"].reverse()
        self.assertFalse(any(f["category"] == "연속성" for f in engine.review(doc)["findings"]))

    def test_time_warning_and_required_element_warning(self):
        doc = document()
        doc["story"]["shots"][0]["duration"] = 100
        findings = engine.review(doc)["findings"]
        self.assertTrue(any(f["category"] == "시간" for f in findings))
        self.assertTrue(any(f["category"] == "필수 요소" for f in findings))

    def test_markdown_escapes_table_delimiters(self):
        doc = document()
        doc["story"]["shots"][0]["visual"] = "장면 | 설명\n다음 줄"
        result = engine.markdown(doc)
        self.assertIn("장면 \\| 설명 / 다음 줄", result)
        self.assertIn("예시", result)
        self.assertIn("start", result)

    def test_semantic_review_rejects_unknown_shot(self):
        response = {"summary": "검토", "findings": [{"severity": "warning", "category": "성격",
                    "shot_id": "S99", "message": "수정 필요"}]}
        with patch("storyboard.providers.generate_json", return_value=response):
            with self.assertRaises(ValidationError):
                engine.semantic_review(document(), "ollama", "test")

    def test_semantic_review_requires_ai(self):
        with self.assertRaises(ValidationError):
            engine.semantic_review(document(), "demo", "")


if __name__ == "__main__":
    unittest.main()
