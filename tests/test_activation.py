"""Chat opt-in and silent hooks; never contacts an advisor."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('BIGBRAIN_')}
        self.env.update(HOME=str(self.root), BIGBRAIN_HOME=str(self.root / 'state'),
                        CODEX_THREAD_ID='chat-a', BIGBRAIN_BACKEND='claude-code')

    def cli(self, *args, env=None, code=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/bigbrain_cli.py'), *args],
            env=env or self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, code, result.stderr)
        return result

    def hook(self, event='UserPromptSubmit', payload=None, env=None):
        result = subprocess.run([sys.executable, str(ROOT / 'hooks/collaboration.py'), event],
            input=json.dumps(payload or {}), env=env or self.env,
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_new_chat_default_off_and_hook_silent_without_writes(self):
        self.assertFalse(json.loads(self.cli('mode', 'status').stdout)['enabled'])
        self.assertEqual(self.hook(), '')
        self.assertFalse((self.root / 'state').exists())

    def test_same_chat_resume_preserves_opt_in_but_new_chat_does_not(self):
        self.cli('mode', 'on')
        for event in ('SessionStart', 'UserPromptSubmit'):
            self.assertIn('explicitly enabled', self.hook(event, {'session_id': 'chat-a', 'source': 'resume'}))
        other = dict(self.env, CODEX_THREAD_ID='chat-b')
        self.assertEqual(self.hook(env=other), '')
        self.assertFalse(json.loads(self.cli('mode', 'status', env=other).stdout)['enabled'])
        self.assertTrue(json.loads(self.cli('mode', 'status').stdout)['enabled'])

    def test_off_silences_both_hooks_and_retains_other_chat(self):
        self.cli('mode', 'on')
        other = dict(self.env, CODEX_THREAD_ID='chat-b')
        self.cli('mode', 'on', env=other)
        self.cli('mode', 'off')
        self.assertEqual(self.hook('SessionStart'), '')
        self.assertEqual(self.hook(), '')
        self.assertIn('explicitly enabled', self.hook(env=other))

    def test_prompt_mentions_and_negations_never_enable(self):
        for prompt in ('use bigbrain', '本次启用 Bigbrain', '不要启用 bigbrain', '修复 bigbrain hook'):
            self.assertEqual(self.hook(payload={'session_id': 'chat-a', 'prompt': prompt}), '')
        self.assertFalse((self.root / 'state').exists())

    def test_missing_or_conflicting_identity_fails_closed(self):
        self.cli('mode', 'on')
        self.assertEqual(self.hook(payload={'session_id': 'chat-b'}), '')
        self.cli('mode', 'on', '--chat-id', 'chat-b', code=2)
        env = dict(self.env)
        env.pop('CODEX_THREAD_ID')
        self.assertEqual(self.hook(env=env), '')
        self.cli('mode', 'on', env=env, code=2)
        self.assertIn('explicitly enabled', self.hook(payload={'session_id': 'chat-a'}, env=env))

    def test_corrupt_state_is_off_and_live_workflow_rejected_before_creation(self):
        self.cli('mode', 'on')
        state = next((self.root / 'state/chat-activation').glob('*.json'))
        state.write_text('{broken')
        self.assertEqual(self.hook(), '')
        task = self.root / 'task'
        result = self.cli('start', '--task', 'test', '--session', str(task), code=2)
        self.assertIn('off for this chat', result.stderr)
        self.assertFalse(task.exists())

    def test_both_skill_entries_disable_implicit_invocation(self):
        for path in ('agents/openai.yaml', 'skills/bigbrain/agents/openai.yaml'):
            self.assertIn('allow_implicit_invocation: false', (ROOT / path).read_text())


if __name__ == '__main__':
    unittest.main()
