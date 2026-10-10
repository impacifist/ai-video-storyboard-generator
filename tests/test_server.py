import http.client
import json
import threading
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from server import Handler
from storyboard import library


class HTTPTests(unittest.TestCase):
    def test_reference_http_security_and_guide_catalog(self):
        import base64

        from test_guides_references import PNG

        with tempfile.TemporaryDirectory() as temporary, patch.object(library, "ROOT", Path(temporary)):
            status, _, raw = self.request("/api/guides")
            self.assertEqual(status, 200)
            self.assertEqual(len(json.loads(raw)["guides"]), 4)
            _, _, raw = self.request("/api/example")
            _, _, raw = self.request("/api/generate", {"brief": json.loads(raw), "provider": "demo"})
            document = json.loads(raw)["document"]
            key = library.save(document)["id"]
            payload = {"id": key, "character_id": document["brief"]["characters"][0]["id"], "name": "a.png",
                       "data": "data:image/png;base64," + base64.b64encode(PNG).decode()}
            for path, body in (("/api/references/upload", payload),
                               ("/api/references/save", {"id": key, "references": []})):
                self.assertEqual(self.request(path, body, {"Origin": "https://evil.example"})[0], 403)
            status, _, raw = self.request("/api/references/upload", payload)
            self.assertEqual(status, 200)
            image = json.loads(raw)["asset"]
            path = "/api/references/image/" + image["id"]
            status, headers, raw = self.request(path)
            self.assertEqual((status, headers["Content-Type"], raw), (200, "image/png", PNG))
            self.assertEqual(self.request(path, headers={"Origin": "https://evil.example"})[0], 403)
            self.assertEqual(self.request("/api/references/image/../../private")[0], 400)
            library.trash(key)
            self.assertEqual(self.request(path)[0], 400)
            library.trash(key, False)
            self.assertEqual(self.request(path)[0], 200)

    def test_library_http_flow_and_origin_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(library, "ROOT", Path(temporary)):
            _, _, raw = self.request("/api/example")
            brief = json.loads(raw)
            _, _, raw = self.request("/api/generate", {"brief": brief, "provider": "demo"})
            document = json.loads(raw)["document"]
            status, _, raw = self.request("/api/library/save", {"document": document})
            self.assertEqual(status, 200)
            key = json.loads(raw)["saved"]["id"]
            selected = [s["id"] for s in document["story"]["shots"]]
            for path, payload in (("/api/library/list", {}), ("/api/library/load", {"id": key}),
                                  ("/api/conversion/plan", {"id": key, "selected": selected})):
                self.assertEqual(self.request(path, payload)[0], 200)
                self.assertEqual(self.request(path, payload, {"Origin": "https://evil.example"})[0], 403)
            self.assertEqual(self.request("/api/library/delete", {"id": key}, {"Origin": "https://evil.example"})[0], 403)
            self.assertEqual(self.request("/api/library/delete", {"id": key})[0], 200)
            self.assertEqual(self.request("/api/conversion/plan", {"id": key, "selected": selected})[0], 400)
            self.assertEqual(self.request("/api/library/restore", {"id": key})[0], 200)
            self.assertEqual(self.request("/api/library/load", {"id": "../../private"})[0], 400)

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        body = json.dumps(payload) if payload is not None else None
        values = {"Content-Type": "application/json"} if body else {}
        values.update(headers or {})
        connection.request("POST" if payload is not None else "GET", path, body=body, headers=values)
        response = connection.getresponse()
        result = response.read()
        status, response_headers = response.status, dict(response.getheaders())
        connection.close()
        return status, response_headers, result

    def test_demo_generation_export_and_import_validation(self):
        status, _, raw = self.request("/api/example")
        self.assertEqual(status, 200)
        brief = json.loads(raw)
        status, _, raw = self.request("/api/generate", {"brief": brief, "provider": "demo"})
        self.assertEqual(status, 200)
        document = json.loads(raw)["document"]
        for path in ("/api/validate", "/api/export"):
            status, _, raw = self.request(path, {"document": document})
            self.assertEqual(status, 200)
        self.assertIn("markdown", json.loads(raw))

    def test_cross_origin_and_dns_rebinding_blocked(self):
        for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/api/generate", {}, headers)[0], 403)

    def test_only_json_posts(self):
        self.assertEqual(self.request("/api/generate", {}, {"Content-Type": "text/plain"})[0], 415)

    def test_private_files_and_unknown_routes_not_served(self):
        for path in ("/.env", "/.git/config", "/../server.py", "/README.md", "/missing"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_static_content_security_headers_and_utf8(self):
        status, headers, raw = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertIn("콘티 제작", raw.decode("utf-8"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        for path in ("/translations.js", "/i18n.js"):
            status, headers, raw = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn("text/javascript", headers["Content-Type"])
            self.assertTrue(raw)

    def test_invalid_import_rejected(self):
        self.assertEqual(self.request("/api/validate", {"document": {"schema_version": 999}})[0], 400)

    def test_settings_cross_origin_cannot_write(self):
        with patch("storyboard.providers.save_settings") as save:
            status, _, _ = self.request("/api/settings", {"values": {}, "clear_keys": []}, {"Origin": "https://evil.example"})
            self.assertEqual(status, 403)
            save.assert_not_called()

    def test_settings_endpoint_returns_only_public_configuration(self):
        with patch("storyboard.providers.save_settings", return_value={"providers": []}) as save:
            status, _, raw = self.request("/api/settings", {"values": {"OPENAI_API_KEY": "fake-test-key"}, "clear_keys": []})
            self.assertEqual(status, 200)
            self.assertNotIn(b"fake-test-key", raw)
            save.assert_called_once()

    def test_corrupt_settings_read_has_sanitized_error(self):
        with patch("storyboard.providers.configuration", side_effect=ValueError("fake-secret-private-path")):
            status, _, raw = self.request("/api/config")
            self.assertEqual(status, 500)
            self.assertNotIn(b"fake-secret", raw)


if __name__ == "__main__":
    unittest.main()
