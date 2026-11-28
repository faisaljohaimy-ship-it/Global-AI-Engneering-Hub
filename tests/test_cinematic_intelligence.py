import copy
import datetime as dt
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
        paths = [cinematic.INVENTORY, *cinematic.INPUTS, 'docs/evidence/nextgen-camera-chromium.json']
        for name in paths:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((self.original / name).read_bytes())
        self.patch = patch.object(cinematic, 'ROOT', self.root)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.receipt_path = self.root / 'docs/evidence/nextgen-camera-chromium.json'
        self.receipt = json.loads(self.receipt_path.read_text())
        self.now = dt.datetime.fromisoformat(self.receipt['recorded_at_utc'].replace('Z', '+00:00')).timestamp() + 1
        self.request = {'schema_version': 1, 'required_browsers': ['chromium'], 'max_age_seconds': 86400, 'max_p95_ms': 25}

    def report(self):
        return cinematic.audit_inventory(self.request, now=self.now)

    def mutate_receipt(self, change):
        value = copy.deepcopy(self.receipt); change(value)
        self.receipt_path.write_text(json.dumps(value))

    def test_actual_inventory_counts_keep_namespaces_distinct(self):
        value = self.report()
        self.assertEqual((value['brief_count'], value['historical_pr16_source_count'], value['local_implemented_count'], value['not_implemented_in_either_inspected_source_count']), (200, 34, 3, 163))
        self.assertEqual(value['reference_recipes_excluded'], 400)
        self.assertEqual(value['operational_for_requested_browsers_count'], 3)
        self.assertFalse(value['pr16']['runtime_reverified_here'])
        self.assertEqual(value['provider_calls'], 0)

    def test_all_browsers_default_withdraws_activation(self):
        self.assertEqual(cinematic.audit_inventory(now=self.now)['operational_for_requested_browsers_count'], 0)

    def test_source_or_harness_change_withdraws_proof(self):
        for name in cinematic.INPUTS:
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
            self.assertEqual(self.report()['operational_for_requested_browsers_count'], 0)
        self.receipt_path.write_text(json.dumps(self.receipt))

    def test_future_stale_and_stricter_budget(self):
        self.assertEqual(cinematic.audit_inventory(self.request, now=self.now - 100)['operational_for_requested_browsers_count'], 0)
        self.assertEqual(cinematic.audit_inventory(self.request, now=self.now + 86401)['operational_for_requested_browsers_count'], 0)
        self.request['max_p95_ms'] = .1
        self.assertEqual(self.report()['operational_for_requested_browsers_count'], 0)

    def test_timestamp_only_receipt_refresh_withdraws_claim(self):
        self.mutate_receipt(lambda r: r.update(recorded_at_utc=dt.datetime.fromtimestamp(
            self.now, dt.timezone.utc).isoformat()))
        self.assertEqual(self.report()['operational_for_requested_browsers_count'], 0)

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

    def test_symlink_receipt_or_source_refused(self):
        p = self.root / cinematic.CAMERA_SOURCE; p.unlink(); p.symlink_to(self.original / cinematic.CAMERA_SOURCE)
        with self.assertRaises(cinematic.CinematicError): self.report()

    def copy_inventory_sources(self):
        names = [cinematic.ENGINE_REGISTRY, cinematic.REFERENCE_DEFINITIONS, cinematic.COMPONENTS,
                 *(str(p.relative_to(self.original)) for p in (self.original / cinematic.NATIVE_MOTIONS).glob('*/*.mjs'))]
        for name in names:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((self.original / name).read_bytes())

    def test_motion_inventory_keeps_native_and_reference_counts_apart(self):
        self.copy_inventory_sources()
        value = cinematic.motion_inventory()
        native = value['native_engine_motions']
        self.assertEqual((native['count'], native['source_files'], native['source_bound_to_registry']), (67, 67, 67))
        self.assertEqual(native['by_engine'], {'canvas2d': 22, 'composition': 1, 'dom': 2, 'svg': 3,
                                               'webgl2-glsl': 31, 'webgl2-points': 7, 'webgpu-wgsl': 1})
        self.assertEqual((native['gpu_api_motions'], native['cpu_motions']), (39, 28))
        self.assertEqual(value['nextgen_camera_motions']['count'], 3)
        self.assertEqual(value['native_total'], 70)
        self.assertEqual(value['reference_canvas2d_motions']['count'], 400)
        self.assertEqual(value['reference_canvas2d_motions']['by_tier'], {'advanced': 200, 'basic': 200})
        self.assertEqual(value['native_3d_scene_engines'], [])
        self.assertFalse(value['gpu_hardware_claimed'])
        self.assertNotIn(437, [v for v in value.values() if isinstance(v, int)])

    def test_motion_inventory_unbinds_changed_native_source(self):
        self.copy_inventory_sources()
        source = self.root / cinematic.NATIVE_MOTIONS / 'quantum/light-tunnel.mjs'
        source.write_bytes(source.read_bytes() + b'\n')
        self.assertEqual(cinematic.motion_inventory()['native_engine_motions']['source_bound_to_registry'], 66)

    def test_motion_inventory_rejects_duplicates_overlap_and_symlinks(self):
        self.copy_inventory_sources()
        path = self.root / cinematic.ENGINE_REGISTRY
        original = json.loads(path.read_text())
        mutations = [lambda r: r['motions'].append(r['motions'][0]),
                     lambda r: r['motions'][0].update(id='os-quantum-b01'),
                     lambda r: r['motions'][0].update(engine='../gpu'),
                     lambda r: r.update(motions=[])]
        for mutate in mutations:
            value = copy.deepcopy(original); mutate(value); path.write_text(json.dumps(value))
            with self.assertRaises(cinematic.CinematicError):
                cinematic.motion_inventory()
        path.write_text(json.dumps(original))
        definitions = self.root / cinematic.REFERENCE_DEFINITIONS
        definitions.unlink(); definitions.symlink_to(self.original / cinematic.REFERENCE_DEFINITIONS)
        with self.assertRaises(cinematic.CinematicError):
            cinematic.motion_inventory()
