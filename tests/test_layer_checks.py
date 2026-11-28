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
