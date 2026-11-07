"""Prevent connection prose from pulling a future action into the preceding clip."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import conversion, engine, guides, handoff, library, prompt_renderer, providers
from storyboard.schema import ValidationError


class HandoffScopeTests(unittest.TestCase):
    def setUp(self):
        brief = json.loads((Path(__file__).resolve().parents[1] / 'examples/rainy-classroom.json').read_text(encoding='utf-8'))
        self.doc = engine.generate({'brief': brief, 'provider': 'demo'})
        for shot in self.doc['story']['shots']:
            shot.update(duration=5, scene_id='room', dialogue=[])
        self.ids = [s['id'] for s in self.doc['story']['shots']]

    def test_future_action_occurs_only_in_its_own_clip_for_each_video_model(self):
        layout = conversion.plan(self.doc, self.ids[:2], limit=5, split_mode='fixed')
        draft = direction_output(layout)
        current = 'The character raises the cup to chest height.'
        future = 'The character takes one sip from the cup.'
        draft['clips'][0]['shots'][0]['direction'] = current
        draft['clips'][1]['shots'][0]['direction'] = future
        draft['clips'][0]['shots'][0]['camera']['transition'] = 'Match cut on the cup'
        original = copy.deepcopy(layout)
        for target in ('minimax-h3-text', 'seedance-2-text', 'ltx-2.5-text'):
            with self.subTest(target=target):
                output, _ = prompt_renderer.assemble(self.doc, layout, draft, guides.profile(target), [])
                first, second = [c['prompt'] for c in output['clips']]
                self.assertIn(current, first)
                self.assertIn('Match cut on the cup', first)
                self.assertNotIn(future, first)
                self.assertNotIn(current, second)
                self.assertEqual(second.count(future), 1)
                prose = target.startswith('ltx')
                self.assertIn(handoff.note(layout['handoffs'][0], 'outgoing', prose=prose), first)
                self.assertIn(handoff.note(layout['handoffs'][0], 'incoming', prose=prose), second)
                self.assertNotIn(handoff.note(layout['handoffs'][0], 'incoming', prose=prose), first)
                self.assertNotIn(handoff.note(layout['handoffs'][0], 'outgoing', prose=prose), second)
                for text in (first, second):
                    self.assertNotIn('Outgoing connection', text)
                    self.assertNotIn('Audio connection:', text)
                    self.assertNotIn('Carry the approved performance into the next segment', text)
        self.assertEqual(layout, original)

    def test_continuous_shot_inherits_state_and_phase_instead_of_restarting_movement(self):
        self.doc['story']['shots'][0]['duration'] = 20
        layout = conversion.plan(self.doc, self.ids[:1], split_mode='fixed')
        draft = direction_output(layout)
        for target in ('minimax-h3-text', 'seedance-2-text', 'ltx-2.5-text'):
            with self.subTest(target=target):
                output, _ = prompt_renderer.assemble(self.doc, layout, draft, guides.profile(target), [])
                first, second = [c['prompt'] for c in output['clips']]
                self.assertIn('Leave the unfinished motion at that phase', first)
                self.assertIn('Do not replay the movement', second)
                self.assertIn('already has the established motion state' if target.startswith('ltx')
                              else 'already has the shared boundary state', second)
                self.assertNotIn('after the planned cut', first + second)
        # There is still one translated shared state, reused as state, not a new action.
        output, _ = prompt_renderer.assemble(self.doc, layout, draft, guides.profile('minimax-h3-text'), [])
        self.assertEqual(output['clips'][0]['prompt'].split('End at shared boundary B01: ')[1].split('\n')[0],
                         output['clips'][1]['prompt'].split('Start at shared boundary B01: ')[1].split('\n')[0])

    def test_scene_changes_and_omitted_intervals_are_not_forced_into_continuous_motion(self):
        self.doc['story']['shots'][1]['scene_id'] = 'another_room'
        layout = conversion.plan(self.doc, self.ids[:2], limit=5, split_mode='fixed')
        self.assertEqual(layout['handoffs'][0]['kind'], 'scene_change')
        for target in ('minimax-h3-text', 'seedance-2-text', 'ltx-2.5-text'):
            output, _ = prompt_renderer.assemble(self.doc, layout, direction_output(layout), guides.profile(target), [])
            self.assertIn("this scene's own approved location", output['clips'][1]['prompt'])
            self.assertNotIn('shared boundary state', output['clips'][0]['prompt'])
            self.assertNotIn('Carry the approved', output['clips'][0]['prompt'])
        gap = conversion.plan(self.doc, [self.ids[0], self.ids[2]], limit=5, split_mode='fixed')
        self.assertEqual(gap['handoffs'], [])
        output, _ = prompt_renderer.assemble(self.doc, gap, direction_output(gap), None, [])
        self.assertNotIn('Clip end scope', output['clips'][0]['prompt'])
        self.assertNotIn('Clip start scope', output['clips'][1]['prompt'])

    def test_schema_has_no_free_handoff_prose_and_old_action_bridge_requires_repair(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with patch.object(library, 'ROOT', Path(temporary.name)):
            key = library.save(self.doc)['id']
            payload = {'id': key, 'selected': self.ids[:2], 'split_mode': 'fixed', 'limit': 5,
                       'guide_id': 'minimax-h3-text', 'provider': 'openai', 'model': 'fake'}
            preview = conversion.preview_request(self.doc, payload)
            self.assertNotIn('handoffs', preview['schema']['properties'])
            valid = direction_output(preview['user']['plan'])
            legacy = copy.deepcopy(valid)
            legacy['handoffs'] = [{'id': 'H01', 'bridge': 'The character takes one sip from the cup.', 'sound_bridge': 'N/A'}]
            with patch.object(providers, 'generate_json', side_effect=[legacy, valid]) as ai:
                result = conversion.compile_prompts(self.doc, payload)
            self.assertEqual(ai.call_count, 2)
            self.assertTrue(result['validation_report']['repaired'])
            self.assertEqual(result['assembly_version'], 9)
            self.assertEqual(result['handoff_bridges'], [])
            self.assertEqual(result['handoff_policy'], handoff.manifest(result['plan']))
            self.assertIn('handoffs', result['validation_report']['issues'][0])
            self.assertEqual(result['request_trace'][0]['output'], legacy)
            self.assertNotIn('one sip', result['output']['clips'][0]['prompt'])
            self.assertEqual(library.load(key), self.doc)

    def test_unrecognized_connection_types_are_rejected(self):
        for kind, side in (('unknown', 'incoming'), ('planned_cut', 'both')):
            with self.subTest(kind=kind, side=side), self.assertRaises(ValidationError):
                handoff.note({'kind': kind}, side)
