"""Real loopback form endpoints backed by the local HTTPS provider fixture."""

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from test_setup import Handler, KEY, MODELS
from tls_fixture import tls_context
from bigbrain.setup_web import SetupServer
from bigbrain import setup_wizard as wizard


class WebSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tls = tempfile.TemporaryDirectory()
        context, cls.cert = tls_context(cls.tls.name)
        cls.api = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.api.socket = context.wrap_socket(cls.api.socket, server_side=True)
        cls.api_thread = threading.Thread(target=cls.api.serve_forever, daemon=True)
        cls.api_thread.start()
        cls.api_url = "https://127.0.0.1:%d" % cls.api.server_port

    @classmethod
    def tearDownClass(cls):
        cls.api.shutdown()
        cls.api.server_close()
        cls.api_thread.join()
        cls.tls.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"BIGBRAIN_HOME": self.temp.name, "SSL_CERT_FILE": self.cert})
        self.env.start()
        self.api.mode = "unpaginated"
        self.api.requests = []
        self.server = SetupServer(timeout=2)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = Path(self.temp.name) / "config.json"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.env.stop()
        self.temp.cleanup()

    def post(self, path, values, **headers):
        auth = {"Origin": self.server.origin, "X-Bigbrain-Token": self.server.token,
                "Content-Type": "application/json", **headers}
        request = urllib.request.Request(self.server.origin + path, data=json.dumps(values).encode(), headers=auth)
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read().decode()
            self.assertNotIn(KEY, body)
            return response.code, json.loads(body)

    def test_url_contains_only_session_token_and_assets_are_not_cached(self):
        self.assertEqual(self.server.url, self.server.origin + "/#" + self.server.token)
        with self.opener.open(self.server.origin) as response:
            html = response.read().decode()
            self.assertIn('type="url"', html)
            self.assertIn('pattern="https://.*"', html)
            self.assertIn('type="password"', html)
            self.assertIn('id="other-models" hidden', html)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_cross_origin_wrong_token_and_host_cannot_submit_credentials(self):
        for headers in ({"Origin": "https://evil.example"}, {"X-Bigbrain-Token": "wrong"},
                        {"Host": "evil.example"}):
            code, _ = self.post("/models", {"base_url": self.api_url, "api_key": KEY}, **headers)
            self.assertEqual(code, 403)
        self.assertEqual(self.api.requests, [])

    def test_plain_http_rejected_without_sending_credentials(self):
        code, result = self.post("/models", {"base_url": self.api_url.replace("https:", "http:"), "api_key": KEY})
        self.assertEqual(code, 400)
        self.assertIn("HTTPS", result["error"])
        self.assertIsNone(self.server.values)
        self.assertEqual(self.api.requests, [])

    def test_browser_discovery_then_verified_save_and_memory_cleanup(self):
        code, result = self.post("/models", {"base_url": self.api_url, "api_key": KEY})
        self.assertEqual(code, 200)
        self.assertEqual(result["models"], MODELS)
        self.assertFalse(self.config.exists())
        code, result = self.post("/save", {"model": MODELS[1]})
        self.assertEqual(code, 200)
        self.assertEqual(result["model"], MODELS[1])
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.assertIsNone(self.server.values)
        self.assertEqual(json.loads(self.config.read_text())["model"], MODELS[1])
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_invalid_key_clears_previous_discovery(self):
        self.post("/models", {"base_url": self.api_url, "api_key": KEY})
        code, result = self.post("/models", {"base_url": self.api_url, "api_key": "invalid-key"})
        self.assertEqual(code, 400)
        self.assertNotIn("invalid-key", result["error"])
        self.assertIsNone(self.server.values)
        self.assertEqual(self.post("/save", {"model": MODELS[0]})[0], 400)
        self.assertFalse(self.config.exists())

    def test_failed_probe_preserves_old_config_and_allows_retry(self):
        self.config.write_text('{"model":"old"}')
        before = self.config.read_bytes()
        self.post("/models", {"base_url": self.api_url, "api_key": KEY})
        self.api.mode = "rate_limit"
        self.assertEqual(self.post("/save", {"model": MODELS[0]})[0], 400)
        self.assertEqual(self.config.read_bytes(), before)
        self.api.mode = "unpaginated"
        self.assertEqual(self.post("/save", {"model": MODELS[0]})[0], 200)

    def test_cancel_drops_key_and_does_not_save(self):
        self.post("/models", {"base_url": self.api_url, "api_key": KEY})
        self.assertEqual(self.post("/cancel", {})[0], 200)
        self.thread.join(timeout=2)
        self.assertIsNone(self.server.values)
        self.assertFalse(self.config.exists())

    def test_error_response_does_not_expose_truncated_key(self):
        self.api.mode = "echo-error"
        code, result = self.post("/models", {"base_url": self.api_url, "api_key": KEY})
        self.assertEqual(code, 400)
        self.assertNotIn(KEY[:12], result["error"])
        self.assertIsNone(self.server.values)

    def test_catalogue_timeout_returns_error_and_allows_retry(self):
        self.api.mode = "slow-body"
        values = {"base_url": self.api_url, "api_key": KEY}
        with patch.object(wizard, "VALIDATE_TOTAL_TIMEOUT", 0.25):
            code, result = self.post("/models", values)
        self.assertEqual(code, 400)
        self.assertIn("timeout", result["error"])
        self.assertIsNone(self.server.values)
        self.assertFalse(self.config.exists())
        self.api.mode = "unpaginated"
        self.assertEqual(self.post("/models", values)[0], 200)
