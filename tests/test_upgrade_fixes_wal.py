"""Finding W2-UP-02: SQLite databases in WAL mode survive an upgrade intact.

`tests/fixtures/upgrade/taskapp-wal` is an overlay for the taskapp fixture: `data/tasks.store`
in WAL mode with five committed rows still in `tasks.store-wal` (305 rows; the main file alone
holds 300). Before the fix the upgrade read the data with `immutable=1` (300 rows), migrated
the main file only and left the stale `-wal` beside it: the report said "upgraded" with 300 rows
preserved while the upgraded copy opened as "database disk image is malformed". Now every copy
goes through `snapshot_database` (byte copy of the file and its `-wal`/`-journal` into a private
directory, the sqlite3 backup API, `PRAGMA integrity_check` and a per-table row-count
comparison) and the migrated file replaces the copy's stale companions.
"""

import hashlib
import pathlib
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

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
TASKAPP = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
OVERLAY = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp-wal"
NOW = 1_800_000_000


def digest(root):
    root = pathlib.Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def count(path):
    conn = sqlite3.connect(path)
    try:
        return (conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], conn.execute("PRAGMA integrity_check").fetchone()[0],
                conn.execute("PRAGMA journal_mode").fetchone()[0],
                sorted(row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")))
    finally:
        conn.close()


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-w2up02-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def pair(self, name="db"):
        directory = self.base / name
        directory.mkdir()
        for suffix in ("", "-wal"):
            shutil.copyfile(OVERLAY / "data" / f"tasks.store{suffix}", directory / f"tasks.store{suffix}")
        return directory / "tasks.store"


class Snapshot(_Base):
    def test_overlay_is_a_pending_wal(self):
        self.assertEqual(engine._pending(OVERLAY / "data" / "tasks.store"), ["-wal"])
        self.assertEqual(engine.data_manifest(OVERLAY / "data" / "tasks.store")["tables"]["tasks"]["rows"], 300)

    def test_snapshot_applies_the_wal_and_never_touches_the_source_directory(self):
        source = self.pair()
        before = digest(source.parent)
        info = engine.snapshot_database(source, self.base / "copy.db", self.base / "staging")
        self.assertEqual(digest(source.parent), before)
        self.assertEqual(sorted(p.name for p in source.parent.iterdir()), ["tasks.store", "tasks.store-wal"])
        self.assertEqual((info["journal_mode"], info["companions"], info["rows"], info["integrity"]), ("wal", ["-wal"], {"tasks": 305}, "ok"))
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["copy.db", "db"])
        self.assertEqual(count(self.base / "copy.db"), (305, "ok", "wal", []))

    def test_manifest_counts_committed_wal_frames_only_through_a_snapshot(self):
        source = self.pair()
        partial = engine.data_manifest(source)
        self.assertEqual((partial["tables"]["tasks"]["rows"], partial["complete"], partial["companions"]), (300, False, ["-wal"]))
        full = engine.data_manifest(source, staging=self.base / "staging")
        self.assertEqual((full["tables"]["tasks"]["rows"], full["complete"], full["companions"]), (305, True, ["-wal"]))
        self.assertFalse((self.base / "staging").exists())
        problems, _ = engine.data_preserved(full, source)
        self.assertEqual(problems, ["table tasks: 305 rows before, 300 after",
                                    "read without its -wal companion: committed data is unproven"])
        self.assertEqual(engine.data_preserved(full, source, self.base / "staging")[0], [])

    def test_a_corrupt_database_or_a_row_count_mismatch_fails_closed(self):
        source = self.pair()
        data = bytearray(source.read_bytes())
        data[4096 + 8:4096 + 64] = b"\xff" * 56  # a b-tree page header
        source.write_bytes(bytes(data))
        with self.assertRaises(UpgradeError) as caught:
            engine.snapshot_database(source, self.base / "copy.db", self.base / "staging")
        self.assertRegex(str(caught.exception), "integrity_check|could not be copied consistently")
        healthy = self.pair("healthy")
        with mock.patch.object(engine, "_row_counts", side_effect=[{"tasks": 305}, {"tasks": 300}]), self.assertRaises(UpgradeError) as caught:
            engine.snapshot_database(healthy, self.base / "copy2.db", self.base / "staging")
        self.assertIn("row counts", str(caught.exception))

    def test_a_symlinked_companion_is_refused(self):
        source = self.pair()
        (source.parent / "tasks.store-shm").symlink_to(self.base / "elsewhere")
        with self.assertRaises(UpgradeError):
            engine.snapshot_database(source, self.base / "copy.db", self.base / "staging")

    def test_migration_returns_one_complete_file_with_the_wal_rows(self):
        source = self.pair()
        before = digest(source.parent)
        data, proof = engine.migrate_database(source, "CREATE INDEX IF NOT EXISTS i ON tasks (status);", "DROP INDEX IF EXISTS i;",
                                              self.base / "work")
        self.assertEqual(digest(source.parent), before)
        self.assertEqual((proof["before"]["tables"]["tasks"]["rows"], proof["down_verified"], proof["copy"]["rows"]), (305, True, {"tasks": 305}))
        shipped = self.base / "shipped.db"
        shipped.write_bytes(data)
        self.assertEqual(count(shipped), (305, "ok", "wal", ["i"]))


