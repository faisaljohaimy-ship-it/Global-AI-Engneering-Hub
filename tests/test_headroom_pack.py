"""Real selective registration and separate-process invocation of the optional pack.

Only unmerged main ancestry is mocked, as in the existing SDK pack tests. Files,
integrity checks and subprocesses are real; the native agent/model host is not.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import hublink

ROOT = Path(__file__).resolve().parents[1]
VENDOR = '.engineering/headroom'


class HeadroomPackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.revision = hublink.head()
        ancestry = mock.patch('hublink.on_main', return_value=True)
        ancestry.start()
        self.addCleanup(ancestry.stop)

    def register(self, *caps, **options):
        return hublink.register(self.project, self.revision, capabilities=caps, **options)

    def command(self, python, *args):
        command = [python, str(self.project / VENDOR / 'headroom_context.py'), *args]
        result = subprocess.run(command, cwd=self.project, capture_output=True,
                                text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return json.loads(result.stdout)

    def test_selective_registration_preserves_project_files_and_both_agent_skills(self):
        for name in ('AGENTS.md', 'CLAUDE.md'):
            (self.project / name).write_text('Owner project instructions\n')
        self.assertFalse(self.register('pack:headroom-context')['applied'])
        self.assertFalse((self.project / '.engineering').exists())
        self.register('pack:headroom-context', apply=True)
        manifest = hublink.load_manifest(self.project)
        self.assertEqual([c['id'] for c in manifest['capabilities']], ['pack:headroom-context'])
        self.assertFalse(manifest['production_runtime_dependency'])
        self.assertEqual(manifest['budget_additional_sar'], 0)
        self.assertEqual(manifest['hub_revision'], self.revision)
        self.assertEqual(len(manifest['capabilities'][0]['files']), 7)
        skill = '.agents/skills/headroom-context-engineering/SKILL.md'
        self.assertEqual((self.project / skill).read_bytes(),
                         (self.project / skill.replace('.agents', '.claude')).read_bytes())
        for name in ('AGENTS.md', 'CLAUDE.md'):
            self.assertEqual((self.project / name).read_text(), 'Owner project instructions\n')
        self.assertTrue(hublink.verify(self.project, strict=True)['ok'])
        self.assertFalse(any(p.name in ('node_modules', 'site-packages', 'venv')
                             for p in self.project.rglob('*')))
        self.assertFalse(self.command(sys.executable, 'status')['runtime_verified'])

    def test_conflict_fails_before_mutation_and_offline_sdk_detects_tampered_worker(self):
        worker = self.project / VENDOR / 'headroom_worker.py'
        worker.parent.mkdir(parents=True)
        worker.write_text('Project-owned worker\n')
        with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
            self.register('pack:headroom-context', apply=True)
        self.assertEqual(worker.read_text(), 'Project-owned worker\n')
        self.assertFalse((self.project / hublink.MANIFEST).exists())
        worker.unlink()
        self.register('pack:engineering-sdk', 'pack:headroom-context', apply=True)
        verify = [sys.executable, str(self.project / '.engineering/sdk/engineering_sdk.py'),
                  'verify', '--project', str(self.project)]
        good = subprocess.run(verify, capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual(json.loads(good.stdout)['network_requests'], 0)
        worker.write_text(worker.read_text() + '\n# unreviewed change\n')
        bad = subprocess.run(verify, capture_output=True, text=True, timeout=10)
        self.assertEqual(bad.returncode, 1)
        self.assertFalse(hublink.verify(self.project, strict=True)['ok'])

    def test_hash_locked_closure_has_no_unpinned_requirement_or_extra(self):
        lines = (ROOT / 'integrations/headroom/requirements.lock').read_text().splitlines()
        requirements = [line for line in lines if line and not line.startswith('#')]
        self.assertEqual(len(requirements), 68)
        for line in requirements:
            self.assertRegex(line, r'^[a-zA-Z0-9_.-]+==[a-zA-Z0-9_.+-]+ --hash=sha256:[a-f0-9]{64}$')
        self.assertTrue(any(line.startswith('headroom-ai==0.45.0 ') for line in requirements))
        self.assertEqual(hashlib.sha256((ROOT / 'integrations/headroom/requirements.lock').read_bytes()).hexdigest(),
                         '2bfb5f5ddfb54dc16d98b8d647c7dbf7821b0e14b345f1811e430418d2f29bbb')

    @unittest.skipUnless(os.environ.get('HEADROOM_CONTEXT_INTEGRATION') == '1',
                         'Explicit reviewed optional SDK environment required')
    def test_actual_vendored_optimization_then_fresh_stdlib_full_retrieval(self):
        self.register('pack:headroom-context', apply=True)
        payload = self.root / 'public-catalog.json'
        payload.write_bytes((ROOT / 'catalog/registry.json').read_bytes())
        store = self.root / 'private-context'
        result = self.command(sys.executable, 'optimize', '--input', str(payload),
                              '--store', str(store), '--kind', 'tool-json')
        self.assertEqual(result['status'], 'optimized', result['reason'])
        self.assertTrue(result['lossless'])
        self.assertTrue(result['ccr_roundtrip'])
        self.assertTrue(result['protected_messages_unchanged'])
        self.assertEqual(result['network_boundary'], 'linux-seccomp-no-ip')
        self.assertLess(result['output_bytes'], result['input_bytes'])
        self.assertIsNone(result['billing'])
        self.assertFalse(result['native_agent_interception'])
        # A fresh base interpreter needs no optional SDK or hub source to recover.
        base_python = getattr(sys, '_base_executable', sys.executable)
        recovered = self.command(base_python, 'retrieve', '--store', str(store),
                                 '--id', result['id'], '--full')
        self.assertTrue(recovered['source_hash_verified'])
        self.assertTrue(recovered['complete'])
        self.assertEqual(recovered['content'].encode('utf-8'), payload.read_bytes())


if __name__ == '__main__':
    unittest.main()
