"""Acceptance Scenario B: the Master Upgrade Engine (L16 with L06/L17) on an existing system.

`tests/fixtures/upgrade/taskapp` is a small stdlib web app (http.server + sqlite3) with 300
synthetic tasks, its own unittest suite (`tests/case_*.py`, outside the repository's
`test*.py` discovery) and four weaknesses. upgrade() must work only in an isolated copy, keep
every original test passing, add tests for each improvement, preserve the data through the
migration, back up the unused asset, leave the fixture byte-identical and produce a patch and a
rollback. Negative cases use the fixture with refused or breaking steps, or tiny targets in
temporary directories. No network, provider, model or production system is used.
"""

import hashlib
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from engineering_os import contracts, healing, upgrade_engine as engine
from engineering_os.memory import MemoryStore
from engineering_os.upgrade_engine import UpgradeError, upgrade

try:  # SEC-07: explicit process-only opt-in where the full sandbox tier is missing (tests/_target_code_mode.py)
    from tests._target_code_mode import opt_in_without_full_tier as setUpModule
except ImportError:  # imported from the tests directory (discover -s tests, layers.verify)
    from _target_code_mode import opt_in_without_full_tier as setUpModule

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
NOW = 1_800_000_000
ARABIC = "طور نظام إدارة المهام بالكامل"
ENGLISH = "Upgrade the task management system completely"
IMPROVEMENTS = ["performance-query-indexes", "security-input-validation", "ui-accessibility-rtl", "assets-backup-unused", "docs-upgrade-notes"]


def tree_digest(root):
    root = pathlib.Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file() or path.is_symlink()}


