import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import conversion, engine, library, providers
from storyboard.schema import ValidationError


class ConversionRequestTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        storage = patch.object(library, 'ROOT', Path(temp.name))
        storage.start()
        self.addCleanup(storage.stop)
        brief = json.loads((Path(__file__).resolve().parents[1] / 'examples/rainy-classroom.json').read_text(encoding='utf-8'))
        self.doc = engine.generate({'brief': brief, 'provider': 'demo'})
        for shot, duration in zip(self.doc['story']['shots'], [4, 4, 4, 5, 7, 6]):
            shot['duration'] = duration
        self.doc['story']['shots'][3]['actions'] = ['Raise a hand.', 'Lower the hand after the reply.']
        self.key = library.save(self.doc)['id']
        self.payload = {'id': self.key, 'selected': [s['id'] for s in self.doc['story']['shots']],
                        'split_mode': 'fixed', 'guide_id': 'minimax-h3-text', 'provider': 'lmstudio', 'model': 'mock'}

    def preview(self):
        with patch.object(providers, 'generate_json', side_effect=AssertionError('No AI in preview')), \
             patch.object(providers, 'load_settings', side_effect=AssertionError('No credentials in preview')):
            return conversion.preview_request(self.doc, self.payload)

    def edit(self):
        preview = self.preview()
        return {k: preview[k] for k in ('fingerprint', 'system', 'user')}

    def fake(self, provider, model, system, user, schema):
        return direction_output(json.loads(user)['plan'])

    def test_preview_is_exact_initial_input_without_provider_or_settings_access(self):
        preview = self.preview()
        with patch.object(providers, 'generate_json', side_effect=self.fake) as ai:
            result = conversion.compile_prompts(self.doc, self.payload)
        self.assertEqual(ai.call_count, 1)
        self.assertEqual(preview['system'], ai.call_args.args[2])
        self.assertEqual(preview['user'], json.loads(ai.call_args.args[3]))
        self.assertEqual(preview['schema'], ai.call_args.args[4])
        self.assertEqual(preview['provider_system'], providers.format_instruction(ai.call_args.args[2], ai.call_args.args[4]))
        self.assertEqual(result['request_trace'][0]['provider_system'], preview['provider_system'])
        self.assertEqual(result['request_trace'][0]['user'], preview['user'])
        self.assertFalse(result['request_edited'])
        self.assertEqual(library.conversions(self.key), [])

    def test_split_actions_and_dialogue_are_visible_with_original_offsets(self):
        preview = self.preview()
        pieces = [s for c in preview['user']['plan']['clips'] for s in c['shots'] if s['id'] == 'S04']
        self.assertEqual(len(pieces), 2)
        self.assertEqual([s['source_offset'] for s in pieces], [0, 3])
        self.assertTrue(all(s['action_scope'] == 'whole_source_context' for s in pieces))
        self.assertEqual(pieces[0]['source']['actions'], pieces[1]['source']['actions'])
        self.assertIn('Do not pull a later shot', preview['system'])

    def test_segment_and_context_edits_are_applied_only_to_this_request(self):
        edit = self.edit()
        edit['system'] = 'Use restrained acting.\n' + edit['system']
        edit['user']['brief']['ending'] = 'Background context only.'
        first = edit['user']['plan']['clips'][0]['shots'][-1]
        first['source']['actions'] = ['Raise a hand; do not lower it yet.']
        first['segment_instruction'] = 'Only raise the hand in this segment.'
        self.payload['request_edit'] = edit
        checked = conversion.preview_request(self.doc, self.payload)
        # Applying a validated preview again must be idempotent, including its derived scope flag.
        self.payload['request_edit'] = {k: checked[k] for k in ('fingerprint', 'system', 'user')}
        with patch.object(providers, 'generate_json', side_effect=self.fake) as ai:
            result = conversion.compile_prompts(self.doc, self.payload)
        request = json.loads(ai.call_args.args[3])
        self.assertEqual(request['plan']['clips'][0]['shots'][-1]['source']['actions'], first['source']['actions'])
        self.assertEqual(request['plan']['clips'][0]['shots'][-1]['action_scope'], 'user_edited_segment')
        self.assertEqual(request['plan']['clips'][1]['shots'][0]['source']['actions'], self.doc['story']['shots'][3]['actions'])
        self.assertEqual(library.load(self.key), self.doc)
        self.assertTrue(result['request_edited'])
        self.assertEqual(result['director_output']['clips'][0]['shots'][0]['id'], 'S01')
        self.assertEqual([d['text'] for d in result['dialogue_manifest']],
                         [d['text'] for s in self.doc['story']['shots'] for d in s['dialogue']])

    def test_immutable_ids_timing_speech_states_and_references_cannot_be_changed(self):
        for field in ('id', 'duration', 'speaker', 'text', 'state', 'references', 'count', 'scope'):
            with self.subTest(field=field):
                edit = self.edit()
                shot = edit['user']['plan']['clips'][0]['shots'][0]
                if field == 'id':
                    shot['id'] = 'S99'
                elif field == 'duration':
                    shot['end'] = 0
                elif field in ('speaker', 'text'):
                    shot['source']['dialogue'][0][field] = 'changed'
                elif field == 'state':
                    shot['source']['start_state']['characters'][0]['position'] = 'changed'
                elif field == 'references':
                    edit['user']['references'].append({'label': 'invented'})
                elif field == 'count':
                    edit['user']['plan']['clips'][0]['shots'].pop()
                else:
                    shot['source_offset'] = False
                with patch.object(providers, 'generate_json') as ai:
                    with self.assertRaises(ValidationError):
                        conversion.compile_prompts(self.doc, {**self.payload, 'request_edit': edit})
                    ai.assert_not_called()

    def test_stale_request_is_rejected_after_configuration_or_source_changes(self):
        edit = self.edit()
        for change in ({'limit': 10}, {'model': 'different'}, {'provider': 'openai'}, {'selected': ['S01']}):
            with self.subTest(change=change), patch.object(providers, 'generate_json') as ai:
                with self.assertRaisesRegex(ValidationError, '다시 불러오세요'):
                    conversion.compile_prompts(self.doc, {**self.payload, **change, 'request_edit': edit})
                ai.assert_not_called()
        doc = copy.deepcopy(self.doc)
        doc['story']['shots'][0]['visual'] += ' Changed.'
        with self.assertRaisesRegex(ValidationError, '다시 불러오세요'):
            conversion.preview_request(doc, {**self.payload, 'request_edit': edit})

    def test_translation_repair_trace_records_the_small_actual_translation_request(self):
        preview = self.preview()
        draft = direction_output(preview['user']['plan'])
        draft['clips'][0]['shots'][0]['deliveries'][0] = '조용하게'
        with patch.object(providers, 'generate_json', side_effect=[draft, {'translations': {'T001': 'Quietly'}}]):
            result = conversion.compile_prompts(self.doc, self.payload)
        self.assertEqual([r['phase'] for r in result['request_trace']], ['initial', 'instruction_translation'])
        self.assertIn('instruction_translations', result['request_trace'][1]['user'])
        self.assertNotIn('brief', result['request_trace'][1]['user'])
        self.assertNotIn('API_KEY', json.dumps(result['request_trace']))
