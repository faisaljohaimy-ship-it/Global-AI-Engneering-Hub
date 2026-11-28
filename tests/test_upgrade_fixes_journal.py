"""Re-check of W2-UP-02: a target's rollback journal never reaches SQLite in the engine process.

The W2-UP-02 fix copied a database's `-journal` next to its private copy and opened it normally.
SQLite rolled the hot journal back and then deleted the file the journal names as its
super-journal: a crafted 16-byte record naming any path the operator may delete was enough
(the reviewer's PoC: the run still ended "upgraded" and the operator file was gone).
`snapshot_database` now reads the journal as bytes first and refuses a journal that is hot or
carries a super-journal record before SQLite opens anything; an inert journal (TRUNCATE or
PERSIST residue) is never copied. A `-wal` is opened only when its header and checksum verify.
Everything here is generated from the synthetic taskapp fixture in temporary directories.
"""

import hashlib
import pathlib
import shutil
import sqlite3
import struct
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
TASKAPP = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
WAL_PAIR = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp-wal" / "data"
DB = TASKAPP / "data" / "tasks.db"
MAGIC = bytes.fromhex("d9d505f920a163d7")
NOW = 1_800_000_000
COMMAND = "Upgrade the task management system"


def digest(root):
    root = pathlib.Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def crashed_journal(directory):
    """The -journal bytes a crash leaves in the middle of a write transaction (the main file already half-written)."""
    work = directory / "throwaway.db"
    shutil.copyfile(DB, work)
    conn = sqlite3.connect(work, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA cache_size=1")  # dirty pages spill into the main file before the commit
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE tasks SET title = 'HALF-WRITTEN ' || title")
        conn.execute("DELETE FROM tasks WHERE id > 150")
        main, journal = work.read_bytes(), pathlib.Path(f"{work}-journal").read_bytes()
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    return main, journal


def super_record(name):
    """<name><u32 length><u32 checksum><magic>: the record a multi-database transaction appends to each child journal."""
    data = str(name).encode()
    return data + struct.pack(">I", len(data)) + struct.pack(">I", sum(data) & 0xFFFFFFFF) + MAGIC


def rows(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        return conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    finally:
        conn.close()


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-sj-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)
        self.victim = self.base / "operator-files" / "precious.txt"
        self.victim.parent.mkdir()
        self.victim.write_text("an operator file outside the target\n")

    def tearDown(self):
        self.tmp.cleanup()

    def database(self, name, journal=None, main=None):
        directory = self.base / name
        directory.mkdir()
        path = directory / "app.db"
        if main is None:
            shutil.copyfile(DB, path)
        else:
            path.write_bytes(main)
        if journal is not None:
            pathlib.Path(f"{path}-journal").write_bytes(journal)
        return path


class Journal(_Base):
    def test_the_crafted_journal_really_is_hot_and_names_the_victim(self):
        _, journal = crashed_journal(self.base)
        self.assertEqual(journal[:8], MAGIC)  # header magic: SQLite plays it back on a normal open
        self.assertTrue(super_record(self.victim).endswith(MAGIC))

    def test_a_super_journal_record_is_refused_and_the_named_file_survives(self):
        _, journal = crashed_journal(self.base)
        source = self.database("target", journal + super_record(self.victim))  # clean main file: the rollback is a no-op
        before = digest(source.parent)
        with self.assertRaises(UpgradeError) as caught:
            engine.snapshot_database(source, self.base / "copy.db", self.base / "staging")
        self.assertIn("super-journal record", str(caught.exception))
        self.assertIn("Refused before SQLite opened it", str(caught.exception))
        self.assertTrue(self.victim.is_file())
        self.assertEqual(digest(source.parent), before)
        self.assertFalse((self.base / "staging").exists())
        self.assertFalse((self.base / "copy.db").exists())

    def test_a_super_journal_record_is_refused_even_in_a_zeroed_journal(self):
        _, journal = crashed_journal(self.base)
        inert = b"\0" * 28 + journal[28:]
        source = self.database("target", inert + super_record(self.victim))
        with self.assertRaises(UpgradeError) as caught:
            engine.snapshot_database(source, self.base / "copy.db", self.base / "staging")
        self.assertIn("super-journal record", str(caught.exception))
        self.assertTrue(self.victim.is_file())

    def test_a_hot_journal_from_a_crash_is_refused_not_rolled_back(self):
        main, journal = crashed_journal(self.base)
        source = self.database("target", journal, main)
        before = digest(source.parent)
        with self.assertRaises(UpgradeError) as caught:
            engine.snapshot_database(source, self.base / "copy.db", self.base / "staging")
        self.assertIn("hot rollback journal", str(caught.exception))
        self.assertEqual(digest(source.parent), before)
        self.assertFalse(engine.data_manifest(source)["complete"])  # the read-only (immutable) path never replays it
        self.assertEqual(digest(source.parent), before)

    def test_inert_truncate_and_persist_journals_are_left_out_and_every_row_is_copied(self):
        _, journal = crashed_journal(self.base)
        for name, residue in (("truncate", b""), ("persist", b"\0" * 512 + journal[512:])):
            with self.subTest(name):
                source = self.database(name, residue)
                before = digest(source.parent)
                info = engine.snapshot_database(source, self.base / f"{name}.db", self.base / "staging")
                self.assertEqual((info["rows"], info["integrity"], info["companions"], info["journal_mode"]),
                                 ({"tasks": 300}, "ok", ["-journal"], "delete"))
                self.assertEqual(digest(source.parent), before)
                self.assertEqual(sorted(p.name for p in self.base.iterdir() if p.name.startswith(name)), [name, f"{name}.db"])
                self.assertEqual(rows(self.base / f"{name}.db"), 300)

    def test_a_real_persist_mode_database_still_snapshots(self):
        source = self.database("persist-real")
        conn = sqlite3.connect(source)
        conn.execute("PRAGMA journal_mode=PERSIST")
        conn.execute("INSERT INTO tasks (title, created_at) VALUES ('transient', 'now')")
        conn.execute("DELETE FROM tasks WHERE title = 'transient'")
        conn.commit()
        conn.close()
        journal = pathlib.Path(f"{source}-journal").read_bytes()
        self.assertTrue(journal and journal[0] == 0)
        self.assertEqual(engine.snapshot_database(source, self.base / "copy.db", self.base / "staging")["rows"], {"tasks": 300})


class Wal(_Base):
    def pair(self, name, wal=None):
        directory = self.base / name
        directory.mkdir()
        shutil.copyfile(WAL_PAIR / "tasks.store", directory / "tasks.store")
        data = (WAL_PAIR / "tasks.store-wal").read_bytes()
        (directory / "tasks.store-wal").write_bytes(data if wal is None else wal(data))
        return directory / "tasks.store"

    def test_a_verified_wal_is_applied(self):
        info = engine.snapshot_database(self.pair("ok"), self.base / "copy.db", self.base / "staging")
        self.assertEqual((info["rows"], info["journal_mode"]), ({"tasks": 305}, "wal"))

    def test_an_empty_wal_holds_nothing_and_the_main_file_is_copied(self):
        info = engine.snapshot_database(self.pair("empty", lambda data: b""), self.base / "copy.db", self.base / "staging")
        self.assertEqual((info["rows"], info["integrity"]), ({"tasks": 300}, "ok"))

    def test_a_wal_whose_header_does_not_verify_is_refused_before_opening(self):
        damaged = {"magic": lambda d: b"\0\0\0\0" + d[4:], "version": lambda d: d[:4] + struct.pack(">I", 1) + d[8:],
                   "checksum": lambda d: d[:24] + bytes(8) + d[32:], "short": lambda d: d[:20]}
        for name, change in damaged.items():
            with self.subTest(name):
                source = self.pair(name, change)
                before = digest(source.parent)
                with self.assertRaises(UpgradeError) as caught:
                    engine.snapshot_database(source, self.base / "copy.db", self.base / "staging")
                self.assertIn("-wal", str(caught.exception))
                self.assertEqual(digest(source.parent), before)
                self.assertFalse((self.base / "staging").exists())


class FullUpgrade(_Base):
    def target(self, journal):
        target = self.base / "target"
        shutil.copytree(TASKAPP, target)
        (target / "data" / "tasks.db-journal").write_bytes(journal)
        (self.base / "home").mkdir(mode=0o700)
        return target

    def run_upgrade(self, target):
        return upgrade(target, command=COMMAND, workdir=self.base / "wd", now=NOW, environ={"GAIE_HOME": str(self.base / "home")})

    def test_the_reviewers_poc_is_refused_and_the_operator_file_survives(self):
        _, journal = crashed_journal(self.base)
        target = self.target(journal + super_record(self.victim))
        before = digest(target)
        with self.assertRaises(UpgradeError) as caught:
            self.run_upgrade(target)
        self.assertIn("tasks.db: its -journal ends in a super-journal record", str(caught.exception))
        self.assertTrue(self.victim.is_file())
        self.assertEqual(self.victim.read_text(), "an operator file outside the target\n")
        self.assertEqual(digest(target), before)

    def test_a_rollback_journal_database_with_an_inert_journal_still_upgrades_with_every_row(self):
        _, journal = crashed_journal(self.base)
        target = self.target(b"\0" * 512 + journal[512:])
        before = digest(target)
        result = self.run_upgrade(target)
        self.assertEqual(result["status"], "upgraded")
        data = result["regression"]["data"]["data/tasks.db"]
        self.assertTrue(data["preserved"])
        self.assertEqual((data["tables"]["tasks"]["rows_before"], data["tables"]["tasks"]["rows_after"]), (300, 300))
        copy = pathlib.Path(result["upgraded_copy"]) / "data"
        self.assertEqual(sorted(p.name for p in copy.iterdir()), ["tasks.db"])  # the stale journal left with the migration
        self.assertEqual(rows(copy / "tasks.db"), 300)
        self.assertEqual(digest(target), before)
        self.assertTrue(self.victim.is_file())


if __name__ == "__main__":
    unittest.main()
