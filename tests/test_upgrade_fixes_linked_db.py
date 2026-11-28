"""Re-check of W2-UP-02 (low, pre-existing): a listed database reached through a symlink is never dropped silently.

`detectors.list_files` skips symlinks, so a database that `gaie-upgrade.json` lists but that is a
relative symlink inside the target (or lies under a symlinked directory) left the data proof
without a word: the run ended "upgraded" with only the other databases proven. Now such a run
is refused before anything is copied, in upgrade and audit mode, and a listed database that is
simply absent is named in `baseline.databases_missing`.
"""

import hashlib
import os
import pathlib
import shutil
import tempfile
import unittest

from engineering_os.upgrade_engine import UpgradeError, upgrade

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


if __name__ == "__main__":
    unittest.main()
