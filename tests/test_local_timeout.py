import io
import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from storyboard import providers
from storyboard.schema import TEXT, obj


class LocalTimeoutTests(unittest.TestCase):
    def test_local_providers_wait_without_socket_timeout(self):
        chat = {"choices": [{"finish_reason": "stop", "message": {"content": '{"message":"ok"}'}}]}
        cases = [("lmstudio", {}, chat),
                 ("openai", {"OPENAI_API_KEY": "fake", "OPENAI_BASE_URL": "http://localhost:1234/v1", "OPENAI_API_MODE": "chat_completions"}, chat),
                 ("ollama", {}, {"done": True, "message": {"content": '{"message":"ok"}'}})]
        for provider, settings, body in cases:
            opener = Mock()
            opener.open.return_value = io.BytesIO(json.dumps(body).encode())
            with self.subTest(provider=provider), patch.object(providers, "load_settings", return_value=settings), \
                 patch.object(providers, "build_opener", return_value=opener):
                self.assertEqual(providers.generate_json(provider, "local", "system", "user", obj(message=TEXT)), {"message": "ok"})
            self.assertIsNone(opener.open.call_args.kwargs["timeout"])
            self.assertEqual(opener.open.call_count, 1)

    def test_ipv6_localhost_and_cloud_timeouts_are_distinct(self):
        for url, expected in (("http://[::1]:1234/v1/chat/completions", None),
                              ("https://api.openai.com/v1/responses", 180),
                              ("https://localhost.example/v1/chat/completions", 180)):
            opener = Mock()
            opener.open.return_value = io.BytesIO(b'{"ok":true}')
            with self.subTest(url=url), patch.object(providers, "build_opener", return_value=opener):
                self.assertEqual(providers.request_json(url, {}, {}), {"ok": True})
            self.assertEqual(opener.open.call_args.kwargs["timeout"], expected)

    def test_local_streaming_also_has_no_timeout(self):
        events = [{'choices': [{'delta': {'content': '{}'}, 'finish_reason': None}]},
                  {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}]
        body = b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events) + b"data: [DONE]\n\n"
        opener = Mock()
        opener.open.return_value = io.BytesIO(body)
        with patch.object(providers, "build_opener", return_value=opener):
            result = providers.request_json("http://127.0.0.1:1234/v1/chat/completions", {"stream": True}, {})
        self.assertEqual(result["choices"][0]["message"]["content"], "{}")
        self.assertIsNone(opener.open.call_args.kwargs["timeout"])

    def test_real_local_response_outlasts_process_socket_default(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                time.sleep(.1)
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        thread.start()
        previous = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(.02)
            self.assertEqual(providers.request_json(f"http://127.0.0.1:{server.server_port}/chat", {}, {}), {"ok": True})
        finally:
            socket.setdefaulttimeout(previous)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
