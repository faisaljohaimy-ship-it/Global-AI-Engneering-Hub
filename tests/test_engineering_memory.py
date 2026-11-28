"""Private memory behavior and boundary tests; all fixtures are synthetic."""

import concurrent.futures
import copy
import hashlib
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from engineering_os.memory import MemoryError, MemoryStore
from engineering_os.orchestration import CoordinationError, _atomic_write, sha


class EngineeringMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.store = MemoryStore(self.root / 'private')
        self.source = self.root / 'source'
        self.source.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def record(self, **changes):
        value = {'project': 'demo', 'kind': 'decision', 'title': 'Use schema migrations',
                 'summary': 'Record database migrations before deployment.', 'tags': ['database'],
                 'symbols': [], 'links': [], 'provenance': {'engine': 'codex', 'source_sha256': 'a' * 64}}
        value.update(changes)
        return value

    def receipt(self, identifier, **changes):
        file = self.source / 'module.py'
        file.write_text('def recover():\n    return True\n')
        value = {'schema_version': 1, 'status': 'passed', 'solution_sha256': identifier,
                 'source_sha256': {'module.py': hashlib.sha256(file.read_bytes()).hexdigest()}}
        value.update(changes)
        path = self.root / 'private' / 'verification.json'
        _atomic_write(path, value)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_cross_engine_dedup_and_persistence(self):
        first = self.store.put(self.record())
        second = self.store.put(self.record(provenance={'engine': 'claude-code', 'source_sha256': 'b' * 64}))
        self.assertEqual(first['id'], second['id'])
        self.assertTrue(second['deduplicated'])
        self.assertEqual(self.store.put(self.record())['revision'], 2)
        reopened = MemoryStore(self.root / 'private')
        row = reopened.search('demo', 'migration')[0]
        self.assertEqual(len(row['provenances']), 2)
        self.assertEqual(row['verification_status'], 'candidate')
        self.assertEqual(os.stat(reopened.path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(reopened.directory).st_mode & 0o777, 0o700)

    def test_project_scope_and_graph(self):
        target = self.store.put(self.record())['id']
        self.store.put(self.record(kind='architecture', title='Service architecture', links=[target]))
        self.store.put(self.record(project='other'))
        self.assertEqual(len(self.store.search('demo', 'migrations')), 2)
        graph = self.store.graph('demo')
        self.assertEqual(len(graph['nodes']), 2)
        self.assertEqual(graph['edges'][0]['to'], target)
        with self.assertRaises(MemoryError):
            self.store.put(self.record(project='other', links=[target]))
        with self.assertRaises(MemoryError):
            self.store.put(self.record(links=['f' * 64]))

    def test_concept_and_symbol_retrieval_are_deterministic(self):
        self.store.put(self.record(title='Recover a failed task', summary='Repair error state', tags=[], symbols=['Task.recover']))
        row = self.store.search('demo', 'incident')[0]
        self.assertEqual(row['retrieval'], 'lexical-concept; no embeddings')
        self.assertEqual(row['score'], 1)
        self.assertGreater(self.store.search('demo', 'Task.recover')[0]['score'], row['score'])
        self.assertEqual(self.store.search('demo', 'nomatch'), [])
        self.assertEqual(self.store.search('other', 'incident'), [])

    def test_ast_index_stores_symbols_but_no_source_bodies(self):
        path = self.source / 'example.py'
        path.write_text('class Recovery:\n    def resume(self):\n        "A private body marker"\n        return 42\n\nasync def renew():\n    pass\n')
        results = self.store.index_python('demo', 'example.py', self.source, 'claude-code')
        self.assertEqual(len(results), 3)
        rows = self.store.search('demo', 'Recovery.resume')
        self.assertEqual(rows[0]['record']['symbols'], ['Recovery.resume'])
        self.assertNotIn('private body marker', self.store.path.read_text())
        self.assertNotIn('return 42', self.store.path.read_text())
        path.write_text('def broken(:')
        with self.assertRaises(SyntaxError):
            self.store.index_python('demo', 'example.py', self.source, 'codex')

    def test_symbol_batch_is_atomic_at_capacity_and_deduplicates_on_retry(self):
        source = self.source / 'module.py'
        source.write_text('def prepare():\n    pass\n\ndef finish():\n    pass\n')
        self.store.put(self.record())
        before = self.store.path.read_bytes()
        with mock.patch('engineering_os.memory.MAX_RECORDS', 2):
            with self.assertRaises(MemoryError):
                self.store.index_python('demo', 'module.py', self.source, 'codex')
        self.assertEqual(self.store.path.read_bytes(), before)

        initial = self.store.index_python('demo', 'module.py', self.source, 'codex')
        snapshot = self.store.path.read_bytes()
        self.assertEqual(len(initial), 2)
        self.assertEqual(self.store.snapshot()['revision'], 3)
        repeat = self.store.index_python('demo', 'module.py', self.source, 'codex')
        self.assertEqual([row['id'] for row in repeat], [row['id'] for row in initial])
        self.assertTrue(all(row['deduplicated'] for row in repeat))
        self.assertEqual(self.store.path.read_bytes(), snapshot)

    def test_verified_solution_source_binding_and_staleness(self):
        identifier = self.store.put(self.record(kind='solution'))['id']
        path, digest = self.receipt(identifier)
        verified = self.store.verify_solution('demo', identifier, self.source, path, digest)
        self.assertEqual(verified['verification_status'], 'source-matches-recorded-test')
        self.assertEqual(self.store.search('demo', 'migrations')[0]['verification_status'], 'evidence-recorded')
        self.assertEqual(self.store.search('demo', 'migrations', source_root=self.source)[0]['verification_status'], 'source-matches-recorded-test')
        (self.source / 'module.py').write_text('changed')
        self.assertEqual(self.store.search('demo', 'migrations', source_root=self.source)[0]['verification_status'], 'stale')
        with self.assertRaises(MemoryError):
            self.store.verify_solution('demo', identifier, self.source, path, digest)

    def test_receipts_refuse_wrong_digest_identity_failure_and_project(self):
        identifier = self.store.put(self.record(kind='solution'))['id']
        for changes in [{'status': 'failed'}, {'solution_sha256': 'f' * 64}, {'source_sha256': {}}, {'source_sha256': {'../outside': 'b' * 64}}]:
            path, digest = self.receipt(identifier, **changes)
            with self.subTest(changes=changes), self.assertRaises((ValueError, OSError)):
                self.store.verify_solution('demo', identifier, self.source, path, digest)
        path, digest = self.receipt(identifier)
        with self.assertRaises(MemoryError):
            self.store.verify_solution('demo', identifier, self.source, path, 'b' * 64)
        with self.assertRaises(MemoryError):
            self.store.verify_solution('other', identifier, self.source, path, digest)
        non_solution = self.store.put(self.record())['id']
        path, digest = self.receipt(non_solution)
        with self.assertRaises(MemoryError):
            self.store.verify_solution('demo', non_solution, self.source, path, digest)

    def test_checkpoint_restore_is_cross_session_and_empty_only(self):
        self.store.put(self.record())
        checkpoint = self.root / 'private' / 'checkpoint.json'
        receipt = self.store.checkpoint(checkpoint)
        restored = MemoryStore(self.root / 'restored')
        self.assertEqual(restored.restore(checkpoint), receipt)
        self.assertEqual(restored.snapshot(), self.store.snapshot())
        with self.assertRaises(MemoryError):
            restored.restore(checkpoint)
        with self.assertRaises(MemoryError):
            self.store.checkpoint(checkpoint)
        value = json.loads(checkpoint.read_text())
        value['state']['revision'] += 1
        _atomic_write(checkpoint, value)
        with self.assertRaises(MemoryError):
            MemoryStore(self.root / 'fresh').restore(checkpoint)

    def test_tampering_and_rehashed_invalid_schema_refused(self):
        self.store.put(self.record())
        state = self.store.snapshot()
        next(iter(state['records'].values()))['record']['summary'] = 'tampered'
        _atomic_write(self.store.path, state)
        with self.assertRaises(MemoryError):
            self.store.snapshot()
        state['sha256'] = sha({key: value for key, value in state.items() if key != 'sha256'})
        _atomic_write(self.store.path, state)
        with self.assertRaises(MemoryError):
            self.store.snapshot()

    def test_git_symlink_permissions_and_hardlinks_refused(self):
        git = self.root / 'repo'
        git.mkdir()
        (git / '.git').write_text('gitdir: ignored')
        with self.assertRaises(CoordinationError):
            MemoryStore(git / 'memory')
        link = self.root / 'linked'
        link.symlink_to(self.root / 'private', target_is_directory=True)
        with self.assertRaises(CoordinationError):
            MemoryStore(link)
        os.chmod(self.store.directory, 0o755)
        with self.assertRaises(CoordinationError):
            self.store.snapshot()
        os.chmod(self.store.directory, 0o700)
        os.link(self.store.path, self.root / 'hardlink')
        with self.assertRaises(CoordinationError):
            self.store.snapshot()

    def test_source_symlink_and_traversal_refused(self):
        outside = self.root / 'outside.py'
        outside.write_text('def noop(): pass')
        (self.source / 'link.py').symlink_to(outside)
        for path in ['../outside.py', '/absolute.py', './link.py', 'link.py', 'a//b.py', '.git/config', 'a\\b']:
            with self.subTest(path=path), self.assertRaises((MemoryError, OSError)):
                self.store.index_python('demo', path, self.source, 'codex')

    def test_index_refuses_a_source_that_changes_after_the_initial_descriptor_check(self):
        target = self.source / 'module.py'
        target.write_text('def first():\n    pass\n')
        target_stat = target.stat()
        original_fstat = os.fstat
        changed = False

        def append_after_first_stat(fd):
            nonlocal changed
            observed = original_fstat(fd)
            if observed.st_ino == target_stat.st_ino and observed.st_dev == target_stat.st_dev and not changed:
                with target.open('a', encoding='utf-8') as stream:
                    stream.write('def second():\n    pass\n')
                changed = True
            return observed

        with mock.patch('engineering_os.memory.os.fstat', side_effect=append_after_first_stat):
            with self.assertRaisesRegex(MemoryError, 'changed during the read'):
                self.store.index_python('demo', 'module.py', self.source, 'codex')
        self.assertTrue(changed)
        self.assertEqual(self.store.snapshot()['records'], {})
        self.assertEqual(len(self.store.index_python('demo', 'module.py', self.source, 'codex')), 2)

    def test_credentials_unknown_fields_bounds_and_control_text(self):
        for changes in [{'summary': 'sk-' + 'a' * 35}, {'title': 'unsafe\ntext'}, {'summary': 'postgres://worker:' + 'private-value' + '@localhost/data'}, {'summary': 'API_KEY = \"' + 'private-key-value' + '\"'}, {'project': '../escape'},
                        {'kind': 'arbitrary'}, {'tags': ['dup', 'dup']}, {'tags': ['a'] * 31},
                        {'provenance': {'engine': 'unverified', 'source_sha256': 'a' * 64}},
                        {'provenance': {'engine': 'codex', 'source_sha256': 'bad'}}, {'summary': 'x' * 4001}, {'password': 'secret'}]:
            with self.subTest(changes=changes), self.assertRaises((MemoryError, CoordinationError)):
                self.store.put(self.record(**changes))
        with self.assertRaises(MemoryError):
            self.store.search('demo', 'query', limit=True)
        with self.assertRaises(CoordinationError):
            self.store.search('demo', 'sk-' + 'b' * 35)
        source = self.source / 'bad.py'
        source.write_text('key = "sk-' + 'b' * 35 + '"')
        with self.assertRaises(MemoryError):
            self.store.index_python('demo', 'bad.py', self.source, 'codex')
        self.assertEqual(self.store.snapshot()['revision'], 0)

    def test_concurrent_writers_do_not_lose_knowledge(self):
        def put(number):
            return MemoryStore(self.root / 'private').put(self.record(title=f'Decision {number}'))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(put, range(16)))
        self.assertEqual(len({value['id'] for value in values}), 16)
        self.assertEqual(self.store.snapshot()['revision'], 16)
        self.assertEqual(len(self.store.graph('demo')['nodes']), 16)


if __name__ == '__main__':
    unittest.main()