def rows(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        return conn.execute("SELECT id, title, status, priority, created_at FROM tasks ORDER BY id").fetchall(), \
            {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    finally:
        conn.close()


def make_target(base, files):
    base = pathlib.Path(base)
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return base


class _Temp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="gaie-scenario-b-")
        cls.base = pathlib.Path(cls.tmp.name)
        (cls.base / "gaie-home").mkdir(mode=0o700)
        cls.environ = {"GAIE_HOME": str(cls.base / "gaie-home")}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def run_upgrade(cls, command, name, **options):
        return upgrade(FIXTURE, command=command, workdir=cls.base / name, now=NOW, environ=cls.environ, **options)


class ScenarioB(_Temp):
    """Arabic and English commands upgrade the fixture the same way, in isolated copies."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.before = tree_digest(FIXTURE)
        cls.result = cls.run_upgrade(ARABIC, "ar")
        cls.english = cls.run_upgrade(ENGLISH, "en")
        cls.after = tree_digest(FIXTURE)
        cls.copy = pathlib.Path(cls.result["upgraded_copy"])
        cls.run_dir = pathlib.Path(cls.result["run_dir"])
        cls.steps = {step["id"]: step for step in cls.result["steps"]}

    def test_route_is_an_arabic_comprehensive_upgrade_of_an_explicit_existing_target(self):
        route = self.result["route"]
        self.assertEqual((route["mode"], route["intent"], route["scope"], route["language"]), ("upgrade", "upgrade", "comprehensive", "ar"))
        self.assertEqual(route["target_resolution"], "explicit-local-target")
        self.assertEqual(route["router"]["engine"], "MASTER_UPGRADE")
        self.assertEqual(route["areas"], list(engine.AREAS))
        self.assertEqual((self.english["route"]["language"], self.english["route"]["scope"]), ("en", "comprehensive"))

    def test_upgraded_and_both_languages_apply_the_same_steps(self):
        self.assertEqual(self.result["status"], "upgraded")
        self.assertEqual(self.result["applied"], IMPROVEMENTS)
        self.assertEqual(self.english["applied"], IMPROVEMENTS)
        self.assertEqual(self.result["rejected"], [])
        ours = {s["id"]: s.get("diff") for s in self.result["steps"] if s["id"] != "docs-upgrade-notes"}
        theirs = {s["id"]: s.get("diff") for s in self.english["steps"] if s["id"] != "docs-upgrade-notes"}
        self.assertEqual(ours, theirs)

    def test_original_fixture_is_byte_identical_and_work_happened_in_an_isolated_copy(self):
        self.assertEqual(self.before, self.after)
        self.assertTrue(self.result["target"]["unchanged"])
        self.assertFalse(self.result["guarantees"]["applied_in_place"])
        self.assertIn(self.base.resolve(), self.copy.parents)
        self.assertNotIn(FIXTURE.resolve(), self.copy.parents)
        self.assertNotEqual(tree_digest(self.copy)["app.py"], self.before["app.py"])
        self.assertEqual(self.result["guarantees"]["production_mutations"], 0)
        self.assertFalse(self.result["guarantees"]["deployment_allowed"])
        self.assertEqual(self.result["usage"]["model_calls"], 0)

    def test_weaknesses_are_found_by_the_audit(self):
        kinds = {row["kind"] for row in self.result["audit"]["opportunities"]}
        self.assertTrue({"missing-input-validation", "html-missing-lang-dir", "unlabelled-control", "unindexed-filter", "unused-asset"} <= kinds)
        unused = [row["path"] for row in self.result["audit"]["opportunities"] if row["kind"] == "unused-asset"]
        self.assertEqual(unused, ["static/old-banner.png"])
        self.assertEqual(self.result["audit"]["defects"], [])
        components = {row["component"] for row in self.result["audit"]["coverage_matrix"]}
        self.assertTrue({"database", "images", "tests"} <= components)

    def test_every_original_test_still_passes(self):
        baseline = self.result["baseline"]["tests"]
        passing = [t for t, o in baseline["outcomes"].items() if o == "passed"]
        self.assertEqual(len(passing), 11)
        final = self.result["regression"]
        self.assertEqual(final["regressions"], [])
        self.assertTrue(final["checks"]["no-regression"])
        self.assertTrue(final["checks"]["test-oracle-unchanged"])
        for rel in ("tests/case_app.py", "tests/case_store.py"):
            self.assertEqual(tree_digest(self.copy)[rel], self.before[rel])

    def test_new_tests_fail_before_and_pass_after_each_improvement(self):
        for step_id in ("security-input-validation", "ui-accessibility-rtl", "performance-query-indexes"):
            tests = self.steps[step_id]["new_tests"]
            self.assertGreater(tests["count"], 0, step_id)
            self.assertTrue(tests["red_before"], step_id)
            self.assertEqual(len(tests["green_after"]), tests["count"], step_id)
        self.assertEqual(self.result["regression"]["tests"]["new_tests"], 10)
        self.assertTrue(self.result["regression"]["checks"]["new-tests-pass"])

    def test_upgraded_copy_suite_passes_when_rerun_independently(self):
        with tempfile.TemporaryDirectory(prefix="gaie-rerun-") as scratch:
            work = pathlib.Path(scratch) / "app"
            shutil.copytree(self.copy, work)
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C.UTF-8"}
            done = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "case_*.py", "-t", "tests"],
                                  cwd=work, env=env, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn("Ran 21 tests", done.stderr)

    def test_input_validation_is_generated_from_the_spec_and_wired_into_the_write_handler(self):
        app = (self.copy / "app.py").read_text(encoding="utf-8")
        self.assertIn("import validation\n", app)
        self.assertIn("problems = validation.validate('Task', body)", app)
        rules = (self.copy / "validation.py").read_text(encoding="utf-8")
        self.assertIn("'values': ['todo', 'in_progress', 'done']", rules)
        evidence = self.steps["security-input-validation"]["evidence"]
        self.assertEqual(evidence["routes"], ["POST /api/tasks"])
        self.assertEqual(evidence["acceptance_cases"], 6)

    def test_data_is_intact_after_the_reversible_index_migration(self):
        original, original_indexes = rows(FIXTURE / "data" / "tasks.db")
        upgraded, upgraded_indexes = rows(self.copy / "data" / "tasks.db")
        self.assertEqual(len(original), 300)
        self.assertEqual(upgraded, original)
        self.assertNotIn("idx_tasks_status_created_at", original_indexes)
        self.assertIn("idx_tasks_status_created_at", upgraded_indexes)
        data = self.result["regression"]["data"]["data/tasks.db"]
        self.assertTrue(data["preserved"])
        self.assertEqual((data["tables"]["tasks"]["rows_before"], data["tables"]["tasks"]["rows_after"]), (300, 300))
        self.assertEqual(data["tables"]["tasks"]["sha256_before"], data["tables"]["tasks"]["sha256_after"])
        migration = self.steps["performance-query-indexes"]["migrations"][0]
        self.assertTrue(migration["down_verified"])
        self.assertEqual(migration["statements"], ["create-index"])
        down = (self.copy / "migrations" / "0001_idx_tasks_status_created_at.down.sql").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as scratch:
            undone = pathlib.Path(scratch) / "tasks.db"
            shutil.copyfile(self.copy / "data" / "tasks.db", undone)
            conn = sqlite3.connect(undone)
            conn.executescript(down)
            conn.close()
            self.assertEqual(rows(undone), (original, original_indexes))

    def test_index_choice_comes_from_a_reasoning_trade_off(self):
        trade = self.result["plan"]["reasoning"]["trade_offs"][0]
        self.assertEqual(trade["winner"], "composite-index")
        self.assertEqual(trade["ranking"][-1], "no-index")
        self.assertEqual(trade["receipt"]["engine"], "reasoning")
        order = self.result["plan"]["order"]
        self.assertEqual(order, IMPROVEMENTS)
        self.assertEqual(self.result["plan"]["reasoning"]["decompose"]["receipt"]["operation"], "decompose")

    def test_unused_asset_moves_to_a_verified_backup_only_because_it_is_unreferenced(self):
        self.assertFalse((self.copy / "static" / "old-banner.png").exists())
        backup = self.run_dir / "backup" / "static" / "old-banner.png"
        self.assertEqual(hashlib.sha256(backup.read_bytes()).hexdigest(), self.before["static/old-banner.png"])
        asset = self.result["regression"]["assets"]["static/old-banner.png"]
        self.assertEqual((asset["status"], asset["proof"]), ("moved-to-backup", "no-internal-reference"))
        for rel in ("static/logo.svg", "static/app.css"):
            self.assertEqual(self.result["regression"]["assets"][rel]["status"], "unchanged")
            self.assertEqual(tree_digest(self.copy)[rel], self.before[rel])

    def test_templates_gain_lang_dir_labels_and_viewport(self):
        page = (self.copy / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="ar" dir="rtl">', page)
        self.assertIn('<label for="title">العنوان</label>', page)
        self.assertIn('<label for="priority">الأولوية</label>', page)
        self.assertIn('name="viewport"', page)
        self.assertIn('required maxlength="200"', page)

    def test_patch_and_rollback_are_produced_and_verified(self):
        patch = (self.run_dir / "upgrade.patch").read_text(encoding="utf-8")
        reverse = (self.run_dir / "rollback.patch").read_text(encoding="utf-8")
        self.assertEqual(patch, self.result["patch"])
        changed = self.result["regression"]["changed_files"]
        text = [rel for rel in changed if rel not in ("data/tasks.db", "static/old-banner.png")]
        before = {rel: (FIXTURE / rel).read_text(encoding="utf-8") for rel in text if (FIXTURE / rel).is_file()}
        after = {rel: (self.copy / rel).read_text(encoding="utf-8") for rel in text}
        self.assertEqual({k: v for k, v in healing.apply_patch(before, patch).items() if v is not None}, after)
        self.assertEqual({k: v for k, v in healing.apply_patch(after, reverse).items() if v is not None}, before)
        for rel in ("app.py", "schema.sql", "templates/index.html", "data/tasks.db", "static/old-banner.png"):
            self.assertEqual(hashlib.sha256((self.run_dir / "rollback" / rel).read_bytes()).hexdigest(), self.before[rel])
        binary = {row["path"]: row["kind"] for row in self.result["rollback"]["binary"]}
        self.assertEqual(binary, {"data/tasks.db": "sqlite-migrated", "static/old-banner.png": "moved-to-backup"})
        self.assertTrue(self.result["rollback"]["verified"])
        self.assertTrue(self.result["regression"]["checks"]["rollback-restores-original"])

    def test_receipts_decision_memory_and_usage(self):
        self.assertTrue(self.result["receipt_chain_valid"])
        self.assertTrue(engine.verify_receipts(self.result["receipts"]))
        self.assertEqual([r["stage"] for r in self.result["receipts"]][:4], ["ROUTE", "BASELINE", "AUDIT", "PLAN"])
        self.assertEqual(self.result["receipts"][-1]["stage"], "REPORT")
        tampered = [dict(r) for r in self.result["receipts"]]
        tampered[2]["status"] = "ok-but-edited"
        self.assertFalse(engine.verify_receipts(tampered))
        decision = self.result["decision"]
        self.assertEqual((decision["status"], decision["mode"], decision["provider_calls"]), ("validated", "deterministic", 0))
        memory = self.result["memory"]
        self.assertTrue(memory["written"])
        self.assertEqual(memory["checkpoints"], 7)
        store = MemoryStore.for_project(pathlib.Path(memory["store"]).parent, "task-manager", create=False)
        self.assertEqual(store.next_steps("task-manager")[0]["status"], "done")
        self.assertEqual(store.adrs("task-manager")[0]["status"], "accepted")
        self.assertTrue((self.run_dir / "memory-checkpoint.json").is_file())
        usage = self.result["usage"]
        self.assertEqual((usage["model_tokens"]["value"], usage["charged"]["value"], usage["provider_calls"]), (0, "0", 0))
        self.assertGreaterEqual(usage["test_runs"], 9)
        self.assertEqual(usage["sandbox_seconds"]["unit"], "seconds")

    def test_upgrade_notes_document_the_change_and_its_rollback(self):
        notes = (self.copy / "UPGRADE.md").read_text(encoding="utf-8")
        self.assertIn(ARABIC, notes)
        self.assertIn("0001_idx_tasks_status_created_at", notes)
        self.assertIn("rollback.patch", notes)
        self.assertIn("backup/static/old-banner.png", notes)

    def test_requirements_drive_the_plan_and_every_nfr_is_traced(self):
        requested = self.result["audit"]["requirements"]
        self.assertEqual((requested["status"], requested["breaking"], requested["unmet"]), ("ok", [], []))
        self.assertEqual(self.result["unmet_requests"], [])
        trace = {row["requirement"]: row["status"] for row in self.result["plan"]["requirements_trace"]}
        for requirement in ("input validation on every write endpoint", "filtered list queries use an index", "labels on form fields", "ar rtl"):
            self.assertEqual(trace[requirement], "addressed-by-step", requirement)
        self.assertEqual(trace["no secrets in the repository"], "verified-by-detector")
        self.assertEqual(trace["keyboard navigable"], "not-addressed-by-a-deterministic-generator")


class AuditOnly(_Temp):
    def test_arabic_audit_changes_nothing_and_writes_nothing(self):
        before = tree_digest(FIXTURE)
        workdir = self.base / "audit-out"
        result = upgrade(FIXTURE, command="افحص نظام إدارة المهام", workdir=workdir, now=NOW, environ=self.environ)
        self.assertEqual(result["status"], "audited")
        self.assertEqual(result["route"]["mode"], "audit")
        self.assertFalse(workdir.exists())
        self.assertEqual(tree_digest(FIXTURE), before)
        self.assertEqual(result["no_change_proof"], {"target_unchanged": True, "workdir_untouched": True, "files_written": 0,
                                                     "tests_executed": False, "memory_written": False})
        self.assertFalse(result["changes_made"])
        self.assertIsNone(result["patch"])
        planned = {s["id"] for s in result["plan"]["steps"] if s["status"] == "planned"}
        self.assertTrue(set(IMPROVEMENTS[:4]) <= planned)
        self.assertTrue(engine.verify_receipts(result["receipts"]))

    def test_english_audit_into_an_existing_workdir_leaves_it_untouched(self):
        workdir = self.base / "existing"
        workdir.mkdir()
        (workdir / "keep.txt").write_text("keep", encoding="utf-8")
        result = upgrade(FIXTURE, command="Audit the task management system", workdir=workdir, now=NOW, environ=self.environ)
        self.assertEqual(result["status"], "audited")
        self.assertEqual(sorted(p.name for p in workdir.iterdir()), ["keep.txt"])


class RejectedAndRefusedSteps(_Temp):
    """Caller-declared steps pass the same gates: breaking, data-losing, escaping and network steps never stay."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.outside = cls.base / "escape.txt"
        cls.before = tree_digest(FIXTURE)
        extra = [
            {"id": "break-health", "area": "code", "title": "Report degraded health",
             "changes": [{"op": "replace", "path": "app.py", "old": '{"status": "ok"}', "new": '{"status": "degraded"}'}]},
            {"id": "drop-tasks", "area": "database", "title": "Drop the tasks table",
             "changes": [{"op": "migration", "database": "data/tasks.db", "name": "drop-tasks", "up": "DROP TABLE tasks;", "down": ""}]},
            {"id": "drop-column", "area": "database", "title": "Drop a column",
             "changes": [{"op": "migration", "database": "data/tasks.db", "name": "drop-column", "up": "ALTER TABLE tasks DROP COLUMN priority;", "down": ""}]},
            {"id": "escape", "area": "docs", "title": "Write next to the workdir",
             "changes": [{"op": "add-file", "path": "../../escape.txt", "text": "outside"}]},
            {"id": "absolute", "area": "docs", "title": "Write to an absolute path",
             "changes": [{"op": "add-file", "path": str(cls.outside), "text": "outside"}]},
            {"id": "edit-test", "area": "tests", "title": "Weaken an existing test",
             "changes": [{"op": "replace", "path": "tests/case_app.py", "old": "self.assertEqual(status, 201)", "new": "pass"}]},
            {"id": "reach-network", "area": "tests", "title": "A new test that reaches a public address",
             "changes": [{"op": "add-file", "path": "netcheck.py", "text": "def ok():\n    return True\n"}],
             "tests": [{"path": "tests/case_netcheck.py", "text": "import socket\nimport unittest\n\n\nclass Net(unittest.TestCase):\n"
                        "    def test_public_address(self):\n        socket.create_connection(('203.0.113.7', 80), timeout=1).close()\n"}]},
        ]
        cls.result = cls.run_upgrade(ENGLISH, "negative", extra_steps=extra)
        cls.steps = {step["id"]: step for step in cls.result["steps"]}
        cls.copy = pathlib.Path(cls.result["upgraded_copy"])

    def test_a_step_that_breaks_an_old_test_is_rejected_and_rolled_back(self):
        step = self.steps["requested-break-health"]
        self.assertEqual(step["status"], "rejected")
        self.assertIn("no-regression", step["reasons"])
        self.assertEqual(step["regressions"], ["case_app.RouteTests.test_health"])
        self.assertTrue(step["rollback_verified"])
        self.assertNotIn('"degraded"', (self.copy / "app.py").read_text(encoding="utf-8"))

    def test_migrations_that_would_drop_data_are_refused_and_data_stays_intact(self):
        for name in ("requested-drop-tasks", "requested-drop-column"):
            self.assertEqual(self.steps[name]["status"], "refused")
            self.assertIn("Migration refused", self.steps[name]["reason"])
        self.assertEqual(rows(self.copy / "data" / "tasks.db")[0], rows(FIXTURE / "data" / "tasks.db")[0])
        self.assertTrue(self.result["regression"]["checks"]["data-preserved"])

    def test_writes_outside_the_workdir_are_refused(self):
        for name in ("requested-escape", "requested-absolute"):
            self.assertEqual(self.steps[name]["status"], "refused")
            self.assertIn("Refused write outside the workdir", self.steps[name]["reason"])
        self.assertFalse(self.outside.exists())
        self.assertFalse((self.base / "negative" / "escape.txt").exists())

    def test_existing_tests_are_never_edited(self):
        step = self.steps["requested-edit-test"]
        self.assertEqual(step["status"], "refused")
        self.assertIn("existing tests are never edited", step["reason"])
        self.assertEqual(tree_digest(self.copy)["tests/case_app.py"], self.before["tests/case_app.py"])

    def test_target_code_cannot_reach_the_network(self):
        step = self.steps["requested-reach-network"]
        self.assertEqual(step["status"], "rejected")
        self.assertEqual(step["failing_new_tests"], ["case_netcheck.Net.test_public_address"])
        detail = step["failure_details"]["case_netcheck.Net.test_public_address"]
        self.assertEqual(detail["type"], "PermissionError")
        self.assertIn("refused", detail["message"])
        self.assertFalse((self.copy / "netcheck.py").exists())

    def test_the_other_improvements_still_apply_and_the_fixture_is_unchanged(self):
        self.assertEqual(self.result["status"], "upgraded-with-rejections")
        self.assertEqual(self.result["applied"], IMPROVEMENTS)
        self.assertTrue(self.result["regression"]["passed"])
        self.assertEqual(tree_digest(FIXTURE), self.before)


class FocusedAndHealing(_Temp):
    def test_performance_focus_applies_only_the_performance_step(self):
        result = self.run_upgrade("طور أداء نظام إدارة المهام", "focus")
        self.assertEqual((result["route"]["scope"], result["route"]["focus"]), ("focused", ["performance"]))
        self.assertEqual(result["applied"], ["performance-query-indexes", "docs-upgrade-notes"])
        statuses = {s["id"]: s["status"] for s in result["plan"]["steps"]}
        self.assertEqual(statuses["security-input-validation"], "not-selected")
        self.assertEqual(statuses["ui-accessibility-rtl"], "not-selected")
        self.assertTrue(result["regression"]["passed"])

    def test_repair_command_uses_the_self_healing_loop(self):
        target = make_target(self.base / "calc", {
            "calc.py": '''
                """Tiny calculator (synthetic)."""


                def add(a, b):
                    return a - b


                def double(x):
                    return x * 2
                ''',
            "tests/test_calc.py": '''
                import unittest

                import calc


                class CalcTests(unittest.TestCase):
                    def test_add(self):
                        self.assertEqual(calc.add(2, 3), 5)

                    def test_double(self):
                        self.assertEqual(calc.double(4), 8)
                ''',
        })
        before = tree_digest(target)
        result = upgrade(target, command="اصلح نظام الحاسبة", workdir=self.base / "calc-run", now=NOW, environ=self.environ)
        self.assertEqual((result["route"]["intent"], result["route"]["scope"]), ("repair", "self-healing"))
        self.assertEqual(result["status"], "upgraded")
        self.assertEqual(result["applied"], ["code-repair-defects", "docs-upgrade-notes"])
        step = next(s for s in result["steps"] if s["id"] == "code-repair-defects")
        self.assertEqual(step["evidence"]["healing_status"], "repaired")
        self.assertEqual(result["regression"]["tests"]["baseline_failures_fixed"], ["test_calc.CalcTests.test_add"])
        self.assertIn("+    return a + b", result["patch"])
        self.assertEqual(tree_digest(target), before)

    def test_requested_additions_without_a_generator_are_reported_as_unmet(self):
        result = self.run_upgrade("طور نظام إدارة المهام وأضف تاريخ الاستحقاق للمهام", "unmet")
        self.assertEqual(result["status"], "partially-upgraded")
        self.assertEqual(result["unmet_requests"], ["field Task.due_date"])
        self.assertEqual(result["decision"]["status"], "validated")
        self.assertIn("requested-changes-met: contradicted", result["decision"]["warnings"])
        self.assertIn("field Task.due_date", result["summary"]["en"])
        self.assertNotIn("due_date", (pathlib.Path(result["upgraded_copy"]) / "validation.py").read_text(encoding="utf-8"))
        self.assertIn("field Task.due_date", (pathlib.Path(result["upgraded_copy"]) / "UPGRADE.md").read_text(encoding="utf-8"))

    def test_a_target_without_tests_is_blocked_and_unchanged(self):
        target = make_target(self.base / "untested", {"tool.py": "def run():\n    return 1\n"})
        result = upgrade(target, command="Upgrade the tool", workdir=self.base / "untested-run", now=NOW, environ=self.environ)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("no existing test suite", result["blocked"])
        self.assertEqual(result["applied"], [])
        self.assertTrue(result["regression"]["checks"]["original-unchanged"])


class Refusals(_Temp):
    def refused(self, message, *, command=ARABIC, target=FIXTURE, workdir=None, **options):
        workdir = workdir or self.base / "refused"
        with self.assertRaises(UpgradeError) as caught:
            upgrade(target, command=command, workdir=workdir, now=NOW, environ=self.environ, **options)
        self.assertIn(message, str(caught.exception))
        self.assertFalse((self.base / "refused").exists())
        return caught.exception

    def test_release_deploy_and_production_are_refused(self):
        for command in ("انشر نظام إدارة المهام", "upgrade the task management system and deploy it", "deploy the task management system"):
            self.refused("Deployment refused", command=command)
        for command in ("upgrade the production task management system", "طور نظام إدارة المهام في بيئة الإنتاج"):
            self.refused("Production target refused", command=command)

    def test_building_from_scratch_is_refused(self):
        self.refused("Building from scratch refused", command="ابن نظام إدارة المهام")
        empty = self.base / "empty"
        empty.mkdir()
        self.refused("never builds from scratch", target=empty)
        self.refused("existing system directory", target=self.base / "missing")

    def test_a_requested_change_that_would_drop_data_is_refused_before_any_copy(self):
        error = self.refused("Requested change refused", command="Upgrade the task management system and remove priority from tasks")
        self.assertIn("field-removed Task.priority", str(error))

    def test_network_deploy_and_in_place_policies_are_refused(self):
        self.refused("Network access refused", policy={"network": True})
        self.refused("Deployment refused", policy={"deploy": True})
        self.refused("Production or in-place upgrade refused", policy={"environment": "production"})
        self.refused("Unknown policy field", policy={"shell": True})

    def test_unsafe_workdirs_are_refused(self):
        self.refused("in place", workdir=FIXTURE / "out")
        self.refused("outside every Git repository", workdir=ROOT / "upgrade-out")
        self.assertFalse((ROOT / "upgrade-out").exists())

    def test_unroutable_and_malformed_requests_are_refused(self):
        self.refused("Command not routable", command="what is the task management system?")
        self.refused("command must be", command="")
        self.refused("Invalid test suite", tests={"start": "../", "pattern": "case_*.py"})
        self.refused("extra step", extra_steps=[{"id": "x", "area": "code"}])
        self.refused("change op", extra_steps=[{"id": "x", "area": "code", "title": "t", "changes": [{"op": "shell", "cmd": "rm"}]}])


class MigrationGuard(unittest.TestCase):
    def test_schema_only_statements_are_allowed(self):
        kinds = [row["kind"] for row in engine.classify_migration(
            "-- add an index\nCREATE INDEX IF NOT EXISTS i ON tasks (status, created_at);\n"
            "ALTER TABLE tasks ADD COLUMN note TEXT DEFAULT '';\nPRAGMA user_version = 2;\nDROP INDEX IF EXISTS old_i;")]
        self.assertEqual(kinds, ["create-index", "add-column", "user-version", "drop-index"])

    def test_data_losing_or_rewriting_statements_are_refused(self):
        for sql in ("DROP TABLE tasks;", "DELETE FROM tasks;", "UPDATE tasks SET title = '';", "INSERT INTO tasks VALUES (1);",
                    "ALTER TABLE tasks DROP COLUMN title;", "ALTER TABLE tasks RENAME TO old_tasks;", "VACUUM;",
                    "ATTACH DATABASE 'x.db' AS x;", "PRAGMA writable_schema = 1;",
                    "CREATE TRIGGER t AFTER INSERT ON tasks BEGIN DELETE FROM tasks; END;",
                    "CREATE INDEX i ON tasks (status); /* hidden */ DROP TABLE tasks;", "-- comment ;\nDELETE FROM tasks"):
            with self.subTest(sql=sql), self.assertRaises(UpgradeError):
                engine.classify_migration(sql)

    def test_dynamic_proof_refuses_data_loss_even_if_the_static_guard_were_bypassed(self):
        with tempfile.TemporaryDirectory() as scratch:
            db = pathlib.Path(scratch) / "tasks.db"
            shutil.copyfile(FIXTURE / "data" / "tasks.db", db)
            digest = hashlib.sha256(db.read_bytes()).hexdigest()
            allow = lambda sql: [{"statement": s, "kind": "bypassed"} for s in engine.split_sql(sql)]
            with mock.patch.object(engine, "classify_migration", allow):
                with self.assertRaises(UpgradeError) as caught:
                    engine.migrate_database(db, "DELETE FROM tasks WHERE status = 'done';", "", pathlib.Path(scratch) / "work")
            self.assertIn("would lose or change data", str(caught.exception))
            self.assertIn("300 rows before, 200 after", str(caught.exception))
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), digest)

    def test_added_columns_keep_the_original_data_proven(self):
        with tempfile.TemporaryDirectory() as scratch:
            db = pathlib.Path(scratch) / "tasks.db"
            shutil.copyfile(FIXTURE / "data" / "tasks.db", db)
            data, proof = engine.migrate_database(db, "ALTER TABLE tasks ADD COLUMN note TEXT;", "", pathlib.Path(scratch) / "work")
            self.assertTrue(proof["data_preserved"])
            migrated = pathlib.Path(scratch) / "migrated.db"
            migrated.write_bytes(data)
            problems, after = engine.data_preserved(engine.data_manifest(db), migrated)
            self.assertEqual(problems, [])
            self.assertIn("note", after["tables"]["tasks"]["columns"])

    def test_a_down_migration_that_does_not_restore_the_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as scratch:
            db = pathlib.Path(scratch) / "tasks.db"
            shutil.copyfile(FIXTURE / "data" / "tasks.db", db)
            with self.assertRaises(UpgradeError) as caught:
                engine.migrate_database(db, "CREATE INDEX i ON tasks (status);", "PRAGMA user_version = 7;", pathlib.Path(scratch) / "work")
            self.assertIn("does not restore", str(caught.exception))

    def test_changed_rows_are_detected(self):
        with tempfile.TemporaryDirectory() as scratch:
            db = pathlib.Path(scratch) / "tasks.db"
            shutil.copyfile(FIXTURE / "data" / "tasks.db", db)
            before = engine.data_manifest(db)
            conn = sqlite3.connect(db)
            conn.execute("UPDATE tasks SET title = 'changed' WHERE id = 7")
            conn.commit()
            conn.close()
            self.assertEqual(engine.data_preserved(before, db)[0], ["table tasks: row checksum changed"])


