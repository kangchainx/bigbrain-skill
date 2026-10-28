"""Reasoning control and user-facing advisor cost regression tests (no paid API)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from bigbrain import client, config, report, session


class EffortCostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.session = self.work / 'session'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('BIGBRAIN_', 'ANTHROPIC_'))}
        self.env.update(HOME=str(self.work), BIGBRAIN_HOME=str(self.work / 'home'),
                        BIGBRAIN_BASE_URL='http://127.0.0.1:1', BIGBRAIN_API_KEY='fake-key',
                        BIGBRAIN_MODEL='test', BIGBRAIN_RETRIES='0',
                        PYTHONDONTWRITEBYTECODE='1')
        self.mock = self.work / 'mock.json'
        self.evidence = self.work / 'evidence.txt'
        self.evidence.write_text('A passed')

    def cli(self, *args, code=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/bigbrain_cli.py'),
                                 *args], cwd=self.work, env=self.env, text=True,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, code, result.stderr)
        return result

    def replies(self, values):
        self.mock.write_text(json.dumps(values))

    def start(self, *args, code=0):
        return self.cli('start', '--task', 'test', '--session', str(self.session),
                        '--mock', str(self.mock), *args, code=code)

    @staticmethod
    def reply(status='continue', usage=None):
        return {'text': json.dumps({'status': status, 'summary': 'test',
                                   'acceptance_criteria': ['A'],
                                   'criteria_status': [{'criterion': 'A', 'met': True,
                                                        'evidence': 'passed'}]}),
                'usage': usage or {'input_tokens': 100, 'output_tokens': 20}}

    def test_default_and_allowed_efforts_on_payload(self):
        for effort in (None, 'medium', 'high', 'xhigh'):
            cfg = {} if effort is None else {'effort': effort}
            payload = client.build_payload(cfg, 'system', [])
            self.assertEqual(payload['output_config']['effort'], effort or 'medium')
            self.assertEqual(payload['thinking'], {'type': 'adaptive'})
        for effort in ('low', 'max', 'ultra', ''):
            with self.assertRaises(config.BigbrainError):
                client.build_payload({'effort': effort}, 'system', [])

    def test_dry_run_defaults_medium_and_does_not_write(self):
        self.replies([self.reply()])
        result = self.start('--dry-run')
        self.assertEqual(json.loads(result.stdout)['request']['output_config']['effort'], 'medium')
        self.assertFalse(self.session.exists())

    def test_session_effort_persists_and_can_change(self):
        self.replies([self.reply(), self.reply(), self.reply()])
        self.start('--effort', 'high')
        for effort, args in [('high', []), ('xhigh', ['--effort', 'xhigh'])]:
            result = self.cli('report', '--session', str(self.session), '--result-file',
                              str(self.evidence), '--mock', str(self.mock), *args)
            self.assertEqual(json.loads(result.stdout)['status'], 'continue')
            transcript = json.loads((self.session / 'transcript.json').read_text())
            self.assertEqual(transcript['effort'], effort)
            n = len(transcript['rounds'])
            request = json.loads((self.session / ('round-%02d-request.json' % n)).read_text())
            self.assertEqual(request['output_config']['effort'], effort)
            self.assertEqual(request['_meta']['effort'], effort)
        result = self.cli('stuck', '--session', str(self.session), '--reason', 'hard', '--dry-run')
        self.assertEqual(json.loads(result.stdout)['request']['output_config']['effort'], 'xhigh')

    def test_cli_rejects_max_before_request(self):
        self.start('--effort', 'max', code=2)
        self.assertFalse(self.session.exists())

    def test_terminal_summary_counts_repair_and_retrospective(self):
        self.replies([{'text': 'invalid', 'usage': {'input_tokens': 100, 'output_tokens': 20}},
                      self.reply('done'), self.reply('done')])
        result = self.start('--effort', 'xhigh', '--quiet')
        data = json.loads(result.stdout)
        summary = data['cost_summary']
        self.assertEqual(summary['calls'], 3)
        self.assertEqual(summary['input_tokens'], 300)
        self.assertEqual(summary['output_tokens'], 60)
        self.assertEqual(summary['total_tokens'], 360)
        self.assertIn('300 input (including cache), 60 output, 360 total', result.stderr)
        self.assertAlmostEqual(summary['advisor_usd'], .009)
        self.assertTrue(summary['estimated'])
        self.assertTrue(summary['mock'])
        self.assertIn('Claude advisor API cost:', result.stderr)
        self.assertNotIn('# bigbrain report', result.stderr)
        for filename in ('round-01-request.json', 'round-01-request-repair.json',
                         'retrospective-request.json'):
            request = json.loads((self.session / filename).read_text())
            self.assertEqual(request['output_config']['effort'], 'xhigh')

    def test_missing_usage_is_not_claimed_free(self):
        self.replies([self.reply('done', {'present': False, 'input_tokens': 0,
                                        'output_tokens': 0})])
        result = self.start('--no-retrospective')
        summary = json.loads(result.stdout)['cost_summary']
        self.assertTrue(summary['incomplete'])
        self.assertIn('total cost unknown', summary['message'])
        self.assertIn('total tokens unknown', summary['message'])

    def test_bad_json_preserves_spend_and_exit_code(self):
        self.replies([{'text': 'invalid', 'usage': {'input_tokens': 100, 'output_tokens': 20}}] * 2)
        result = self.start(code=12)
        self.assertIn('Claude advisor API cost:', result.stderr)
        payload = json.loads((self.session / 'report.json').read_text())
        self.assertEqual(payload['tokens']['calls'], 2)
        self.assertAlmostEqual(payload['cost']['advisor_usd'], .006)
        result = self.cli('finish', '--session', str(self.session), '--no-retrospective', '--json')
        self.assertEqual(json.loads(result.stdout)['cost_summary']['calls'], 2)

    def test_transport_failure_reports_unknown_total(self):
        result = self.cli('start', '--task', 'test', '--session', str(self.session), code=3)
        self.assertIn('total cost unknown', result.stderr)
        payload = json.loads((self.session / 'report.json').read_text())
        self.assertTrue(payload['cost_incomplete'])
        self.assertFalse(payload['mock'])

    def test_blocked_and_round_limit_emit_cost(self):
        self.replies([self.reply('blocked')])
        result = self.start('--no-retrospective', code=10)
        self.assertEqual(json.loads(result.stdout)['cost_summary']['calls'], 1)
        self.env['BIGBRAIN_MAX_ROUNDS'] = '1'
        self.replies([self.reply()])
        result = self.start('--force', '--no-retrospective', code=11)
        self.assertEqual(json.loads(result.stdout)['cost_summary']['calls'], 1)

    def test_cache_prices_and_advisor_only_summary(self):
        cfg = {'prices': {'advisor_in': 10, 'advisor_out': 50}}
        transcript = session.new_transcript('test', cfg)
        session.record_executor_work(transcript, text='implementation and test output' * 100)
        transcript['usage'] = {'input_tokens': 1000, 'output_tokens': 100, 'calls': 1,
                               'cache_creation_input_tokens': 200, 'cache_read_input_tokens': 300}
        payload = report.build_report(transcript, cfg)
        self.assertAlmostEqual(report.cost_summary(payload)['advisor_usd'], .0128)
        self.assertEqual(report.cost_summary(payload)['input_tokens'], 1000)
        self.assertEqual(report.cost_summary(payload)['output_tokens'], 100)
        self.assertEqual(report.cost_summary(payload)['total_tokens'], 1100)
        self.assertNotEqual(payload['cost']['actual_usd'], report.cost_summary(payload)['advisor_usd'])


if __name__ == '__main__':
    unittest.main()
