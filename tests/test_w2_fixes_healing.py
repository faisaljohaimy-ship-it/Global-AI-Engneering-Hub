"""Review fix w2-memory-heal-orch H1: a repair that adds a defect is never reported repaired.

Before the fix, VALIDATE ignored its own final detector run: a one-character mutation
made ``test_average`` pass while ``GET /stats`` started returning 500, and heal()
reported ``repaired``. Now CRITIQUE re-runs every detector (runtime ones included) on
each candidate and rejects, then rolls back, one that adds a medium-or-higher finding
or stops a detector from observing the copy; VALIDATE re-checks the same against the
start as a fail-closed backstop, and the ledger never calls a finding resolved when
its detector could not look again. Synthetic targets in temporary directories only.
"""

import hashlib
import json
import pathlib
import tempfile
import textwrap
import unittest
from unittest import mock

from engineering_os import healing
from engineering_os.healing import heal, introduced, verify_receipts

try:  # SEC-07: explicit process-only opt-in where the full sandbox tier is missing (tests/_target_code_mode.py)
    from tests._target_code_mode import opt_in_without_full_tier as setUpModule
except ImportError:  # imported from the tests directory (discover -s tests, layers.verify)
    from _target_code_mode import opt_in_without_full_tier as setUpModule

TESTS = {"start": "tests", "pattern": "test_*.py"}
NOW = 1_800_000_000
POLICY = {"max_iterations": 2, "test_timeout_s": 60}

STATS_APP = '''
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

SAMPLES = {samples}


def average(values):
    return sum(values) / (len(values) + 1)


def label(name):
    return name.strip().title()


def health():
    return 200, {{"ok": True}}


def stats():
    return 200, {{"average": average(SAMPLES)}}


ROUTES = {{"/health": health, "/stats": stats}}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        handler = ROUTES.get(self.path)
        if handler is None:
            self.send_response(404)
            self.end_headers()
            return
        try:
            status, body = handler()
        except Exception:
            status, body = 500, {{"error": "internal"}}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main():
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()


if __name__ == "__main__":
    main()
'''

STATS_TESTS = '''
import unittest
import app


class AppTests(unittest.TestCase):
    def test_average(self):
        self.assertEqual(app.average([2, 4]), 3)

    def test_label(self):
        self.assertEqual(app.label(" ada "), "Ada")
'''

MANIFEST = {"schema_version": 1, "name": "stats-app", "app": {"script": "app.py", "args": ["{port}"], "ready_path": "/health"},
            "entrypoints": ["main"]}

STARTUP_APP = '''
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def strict_mode():
    return False


def health():
    return 200, {"ok": True}


def broken():
    raise RuntimeError("always fails")


ROUTES = {"/health": health, "/broken": broken}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        handler = ROUTES.get(self.path)
        if handler is None:
            self.send_response(404)
            self.end_headers()
            return
        try:
            status, body = handler()
        except Exception:
            status, body = 500, {"error": "internal"}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main():
    if strict_mode():
        raise SystemExit(2)
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()


if __name__ == "__main__":
    main()
'''

STARTUP_TESTS = '''
import unittest
import app


class AppTests(unittest.TestCase):
    def test_strict_mode_is_on(self):
        self.assertTrue(app.strict_mode())
'''

CONTRACTS = {"schema_version": 1, "contracts": [{"id": "ui-health", "consumer": "ui", "interactions": [
    {"request": {"method": "GET", "path": "/health"}, "response": {"status": 200, "json": {"ok": True}}}]}]}


def tree_digest(root):
    root = pathlib.Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def make_target(base, files):
    base = pathlib.Path(base)
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if rel.endswith(".json") else textwrap.dedent(text).lstrip(), encoding="utf-8")
    return base


def stats_target(base, samples):
    return make_target(base, {"app.py": STATS_APP.format(samples=samples), "tests/test_app.py": STATS_TESTS,
                              "healing.json": json.dumps(MANIFEST)})


def accept_without_recheck(self):
    """Stand-in for CRITIQUE's detector re-run that reports the accepted state unchanged."""
    return self.reference_detection


