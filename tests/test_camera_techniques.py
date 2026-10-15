import re
import unittest

from storyboard import engine, guides


class CameraTechniqueTests(unittest.TestCase):
    def test_complete_catalog_reaches_storyboard_and_conversion_instructions(self):
        catalog = (guides.ROOT / "camera-techniques.ko.md").read_text(encoding="utf-8")
        numbers = [int(number) for number in re.findall(r"^\| (\d{2}) \|", catalog, re.MULTILINE)]
        self.assertEqual(numbers, list(range(1, 76)))
        self.assertIn(catalog, engine.SHOT_DIRECTION)
        self.assertIn(catalog, engine.DIRECTOR)
        # Includes the custom-model path as well as every supplied target profile.
        self.assertIn(catalog, guides.assembly_rules())
        for key in guides.PROFILES:
            with self.subTest(profile=key):
                self.assertIn(catalog, guides.profile(key)["system_prompt"])


if __name__ == "__main__":
    unittest.main()
