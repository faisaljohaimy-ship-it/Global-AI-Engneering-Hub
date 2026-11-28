"""Shared local entry-point acceptance scenarios; all data is synthetic."""
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from engineering_os.intelligence import dispatch, main, read_request


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def request(self):
        now = time.time()
        return {'schema_version': 1, 'project': 'synthetic', 'task': 'feature',
                'source_sha256': 'a' * 64,
                'nodes': [{'id': 'design', 'parent': None, 'depends_on': [],
                           'minutes': 2, 'risk': .1, 'novelty': .1, 'confidence': .9}],
                'constraints': {'max_minutes': 10, 'max_parallel': 1, 'max_depth': 5,
                                'max_cost_units': 1, 'max_latency_ms': 100,
                                'min_quality': .8, 'required_checks': ['tests']},
                'alternatives': [{'id': 'reuse', 'cost_units': 0, 'latency_ms': 1,
                                  'quality': .9, 'evidence_ids': ['reference']}],
                'evidence': [{'id': 'reference', 'project': 'synthetic',
                              'source_sha256': 'a' * 64, 'at': now, 'kind': 'test',
                              'sha256': 'b' * 64, 'confidence': .9}]}

    def record(self, engine='codex'):
        return {'project': 'synthetic', 'kind': 'decision', 'title': 'Reuse tested modules',
                'summary': 'Use a modular architecture with reviewed source evidence.',
                'tags': ['architecture'], 'symbols': [], 'links': [],
                'provenance': {'engine': engine, 'source_sha256': 'a' * 64}}

    def test_reasoning_review_and_cross_session_memory_handoff(self):
        planned = dispatch('reasoning-plan', self.request())
        wrapper = {'plan': planned, 'reviews': [], 'verification': []}
        self.assertEqual(dispatch('reasoning-review', wrapper)['decision'], 'blocked')
        now = time.time()
        # Explicit synthetic evaluator assertions, not real model reviews.
        wrapper['reviews'] = [
            {'reviewer': 'fixture-' + str(i), 'model': 'fixture-model-' + str(i),
             'revision': str(i) * 40, 'decision': 'approved',
             'source_sha256': 'a' * 64, 'plan_sha256': planned['plan_sha256'],
             'evidence_sha256': str(i) * 64, 'at': now} for i in [1, 2]]
        wrapper['verification'] = [{'id': 'tests', 'status': 'passed',
                                    'source_sha256': 'a' * 64,
                                    'plan_sha256': planned['plan_sha256'],
                                    'sha256': 'c' * 64, 'at': now}]
        self.assertEqual(dispatch('reasoning-review', wrapper)['decision'], 'accepted')
        state = self.root / 'memory'
        first = dispatch('memory-put', self.record(), state_dir=state)
        second = dispatch('memory-put', self.record('claude-code'), state_dir=state)
        self.assertEqual(first['id'], second['id'])
        self.assertTrue(second['deduplicated'])
        checkpoint = self.root / 'checkpoints' / 'checkpoint.json'
        dispatch('memory-checkpoint', {'destination': str(checkpoint)}, state_dir=state)
        restored = self.root / 'restored'
        dispatch('memory-restore', {'checkpoint': str(checkpoint)}, state_dir=restored)
        rows = dispatch('memory-search', {'project': 'synthetic', 'query': 'architecture'},
                        state_dir=restored)
        self.assertEqual(rows[0]['id'], first['id'])
        self.assertEqual(len(rows[0]['provenances']), 2)
        self.assertEqual(dispatch('memory-graph', {'project': 'other'}, state_dir=restored)['nodes'], [])

    def test_factory_planning_does_not_advance_without_evidence(self):
        request = {'schema_version': 1, 'project': 'synthetic', 'source_revision': 'a' * 40,
                   'requirements': [{'id': 'access', 'summary': 'Require an authorized caller',
                                     'acceptance': ['allowed', 'denied']}], 'targets': ['web', 'api']}
        planned = dispatch('factory-plan', request)
        result = dispatch('factory-evaluate', {'plan': planned, 'receipts': []}, artifact_root=self.root)
        self.assertEqual(result['verified_count'], 0)
        self.assertFalse(result['deployment_authorized'])
        self.assertEqual(result['ready'], ['requirements'])

    def test_disposable_repair_and_rollback_do_not_authorize_code_execution(self):
        from engineering_os.healing import artifact_digest
        before, after = {'settings.json': '{"enabled":false}'}, {'settings.json': '{"enabled":true}'}
        result = dispatch('healing-verify', {
            'schema_version': 1, 'project': 'synthetic', 'baseline_files': before,
            'candidate_files': after, 'baseline_sha256': artifact_digest(before),
            'candidate_sha256': artifact_digest(after),
            'checks': [{'id': 'enabled', 'kind': 'json-value', 'path': 'settings.json',
                        'pointer': ['enabled'], 'value': True}],
            'rollback_checks': [{'id': 'disabled', 'kind': 'json-value', 'path': 'settings.json',
                                 'pointer': ['enabled'], 'value': False}]})
        self.assertFalse(result['runtime_tested'])
        self.assertFalse(result['deployment_allowed'])

    def test_missing_team_usage_never_becomes_exact_task_economics(self):
        result = dispatch('economics', {'schema_version': 1, 'project': 'synthetic',
                                      'actors': [{'id': 'coordinator', 'role': 'coordinator', 'complete': False}],
                                      'tasks': [], 'usage': [], 'overheads': []})
        self.assertFalse(result['accounting_complete'])
        self.assertIsNone(result['summary']['tokens_per_verified_task'])
        self.assertIsNone(result['subscription_allowance'])

    def test_cli_runs_in_two_real_local_processes_and_loads_only_selected_engine(self):
        source = self.root / 'request.json'
        source.write_text(json.dumps(self.request()))
        command = [sys.executable, '-m', 'engineering_os.intelligence', 'reasoning-plan', '--input', str(source)]
        for _ in range(2):
            completed = subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(completed.stdout)['provider_calls'], 0)
        code = ('import sys; from engineering_os.intelligence import dispatch; '
                'assert "engineering_os.memory" not in sys.modules; '
                'assert "engineering_os.reasoning" not in sys.modules; '
                'assert "engineering_os.healing" not in sys.modules')
        subprocess.run([sys.executable, '-c', code], check=True, capture_output=True)

    def test_rejected_input_is_bounded_and_redacted(self):
        path = self.root / 'input.json'
        for data in ['{"private":"SYNTHETIC_PRIVATE_MARKER","private":1}', '{"value":NaN}', '[]']:
            path.write_text(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                read_request(path)
        path.write_text('{"private":"SYNTHETIC_PRIVATE_MARKER"}')
        stderr, stdout = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            status = main(['reasoning-plan', '--input', str(path)])
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', stderr.getvalue())
        self.assertNotIn(str(path), stderr.getvalue())

    def test_envelopes_and_private_paths_fail_closed(self):
        for operation, request in [('unknown', {}), ('reasoning-review', {}),
                                   ('memory-search', {'project': 'synthetic', 'query': 'x'}),
                                   ('factory-evaluate', {'plan': {}, 'receipts': []})]:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                dispatch(operation, request)
        with self.assertRaises(ValueError):
            dispatch('memory-put', self.record(), state_dir=pathlib.Path(__file__).parents[1] / 'private-memory')

    def test_fifo_and_symlink_inputs_are_rejected_without_blocking(self):
        fifo = self.root / 'pipe.json'
        os.mkfifo(fifo)
        result = subprocess.run([sys.executable, '-m', 'engineering_os.intelligence',
                                 'reasoning-plan', '--input', str(fifo)],
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 1)
        target = self.root / 'request.json'
        target.write_text('{}')
        link = self.root / 'linked.json'
        link.symlink_to(target)
        with self.assertRaises(OSError):
            read_request(link)


if __name__ == '__main__':
    unittest.main()