class ScenarioFNewDefect(unittest.TestCase):
    """The reviewer's PoC: the only test-passing candidate makes GET /stats return 500."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="gaie-h1-")
        cls.target = stats_target(pathlib.Path(cls.tmp.name) / "app", "[]  # filled at runtime; empty on a fresh start")
        cls.before = tree_digest(cls.target)
        cls.result = heal(cls.target, workdir=pathlib.Path(cls.tmp.name) / "work", tests=TESTS, now=NOW, policy=POLICY)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_run_is_not_reported_repaired_and_offers_no_patch(self):
        self.assertEqual(self.result["status"], "no-safe-repair")
        self.assertEqual(self.result["repairs"], [])
        self.assertIsNone(self.result["patch"])
        self.assertFalse(self.result["validation"]["passed"])
        self.assertFalse(list(pathlib.Path(self.result["run_dir"]).glob("patch.diff")))

    def test_the_defect_adding_candidate_is_rejected_for_its_new_finding_and_rolled_back(self):
        trial = next(row for row in self.result["trials"] if "'1' -> '0'" in row["candidate"])
        self.assertEqual(trial["full"]["failed"], 0)  # the tests alone would have accepted it
        self.assertEqual(trial["critique"]["reasons"], ["new-finding"])
        self.assertEqual(trial["repair"], "rolled-back")
        self.assertTrue(trial["rollback_verified"])
        new = trial["critique"]["recheck"]["new_findings"]
        self.assertEqual([(row["kind"], row["severity"], row["symbol"]) for row in new], [("api-error-status", "high", "GET /stats")])
        self.assertEqual(trial["critique"]["recheck"]["not_rechecked"], [])
        copy = pathlib.Path(self.result["isolated_copy"]) / "app.py"
        self.assertEqual(copy.read_bytes(), (self.target / "app.py").read_bytes())

    def test_the_ledger_reports_the_failure_unrepaired_and_names_the_new_finding(self):
        ledger = {row["defect"]: row for row in self.result["defects"]}
        row = ledger["test:test_app.AppTests.test_average"]
        self.assertEqual(row["status"], "unrepaired")
        self.assertIn("new-finding", row["reason"])
        self.assertNotIn("repaired", {entry["status"] for entry in self.result["defects"]})

    def test_target_is_unchanged_and_receipts_chain(self):
        self.assertEqual(tree_digest(self.target), self.before)
        self.assertTrue(self.result["target"]["unchanged"])
        self.assertTrue(verify_receipts(self.result["receipts"]))
        self.assertFalse([row for row in self.result["final_findings"] if row["severity"] in ("medium", "high", "critical")])


class ValidateBackstopTests(unittest.TestCase):
    """VALIDATE fails closed on its own final detection even if CRITIQUE let a candidate through."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-h1v-")
        self.base = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_new_final_finding_fails_validation_and_withholds_the_patch(self):
        target = stats_target(self.base / "app", "[]")
        with mock.patch.object(healing._Heal, "recheck", accept_without_recheck):
            result = heal(target, workdir=self.base / "work", tests=TESTS, now=NOW, policy=POLICY)
        self.assertEqual(len(result["repairs"]), 1)
        self.assertEqual(result["status"], "validation-failed")
        validation = result["validation"]
        self.assertFalse(validation["passed"])
        self.assertFalse(validation["checks"]["no_new_findings"])
        self.assertTrue(validation["checks"]["target_tests_pass"])
        self.assertEqual([(row["kind"], row["symbol"]) for row in validation["new_findings"]], [("api-error-status", "GET /stats")])
        self.assertIsNone(result["patch"])
        self.assertIn("+    return sum(values) / (len(values) + 0)", result["rejected_patch"])
        self.assertTrue(result["artifacts"]["patch"].endswith("rejected.diff"))
        introduced_rows = [row for row in result["defects"] if row["status"] == "introduced"]
        self.assertEqual([(row["kind"], row["severity"]) for row in introduced_rows], [("api-error-status", "high")])

    def test_an_app_that_stops_starting_hides_no_finding(self):
        target = make_target(self.base / "start", {"app.py": STARTUP_APP, "tests/test_app.py": STARTUP_TESTS,
                                                    "contracts.json": json.dumps(CONTRACTS),
                                                    "healing.json": json.dumps(dict(MANIFEST, contracts="contracts.json"))})
        with mock.patch.object(healing._Heal, "recheck", accept_without_recheck):
            result = heal(target, workdir=self.base / "work", tests=TESTS, now=NOW, policy=POLICY)
        self.assertEqual([row["description"].split(" (")[0] for row in result["repairs"]], ["return mutation in strict_mode"])
        self.assertEqual(result["status"], "validation-failed")
        validation = result["validation"]
        self.assertEqual([row["kind"] for row in validation["new_findings"]], ["app-start-failed"])
        self.assertEqual(validation["detectors_not_rechecked"], ["integrations"])
        self.assertFalse(validation["checks"]["detectors_rechecked"])
        ledger = {row["kind"]: row for row in result["defects"] if row["type"] == "finding"}
        self.assertEqual(ledger["api-error-status"]["status"], "unrepaired")  # was "resolved-indirectly"
        self.assertIn("not re-checked", ledger["api-error-status"]["reason"])
        self.assertEqual(ledger["app-start-failed"]["status"], "introduced")

    def test_without_the_stand_in_critique_rejects_the_startup_break(self):
        target = make_target(self.base / "start", {"app.py": STARTUP_APP, "tests/test_app.py": STARTUP_TESTS,
                                                    "contracts.json": json.dumps(CONTRACTS),
                                                    "healing.json": json.dumps(dict(MANIFEST, contracts="contracts.json"))})
        result = heal(target, workdir=self.base / "work", tests=TESTS, now=NOW, policy=POLICY)
        self.assertEqual(result["status"], "no-safe-repair")
        trial = next(row for row in result["trials"] if row["strategy"] == "safe-mutation-search")
        self.assertEqual(trial["critique"]["reasons"], ["new-finding", "detector-not-rechecked"])
        self.assertEqual(trial["critique"]["recheck"]["not_rechecked"], ["integrations"])
        self.assertTrue(trial["rollback_verified"])
        ledger = {row["kind"]: row["status"] for row in result["defects"]}
        self.assertEqual(ledger, {"api-error-status": "unrepaired", "failing-test": "unrepaired"})


