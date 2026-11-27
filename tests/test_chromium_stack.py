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
        self.assertEqual(package['devDependencies'], {'playwright': '1.63.0'})
        self.assertNotIn('dependencies', package)
        for path in ['node_modules/playwright', 'node_modules/playwright-core']:
            self.assertEqual(lock['packages'][path]['version'], '1.63.0')
            self.assertEqual(lock['packages'][path]['license'], 'Apache-2.0')
            self.assertTrue(lock['packages'][path]['integrity'].startswith('sha512-'))
        provenance = json.loads((STACK / 'provenance.json').read_text())
        self.assertEqual(provenance['original_manifest']['dependency_count'], 18)
        self.assertFalse(provenance['dependency_review']['original_other_engines_installed'])

    def test_render_evidence_is_source_bound_and_webgpu_is_not_render_claim(self):
        evidence = json.loads((ROOT / 'docs/evidence/chromium-recovery-2026-11-27.json').read_text())
        for source, expected in evidence['inputs'].items():
            self.assertEqual(hashlib.sha256((STACK / source).read_bytes()).hexdigest(), expected, source)
        self.assertEqual(evidence['webgpu_rendering_cases'], 0)
        self.assertEqual(evidence['toolchain']['playwright'], '1.63.0')
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
