import copy
import datetime as dt
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from engineering_os import cinematic


class CinematicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.original = cinematic.ROOT
        local = cinematic._read(cinematic.LOCAL_INVENTORY)
        self.canvas_count = sum(len(catalog['ids']) for catalog in local['catalogs'])
        self.receipts = {browser: f'docs/evidence/nextgen-originals-{browser}.json'
                         for browser in cinematic.BROWSERS}
        self.inputs = cinematic.INPUTS | {catalog['source'] for catalog in local['catalogs']}
        paths = [cinematic.INVENTORY, *self.inputs, *self.receipts.values()]
        for name in paths:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((self.original / name).read_bytes())
        self.patch = patch.object(cinematic, 'ROOT', self.root)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.receipt_path = self.root / self.receipts['chromium']
        self.receipt = json.loads(self.receipt_path.read_text())
        self.now = max(dt.datetime.fromisoformat(json.loads((self.root / name).read_text())[
            'recorded_at_utc'].replace('Z', '+00:00')).timestamp() for name in self.receipts.values()) + 1
        self.request = {'schema_version': 1, 'required_browsers': ['chromium'], 'max_age_seconds': 86400, 'max_p95_ms': 25}

    def report(self):
        return cinematic.audit_inventory(self.request, now=self.now)

    def mutate_receipt(self, change):
        value = copy.deepcopy(self.receipt); change(value)
        self.receipt_path.write_text(json.dumps(value))

    def test_actual_inventory_counts_keep_namespaces_distinct(self):
        value = self.report()
        self.assertEqual((value['brief_count'], value['historical_pr16_source_count']), (200, 34))
        self.assertGreaterEqual(value['local_implemented_count'], self.canvas_count)
        self.assertEqual(value['not_implemented_in_either_inspected_source_count'], 166 - value['local_implemented_count'])
        self.assertEqual(value['reference_recipes_excluded'], 400)
        self.assertEqual(value['operational_for_requested_browsers_count'], self.canvas_count)
        self.assertFalse(value['pr16']['runtime_reverified_here'])
        self.assertEqual(value['provider_calls'], 0)

    def test_all_browsers_default_requires_a_complete_matrix(self):
        self.assertEqual(cinematic.audit_inventory(now=self.now)['operational_for_requested_browsers_count'], self.canvas_count)
        (self.root / self.receipts['webkit']).unlink()
        self.assertEqual(cinematic.audit_inventory(now=self.now)['operational_for_requested_browsers_count'], 0)

    def test_source_or_harness_change_withdraws_proof(self):
        for name in self.inputs:
            p = self.root / name; old = p.read_bytes(); p.write_bytes(old + b'\n')
            self.assertEqual(self.report()['operational_for_requested_browsers_count'], 0, name)
            p.write_bytes(old)

    def test_bad_proof_matrix_and_metrics_withdraw_claim(self):
        mutations = [lambda r: r.update(status='failed'), lambda r: r['cases'].pop(),
                     lambda r: r['cases'].__setitem__(0, r['cases'][1]),
                     lambda r: r['cases'][0]['checks'].update(rtl=False),
                     lambda r: r['cases'][0]['checks'].update(rtl=1),
                     lambda r: r['cases'][0]['frames'][0].update(drawn_pixels=0),
                     lambda r: r['cases'][0]['benchmark'].update(p95_ms=float('nan')),
                     lambda r: r['cases'][0]['benchmark'].update(p95_ms=30),
                     lambda r: r.update(gpu_runtime_verified=True),
                     lambda r: r.update(external_requests=1),
                     lambda r: r.update(browser='webkit'),
                     lambda r: r.update(recorded_at_utc='2020-01-01T00:00:00Z')]
        for mutate in mutations:
            self.mutate_receipt(mutate)
            # Even independently pinned malformed evaluator output is rejected.
            digest = hashlib.sha256(self.receipt_path.read_bytes()).hexdigest()
            with patch.dict(cinematic.RECEIPT_SHA256, chromium=digest):
                self.assertEqual(self.report()['operational_for_requested_browsers_count'], 0)
        self.receipt_path.write_text(json.dumps(self.receipt))

    def test_future_stale_and_stricter_budget(self):
        future_cutoff = dt.datetime.fromisoformat(self.receipt['recorded_at_utc'].replace('Z', '+00:00')).timestamp() - 1
        self.assertEqual(cinematic.audit_inventory(self.request, now=future_cutoff)['operational_for_requested_browsers_count'], 0)
        self.assertEqual(cinematic.audit_inventory(self.request, now=self.now + 86401)['operational_for_requested_browsers_count'], 0)
        self.request['max_p95_ms'] = .1
        self.assertEqual(self.report()['operational_for_requested_browsers_count'], 0)

    def test_timestamp_only_receipt_refresh_withdraws_claim(self):
        self.mutate_receipt(lambda r: r.update(recorded_at_utc=dt.datetime.fromtimestamp(
            self.now, dt.timezone.utc).isoformat()))
        self.assertEqual(self.report()['operational_for_requested_browsers_count'], 0)

    def test_whole_original_inventory_is_implemented_and_verified_in_all_three_engines(self):
        for name in [*cinematic.WEBGL_INPUTS,
                     *(f'docs/evidence/nextgen-webgl-{browser}.json' for browser in cinematic.BROWSERS)]:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((self.original / name).read_bytes())
        now = max(self.now, *(dt.datetime.fromisoformat(json.loads((self.root /
            f'docs/evidence/nextgen-webgl-{browser}.json').read_text())['recorded_at_utc'].replace('Z', '+00:00')).timestamp() + 1
            for browser in cinematic.BROWSERS))
        report = cinematic.audit_inventory(now=now)
        self.assertEqual(report['local_implemented_count'], 166)
        self.assertEqual(report['not_implemented_in_either_inspected_source_count'], 0)
        self.assertEqual(report['operational_for_requested_browsers_count'], 166)
        self.assertEqual(set(report['verified_webgl2_browser_receipts']), cinematic.BROWSERS)
        self.assertEqual(sum(row['cases'] for row in report['verified_webgl2_browser_receipts'].values()), 72)
        (self.root / cinematic.WEBGL_SOURCE).write_bytes((self.root / cinematic.WEBGL_SOURCE).read_bytes() + b'\n')
        withdrawn = cinematic.audit_inventory(now=now)
        self.assertEqual(withdrawn['operational_for_requested_browsers_count'], self.canvas_count)

    def test_request_rejects_paths_invalid_browsers_and_non_finite(self):
        for change in [{'path': '/tmp/source'}, {'required_browsers': ['unknown']}, {'required_browsers': ['chromium', 'chromium']}, {'max_p95_ms': float('inf')}, {'max_age_seconds': True}, {'schema_version': True}]:
            with self.assertRaises(cinematic.CinematicError):
                cinematic.audit_inventory({**self.request, **change}, now=self.now)

    def test_inventory_rejects_duplicates_and_unsafe_paths(self):
        p = self.root / cinematic.INVENTORY; original = json.loads(p.read_text())
        for mutate in [lambda r: r['motions'].__setitem__(0, r['motions'][1]),
                       lambda r: r['motions'][0]['pr16_source'].update(path='../secret'),
                       lambda r: r['motions'].pop()]:
            value = copy.deepcopy(original); mutate(value); p.write_text(json.dumps(value))
            with self.assertRaises(cinematic.CinematicError): self.report()

    def test_local_inventory_refuses_duplicate_and_historical_ids(self):
        path = self.root / cinematic.LOCAL_INVENTORY
        original = json.loads(path.read_text())
        for identifier in (original['catalogs'][0]['ids'][0], 'quantum-field-pulse'):
            value = copy.deepcopy(original)
            value['catalogs'][0]['ids'].append(identifier)
            path.write_text(json.dumps(value))
            with self.assertRaises(cinematic.CinematicError):
                self.report()

    def test_symlink_receipt_or_source_refused(self):
        p = self.root / cinematic.CAMERA_SOURCE; p.unlink(); p.symlink_to(self.original / cinematic.CAMERA_SOURCE)
        with self.assertRaises(cinematic.CinematicError): self.report()
