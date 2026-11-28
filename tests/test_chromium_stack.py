import hashlib
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STACK = ROOT / 'motion-library/chromium-stack'


class ChromiumStackTests(unittest.TestCase):
    def test_only_reviewed_exact_playwright_is_installed(self):
        package = json.loads((STACK / 'package.json').read_text())
        lock = json.loads((STACK / 'package-lock.json').read_text())
        policy = json.loads((ROOT / 'catalog/capabilities/playwright.json').read_text())
        self.assertEqual(policy['requested_state'], 'TESTED')
        self.assertEqual(package['devDependencies'], {'playwright': policy['version']})
        self.assertNotIn('dependencies', package)
        for path in ['node_modules/playwright', 'node_modules/playwright-core']:
            self.assertEqual(lock['packages'][path]['version'], policy['version'])
            self.assertEqual(lock['packages'][path]['integrity'], policy['npm_integrities'][path.split('/')[-1]])
            self.assertEqual(lock['packages'][path]['license'], 'Apache-2.0')
            self.assertTrue(lock['packages'][path]['integrity'].startswith('sha512-'))
        provenance = json.loads((STACK / 'provenance.json').read_text())
        self.assertEqual(provenance['original_manifest']['dependency_count'], 18)
        self.assertFalse(provenance['dependency_review']['original_other_engines_installed'])

    def test_historical_render_evidence_preserves_reviewed_digest_and_scope(self):
        policy = json.loads((ROOT / 'catalog/capabilities/playwright.json').read_text())
        history = policy['historical_reviews'][0]
        path = ROOT / history['native_receipt']['path']
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), history['native_receipt']['sha256'])
        evidence = json.loads(path.read_text())
        # Package manifests changed; historical proof never claims the new driver ran.
        for source, expected in evidence['inputs'].items():
            actual = hashlib.sha256((STACK / source).read_bytes()).hexdigest()
            if source in ('package.json', 'package-lock.json'):
                self.assertNotEqual(actual, expected, source)
            else:
                self.assertEqual(actual, expected, source)
        self.assertEqual(evidence['webgpu_rendering_cases'], 0)
        self.assertEqual(evidence['toolchain']['playwright'], history['version'])
        self.assertNotEqual(history['version'], policy['version'])
        self.assertNotEqual(policy['runtime_receipt'], history['native_receipt']['path'])
        self.assertEqual(len(evidence['cases']), 3)
        for row in evidence['cases']:
            self.assertTrue(all(row['checks'].values()))
            self.assertTrue(row['rendered']['canvas2d'])
            self.assertTrue(row['rendered']['webgl_shader'])
            self.assertFalse(row['webgpu']['rendering_tested'])
            self.assertEqual(row['external_requests'], 0)
            self.assertGreater(row['benchmark']['frames'], 0)
            self.assertGreater(row['benchmark']['median_interval_ms'], 0)
            self.assertLessEqual(row['benchmark']['p95_interval_ms'], row['benchmark']['frame_budget_ms'])
        reduced = evidence['cases'][-1]
        self.assertTrue(reduced['reduced_motion'])
        self.assertFalse(reduced['rendered']['css_animation'])
        self.assertFalse(reduced['rendered']['waapi'])