class RegisteredProjectScope(unittest.TestCase):
    """A command that names a registered project runs only on that project's verified isolated worktree."""

    SADEED = "https://github.com/faisaljohaimy-ship-it/biz-pulse-ar.git"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-upgrade-scope-")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.environ = {"GAIE_HOME": str(self.base / "gaie-home")}

    def linked(self, name, origin):
        checkout, worktree = self.base / f"{name}-canonical", self.base / f"{name}-worktree"
        checkout.mkdir(mode=0o700)

        def git(*args):
            subprocess.run(["git", "-C", str(checkout), *args], check=True, capture_output=True)

        git("init", "-q", "-b", "main")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "base")
        git("remote", "add", "origin", origin)
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        git("worktree", "add", "-qb", f"codex/gaie-upgrade-{name}", str(worktree))
        worktree.chmod(0o700)
        return checkout, worktree

    def route(self, command, workspace):
        return engine.route_command(command, environ=self.environ, workspace=workspace)

    def test_upgrade_and_audit_accept_only_the_verified_worktree_of_the_named_project(self):
        checkout, worktree = self.linked("sadeed", self.SADEED)
        _, foreign = self.linked("other", "https://github.com/example/another-project.git")
        for command, mode in (("Upgrade Sadeed", "upgrade"), ("طور سديد", "upgrade"), ("Audit Sadeed", "audit"), ("افحص سديد", "audit")):
            with self.subTest(command=command):
                route = self.route(command, worktree)
                self.assertEqual((route["mode"], route["project"], route["target_resolution"]),
                                 (mode, "biz-pulse-ar", "registered-project"))
                for unverified in (checkout, foreign, ROOT, FIXTURE):
                    with self.subTest(workspace=unverified.name), self.assertRaises(UpgradeError) as caught:
                        self.route(command, unverified)
                    self.assertIn("not its verified isolated checkout", str(caught.exception))

    def test_a_dirty_worktree_is_refused_for_an_upgrade_and_readable_for_an_audit(self):
        _, worktree = self.linked("sadeed", self.SADEED)
        (worktree / "untracked.txt").write_text("local edit\n", encoding="utf-8")
        with self.assertRaises(UpgradeError) as caught:
            self.route("Upgrade Sadeed", worktree)
        self.assertIn("clean dedicated worktree", str(caught.exception))
        self.assertEqual(self.route("Audit Sadeed", worktree)["mode"], "audit")

    def test_several_named_projects_are_refused_for_one_target(self):
        _, worktree = self.linked("sadeed", self.SADEED)
        for command in ("Upgrade Sadeed and Wow Bus", "Audit Sadeed and Wow Bus"):
            with self.subTest(command=command), self.assertRaises(UpgradeError) as caught:
                self.route(command, worktree)
            self.assertIn("One explicit target per run", str(caught.exception))

    def test_questions_and_read_only_wording_never_start_an_upgrade(self):
        _, worktree = self.linked("sadeed", self.SADEED)
        for command in ("Can you upgrade Sadeed?", "هل يمكن تطوير سديد؟", "Upgrade Sadeed, read-only", "طور سديد بدون تعديل",
                        "Upgrade the task management system without changes"):
            with self.subTest(command=command), self.assertRaises(UpgradeError) as caught:
                self.route(command, worktree)
            self.assertIn("Command not routable", str(caught.exception))
        with tempfile.TemporaryDirectory() as scratch:
            workdir = pathlib.Path(scratch) / "never"
            with self.assertRaises(UpgradeError):
                upgrade(FIXTURE, command="Can you upgrade the task management system?", workdir=workdir, now=NOW,
                        environ=self.environ)
            self.assertFalse(workdir.exists())


