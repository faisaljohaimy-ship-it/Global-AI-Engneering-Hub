"""Acceptance Scenario F: the governed self-healing loop (L17) on a synthetic fixture.

`tests/fixtures/healing/webapp` is a tiny stdlib web app with three injected defects.
heal() must detect them, trace root causes, repair them only in an isolated copy under
a temporary workdir and prove no regression. Negative cases build small synthetic
targets in temporary directories. No network, provider or production system is used.
"""

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from engineering_os import healing
from engineering_os.healing import HealingError, apply_patch, heal, safe_destination, verify_receipts
from engineering_os.orchestration import sha

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "healing" / "webapp"
TESTS = {"start": "suite", "pattern": "case_*.py"}
NOW = 1_800_000_000
BASELINE_FAILURES = {"case_deps.DependencyTests.test_pins_match_lock",
                     "case_pricing.PricingTests.test_bulk_discount_starts_at_ten",
                     "case_routes.RouteTests.test_count_items"}


def tree_digest(root):
    root = pathlib.Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file() or path.is_symlink()}


def make_target(base, files):
    base = pathlib.Path(base)
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return base


class ScenarioF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="gaie-scenario-f-")
        cls.before = tree_digest(FIXTURE)
        cls.result = heal(FIXTURE, workdir=cls.tmp.name, tests=TESTS, now=NOW)
        cls.after = tree_digest(FIXTURE)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_original_fixture_is_unchanged_and_work_happened_in_an_isolated_copy(self):
        self.assertEqual(self.before, self.after)
        self.assertTrue(self.result["target"]["unchanged"])
        self.assertFalse(self.result["guarantees"]["applied_in_place"])
        copy_root = pathlib.Path(self.result["isolated_copy"])
        self.assertTrue(copy_root.is_dir())
        self.assertIn(pathlib.Path(self.tmp.name).resolve(), copy_root.parents)
        self.assertNotIn(FIXTURE.resolve(), copy_root.parents)
        self.assertNotEqual(tree_digest(copy_root)["pricing.py"], self.before["pricing.py"])
        self.assertEqual(self.result["guarantees"]["production_mutations"], 0)
        self.assertFalse(self.result["guarantees"]["deployment_allowed"])
        # The claim follows the tier every run actually used (Sandbox.summary()): the full OS sandbox on a
        # host that has it, never on the audited process-only opt-in this module takes elsewhere.
        full = governor.isolation_probe()["tier"] == "full"
        self.assertEqual(self.result["guarantees"]["os_sandbox_claimed"], full)
        self.assertEqual(self.result["sandbox"]["os_sandbox"], full)
        self.assertEqual(set(self.result["sandbox"]["tiers"]), {"governor-full"} if full else {"process-only"})

    def test_injected_defects_are_detected(self):
        kinds = {row["kind"] for row in self.result["findings"]}
        self.assertTrue({"missing-route-handler", "pin-lock-mismatch", "api-error-status", "contract-failed"} <= kinds)
        failing = {t for t, o in self.result["baseline_tests"].items() if o != "passed"}
        self.assertEqual(failing, BASELINE_FAILURES)
        self.assertEqual(len(self.result["baseline_tests"]), 15)
        route = next(row for row in self.result["findings"] if row["kind"] == "missing-route-handler")
        self.assertEqual(route["location"]["symbol"], "count_items")
        self.assertEqual(route["evidence"]["linked_from"], ["templates/index.html"])
        for row in self.result["findings"]:
            self.assertEqual(set(row), {"id", "key", "detector", "kind", "location", "evidence", "severity"})

    def test_root_causes_explain_each_failure(self):
        roots = {row["node"]: row for row in self.result["root_causes"]}
        self.assertEqual(len(roots), 3)
        by_kind = {row["id"].split("-")[0]: row for row in roots.values()}
        route_root = next(row for row in roots.values() if row["id"].startswith("missing-route-handler"))
        pin_root = next(row for row in roots.values() if row["id"].startswith("pin-lock-mismatch"))
        logic_root = next(row for row in roots.values() if row["type"] == "test")
        self.assertIn("test:case_routes.RouteTests.test_count_items", route_root["explains"])
        self.assertTrue(any(label.startswith("finding:api-error-status") for label in route_root["explains"]))
        self.assertTrue(any(label.startswith("finding:contract-failed") for label in route_root["explains"]))
        self.assertEqual(pin_root["explains"], ["test:case_deps.DependencyTests.test_pins_match_lock"])
        self.assertEqual(logic_root["id"], "case_pricing.PricingTests.test_bulk_discount_starts_at_ten")
        self.assertTrue(by_kind)
        localized = self.result["iterations"][0]["localization"][logic_root["id"]]
        self.assertEqual((localized[0]["path"], localized[0]["function"]), ("pricing.py", "quote"))

    def test_each_defect_is_repaired_and_validated_without_regression(self):
        self.assertEqual(self.result["status"], "repaired")
        strategies = sorted(row["strategy"] for row in self.result["repairs"])
        self.assertEqual(strategies, ["align-pin-to-lock", "restore-route-handler", "safe-mutation-search"])
        validation = self.result["validation"]
        self.assertTrue(validation["passed"])
        self.assertTrue(all(validation["checks"].values()), validation["checks"])
        self.assertEqual(validation["regressions"], [])
        self.assertEqual(validation["final_failing"], [])
        self.assertEqual(set(validation["targeted_tests"]), BASELINE_FAILURES)
        for test, outcome in self.result["baseline_tests"].items():
            self.assertEqual(validation["final_tests"][test], "passed", test)
            if outcome == "passed":
                self.assertEqual(validation["final_tests"][test], "passed")
        self.assertEqual({row["status"] for row in self.result["defects"]}, {"repaired"})
        self.assertFalse([row for row in self.result["final_findings"] if row["severity"] in ("medium", "high", "critical")])

    def test_rejected_candidates_are_rolled_back_before_the_next_try(self):
        rejected = [row for row in self.result["trials"] if row["repair"] == "rolled-back"]
        self.assertTrue(rejected)
        for row in rejected:
            self.assertTrue(row["rollback_verified"])
            self.assertIn("target-tests-still-failing", row["critique"]["reasons"])
        kept = [row for row in self.result["trials"] if row["repair"] == "kept"]
        self.assertEqual(len(kept), 3)
        self.assertTrue(any("'quantity > 10' -> 'quantity >= 10'" in row["candidate"] for row in kept))

    def test_patch_and_rollback_round_trip(self):
        patch = self.result["patch"]
        self.assertEqual(pathlib.Path(self.result["artifacts"]["patch"]).read_text(encoding="utf-8"), patch)
        self.assertEqual(hashlib.sha256(patch.encode()).hexdigest(), self.result["patch_sha256"])
        changed = sorted(self.result["rollback"]["files"])
        self.assertEqual(changed, ["app.py", "pricing.py", "requirements.txt"])
        originals = {rel: (FIXTURE / rel).read_text(encoding="utf-8") for rel in changed}
        repaired = {rel: (pathlib.Path(self.result["isolated_copy"]) / rel).read_text(encoding="utf-8") for rel in changed}
        self.assertEqual(apply_patch(originals, patch), repaired)
        reverse = pathlib.Path(self.result["artifacts"]["reverse_patch"]).read_text(encoding="utf-8")
        self.assertEqual(apply_patch(repaired, reverse), originals)
        for rel in changed:
            backup = pathlib.Path(self.result["artifacts"]["rollback_dir"]) / rel
            self.assertEqual(backup.read_text(encoding="utf-8"), originals[rel])
            self.assertEqual(self.result["rollback"]["files"][rel]["original_sha256"], self.before[rel])
        self.assertIn("+def count_items(conn, query):", patch)
        self.assertIn("-fixture-json-schema==1.2.0", patch)
        self.assertIn("+    if quantity >= 10:", patch)
        self.assertTrue(self.result["rollback"]["verified"])

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_patch_applies_with_git_to_a_fresh_copy_and_the_suite_passes(self):
        with tempfile.TemporaryDirectory() as scratch:
            fresh = pathlib.Path(scratch) / "app"
            shutil.copytree(FIXTURE, fresh)
            subprocess.run(["git", "apply", "-p1", self.result["artifacts"]["patch"]], cwd=fresh, check=True, capture_output=True)
            done = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "suite", "-p", "case_*.py"],
                                  cwd=fresh, capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            self.assertIn("Ran 15 tests", done.stderr)

    def test_receipts_cover_every_stage_and_form_a_hash_chain(self):
        receipts = self.result["receipts"]
        self.assertEqual({row["stage"] for row in receipts}, set(healing.STAGES))
        self.assertEqual(receipts[0]["stage"], "DISCOVER")
        self.assertEqual(receipts[-1]["stage"], "VALIDATE")
        self.assertTrue(verify_receipts(receipts))
        self.assertTrue(self.result["receipt_chain_valid"])
        tampered = json.loads(json.dumps(receipts))
        tampered[3]["status"] = "accepted-by-hand"
        self.assertFalse(verify_receipts(tampered))
        on_disk = json.loads((pathlib.Path(self.result["run_dir"]) / "receipts.json").read_text())
        self.assertEqual(on_disk, receipts)

    def test_report_is_hash_bound_and_persisted(self):
        result = json.loads(json.dumps(self.result))
        digest = result.pop("report_sha256")
        self.assertEqual(sha(result), digest)
        on_disk = json.loads((pathlib.Path(self.result["run_dir"]) / "report.json").read_text())
        self.assertEqual(on_disk, self.result)
        self.assertEqual(self.result["evidence"]["simulated"], [])
        self.assertEqual(self.result["guarantees"]["model_calls"], 0)

    def test_same_input_and_clock_give_the_same_receipt_chain(self):
        with tempfile.TemporaryDirectory() as scratch:
            again = heal(FIXTURE, workdir=scratch, tests=TESTS, now=NOW)
        self.assertEqual(again["patch"], self.result["patch"])
        self.assertEqual([row["receipt_sha256"] for row in again["receipts"]], [row["receipt_sha256"] for row in self.result["receipts"]])


class LoopSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-heal-neg-")
        self.base = pathlib.Path(self.tmp.name)
        self.workdir = self.base / "work"

    def tearDown(self):
        self.tmp.cleanup()

    def test_defect_without_a_safe_repair_is_reported_not_fixed(self):
        target = make_target(self.base / "nosafe", {
            "app.py": '''
                ROUTES = {("GET", "/report"): "report"}


                def dispatch(method, path):
                    name = ROUTES.get((method, path))
                    handler = globals().get(name) if name else None
                    return 500 if handler is None else handler()
            ''',
            "greet.py": '''
                def greet(name):
                    return "Hi " + name
            ''',
            "suite/case_app.py": '''
                import unittest
                import app
                import greet


                class Tests(unittest.TestCase):
                    def test_report_route(self):
                        self.assertEqual(app.dispatch("GET", "/report"), 200)

                    def test_greeting(self):
                        self.assertEqual(greet.greet("Ada"), "Hello, Ada!")

                    def test_unknown_route(self):
                        self.assertEqual(app.dispatch("GET", "/nope"), 500)
            ''',
        })
        before = tree_digest(target)
        result = heal(target, workdir=self.workdir, tests=TESTS, now=NOW)
        self.assertEqual(tree_digest(target), before)
        self.assertEqual(result["status"], "no-safe-repair")
        self.assertIsNone(result["patch"])
        self.assertIsNone(result["rejected_patch"])
        self.assertEqual(result["repairs"], [])
        self.assertFalse(result["validation"]["passed"])
        statuses = {row["defect"]: row for row in result["defects"]}
        self.assertEqual({row["status"] for row in statuses.values()}, {"unrepaired"})
        self.assertTrue(all(row["reason"] for row in statuses.values()))
        route = next(row for label, row in statuses.items() if label.startswith("finding:missing-route-handler"))
        self.assertIn("not declared in a route spec", route["reason"])
        greeting = statuses["test:case_app.Tests.test_greeting"]
        self.assertIn("none validated", greeting["reason"])
        self.assertTrue(all(row["repair"] in ("rolled-back", "refused") for row in result["trials"]))
        self.assertTrue(verify_receipts(result["receipts"]))

    def test_repair_that_breaks_another_test_is_rejected_and_rolled_back(self):
        target = make_target(self.base / "conflict", {
            "rules.py": '''
                def is_adult(age):
                    return age > 18
            ''',
            "suite/case_rules.py": '''
                import unittest
                from rules import is_adult


                class NewPolicy(unittest.TestCase):
                    def test_eighteen_is_adult(self):
                        self.assertTrue(is_adult(18))


                class LegacyContract(unittest.TestCase):
                    def test_eighteen_is_still_a_minor_for_legacy_accounts(self):
                        self.assertFalse(is_adult(18))

                    def test_thirty_is_adult(self):
                        self.assertTrue(is_adult(30))
            ''',
        })
        original = (target / "rules.py").read_bytes()
        result = heal(target, workdir=self.workdir, tests=TESTS, now=NOW)
        regressions = [row for row in result["trials"] if "regression" in row.get("critique", {}).get("reasons", [])]
        self.assertTrue(regressions)
        for row in result["trials"]:
            self.assertEqual(row["repair"], "rolled-back")
            self.assertTrue(row["rollback_verified"])
        broken = regressions[0]["critique"]["regressions"]["regressions"]
        self.assertEqual(broken, ["case_rules.LegacyContract.test_eighteen_is_still_a_minor_for_legacy_accounts"])
        self.assertTrue(regressions[0]["critique"]["regressions"]["cross_checked"])
        self.assertEqual(result["status"], "no-safe-repair")
        self.assertIsNone(result["patch"])
        self.assertEqual((pathlib.Path(result["isolated_copy"]) / "rules.py").read_bytes(), original)
        self.assertEqual((target / "rules.py").read_bytes(), original)

    def test_writes_outside_the_workdir_are_refused(self):
        base = self.base / "box"
        base.mkdir()
        outside = self.base / "outside"
        outside.mkdir()
        (base / "link").symlink_to(outside)
        for relative in ("../escape.py", "/etc/passwd", "a/../../escape.py", "link/escape.py", "", "a\\b", "./x"):
            with self.subTest(relative=relative), self.assertRaises(HealingError):
                safe_destination(base, relative)
        self.assertEqual(safe_destination(base, "inner/file.py"), base.resolve() / "inner" / "file.py")
        self.assertEqual(list(outside.iterdir()), [])

    def test_workdir_inside_target_and_escaping_paths_are_refused(self):
        target = make_target(self.base / "app", {"rules.py": "def f():\n    return 1\n",
                                                 "suite/case_rules.py": "import unittest\n"})
        before = tree_digest(target)
        with self.assertRaises(HealingError):
            heal(target, workdir=target / "work", tests=TESTS, now=NOW)
        self.assertFalse((target / "work").exists())
        for allowed in (["../outside.py"], ["/etc/passwd"], ["suite/case_rules.py"], ["missing.py"]):
            with self.subTest(allowed=allowed), self.assertRaises(HealingError):
                heal(target, workdir=self.workdir, tests=TESTS, now=NOW, policy={"allowed_files": allowed})
        for spec in ({"start": "../", "pattern": "case_*.py"}, {"start": "suite", "pattern": "../x.py"}, {"start": "suite"}):
            with self.subTest(spec=spec), self.assertRaises(HealingError):
                heal(target, workdir=self.workdir, tests=spec, now=NOW)
        self.assertEqual(tree_digest(target), before)
        self.assertFalse(self.workdir.exists())

    def test_targets_with_escaping_symlinks_are_refused(self):
        outside = self.base / "outside.py"
        outside.write_text("def f():\n    return 1\n")
        for name, link in (("absolute", outside), ("relative", pathlib.Path("..") / ".." / "outside.py")):
            target = make_target(self.base / name, {"suite/case_rules.py": "import unittest\n"})
            (target / "rules.py").symlink_to(link)
            with self.subTest(name=name), self.assertRaises(HealingError):
                heal(target, workdir=self.workdir, tests=TESTS, now=NOW)
        self.assertEqual(outside.read_text(), "def f():\n    return 1\n")

    def test_a_strategy_that_tries_to_write_outside_is_refused_by_the_guard(self):
        target = make_target(self.base / "app", {
            "rules.py": "def is_adult(age):\n    return age > 18\n",
            "suite/case_rules.py": '''
                import unittest
                from rules import is_adult


                class Tests(unittest.TestCase):
                    def test_eighteen(self):
                        self.assertTrue(is_adult(18))
            ''',
        })

        def hostile(self, item):
            yield {"description": "hostile strategy", "edits": {"../../escape.py": b"print('escaped')\n"}}
            yield {"description": "hostile strategy 2", "edits": {"rules.py": b"x = 1\n", "suite/case_rules.py": b"import unittest\n"}}

        with mock.patch.object(healing._Heal, "candidates", hostile):
            result = heal(target, workdir=self.workdir, tests=TESTS, now=NOW)
        self.assertEqual([row["implement"] for row in result["trials"]], ["refused", "refused"])
        self.assertIn("outside the workdir", result["trials"][0]["refusal"])
        self.assertIn("allowed repair set", result["trials"][1]["refusal"])
        self.assertTrue(result["trials"][1]["rollback_verified"])
        self.assertFalse((self.base / "escape.py").exists())
        self.assertFalse(list(self.workdir.rglob("escape.py")))
        self.assertEqual(result["status"], "no-safe-repair")
        self.assertEqual((pathlib.Path(result["isolated_copy"]) / "rules.py").read_text(), "def is_adult(age):\n    return age > 18\n")

    def test_unbounded_networked_or_production_repairs_are_refused(self):
        target = make_target(self.base / "app", {"rules.py": "X = 1\n", "suite/case_rules.py": "import unittest\n"})
        for policy in ({"max_iterations": 1000}, {"max_iterations": 0}, {"max_iterations": None}, {"max_iterations": float("inf")},
                       {"max_candidates": 10 ** 6}, {"test_timeout_s": 0}, {"network": True}, {"environment": "production"},
                       {"environment": "in-place"}, {"deploy": True}, {"allow_dead_code_removal": "yes"}):
            with self.subTest(policy=policy), self.assertRaises(HealingError):
                heal(target, workdir=self.workdir, tests=TESTS, now=NOW, policy=policy)
        self.assertFalse(self.workdir.exists())

    def test_dead_code_is_removed_only_when_opted_in_and_stays_recoverable(self):
        target = make_target(self.base / "app", {
            "helpers.py": '''
                def used(value):
                    return value * 2


                def orphan_formatter(value):
                    return "#" + str(value)


                LIMIT = 3
            ''',
            "suite/case_helpers.py": '''
                import unittest
                from helpers import LIMIT, used


                class Tests(unittest.TestCase):
                    def test_used(self):
                        self.assertEqual(used(LIMIT), 6)
            ''',
        })
        reported = heal(target, workdir=self.workdir, tests=TESTS, now=NOW)
        self.assertEqual(reported["status"], "no-defects-found")
        dead = [row for row in reported["findings"] if row["kind"] == "dead-code"]
        self.assertEqual([row["location"]["symbol"] for row in dead], ["orphan_formatter"])
        self.assertEqual(dead[0]["evidence"]["proof"], "no-static-reference")
        self.assertIsNone(reported["patch"])
        removed = heal(target, workdir=self.workdir, tests=TESTS, now=NOW, policy={"allow_dead_code_removal": True})
        self.assertEqual(removed["status"], "repaired")
        self.assertEqual([row["strategy"] for row in removed["repairs"]], ["remove-dead-code"])
        self.assertIn("-def orphan_formatter(value):", removed["patch"])
        self.assertNotIn("orphan_formatter", (pathlib.Path(removed["isolated_copy"]) / "helpers.py").read_text())
        original = (target / "helpers.py").read_text()
        repaired = (pathlib.Path(removed["isolated_copy"]) / "helpers.py").read_text()
        reverse = pathlib.Path(removed["artifacts"]["reverse_patch"]).read_text()
        self.assertEqual(apply_patch({"helpers.py": repaired}, reverse), {"helpers.py": original})
        self.assertIn("orphan_formatter", original)

    def test_dynamic_access_blocks_dead_code_removal(self):
        target = make_target(self.base / "dyn", {
            "helpers.py": '''
                def orphan_formatter(value):
                    return "#" + str(value)


                def call(name, value):
                    return globals()[name](value)
            ''',
            "suite/case_helpers.py": '''
                import unittest
                import helpers


                class Tests(unittest.TestCase):
                    def test_call(self):
                        self.assertEqual(helpers.call("orphan" + "_formatter", 1), "#1")
            ''',
        })
        result = heal(target, workdir=self.workdir, tests=TESTS, now=NOW, policy={"allow_dead_code_removal": True})
        dead = [row for row in result["findings"] if row["kind"] == "dead-code"]
        self.assertTrue(dead)
        self.assertTrue(all(row["evidence"]["proof"] == "unproven-dynamic-access" for row in dead))
        self.assertEqual(result["repairs"], [])
        self.assertIsNone(result["patch"])
        self.assertIn("orphan_formatter", (pathlib.Path(result["isolated_copy"]) / "helpers.py").read_text())

    def test_partial_repair_keeps_validated_fix_and_reports_the_rest(self):
        target = make_target(self.base / "partial", {
            "blocking.py": '''
                def window(start, size):
                    return list(range(start, start + size - 1))
            ''',
            "greet.py": '''
                def greet(name):
                    return "Hi " + name
            ''',
            "suite/case_mixed.py": '''
                import unittest
                from blocking import window
                from greet import greet


                class Tests(unittest.TestCase):
                    def test_window_has_size_items(self):
                        self.assertEqual(window(2, 3), [2, 3, 4])

                    def test_empty_window(self):
                        self.assertEqual(window(5, 0), [])

                    def test_greeting(self):
                        self.assertEqual(greet("Ada"), "Hello, Ada!")
            ''',
        })
        result = heal(target, workdir=self.workdir, tests=TESTS, now=NOW, policy={"max_iterations": 2})
        self.assertIn("blocking.py", result["allowed_files"])
        self.assertEqual(result["status"], "partially-repaired")
        self.assertTrue(result["validation"]["passed"])
        self.assertEqual([row["files"] for row in result["repairs"]], [["blocking.py"]])
        self.assertIn("+    return list(range(start, start + size - 0))", result["patch"])  # first validated mutation, not idiomatic
        ledger = {row["defect"]: row for row in result["defects"]}
        self.assertEqual(ledger["test:case_mixed.Tests.test_window_has_size_items"]["status"], "repaired")
        self.assertEqual(ledger["test:case_mixed.Tests.test_greeting"]["status"], "unrepaired")
        second = result["iterations"][1]["plan"]
        self.assertEqual([item["reason"] for item in second], ["candidates already exhausted on identical source in an earlier iteration"])
        self.assertEqual(result["validation"]["final_failing"], ["case_mixed.Tests.test_greeting"])


