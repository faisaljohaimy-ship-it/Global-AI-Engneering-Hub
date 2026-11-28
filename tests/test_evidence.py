import json
import copy
import hashlib
import math
import pathlib
import shlex
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def native_smoke_budget(workflow):
    """Read the executed smoke CLI, not comments or an unrelated test budget."""
    commands = []
    for line in workflow.splitlines():
        if line.strip().startswith('node '):
            command = shlex.split(line.strip(), comments=True)
            if command[:2] == ['node', 'motion-library/chromium-stack/smoke.mjs']:
                commands.append(command)
    if len(commands) != 1:
        raise ValueError('Exactly one actual native smoke command required')
    command = commands[0]
    values = {}
    for option in ('--frame-budget-ms', '--frames'):
        if command.count(option) != 1:
            raise ValueError('Exactly one explicit native option required')
        index = command.index(option)
        if index + 1 >= len(command):
            raise ValueError('Native option value required')
        values[option] = command[index + 1]
    budget = float(values['--frame-budget-ms'])
    frames = int(values['--frames'])
    if not math.isfinite(budget) or not 0 < budget <= 20 or not 30 <= frames <= 600:
        raise ValueError('Native receipt policy requires a positive budget <=20ms and 30..600 frames')
    return budget


class EvidenceTests(unittest.TestCase):
    def test_reviewed_native_curation_preserves_all_retained_values_and_raw_samples(self):
        policy=json.loads((ROOT/'catalog/capabilities/playwright.json').read_text())
        manifest=json.loads((ROOT/policy['provenance_manifest']['path']).read_text())
        raw=json.loads((ROOT/policy['runtime_raw_receipt']['path']).read_text())
        curated=json.loads((ROOT/policy['runtime_receipt']).read_text())
        expected=copy.deepcopy(raw)
        removed=[]
        samples=0
        for index,row in enumerate(expected['cases']):
            benchmark=row['benchmark']
            intervals=benchmark.pop('intervals_ms')
            self.assertEqual(len(intervals),benchmark['frames'])
            self.assertTrue(all(math.isfinite(value) and value>0 for value in intervals))
            ordered=sorted(intervals)
            self.assertEqual(benchmark['median_interval_ms'],ordered[int(len(ordered)*.5)])
            self.assertEqual(benchmark['p95_interval_ms'],ordered[int(len(ordered)*.95)])
            self.assertLessEqual(benchmark['p95_interval_ms'],benchmark['frame_budget_ms'])
            self.assertEqual(benchmark['frame_budget_ms'],20)
            samples+=len(intervals)
            removed.append(f'cases/{index}/benchmark/intervals_ms')
        self.assertEqual(curated,expected)
        self.assertEqual(samples,90)
        self.assertEqual(manifest['native_curation']['only_removed_json_paths'],removed)
        self.assertEqual(manifest['native_curation']['raw_interval_samples_retained'],samples)
        self.assertEqual(hashlib.sha256((ROOT/policy['runtime_receipt']).read_bytes()).hexdigest(),policy['runtime_receipt_sha256'])
        self.assertEqual(hashlib.sha256((ROOT/policy['runtime_raw_receipt']['path']).read_bytes()).hexdigest(),policy['runtime_raw_receipt']['sha256'])
        self.assertEqual(policy['maximum_receipt_age_seconds'],86400)

    def test_current_motion_receipts_bind_all_ids_profiles_and_sources_for_three_engines(self):
        policy=json.loads((ROOT/'catalog/capabilities/playwright.json').read_text())
        definitions=json.loads((ROOT/'motion-library/expansion/definitions.json').read_text())['definitions']
        expected={row['id'] for row in definitions}
        self.assertEqual(len(expected),400)
        self.assertEqual(set(policy['motion_cross_browser_receipts']),{'chromium','firefox','webkit'})
        for engine,reference in policy['motion_cross_browser_receipts'].items():
            path=ROOT/reference['path']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),reference['sha256'])
            receipt=json.loads(path.read_text())
            self.assertEqual(receipt['engine'],engine+'-canvas2d')
            self.assertEqual(receipt['playwright_version'],policy['version'])
            self.assertEqual((receipt['definitions'],receipt['basic'],receipt['advanced']),(400,200,200))
            self.assertEqual((receipt['frame_samples'],receipt['reduced_motion_cases'],receipt['benchmark_draws']),(2400,800,9600))
            self.assertFalse(receipt['production_fps_verified']);self.assertFalse(receipt['gpu_runtime_verified'])
            for name,digest in receipt['source_sha256'].items():
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest)
            self.assertEqual({(r['viewport']['width'],r['viewport']['height'],r['direction'],r['language']) for r in receipt['profiles']},
                             {(390,844,'rtl','ar'),(1280,900,'ltr','en')})
            for profile in receipt['profiles']:
                self.assertEqual(len(profile['definitions']),400)
                self.assertEqual({row['id'] for row in profile['definitions']},expected)
                for row in profile['definitions']:
                    self.assertEqual((row['frame_samples'],row['benchmark_frames']),(3,12))
                    self.assertGreaterEqual(row['distinct_sampled_frames'],2)
                    self.assertGreater(row['minimum_changed_pixels'],0)
                    self.assertTrue(row['reduced_motion_stable'])
                    self.assertTrue(0<=row['cpu_p95_ms']<=row['cpu_budget_ms']<=1000/60)
        self.assertEqual(policy['motion_runtime_receipt'],policy['motion_cross_browser_receipts']['chromium']['path'])

    def test_current_quality_proof_remains_lab_only_and_binds_the_current_lock(self):
        policy=json.loads((ROOT/'catalog/capabilities/playwright.json').read_text())
        report=json.loads((ROOT/policy['quality_receipt']['path']).read_text())
        self.assertFalse(report['live_recheck_performed'])
        self.assertEqual({row['profile'] for row in report['profiles']},{'desktop','mobile'})
        for row in report['profiles']:
            self.assertTrue(row['passed']);self.assertEqual(row['failures'],[])
            self.assertEqual(row['tool_versions']['playwright'],policy['version'])
            self.assertEqual(row['package_lock_sha256'],hashlib.sha256((ROOT/'motion-library/quality/package-lock.json').read_bytes()).hexdigest())
            self.assertGreaterEqual(row['metrics']['performance'],95)
            self.assertGreaterEqual(row['metrics']['accessibility'],95)
            self.assertLessEqual(row['metrics']['lcp_ms'],2500);self.assertLessEqual(row['metrics']['cls'],.1)
            self.assertEqual(row['metrics']['critical_axe'],0);self.assertIsNone(row['metrics']['inp_ms'])
            for name,digest in row['source_sha256'].items():
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest)

    def test_actual_ci_native_smoke_budget_satisfies_strict_receipt_policy(self):
        workflow = (ROOT / '.github/workflows/operating-system.yml').read_text()
        self.assertLessEqual(native_smoke_budget(workflow), 20)

    def test_native_ci_budget_guard_rejects_relaxed_missing_or_ambiguous_options(self):
        # Synthetic command fixtures exercise policy checks only, not rendering.
        command = 'node motion-library/chromium-stack/smoke.mjs --frames 30 --frame-budget-ms 20 --out "$CHROMIUM_EVIDENCE_DIR"'
        self.assertEqual(native_smoke_budget(command), 20)
        for value in ('100', '20.01', '0', '-1', 'NaN', 'Infinity'):
            with self.subTest(budget=value), self.assertRaises(ValueError):
                native_smoke_budget(command.replace('--frame-budget-ms 20', '--frame-budget-ms ' + value))
        invalid = [command.replace('--frame-budget-ms 20', ''),
                   command + ' --frame-budget-ms 100',
                   command.replace('--frames 30', '--frames 12'),
                   '# ' + command,
                   command + '\n' + command]
        for value in invalid:
            with self.subTest(command=value), self.assertRaises(ValueError):
                native_smoke_budget(value)

    def test_studio_quality_snapshot_matches_sources_and_measured_budgets(self):
        policy=json.loads((ROOT/'catalog/capabilities/playwright.json').read_text())
        history=policy['historical_reviews'][0]
        path=ROOT/history['quality_receipt']['path']
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),history['quality_receipt']['sha256'])
        report=json.loads(path.read_text())
        self.assertFalse(report['live_recheck_performed'])
        self.assertEqual({row['profile'] for row in report['profiles']},{'desktop','mobile'})
        for row in report['profiles']:
            self.assertTrue(row['passed']);self.assertEqual(row['failures'],[])
            metrics=row['metrics']
            self.assertGreaterEqual(metrics['performance'],95)
            self.assertGreaterEqual(metrics['accessibility'],95)
            self.assertLessEqual(metrics['lcp_ms'],2500)
            self.assertLessEqual(metrics['cls'],.1)
            self.assertEqual(metrics['critical_axe'],0)
            self.assertIsNone(metrics['inp_ms'])
            for name,digest in row['source_sha256'].items():
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest)
            self.assertEqual(row['package_lock_sha256'],history['quality_package_lock_sha256'])
            self.assertEqual(row['tool_versions']['playwright'],history['version'])
            self.assertNotEqual(hashlib.sha256((ROOT/'motion-library/quality/package-lock.json').read_bytes()).hexdigest(),row['package_lock_sha256'])

    def test_sample_render_evidence_matches_current_inputs(self):
        report = json.loads((ROOT / "motion-library/evidence/sample-render.json").read_text())
        inputs = report["inputs"]
        files = {
            "scene_sha256": ROOT / "motion-library/render/scene.html",
            "runtime_sha256": ROOT / "motion-library/runtime/hub-motion.mjs",
            "core_sha256": ROOT / "motion-library/runtime/core.mjs",
            "renderer_sha256": ROOT / "motion-library/render/render.mjs",
        }
        self.assertTrue(report["pass"])
        self.assertTrue(all(report["checks"].values()))
        for key, path in files.items():
            self.assertEqual(inputs[key], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_all_22_programs_have_sanitized_probe_evidence(self):
        catalog = json.loads((ROOT / "integrations/PROGRAMS.json").read_text())
        evidence = json.loads((ROOT / "integrations/EVIDENCE.json").read_text())
        expected = {item["name"] for item in catalog["programs"]}
        rows = evidence["programs"]
        self.assertEqual(len(expected), 22)
        self.assertEqual({item["program"] for item in rows}, expected)
        self.assertEqual(len(rows), 22)
        self.assertTrue(all(item["mutation"] is False for item in rows))
        self.assertTrue(all(item["budget_impact"] == 0 for item in rows))
        serialized = json.dumps(evidence).casefold()
        for forbidden in ("email", "account_id", "team_id", "balance", "access_token"):
            self.assertNotIn(f'"{forbidden}"', serialized)

    def test_probe_outcome_counts(self):
        rows = json.loads((ROOT / "integrations/EVIDENCE.json").read_text())["programs"]
        self.assertEqual(sum(item["result"] == "success" for item in rows), 12)
        self.assertEqual(sum(item["authenticated_read"] for item in rows), 10)
        self.assertEqual(sum(item["surface"] == "local_executable" for item in rows), 2)
        self.assertEqual(sum(item["result"] == "unavailable" for item in rows), 10)

    def test_recovery_manifest_is_index_only(self):
        data = json.loads((ROOT / "catalog/recovered-packages.json").read_text())
        self.assertEqual(len(data["packages"]), 3)
        self.assertTrue(all(item["status"] == "verified-source" for item in data["packages"]))
        self.assertTrue(all(item["imported"] is False for item in data["packages"]))
        self.assertTrue(all(item["source_commit"] for item in data["packages"]))
        self.assertTrue(all(item["imported"] is False for item in data["deferred"]))
        self.assertEqual(data["deferred"][0]["id"], "catalog-media-tools")
        packs = json.loads((ROOT / "catalog/packs.json").read_text())["packs"]
        self.assertEqual(set(packs), {"motion-runtime", "engineering-sdk", "motion-sdk", "headroom-context", "gaie-factory"})
        self.assertEqual(packs["engineering-sdk"]["version"], "1.0.1")
        self.assertNotIn("catalog-media-tools", packs)


if __name__ == "__main__":
    unittest.main()