class WalUpgrade(_Base):
    @classmethod
    def setUpClass(cls):
        cls.tmp_class = tempfile.TemporaryDirectory(prefix="gaie-w2up02u-", dir="/tmp")
        base = pathlib.Path(cls.tmp_class.name)
        cls.target = base / "target"
        shutil.copytree(TASKAPP, cls.target)
        shutil.copytree(OVERLAY, cls.target, dirs_exist_ok=True)
        (cls.target / "README.md").unlink()
        (base / "home").mkdir(mode=0o700)
        cls.before = digest(cls.target)
        cls.result = upgrade(cls.target, command="Upgrade the task management system", workdir=base / "wd", now=NOW,
                             environ={"GAIE_HOME": str(base / "home")})
        cls.copy = pathlib.Path(cls.result["upgraded_copy"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp_class.cleanup()

    def test_the_upgraded_wal_database_opens_with_every_committed_row(self):
        self.assertEqual(self.result["status"], "upgraded")
        self.assertIn("performance-query-indexes", self.result["applied"])
        self.assertEqual(sorted(p.name for p in (self.copy / "data").iterdir()), ["tasks.db", "tasks.store"])
        self.assertEqual(count(self.copy / "data" / "tasks.store"), (305, "ok", "wal", ["idx_tasks_status_created_at"]))

    def test_the_data_proof_counts_the_wal_rows(self):
        data = self.result["regression"]["data"]["data/tasks.store"]
        self.assertTrue(data["preserved"])
        self.assertEqual((data["tables"]["tasks"]["rows_before"], data["tables"]["tasks"]["rows_after"]), (305, 305))
        self.assertEqual(self.result["baseline"]["data"]["data/tasks.store"]["companions"], ["-wal"])
        migration = next(m for s in self.result["steps"] for m in s.get("migrations", []) if m["database"] == "data/tasks.store")
        self.assertEqual(migration["rows"], {"tasks": 305})

    def test_the_original_is_unchanged_and_the_rollback_restores_the_wal(self):
        self.assertEqual(digest(self.target), self.before)
        self.assertFalse((self.target / "data" / "tasks.store-shm").exists())
        self.assertTrue(self.result["regression"]["checks"]["original-unchanged"])
        self.assertTrue(self.result["rollback"]["verified"])
        restore = self.result["rollback"]["files"]["data/tasks.store-wal"]
        self.assertIsNone(restore["upgraded_sha256"])
        self.assertEqual(restore["restore_from"], "rollback/data/tasks.store-wal")
        saved = pathlib.Path(self.result["run_dir"]) / "rollback" / "data" / "tasks.store-wal"
        self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), self.before["data/tasks.store-wal"])

    def test_a_wal_database_that_fails_its_integrity_check_stops_the_upgrade(self):
        target = self.base / "broken"
        shutil.copytree(self.target, target)
        data = bytearray((target / "data" / "tasks.store").read_bytes())
        data[4096 + 8:4096 + 64] = b"\xff" * 56
        (target / "data" / "tasks.store").write_bytes(bytes(data))
        (self.base / "home").mkdir(mode=0o700)
        with self.assertRaises(UpgradeError) as caught:
            upgrade(target, command="Upgrade the task management system", workdir=self.base / "wd", now=NOW,
                    environ={"GAIE_HOME": str(self.base / "home")})
        self.assertIn("tasks.store", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
