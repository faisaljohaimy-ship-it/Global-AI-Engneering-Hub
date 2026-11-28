"""Follow-up fix recheck-w2-heal (c): every introduced finding is listed; the report names its sandbox tier.

Rejection stays at medium and above, but a candidate that adds a lower finding was invisible:
in the reviewer's V4 case the only test-passing mutation made ``scale_b`` an AST duplicate of
``scale_a`` (duplicate-component, low), and neither the validation nor the ledger mentioned it.
VALIDATE now lists every introduced finding (``introduced_findings``, with ``blocking``) and the
ledger has an ``introduced`` row for each; only medium-or-higher rows count as remaining.

heal() reports also said "not an OS sandbox" and ``os_sandbox_claimed: false`` whatever tier ran
the target code. The report now carries ``sandbox`` (``Sandbox.summary()``: mode, runs per tier,
``os_sandbox``), and ``guarantees`` and ``limits`` follow it.

Synthetic targets in temporary directories only.
"""

import os
import pathlib
import tempfile
import textwrap
import unittest
from unittest import mock

from engineering_os import detectors, governor
from engineering_os.healing import HealingError, heal, introduced

TESTS = {"start": "tests", "pattern": "test_*.py"}
NOW = 1_800_000_000
POLICY = {"max_iterations": 2, "test_timeout_s": 60}
PLAIN_TIER = {"tier": "plain", "root_netns": False, "userns_netns": False, "unshare": True, "root": False, "full_checks": None}

V4_LIB = '''
def scale_a(values, factor):
    out = []
    for value in values:
        if value is not None:
            out.append(value * factor + 1)
    return out


def scale_b(values, factor):
    out = []
    for value in values:
        if value is not None:
            out.append(value * factor + 2)
    return out
'''
V4_TESTS = '''
import unittest
import lib


class T(unittest.TestCase):
    def test_a(self):
        self.assertEqual(lib.scale_a([1, None, 2], 3), [4, 7])

    def test_b(self):
        self.assertEqual(lib.scale_b([1, None, 2], 3), [4, 7])
'''
PLAIN_LIB = "def double(n):\n    return n * 2\n"
PLAIN_TESTS = "import unittest\nimport lib\n\n\nclass T(unittest.TestCase):\n    def test_double(self):\n        self.assertEqual(lib.double(4), 8)\n"


def setUpModule():
    """Same opt-in as tests/test_healing.py: the full sandbox tier, or the audited process-only mode."""
    if governor.isolation_probe()["tier"] == "full":
        return
    if os.environ.get("GAIE_REQUIRE_FULL_SANDBOX") == "1":
        raise AssertionError("GAIE_REQUIRE_FULL_SANDBOX=1 but the governor's full sandbox tier is missing")
    patcher = mock.patch.object(detectors, "DEFAULT_ISOLATION", "process-only")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def run_heal(lib, tests):
    with tempfile.TemporaryDirectory(prefix="gaie-hf2c-") as scratch:
        target = pathlib.Path(scratch) / "t"
        (target / "tests").mkdir(parents=True)
        (target / "lib.py").write_text(textwrap.dedent(lib).lstrip(), encoding="utf-8")
        (target / "tests" / "test_lib.py").write_text(textwrap.dedent(tests).lstrip(), encoding="utf-8")
        return heal(target, workdir=pathlib.Path(scratch) / "w", tests=TESTS, now=NOW, policy=POLICY)


class SubThresholdFindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_heal(V4_LIB, V4_TESTS)

    def test_the_candidate_is_still_accepted_at_the_medium_threshold(self):
        result = self.result
        self.assertEqual(result["status"], "repaired")
        self.assertTrue(result["validation"]["passed"], result["validation"]["checks"])
        self.assertEqual(result["validation"]["new_findings"], [])
        self.assertIsNotNone(result["patch"])
        self.assertEqual([row["repair"] for row in result["trials"] if row["repair"] == "kept"], ["kept"])

    def test_the_introduced_low_finding_is_listed_in_validation(self):
        listed = self.result["validation"]["introduced_findings"]
        self.assertEqual([(row["kind"], row["severity"], row["blocking"], row["instances"], row["previously"]) for row in listed],
                         [("duplicate-component", "low", False, 1, 0)])
        final = {row["key"] for row in self.result["final_findings"] if row["kind"] == "duplicate-component"}
        self.assertEqual({row["key"] for row in listed}, final)

    def test_the_ledger_has_an_introduced_row_that_does_not_block(self):
        rows = [row for row in self.result["defects"] if row["status"] == "introduced"]
        self.assertEqual([(row["kind"], row["severity"], row["location"]["symbol"]) for row in rows],
                         [("duplicate-component", "low", "scale_a")])
        self.assertIn("below the medium rejection threshold", rows[0]["reason"])
        self.assertEqual({row["status"] for row in self.result["defects"] if row["type"] == "test"}, {"repaired"})

    def test_section_3_documents_the_recheck_the_validate_checks_and_the_ledger(self):
        """recheck-w2-heal (d): SELF_HEALING.md section 3 names what the loop now checks and reports."""
        text = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "specs" / "gaie-20-layers" / "SELF_HEALING.md").read_text(encoding="utf-8")
        loop = text[text.index("## 3. The governed loop"):text.index("## 4. Guarantees")]
        for name in ("no_new_findings", "detectors_rechecked", "targeted_findings_resolved"):
            self.assertIn(name, self.result["validation"]["checks"])
            self.assertIn(f"`{name}`", loop)
        for word in ("`new-finding`", "`detector-not-rechecked`", "re-checked by every", "`introduced`", "`introduced_findings`",
                     "`blocking`", "form feed"):
            self.assertIn(word, loop)
        statuses = {row["status"] for row in self.result["defects"]}
        self.assertTrue(statuses <= {"repaired", "resolved-indirectly", "unrepaired", "introduced"})


class IntroducedThresholdTests(unittest.TestCase):
    @staticmethod
    def row(key, severity):
        return {"id": f"x-{key}-{severity}", "key": key, "detector": "duplicates", "kind": "duplicate-component", "severity": severity,
                "location": {"path": "lib.py", "line": 1, "symbol": "f"}, "evidence": {}}

    def test_minimum_selects_the_listed_severities(self):
        reference = {"findings": [], "detectors": []}
        detection = {"findings": [self.row("a", "low"), self.row("b", "info"), self.row("c", "high")], "detectors": []}
        self.assertEqual([row["key"] for row in introduced(reference, detection)["new_findings"]], ["c"])
        self.assertEqual([row["key"] for row in introduced(reference, detection, minimum="info")["new_findings"]], ["c", "a", "b"])
        with self.assertRaises(HealingError):
            introduced(reference, detection, minimum="severe")


class SandboxTierReportTests(unittest.TestCase):
    def check(self, result, mode, tiers, os_sandbox, guard, phrase):
        self.assertEqual(result["sandbox"]["mode"], mode)
        self.assertEqual(set(result["sandbox"]["tiers"]), tiers)
        self.assertTrue(all(count > 0 for count in result["sandbox"]["tiers"].values()))
        self.assertIs(result["sandbox"]["os_sandbox"], os_sandbox)
        self.assertIs(result["guarantees"]["os_sandbox_claimed"], os_sandbox)
        self.assertEqual(result["guarantees"]["network_guard"], guard)
        self.assertIn(phrase, result["limits"])

    def test_the_default_records_the_tier_this_host_provides(self):
        result = run_heal(PLAIN_LIB, PLAIN_TESTS)
        self.assertEqual(result["status"], "no-defects-found")
        if governor.isolation_probe()["tier"] == "full":
            self.check(result, "os", {"governor-full"}, True, "os-network-namespace-private-loopback+python-socket-guard",
                       "ran only in the governor's full OS sandbox")
            self.assertNotIn("not an OS sandbox", result["limits"])
        else:  # this module's explicit opt-in
            self.check(result, "process-only", {"process-only"}, False, "python-socket-loopback-only", "process-only mode")

    def test_the_process_only_opt_in_is_never_reported_as_an_os_sandbox(self):
        with mock.patch.object(detectors, "DEFAULT_ISOLATION", "process-only"):
            result = run_heal(PLAIN_LIB, PLAIN_TESTS)
        self.check(result, "process-only", {"process-only"}, False, "python-socket-loopback-only", "no OS isolation")
        self.assertTrue(result["sandbox"]["audit_log"])

    def test_a_refused_sandbox_reports_that_no_target_code_ran(self):
        with mock.patch.object(detectors, "DEFAULT_ISOLATION", "os"), \
                mock.patch.object(governor, "isolation_probe", return_value=PLAIN_TIER):
            result = run_heal(PLAIN_LIB, PLAIN_TESTS)
        self.assertEqual(result["status"], "blocked")
        self.check(result, "os", {"refused"}, False, "target-code-not-run", "target code was not run")


if __name__ == "__main__":
    unittest.main()