class Units(unittest.TestCase):
    def test_route_command_maps_intents_to_areas(self):
        environ = {"GAIE_HOME": tempfile.gettempdir() + "/gaie-upgrade-unit-home"}
        self.assertEqual(engine.route_command("سرّع نظام إدارة المهام", environ=environ)["scope"], "performance")
        self.assertEqual(engine.route_command("upgrade the security of the task system", environ=environ)["areas"], ["security", "tests", "docs"])
        self.assertEqual(engine.route_command("طور واجهة نظام إدارة المهام", environ=environ)["areas"], ["ui", "tests", "docs"])
        with self.assertRaises(UpgradeError):
            engine.route_command("upgrade all my projects", environ=environ)

    def test_html_fix_is_deterministic_and_never_invents_alt_text(self):
        page = '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n</head>\n<body>\n  <label>Name <input name="n"></label>\n' \
               '  <input name="email" type="email">\n  <img src="/x.png">\n</body>\n</html>\n'
        fixed, changes = engine.fix_html(page, None)
        self.assertIn('<html lang="en" dir="ltr">', fixed)
        self.assertIn('<label for="email">Email</label>\n  <input name="email" type="email" id="email">', fixed)
        self.assertEqual(fixed.count("<label"), 2)
        self.assertIn('<img src="/x.png">', fixed)
        self.assertEqual(engine.fix_html(fixed, None)[0].count("<label"), 2)
        kinds = {row["kind"] for row in changes}
        self.assertEqual(kinds, {"html-lang-dir", "label-added", "viewport-added"})

    def test_fragments_only_get_labels_and_generated_tests_compile(self):
        fixed, changes = engine.fix_html('<form>\n  <input name="query">\n</form>\n', None)
        self.assertEqual(fixed, '<form>\n  <label for="query">Query</label>\n  <input name="query" id="query">\n</form>\n')
        self.assertEqual([row["kind"] for row in changes], ["label-added"])
        source = engine._ui_tests("ui-accessibility-rtl", ["templates/a.html", "templates/part.html"], None, None)
        compile(source, "case_upgrade_ui.py", "exec")
        self.assertIn("RTL = ('ar', 'fa', 'he', 'ur')", source)

    def test_asset_reference_proofs(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = make_target(scratch, {"index.html": '<img src="/static/used.png">', "app.py": "x = 1\n",
                                         "static/used.png": "png", "static/spare-image.png": "png"})
            files = ["app.py", "index.html", "static/spare-image.png", "static/used.png"]
            self.assertEqual(engine.asset_references(root, "static/used.png", files)["proof"], "referenced")
            self.assertEqual(engine.asset_references(root, "static/spare-image.png", files)["proof"], "no-internal-reference")
            (root / "app.py").write_text("import os\nNAMES = os.listdir('static')\n", encoding="utf-8")
            self.assertEqual(engine.asset_references(root, "static/spare-image.png", files)["proof"], "unproven-dynamic-access")

    def test_engine_record_satisfies_the_contract_and_health_is_side_effect_free(self):
        record = {"id": "master-upgrade-engine", "layer": "L16", "title": {"en": "Master Upgrade Engine", "ar": "محرك التطوير الرئيسي"},
                  "entrypoint": "engineering_os.upgrade_engine:engine", "health": "engineering_os.upgrade_engine:health",
                  "actions": engine.ENGINE_ACTIONS, "supersedes": []}
        contracts.validate_engine(record, check_imports=True)
        self.assertEqual(engine.health()["ok"], True)
        with tempfile.TemporaryDirectory() as scratch:
            workdir = pathlib.Path(scratch) / "never"
            payload = {"target": str(FIXTURE), "command": ARABIC, "workdir": str(workdir)}
            with self.assertRaises(UpgradeError):
                engine.engine("audit", payload, {"now": NOW, "environ": {"GAIE_HOME": scratch + "/home"}})
            self.assertFalse(workdir.exists())
            result = engine.engine("audit", {**payload, "command": "افحص نظام إدارة المهام"}, {"now": NOW, "environ": {"GAIE_HOME": scratch + "/home"}})
            self.assertEqual(result["status"], "audited")
            self.assertFalse(workdir.exists())
            with self.assertRaises(UpgradeError):
                engine.engine("deploy", payload)


if __name__ == "__main__":
    unittest.main()
