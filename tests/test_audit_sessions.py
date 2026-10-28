"""Offline audit accounting and read-only guarantees."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/audit_sessions.py'


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, name='valid', **changes):
        data = {'backend': 'claude-code', 'status': 'done', 'rounds': [],
                'usage': {'cli_cost_usd': 0.4321, 'input_tokens': 1000,
                          'output_tokens': 100, 'calls': 4,
                          'cache_creation_input_tokens': 200, 'cache_read_input_tokens': 700,
                          'by_kind': {'round': {'calls': 3}, 'retrospective': {'calls': 1}}},
                'user_feedback': [{'text': 'PRIVATE-FEEDBACK-SENTINEL'}],
                'criteria_status': [{'met': True}, {'met': True}, {'met': False}]}
        data.update(changes)
        path = self.root / name
        path.mkdir(exist_ok=True)
        (path / 'transcript.json').write_text(json.dumps(data))
        return path

    def run_audit(self, *paths):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BIGBRAIN_')}
        env['HOME'] = str(self.root)
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, paths)],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout), result.stdout

    def test_dedup_same_session_via_dir_trailing_slash_symlink_and_root_counts_once(self):
        path = self.fixture()
        alias = self.root / 'alias'
        alias.symlink_to(path, target_is_directory=True)
        data, _ = self.run_audit(path, str(path) + '/', alias, self.root)
        self.assertEqual([r['path'] for r in data['sessions']], [str(path.resolve())])
        self.assertEqual(data['totals']['sessions'], 1)

    def test_mock_session_excluded_with_reason_mock_and_not_in_totals(self):
        self.fixture(mock=True)
        self.fixture('round-mock', rounds=[{'meta': {'mode': 'mock'}}])
        data, _ = self.run_audit(self.root)
        self.assertEqual(data['totals']['sessions'], 0)
        self.assertEqual([r['reason'] for r in data['excluded']], ['mock', 'mock'])

    def test_cli_cost_missing_flag_reports_null_not_zero(self):
        path = self.fixture(cost_incomplete=True)
        data, _ = self.run_audit(path)
        self.assertIsNone(data['sessions'][0]['cli_cost_usd'])
        self.assertIsNone(data['totals']['cli_cost_usd'])
        self.assertEqual(data['totals']['cli_cost_usd_recorded'], 0.4321)
        self.assertIsNone(data['totals']['input_tokens'])
        for usage in ({'cli_cost_missing': True}, {}):
            data, _ = self.run_audit(self.fixture(usage=usage))
            self.assertIsNone(data['totals']['cli_cost_usd'])

    def test_negative_or_nan_cost_reports_cli_cost_invalid(self):
        for cost in (-1, float('nan'), float('inf'), True, '0.1'):
            data, _ = self.run_audit(self.fixture(usage={'cli_cost_usd': cost}))
            self.assertIn('cli_cost_invalid', data['sessions'][0]['issues'])
            self.assertIsNone(data['sessions'][0]['cli_cost_usd'])

    def test_missing_usage_reports_null_and_issue(self):
        data, _ = self.run_audit(self.fixture(usage=None))
        self.assertIn('usage_missing', data['sessions'][0]['issues'])
        self.assertIsNone(data['totals']['input_tokens'])
        self.assertIsNone(data['totals']['cli_cost_usd'])

    def test_invalid_json_transcript_flagged_without_crash(self):
        path = self.fixture()
        (path / 'transcript.json').write_text('{broken')
        data, _ = self.run_audit(path)
        self.assertIn('transcript_invalid_json', data['sessions'][0]['issues'])
        self.assertIsNone(data['totals']['cli_cost_usd'])

    def test_valid_claude_code_session_exact_values(self):
        valid = self.fixture()
        unknown = self.fixture('unknown', usage={})
        data, raw = self.run_audit(valid, unknown)
        row = next(r for r in data['sessions'] if r['path'] == str(valid.resolve()))
        self.assertEqual([row[k] for k in ('input_tokens', 'output_tokens', 'calls',
                         'cache_creation_input_tokens', 'cache_read_input_tokens')],
                         [1000, 100, 4, 200, 700])
        self.assertEqual(row['calls_by_kind'], {'round': 3, 'retrospective': 1})
        self.assertEqual(row['criteria'], {'reported': 3, 'met': 2})
        self.assertEqual(row['feedback_count'], 1)
        self.assertEqual(row['issues'], [])
        self.assertEqual(data['totals']['cli_cost_usd_recorded'], 0.4321)
        self.assertEqual(data['totals']['cost_unknown_sessions'], 1)
        self.assertNotIn('PRIVATE-FEEDBACK-SENTINEL', raw)

    def test_output_byte_identical_across_runs(self):
        path = self.fixture()
        self.assertEqual(self.run_audit(path)[1], self.run_audit(path)[1])

    def test_pending_native_receipt_is_unknown_until_atomic_commit_marker(self):
        path = self.fixture()
        journal = path / 'claude-journal.json'
        journal.write_text(json.dumps({'id': 'operation-1', 'state': 'captured'}))
        data, _ = self.run_audit(path)
        self.assertIsNone(data['totals']['cli_cost_usd'])
        self.assertIn('native_operation_unsettled', data['sessions'][0]['issues'])
        transcript = json.loads((path / 'transcript.json').read_text())
        transcript['native_applied_operation'] = 'operation-1'
        (path / 'transcript.json').write_text(json.dumps(transcript))
        data, _ = self.run_audit(path)
        self.assertEqual(data['totals']['cli_cost_usd'], 0.4321)

    def test_no_args_exit_2(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_first_turn_without_transcript_is_counted_as_unknown(self):
        self.fixture()
        pending = self.root / 'interrupted'
        pending.mkdir()
        (pending / 'claude-session.json').write_text('{"id":"native-id"}')
        (pending / 'claude-journal.json').write_text('{"state":"captured"}')
        data, _ = self.run_audit(self.root, pending)
        self.assertEqual(data['totals']['sessions'], 2)
        self.assertEqual(data['totals']['cost_unknown_sessions'], 1)
        self.assertIsNone(data['totals']['cli_cost_usd'])
        self.assertIsNone(data['totals']['input_tokens'])
        self.assertEqual(data['totals']['cli_cost_usd_recorded'], 0.4321)
        row = next(r for r in data['sessions'] if r['path'] == str(pending.resolve()))
        self.assertIn('native_operation_unsettled', row['issues'])

    def test_read_only_and_no_network(self):
        path = self.fixture() / 'transcript.json'
        def snapshot():
            return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns
        before = snapshot()
        self.run_audit(path.parent)
        self.assertEqual(snapshot(), before)
        imports = set()
        for node in ast.walk(ast.parse(SCRIPT.read_text())):
            if isinstance(node, ast.Import):
                imports.update(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertLessEqual(imports, {'argparse', 'json', 'math', 'pathlib', 'sys'})

    def test_api_cost_unknown_and_missing_path_not_silently_zero(self):
        data, _ = self.run_audit(self.fixture(backend='api'), self.root / 'missing')
        self.assertIn('cli_cost_not_applicable_api_backend', data['sessions'][0]['issues'])
        self.assertIsNone(data['totals']['cli_cost_usd'])
        data, _ = self.run_audit(self.root / 'missing')
        self.assertIsNone(data['totals']['cli_cost_usd'])


if __name__ == '__main__':
    unittest.main()
