"""Synthetic diagnostics/repair checks; no project or production data."""

import copy
import hashlib
import pathlib
import tempfile
import unittest

from engineering_os.healing import HealingError, analyze, artifact_digest, verify_repair
from engineering_os.orchestration import sha


class AnalysisTests(unittest.TestCase):
    def request(self):
        return {"schema_version": 1, "project": "synthetic", "source_sha256": "b" * 64, "baseline_sha256": "a" * 64,
                "baseline_tests": {"smoke": "passed", "legacy": "passed"}, "current_tests": {"smoke": "failed", "new": "failed"},
                "failures": [{"id": "storage", "component": "db", "kind": "runtime", "error_sha256": "e" * 64, "depends_on": []},
                             {"id": "api", "component": "backend", "kind": "test", "error_sha256": "f" * 64, "depends_on": ["storage"]}],
                "performance": [{"id": "p95", "baseline_ms": 100, "current_ms": 150, "max_ratio": 1.2}],
                "dependencies": [{"package": "library", "required": ["1.0.0", "2.0.0"], "installed": "1.0.0"}],
                "evidence": {"project": "synthetic", "source_sha256": "b" * 64, "baseline_sha256": "a" * 64, "at": 1000, "sha256": "c" * 64}}

    def test_diagnostics_are_deterministic_and_never_authorize_release(self):
        result = analyze(self.request(), now=1001)
        self.assertEqual(result, analyze(self.request(), now=1001))
        self.assertEqual(result["regressions"], ["legacy", "smoke"])
        self.assertEqual(result["missing_baseline_tests"], ["legacy"])
        self.assertEqual(result["new_failures"], ["new"])
        self.assertEqual(result["dependency_conflicts"][0]["reason"], "incompatible-exact-pins")
        self.assertEqual(result["performance_regressions"][0]["ratio"], 1.5)
        self.assertEqual(result["root_cause_hypotheses"][0]["failure"], "storage")
        self.assertEqual(result["root_cause_hypotheses"][0]["downstream_failures"], 1)
        self.assertFalse(result["root_cause_hypotheses"][0]["causal_proof"])
        self.assertEqual(result["production_mutations"], 0)
        self.assertFalse(result["deployment_allowed"])
        self.assertEqual(result.pop("report_sha256"), sha(result))

    def test_no_observed_regression_is_not_a_quality_certification(self):
        request = self.request()
        request.update(current_tests=dict(request["baseline_tests"]), failures=[], performance=[], dependencies=[])
        result = analyze(request, now=1001)
        self.assertEqual(result["status"], "no-regression-observed")
        self.assertTrue(result["uncertainties"])
        self.assertFalse(result["deployment_allowed"])

    def test_old_failure_does_not_become_new_regression(self):
        request = self.request()
        request["baseline_tests"]["smoke"] = "failed"
        result = analyze(request, now=1001)
        self.assertNotIn("smoke", result["regressions"])

    def test_pin_mismatch_proposal_and_exact_compatible_pin(self):
        request = self.request()
        request["dependencies"][0]["required"] = ["2.0.0"]
        self.assertEqual(analyze(request, now=1001)["dependency_conflicts"][0]["reason"], "installed-pin-mismatch")
        request["dependencies"][0]["installed"] = "2.0.0"
        self.assertEqual(analyze(request, now=1001)["dependency_conflicts"], [])

    def test_unexplained_runtime_failure_requires_investigation(self):
        request = self.request()
        request.update(current_tests=dict(request["baseline_tests"]), performance=[], dependencies=[])
        result = analyze(request, now=1001)
        self.assertEqual(result["proposals"][0]["kind"], "investigate-upstream-failure")

    def test_source_project_staleness_and_future_binding(self):
        for field, value in [("project", "other"), ("source_sha256", "d" * 64), ("baseline_sha256", "d" * 64), ("at", 1002), ("at", 0)]:
            with self.subTest(field=field, value=value):
                request = self.request()
                request["evidence"][field] = value
                with self.assertRaises(HealingError):
                    analyze(request, now=90000 if value == 0 else 1001)

    def test_unknown_dependency_cycle_duplicate_and_self_are_rejected(self):
        for dependency in (["absent"], ["api"], ["storage", "storage"]):
            request = self.request()
            request["failures"][1]["depends_on"] = dependency
            with self.assertRaises(HealingError):
                analyze(request, now=1001)
        request = self.request()
        request["failures"][0]["depends_on"] = ["api"]
        with self.assertRaises(HealingError):
            analyze(request, now=1001)
        request = self.request()
        request["failures"].append(copy.deepcopy(request["failures"][0]))
        with self.assertRaises(HealingError):
            analyze(request, now=1001)

    def test_nonfinite_boolean_zero_and_negative_metrics_rejected(self):
        for field, value in [("baseline_ms", 0), ("baseline_ms", -1), ("current_ms", float("nan")), ("current_ms", float("inf")), ("current_ms", True), ("max_ratio", 0.5), ("current_ms", 10**500)]:
            request = self.request()
            request["performance"][0][field] = value
            with self.assertRaises(HealingError):
                analyze(request, now=1001)

    def test_persistent_failing_tests_still_require_investigation(self):
        request = self.request()
        request.update(baseline_tests={'smoke': 'failed'}, current_tests={'smoke': 'failed'},
                       failures=[], performance=[], dependencies=[])
        result = analyze(request, now=1001)
        self.assertEqual(result['status'], 'review-required')
        self.assertEqual(result['proposals'][0]['kind'], 'investigate-persistent-failure')

    def test_unknown_fields_schema_and_unpinned_dependency_rejected(self):
        for mutation in (lambda r: r.update(schema_version=True), lambda r: r.update(command="run"),
                         lambda r: r["dependencies"][0].update(installed="latest"),
                         lambda r: r["current_tests"].update(smoke="skipped")):
            request = self.request()
            mutation(request)
            with self.assertRaises(HealingError):
                analyze(request, now=1001)

    def test_empty_unbounded_and_duplicate_evidence_rejected(self):
        request = self.request()
        request["baseline_tests"] = {}
        with self.assertRaises(HealingError):
            analyze(request, now=1001)
        request = self.request()
        request["performance"] *= 201
        with self.assertRaises(HealingError):
            analyze(request, now=1001)
        request = self.request()
        request["performance"] *= 2
        with self.assertRaises(HealingError):
            analyze(request, now=1001)


