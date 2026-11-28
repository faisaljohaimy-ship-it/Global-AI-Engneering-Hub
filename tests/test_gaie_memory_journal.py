"""SEC-10: the frozen portable journal of gaie_memory opens its file the way the unified memory does.

The journal (entries.jsonl, used when gaie_memory.py is vendored alone and as the import source of the engine) must
be a regular file the caller owns, with one link and mode 0600, in caller-owned 0700 directories. Each negative case
plants the defect first (a symbolic link, a hard link to another file, a FIFO, a shared directory, a loose mode,
another owner) and checks that nothing is written and that the planted file keeps its bytes. Everything runs in
private temporary directories; no network, no model.
"""
import ast
import datetime
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import gaie_memory  # noqa: E402

NOW = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)


def in_thread(function, seconds=15):
    """(finished, result or exception) of function run in a daemon thread, so a blocking open cannot hang the suite."""
    box = {}

    def target():
        try:
            box["value"] = function()
        except Exception as error:  # noqa: BLE001 - handed back to the test
            box["value"] = error
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    return not thread.is_alive(), box.get("value")


class JournalBase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-j-")
        self.addCleanup(temporary.cleanup)
        self.tmp = pathlib.Path(temporary.name)
        os.chmod(self.tmp, 0o700)
        self.home = self.tmp / "home"
        self.home.mkdir(mode=0o700)
        self.memory = gaie_memory.Memory("demo", {"GAIE_HOME": str(self.home)})
        self.outside = self.tmp / "outside.txt"

    def private_dirs(self):
        for directory in (self.memory.root.parent, self.memory.root):
            directory.mkdir(mode=0o700, exist_ok=True)
            os.chmod(directory, 0o700)

    def add(self, title="Slow query", body="Missing index on created_at"):
        return gaie_memory._journal_add(self.memory, "root-cause", title, body, ["db"], [], [], NOW)

    def refused(self, *needles):
        with self.assertRaises(gaie_memory.MemoryError_) as caught:
            self.add()
        for needle in needles:
            self.assertIn(needle, str(caught.exception))
        return str(caught.exception)


