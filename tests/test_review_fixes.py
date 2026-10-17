"""Regressions for everyday use and the independently reproduced audit bugs."""

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bigbrain import client, config, loop, schema, scoring

KEY = 'fake-review-key-with-"quotes"-1234"\\'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        mode = self.server.mode
        if mode == "retry":
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "stream-error":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            body = {"error": {"type": "authentication_error", "message": KEY}}
            self.wfile.write(("event: error\ndata: " + json.dumps(body) + "\n\n").encode())
            return
        if mode == "slow":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for _ in range(20):
                    self.wfile.write(b": ping ")
                    self.wfile.flush()
                    time.sleep(.1)
            except OSError:
                pass
            return
        self.send_response(401 if mode == "http-error" else 200)
        self.send_header("Content-Type", "application/json")
        body = json.dumps({"error": {"message": "A" * 385 + KEY}}).encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CoreTests(unittest.TestCase):
    def test_explicit_user_request_overrides_score_threshold(self):
        self.assertEqual(scoring.score_task(user_request=True)["decision"], "escalate")
        self.assertEqual(scoring.score_task()["decision"], "stay_local")

    def test_done_requires_original_criteria_including_missing_and_unmet(self):
        transcript = {"rounds": [{}], "max_rounds": 8,
                      "acceptance_criteria": ["A", "B"],
                      "criteria_status": [{"criterion": "B", "met": False}]}
        reply, errors = schema.normalize_advisor({"status": "done", "summary": "done",
            "criteria_status": [{"criterion": "A", "met": True, "evidence": "test"}]})
        self.assertEqual(errors, [])
        self.assertNotEqual(loop.decide(transcript, reply)[0], "done")
        reply["criteria_status"].append({"criterion": "B", "met": True, "evidence": "test"})
        self.assertEqual(loop.decide(transcript, reply)[0], "done")

    def test_total_timeout_configuration_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in ("2", "0", "invalid"):
                cfg = config.load_config(env={"BIGBRAIN_MAX_TOTAL_TIMEOUT": value},
                                         json_file=Path(tmp)/"absent.json", config_file=Path(tmp)/"absent.env")
                if value == "2":
                    self.assertEqual(cfg.get("max_total_timeout"), 2)
                else:
                    self.assertTrue(any("MAX_TOTAL_TIMEOUT" in p for p in cfg["problems"]))


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def call(self, **overrides):
        cfg = {"base_url": "http://127.0.0.1:%d" % self.server.server_port,
               "api_key": KEY, "retries": 0, "timeout": 2, **overrides}
        return client.post_messages(cfg, {"model": "test", "max_tokens": 16,
                                          "messages": [{"role": "user", "content": "ping"}]})

    def test_error_paths_redact_key_before_truncation(self):
        for mode in ("http-error", "stream-error", "json-error"):
            for stream in (True, False) if mode != "stream-error" else (True,):
                with self.subTest(mode=mode, stream=stream):
                    self.server.mode = mode
                    with self.assertRaises(config.BigbrainError) as caught:
                        response = self.call(stream=stream)
                        response.text
                    rendered = str(caught.exception) + json.dumps(caught.exception.extra)
                    self.assertNotIn(KEY, rendered)
                    self.assertNotIn(json.dumps(KEY)[1:-1], rendered)
                    self.assertNotIn("fake-review-key", rendered)

    def test_total_timeout_stops_trickling_stream(self):
        self.server.mode = "slow"
        for stream in (True, False):
            with self.subTest(stream=stream):
                started = time.monotonic()
                with self.assertRaises(config.BigbrainError):
                    self.call(max_total_timeout=.2, stream=stream)
                self.assertLess(time.monotonic() - started, .8)

    def test_total_timeout_includes_retry_backoff(self):
        self.server.mode = "retry"
        started = time.monotonic()
        with self.assertRaises(config.BigbrainError):
            self.call(max_total_timeout=.2, retries=5, retry_backoff=1)
        self.assertLess(time.monotonic() - started, .8)


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("BIGBRAIN_", "ANTHROPIC_"))}
        self.env.update(HOME=str(self.work), CODEX_HOME=str(self.work/"codex"),
                        BIGBRAIN_BASE_URL="http://127.0.0.1:1", BIGBRAIN_API_KEY="fake-key-123456",
                        BIGBRAIN_MODEL="test", PYTHONDONTWRITEBYTECODE="1")

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, str(ROOT/"scripts/bigbrain_cli.py"), *args],
                                env=self.env, cwd=self.work, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_repair_cursor_and_quiet_completion_with_explicit_report(self):
        first = {"status": "continue", "summary": "first", "acceptance_criteria": ["A"]}
        done = {"status": "done", "summary": "second", "criteria_status": [
            {"criterion": "A", "met": True, "evidence": "test"}]}
        mock = self.work/"mock.json"
        mock.write_text(json.dumps([{"text": "invalid"}, {"text": json.dumps(first)},
                                    {"text": json.dumps(done)}]))
        session = self.work/"session"
        self.run_cli("start", "--task", "test", "--session", str(session), "--mock", str(mock))
        evidence = self.work/"result.txt"
        evidence.write_text("A passed")
        result = self.run_cli("report", "--session", str(session), "--mock", str(mock),
                              "--result-file", str(evidence), "--no-retrospective")
        self.assertEqual(json.loads(result.stdout)["summary"], "second")
        self.assertIn("DONE", result.stderr)
        self.assertNotIn("# bigbrain report", result.stdout + result.stderr)
        self.assertNotIn("report written:", result.stderr)
        result = self.run_cli("finish", "--session", str(session), "--no-retrospective")
        self.assertIn("# bigbrain report", result.stdout)

    def test_install_preserves_spaced_destination(self):
        destination = self.work/"space dir"
        result = subprocess.run(["bash", str(ROOT/"install.sh"), "--dir", str(destination), "--no-setup"],
                                env=self.env, cwd=self.work, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((destination/"bigbrain/SKILL.md").is_file())
        self.assertFalse((self.work/"space").exists())
        self.assertFalse((self.work/"dir").exists())

    def test_inspect_saved_config_without_contacting_provider(self):
        path = self.work/".bigbrain/config.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"base_url": "http://127.0.0.1:1", "model": "saved-model", "api_key": KEY}))
        env = {k: v for k, v in self.env.items() if not k.startswith("BIGBRAIN_")}
        result = subprocess.run([sys.executable, str(ROOT/"scripts/check_config.py"), "--no-call", "--json"],
                                env=env, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data["pinged"])
        self.assertEqual(data["model"], "saved-model")
        self.assertEqual(data["config_sources"], {"base_url": "json", "model": "json", "api_key": "json"})
        self.assertNotIn(KEY, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
