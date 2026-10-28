"""CLI transport and correction lifecycle, isolated from real credentials/models."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bigbrain import config, io, report


class ClaudeCodeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.session = self.work / "session"
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.reply = self.work / "reply.json"
        self.capture = self.work / "capture.json"
        fake = self.bin / "claude"
        fake.write_text("#!" + sys.executable + "\n" + '''
import json, os, sys
from pathlib import Path
if sys.argv[1:] == ['auth', 'status']:
    print(json.dumps({'loggedIn': True, 'authMethod': 'test', 'apiProvider': 'fake'}))
else:
    if os.environ.get('FAKE_TIMEOUT'):
        import time
        time.sleep(30)
    Path(os.environ['CAPTURE']).write_text(json.dumps({
        'argv': sys.argv[1:], 'pid': os.getpid(), 'cwd': os.getcwd(), 'input': json.loads(sys.stdin.read())}))
    print(json.dumps({'type': 'assistant', 'message': {'content': [
        {'type': 'thinking', 'thinking': 'PRIVATE_THINKING_MUST_NOT_LEAK'},
        {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'app.py'}}]}}))
    data = json.loads(Path(os.environ['REPLY']).read_text())
    sid = sys.argv[sys.argv.index('--resume') + 1] if '--resume' in sys.argv else sys.argv[sys.argv.index('--session-id') + 1] if '--session-id' in sys.argv else 'ephemeral'
    native = Path.home() / (sid + '.json')
    if '--resume' in sys.argv and not native.exists():
        print(json.dumps({'type': 'result', 'session_id': sid, 'is_error': True, 'num_turns': 0,
            'duration_api_ms': 0, 'errors': ['No conversation found with session ID: ' + sid],
            'total_cost_usd': 0, 'usage': {'input_tokens': 0, 'output_tokens': 0}}))
        sys.exit(1)
    cost_before = json.loads(native.read_text()).get('cost', 0) if native.exists() else 0
    if 'total_cost_usd' in data:
        data['total_cost_usd'] += cost_before
    native.write_text(json.dumps({'cost': data.get('total_cost_usd', cost_before)}))
    data['session_id'] = sid
    if os.environ.get('FAKE_BAD_FIRST') and cost_before == 0:
        data['result'] = 'invalid advisor JSON'
    if os.environ.get('FAKE_COMPACT'):
        print(json.dumps({'type': 'system', 'subtype': 'compact_boundary'}))
    with open(os.environ['CAPTURE'] + '.calls', 'a') as out:
        out.write(sid + chr(10))
    print(json.dumps(data), flush=True)
    if os.environ.get('FAKE_AFTER_RESULT_WAIT'):
        import time
        time.sleep(30)
''')
        fake.chmod(0o700)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("BIGBRAIN_", "ANTHROPIC_", "CODEX_THREAD_ID"))}
        self.env.update(PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        HOME=str(self.work), BIGBRAIN_HOME=str(self.work / "home"),
                        BIGBRAIN_BACKEND="claude-code", BIGBRAIN_CLAUDE_MODEL="opus",
                        CODEX_THREAD_ID="chat-a", CAPTURE=str(self.capture), REPLY=str(self.reply),
                        BIGBRAIN_COMPRESS="1", PYTHONDONTWRITEBYTECODE="1")
        self.evidence = self.work / "evidence.txt"
        self.evidence.write_text("A passed")
        self.set_reply()
        self.cli("mode", "on")

    def set_reply(self, status="continue", criteria=None, error=False, cost=0.12, usage=True):
        criteria = criteria or ["A"]
        response = {"status": status, "summary": "Inspect and verify A",
                    "acceptance_criteria": ["A"], "next_instructions": "Check A",
                    "criteria_status": [{"criterion": c, "met": status == "done", "evidence": "verified"}
                                        for c in criteria]}
        data = {"type": "result", "result": json.dumps(response), "is_error": error,
                "modelUsage": {"claude-test": {}}, "session_id": "fresh-call-id"}
        if cost is not None:
            data["total_cost_usd"] = cost
        if usage:
            data["usage"] = {"input_tokens": 10, "cache_read_input_tokens": 20,
                             "cache_creation_input_tokens": 30, "output_tokens": 5}
        self.reply.write_text(json.dumps(data))

    def cli(self, *args, code=0, env=None, cwd=None):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/bigbrain_cli.py"), *args],
                                cwd=cwd or self.work, env=env or self.env, text=True,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertNotIn("PRIVATE_THINKING", result.stdout + result.stderr)
        return result

    def start(self, *args, code=0):
        return self.cli("start", "--task", "Verify A", "--session", str(self.session),
                        "--no-retrospective", *args, code=code)

    def transcript(self):
        return json.loads((self.session / "transcript.json").read_text())

    def review(self, *args, **kwargs):
        return self.cli("report", "--session", str(self.session), "--result-file", str(self.evidence),
                        "--no-retrospective", *args, **kwargs)

    def test_cli_config_needs_no_api_key(self):
        cfg = config.load_config(env=self.env, config_file=self.work / "absent")
        self.assertEqual(cfg["model"], "opus")
        self.assertEqual(config.config_problems(cfg), [])

    def test_fresh_review_after_done_resumes_same_session_with_new_evidence(self):
        self.start()
        self.set_reply("done")
        self.review()
        self.assertEqual(self.transcript()["status"], "done")
        native_id = json.loads((self.session / "claude-session.json").read_text())["id"]
        calls = self.call_count()
        self.evidence.write_text("New scope: UI diff after analytics review; verify render status accessibility.")
        self.review("--force")
        self.assertEqual(self.call_count(), calls + 1)
        captured = json.loads(self.capture.read_text())
        self.assertEqual(captured["argv"][captured["argv"].index("--resume") + 1], native_id)
        self.assertIn("UI diff after analytics review", json.dumps(captured["input"]))
        self.cli("mode", "off")
        self.review("--force", code=2)
        self.assertEqual(self.call_count(), calls + 1)

    def test_read_only_flags_images_history_and_actual_model(self):
        from test_vision import PNG
        image = self.work / "image.png"
        image.write_bytes(PNG)
        result = self.start("--image-file", str(image), "--effort", "high")
        self.assertIn("Claude | Read: app.py", result.stderr)
        captured = json.loads(self.capture.read_text())
        argv = captured["argv"]
        for flag in ("--safe-mode", "--session-id", "--strict-mcp-config"):
            self.assertIn(flag, argv)
        for flag in ("--resume", "--continue", "--dangerously-skip-permissions", "--no-session-persistence"):
            self.assertNotIn(flag, argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep")
        self.assertEqual(argv[argv.index("--effort") + 1], "high")
        blocks = captured["input"]["message"]["content"]
        self.assertEqual([b for b in blocks if b["type"] == "image"],
                         [b for b in io.attach_images("", [image]) if b["type"] == "image"])
        other = self.work / "other"
        other.mkdir()
        self.review(cwd=other)
        captured = json.loads(self.capture.read_text())
        self.assertEqual(Path(captured["cwd"]).resolve(), self.work.resolve())
        self.assertNotIn("ASSISTANT", json.dumps(captured["input"]))
        self.assertIn("--resume", captured["argv"])
        self.assertEqual(self.transcript()["usage"]["models"], ["claude-test"])
        self.assertEqual(self.transcript()["model"], "claude-test")

    def test_reported_cost_and_cache_counts(self):
        self.start()
        self.set_reply("done", cost=0.05)
        summary = json.loads(self.review().stdout)["cost_summary"]
        self.assertAlmostEqual(summary["advisor_usd"], 0.17)
        self.assertEqual(summary["total_tokens"], 130)
        self.assertIn("Claude Code reported", summary["message"])
        self.assertFalse(summary["incomplete"])

    def test_missing_cost_or_tokens_marks_incomplete(self):
        self.set_reply("done", cost=None, usage=False)
        summary = json.loads(self.start().stdout)["cost_summary"]
        self.assertTrue(summary["incomplete"])
        self.assertIn("total cost unknown", summary["message"])

    def test_timeout_has_no_retry_and_marks_unknown_usage(self):
        self.env.update(FAKE_TIMEOUT="1", BIGBRAIN_MAX_TOTAL_TIMEOUT="1")
        self.start(code=3)
        saved = self.transcript()
        self.assertTrue(saved["cost_incomplete"])
        self.assertEqual(saved["usage"]["calls"], 0)

    def test_paid_error_receipt_survives_later_success_without_prompt_text(self):
        self.set_reply(error=True)
        self.start(code=6)
        self.set_reply('done')
        self.review()
        receipts = [json.loads(p.read_text()) for p in (self.session / 'claude-receipts').glob('*.json')]
        self.assertEqual(len(receipts), 2)
        calls = [c for r in receipts for c in r['calls']]
        self.assertAlmostEqual(sum(c['usage']['cli_cost_usd'] for c in calls), 0.24)
        self.assertEqual(len(set(c['id'] for c in calls)), 2)
        self.assertNotIn('Verify A', json.dumps(receipts))

    def test_failure_keeps_spend_without_repair_or_fallback(self):
        self.set_reply(error=True)
        self.start(code=6)
        saved = self.transcript()
        self.assertEqual(saved["usage"]["calls"], 1)
        self.assertEqual(saved["usage"]["cli_cost_usd"], 0.12)
        self.assertNotEqual(saved["status"], "done")
        self.assertTrue(saved["cost_incomplete"])

    def test_auxiliary_model_first_is_not_reported_as_advisor(self):
        data = json.loads(self.reply.read_text())
        data["modelUsage"] = {"auxiliary": {"outputTokens": 1}, "claude-test": {"outputTokens": 9}}
        self.reply.write_text(json.dumps(data))
        self.start()
        response = json.loads((self.session / "round-01-response.json").read_text())
        self.assertEqual(response["meta"]["model"], "claude-test")
        self.assertEqual(self.transcript()["usage"]["models"], ["auxiliary", "claude-test"])

    def test_dry_run_does_not_launch_cli_or_write_session(self):
        data = json.loads(self.start("--dry-run").stdout)["request"]
        self.assertEqual(data["backend"], "claude-code")
        self.assertNotIn("max_tokens", data)
        self.assertFalse(self.capture.exists())
        self.assertFalse(self.session.exists())

    def test_quiet_hides_file_activity(self):
        result = self.start("--quiet")
        self.assertNotIn("Claude | Read", result.stderr)

    def test_feedback_reopens_done_and_requires_fresh_review(self):
        self.set_reply("done")
        self.start()
        result = self.cli("feedback", "--session", str(self.session), "--reason",
                          "Still wrong: button is invisible", "--no-retrospective")
        self.assertEqual(json.loads(result.stdout)["status"], "continue")
        saved = self.transcript()
        self.assertNotEqual(saved["status"], "done")
        self.assertFalse(any(c["met"] for c in saved["criteria_status"]))
        self.assertGreater(saved["max_rounds"], len(saved["rounds"]))
        self.set_reply()
        for _ in range(3):
            self.review()
        self.assertIn("button is invisible", self.capture.read_text())
        self.set_reply("done")  # Omitting the correction must not approve completion.
        result = self.review()
        self.assertNotEqual(self.transcript()["status"], "done")
        self.set_reply("done", criteria=["A", "User correction 1 is resolved"])
        self.review()
        self.assertEqual(self.transcript()["status"], "done")

    def test_failed_feedback_invalidates_done_before_network_call(self):
        self.set_reply("done")
        self.start()
        self.set_reply(error=True)
        self.cli("feedback", "--session", str(self.session), "--reason", "Still wrong", code=6)
        saved = self.transcript()
        self.assertNotEqual(saved["status"], "done")
        self.assertTrue(saved["feedback_needs_diagnosis"])
        self.review(code=2)

    def test_session_backend_is_pinned_and_other_chat_cannot_use_it(self):
        self.start()
        self.review(env=dict(self.env, BIGBRAIN_BACKEND="api", BIGBRAIN_MODEL="wrong"))
        self.review(env=dict(self.env, CODEX_THREAD_ID="chat-b"), code=2)

    def test_setup_preserves_existing_api_credentials(self):
        path = Path(self.env["BIGBRAIN_HOME"]) / "config.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"api_key": "keep-me", "model": "legacy", "threshold": 0.3}))
        self.cli("setup", "--claude-code")
        saved = json.loads(path.read_text())
        self.assertEqual(saved["api_key"], "keep-me")
        self.assertEqual(saved["backend"], "claude-code")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def call_count(self):
        path = Path(str(self.capture) + '.calls')
        return len(path.read_text().splitlines()) if path.exists() else 0

    def simulate_uncommitted_receipt(self, no_transcript=False):
        path = self.session / 'claude-journal.json'
        journal = json.loads(path.read_text())
        journal['state'] = 'captured'
        path.write_text(json.dumps(journal))
        if no_transcript:
            (self.session / 'transcript.json').unlink()
        else:
            (self.session / 'transcript.json').write_text(json.dumps(journal['snapshot']))
        return journal

    def test_captured_start_without_transcript_recovers_with_zero_extra_calls_and_cost_once(self):
        self.start()
        sid = self.transcript()['claude_session']['id']
        self.simulate_uncommitted_receipt(no_transcript=True)
        self.cli('status', '--session', str(self.session), '--json')
        self.cli('recover', '--session', str(self.session))
        self.assertEqual(self.call_count(), 1)
        self.assertEqual(self.transcript()['usage']['calls'], 1)
        self.assertEqual(len(list((self.session / 'claude-receipts').glob('*.json'))), 1)
        self.assertAlmostEqual(self.transcript()['usage']['cli_cost_usd'], 0.12)
        self.assertEqual(self.transcript()['claude_session']['id'], sid)
        self.cli('recover', '--session', str(self.session))
        self.assertEqual(self.call_count(), 1)
        self.assertEqual(self.transcript()['usage']['calls'], 1)

    def test_captured_feedback_recovers_without_duplicate_correction_or_cost(self):
        self.start()
        self.cli('feedback', '--session', str(self.session), '--reason', 'visual goal unmet', '--no-retrospective')
        self.simulate_uncommitted_receipt()
        self.cli('recover', '--session', str(self.session))
        self.assertEqual(self.call_count(), 2)
        self.assertEqual(len(self.transcript()['user_feedback']), 1)
        self.assertEqual(self.transcript()['usage']['calls'], 2)

    def test_unknown_outcome_blocks_report_and_recover_with_zero_extra_calls(self):
        self.start()
        journal = self.simulate_uncommitted_receipt()
        del journal['calls'][0]['response']
        (self.session / 'claude-journal.json').write_text(json.dumps(journal))
        self.review(code=2)
        result = self.cli('recover', '--session', str(self.session), code=2)
        self.assertIn('Outcome unknown', result.stderr)
        self.assertEqual(self.call_count(), 1)

    def test_task_binding_mismatch_and_force_start_rejected_without_call(self):
        self.start()
        self.start('--force', code=2)
        t = self.transcript()
        t['task'] = 'different task'
        (self.session / 'transcript.json').write_text(json.dumps(t))
        self.review(code=2)
        self.assertEqual(self.call_count(), 1)

    def test_busy_task_rejected_before_mutation_and_lock_released(self):
        from bigbrain.native_session import lock
        self.start()
        before = (self.session / 'transcript.json').read_bytes()
        with lock(self.session):
            self.review(code=2)
        self.assertEqual((self.session / 'transcript.json').read_bytes(), before)
        self.assertEqual(self.call_count(), 1)
        self.review()
        self.assertEqual(self.call_count(), 2)

    def test_missing_native_session_does_not_create_replacement(self):
        self.start()
        sid = self.transcript()['claude_session']['id']
        (self.work / (sid + '.json')).unlink()
        self.review(code=6)
        self.assertEqual(self.transcript()['claude_session']['id'], sid)
        self.assertFalse((self.work / (sid + '.json')).exists())
        self.assertIn('--resume', json.loads(self.capture.read_text())['argv'])
        state = self.transcript()['claude_session']
        self.assertTrue(state['missing_session'])
        self.assertAlmostEqual(state['cost_cumulative'], 0.12)
        self.assertFalse(self.transcript().get('cost_incomplete', False))
        info = self.cli('status', '--session', str(self.session), '--json').stdout
        self.assertIn('Missing native session', info)
        self.assertIn(sid, info)
        self.assertIn('-replacement', info)
        (self.work / (sid + '.json')).write_text('{"cost": 0.12}')
        self.review()
        self.assertFalse(self.transcript()['claude_session']['missing_session'])
        self.assertAlmostEqual(self.transcript()['usage']['cli_cost_usd'], 0.24)

    def test_compaction_preserves_contract_and_native_id_without_history_replay(self):
        self.start()
        sid = self.transcript()['claude_session']['id']
        self.env['FAKE_COMPACT'] = '1'
        self.review()
        captured = json.loads(self.capture.read_text())
        body = json.dumps(captured['input'])
        self.assertIn('REASSERTED TASK CONTRACT', body)
        self.assertIn('acceptance_criteria', body)
        self.assertNotIn('# ASSISTANT', body)
        self.assertEqual(self.transcript()['claude_session']['compactions'], 1)
        self.assertEqual(self.transcript()['claude_session']['id'], sid)

    def test_legacy_task_bootstraps_once_with_full_history_then_resumes(self):
        self.start()
        for name in ['claude-session.json', 'claude-journal.json']:
            (self.session / name).unlink()
        self.review()
        argv = json.loads(self.capture.read_text())['argv']
        self.assertIn('--session-id', argv)
        self.assertIn('# ASSISTANT', json.dumps(json.loads(self.capture.read_text())['input']))
        self.assertTrue(self.transcript()['claude_session']['migrated_from_nonpersistent'])
        self.review()
        self.assertIn('--resume', json.loads(self.capture.read_text())['argv'])
        self.assertEqual(self.transcript()['usage']['calls'], 3)
        self.assertAlmostEqual(self.transcript()['usage']['cli_cost_usd'], 0.36)

    def test_cumulative_cost_regression_is_unknown_not_negative_or_added_twice(self):
        self.start()
        sid = self.transcript()['claude_session']['id']
        (self.work / (sid + '.json')).write_text('{"cost": 0}')
        self.set_reply('done', cost=0.01)
        summary = json.loads(self.review().stdout)['cost_summary']
        self.assertTrue(summary['incomplete'])
        self.assertAlmostEqual(self.transcript()['usage']['cli_cost_usd'], 0.12)

    def test_repair_resumes_same_id_sends_only_instruction_and_recovery_counts_once(self):
        self.env['FAKE_BAD_FIRST'] = '1'
        self.start()
        journal = json.loads((self.session / 'claude-journal.json').read_text())
        self.assertEqual(len(journal['calls']), 2)
        self.assertEqual(len(journal['calls'][1]['messages']), 1)
        self.assertEqual(journal['calls'][1]['messages'][0]['role'], 'user')
        self.assertEqual(len(set(Path(str(self.capture) + '.calls').read_text().splitlines())), 1)
        artifact = json.loads((self.session / 'round-01-request-repair.json').read_text())
        self.assertEqual(artifact['messages'], journal['calls'][1]['messages'])
        self.simulate_uncommitted_receipt()
        self.cli('recover', '--session', str(self.session))
        self.assertEqual(self.call_count(), 2)
        self.assertEqual(self.transcript()['usage']['calls'], 2)
        self.assertAlmostEqual(self.transcript()['usage']['cli_cost_usd'], 0.24)

    def test_sigkill_after_terminal_receipt_recovers_with_no_extra_cli_call(self):
        import signal
        import time
        env = dict(self.env, FAKE_AFTER_RESULT_WAIT="1")
        process = subprocess.Popen([sys.executable, str(ROOT / "scripts/bigbrain_cli.py"),
            "start", "--task", "Verify A", "--session", str(self.session), "--no-retrospective"],
            cwd=self.work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 8
            captured = False
            while time.monotonic() < deadline:
                path = self.session / 'claude-journal.json'
                if path.exists():
                    captured = json.loads(path.read_text())['state'] == 'captured'
                    if captured:
                        break
                time.sleep(0.02)
            self.assertTrue(captured, 'terminal receipt was not persisted')
        finally:
            process.kill()
            process.wait(timeout=5)
            if self.capture.exists():
                try:
                    os.kill(json.loads(self.capture.read_text())['pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate(timeout=5)
        self.assertFalse((self.session / 'transcript.json').exists())
        self.cli('recover', '--session', str(self.session))
        self.assertEqual(self.call_count(), 1)
        self.assertEqual(self.transcript()['usage']['calls'], 1)
        self.assertAlmostEqual(self.transcript()['usage']['cli_cost_usd'], 0.12)

    def test_hook_only_injects_instructions(self):
        for event in ("SessionStart", "UserPromptSubmit"):
            result = subprocess.run([sys.executable, str(ROOT / "hooks/collaboration.py"), event],
                                    env=self.env, text=True, capture_output=True, timeout=5)
            data = json.loads(result.stdout)["hookSpecificOutput"]
            self.assertEqual(data["hookEventName"], event)
            self.assertIn("feedback --session", data["additionalContext"])
            self.assertIn("debugging trajectory from evidence", data["additionalContext"])
            self.assertIn("stuck --session", data["additionalContext"])
            self.assertIn("no automatic trajectory analysis", data["additionalContext"])
        self.assertFalse(self.capture.exists())
        result = subprocess.run([sys.executable, str(ROOT / "hooks/collaboration.py"), "Other"],
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
