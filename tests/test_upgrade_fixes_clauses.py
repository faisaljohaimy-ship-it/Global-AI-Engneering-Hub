"""Re-check of W2-UP-04: a request is met only when every clause of the command is accounted for.

The first fix stopped on remove verbs from a fixed lexicon; any other wording the parser ignored
("get rid of", "disable", a passive clause, «امسح», «يجب حذف», "rename ... to ...") still gave
status "ok" with nothing unmet, so the run ended "upgraded" with requested-changes-met true and
the copy unchanged. Now `requested_changes` accounts for every word (`_account`): the router's
own vocabulary, function words, the target's name, the requirements-lexicon phrases the
specification diff is computed from, or one of the engine's own steps (`ENGINE_REQUESTS`).
Anything else makes the request `unsettled` and the upgrade stops before copying. The engine
requests ("remove unused assets", "remove dead code", "remove slow queries") are accepted again
and are met only when the upgraded copy is verified to satisfy them.
"""

import json
import pathlib
import shutil
import tempfile
import unittest

from engineering_os import upgrade_engine as engine
from engineering_os.upgrade_engine import UpgradeError, upgrade

try:  # SEC-07 (final branch): explicit process-only opt-in where the full sandbox tier is missing (tests/_target_code_mode.py)
    from tests._target_code_mode import opt_in_without_full_tier as setUpModule
except ImportError:
    try:  # imported from the tests directory (discover -s tests)
        from _target_code_mode import opt_in_without_full_tier as setUpModule
    except ImportError:  # a tree before SEC-07: detectors.Sandbox runs the target's suite without an opt-in
        pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
SPEC = json.loads((FIXTURE / "gaie-spec.json").read_text(encoding="utf-8"))
NOW = 1_800_000_000
# The re-check's bypasses (they ended "upgraded", requested-changes-met true) and a counterpart in the other language.
BYPASSES = (
    "Upgrade the task management system and get rid of the Arabic locale",
    "طور نظام إدارة المهام وتخلص من اللغة العربية",
    "Upgrade the task management system and disable Arabic",
    "طور نظام إدارة المهام وعطّل اللغة العربية",
    "Upgrade the task management system; the Arabic locale should be removed",
    "طور نظام إدارة المهام، يجب حذف اللغة العربية",
    "طور نظام إدارة المهام وامسح اللغة العربية",
    "Upgrade the task management system and erase the Arabic locale",
    "Upgrade the task management system and rename the tasks entity to jobs",
    "طور نظام إدارة المهام وأعد تسمية المهام إلى وظائف",
    "Upgrade the task management system and replace Arabic with French",
    "طور نظام إدارة المهام واستبدل العربية بالفرنسية",
    "Upgrade the task management system and make the title optional",
    "طور نظام إدارة المهام واجعل العنوان اختياريا",
    "طور نظام إدارة المهام وألغِ اللغة العربية",
    "Upgrade the task management system minus the Arabic locale",
    "Upgrade the task management system and rem0ve the Arabic locale",
)
SETTLED = {
    "Upgrade the task management system completely": ("ok", []),
    "طور نظام إدارة المهام بالكامل": ("ok", []),
    "طور أداء نظام إدارة المهام": ("ok", []),
    "Fix the errors in the task management system": ("ok", []),
    "Speed up the task management system": ("ok", []),
    "طور نظام إدارة المهام وأضف تاريخ الاستحقاق للمهام": ("ok", ["field Task.due_date"]),
    "Upgrade the task management system and remove priority from tasks": ("refused-breaking", []),
}
ENGINE = {
    "Upgrade the task management system and remove unused assets": "unused-assets",
    "طور نظام إدارة المهام واحذف الأصول المهملة": "unused-assets",
    "Upgrade the task management system and remove dead code": "dead-code",
    "طور نظام إدارة المهام واحذف الكود الميت": "dead-code",
    "Speed up the task management system and remove slow queries": "slow-queries",
    "سرّع نظام إدارة المهام واحذف الاستعلامات البطيئة": "slow-queries",
}


