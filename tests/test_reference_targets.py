"""Four reference kinds: immutable identity, scope, legacy data and exports."""

import base64
import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from conversion_fixtures import direction_output
from test_guides_references import PNG
from storyboard import conversion, engine, guides, library, prompt_renderer, references
from storyboard.schema import ValidationError

ROOT = Path(__file__).resolve().parents[1]


class ReferenceTargetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        storage = patch.object(library, "ROOT", Path(temporary.name))
        storage.start()
        self.addCleanup(storage.stop)
        brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
        self.doc = engine.generate({"brief": brief, "provider": "demo"})
        self.board = library.save(self.doc)["id"]
        self.person = self.doc["brief"]["characters"][0]["id"]

    def upload(self, kind="prop", **extra):
        return references.upload({"id": self.board, "kind": kind, "character_id": self.person if kind == "character" else "",
                                  "target_name": "소라의 휴대폰" if kind == "prop" else "조명" if kind == "other" else "",
                                  "note": "따뜻한 역광만 참고" if kind == "other" else "", "name": "reference.png",
                                  "data": "data:image/png;base64," + base64.b64encode(PNG).decode(), **extra})

    def test_grouped_props_mixed_references_scope_and_zip_do_not_change_source(self):
        original = copy.deepcopy(self.doc)
        prop = self.upload(owner_id=self.person, shot_ids=["S01"])
        images = [self.upload("character"), self.upload("background"), prop,
                  self.upload(target_id=prop["target_id"], owner_id=self.person, shot_ids=["S01"]), self.upload("other")]
        references.save(self.board, images)
        self.assertEqual(len({a["target_id"] for a in references.load(self.board)}), 4)
        for target in ("minimax-h3-reference", "seedance-2-reference"):
            payload = {"id": self.board, "guide_id": target, "selected": [s["id"] for s in self.doc["story"]["shots"]],
                       "split_mode": "fixed", "provider": "openai", "model": "mock", "references": images}

            def ai(provider, model, system, user, schema):
                request = json.loads(user)
                props = [t for t in request["reference_targets"] if t["kind"] == "prop"]
                self.assertEqual(len(props), 1)
                self.assertEqual(len(props[0]["pictures"]), 2)
                self.assertEqual(props[0]["owner_id"], self.person)
                self.assertEqual(props[0]["shot_ids"], ["S01"])
                return direction_output(request["plan"], request["references"])

            with patch("storyboard.providers.generate_json", side_effect=ai):
                result = conversion.compile_prompts(self.doc, payload)
            first, second = [c["prompt"] for c in result["output"]["clips"]]
            self.assertIn("Prop 1 (Phone)", first)
            self.assertIn("Apply only in [Shot 1]", first)
            self.assertIn("Ownership follows the approved shot states", first)
            self.assertIn("Visual reference 1 (Lighting)", first)
            self.assertNotIn("Prop 1 (Phone)", second)
            self.assertIn("is not used in this clip", second)
            self.assertNotIn("소라의 휴대폰", first)
            self.assertNotIn("따뜻한 역광", first)
            if target.startswith("minimax"):
                self.assertIn("<Subject 3> Prop 1", first)
                self.assertNotRegex(first, r"<Subject 3> \(S\d+\)")
            else:
                self.assertNotIn("<Subject", first)
            text = prompt_renderer.export_text(result)
            self.assertIn("| Phone | prop", text)
            self.assertIn("| Lighting | other", text)
            key = library.save_conversion(self.board, result)
            with zipfile.ZipFile(io.BytesIO(references.package(key))) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest[2]["shot_ids"], ["S01"])
                self.assertEqual(manifest[2]["target_id"], manifest[3]["target_id"])
                self.assertEqual(archive.read(manifest[3]["file"]), PNG)
                self.assertEqual(archive.read("video-prompts.txt").decode(), text)
        self.assertEqual(self.doc, original)

    def test_target_kind_owner_assignment_cannot_be_forged(self):
        prop = self.upload(owner_id=self.person)
        for changes in ({"kind": "character"}, {"character_id": self.person}, {"owner_id": "unknown"},
                        {"target_id": "unknown"}, {"target_name": "different"}, {"role": "appearance"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                references.save(self.board, [{**prop, **changes}])
        other_board = library.save(self.doc)["id"]
        with self.assertRaises(ValidationError):
            self.upload(id=other_board, target_id=prop["target_id"], owner_id=self.person)

    def test_required_names_purpose_owners_and_kinds_validated_before_storing(self):
        for kind, changes in (("prop", {"target_name": " "}), ("other", {"note": ""}),
                              ("prop", {"owner_id": "unknown"}), ("invalid", {}),
                              ("background", {"character_id": self.person}), ("prop", {"shot_ids": ["S99"]})):
            with self.subTest(kind=kind, changes=changes), self.assertRaises(ValidationError):
                self.upload(kind, **changes)
        with library.database() as db:
            references.tables(db)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reference_assets").fetchone()[0], 0)

    def test_group_scopes_must_match_and_selected_empty_cannot_mean_all(self):
        first = self.upload()
        second = self.upload(target_id=first["target_id"])
        for changes in ({"shot_ids": ["S01"]}, {"shot_ids": ["S99"]},
                        {"shot_ids": ["S01", "S01"]}, {"scope_mode": "selected", "shot_ids": []}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                references.save(self.board, [first, {**second, **changes}])
        saved = references.save(self.board, [{**image, "shot_ids": ["S01", "S02"]} for image in (first, second)])
        self.assertTrue(all(a["scope_mode"] == "selected" for a in saved))

    def test_same_names_do_not_merge_separate_objects(self):
        first, second = self.upload(), self.upload()
        third = self.upload(target_id=first["target_id"])
        assets = references.manifest(self.board, [first, second, third], guides.profile("minimax-h3-reference"))
        bindings = references.target_bindings(assets, 2)
        self.assertEqual([b["subject"] for b in bindings], ["<Subject 3>", "<Subject 4>"])
        self.assertEqual([b["pictures"] for b in bindings], [["<Picture 1>", "<Picture 3>"], ["<Picture 2>"]])

    def test_legacy_assets_keep_their_kind_and_selection_without_schema_migration(self):
        image = self.upload("character")
        with library.database() as db:
            db.execute("DELETE FROM reference_targets WHERE asset_id=?", (image["id"],))
        legacy = {key: image[key] for key in ("id", "character_id", "role", "note")}
        legacy.update(role="face", note="Keep the hair clip.")
        saved = references.save(self.board, [legacy])[0]
        self.assertEqual((saved["kind"], saved["character_id"], saved["note"], saved["role"]),
                         ("character", self.person, "Keep the hair clip.", "face"))
        with self.assertRaises(ValidationError):
            references.save(self.board, [{**saved, "kind": "prop", "role": "prop"}])

    def test_nonenglish_or_empty_translated_target_names_are_rejected(self):
        images = [self.upload()]
        profile = guides.profile("minimax-h3-reference")
        assets = references.manifest(self.board, images, profile)
        plan = conversion.plan(self.doc, ["S01"])
        for name in ("", "휴대폰", "<d>[English] speech</d>"):
            draft = direction_output(plan, assets)
            draft["reference_notes"][0]["target_name"] = name
            with self.subTest(name=name), self.assertRaises(ValidationError):
                prompt_renderer.assemble(self.doc, plan, draft, profile, assets)


if __name__ == "__main__":
    unittest.main()