# --------------------------------------------------------------------------- isolation of target code (SEC-07)

from engineering_os import detectors, governor  # noqa: E402

PLAIN_TIER = {"tier": "plain", "root_netns": False, "userns_netns": False, "unshare": True, "root": False, "full_checks": None}


def setUpModule():
    """Real boundary or explicit opt-in. Where the governor's full sandbox cannot be built (for example
    a GitHub runner without user namespaces) this module opts into the audited process-only mode
    explicitly, so the loop is still proven there; OSSandboxTests proves that without the opt-in such
    a host refuses. With GAIE_REQUIRE_FULL_SANDBOX=1 a missing full tier fails instead."""
    if governor.isolation_probe()["tier"] == "full":
        return
    if os.environ.get("GAIE_REQUIRE_FULL_SANDBOX") == "1":
        raise AssertionError("GAIE_REQUIRE_FULL_SANDBOX=1 but the governor's full sandbox tier is missing")
    patcher = mock.patch.object(detectors, "DEFAULT_ISOLATION", "process-only")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class OSSandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-heal-iso-")
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.target = make_target(self.base / "target", {
            "calc.py": """
                def double(n):
                    return n * 2
            """,
            "suite/case_calc.py": """
                import unittest
                from calc import double


                class Tests(unittest.TestCase):
                    def test_double(self):
                        self.assertEqual(double(4), 8)
            """,
        })

    def runs(self, **kw):
        seen, real = [], detectors.Sandbox._record

        def spy(box, tier, **extra):
            seen.append(real(box, tier, **extra))
            return seen[-1]
        with mock.patch.object(detectors.Sandbox, "_record", spy):
            result = heal(self.target, workdir=self.base / "work", tests=TESTS, now=NOW, **kw)
        return result, seen

    def test_target_code_runs_with_the_isolation_this_host_provides(self):
        result, seen = self.runs()
        self.assertTrue(seen)
        self.assertEqual(result["status"], "no-defects-found")
        if governor.isolation_probe()["tier"] == "full":
            self.assertEqual({row["tier"] for row in seen}, {"governor-full"})
            self.assertTrue(all(row["fs_isolated"] for row in seen))
        else:  # the explicit module opt-in above: recorded and audited, never presented as an OS sandbox
            self.assertEqual({(row["tier"], row["opt_in"]) for row in seen}, {("process-only", True)})
            run_dir = pathlib.Path(result["run_dir"])
            self.assertEqual(governor.verify_audit(run_dir / "sandbox"), 1)

    def test_without_the_os_sandbox_the_default_refuses_and_the_loop_is_blocked(self):
        before = tree_digest(self.target)
        with mock.patch.object(detectors, "DEFAULT_ISOLATION", "os"), \
                mock.patch.object(governor, "isolation_probe", return_value=PLAIN_TIER):
            result, seen = self.runs()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual({row["tier"] for row in seen}, {"refused"})
        self.assertEqual(result["baseline_tests"], {})
        self.assertEqual(tree_digest(self.target), before)
        runtime = {row["detector"]: row["status"] for row in result["detectors"] if row["detector"] in detectors.RUNTIME}
        self.assertTrue(set(runtime.values()) <= {"refused", "not-configured"}, runtime)


if __name__ == "__main__":
    unittest.main()
