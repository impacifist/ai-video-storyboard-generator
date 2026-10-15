import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import conversion, engine, library, prompt_renderer


class FractionalClipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        storage = patch.object(library, 'ROOT', Path(temporary.name))
        storage.start()
        self.addCleanup(storage.stop)
        brief = json.loads((Path(__file__).resolve().parent.parent / 'examples/rainy-classroom.json').read_text(encoding='utf-8'))
        self.doc = engine.generate({'brief': brief, 'provider': 'demo'})
        self.key = library.save(self.doc)['id']

    def test_official_clips_round_up_without_changing_source_timing(self):
        for guide in ('seedance-2-text', 'minimax-h3-text'):
            for duration, expected in ((0.5, 4), (3, 4), (4, 4), (4.00001, 5), (7.4, 8), (14.9, 15), (15, 15)):
                with self.subTest(guide=guide, duration=duration):
                    self.doc['story']['shots'][0]['duration'] = duration
                    before = copy.deepcopy(self.doc)
                    layout, _, _ = conversion.preflight(self.doc, {'id': self.key, 'selected': ['S01'], 'guide_id': guide})
                    clip = layout['clips'][0]
                    self.assertEqual(clip['duration'], expected)
                    self.assertIs(type(clip['duration']), int)
                    self.assertEqual(clip['shots'][0]['end'], duration)
                    self.assertEqual(clip['shots'][0]['source']['duration'], duration)
                    self.assertEqual(clip.get('content_duration', duration), duration)
                    self.assertEqual(self.doc, before)

    def test_fixed_split_preserves_fractional_offsets_and_only_pads_tail(self):
        self.doc['story']['shots'][0]['duration'] = 16.4
        layout, _, _ = conversion.preflight(self.doc, {'id': self.key, 'selected': ['S01'], 'guide_id': 'minimax-h3-text', 'split_mode': 'fixed'})
        first, last = layout['clips']
        self.assertEqual([c['duration'] for c in layout['clips']], [15, 4])
        self.assertNotIn('content_duration', first)
        self.assertEqual(last['content_duration'], 1.4)
        self.assertEqual(last['timeline_end'], 16.4)
        self.assertEqual(last['shots'][0]['source_offset'], 15)
        self.assertEqual(last['shots'][0]['source_end'], 16.4)
        self.assertEqual(first['shots'][0]['exit_boundary_id'], last['shots'][0]['entry_boundary_id'])

    def test_conversion_and_txt_preserve_dialogue_and_defer_transition_until_after_hold(self):
        self.doc['story']['shots'][0]['duration'] = 7.4
        self.doc['story']['shots'][0]['locked'] = True
        before = copy.deepcopy(self.doc)
        for guide in ('seedance-2-text', 'minimax-h3-text'):
            payload = {'id': self.key, 'selected': ['S01'], 'guide_id': guide, 'provider': 'openai', 'model': 'fake'}

            def generate(provider, model, system, user, schema):
                plan = json.loads(user)['plan']
                self.assertEqual(plan['clips'][0]['duration'], 8)
                self.assertIn('clip.content_duration', system)
                return direction_output(plan)

            with self.subTest(guide=guide), patch('storyboard.providers.generate_json', side_effect=generate):
                result = conversion.compile_prompts(self.doc, payload)
                prompt = result['output']['clips'][0]['prompt']
                self.assertIn('From 7.4s to 8s, hold the final frame.', prompt)
                self.assertIn('After the final-frame hold: Cut on the reaction', prompt)
                self.assertNotIn('At the end of this source shot:', prompt)
                text = prompt_renderer.export_text(result)
                self.assertIn('C01 | 8s', text)
                self.assertIn('source content 7.4s; generated duration 8s', text)
                self.assertEqual([line['text'] for line in result['dialogue_manifest']],
                                 [line['text'] for line in self.doc['story']['shots'][0]['dialogue']])
                self.assertEqual(self.doc, before)

    def test_custom_guide_keeps_fractional_clip_duration(self):
        self.doc['story']['shots'][0]['duration'] = 7.4
        layout, _, _ = conversion.preflight(self.doc, {'selected': ['S01'], 'limit': 14.5})
        self.assertEqual(layout['clips'][0]['duration'], 7.4)
        self.assertNotIn('content_duration', layout['clips'][0])


if __name__ == '__main__':
    unittest.main()
