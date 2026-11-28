"""Follow-up fixes recheck-w2-heal (a, b): finding identities that stay stable when lines move.

(a) The database query-error key included the line number (symbol ``sql@<line>``), so a
genuine repair that inserted lines above an unrelated broken SQL literal was rejected by
CRITIQUE as ``new-finding``. The key is now built from the file, the whitespace-normalised
statement and the error class; a different broken statement is still a new finding.

(b) Two identical TLS-disabled lines in one file share one key and one fingerprint, so the
reviewer's V7 mutation (``verify=1`` -> ``verify=0`` next to a flagged
``fetch(url, verify=0)``) added a second high instance that both the security baseline and
the recheck read as known. The security baseline is now a multiset (one occurrence per
instance) and ``introduced`` compares instance counts per key.

Synthetic targets in temporary directories only; the Scenario F fixture is copied, never written.
"""

import pathlib
import shutil
import tempfile
import unittest

from engineering_os import detectors, healing
from engineering_os.healing import heal, introduced

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "healing" / "webapp"
TESTS = {"start": "suite", "pattern": "case_*.py"}
NOW = 1_800_000_000
SCHEMA = "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL);\n"
AUDIT = 'def audit(conn):\n    return conn.execute("SELECT missing_column FROM items").fetchall()\n\n\n'


try:  # SEC-07: explicit process-only opt-in where the full sandbox tier is missing (tests/_target_code_mode.py)
    from tests._target_code_mode import opt_in_without_full_tier as setUpModule
except ImportError:  # imported from the tests directory (discover -s tests, layers.verify)
    from _target_code_mode import opt_in_without_full_tier as setUpModule


def database(root, files):
    root = pathlib.Path(root)
    shutil.rmtree(root, ignore_errors=True)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    report = detectors.detect_database(root)
    return {"detectors": [report], "findings": report["findings"]}


class QueryErrorKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-hf2-")
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name) / "t"

    def scan(self, store):
        return database(self.root, {"schema.sql": SCHEMA, "store.py": store})

    def test_moving_a_broken_literal_keeps_its_key(self):
        before = self.scan('def audit(conn):\n    return conn.execute("SELECT missing_column FROM items")\n')
        after = self.scan("\n\n\n\n\n\ndef audit(conn):\n    return conn.execute(\"SELECT missing_column FROM items\")\n")
        [old], [new] = before["findings"], after["findings"]
        self.assertEqual((old["kind"], old["location"]["line"], new["location"]["line"]), ("query-error", 2, 8))
        self.assertEqual(old["key"], new["key"])
        self.assertRegex(old["location"]["symbol"], r"^sql:[0-9a-f]{16}$")
        self.assertEqual(old["location"]["symbol"], new["location"]["symbol"])
        self.assertEqual(new["evidence"]["error_class"], "OperationalError")
        self.assertEqual(introduced(before, after)["new_findings"], [])

    def test_whitespace_only_differences_keep_the_key(self):
        one = self.scan('Q = "SELECT missing_column FROM items"\n')
        two = self.scan('Q = """SELECT  missing_column\n    FROM items;"""\n')
        self.assertEqual(one["findings"][0]["key"], two["findings"][0]["key"])

    def test_a_new_broken_statement_is_still_a_new_finding(self):
        before = self.scan('A = "SELECT missing_column FROM items"\n')
        after = self.scan('A = "SELECT missing_column FROM items"\nB = "SELECT id FROM no_such_table"\n')
        self.assertEqual(len(after["findings"]), 2)
        new = introduced(before, after)["new_findings"]
        self.assertEqual([(row["kind"], row["severity"], row["path"]) for row in new], [("query-error", "high", "store.py")])
        self.assertNotEqual(new[0]["key"], before["findings"][0]["key"])

    def test_the_same_statement_in_another_file_is_a_different_finding(self):
        before = self.scan('A = "SELECT missing_column FROM items"\n')
        after = database(self.root, {"schema.sql": SCHEMA, "store.py": 'A = "SELECT missing_column FROM items"\n',
                                     "report.py": 'B = "SELECT missing_column FROM items"\n'})
        self.assertEqual([row["path"] for row in introduced(before, after)["new_findings"]], ["report.py"])

    def test_a_different_error_class_is_a_different_key(self):
        error = detectors.sqlite3.OperationalError("x")
        self.assertNotEqual(detectors.sql_fingerprint("SELECT 1", error), detectors.sql_fingerprint("SELECT 1", ValueError("x")))
        self.assertEqual(detectors.sql_fingerprint("SELECT 1;", error), detectors.sql_fingerprint(" SELECT   1 ", error))


