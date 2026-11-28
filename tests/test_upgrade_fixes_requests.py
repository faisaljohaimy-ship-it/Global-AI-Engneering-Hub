"""Finding W2-UP-04: an unparsed, unsettled or ignored request is never reported as met.

Before the fix "Upgrade the task management system and remove the tasks entity" (the parser
cannot apply it: the spec would lose its only entity) and "... remove the Arabic locale" /
«... واحذف اللغة العربية» (the parser has no locale removal, so the diff was empty) each ended
"upgraded" with requested-changes-met true. Now such a request is `unparsed`,
`open-questions` or `unsettled`, the upgrade stops before anything is copied, and the
regression check is true only for a settled (`ok`) request without unmet items.
"""

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from engineering_os import upgrade_engine as engine
from engineering_os.upgrade_engine import UpgradeError, upgrade

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
SPEC = json.loads((FIXTURE / "gaie-spec.json").read_text(encoding="utf-8"))
NOW = 1_800_000_000
NOT_SETTLED = {
    "Upgrade the task management system and remove the tasks entity": "unparsed",
    "طور نظام إدارة المهام واحذف المهام": "unparsed",
    "Upgrade the task management system and remove the Arabic locale": "unsettled",
    "طور نظام إدارة المهام واحذف اللغة العربية": "unsettled",
    "Upgrade the task management system without the Arabic locale": "unsettled",
    "طور نظام إدارة المهام بدون اللغة العربية": "unsettled",
}


class RequestedChanges(unittest.TestCase):
    def test_unparsed_and_ignored_removals_are_not_settled_in_both_languages(self):
        for command, status in NOT_SETTLED.items():
            with self.subTest(command=command):
                requested = engine.requested_changes(command, SPEC)
                self.assertEqual(requested["status"], status)
                self.assertIn(status, engine.UNSETTLED)
                self.assertTrue(requested["unmet"], "what was asked is named as unmet")
        locale = engine.requested_changes("طور نظام إدارة المهام واحذف اللغة العربية", SPEC)
        self.assertEqual(locale["unmet"], ["remove or exclude: واحذف اللغه العربيه"])

    def test_settled_requests_keep_their_status(self):
        cases = {"طور نظام إدارة المهام بالكامل": ("ok", []), "Upgrade the task management system completely": ("ok", []),
                 "طور نظام إدارة المهام وأضف تاريخ الاستحقاق للمهام": ("ok", ["field Task.due_date"]),
                 "Upgrade the task management system and remove priority from tasks": ("refused-breaking", [])}
        for command, (status, unmet) in cases.items():
            with self.subTest(command=command):
                requested = engine.requested_changes(command, SPEC)
                self.assertEqual((requested["status"], requested["unmet"]), (status, unmet))

    def test_a_remove_verb_that_is_not_a_command_is_not_an_exclusion(self):
        requested = engine.requested_changes("Upgrade the task management system so members can delete their own tasks", SPEC)
        self.assertEqual(requested["status"], "ok")
        self.assertEqual(engine._exclusions("Upgrade the task management system so members can delete their own tasks", SPEC), [])

    def test_without_a_specification_a_removal_is_still_not_settled(self):
        self.assertEqual(engine.requested_changes("Upgrade the tool and delete the cache", None)["status"], "unsettled")
        self.assertEqual(engine.requested_changes("Upgrade the tool", None)["status"], "no-specification")


class UpgradeStops(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-w2up04-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)
        (self.base / "home").mkdir(mode=0o700)
        self.environ = {"GAIE_HOME": str(self.base / "home")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_upgrade_stops_before_copying_anything_in_arabic_and_english(self):
        for number, (command, status) in enumerate(NOT_SETTLED.items()):
            workdir = self.base / f"wd-{number}"
            with self.subTest(command=command):
                with self.assertRaises(UpgradeError) as caught:
                    upgrade(FIXTURE, command=command, workdir=workdir, now=NOW, environ=self.environ)
                if "without" in command or "بدون" in command:  # the router already refuses no-change wording next to a mutation
                    self.assertIn("Command not routable", str(caught.exception))
                else:
                    self.assertIn(f"Requested change not settled ({status}", str(caught.exception))
                    self.assertIn("Nothing was copied or changed", str(caught.exception))
                self.assertFalse(workdir.exists())

    def test_an_audit_reports_the_unsettled_request_without_stopping(self):
        result = upgrade(FIXTURE, command="افحص نظام إدارة المهام بدون اللغة العربية", workdir=self.base / "audit", now=NOW,
                         environ=self.environ)
        self.assertEqual(result["status"], "audited")
        self.assertEqual(result["audit"]["requirements"]["status"], "unsettled")

    def test_the_regression_check_is_false_for_any_unsettled_request(self):
        with mock.patch.object(engine, "UNSETTLED", ()):  # bypass the stop: the report itself must not claim the request met
            result = upgrade(FIXTURE, command="Upgrade the task management system and remove the Arabic locale",
                             workdir=self.base / "bypassed", now=NOW, environ=self.environ)
        self.assertFalse(result["regression"]["checks"]["requested-changes-met"])
        self.assertEqual(result["status"], "partially-upgraded")
        self.assertEqual(result["unmet_requests"], ["remove or exclude: remove the arabic locale"])
        self.assertIn("Requested but NOT implemented: remove or exclude: remove the arabic locale", result["summary"]["en"])
        self.assertIn("requested-changes-met: contradicted", result["decision"]["warnings"])


if __name__ == "__main__":
    unittest.main()
