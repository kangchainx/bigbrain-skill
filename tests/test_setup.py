"""Local HTTP regressions for model discovery and the Codex setup helpers."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from tls_fixture import tls_context

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from bigbrain import setup_wizard as wizard

KEY = "test-key-not-a-real-secret"
MODELS = ["model-with.dots", "provider/second-model", "third-model"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.server.requests.append(("GET", self.path))
        if self.headers.get("x-api-key") != KEY:
            self.respond(401, {"error": "rejected " + self.headers.get("x-api-key", "")})
            return
        if self.server.mode in ("echo-error", "echo-invalid-json"):
            body = ("A" * 385 + KEY).encode()
            self.send_response(401 if self.server.mode == "echo-error" else 200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.server.mode in ("slow-body", "slow-error", "slow-pages"):
            page = {"data": [{"id": MODELS[0]}]}
            if self.server.mode == "slow-pages" and "after_id" not in self.path:
                page.update(has_more=True, last_id=MODELS[0])
            body = json.dumps(page).encode()
            self.send_response(429 if self.server.mode == "slow-error" else 200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                for chunk in (body[:1], body[1:2], body[2:3], body[3:]):
                    time.sleep(0.1)
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except OSError:
                pass  # The deadline deliberately closes the client connection.
        elif self.server.mode == "missing":
            self.respond(404, {"error": "route missing"})
        elif self.server.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/v1/models")
            self.end_headers()
        elif self.server.mode == "empty":
            self.respond(200, {"data": []})
        elif self.server.mode == "malformed":
            self.respond(200, {"error": "not a catalogue"})
        elif self.server.mode == "repeat":
            self.respond(200, {"data": [{"id": MODELS[0]}], "has_more": True, "last_id": "same"})
        elif self.server.mode == "unpaginated":
            self.respond(200, {"object": "list", "data": [{"id": m} for m in MODELS]})
        elif parse_qs(urlsplit(self.path).query).get("after_id") == [MODELS[0]]:
            self.respond(200, {"data": [{"id": m} for m in MODELS], "has_more": False})
        else:
            self.respond(200, {"data": [{"id": MODELS[0]}], "has_more": True, "last_id": MODELS[0]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(("POST", body))
        if self.server.mode == "rate_limit":
            self.respond(429, {"error": {"message": "rate limited " + KEY}})
        else:
            self.respond(200, {"type": "message", "role": "assistant", "model": body["model"],
                               "content": [{"type": "text", "text": "pong"}], "stop_reason": "end_turn"})


class SetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tls = tempfile.TemporaryDirectory()
        context, cls.cert = tls_context(cls.tls.name)
        cls.trust = patch.dict(os.environ, {"SSL_CERT_FILE": cls.cert})
        cls.trust.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "https://127.0.0.1:%s" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.trust.stop()
        cls.tls.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.env = {"BIGBRAIN_HOME": self.temp.name, "SSL_CERT_FILE": self.cert}
        self.server.mode = "pages"
        self.server.requests = []

    def helper(self, action="list-models", **values):
        payload = {"base_url": self.base, "api_key": KEY, **values}
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "bigbrain_cli.py"), "setup", "--" + action, "--timeout", "2"],
            input=json.dumps(payload), text=True, capture_output=True, env=self.env, timeout=10,
        )
        self.assertNotIn(KEY, result.stdout + result.stderr)
        self.assertNotIn(payload["api_key"], result.stdout + result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_catalogue_reads_all_pages_and_deduplicates(self):
        code, result = self.helper()
        self.assertEqual(code, 0)
        self.assertEqual(result["models"], MODELS)
        self.assertFalse(result["generation_verified"])
        self.assertEqual(len(self.server.requests), 2)
        self.assertFalse(self.path.exists())

    def test_unpaginated_relay_and_trailing_v1(self):
        self.server.mode = "unpaginated"
        code, result = self.helper(base_url=self.base + "/v1/")
        self.assertEqual(code, 0)
        self.assertEqual(result["models"], MODELS)
        self.assertEqual(self.server.requests, [("GET", "/v1/models")])

    def test_wrong_key_blocks_selection_and_is_redacted(self):
        code, result = self.helper(api_key="wrong-secret-key")
        self.assertEqual(code, 4)
        self.assertFalse(result["ok"])
        self.assertNotIn("models", result)
        self.assertFalse(self.path.exists())

    def test_error_key_is_redacted_before_truncating_http_and_non_json_bodies(self):
        for mode in ("echo-error", "echo-invalid-json"):
            with self.subTest(mode=mode):
                self.server.mode = mode
                code, result = self.helper()
                self.assertNotEqual(code, 0)
                self.assertNotIn(KEY[:12], result["error"])

    def test_json_escaped_key_is_redacted_in_error_body(self):
        key = 'synthetic-"quoted"-key\\tail'
        code, result = self.helper(api_key=key)
        self.assertEqual(code, 4)
        self.assertNotIn(json.dumps(key)[1:-1], result["error"])
        self.assertNotIn("synthetic-", result["error"])

    def test_catalogue_deadline_covers_slow_success_error_and_multiple_pages(self):
        for mode, budget in (("slow-body", 0.25), ("slow-error", 0.25), ("slow-pages", 0.55)):
            with self.subTest(mode=mode):
                self.server.mode = mode
                self.path.write_text('{"model":"previous-model"}')
                before = self.path.read_bytes()
                with patch.object(wizard, "VALIDATE_TOTAL_TIMEOUT", budget), patch.dict(os.environ, self.env):
                    started = time.monotonic()
                    with self.assertRaises(wizard.BigbrainError) as caught:
                        wizard.configure({"base_url": self.base, "api_key": KEY, "model": MODELS[0]}, save=True)
                    elapsed = time.monotonic() - started
                self.assertEqual(caught.exception.exit_code, wizard.EXIT_NETWORK)
                self.assertIn("timeout", str(caught.exception))
                self.assertLess(elapsed, budget + 0.2)
                self.assertEqual(self.path.read_bytes(), before)

    def test_http_url_is_rejected_before_sending_the_key(self):
        code, result = self.helper(base_url=self.base.replace("https:", "http:"))
        self.assertEqual(code, 2)
        self.assertIn("HTTPS", result["error"])
        self.assertEqual(self.server.requests, [])

    def test_https_redirect_cannot_downgrade_credentials(self):
        self.server.mode = "redirect"
        code, result = self.helper()
        self.assertNotEqual(code, 0)
        self.assertIn("302", result["error"])
        self.assertEqual(len(self.server.requests), 1)

    def test_recommended_model_only_if_returned(self):
        self.assertIsNone(self.helper()[1]["recommended_model"])
        with patch.object(wizard, "discover_models", return_value=[wizard.PREFERRED_MODEL, *MODELS]):
            result = wizard.configure({"base_url": self.base, "api_key": KEY})
        self.assertEqual(result["recommended_model"], wizard.PREFERRED_MODEL)

    def test_other_models_are_hidden_until_expanded(self):
        output = []
        answers = iter(["2", "2"])

        def ask(prompt):
            if len(output) == 2:
                self.assertFalse(any(MODELS[0] in line for line in output))
            return next(answers)

        prompter = wizard.Prompter(ask=ask, out=output.append)
        selected = wizard.select_model(prompter, [wizard.PREFERRED_MODEL, *MODELS])
        self.assertEqual(selected, MODELS[1])

    def test_unusable_catalogues_fail_without_guessed_models(self):
        for mode in ("empty", "malformed", "missing", "repeat"):
            with self.subTest(mode=mode):
                self.server.mode = mode
                code, result = self.helper()
                self.assertNotEqual(code, 0)
                self.assertFalse(result["ok"])
                self.assertNotIn("models", result)
                self.assertFalse(self.path.exists())

    def test_save_requires_catalogue_member(self):
        for model in ("invented-model", None):
            code, result = self.helper("save", model=model)
            self.assertNotEqual(code, 0)
            self.assertFalse(result["ok"])
            self.assertFalse(self.path.exists())
        self.assertFalse(any(method == "POST" for method, _ in self.server.requests))

    def test_selected_model_probed_then_saved_privately(self):
        self.path.write_text('{"threshold": 0.4}')
        code, result = self.helper("save", model=MODELS[1])
        self.assertEqual(code, 0)
        self.assertTrue(result["generation_verified"])
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["model"], MODELS[1])
        self.assertEqual(saved["threshold"], 0.4)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        probes = [body for method, body in self.server.requests if method == "POST"]
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0]["model"], MODELS[1])
        self.assertEqual(probes[0]["max_tokens"], 16)

    def test_failed_probe_preserves_existing_config(self):
        self.server.mode = "rate_limit"
        self.path.write_text('{"model": "previous-model"}')
        before = self.path.read_bytes()
        code, result = self.helper("save", model=MODELS[0])
        self.assertNotEqual(code, 0)
        self.assertFalse(result["ok"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sum(method == "POST" for method, _ in self.server.requests), 1)

    def test_explicit_input_wins_during_probe_but_reports_runtime_override(self):
        self.env["BIGBRAIN_BASE_URL"] = "http://127.0.0.1:9"
        self.env["BIGBRAIN_API_KEY"] = "unrelated-ambient-key"
        code, result = self.helper("save", model=MODELS[0])
        self.assertEqual(code, 0)
        self.assertEqual(set(result["environment_overrides"]), {"BIGBRAIN_BASE_URL", "BIGBRAIN_API_KEY"})

    def test_invalid_json_and_url_do_not_print_secrets_or_send_requests(self):
        for payload in ('{"api_key":"' + KEY, '[]', json.dumps({"base_url": "ftp://example.com", "api_key": KEY})):
            output = io.StringIO()
            with patch("sys.stdin", io.StringIO(payload)), contextlib.redirect_stdout(output):
                code = wizard.run_json("list-models")
            self.assertNotEqual(code, 0)
            self.assertNotIn(KEY, output.getvalue())
        self.assertEqual(self.server.requests, [])

    def test_invalid_header_value_never_reaches_http_or_traceback(self):
        code, result = self.helper(api_key=KEY + "\nsecond-line")
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertEqual(self.server.requests, [])

    def test_terminal_auth_failure_never_asks_for_model(self):
        prompts = []
        answers = iter(["3", self.base, "a"])

        def ask(prompt):
            prompts.append(prompt)
            return next(answers)

        prompter = wizard.Prompter(ask=ask, secret=lambda _: "wrong-secret-key", out=lambda *_: None)
        with patch.object(wizard, "detect", return_value=[]):
            self.assertEqual(wizard.run_wizard(env=self.env, io=prompter), 1)
        self.assertFalse(any("Model" in prompt for prompt in prompts))
        self.assertFalse(self.path.exists())

    def test_terminal_shows_every_model_and_requires_explicit_choice(self):
        output, prompts = [], []
        answers = iter(["3", self.base, "", "invented", "2"])

        def ask(prompt):
            prompts.append(prompt)
            if "Model (" in prompt:
                self.assertTrue(all(any(model in line for line in output) for model in MODELS))
            return next(answers)

        prompter = wizard.Prompter(ask=ask, secret=lambda _: KEY, out=output.append)
        with patch.object(wizard, "detect", return_value=[]):
            self.assertEqual(wizard.run_wizard(env=self.env, io=prompter), 0)
        self.assertEqual(json.loads(self.path.read_text())["model"], MODELS[1])
        self.assertEqual(sum("Model (" in prompt for prompt in prompts), 3)
        self.assertNotIn(KEY, "\n".join(output))


if __name__ == "__main__":
    unittest.main()
