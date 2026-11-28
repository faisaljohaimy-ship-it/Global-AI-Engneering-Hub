"""Behavioral checks for the actual generated application and publication."""

import concurrent.futures
import copy
import hashlib
import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from engineering_os.factory import FactoryError
from engineering_os.factory_generate import _call, _server, generate_system
from engineering_os.orchestration import sha


def projection():
    return {
        'schema_version': 1,
        'project': 'synthetic-app',
        'source_revision': 'a' * 40,
        'resources': [
            {'name': 'tasks', 'fields': [
                {'name': 'title', 'type': 'text', 'required': True},
                {'name': 'done', 'type': 'boolean', 'required': False},
                {'name': 'priority', 'type': 'integer', 'required': True},
            ]},
            {'name': 'notes', 'fields': [
                {'name': 'body', 'type': 'text', 'required': False},
            ]},
        ],
    }


class FactoryGenerationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='gaie-factory-')
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)

    def test_generate_verifies_every_resource_and_publishes_only_source_artifacts(self):
        output = self.root / 'app'
        manifest = generate_system(projection(), destination=output)
        self.assertEqual(manifest['verification']['status'], 'passed')
        self.assertEqual(manifest['verification']['resources'], ['notes', 'tasks'])
        self.assertEqual(manifest['verification']['starts'], 3)
        self.assertIn('restart-persistence', manifest['verification']['checks'])
        self.assertFalse(manifest['deployment_authorized'])
        self.assertEqual(json.loads((output / 'manifest.json').read_bytes()), manifest)
        self.assertEqual(manifest['manifest_sha256'], sha({
            key: value for key, value in manifest.items() if key != 'manifest_sha256'
        }))
        self.assertEqual(set(child.name for child in output.iterdir()),
                         {'README.md', 'app.py', 'manifest.json', 'openapi.json', 'plan.json',
                          'requirements.json', 'schema.sql'})
        for name, digest in manifest['files_sha256'].items():
            artifact = output / name
            self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), digest)
            self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        plan = json.loads((output / 'plan.json').read_text())
        self.assertEqual({row['id'] for row in plan['request']['requirements']}, {'notes', 'tasks'})
        api = json.loads((output / 'openapi.json').read_text())
        self.assertIn('/v1/tasks/{id}', api['paths'])
        self.assertIn('delete', api['paths']['/v1/tasks/{id}'])

    def test_standalone_published_software_stores_validated_sqlite_values(self):
        output = self.root / 'app'
        generate_system(projection(), destination=output, verify=False)
        notes = '/v1/notes'
        tasks = '/v1/tasks'
        with _server(output, 'synthetic-app') as endpoint:
            values = {'title': 'A "quoted" title', 'priority': 7, 'done': False}
            self.assertEqual(_call(endpoint, 'POST', tasks, 201, values), {'id': 1, **values})
            _call(endpoint, 'POST', tasks, 400, {**values, 'priority': False})
            _call(endpoint, 'POST', tasks, 400, {**values, 'done': 0})
            _call(endpoint, 'POST', tasks, 400, {'title': 'missing required priority'})
            self.assertEqual(_call(endpoint, 'POST', notes, 201, {}), {'id': 1, 'body': None})
        with sqlite3.connect(output / 'run/data.sqlite3') as db:
            self.assertEqual(db.execute('SELECT title,priority,done FROM tasks').fetchall(),
                             [('A "quoted" title', 7, 0)])
            self.assertEqual(db.execute('SELECT body FROM notes').fetchall(), [(None,)])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
        with _server(output, 'synthetic-app') as endpoint:
            self.assertEqual(_call(endpoint, 'GET', tasks + '/1', 200), {'id': 1, **values})

    def test_same_projection_order_is_deterministic_and_no_verify_remains_unverified(self):
        request = projection()
        reordered = copy.deepcopy(request)
        reordered['resources'].reverse()
        reordered['resources'][1]['fields'].reverse()
        first = generate_system(request, destination=self.root / 'one', verify=False)
        second = generate_system(reordered, destination=self.root / 'two', verify=False)
        self.assertEqual(first, second)
        self.assertEqual(first['verification'], {'status': 'unverified'})

    def test_tampered_runtime_inputs_and_cross_project_database_are_rejected(self):
        original = self.root / 'first'
        generate_system(projection(), destination=original, verify=False)
        with _server(original, 'synthetic-app') as endpoint:
            _call(endpoint, 'POST', '/v1/notes', 201, {'body': 'independent'})
        other = self.root / 'second'
        generate_system({**projection(), 'project': 'other-app'}, destination=other, verify=False)
        command = [sys.executable, '-I', '-B', str(other / 'app.py'), '--state-dir',
                   str(original / 'run')]
        cross_project = subprocess.run(command, capture_output=True, text=True, timeout=3)
        self.assertNotEqual(cross_project.returncode, 0)
        self.assertIn('different project or schema', cross_project.stderr)
        (other / 'schema.sql').write_text('SELECT 1;')
        modified_source = subprocess.run(command, capture_output=True, text=True, timeout=3)
        self.assertNotEqual(modified_source.returncode, 0)
        self.assertIn('changed generated configuration', modified_source.stderr)
        with _server(original, 'synthetic-app') as endpoint:
            self.assertEqual(_call(endpoint, 'GET', '/v1/notes/1', 200)['body'], 'independent')

    def test_malformed_schema_and_unsafe_publication_do_not_create_output(self):
        output = self.root / 'output'
        for bad in ('bad/name', 'sqlite_master', 'Tasks', 'a";drop', 'health'):
            request = projection()
            request['resources'][0]['name'] = bad
            with self.subTest(bad=bad), self.assertRaises(FactoryError):
                generate_system(request, destination=output, verify=False)
            self.assertFalse(output.exists())
        existing = self.root / 'existing'
        existing.mkdir()
        marker = existing / 'keep'
        marker.write_text('keep')
        with self.assertRaises(FactoryError):
            generate_system(projection(), destination=existing, verify=False)
        self.assertEqual(marker.read_text(), 'keep')
        link = self.root / 'link'
        link.symlink_to(existing, target_is_directory=True)
        with self.assertRaises(ValueError):
            generate_system(projection(), destination=link / 'output', verify=False)
        public = self.root / 'public'
        public.mkdir()
        public.chmod(0o755)
        with self.assertRaises(ValueError):
            generate_system(projection(), destination=public / 'output', verify=False)
        git = self.root / 'checkout'
        git.mkdir(mode=0o700)
        (git / '.git').write_text('gitdir: /nonexistent\n')
        with self.assertRaises(ValueError):
            generate_system(projection(), destination=git / 'output', verify=False)

    def test_failed_verification_never_publishes_and_competing_creators_preserve_output(self):
        output = self.root / 'app'
        with patch('engineering_os.factory_generate._verify', side_effect=FactoryError('fixture failure')):
            with self.assertRaises(FactoryError):
                generate_system(projection(), destination=output)
        self.assertFalse(output.exists())

        def publish():
            try:
                return generate_system(projection(), destination=output, verify=False)
            except (FactoryError, FileExistsError):
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            one, two = list(pool.map(lambda _: publish(), range(2)))
        self.assertEqual(sum(value is not None for value in (one, two)), 1)
        self.assertEqual(json.loads((output / 'manifest.json').read_bytes()), one or two)


if __name__ == '__main__':
    unittest.main()
