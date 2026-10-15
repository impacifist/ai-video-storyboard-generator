import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from storyboard import providers
from storyboard.schema import TEXT, obj


def event(delta=None, finish=None):
    return {'choices': [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}]}


def response(*events, done=True):
    body = b': keepalive\r\n\r\n'
    for item in events:
        body += b'data: ' + json.dumps(item, ensure_ascii=False).encode() + b'\r\n\r\n'
    if done:
        body += b'data: [DONE]\r\n\r\n'
    return io.BytesIO(body)


class ChatStreamTests(unittest.TestCase):
    def test_collects_unicode_content_ignores_reasoning_and_usage(self):
        result = providers.read_chat_stream(response(
            event({'reasoning_content': 'not output'}), event({'role': 'assistant'}),
            event({'content': '{"message":'}), event({'content': '"한국어"}'}),
            event(finish='stop'), {'choices': [], 'usage': {'total_tokens': 10}}))
        self.assertEqual(result, {'choices': [{'finish_reason': 'stop',
                         'message': {'content': '{"message":"한국어"}'}}]})

    def test_disconnect_and_missing_finish_never_succeed(self):
        for stream in (response(event({'content': '{}'}), done=False),
                       response(event({'content': '{}'})),
                       response(event({'content': '{}'}), event(finish='stop'), done=False)):
            with self.assertRaises(providers.ProviderError):
                providers.read_chat_stream(stream)

    def test_stream_errors_do_not_expose_server_text(self):
        with self.assertRaises(providers.ProviderError) as caught:
            providers.read_chat_stream(response({'error': {'message': 'secret-token'}}))
        self.assertNotIn('secret-token', str(caught.exception))

    def test_wire_size_is_bounded_including_ignored_events(self):
        with patch.object(providers, 'MAX_RESPONSE', 60), self.assertRaises(providers.ProviderError):
            providers.read_chat_stream(response(event({'reasoning_content': 'x' * 100})))

    def test_crowbot_adapter_uses_stream_and_keeps_output_validation(self):
        settings = {'OPENAI_API_KEY': 'fake-key', 'OPENAI_BASE_URL': 'https://api.crowbot.sh/v1',
                    'OPENAI_API_MODE': 'chat_completions', 'OPENAI_OUTPUT_MODE': 'prompt'}
        opener = Mock()
        opener.open.return_value = response(event({'content': '{"message":"ok"}'}), event(finish='stop'))
        with patch.object(providers, 'load_settings', return_value=settings), \
             patch.object(providers, 'build_opener', return_value=opener):
            self.assertEqual(providers.generate_json('openai', 'claude-opus-5-5', 'sys', 'user', obj(message=TEXT)),
                             {'message': 'ok'})
        request = opener.open.call_args.args[0]
        self.assertTrue(json.loads(request.data)['stream'])
        self.assertNotIn('response_format', json.loads(request.data))

    def test_truncation_refusal_and_tools_are_rejected_by_adapter(self):
        settings = {'OPENAI_API_KEY': 'fake-key', 'OPENAI_BASE_URL': 'https://api.crowbot.sh/v1',
                    'OPENAI_API_MODE': 'chat_completions'}
        for delta, finish in (({'content': '{}'}, 'length'),
                              ({'content': '{"message":"ok"}', 'refusal': 'refused'}, 'stop'),
                              ({'tool_calls': [{}]}, 'tool_calls')):
            opener = Mock()
            opener.open.return_value = response(event(delta), event(finish=finish))
            with self.subTest(finish=finish, delta=delta), \
                 patch.object(providers, 'load_settings', return_value=settings), \
                 patch.object(providers, 'build_opener', return_value=opener), \
                 self.assertRaises(providers.ProviderError):
                providers.generate_json('openai', 'm', 's', 'u', obj(message=TEXT))
            self.assertEqual(opener.open.call_count, 1)

    def test_gateway_timeouts_and_rate_limits_have_specific_safe_messages(self):
        for status, expected in ((504, '시간 초과'), (503, '서버 오류'), (502, '서버 오류'), (429, '동시 요청')):
            opener = Mock()
            opener.open.side_effect = HTTPError('url', status, 'secret-token', {}, None)
            with self.subTest(status=status), patch.object(providers, 'build_opener', return_value=opener):
                with self.assertRaises(providers.ProviderError) as caught:
                    providers.request_json('https://api.crowbot.sh/v1/chat/completions', {}, {})
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn('secret-token', str(caught.exception))
                self.assertEqual(opener.open.call_count, 1)


if __name__ == '__main__':
    unittest.main()
