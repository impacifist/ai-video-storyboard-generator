"""Synthetic long, three-person plans; never include private feedback narratives."""

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import conversion, conversion_structure, engine, guides, prompt_renderer, providers
from storyboard.schema import ValidationError


class ConversionStructureTests(unittest.TestCase):
    def setUp(self):
        brief = json.loads((Path(__file__).resolve().parents[1] / 'examples/rainy-classroom.json').read_text(encoding='utf-8'))
        # Match the supplied input's dimensions, with an unrelated authored scene.
        brief.update(duration=100, shot_count=10, title='An office introduction', location='Office')
        brief['characters'] = [dict(brief['characters'][0], id=f'person_{i}', name=f'Person {i}') for i in range(1, 4)]
        self.doc = engine.generate({'brief': brief, 'provider': 'demo'})
        for shot, duration in zip(self.doc['story']['shots'], [5, 5, 10, 10, 30, 10, 5, 5, 10, 10]):
            shot.update(duration=duration, scene_id='office')
        engine.validate_document(self.doc)
        self.ids = [s['id'] for s in self.doc['story']['shots']]
        self.layout = conversion.plan(self.doc, self.ids, split_mode='fixed')
        self.valid = direction_output(self.layout)

    def compile(self, outputs, target='minimax-h3-text', layout=None, provider='openai'):
        layout = copy.deepcopy(layout or self.layout)
        with patch.object(providers, 'generate_json', side_effect=outputs) as ai:
            result = conversion.compile_directions(self.doc, layout, guides.profile(target), [], provider,
                                                   'a-different-conversion-model', 'System', {'plan': copy.deepcopy(layout)})
        return result, ai

    def test_order_only_recovery_retains_whole_objects_and_original_dialogue_for_every_target(self):
        for target in ('minimax-h3-text', 'seedance-2-text', 'ltx-2.5-text'):
            for provider in ('openai', 'claude', 'ollama', 'lmstudio'):
                with self.subTest(target=target, provider=provider):
                    scrambled = copy.deepcopy(self.valid)
                    scrambled['clips'].reverse()
                    for clip in scrambled['clips']:
                        clip['shots'].reverse()
                    before = copy.deepcopy(scrambled)
                    (draft, output, manifest, report), ai = self.compile([scrambled], target, provider=provider)
                    self.assertEqual(ai.call_count, 1)
                    self.assertEqual(draft, self.valid)
                    self.assertEqual(scrambled, before)
                    self.assertTrue(report['reordered_by_id'])
                    self.assertFalse(report['repaired'])
                    self.assertEqual([x['text'] for x in manifest],
                                     [d['text'] for s in self.doc['story']['shots'] for d in s['dialogue']])
                    self.assertEqual([c['id'] for c in output['clips']], [c['id'] for c in self.layout['clips']])

    def test_contract_keeps_global_and_repeated_continuation_ids(self):
        (_, _, _, _), ai = self.compile([self.valid])
        request = json.loads(ai.call_args.args[3])
        contract = request['shot_contract']
        self.assertEqual(contract['clips'], [{'id': c['id'], 'shot_ids': [s['id'] for s in c['shots']]}
                                             for c in self.layout['clips']])
        self.assertGreater(sum('S05' in c['shot_ids'] for c in contract['clips']), 1)
        self.assertIn('Never restart shot numbering', ai.call_args.args[2])
        self.assertEqual(self.doc['provenance']['provider'], 'demo')
        self.assertEqual(ai.call_args.args[0], 'openai')

    def test_output_schema_limits_ids_to_selected_plan_without_mutating_base(self):
        before = copy.deepcopy(prompt_renderer.DIRECTOR_OUTPUT)
        layout = conversion.plan(self.doc, ['S07', 'S09'], split_mode='fixed')
        schema = prompt_renderer.output_schema(self.doc, layout)
        clip = schema['properties']['clips']['items']['properties']
        self.assertEqual(clip['id']['enum'], [c['id'] for c in layout['clips']])
        self.assertEqual(clip['shots']['items']['properties']['id']['enum'], ['S07', 'S09'])
        invalid = direction_output(layout)
        invalid['clips'][0]['shots'][0]['id'] = 'S01'
        with self.assertRaisesRegex(ValidationError, r'shots\[0\].id'):
            prompt_renderer.validate(invalid, schema)
        self.assertEqual(before, prompt_renderer.DIRECTOR_OUTPUT)

    def test_missing_extra_duplicate_renumbered_and_moved_shots_need_explicit_repair(self):
        for issue in ('missing', 'extra', 'duplicate', 'renumber', 'move', 'missing-clip', 'duplicate-clip', 'extra-clip'):
            with self.subTest(issue=issue):
                invalid = copy.deepcopy(self.valid)
                clip = invalid['clips'][1]
                shots = clip['shots']
                if issue == 'missing':
                    shots.pop()
                elif issue == 'extra':
                    shots.append(dict(copy.deepcopy(shots[0]), id='S99'))
                elif issue == 'duplicate':
                    shots.append(copy.deepcopy(shots[0]))
                elif issue == 'renumber':
                    for i, shot in enumerate(shots, 1):
                        shot['id'] = f'S{i:02d}'
                elif issue == 'move':
                    invalid['clips'][0]['shots'].append(shots.pop())
                elif issue == 'missing-clip':
                    invalid['clips'].pop()
                elif issue == 'duplicate-clip':
                    invalid['clips'].append(copy.deepcopy(clip))
                else:
                    invalid['clips'].append(dict(copy.deepcopy(clip), id='C99'))
                before, layout_before = copy.deepcopy(invalid), copy.deepcopy(self.layout)
                (_, _, _, report), ai = self.compile([invalid, self.valid])
                self.assertEqual(ai.call_count, 2)
                repair = json.loads(ai.call_args.args[3])
                self.assertIn('shot_contract', repair)
                self.assertIn('예상', repair['repair']['validation_errors'][0])
                self.assertIn('응답', repair['repair']['validation_errors'][0])
                self.assertIn('clips', repair['repair']['validation_errors'][0])
                self.assertEqual(repair['repair']['previous_output'], invalid)
                self.assertTrue(report['repaired'])
                self.assertEqual(invalid, before)
                self.assertEqual(self.layout, layout_before)

    def test_failed_repair_is_precise_bounded_and_cannot_mutate_source_or_layout(self):
        invalid = copy.deepcopy(self.valid)
        invalid['clips'][1]['shots'].pop()
        layout, source = copy.deepcopy(self.layout), copy.deepcopy(self.doc)
        with patch.object(providers, 'generate_json', return_value=invalid) as ai:
            with self.assertRaisesRegex(ValidationError, r'1회.*clips.C02.shots.*예상.*응답.*누락'):
                conversion.compile_directions(self.doc, self.layout, None, [], 'ollama', 'fake', 'System', {})
        self.assertEqual(ai.call_count, 2)
        self.assertEqual(self.layout, layout)
        self.assertEqual(self.doc, source)

    def test_auto_pacing_and_selection_gaps_preserve_user_plan(self):
        for mode in ('auto', 'fixed', 'shots'):
            with self.subTest(mode=mode):
                selected = ['S02', 'S07', 'S09']
                layout = conversion.plan(self.doc, selected, split_mode=mode)
                draft = direction_output(layout)
                draft['clips'].reverse()
                (_, _, manifest, report), ai = self.compile([draft], layout=layout)
                self.assertEqual(ai.call_count, 1)
                self.assertTrue(report['reordered_by_id'])
                self.assertEqual({d['shot_id'] for d in manifest}, set(selected))

    def test_reordering_cannot_bypass_speaker_or_warning_validation(self):
        invalid = copy.deepcopy(self.valid)
        invalid['clips'].reverse()
        invalid['clips'][-1]['shots'][0]['speech_cues'][0]['speaker'] = 'unknown'
        (_, _, _, report), ai = self.compile([invalid, self.valid])
        self.assertEqual(ai.call_count, 2)
        self.assertTrue(report['repaired'])
        invalid = copy.deepcopy(self.valid)
        invalid['clips'].reverse()
        invalid['warnings'] = ['A real guide conflict']
        (_, output, _, _), ai = self.compile([invalid])
        self.assertEqual(output['warnings'], ['A real guide conflict'])
        self.assertEqual(ai.call_count, 1)

    def test_direct_renderer_and_refiner_remain_strict_and_show_the_same_paths(self):
        invalid = copy.deepcopy(self.valid)
        invalid['clips'][1]['shots'].pop()
        with self.assertRaisesRegex(ValidationError, 'clips.C02.shots'):
            prompt_renderer.assemble(self.doc, self.layout, invalid, None, [])
        with self.assertRaisesRegex(ValidationError, 'clips.C02.shots'):
            conversion.clip_flow.refine(copy.deepcopy(self.layout), invalid)
        self.assertEqual(conversion_structure.issues(self.layout, {'clips': 'malformed'}), [])

    def test_actual_provider_adapters_keep_structure_feedback_and_one_repair_budget(self):
        invalid = copy.deepcopy(self.valid)
        invalid['clips'][1]['shots'].pop()
        settings = {'OPENAI_API_KEY': 'fake', 'ANTHROPIC_API_KEY': 'fake'}
        for provider in ('openai', 'claude', 'ollama', 'lmstudio'):
            with self.subTest(provider=provider):
                calls = []

                def response(url, payload, headers):
                    calls.append(payload)
                    content = json.dumps(invalid if len(calls) == 1 else self.valid)
                    if provider == 'openai':
                        return {'status': 'completed', 'output': [{'type': 'message', 'content': [
                            {'type': 'output_text', 'text': content}]}]}
                    if provider == 'claude':
                        return {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': content}]}
                    if provider == 'lmstudio':
                        return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
                    return {'done': True, 'message': {'content': content}}

                with patch.object(providers, 'load_settings', return_value=settings), \
                     patch.object(providers, 'request_json', side_effect=response):
                    _, _, _, report = conversion.compile_directions(
                        self.doc, copy.deepcopy(self.layout), None, [], provider, 'fake', 'System', {})
                self.assertEqual(len(calls), 2)
                self.assertTrue(report['repaired'])
                self.assertIn('clips.C02.shots', report['issues'][0])