class GenuineRepairTests(unittest.TestCase):
    def test_a_repair_that_adds_no_defect_is_still_reported_repaired(self):
        with tempfile.TemporaryDirectory(prefix="gaie-h1g-") as scratch:
            target = stats_target(pathlib.Path(scratch) / "app", "[1, 2, 3]")
            result = heal(target, workdir=pathlib.Path(scratch) / "work", tests=TESTS, now=NOW, policy=POLICY)
        self.assertEqual(result["status"], "repaired")
        self.assertTrue(result["validation"]["passed"])
        self.assertTrue(all(result["validation"]["checks"].values()), result["validation"]["checks"])
        self.assertEqual(result["validation"]["new_findings"], [])
        self.assertEqual(result["validation"]["detectors_not_rechecked"], [])
        kept = next(row for row in result["trials"] if row["repair"] == "kept")
        self.assertIn("'1' -> '0'", kept["candidate"])
        self.assertEqual(kept["critique"]["recheck"], {"new_findings": [], "not_rechecked": []})
        self.assertIn("broken-apis", {row["detector"] for row in result["detectors"] if row["status"] == "ran"})
        self.assertEqual({row["status"] for row in result["defects"]}, {"repaired"})


class IntroducedTests(unittest.TestCase):
    @staticmethod
    def row(key, severity, detector="broken-apis", kind="api-error-status"):
        return {"id": f"{kind}-{key}", "key": key, "detector": detector, "kind": kind, "severity": severity,
                "location": {"path": "app.py", "line": None, "symbol": "GET /x"}, "evidence": {"measured": 1.5}}

    def test_only_new_keys_at_medium_or_higher_and_lost_detectors_count(self):
        reference = {"findings": [self.row("k-known", "low")],
                     "detectors": [{"detector": "broken-apis", "status": "ran"}, {"detector": "integrations", "status": "ran"},
                                   {"detector": "memory", "status": "not-configured"}]}
        detection = {"findings": [self.row("k-known", "high"), self.row("k-new", "medium"), self.row("k-new", "high"),
                                  self.row("k-low", "low"), self.row("k-info", "info")],
                     "detectors": [{"detector": "broken-apis", "status": "ran"}, {"detector": "integrations", "status": "skipped"},
                                   {"detector": "memory", "status": "not-configured"}]}
        result = introduced(reference, detection)
        self.assertEqual([row["key"] for row in result["new_findings"]], ["k-new"])
        self.assertNotIn("evidence", result["new_findings"][0])
        self.assertEqual(result["not_rechecked"], ["integrations"])
        self.assertEqual(introduced(reference, reference), {"new_findings": [], "not_rechecked": []})


if __name__ == "__main__":
    unittest.main()
