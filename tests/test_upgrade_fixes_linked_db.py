"""Re-check of W2-UP-02 (low, pre-existing): a listed database reached through a symlink is never dropped silently.

`detectors.list_files` skips symlinks, so a database that `gaie-upgrade.json` lists but that is a
relative symlink inside the target (or lies under a symlinked directory) left the data proof
without a word: the run ended "upgraded" with only the other databases proven. Now such a run
is refused before anything is copied, in upgrade and audit mode, and a listed database that is
simply absent is named in `baseline.databases_missing`.

Re-check 2 (low): a listed database that exists under a skipped directory (venv/) was reported
only in `databases_missing` (mislabelled) and the run still ended "upgraded" with every check
true. It is now `baseline.databases_skipped` (status `skipped-by-policy`, with the reason), the
data proof lists it as not preserved (so `data-preserved` is false and the upgrade is
`rejected`), and both summaries name it.
"""

import hashlib
import json
import os
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
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
NOW = 1_800_000_000


def digest(root):
    root = pathlib.Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file() and not path.is_symlink()}


class LinkedDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-ld-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)
        self.target = self.base / "target"
        shutil.copytree(FIXTURES / "taskapp", self.target)
        shutil.copyfile(FIXTURES / "taskapp-wal" / "gaie-upgrade.json", self.target / "gaie-upgrade.json")  # lists data/tasks.store
        (self.base / "home").mkdir(mode=0o700)
        self.environ = {"GAIE_HOME": str(self.base / "home")}

    def tearDown(self):
        self.tmp.cleanup()

    def refused(self, command, name):
        before = digest(self.target)
        with self.assertRaises(UpgradeError) as caught:
            upgrade(self.target, command=command, workdir=self.base / name, now=NOW, environ=self.environ)
        self.assertFalse((self.base / name).exists())
        self.assertEqual(digest(self.target), before)
        return str(caught.exception)

    def test_a_symlinked_listed_database_is_refused_in_upgrade_and_audit(self):
        shutil.copyfile(self.target / "data" / "tasks.db", self.target / "data" / "real.store")
        os.symlink("real.store", self.target / "data" / "tasks.store")
        for number, command in enumerate(("Upgrade the task management system", "Audit the task management system")):
            with self.subTest(command=command):
                message = self.refused(command, f"wd-{number}")
                self.assertIn("Database data/tasks.store listed in gaie-upgrade.json is reached through the symlink data/tasks.store", message)

    def test_a_listed_database_under_a_symlinked_directory_is_refused(self):
        (self.base / "store").mkdir()
        shutil.copyfile(self.target / "data" / "tasks.db", self.base / "store" / "tasks.store")
        shutil.move(str(self.base / "store"), str(self.target / "real-data"))
        shutil.move(str(self.target / "data" / "tasks.db"), str(self.target / "real-data" / "tasks.db"))
        (self.target / "data").rmdir()
        os.symlink("real-data", self.target / "data")
        message = self.refused("Upgrade the task management system", "wd")
        self.assertIn("is reached through the symlink data;", message)

    def test_a_listed_database_that_is_absent_is_named(self):
        result = upgrade(self.target, command="Audit the task management system", workdir=self.base / "audit", now=NOW,
                         environ=self.environ)
        self.assertEqual(result["status"], "audited")
        self.assertEqual(result["baseline"]["databases_missing"], ["data/tasks.store"])
        self.assertEqual(sorted(result["baseline"]["data"]), ["data/tasks.db"])


class SkippedByPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-sp-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)
        self.target = self.base / "target"
        shutil.copytree(FIXTURES / "taskapp", self.target)
        (self.target / "venv").mkdir()
        shutil.copyfile(self.target / "data" / "tasks.db", self.target / "venv" / "tasks.db")
        manifest = json.loads((self.target / "gaie-upgrade.json").read_text(encoding="utf-8"))
        manifest["databases"] = ["data/tasks.db", "venv/tasks.db"]
        (self.target / "gaie-upgrade.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.base / "home").mkdir(mode=0o700)
        self.environ = {"GAIE_HOME": str(self.base / "home")}
        self.reason = "it lies under venv/, a directory the engine never copies, reads or proves"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_listed_database_under_a_skipped_directory_makes_the_upgrade_unproven(self):
        before = digest(self.target)
        result = upgrade(self.target, command="Upgrade the task management system", workdir=self.base / "wd", now=NOW,
                         environ=self.environ)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual([name for name, ok in result["regression"]["checks"].items() if not ok], ["data-preserved"])
        self.assertEqual(result["baseline"]["databases_missing"], [])
        self.assertEqual(result["baseline"]["databases_skipped"],
                         [{"path": "venv/tasks.db", "status": "skipped-by-policy", "reason": self.reason}])
        row = result["regression"]["data"]["venv/tasks.db"]
        self.assertEqual((row["preserved"], row["status"]), (False, "skipped-by-policy"))
        self.assertTrue(result["regression"]["data"]["data/tasks.db"]["preserved"])
        self.assertIn(f"skipped by policy, data unproven: venv/tasks.db ({self.reason})", result["summary"]["en"])
        self.assertIn("venv/tasks.db", result["summary"]["ar"])
        self.assertEqual(digest(self.target), before)

    def test_the_audit_names_it_as_skipped_not_missing(self):
        result = upgrade(self.target, command="Audit the task management system", workdir=self.base / "audit", now=NOW,
                         environ=self.environ)
        self.assertEqual(result["status"], "audited")
        self.assertEqual((result["baseline"]["databases_missing"], [row["path"] for row in result["baseline"]["databases_skipped"]]),
                         ([], ["venv/tasks.db"]))
        self.assertIn("skipped by policy, data unproven: venv/tasks.db", result["summary"]["en"])

    def test_each_reason_a_listed_database_is_left_out(self):
        (self.target / "node_modules" / "cache").mkdir(parents=True)
        (self.target / "node_modules" / "cache" / "x.db").write_bytes(b"")
        (self.target / "real").mkdir()
        os.symlink("real", self.target / "linked")
        (self.target / "linked" / "y.db").write_bytes(b"")
        (self.target / "data" / "dir.db").mkdir()
        (self.target / "data" / "z.db.pyc").write_bytes(b"")
        cases = {"data/absent.db": ("absent", "no file at this path in the target"),
                 "venv/absent.db": ("absent", "no file at this path in the target"),
                 "node_modules/cache/x.db": ("skipped-by-policy", "it lies under node_modules/, a directory the engine never copies, "
                                                                  "reads or proves"),
                 "linked/y.db": ("skipped-by-policy", "it is reached through the symlink linked, which the engine never follows"),
                 "data/dir.db": ("skipped-by-policy", "it is not a regular file"),
                 "data/z.db.pyc": ("skipped-by-policy", "it has a compiled-cache name the engine never copies")}
        for rel, expected in cases.items():
            with self.subTest(rel):
                self.assertEqual(engine._left_out(self.target, rel), expected)


if __name__ == "__main__":
    unittest.main()
