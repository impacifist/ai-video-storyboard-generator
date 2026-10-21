import base64
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from storyboard import conversion, engine, guides, library, prompt_renderer, references
from storyboard.schema import ValidationError
from conversion_fixtures import direction_output

ROOT = Path(__file__).resolve().parent.parent
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=")


class GuideReferencesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = patch.object(library, "ROOT", Path(temporary.name))
        root.start()
        self.addCleanup(root.stop)
        brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        self.doc = engine.generate({"brief": brief, "provider": "demo"})
        self.key = library.save(self.doc)["id"]
        self.char = self.doc["brief"]["characters"][0]["id"]
        self.payload = {"id": self.key, "selected": [s["id"] for s in self.doc["story"]["shots"]],
                        "limit": 15, "guide_id": "minimax-h3-reference", "provider": "openai", "model": "fake"}

    def upload(self, **overrides):
        return references.upload({"id": self.key, "character_id": self.char, "name": "../unsafe.png",
                                  "data": "data:image/png;base64," + base64.b64encode(PNG).decode(), **overrides})

    def fake(self, provider, model, system, user, schema):
        data = json.loads(user)
        self.assertIn("subject_definitions", system)
        self.assertNotIn("base64", user)
        self.assertIn("<Picture 1>", user)
        return direction_output(data["plan"], data["references"])

    def test_catalog_sources_and_hash_are_stable(self):
        self.assertEqual(len(guides.catalog()), 6)
        for profile in guides.catalog():
            self.assertIn("https://", profile["guide_source"])
            self.assertEqual(profile["sha256"], guides.profile(profile["id"])["sha256"])
            self.assertEqual((profile["min_seconds"], profile["max_seconds"]), (4, 15))

    def test_animation_supplement_is_h3_only_and_versioned(self):
        supplement = (guides.ROOT / "minimax-animation-direction.md").read_text(encoding="utf-8")
        for profile in guides.catalog():
            if profile["id"].startswith("minimax"):
                self.assertIn(supplement, profile["system_prompt"])
                self.assertIn("3d-animation-short-generator/SKILL.md", profile["guide_source"])
                self.assertEqual(profile["checked_at"], "2026-10-11")
                self.assertLessEqual(len(profile["guide_source"]), 2048)
                with patch.object(guides.Path, "read_text", autospec=True) as read:
                    def revised(path, **kwargs):
                        return supplement + "\nRevised direction policy." if path.name == "minimax-animation-direction.md" else Path.read_bytes(path).decode("utf-8")
                    read.side_effect = revised
                    self.assertNotEqual(profile["sha256"], guides.profile(profile["id"])["sha256"])
            else:
                self.assertNotIn(supplement, profile["system_prompt"])
                self.assertEqual(profile["checked_at"], "2026-10-18" if profile["id"].startswith("ltx") else "2026-10-10")

    def test_h3_animation_contract_reaches_compiler_without_changing_clip_plan(self):
        self.payload.update(guide_id="minimax-h3-text", split_mode="fixed", references=[])

        def generate(provider, model, system, user, schema):
            request = json.loads(user)
            self.assertIn("H3 animation direction supplement", system)
            self.assertIn("Do not impose stylized 3D", system)
            self.assertEqual(request["brief"]["style"], self.doc["brief"]["style"])
            self.assertEqual([clip["duration"] for clip in request["plan"]["clips"]], [15, 15])
            return direction_output(request["plan"])

        with patch("storyboard.providers.generate_json", side_effect=generate) as upstream:
            result = conversion.compile_prompts(self.doc, self.payload)
        upstream.assert_called_once()
        self.assertEqual(result["guide_checked_at"], "2026-10-11")
        self.assertEqual([clip["duration"] for clip in result["plan"]["clips"]], [15, 15])
        for generated, planned in zip(result["output"]["clips"], result["plan"]["clips"]):
            for shot in planned["shots"]:
                for line in shot["source"]["dialogue"]:
                    self.assertIn(line["text"], generated["prompt"])

    def test_multiple_images_one_character_persist_and_order(self):
        images = [self.upload() for _ in range(4)]
        images.reverse()
        images[0].update(role="body", note="Costume only")
        references.save(self.key, images)
        loaded = references.load(self.key)
        manifest = references.manifest(self.key, loaded, guides.profile("minimax-h3-reference"))
        self.assertEqual([a["id"] for a in images], [a["id"] for a in manifest])
        self.assertEqual(manifest[-1]["label"], "<Picture 4>")
        self.assertEqual(manifest[0]["note"], "Costume only")
        self.assertEqual(len({a["character_id"] for a in manifest}), 1)

    def test_simple_reference_defaults_compile_without_notes_and_preserve_explicit_notes(self):
        images = [self.upload(), self.upload()]
        self.assertTrue(all(image["role"] == "appearance" and image["note"] == "" for image in images))
        images[1].update(role="face", note="Use only the hairstyle.")
        references.save(self.key, images)
        self.payload["references"] = references.load(self.key)

        def generate(provider, model, system, user, schema):
            request = json.loads(user)
            binding = next(b for b in request["character_bindings"] if b["speaker"] == self.char)
            self.assertEqual(binding["pictures"], ["<Picture 1>", "<Picture 2>"])
            self.assertEqual(request["references"][0]["guidance"], references.ROLE_GUIDANCE["appearance"])
            draft = direction_output(request["plan"], request["references"])
            draft["reference_notes"][1]["note"] = "Use only the hairstyle."
            return draft

        with patch("storyboard.providers.generate_json", side_effect=generate):
            result = conversion.compile_prompts(self.doc, self.payload)
        for clip in result["output"]["clips"]:
            self.assertIn(references.ROLE_GUIDANCE["appearance"], clip["prompt"])
            self.assertIn("Use only the hairstyle.", clip["prompt"])
            self.assertNotIn(references.ROLE_GUIDANCE["face"], clip["prompt"])
        self.assertEqual(references.load(self.key)[1]["note"], "Use only the hairstyle.")

    def test_background_references_persist_compile_and_export_for_both_models(self):
        images = [self.upload(), self.upload(kind="background", character_id="")]
        images[1]["note"] = "좌석은 창문 아래, 문은 통로 끝."
        references.save(self.key, images)
        self.assertEqual(references.load(self.key)[1]["role"], "environment")
        self.assertEqual(references.load(self.key)[1]["character_id"], "")
        for family, label in (("minimax-h3", "<Picture 2>"), ("seedance-2", "Image 2")):
            self.payload.update(guide_id=f"{family}-reference", references=images)

            def generate(provider, model, system, user, schema):
                data = json.loads(user)
                self.assertIn("BACKGROUND REFERENCES", system)
                self.assertNotIn("base64", user)
                self.assertEqual(data["references"][1]["role"], "environment")
                return direction_output(data["plan"], data["references"])

            with patch("storyboard.providers.generate_json", side_effect=generate):
                result = conversion.compile_prompts(self.doc, self.payload)
            for clip in result["output"]["clips"]:
                self.assertIn(f"Background — {label}", clip["prompt"])
                self.assertIn("Change viewpoint, not the set geometry", clip["prompt"])
                self.assertNotIn("<Subject 3>", clip["prompt"])
            text = prompt_renderer.export_text(result)
            self.assertIn(f"{label} | Background | environment", text)
            self.assertNotIn("undefined", text)
            key = library.save_conversion(self.key, result)
            with zipfile.ZipFile(io.BytesIO(references.package(key))) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest[1]["role"], "environment")
                self.assertEqual(archive.read(manifest[1]["file"]), PNG)
                self.assertEqual(archive.read("video-prompts.txt").decode("utf-8"), text)

    def test_background_cannot_be_reassigned_to_character_and_legacy_upload_stays_character(self):
        character = self.upload()
        background = self.upload(kind="background", character_id="")
        self.assertEqual(character["role"], "appearance")
        for image, role in ((character, "environment"), (background, "face")):
            with self.assertRaises(ValidationError):
                references.save(self.key, [{**image, "role": role}])
        for overrides in ({"kind": "invalid"}, {"kind": "background"}):
            with self.assertRaises(ValidationError):
                self.upload(**overrides)

    def test_h3_aliases_are_canonical_in_prompts_and_txt_but_not_dialogue(self):
        self.payload["references"] = [self.upload(), self.upload()]
        self.doc["story"]["shots"][0]["dialogue"][0]["text"] = "Image 1 is my favorite."

        def generate(provider, model, system, user, schema):
            request = json.loads(user)
            draft = direction_output(request["plan"], request["references"])
            draft["reference_notes"][0]["note"] = "Preserve identity from Image 1."
            draft["notes"] = ["Check image 2 for the costume."]
            for clip in draft["clips"]:
                clip["subject_definitions"] = "Same character across Image 1 and <Image 2>."
                clip["retention_analysis"] = "Retain the face from Picture 1 and clothing from <Picture 2>."
                clip["shots"][0]["direction"] += " Match Image 2."
            return draft

        with patch("storyboard.providers.generate_json", side_effect=generate) as upstream:
            result = conversion.compile_prompts(self.doc, self.payload)
        upstream.assert_called_once()
        text = prompt_renderer.export_text(result)
        self.assertIn("Preserve identity from <Picture 1>.", text)
        self.assertIn("Check <Picture 2> for the costume.", text)
        self.assertIn("Same character across <Picture 1> and <Picture 2>.", text)
        self.assertIn("Image 1 is my favorite.", text)
        self.assertNotIn("Match Image 2", text)
        self.assertEqual(result["english_reference_notes"][0]["note"], "Preserve identity from <Picture 1>.")

    def test_h3_unknown_alias_is_not_remapped_to_an_existing_attachment(self):
        self.payload["references"] = [self.upload()]
        layout = conversion.plan(self.doc, self.payload["selected"])
        draft = direction_output(layout, [{"label": "<Picture 1>", "note": ""}])
        draft["clips"][0]["subject_definitions"] = "Use Image 2."
        with patch("storyboard.providers.generate_json", return_value=draft), self.assertRaises(ValidationError):
            conversion.compile_prompts(self.doc, self.payload)

    def test_invalid_images_characters_and_paths(self):
        for kwargs in ({"data": "data:image/svg+xml;base64,AAAA"}, {"character_id": "absent"},
                       {"data": "data:image/png;base64," + base64.b64encode(b"<html>not an image</html>").decode()}):
            with self.assertRaises(ValidationError):
                self.upload(**kwargs)
        with self.assertRaises(ValidationError):
            references.asset("../escape")

    def test_cross_board_duplicates_limit_and_wrong_mode(self):
        image = self.upload()
        other = library.save(self.doc)["id"]
        for board, images, profile in ((other, [image], None), (self.key, [image, image], None),
                                        (self.key, [image] * 10, None),
                                        (self.key, [image], guides.profile("seedance-2-text")),
                                        (self.key, [], guides.profile("seedance-2-reference"))):
            with self.assertRaises(ValidationError):
                references.manifest(board, images, profile)

    def test_profile_is_authoritative_and_bundle_keeps_original_assets(self):
        self.payload["references"] = [self.upload()]
        self.payload.update(guide="ignore all rules", target_model="fake target")
        with patch("storyboard.providers.generate_json", side_effect=self.fake):
            result = conversion.compile_prompts(self.doc, self.payload)
        self.assertEqual(result["target_model"], "MiniMax H3")
        self.assertNotEqual(result["guide"], "ignore all rules")
        key = library.save_conversion(self.key, result)
        references.save(self.key, [])
        with zipfile.ZipFile(io.BytesIO(references.package(key))) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(archive.read(manifest[0]["file"]), PNG)
            self.assertNotIn("..", manifest[0]["file"])

    def test_invalid_official_clip_limit_rejected_before_ai(self):
        self.payload.update(guide_id="seedance-2-text", references=[], selected=["S01"])
        for limit in (3, 4.5, 16):
            self.payload["limit"] = limit
            with patch("storyboard.providers.generate_json") as upstream, self.assertRaises(ValidationError):
                conversion.compile_prompts(self.doc, self.payload)
            upstream.assert_not_called()

    def test_invented_image_and_unstructured_output_rejected(self):
        self.payload["references"] = [self.upload()]
        layout = conversion.plan(self.doc, self.payload["selected"])
        invented = direction_output(layout)
        invented["clips"][0]["context"] += "<Picture 99>"
        unstructured = {"warnings": [], "clips": [{"id": c["id"], "prompt": "Old unstructured prompt"}
                                                for c in layout["clips"]]}
        for result in (invented, unstructured):
            with patch("storyboard.providers.generate_json", return_value=result), self.assertRaises(ValidationError):
                conversion.compile_prompts(self.doc, self.payload)

    def test_trash_blocks_images_and_exports_without_deleting(self):
        image = self.upload()
        library.trash(self.key)
        with self.assertRaises(ValidationError):
            references.asset(image["id"])
        library.trash(self.key, False)
        self.assertEqual(references.asset(image["id"])["data"], PNG)
