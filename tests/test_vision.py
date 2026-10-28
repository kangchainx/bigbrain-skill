"""Multimodal transport regression tests; no paid provider requests."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from bigbrain import client, config, io, loop

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC')


class VisionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.image = self.work / 'frame-22s.png'
        self.image.write_bytes(PNG)
        self.session = self.work / 'session'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('BIGBRAIN_', 'ANTHROPIC_'))}
        self.env.update(HOME=str(self.work), BIGBRAIN_HOME=str(self.work / 'home'),
                        BIGBRAIN_BASE_URL='http://127.0.0.1:1', BIGBRAIN_API_KEY='test',
                        BIGBRAIN_MODEL='test', BIGBRAIN_RETRIES='0', BIGBRAIN_COMPRESS='1',
                        PYTHONDONTWRITEBYTECODE='1')
        self.mock = self.work / 'mock.json'
        reply = {'status': 'continue', 'summary': 'test', 'acceptance_criteria': ['visual'],
                 'criteria_status': [{'criterion': 'visual', 'met': False, 'evidence': 'pending'}]}
        self.mock.write_text(json.dumps([reply] * 5))
        self.evidence = self.work / 'report.txt'
        self.evidence.write_text('Compare reference and output at 22 seconds.')

    def cli(self, *args, code=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/bigbrain_cli.py'), *args],
                                cwd=self.work, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, code, result.stderr)
        return result

    def start(self, *args, code=0):
        return self.cli('start', '--task', 'Review animation', '--user-request',
                        '--session', str(self.session), '--mock', str(self.mock), *args, code=code)

    @staticmethod
    def images(payload):
        return [b for m in payload['messages'] if isinstance(m['content'], list)
                for b in m['content'] if b['type'] == 'image']

    def test_dry_run_sends_real_bytes_and_does_not_write(self):
        result = self.start('--image-file', str(self.image), '--dry-run')
        request = json.loads(result.stdout)['request']
        source = self.images(request)[0]['source']
        self.assertEqual(source['media_type'], 'image/png')
        self.assertEqual(base64.b64decode(source['data']), PNG)
        self.assertFalse(self.session.exists())

    def test_report_and_stuck_keep_images_after_compression(self):
        self.start('--image-file', str(self.image))
        for _ in range(2):
            self.cli('report', '--session', str(self.session), '--result-file', str(self.evidence),
                     '--image-file', str(self.image), '--mock', str(self.mock))
        request = json.loads((self.session / 'round-03-request.json').read_text())
        self.assertEqual(request['_meta']['image_count'], 2)  # initial + current
        for block in self.images(request):
            self.assertEqual(base64.b64decode(block['source']['data']), PNG)
        self.assertIn('Earlier intermediate images are omitted', request['messages'][-1]['content'][-1]['text'])
        result = self.cli('stuck', '--session', str(self.session), '--reason', 'visual defect',
                          '--image-file', str(self.image), '--dry-run')
        self.assertEqual(len(self.images(json.loads(result.stdout)['request'])), 2)

    def test_repair_preserves_images(self):
        replies = json.loads(self.mock.read_text())
        self.mock.write_text(json.dumps([{'text': 'bad json'}, replies[0]]))
        self.start('--image-file', str(self.image))
        request = json.loads((self.session / 'round-01-request-repair.json').read_text())
        self.assertEqual(base64.b64decode(self.images(request)[0]['source']['data']), PNG)

    def test_invalid_missing_and_oversized_images_fail_before_request(self):
        bad = self.work / 'bad.mp4'
        bad.write_bytes(b'not an image')
        huge = self.work / 'huge.png'
        huge.write_bytes(PNG + b'0' * 3_750_000)
        for path in (bad, self.work / 'missing.png', huge):
            result = self.start('--image-file', str(path), '--dry-run', code=2)
            self.assertNotIn('Traceback', result.stderr)
        self.assertFalse(self.session.exists())

    def test_context_image_is_rejected_not_decoded_as_text(self):
        result = self.start('--context-file', str(self.image), '--dry-run', code=2)
        self.assertIn('requires --image-file', result.stderr)

    def test_text_only_compatibility_and_missing_context_note(self):
        self.assertEqual(io.attach_images('hello', []), 'hello')
        text, notes = io.read_context_files([self.work / 'missing.txt'])
        self.assertEqual(text, '')
        self.assertEqual(len(notes), 1)
        result = self.start('--dry-run')
        self.assertEqual(self.images(json.loads(result.stdout)['request']), [])

    def test_compression_never_truncates_image_or_label(self):
        initial = io.attach_images('original', [self.image])
        history = [{'role': 'user', 'content': initial}, {'role': 'assistant', 'content': '{}'}] * 2
        current = io.attach_images('x' * 50000, [self.image])
        out = loop.compress_messages(history, current)
        self.assertEqual(out[0]['content'], initial)
        self.assertEqual(out[-1]['content'][:-1], current[:-1])
        self.assertLess(len(out[-1]['content'][-1]['text']), 15000)
        self.assertNotIn(current[1]['source']['data'], out[-1]['content'][-1]['text'])

    def test_large_image_history_fails_instead_of_silently_dropping_pixels(self):
        block = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'A' * 5_000_000}}
        with self.assertRaises(config.BigbrainError):
            client.build_payload({}, 'system', [{'role': 'user', 'content': [block] * 7}])


if __name__ == '__main__':
    unittest.main()