class Accounting(unittest.TestCase):
    def test_every_ignored_clause_leaves_the_request_unsettled_in_both_languages(self):
        for command in BYPASSES:
            with self.subTest(command=command):
                requested = engine.requested_changes(command, SPEC)
                self.assertEqual(requested["status"], "unsettled")
                self.assertTrue(requested["unmet"], "the unaccounted wording is named")
        self.assertEqual(engine.requested_changes(BYPASSES[0], SPEC)["unmet"], ["not accounted for: get rid of the arabic locale"])
        self.assertEqual(engine.requested_changes(BYPASSES[6], SPEC)["unmet"], ["not accounted for: وامسح اللغه العربيه"])

    def test_settled_commands_keep_their_status(self):
        for command, expected in SETTLED.items():
            with self.subTest(command=command):
                requested = engine.requested_changes(command, SPEC)
                self.assertEqual((requested["status"], requested["unmet"]), expected)

    def test_the_engines_own_steps_are_accepted_as_requests(self):
        for command, request in ENGINE.items():
            with self.subTest(command=command):
                requested = engine.requested_changes(command, SPEC)
                self.assertEqual((requested["status"], requested["unmet"]), ("ok", []))
                self.assertEqual([row["id"] for row in requested["requests"]], [request])
                self.assertEqual(engine._exclusions(command, SPEC), [])

    def test_a_removal_beyond_an_engine_request_is_still_an_exclusion(self):
        requested = engine.requested_changes("Upgrade the task management system and remove unused assets and the Arabic locale", SPEC)
        self.assertEqual((requested["status"], requested["unmet"]), ("unsettled", ["not accounted for: arabic locale"]))
        for command in ("Upgrade the task management system and remove the duplicate code",
                        "Upgrade the task management system and delete old banner images"):
            self.assertEqual(engine.requested_changes(command, SPEC)["status"], "unsettled", command)

    def test_a_later_change_verb_needs_a_diff(self):
        for command in ("Upgrade the task management system and modify the tasks", "طور نظام إدارة المهام وعدّل المهام"):
            requested = engine.requested_changes(command, SPEC)
            self.assertEqual(requested["status"], "unsettled", command)
            self.assertTrue(requested["unmet"][0].startswith("change: "))

    def test_the_target_name_comes_from_the_specification_or_the_run(self):
        self.assertEqual(engine.requested_changes("Upgrade Sadeed", SPEC)["status"], "unsettled")
        self.assertEqual(engine.requested_changes("Upgrade Sadeed", SPEC, ["sadeed"])["status"], "ok")
        self.assertEqual(engine.requested_changes("طور نظام إدارة المهام", SPEC)["status"], "ok")  # the spec's own title

    def test_without_a_specification_only_the_name_after_the_verb_is_free(self):
        for command in ("Upgrade the tool", "اصلح نظام الحاسبة", "Upgrade my calculator app completely"):
            self.assertEqual(engine.requested_changes(command, None)["status"], "no-specification", command)
        for command in ("Upgrade the tool minus the cache", "Upgrade the calculator and get rid of the logs",
                        "طور الحاسبة وامسح السجلات"):
            self.assertEqual(engine.requested_changes(command, None)["status"], "unsettled", command)


class _Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-cl-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)
        (self.base / "home").mkdir(mode=0o700)
        self.environ = {"GAIE_HOME": str(self.base / "home")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_upgrade(self, command, name, target=FIXTURE, **options):
        return upgrade(target, command=command, workdir=self.base / name, now=NOW, environ=self.environ, **options)


class UpgradeStops(_Run):
    def test_each_bypass_stops_before_anything_is_copied(self):
        for number, command in enumerate(BYPASSES):
            with self.subTest(command=command):
                with self.assertRaises(UpgradeError) as caught:
                    self.run_upgrade(command, f"wd-{number}")
                self.assertIn("Requested change not settled (unsettled", str(caught.exception))
                self.assertIn("Nothing was copied or changed", str(caught.exception))
                self.assertFalse((self.base / f"wd-{number}").exists())


class EngineRequests(_Run):
    def test_remove_unused_assets_is_carried_out_and_met(self):
        result = self.run_upgrade("Upgrade the task management system and remove unused assets", "assets")
        self.assertEqual(result["status"], "upgraded")
        self.assertIn("assets-backup-unused", result["applied"])
        self.assertTrue(result["regression"]["checks"]["requested-changes-met"])
        self.assertEqual(result["unmet_requests"], [])
        self.assertEqual(result["regression"]["assets"]["static/old-banner.png"]["status"], "moved-to-backup")

    def test_an_engine_request_the_run_cannot_satisfy_is_reported_unmet(self):
        result = self.run_upgrade("طور نظام إدارة المهام واحذف الأصول المهملة", "no-backup", policy={"asset_backup": False})
        self.assertEqual(result["status"], "partially-upgraded")
        self.assertFalse(result["regression"]["checks"]["requested-changes-met"])
        self.assertEqual(result["unmet_requests"], ["الاصول المهمله: 1 unreferenced asset(s) still in the copy (static/old-banner.png)"])
        self.assertIn("الاصول المهمله", (pathlib.Path(result["upgraded_copy"]) / "UPGRADE.md").read_text(encoding="utf-8"))

    def test_remove_dead_code_is_met_only_when_no_dead_code_remains(self):
        clean = self.run_upgrade("طور نظام إدارة المهام واحذف الكود الميت", "clean")
        self.assertEqual((clean["status"], clean["unmet_requests"]), ("upgraded", []))
        self.assertTrue(clean["regression"]["checks"]["requested-changes-met"])
        target = self.base / "dead"
        shutil.copytree(FIXTURE, target)
        (target / "legacy.py").write_text("def unused_report_helper(rows):\n    return len(rows)\n", encoding="utf-8")
        result = self.run_upgrade("Upgrade the task management system and remove dead code", "dead-run", target=target)
        self.assertEqual(result["status"], "partially-upgraded")
        self.assertFalse(result["regression"]["checks"]["requested-changes-met"])
        self.assertEqual(len(result["unmet_requests"]), 1)
        self.assertRegex(result["unmet_requests"][0], r"^dead code: 1 dead-code finding\(s\) remain")
        self.assertIn("unused_report_helper", (pathlib.Path(result["upgraded_copy"]) / "legacy.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