class FreshJournalTests(JournalBase):
    def test_a_fresh_journal_is_private_and_chains(self):
        previous = os.umask(0)
        try:
            first = self.add()
            second = self.add("Add index", "Index on created_at")
        finally:
            os.umask(previous)
        self.assertEqual((first["status"], second["status"]), ("stored", "stored"))
        self.assertEqual(stat.S_IMODE(self.memory.journal.stat().st_mode), 0o600)
        for directory in (self.memory.root.parent, self.memory.root):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700, directory.name)
        rows = gaie_memory._journal_rows(self.memory)
        self.assertEqual([row["title"] for row in rows], ["Slow query", "Add index"])
        self.assertEqual(rows[1]["previous"], first["id"])
        self.assertEqual(self.add()["status"], "duplicate")

    def test_a_missing_journal_reads_as_empty_and_creates_nothing(self):
        self.assertEqual(gaie_memory._journal_rows(self.memory), [])
        self.assertFalse(self.memory.root.parent.exists())

    def test_the_portable_copy_stays_standalone(self):
        """Vendored alone, gaie_memory.py may import only the standard library and the router beside it."""
        tree = ast.parse((ROOT / "engineering_os/gaie_memory.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add(node.module.split(".")[0])
        self.assertEqual(names - set(sys.stdlib_module_names), {"gaie_router"})


class LinkTests(JournalBase):
    def test_a_hard_linked_journal_is_refused_and_the_other_file_keeps_its_bytes(self):
        self.private_dirs()
        self.outside.write_bytes(b"")
        os.chmod(self.outside, 0o600)
        os.link(self.outside, self.memory.journal)
        message = self.refused("2 links", "Fix: cp")
        self.assertIn('"$GAIE_HOME/memory/demo/entries.jsonl"', message)
        self.assertEqual(self.outside.stat().st_size, 0)
        with self.assertRaises(gaie_memory.MemoryError_):
            gaie_memory._journal_rows(self.memory)

    def test_a_symlinked_journal_is_refused(self):
        self.private_dirs()
        self.outside.write_text("owner data\n")
        self.memory.journal.symlink_to(self.outside)
        self.refused("symlink")
        self.assertEqual(self.outside.read_text(), "owner data\n")

    def test_a_dangling_symlink_does_not_create_its_target(self):
        self.private_dirs()
        self.memory.journal.symlink_to(self.outside)
        self.refused("symlink")
        self.assertFalse(self.outside.exists())

    def test_a_symlinked_project_directory_is_refused(self):
        self.memory.root.parent.mkdir(mode=0o700)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        self.memory.root.symlink_to(elsewhere, target_is_directory=True)
        self.refused("symlink")
        self.assertEqual(list(elsewhere.iterdir()), [])


class ModeTests(JournalBase):
    def test_a_journal_open_to_others_is_refused_with_the_fix(self):
        self.add()
        os.chmod(self.memory.journal, 0o644)
        before = self.memory.journal.read_bytes()
        self.refused("open to other users", 'chmod 600 "$GAIE_HOME/memory/demo/entries.jsonl"')
        self.assertEqual(self.memory.journal.read_bytes(), before)
        with self.assertRaises(gaie_memory.MemoryError_):
            gaie_memory._journal_rows(self.memory)
        os.chmod(self.memory.journal, 0o600)  # the named fix restores normal use
        self.assertEqual(self.add("Add index", "Index on created_at")["status"], "stored")

    def test_a_group_writable_project_directory_is_refused_and_nothing_is_written(self):
        self.private_dirs()
        os.chmod(self.memory.root, 0o770)
        self.refused("open to other users", 'chmod 700 "$GAIE_HOME/memory/demo"')
        self.assertFalse(self.memory.journal.exists())

    def test_a_shared_memory_directory_is_refused(self):
        self.private_dirs()
        os.chmod(self.memory.root.parent, 0o755)
        self.refused('"$GAIE_HOME/memory"')
        self.assertFalse(self.memory.journal.exists())

    def test_a_home_others_can_write_is_refused_before_anything_is_created(self):
        os.chmod(self.home, 0o777)
        self.refused("chmod go-w")
        self.assertFalse(self.memory.root.parent.exists())

    def test_a_readable_home_is_still_accepted(self):
        os.chmod(self.home, 0o755)
        self.assertEqual(self.add()["status"], "stored")


class SpecialFileTests(JournalBase):
    def test_a_fifo_in_place_of_the_journal_is_refused_without_blocking(self):
        self.private_dirs()
        os.mkfifo(self.memory.journal, 0o600)
        finished, result = in_thread(self.add)
        self.assertTrue(finished, "the append blocked on a FIFO")
        self.assertIsInstance(result, gaie_memory.MemoryError_)
        self.assertIn("not a regular file", str(result))
        finished, result = in_thread(lambda: gaie_memory._journal_rows(self.memory))
        self.assertTrue(finished, "the read blocked on a FIFO")
        self.assertIsInstance(result, gaie_memory.MemoryError_)

    def test_a_directory_in_place_of_the_journal_is_refused(self):
        self.private_dirs()
        self.memory.journal.mkdir(mode=0o700)
        self.refused()
        with self.assertRaises(gaie_memory.MemoryError_):
            gaie_memory._journal_rows(self.memory)


@unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "changing a file's owner needs root")
class OwnerTests(JournalBase):
    def test_a_journal_owned_by_another_user_is_refused(self):
        self.add()
        os.chown(self.memory.journal, 65534, 65534)
        before = self.memory.journal.read_bytes()
        self.refused("owned by another user")
        self.assertEqual(self.memory.journal.read_bytes(), before)

    def test_a_project_directory_owned_by_another_user_is_refused(self):
        self.private_dirs()
        os.chown(self.memory.root, 65534, 65534)
        self.refused("owned by another user")
        self.assertFalse(self.memory.journal.exists())


class EngineImportTests(JournalBase):
    @unittest.skipIf(gaie_memory.ENGINE is None, "the unified engine is not importable here")
    def test_the_engine_refuses_to_import_a_hard_linked_legacy_journal(self):
        self.add()
        data = self.memory.journal.read_bytes()
        self.memory.journal.unlink()
        self.outside.write_bytes(data)
        os.chmod(self.outside, 0o600)
        os.link(self.outside, self.memory.journal)
        with self.assertRaises(gaie_memory.MemoryError_):
            gaie_memory.Memory("demo", {"GAIE_HOME": str(self.home)}).entries()
        self.assertEqual(self.outside.read_bytes(), data)


def tree(root):
    """{relative path: (mode, size, mtime_ns)} of everything under root (nothing when root is missing)."""
    found = {}
    for directory, names, files in os.walk(root):
        for name in names + files:
            path = pathlib.Path(directory) / name
            info = path.lstat()
            found[str(path.relative_to(root))] = (info.st_mode, info.st_size, info.st_mtime_ns)
    return found


@unittest.skipIf(gaie_memory.ENGINE is None, "the unified engine is not importable here")
class ReadOnlyCommandTests(JournalBase):
    """pr30-authz F2: read commands create nothing (no directory, lock file, persisted migration or import)."""

    READS = (("entries",), ("search", "index"), ("brief",), ("next_steps",), ("where", "Cart.total"), ("why", "queue"),
             ("recall_failure", "TimeoutError"), ("solutions",))

    def run_reads(self):
        facade = gaie_memory.Memory("demo", {"GAIE_HOME": str(self.home)})
        outcomes = []
        for method, *args in self.READS:
            try:
                if method == "entries":
                    outcomes.append(facade.entries())
                elif method == "search":
                    outcomes.append(facade.search(*args))
                else:
                    outcomes.append(facade.call(method, *args, create=False))
            except gaie_memory.MemoryError_ as error:
                outcomes.append(str(error))
        return outcomes

    def assert_unchanged(self):
        before = tree(self.home)
        outcomes = self.run_reads()
        self.assertEqual(tree(self.home), before)
        return outcomes

    def test_a_project_with_no_memory_reads_as_empty_and_creates_nothing(self):
        outcomes = self.assert_unchanged()
        self.assertEqual(outcomes[:2], [[], []])
        self.assertEqual(tree(self.home), {})

    def test_reading_a_store_without_its_lock_file_creates_no_lock(self):
        facade = gaie_memory.Memory("demo", {"GAIE_HOME": str(self.home)})
        facade.add("decision", "Queue jobs", "Use a durable queue for slow work", ["queue"])
        (facade.root / "memory.lock").unlink()
        outcomes = self.assert_unchanged()
        self.assertEqual([row["title"] for row in outcomes[0]], ["Queue jobs"])
        self.assertFalse((facade.root / "memory.lock").exists())

    def test_reading_a_schema_1_store_does_not_persist_its_migration(self):
        from engineering_os.orchestration import sha
        self.private_dirs()
        state = {"schema_version": 1, "revision": 0, "records": {}}
        state["sha256"] = sha(state)
        legacy = self.memory.root / "memory.json"
        legacy.write_text(json.dumps(state) + "\n")
        os.chmod(legacy, 0o600)
        outcomes = self.assert_unchanged()
        self.assertEqual(outcomes[:2], [[], []])
        self.assertFalse((self.memory.root / "memory.jsonl").exists())

    def test_an_imported_legacy_journal_is_not_imported_or_locked_again(self):
        self.add()
        facade = gaie_memory.Memory("demo", {"GAIE_HOME": str(self.home)})
        self.assertEqual([row["title"] for row in facade.entries()], ["Slow query"])
        self.assertEqual(facade.import_report, {"imported": 1, "refused": 0})
        (facade.root / "memory.lock").unlink()
        outcomes = self.assert_unchanged()
        self.assertEqual([row["title"] for row in outcomes[0]], ["Slow query"])

    def test_the_portable_copy_reads_without_creating_anything(self):
        engine = self.tmp / "engine"
        engine.mkdir()
        for source, name in {"engineering_os/gaie_memory.py": "gaie_memory.py", "engineering_os/gaie_router.py": "gaie_router.py",
                             "governance/policies/gaie-routes.json": "gaie-routes.json", "projects/registry.json": "projects.json",
                             "projects/aliases.json": "aliases.json"}.items():
            shutil.copyfile(ROOT / source, engine / name)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GAIE_HOME": str(self.home), "LANG": "C.UTF-8"}
        done = subprocess.run([sys.executable, str(engine / "gaie_memory.py"), "--project", "demo", "search", "index"],
                              capture_output=True, text=True, env=env, cwd=self.tmp, timeout=60)
        self.assertEqual((done.returncode, json.loads(done.stdout)), (0, []), done.stderr)
        self.assertEqual(tree(self.home), {})


WRITER = """
import os, sys, pathlib
sys.path.insert(0, sys.argv[1])
from engineering_os import gaie_memory
home, name, count, gate = sys.argv[2], sys.argv[3], int(sys.argv[4]), pathlib.Path(sys.argv[5])
memory = gaie_memory.Memory("demo", {"GAIE_HOME": home})
while not gate.exists():
    pass
stored = 0
for number in range(count):
    result = gaie_memory._journal_add(memory, "lesson", f"{name} entry {number}", f"written by {name}", [], [], [], None)
    stored += result["status"] == "stored"
print(stored)
"""


class ConcurrentAppendTests(JournalBase):
    """w2-memory-heal-orch M1: two processes appending at once both land every entry and the chain verifies."""

    def test_two_writers_land_every_entry_and_the_journal_verifies(self):
        count, gate = 12, self.tmp / "go"
        writers = [subprocess.Popen([sys.executable, "-c", WRITER, str(ROOT), str(self.home), name, str(count), str(gate)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for name in ("alpha", "beta")]
        gate.touch()
        results = [writer.communicate(timeout=120) for writer in writers]
        for writer, (out, err) in zip(writers, results):
            self.assertEqual((writer.returncode, out.strip()), (0, str(count)), err[-2000:])
        rows = gaie_memory._journal_rows(self.memory)
        self.assertEqual(len(rows), 2 * count)
        self.assertEqual(len({row["previous"] for row in rows}), 2 * count)
        self.assertEqual(stat.S_IMODE((self.memory.root / gaie_memory.JOURNAL_LOCK).stat().st_mode), 0o600)
        if gaie_memory.ENGINE is not None:
            facade = gaie_memory.Memory("demo", {"GAIE_HOME": str(self.home)})
            self.assertEqual(len(facade.entries()), 2 * count)

    def test_a_hard_linked_lock_file_is_refused(self):
        self.private_dirs()
        self.outside.write_bytes(b"")
        os.chmod(self.outside, 0o600)
        os.link(self.outside, self.memory.root / gaie_memory.JOURNAL_LOCK)
        self.refused("memory journal lock", "links")
        self.assertFalse(self.memory.journal.exists())


class PortableSecretTests(JournalBase):
    """The portable journal refuses the credential shapes the engine refuses, Arabic-touching ones included."""
    AWS = "AK" + "IA" + "IOSFODNN7EXAMPLE"

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(gaie_memory, "ENGINE", None)  # as when the file is vendored alone
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_keys_touching_arabic_letters_or_underscores_are_refused(self):
        for body in ["و" + self.AWS, self.AWS + "هنا", "aws_" + self.AWS, "رمز" + "gh" + "p_" + "a" * 36,
                     "مفتاح" + "sk_" + "live_" + "a" * 24, "رمز" + "ey" + "J" + "a" * 12 + "." + "b" * 24 + "." + "c" * 24,
                     "كلمة المرور: " + "Sup3rS3cretValue", "كَلِمَةُ الْمُرُورِ: " + "Sup3rS3cretValue"]:
            with self.subTest(body=body[:6]):
                with self.assertRaises(gaie_memory.MemoryError_) as caught:
                    self.memory.add("lesson", "Key", body, now=NOW)
                self.assertIn("credential", str(caught.exception))
        self.assertFalse(self.memory.journal.exists())

    def test_ascii_words_and_arabic_prose_stay_storable(self):
        for body in ["disk-usage-monitoring-dashboard-panel-view", "risk_live_dashboard_metrics_view_extra",
                     "X" + self.AWS + "YZ", "كلمة المرور يجب أن تكون طويلة"]:
            with self.subTest(body=body):
                self.assertEqual(self.memory.add("lesson", body[:20], body, now=NOW)["status"], "stored")

    def test_engine_and_portable_patterns_are_identical(self):
        from engineering_os import memory as engine
        self.assertEqual(gaie_memory.SECRET.pattern, engine.BROAD_SECRET.pattern)
        self.assertEqual(gaie_memory.SECRET.flags, engine.BROAD_SECRET.flags)
        self.assertEqual(gaie_memory._ARABIC_MARKS.pattern, engine._ARABIC_MARKS.pattern)


class VendoredAloneTests(JournalBase):
    def vendor(self):
        engine = self.tmp / "engine"
        engine.mkdir()
        for source, name in {"engineering_os/gaie_memory.py": "gaie_memory.py", "engineering_os/gaie_router.py": "gaie_router.py",
                             "governance/policies/gaie-routes.json": "gaie-routes.json", "projects/registry.json": "projects.json",
                             "projects/aliases.json": "aliases.json"}.items():
            shutil.copyfile(ROOT / source, engine / name)
        return engine

    def test_the_vendored_journal_cli_refuses_an_arabic_touching_key(self):
        engine = self.vendor()
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GAIE_HOME": str(self.home), "LANG": "C.UTF-8"}
        base = [sys.executable, str(engine / "gaie_memory.py"), "--project", "demo", "add", "--kind", "lesson", "--title"]
        first = subprocess.run(base + ["Portable", "--body", "Vendored alone"], capture_output=True, text=True, env=env,
                               cwd=self.tmp, timeout=60)
        self.assertEqual((first.returncode, json.loads(first.stdout)["status"]), (0, "stored"), first.stderr)
        before = self.memory.journal.read_bytes()
        refused = subprocess.run(base + ["Key", "--body", "و" + PortableSecretTests.AWS], capture_output=True, text=True,
                                 env=env, cwd=self.tmp, timeout=60)
        self.assertEqual((refused.returncode, json.loads(refused.stdout)["status"]), (1, "error"))
        self.assertEqual(self.memory.journal.read_bytes(), before)
        self.assertNotIn(PortableSecretTests.AWS.encode(), self.memory.journal.read_bytes())

    def test_the_vendored_journal_cli_refuses_a_hard_link(self):
        engine = self.vendor()
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GAIE_HOME": str(self.home), "LANG": "C.UTF-8"}
        cli = [sys.executable, str(engine / "gaie_memory.py"), "--project", "demo", "add", "--kind", "lesson",
               "--title", "Portable", "--body", "Vendored alone"]
        first = subprocess.run(cli, capture_output=True, text=True, env=env, cwd=self.tmp, timeout=60)
        self.assertEqual((first.returncode, json.loads(first.stdout)["status"]), (0, "stored"), first.stderr)
        self.outside.write_bytes(b"")
        self.memory.journal.rename(self.tmp / "moved.jsonl")
        os.link(self.outside, self.memory.journal)
        second = subprocess.run(cli, capture_output=True, text=True, env=env, cwd=self.tmp, timeout=60)
        self.assertEqual(second.returncode, 1)
        self.assertIn("links", json.loads(second.stdout)["error"])
        self.assertEqual(self.outside.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
