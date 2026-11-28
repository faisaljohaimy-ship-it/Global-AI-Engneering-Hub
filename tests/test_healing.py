"""Synthetic diagnostics/repair checks; no project or production data."""

import copy
import hashlib
import json
import pathlib
import shutil
import sqlite3
import struct
import tempfile
import textwrap
import time
import unittest
import zlib

from engineering_os import detectors, healing
from engineering_os.healing import HealingError, analyze, artifact_digest, verify_repair
from engineering_os.orchestration import sha

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "healing" / "webapp"


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


class _Workspace(unittest.TestCase):
    """Synthetic targets in a temporary directory (never project data)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gaie-detect-test-")
        self.root = pathlib.Path(self._tmp.name) / "target"
        self.root.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text, mode="w"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "wb":
            path.write_bytes(text)
        else:
            path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
        return path

    def kinds(self, report):
        return sorted(row["kind"] for row in report["findings"])

    def sandbox(self, timeout=60):
        return detectors.Sandbox(pathlib.Path(self._tmp.name) / "sandbox", timeout=timeout)


class StaticDetectorTests(_Workspace):
    def test_route_table_against_handlers_spec_and_internal_links(self):
        self.write("app.py", """
            ROUTES = {("GET", "/"): "home", ("GET", "/items"): "items", ("GET", "/gone"): "gone", ("GET", "/items"): "items"}


            def home(conn, query):
                return 200, "text/html", "<a href='/items'>x</a>"


            def items(conn, query):
                return 200, "application/json", {"items": []}
        """)
        self.write("spec.json", json.dumps({"schema_version": 1, "routes": [
            {"method": "GET", "path": "/", "handler": "home", "response": {"type": "html"}},
            {"method": "GET", "path": "/items", "handler": "items", "response": {"shape": {"items": "list"}}},
            {"method": "GET", "path": "/report", "handler": "report", "response": {}}]}))
        self.write("pages/index.html", '<a href="/items">ok</a> <a href="/nowhere?x=1">bad</a> <img src="/static/logo.png"> <a href="//cdn.example">ext</a>')
        self.write("static/logo.png", b"\x89PNG\r\n\x1a\n", mode="wb")
        report = detectors.detect_broken_routes(self.root, manifest={"schema_version": 1, "route_spec": "spec.json"})
        self.assertEqual(report["status"], "ran")
        self.assertEqual(self.kinds(report), ["broken-internal-link", "duplicate-route", "missing-route-handler", "route-missing-from-table", "undeclared-route"])
        missing = next(row for row in report["findings"] if row["kind"] == "missing-route-handler")
        self.assertEqual((missing["location"]["symbol"], missing["evidence"]["spec_declares"]), ("gone", False))
        link = next(row for row in report["findings"] if row["kind"] == "broken-internal-link")
        self.assertEqual((link["evidence"]["route"], link["location"]["path"]), ("/nowhere", "pages/index.html"))

    def test_clean_route_table_and_missing_table(self):
        self.write("app.py", 'import views\nROUTES = {"/": "home", "/v": "views"}\n\ndef home():\n    return 1\n')
        self.assertEqual(detectors.detect_broken_routes(self.root)["findings"], [])
        self.write("app.py", "ROUTES = build_routes()\n")
        self.assertEqual(detectors.detect_broken_routes(self.root)["status"], "not-configured")

    def test_dead_code_needs_proof_of_no_reference(self):
        self.write("lib.py", """
            import json


            def used():
                return helper_by_name()


            def helper_by_name():
                return 1


            def recursive_orphan(n):
                return recursive_orphan(n - 1) if n else 0


            def named_in_template():
                return 2


            def route_handler():
                return 3


            class Orphan:
                pass


            TABLE = {"/r": "route_handler"}
        """)
        self.write("main.py", "from lib import used\nprint(used())\n")
        self.write("page.html", "<p>{{ named_in_template }}</p>")
        report = detectors.detect_dead_code(self.root)
        self.assertEqual(sorted(row["location"]["symbol"] for row in report["findings"]), ["Orphan", "recursive_orphan"])
        self.assertTrue(all(row["evidence"]["proof"] == "no-static-reference" for row in report["findings"]))
        self.write("loader.py", "import lib\n\ndef load(name):\n    return getattr(lib, name)()\n")
        report = detectors.detect_dead_code(self.root)
        self.assertTrue(report["findings"])
        self.assertTrue(all(row["evidence"]["proof"] == "unproven-dynamic-access" for row in report["findings"]))

    def test_duplicate_components_by_normalized_ast(self):
        body = '''
            def {name}({a}, {b}):
                """{doc}"""
                total = 0
                for item in {a}:
                    if item > {b}:
                        total += item * 2
                return total
        '''
        self.write("one.py", textwrap.dedent(body.format(name="sum_large", a="values", b="limit", doc="First copy.")))
        self.write("two.py", textwrap.dedent(body.format(name="add_big", a="xs", b="floor", doc="Renamed copy.")))
        self.write("three.py", textwrap.dedent(body.format(name="other", a="xs", b="floor", doc="Different.")).replace("* 2", "* 3"))
        report = detectors.detect_duplicates(self.root)
        self.assertEqual(len(report["findings"]), 1)
        members = report["findings"][0]["evidence"]["members"]
        self.assertEqual([m["symbol"] for m in members], ["sum_large", "add_big"])
        self.assertEqual(report["findings"][0]["severity"], "low")

    def test_dependency_pins_against_lock_and_each_other(self):
        self.write("requirements.txt", """
            # comment
            alpha==1.2.0
            Beta_Pkg>=2.0,<3.0
            gamma~=1.4.2
            delta
            epsilon==1.0.0
            -r requirements-dev.txt
        """)
        self.write("requirements-dev.txt", "epsilon==1.1.0\nzeta==0.1.0  # dev only\n")
        self.write("requirements.lock.json", json.dumps({"packages": {
            "alpha": {"version": "1.3.0", "sha256": "a" * 64}, "beta-pkg": {"version": "3.1.0"}, "gamma": {"version": "1.4.9"},
            "delta": {"version": "1.0.0"}, "epsilon": {"version": "1.0.0"}}}))
        report = detectors.detect_dependencies(self.root)
        found = {(row["kind"], row["location"]["symbol"]) for row in report["findings"]}
        self.assertEqual(found, {("pin-lock-mismatch", "alpha"), ("range-violation", "beta-pkg"), ("unpinned-requirement", "delta"),
                                 ("pin-lock-mismatch", "epsilon"), ("conflicting-pins", "epsilon"), ("unlocked-requirement", "zeta")})
        alpha = next(row for row in report["findings"] if row["location"]["symbol"] == "alpha")
        self.assertEqual((alpha["evidence"]["locked"], alpha["evidence"]["lock_has_integrity"]), ("1.3.0", True))
        self.write("requirements.txt", "alpha==1.3.0\n")
        self.write("requirements-dev.txt", "")
        self.assertEqual(detectors.detect_dependencies(self.root)["findings"], [])
        self.write("requirements.txt", "-r ../../outside.txt\n")
        with self.assertRaises(detectors.DetectorError):
            detectors.detect_dependencies(self.root)

    def test_version_ordering_and_specifiers(self):
        key = detectors.version_key
        self.assertLess(key("1.0.0a1"), key("1.0.0rc1"))
        self.assertLess(key("1.0.0rc1"), key("1.0.0"))
        self.assertLess(key("1.0.0"), key("1.0.0.post1"))
        self.assertLess(key("1.0.0.dev1"), key("1.0.0a1"))
        self.assertEqual(key("1.2"), key("1.2.0"))
        self.assertLess(key("1.9"), key("1.10"))
        self.assertIsNone(key("latest"))
        self.assertTrue(detectors.satisfies("1.4.9", "~=", "1.4.2"))
        self.assertFalse(detectors.satisfies("1.5.0", "~=", "1.4.2"))
        self.assertTrue(detectors.satisfies("2.3.1", "==", "2.3.*"))
        self.assertFalse(detectors.satisfies("2.4.0", "==", "2.3.*"))
        self.assertTrue(detectors.satisfies("1.0", "===", "1.0"))
        self.assertIsNone(detectors.satisfies("nightly", ">=", "1.0"))

    def test_security_regressions_are_reported_without_values(self):
        token = "gh" + "p_" + "A1b2C3d4" * 5
        self.write("risky.py", "\n".join([
            "import os, ssl, subprocess, pickle",
            "def run(cmd, blob, url, session):",
            "    eval(cmd)",
            "    exec(cmd)",
            "    subprocess.run(cmd, shell=True)",
            "    os.system(cmd)",
            "    pickle.loads(blob)",
            "    session.get(url, verify=False)",
            "    ctx = ssl._create_unverified_context()",
            "    ctx.check_hostname = False",
            "    return ctx",
            ""]))
        self.write("settings.py", f"GITHUB_TOKEN = '{token}'\n")
        self.write("client.js", "const agent = new https.Agent({ rejectUnauthorized: false });\neval(userInput);\n")
        self.write("deploy.sh", "export NODE_TLS_REJECT_UNAUTHORIZED=0\ncurl -k https://example.invalid/\n")
        self.write("clean.py", "import subprocess\n\ndef ok(args):\n    return subprocess.run(args, shell=False, check=True)\n")
        report = detectors.detect_security(self.root)
        by_file = {}
        for row in report["findings"]:
            by_file.setdefault(row["location"]["path"], set()).add((row["kind"], row["location"]["line"]))
        self.assertNotIn("clean.py", by_file)
        self.assertEqual({kind for kind, _ in by_file["risky.py"]}, {"dynamic-code-execution", "shell-execution", "unsafe-deserialization", "tls-verification-disabled"})
        self.assertEqual(sorted(line for kind, line in by_file["risky.py"] if kind == "tls-verification-disabled"), [8, 9, 10])
        self.assertEqual(by_file["settings.py"], {("hard-coded-secret", 1)})
        self.assertEqual({kind for kind, _ in by_file["client.js"]}, {"tls-verification-disabled", "dynamic-code-execution"})
        self.assertEqual(by_file["deploy.sh"], {("tls-verification-disabled", 1), ("tls-verification-disabled", 2)})
        self.assertNotIn(token, json.dumps(report))
        self.assertEqual(next(r for r in report["findings"] if r["kind"] == "hard-coded-secret")["severity"], "critical")

    def test_security_baseline_marks_only_new_findings_as_regressions(self):
        self.write("legacy.py", "def run(cmd):\n    return eval(cmd)\n")
        first = detectors.detect_security(self.root)
        baseline = [row["evidence"]["fingerprint"] for row in first["findings"]]
        self.assertEqual({row["evidence"]["baseline"] for row in first["findings"]}, {"no-baseline"})
        self.write("legacy.py", "\n\ndef run(cmd):\n    return eval(cmd)\n")
        self.write("new.py", "def run(cmd):\n    exec(cmd)\n")
        second = detectors.detect_security(self.root, baseline=baseline)
        states = {row["location"]["path"]: row["evidence"]["baseline"] for row in second["findings"]}
        self.assertEqual(states, {"legacy.py": "known", "new.py": "new"})

    def test_database_schema_query_and_integrity_smoke(self):
        self.write("schema.sql", "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL);\n")
        self.write("broken.sql", "CREATE TABLE broken (id INTEGER,\n")
        self.write("store.py", """
            def rows(conn, ident):
                good = conn.execute("SELECT id, name FROM items WHERE id = ?", (ident,))
                named = conn.execute("SELECT name FROM items WHERE id = :ident", {"ident": ident})
                bad = conn.execute("SELECT missing_column FROM items")
                worse = conn.execute("SELECT id FROM no_such_table")
                return good, named, bad, worse
        """)
        valid = self.root / "valid.db"
        conn = sqlite3.connect(valid)
        conn.execute("CREATE TABLE t (x)")
        conn.commit()
        conn.close()
        before = valid.read_bytes()
        self.write("corrupt.sqlite", b"this is not a database" * 50, mode="wb")
        report = detectors.detect_database(self.root, manifest={"database": {"schema": ["schema.sql", "broken.sql"]}})
        self.assertEqual(self.kinds(report), ["database-integrity", "query-error", "query-error", "schema-error"])
        errors = sorted(row["evidence"]["error"] for row in report["findings"] if row["kind"] == "query-error")
        self.assertTrue(any("missing_column" in e for e in errors) and any("no_such_table" in e for e in errors))
        self.assertEqual(next(r for r in report["findings"] if r["kind"] == "database-integrity")["location"]["path"], "corrupt.sqlite")
        self.assertEqual(valid.read_bytes(), before)
        self.write("broken.sql", "-- fixed\n")
        (self.root / "corrupt.sqlite").unlink()
        self.write("store.py", 'Q = "SELECT id FROM items"\n')
        self.assertEqual(detectors.detect_database(self.root, manifest={"database": {"schema": ["schema.sql"]}})["findings"], [])

    def png(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))

    def test_media_signatures_and_honest_skip_without_ffprobe(self):
        self.write("ok.png", self.png(), mode="wb")
        self.write("clip.mp4", b"not a video", mode="wb")
        report = detectors.detect_media(self.root, ffprobe=None)
        self.assertEqual(report["status"], "partial")
        self.assertIn("ffprobe not available", report["reason"])
        self.assertEqual(report["decode_checked"], 0)
        self.assertEqual([(r["kind"], r["location"]["path"]) for r in report["findings"]], [("media-signature-mismatch", "clip.mp4")])
        (self.root / "clip.mp4").unlink()
        (self.root / "ok.png").unlink()
        self.assertEqual(detectors.detect_media(self.root, ffprobe=None)["status"], "ran")

    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe not installed")
    def test_media_decoding_with_ffprobe(self):
        self.write("ok.png", self.png(), mode="wb")
        self.write("bad.png", b"\x89PNG\r\n\x1a\n" + b"garbage" * 10, mode="wb")
        report = detectors.detect_media(self.root)
        self.assertEqual(report["status"], "ran")
        self.assertEqual(report["decode_checked"], 2)
        self.assertEqual([(r["kind"], r["location"]["path"]) for r in report["findings"]], [("broken-media", "bad.png")])

    def test_runtime_detectors_never_run_without_runtime_flag(self):
        self.write("marker.py", "import pathlib\npathlib.Path(__file__).with_name('EXECUTED').write_text('x')\ndef f():\n    return 1\n")
        self.write("app.py", "import marker\nROUTES = {}\n")
        self.write("healing.json", json.dumps({"schema_version": 1, "app": {"script": "app.py"},
                                               "memory": [{"module": "marker", "function": "f", "calls": 10, "threshold_bytes": 4096}]}))
        result = detectors.run_all(self.root)
        statuses = {r["detector"]: r["status"] for r in result["detectors"]}
        self.assertEqual({statuses[name] for name in detectors.RUNTIME}, {"skipped"})
        self.assertFalse(result["runtime_executed"])
        self.assertFalse((self.root / "EXECUTED").exists())
        self.assertEqual([r["detector"] for r in result["detectors"]], list(detectors.DETECTORS))

    def test_manifest_and_spec_validation_fail_closed(self):
        bad_manifests = [
            {"schema_version": 2}, {"schema_version": 1, "unknown": True},
            {"schema_version": 1, "app": {"script": "/abs/app.py"}},
            {"schema_version": 1, "app": {"script": "app.py", "args": ["{cmd}"]}},
            {"schema_version": 1, "route_spec": "../routes.json"},
            {"schema_version": 1, "memory": [{"module": "m", "function": "f", "calls": 10 ** 9, "threshold_bytes": 4096}]},
            {"schema_version": 1, "memory": [{"module": "os; rm", "function": "f", "calls": 10, "threshold_bytes": 4096}]},
            {"schema_version": 1, "dependencies": {"requirements": ["a/../../b.txt"]}},
        ]
        for manifest in bad_manifests:
            with self.subTest(manifest=manifest), self.assertRaises(detectors.DetectorError):
                detectors.validate_manifest(manifest, self.root)
        self.write("healing.json", '{"schema_version": 1, "name": "a", "name": "b"}')
        with self.assertRaises(detectors.DetectorError):
            detectors.load_manifest(self.root)
        for route in ({"method": "GET", "path": "/a", "handler": "a", "response": {}, "implementation": {"template": "shell"}},
                      {"method": "GET", "path": "/a", "handler": "a", "response": {}, "probe": "/b?x=1"},
                      {"method": "TRACE", "path": "/a", "handler": "a", "response": {}},
                      {"method": "GET", "path": "/a", "handler": "a-b", "response": {}}):
            self.write("routes.json", json.dumps({"schema_version": 1, "routes": [route]}))
            with self.subTest(route=route), self.assertRaises(detectors.DetectorError):
                detectors.load_route_spec(self.root, "routes.json")
        self.write("contracts.json", json.dumps({"schema_version": 1, "contracts": [{"id": "c", "consumer": "x", "interactions": [
            {"request": {"method": "GET", "path": "http://example.invalid/"}, "response": {"status": 200}}]}]}))
        with self.assertRaises(detectors.DetectorError):
            detectors.load_contracts(self.root, "contracts.json")


class SandboxDetectorTests(_Workspace):
    def test_network_guard_allows_only_loopback_and_env_is_minimal(self):
        self.write("suite/case_net.py", """
            import os
            import socket
            import unittest


            class Net(unittest.TestCase):
                def test_external_connect_refused(self):
                    with self.assertRaises(PermissionError):
                        socket.create_connection(("192.0.2.1", 9), timeout=1)

                def test_raw_connect_refused(self):
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        with self.assertRaises(PermissionError):
                            sock.connect(("192.0.2.1", 9))
                    finally:
                        sock.close()

                def test_dns_refused(self):
                    with self.assertRaises(PermissionError):
                        socket.getaddrinfo("example.invalid", 80)

                def test_udp_refused(self):
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    try:
                        with self.assertRaises(PermissionError):
                            sock.sendto(b"x", ("192.0.2.1", 9))
                    finally:
                        sock.close()

                def test_loopback_allowed(self):
                    server = socket.socket()
                    server.bind(("127.0.0.1", 0))
                    server.listen(1)
                    try:
                        socket.create_connection(server.getsockname(), timeout=2).close()
                    finally:
                        server.close()

                def test_environment_is_minimal(self):
                    for name in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "PYTHONPATH"):
                        self.assertNotIn(name, os.environ)
                    self.assertEqual(os.environ["PYTHONHASHSEED"], "0")
        """)
        result = self.sandbox().run_tests(self.root, "suite", "case_*.py")
        self.assertEqual(result["status"], "ok", result.get("log_tail"))
        self.assertEqual(len(result["tests"]), 6)
        self.assertEqual(set(result["tests"].values()), {"passed"}, result["details"])

    def test_timeouts_kill_the_run(self):
        self.write("suite/case_slow.py", "import time\nimport unittest\n\nclass Slow(unittest.TestCase):\n    def test_hang(self):\n        time.sleep(120)\n")
        started = time.monotonic()
        result = self.sandbox().run_tests(self.root, "suite", "case_*.py", timeout=2)
        self.assertEqual(result["status"], "timeout")
        self.assertLess(time.monotonic() - started, 30)

    def test_memory_growth_is_found_only_for_a_leak(self):
        self.write("leaky.py", "_CACHE = []\n\ndef leak(n):\n    _CACHE.append(bytearray(n))\n    return len(_CACHE)\n\ndef steady(n):\n    return len(bytearray(n))\n")
        manifest = {"memory": [{"module": "leaky", "function": "leak", "args": [512], "calls": 500, "threshold_bytes": 65536},
                               {"module": "leaky", "function": "steady", "args": [512], "calls": 500, "threshold_bytes": 65536}]}
        report = detectors.detect_memory(self.root, manifest, sandbox=self.sandbox())
        self.assertEqual([(r["kind"], r["location"]["symbol"]) for r in report["findings"]], [("memory-growth", "leaky:leak")])
        evidence = report["findings"][0]["evidence"]
        self.assertGreater(evidence["growth_bytes"], 65536)
        self.assertTrue(all(delta > 0 for delta in evidence["round_deltas"]))
        self.assertEqual(report["findings"][0]["location"]["path"], "leaky.py")
        self.assertEqual(detectors.detect_memory(self.root, {}, sandbox=self.sandbox())["status"], "not-configured")

    def test_performance_regression_against_stored_baseline(self):
        self.write("work.py", "import time\n\ndef slow():\n    time.sleep(0.004)\n\ndef fast():\n    return 1\n")
        self.write("perf.json", json.dumps({"schema_version": 1, "functions": {
            "work:slow": {"median_ms": 0.01, "tolerance": 2, "repeats": 3, "number": 2},
            "work:fast": {"median_ms": 50.0, "tolerance": 2, "repeats": 3, "number": 10}}}))
        report = detectors.detect_performance(self.root, {"performance": {"baseline": "perf.json"}}, sandbox=self.sandbox())
        self.assertEqual([(r["kind"], r["location"]["symbol"]) for r in report["findings"]], [("performance-regression", "work:slow")])
        self.assertGreater(report["findings"][0]["evidence"]["ratio"], 2)
        self.assertIn("measured", report["method"])
        self.assertEqual({row["function"] for row in report["measured"]}, {"work:slow", "work:fast"})

    def test_app_that_cannot_start_is_a_critical_finding(self):
        self.write("app.py", "import sys\nsys.exit(3)\n")
        manifest = {"schema_version": 1, "app": {"script": "app.py", "startup_timeout_s": 5}}
        apis, integrations = detectors.detect_http(self.root, None, manifest, sandbox=self.sandbox())
        self.assertEqual([(r["kind"], r["severity"], r["evidence"]["exit_code"]) for r in apis["findings"]], [("app-start-failed", "critical", 3)])
        self.assertEqual(integrations["status"], "skipped")

    def test_contract_runner_catches_value_and_status_mismatches(self):
        target = pathlib.Path(self._tmp.name) / "webapp"
        shutil.copytree(FIXTURE, target)
        contracts = json.loads((target / "contracts.json").read_text())
        contracts["contracts"][1]["interactions"][0]["response"]["json"] = {"total": 9999}
        (target / "contracts.json").write_text(json.dumps(contracts))
        apis, integrations = detectors.detect_http(target, None, detectors.load_manifest(target), sandbox=self.sandbox())
        self.assertEqual([(r["evidence"]["route"], r["evidence"]["status"]) for r in apis["findings"]], [("/api/items/count", 500)])
        problems = {r["evidence"]["contract"]: r["evidence"]["problems"] for r in integrations["findings"]}
        self.assertEqual(problems["checkout-quote"], ["json-mismatch"])
        self.assertIn("status:500", problems["storefront-catalogue"])
        self.assertEqual(integrations["interactions"], 3)


class RepairPrimitiveTests(unittest.TestCase):
    def test_patch_round_trip_including_missing_final_newline(self):
        before, after = "keep\nold\ntail", "keep\nnew\ntail\nmore"
        patch = healing._diff("a.txt", before.encode(), after.encode())
        self.assertIn("\\ No newline at end of file", patch)
        self.assertEqual(healing.apply_patch({"a.txt": before}, patch), {"a.txt": after})
        reverse = healing._diff("a.txt", after.encode(), before.encode())
        self.assertEqual(healing.apply_patch({"a.txt": after}, reverse), {"a.txt": before})

    def test_patch_refuses_mismatched_context_and_malformed_input(self):
        patch = healing._diff("a.txt", b"one\ntwo\n", b"one\nthree\n")
        for files, text in (({"a.txt": "one\nchanged\n"}, patch), ({}, patch), ({"a.txt": "one\ntwo\n"}, "garbage\n"),
                            ({"a.txt": "one\ntwo\n"}, patch.replace("@@ -1,2 +1,2 @@", "@@ -1,2 +1,9 @@"))):
            with self.subTest(text=text[:30]), self.assertRaises(HealingError):
                healing.apply_patch(files, text)

    def test_mutation_candidates_are_deterministic_minimal_and_parse(self):
        source = textwrap.dedent('''
            def limit(x, flag):
                # keep this comment
                if x > 1 and not flag:
                    return x + 1
                return False


            def untouched(y):
                return y < 3
        ''').lstrip()
        first = list(healing.mutation_candidates(source, "limit", 1))
        self.assertEqual(first, list(healing.mutation_candidates(source, "limit", 1)))
        kinds = [row["kind"] for row in first]
        self.assertEqual(kinds, sorted(kinds, key=healing._KIND_ORDER.get))
        self.assertTrue({"compare", "binop", "boolop", "not", "return", "int"} <= set(kinds))
        for row in first:
            healing.ast.parse(row["source"])
            changed = [i for i, (a, b) in enumerate(zip(source.splitlines(), row["source"].splitlines())) if a != b]
            self.assertEqual(len(changed), 1, row)
            self.assertIn("# keep this comment", row["source"])
            self.assertIn("return y < 3", row["source"])
        self.assertEqual(first[0]["before"], "x > 1")
        self.assertEqual(first[0]["after"], "x >= 1")
        self.assertEqual(list(healing.mutation_candidates(source, "absent", 1)), [])

    def test_handler_templates_refuse_unsafe_specs(self):
        spec = {"handler_convention": detectors.CONVENTION}
        good = {"method": "GET", "path": "/n", "handler": "count_rows", "response": {"shape": {"count": "int"}},
                "implementation": {"template": "sql-scalar", "query": "SELECT COUNT(*) FROM t", "field": "count"}}
        code = healing.handler_source(good, spec)
        self.assertIn("def count_rows(conn, query):", code)
        rows = dict(good, implementation={"template": "sql-rows", "query": "SELECT a, b FROM t", "field": "rows"}, response={"shape": {"rows": "list"}})
        self.assertIn("cursor.fetchall()", healing.handler_source(rows, spec))
        static = dict(good, implementation={"template": "static-json", "body": {"count": 0}})
        self.assertIn("{'count': 0}", healing.handler_source(static, spec))
        bad = [
            (dict(good, implementation={"template": "sql-scalar", "query": "SELECT 1; DROP TABLE t", "field": "count"}), spec),
            (dict(good, implementation={"template": "sql-scalar", "query": "DELETE FROM t", "field": "count"}), spec),
            (dict(good, implementation={"template": "sql-scalar", "query": "SELECT a FROM t WHERE b = ?", "field": "count"}), spec),
            (dict(good, implementation={"template": "sql-scalar", "query": "SELECT a FROM t", "field": "other"}), spec),
            (dict(good, handler="class"), spec), (dict(good, response={"type": "html"}), spec),
            ({k: v for k, v in good.items() if k != "implementation"}, spec), (good, {"handler_convention": "django"}),
            (dict(good, implementation={"template": "static-json", "body": {"count": "x" * 3000}}), spec),
        ]
        for route, declared in bad:
            with self.subTest(route=route.get("implementation"), handler=route["handler"]), self.assertRaises(HealingError):
                healing.handler_source(route, declared)
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, "schema.sql").write_text("CREATE TABLE t (a INTEGER);\n")
            with self.assertRaises(HealingError):
                healing.handler_source(dict(good, implementation={"template": "sql-scalar", "query": "SELECT COUNT(*) FROM missing", "field": "count"}),
                                       spec, root=pathlib.Path(directory), schemas=["schema.sql"])

    def test_receipt_chain_rejects_tampering_reordering_and_emptiness(self):
        def receipt(stage, previous):
            row = {"stage": stage, "iteration": 1, "status": "ok", "input_sha256": "a" * 64, "output_sha256": "b" * 64,
                   "source_sha256": "c" * 64, "side_effect": "none", "at": "2027-01-15T08:00:00Z", "previous_sha256": previous}
            row["receipt_sha256"] = sha(row)
            return row
        first = receipt("DISCOVER", "0" * 64)
        second = receipt("ANALYZE", first["receipt_sha256"])
        self.assertTrue(healing.verify_receipts([first, second]))
        self.assertFalse(healing.verify_receipts([second, first]))
        self.assertFalse(healing.verify_receipts([]))
        self.assertFalse(healing.verify_receipts([dict(first, stage="DEPLOY")]))
        self.assertFalse(healing.verify_receipts([first, dict(second, status="forged")]))


if __name__ == "__main__":
    unittest.main()
