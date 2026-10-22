"""Targeted instruction translation, no real provider calls or user narratives."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conversion_fixtures import direction_output
from storyboard import conversion, engine, instruction_translation, library, prompt_renderer, providers
from storyboard.schema import ValidationError


class InstructionTranslationTests(unittest.TestCase):
    def setUp(self):
        brief = json.loads((Path(__file__).resolve().parents[1] / 'examples/rainy-classroom.json').read_text(encoding='utf-8'))
        self.doc = engine.generate({'brief': brief, 'provider': 'demo'})
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        storage = patch.object(library, 'ROOT', Path(temporary.name))
        storage.start()
        self.addCleanup(storage.stop)
        self.board = library.save(self.doc)['id']
        self.payload = {'id': self.board, 'selected': [s['id'] for s in self.doc['story']['shots']],
                        'split_mode': 'fixed', 'guide_id': 'minimax-h3-text', 'provider': 'lmstudio', 'model': 'mock-gemma'}
        self.layout = conversion.preflight(self.doc, self.payload)[0]
        self.invalid = direction_output(self.layout)
        self.invalid['clips'][0]['shots'][0]['deliveries'][0] = '걱정스럽게'
        self.translated = {'translations': {'T001': 'With concern'}}

    def test_delivery_only_translation_for_every_guide_and_provider_keeps_scene_and_speech(self):
        source = copy.deepcopy(self.doc)
        for guide in ('minimax-h3-text', 'seedance-2-text', 'ltx-2.5-text'):
            for provider in ('openai', 'claude', 'ollama', 'lmstudio'):
                with self.subTest(guide=guide, provider=provider):
                    with patch.object(providers, 'generate_json', side_effect=[self.invalid, self.translated]) as ai:
                        result = conversion.compile_prompts(self.doc, {**self.payload, 'guide_id': guide, 'provider': provider})
                    self.assertEqual(ai.call_count, 2)
                    self.assertEqual(result['validation_report']['repair_kind'], 'instruction_translation')
                    self.assertEqual(result['validation_report']['translated_fields'], ['clips.C01.shots[0].deliveries[0]'])
                    request = json.loads(ai.call_args.args[3])
                    self.assertEqual(set(request), {'instruction_translations'})
                    self.assertEqual(request['instruction_translations'][0]['text'], '걱정스럽게')
                    self.assertNotIn('previous_output', request)
                    self.assertNotIn('brief', request)
                    expected = [d['text'] for s in self.doc['story']['shots'] for d in s['dialogue']]
                    self.assertEqual([d['text'] for d in result['dialogue_manifest']], expected)
                    for d in result['dialogue_manifest']:
                        self.assertIn(d['text'], next(c['prompt'] for c in result['output']['clips'] if c['id'] == d['clip_id']))
                    self.assertIn('With concern', result['output']['clips'][0]['prompt'])
                    self.assertEqual(self.doc, source)

    def test_multiple_invalid_fields_are_translated_in_one_atomic_patch(self):
        draft = copy.deepcopy(self.invalid)
        draft['clips'][0]['shots'][0]['camera']['movement'] = 'ゆっくり移動'
        draft['notes'] = ['Keep this existing note.', 'café lighting']
        draft['warnings'] = ['A real conflict']
        targets = instruction_translation.invalid_fields(draft)
        response = {'translations': {f'T{i:03d}': f'English instruction {i}' for i in range(1, len(targets) + 1)}}
        before = copy.deepcopy(draft)
        with patch.object(providers, 'generate_json', return_value=response) as ai:
            result, paths = instruction_translation.repair(draft, 'lmstudio', 'fake')
        self.assertEqual(ai.call_count, 1)
        self.assertEqual(len(paths), 3)
        self.assertEqual(result['warnings'], before['warnings'])
        self.assertEqual(result['notes'][0], before['notes'][0])
        expected = copy.deepcopy(before)
        for i, (path, _) in enumerate(targets, 1):
            current = expected
            for part in path[:-1]:
                current = current[part]
            current[path[-1]] = f'English instruction {i}'
        self.assertEqual(result, expected)
        self.assertEqual(draft, before)

    def test_non_english_internal_lookup_keys_are_not_translation_targets(self):
        draft = copy.deepcopy(self.invalid)
        draft['clips'][0]['shots'][0]['deliveries'][0] = 'With concern'
        draft['reference_notes'] = [{'label': '인물_키', 'note': 'Keep the face.', 'target_name': 'Face'}]
        draft['boundaries'] = [{'id': '경계', 'state': {'characters': [{'character_id': '인물',
            'position': 'Left', 'pose': 'Seated', 'gaze': 'Forward', 'emotion': 'Calm'}],
            'props': [{'name': '휴대전화', 'english_name': 'Phone', 'holder': '인물', 'position': 'On the seat'}]}}]
        self.assertEqual(instruction_translation.invalid_fields(draft), [])

    def test_bad_translation_never_saves_and_never_requests_a_third_call(self):
        for response in ({'translations': {}}, {'translations': {'T001': '걱정스럽게'}},
                         {'translations': {'T001': ''}}, {'translations': {'T001': 'With concern', 'T002': 'Extra'}},
                         {'clips': []}, {'translations': {'T001': '<d>Invented speech</d>'}}):
            with self.subTest(response=response):
                with patch.object(providers, 'generate_json', side_effect=[self.invalid, response]) as ai:
                    with self.assertRaisesRegex(ValidationError, '1회'):
                        conversion.compile_prompts(self.doc, self.payload)
                self.assertEqual(ai.call_count, 2)
                self.assertEqual(library.conversions(self.board), [])
                self.assertEqual(library.load(self.board), self.doc)

    def test_warning_cannot_be_erased_and_partial_failure_does_not_modify_input(self):
        invalid = copy.deepcopy(self.invalid)
        invalid['warnings'] = ['A genuine guide conflict']
        with patch.object(providers, 'generate_json', side_effect=[invalid, self.translated]):
            with self.assertRaisesRegex(ValidationError, 'A genuine guide conflict'):
                conversion.compile_prompts(self.doc, self.payload)
        before = copy.deepcopy(invalid)
        with patch.object(providers, 'generate_json', return_value={'translations': {'T001': '日本語'}}):
            with self.assertRaises(prompt_renderer.EnglishInstructionError):
                instruction_translation.repair(invalid, 'lmstudio', 'fake')
        self.assertEqual(invalid, before)

    def test_other_structural_repairs_do_not_gain_an_extra_translation_call(self):
        structural = copy.deepcopy(self.invalid)
        structural['clips'][0]['shots'].pop()
        with patch.object(providers, 'generate_json', side_effect=[structural, self.invalid]) as ai:
            with self.assertRaisesRegex(ValidationError, '1회'):
                conversion.compile_prompts(self.doc, self.payload)
        self.assertEqual(ai.call_count, 2)
        self.assertIn('repair', json.loads(ai.call_args.args[3]))

    def test_translation_provider_failure_is_not_retried(self):
        for error in (providers.ProviderError('timeout'), providers.OutputValidationError('bad translation schema', {})):
            with patch.object(providers, 'generate_json', side_effect=[self.invalid, error]) as ai:
                with self.assertRaises((providers.ProviderError, ValidationError)):
                    conversion.compile_prompts(self.doc, self.payload)
            self.assertEqual(ai.call_count, 2)

    def test_actual_adapters_accept_small_translation_schema_and_preserve_reordered_report(self):
        scrambled = copy.deepcopy(self.invalid)
        scrambled['clips'].reverse()
        settings = {'OPENAI_API_KEY': 'fake', 'ANTHROPIC_API_KEY': 'fake'}
        for provider in ('openai', 'claude', 'ollama', 'lmstudio'):
            with self.subTest(provider=provider):
                calls = []

                def response(url, payload, headers):
                    calls.append(payload)
                    content = json.dumps(scrambled if len(calls) == 1 else self.translated)
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
                    result = conversion.compile_prompts(self.doc, {**self.payload, 'provider': provider})
                self.assertEqual(len(calls), 2)
                self.assertEqual(result['validation_report']['repair_kind'], 'instruction_translation')
                self.assertEqual(result['validation_report']['reordered_by_id'], ['clips'])
