import contextlib
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from engineering_os import control, layer_checks


class LayerAcceptanceTests(unittest.TestCase):
    def test_all_twenty_layers_have_unique_ids_and_fixed_local_suites(self):
        rows = control.architecture()['layers']
        self.assertEqual([row['id'] for row in rows], list(layer_checks.CHECKS))
        for row in rows:
            self.assertTrue(row['acceptance_suites'])
            self.assertTrue(all(control.safe_path(path).is_file() for path in row['acceptance_suites']))

    def test_failed_or_unavailable_suite_never_verifies_layer(self):
        for status in ('failed', 'unavailable', 'missing'):
            with self.subTest(status=status), patch.object(layer_checks, '_run_suite',
                    return_value={'suite': 'tests/test_hub.py', 'status': status, 'tests': 0, 'skipped': 0}):
                result = layer_checks.verify_layers('L04')
                self.assertEqual(result['passed'], 0)
                self.assertEqual(result['layers'][0]['status'], 'failed')

    def test_layer_check_refuses_unknown_selector(self):
        with self.assertRaises(ValueError):
            layer_checks.verify_layers('../outside')

    def test_master_acceptance_covers_scoping_approval_workflow_and_native_fixture(self):
        masters = {'tests/test_capability_scope.py', 'tests/test_master_approval.py',
                   'tests/test_master_workflow.py'}
        for layer in ('L05', 'L20'):
            self.assertLessEqual(masters, set(layer_checks.CHECKS[layer]))
            self.assertIn('tests/test_claude_bridge.py', layer_checks.CHECKS[layer])
            self.assertIn('.mcp.json', layer_checks.SUPPLEMENTARY_INPUTS[layer])
        self.assertIn('tests/test_claude_native_fixture.py', layer_checks.CHECKS['L20'])

    @contextlib.contextmanager
    def fixture(self):
        suites = {'L01': ('first.py',), 'L02': ('first.py', 'second.py')}
        layers = [('L01', 'first', ['first-source.py']), ('L02', 'second', ['second-source.py'])]
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for name in ('first.py', 'first-source.py', 'second.py', 'second-source.py',
                         *layer_checks.COMMON_INPUTS):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# local verification fixture\n', encoding='utf-8')
            with (patch.object(control, 'ROOT', root), patch.object(control, 'LAYERS', layers),
                  patch.object(layer_checks, 'CHECKS', suites)):
                yield root

    def test_shared_suite_cannot_verify_older_evidence_after_a_source_change(self):
        def run(name):
            if name == 'first.py':
                source = root / 'second-source.py'
                original = source.read_bytes()
                source.write_text('# source changed\n', encoding='utf-8')
                source.write_bytes(original)
            return {'suite': name, 'status': 'passed', 'tests': 1, 'skipped': 0}

        with self.fixture() as root, patch.object(layer_checks, '_run_suite', side_effect=run) as runner:
            result = layer_checks.verify_layers()
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(result['passed'], 0)
        self.assertEqual(result['inputs_changed_during_verification'], ['second-source.py'])
        self.assertEqual([row['status'] for row in result['layers']], ['failed', 'failed'])

    def test_missing_unsafe_and_malformed_inputs_cannot_green_a_layer(self):
        valid = {'suite': 'first.py', 'status': 'passed', 'tests': 1, 'skipped': 0}
        for result in (None, {}, {**valid, 'tests': 0}, {**valid, 'tests': True},
                       {**valid, 'skipped': 1}, {**valid, 'suite': 'other.py'}):
            with self.subTest(result=result), self.fixture(), patch.object(layer_checks, '_run_suite',
                                                                                 return_value=result):
                self.assertEqual(layer_checks.verify_layers('L01')['passed'], 0)
        with self.fixture() as root, patch.object(layer_checks, '_run_suite', return_value=valid):
            source = root / 'first-source.py'
            source.unlink()
            source.symlink_to(root / 'second-source.py')
            result = layer_checks.verify_layers('L01')
        self.assertEqual(result['passed'], 0)
        self.assertEqual(result['layers'][0]['unavailable_inputs'], ['first-source.py'])

    def test_test_process_receives_only_runtime_path_and_locale(self):
        response = subprocess.CompletedProcess([], 0, '', '\nRan 1 test in 0.001s\n\nOK\n')
        with (self.fixture(), patch.dict(os.environ, {'UNIT_ONLY_SECRET': 'redacted-fixture'}),
              patch.object(layer_checks.subprocess, 'run', return_value=response) as run):
            result = layer_checks._run_suite('first.py')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(set(run.call_args.kwargs['env']), {'PATH', 'LANG'})
        self.assertNotIn('redacted-fixture', str(run.call_args.kwargs))

    def test_real_python_result_requires_nonempty_suite_without_skip(self):
        fixture = '''
import unittest

class LocalCheck(unittest.TestCase):
    def test_actual(self):
        self.assertEqual(2 + 2, 4)
'''
        with self.fixture() as root:
            source = root / 'first.py'
            source.write_text(fixture, encoding='utf-8')
            self.assertEqual(layer_checks._run_suite('first.py')['status'], 'passed')
            source.write_text(fixture.replace('    def test_actual', '    @unittest.skip("fixture")\n    def test_actual'),
                              encoding='utf-8')
            skipped = layer_checks._run_suite('first.py')
            self.assertEqual((skipped['status'], skipped['skipped']), ('failed', 1))
            source.write_text('# No tests in this fixture\n', encoding='utf-8')
            self.assertEqual(layer_checks._run_suite('first.py')['status'], 'failed')
