import json
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
        self.assertEqual(set(packs), {"motion-runtime", "engineering-sdk", "motion-sdk", "headroom-context"})
        self.assertEqual(packs["engineering-sdk"]["version"], "1.0.0")
        self.assertNotIn("catalog-media-tools", packs)


if __name__ == "__main__":
    unittest.main()