class MovedLiteralRepairTests(unittest.TestCase):
    """The reviewer's L-sql case: Scenario F plus an unrelated broken SQL literal below the point where
    the restored route handler is inserted (it moves from line 64 to line 70)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="gaie-hf2-sql-")
        base = pathlib.Path(cls.tmp.name)
        target = base / "target"
        shutil.copytree(FIXTURE, target, ignore=shutil.ignore_patterns("__pycache__"))
        app = (target / "app.py").read_text(encoding="utf-8")
        marker = "class Handler(BaseHTTPRequestHandler):"
        assert app.count(marker) == 1
        (target / "app.py").write_text(app.replace(marker, AUDIT + marker), encoding="utf-8")
        cls.result = heal(target, workdir=base / "work", tests=TESTS, now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_genuine_route_repair_is_kept_and_reported_repaired(self):
        result = self.result
        route = [row for row in result["trials"] if row["strategy"] == "restore-route-handler"]
        self.assertEqual([row["repair"] for row in route], ["kept"])
        self.assertEqual(route[0]["critique"]["recheck"]["new_findings"], [])
        self.assertTrue(result["validation"]["passed"], result["validation"]["checks"])
        ledger = {row["kind"]: row["status"] for row in result["defects"] if row["type"] == "finding"}
        self.assertEqual(ledger["missing-route-handler"], "repaired")
        self.assertEqual(ledger["api-error-status"], "repaired")
        self.assertEqual(ledger["contract-failed"], "repaired")
        self.assertEqual(result["validation"]["final_failing"], [])

    def test_the_unrelated_broken_literal_moved_and_stays_one_unrepaired_finding(self):
        start = [row for row in self.result["findings"] if row["kind"] == "query-error"]
        final = [row for row in self.result["final_findings"] if row["kind"] == "query-error"]
        self.assertEqual(len(start), 1)
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["location"]["line"] - start[0]["location"]["line"], 6)
        self.assertEqual(start[0]["key"], final[0]["key"])
        query = [row for row in self.result["defects"] if row["kind"] == "query-error"]
        self.assertEqual([row["status"] for row in query], ["unrepaired"])
        self.assertEqual(self.result["status"], "partially-repaired")
        self.assertEqual(self.result["validation"]["new_findings"], [])


V7_LIB = """
def fetch(url, verify=True, timeout=5):
    return {"url": url, "verify": verify, "timeout": timeout}


def legacy(url):
    return fetch(url, verify=0)


def modern(url):
    return fetch(url, verify=1)
"""
V7_TEST = """import unittest
import lib


class T(unittest.TestCase):
    def test_modern_matches_the_legacy_profile(self):
        self.assertEqual(lib.modern("u"), {"url": "u", "verify": 0, "timeout": 5})
"""


def write(root, files):
    root = pathlib.Path(root)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


class InstanceCountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-hf2-")
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def security(self, name, source, baseline=None):
        report = detectors.detect_security(write(self.root / name, {"lib.py": source}), baseline=baseline)
        return {"detectors": [report], "findings": report["findings"]}

    def test_a_second_identical_tls_line_is_new_against_the_baseline(self):
        before = self.security("one", V7_LIB)
        [row] = before["findings"]
        baseline = [r["evidence"]["fingerprint"] for r in before["findings"]]
        after = self.security("two", V7_LIB.replace("verify=1", "verify=0"), baseline)
        self.assertEqual([(r["location"]["line"], r["evidence"]["fingerprint"] == row["evidence"]["fingerprint"])
                          for r in after["findings"]], [(7, True), (11, True)])
        self.assertEqual([r["evidence"]["baseline"] for r in after["findings"]], ["known", "new"])
        # one baseline entry per instance: two listed occurrences cover two identical lines
        both = self.security("three", V7_LIB.replace("verify=1", "verify=0"), baseline * 2)
        self.assertEqual([r["evidence"]["baseline"] for r in both["findings"]], ["known", "known"])

    def test_introduced_counts_instances_per_key(self):
        before = self.security("one", V7_LIB)
        after = self.security("two", V7_LIB.replace("verify=1", "verify=0"))
        self.assertEqual(len({r["key"] for r in after["findings"]}), 1)
        new = introduced(before, after)["new_findings"]
        self.assertEqual([(r["kind"], r["severity"], r["instances"], r["previously"]) for r in new],
                         [("tls-verification-disabled", "high", 2, 1)])
        self.assertEqual(introduced(after, after)["new_findings"], [])
        self.assertEqual(introduced(after, before)["new_findings"], [])  # fewer instances is not new

    def test_the_ledger_row_is_the_added_instance(self):
        before = self.security("one", V7_LIB)
        after = self.security("two", V7_LIB.replace("verify=1", "verify=0"))
        rows = healing._introduced_rows(before, after, introduced(before, after)["new_findings"])
        self.assertEqual([r["location"]["line"] for r in rows], [11])


class TlsInstanceHealTests(unittest.TestCase):
    """The reviewer's V7 target end to end: the only test-passing mutation adds the second instance."""

    def test_the_second_high_instance_is_rejected_and_no_patch_is_offered(self):
        with tempfile.TemporaryDirectory(prefix="gaie-hf2-v7-") as scratch:
            target = write(pathlib.Path(scratch) / "t", {"lib.py": V7_LIB, "tests/test_lib.py": V7_TEST})
            result = heal(target, workdir=pathlib.Path(scratch) / "w", tests={"start": "tests", "pattern": "test_*.py"},
                          now=NOW, policy={"max_iterations": 2, "test_timeout_s": 60})
        trial = next(row for row in result["trials"] if "'1' -> '0'" in row["candidate"])
        self.assertEqual(trial["repair"], "rolled-back")
        self.assertIn("new-security-finding", trial["critique"]["reasons"])
        self.assertTrue(trial["rollback_verified"])
        self.assertEqual(result["status"], "no-safe-repair")
        self.assertIsNone(result["patch"])
        self.assertEqual(len([r for r in result["final_findings"] if r["kind"] == "tls-verification-disabled"]), 1)
        ledger = {row["kind"]: row["status"] for row in result["defects"]}
        self.assertEqual(ledger, {"tls-verification-disabled": "unrepaired", "failing-test": "unrepaired"})


if __name__ == "__main__":
    unittest.main()