class RepairTests(unittest.TestCase):
    def request(self):
        before = {"app/settings.json": '{"limit":0}\r\n', "app/core.py": "def capacity():\n    return 5\n"}
        after = {**before, "app/settings.json": '{"limit":5}\r\n'}
        return {"schema_version": 1, "project": "synthetic", "baseline_files": before, "candidate_files": after,
                "baseline_sha256": artifact_digest(before), "candidate_sha256": artifact_digest(after),
                "checks": [{"id": "capacity", "kind": "json-value", "path": "app/settings.json", "pointer": ["limit"], "value": 5},
                           {"id": "syntax", "kind": "python-syntax", "path": "app/core.py"}],
                "rollback_checks": [{"id": "rollback", "kind": "sha256", "path": "app/settings.json", "expected": hashlib.sha256(before["app/settings.json"].encode()).hexdigest()}]}

    def rehash(self, request):
        request["baseline_sha256"] = artifact_digest(request["baseline_files"])
        request["candidate_sha256"] = artifact_digest(request["candidate_files"])
        return request

    def test_synthetic_repair_and_exact_crlf_rollback(self):
        request = self.request()
        unchanged = copy.deepcopy(request)
        result = verify_repair(request)
        self.assertEqual(request, unchanged)
        self.assertEqual(result["status"], "artifact-verified-awaiting-runtime-review")
        self.assertTrue(result["artifact_improved"])
        self.assertTrue(result["artifact_checks_passed"])
        self.assertTrue(result["rollback_artifact_verified"])
        self.assertEqual(result["rollback_sha256"], request["baseline_sha256"])
        self.assertFalse(result["runtime_tested"])
        self.assertFalse(result["os_sandbox_claimed"])
        self.assertFalse(result["deployment_allowed"])
        self.assertEqual(result.pop("receipt_sha256"), sha(result))

    def test_candidate_python_is_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = pathlib.Path(directory) / "must-not-exist"
            request = self.request()
            request["candidate_files"]["app/core.py"] = "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('unsafe')\nraise RuntimeError('never execute')\n"
            result = verify_repair(self.rehash(request))
            self.assertTrue(result["artifact_checks_passed"])
            self.assertFalse(result["untrusted_code_executed"])
            self.assertFalse(result["runtime_tested"])
            self.assertFalse(marker.exists())

    def test_bad_candidate_syntax_or_missing_artifact_blocks(self):
        for replacement in ("def broken(:\n", None):
            request = self.request()
            if replacement is None:
                del request["candidate_files"]["app/core.py"]
            else:
                request["candidate_files"]["app/core.py"] = replacement
            result = verify_repair(self.rehash(request))
            self.assertFalse(result["artifact_checks_passed"])
            self.assertEqual(result["status"], "blocked")

    def test_no_improvement_and_bad_rollback_do_not_verify(self):
        request = self.request()
        request["baseline_files"] = dict(request["candidate_files"])
        result = verify_repair(self.rehash(request))
        self.assertFalse(result["artifact_improved"])
        self.assertEqual(result["status"], "blocked")
        request = self.request()
        request["rollback_checks"][0]["expected"] = "0" * 64
        result = verify_repair(request)
        self.assertFalse(result["rollback_artifact_verified"])
        self.assertEqual(result["status"], "blocked")

    def test_changed_artifact_digest_blocks_before_copy(self):
        request = self.request()
        request["candidate_files"]["app/settings.json"] = '{"limit":7}'
        with self.assertRaises(HealingError):
            verify_repair(request)

    def test_digest_is_path_and_byte_sensitive_and_order_independent(self):
        self.assertEqual(artifact_digest({"a": "x", "b": "y"}), artifact_digest({"b": "y", "a": "x"}))
        self.assertNotEqual(artifact_digest({"a": "x"}), artifact_digest({"b": "x"}))
        self.assertNotEqual(artifact_digest({"a": "x\n"}), artifact_digest({"a": "x\r\n"}))

    def test_unsafe_paths_and_directory_collisions_rejected(self):
        for name in ("../escape", "/tmp/escape", "a/../b", ".git/config", "a//b", "a\\b", "./a", "a/./b"):
            with self.subTest(name=name), self.assertRaises(HealingError):
                artifact_digest({name: "safe"})
        with self.assertRaises(HealingError):
            artifact_digest({"a": "safe", "a/b": "safe"})

    def test_credential_shaped_files_and_control_bytes_rejected(self):
        for content in ("ghp_" + "q" * 40, "api_key='" + "z" * 32 + "'", "safe\x00bad"):
            with self.assertRaises(HealingError):
                artifact_digest({"code.py": content})

    def test_size_and_count_limits_rejected(self):
        for files in ({"large": "x" * (64 * 1024 + 1)}, {str(i): "x" for i in range(51)}, {}):
            with self.assertRaises(HealingError):
                artifact_digest(files)

    def test_unknown_empty_and_duplicate_checks_rejected(self):
        for value in ([], [{"id": "unsafe", "kind": "shell", "path": "app/core.py", "command": "anything"}], self.request()["checks"] * 2):
            request = self.request()
            request["checks"] = value
            with self.assertRaises(HealingError):
                verify_repair(request)

    def test_json_type_mismatch_duplicate_keys_and_missing_pointer_fail(self):
        for source in ('{"limit":true}', '{"limit":5,"limit":5}', '{"other":5}', '[5]'):
            request = self.request()
            request["candidate_files"]["app/settings.json"] = source
            self.assertFalse(verify_repair(self.rehash(request))["artifact_checks_passed"])

    def test_list_pointer_and_null_value_work(self):
        request = self.request()
        request["candidate_files"]["app/settings.json"] = '{"values":[null]}'
        request["checks"][0].update(pointer=["values", 0], value=None)
        self.assertTrue(verify_repair(self.rehash(request))["artifact_checks_passed"])


if __name__ == "__main__":
    unittest.main()
