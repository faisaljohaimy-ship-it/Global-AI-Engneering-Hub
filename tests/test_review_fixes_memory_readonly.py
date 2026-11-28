"""Review fix pr30-authz F2 (engineering_os/memory.py part): memory.invoke read actions change nothing on disk.

memory.invoke used to open every side_effect "none" action with for_project(create=False): that took the
lock (creating memory.lock) and migrated a schema-1 store to memory.jsonl. Each read action is now run on
a missing, an empty, a legacy and a v2 store, and the state tree (names, modes, sizes, times and bytes)
is compared before and after. A store that was never written reads as an empty one. Synthetic data only.
"""
import hashlib
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import memory  # noqa: E402
from engineering_os.memory import MemoryStore  # noqa: E402
from engineering_os.orchestration import CoordinationError, _atomic_write, sha  # noqa: E402

READ_ACTIONS = sorted(name for name, spec in memory.ENGINE_RECORD["actions"].items() if spec["side_effect"] == "none")


def tree(root):
    root = pathlib.Path(root)
    if not os.path.lexists(root):
        return None
    listing = {}
    for current, directories, files in os.walk(root):
        for name in (*directories, *files):
            path = pathlib.Path(current) / name
            info = path.lstat()
            data = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else None
            listing[str(path.relative_to(root))] = (info.st_mode, info.st_size, info.st_mtime_ns, data)
    return listing


def payload(action):
    required = memory._ACTIONS[action][1]
    return {"project": "demo", **{key: "x" for key in required}, **({"query": "cents"} if action == "search" else {})}


def outcome(action, state_dir):
    try:
        return "ok", memory.invoke(action, payload(action), {"state_dir": str(state_dir)})
    except Exception as error:  # the same refusal on both sides is also an equal outcome
        return "error", type(error).__name__, str(error)


def record(**changes):
    value = {"project": "demo", "kind": "decision", "title": "Use integer cents", "summary": "Money is stored as integer cents.",
             "tags": ["money"], "symbols": [], "links": [], "provenance": {"engine": "codex", "source_sha256": "a" * 64}}
    value.update(changes)
    return value


class ReadActionsLeaveStateUnchangedTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-f2-")
        self.addCleanup(temporary.cleanup)
        self.tmp = pathlib.Path(temporary.name)
        os.chmod(self.tmp, 0o700)
        self.root = self.tmp / "root"

    def private(self, path):
        for directory in (*reversed(path.relative_to(self.tmp).parents), path.relative_to(self.tmp)):
            (self.tmp / directory).mkdir(mode=0o700, exist_ok=True)
        return path

    def empty_reference(self):
        reference = self.tmp / "reference"
        MemoryStore.for_project(reference, "demo")
        return reference

    def legacy(self, directory):
        first = record()
        first_id = sha({key: value for key, value in first.items() if key != "provenance"})
        second = record(kind="architecture", title="Service layout", links=[first_id])
        second_id = sha({key: value for key, value in second.items() if key != "provenance"})
        records = {key: {"record": value, "provenances": [value["provenance"]], "verification": None}
                   for key, value in ((second_id, second), (first_id, first))}
        state = {"schema_version": 1, "revision": 2, "records": records}
        state["sha256"] = sha(state)
        _atomic_write(self.private(directory) / "memory.json", state)

    def assert_unchanged_and_equal(self, reference):
        for action in READ_ACTIONS:
            with self.subTest(action=action):
                before = tree(self.root)
                result = outcome(action, self.root)
                self.assertEqual(tree(self.root), before, f"{action} changed the memory state on disk")
                self.assertEqual(result, outcome(action, reference))

    def test_the_read_actions_are_the_ones_the_reviewer_named_and_more(self):
        self.assertTrue({"search", "graph", "brief"} <= set(READ_ACTIONS))
        self.assertNotIn("put", READ_ACTIONS)
        self.assertNotIn("checkpoint", READ_ACTIONS)

    def test_a_missing_memory_root_is_never_created_and_reads_as_empty(self):
        self.assert_unchanged_and_equal(self.empty_reference())
        self.assertFalse(os.path.lexists(self.root))

    def test_a_missing_project_directory_is_never_created_and_reads_as_empty(self):
        self.private(self.root)
        self.assert_unchanged_and_equal(self.empty_reference())
        self.assertEqual(os.listdir(self.root), [])

    def test_a_project_directory_without_a_journal_reads_as_empty_and_gets_no_lock(self):
        self.private(self.root / "demo")
        self.assert_unchanged_and_equal(self.empty_reference())
        self.assertEqual(os.listdir(self.root / "demo"), [])

    def test_a_legacy_store_is_read_without_a_lock_or_a_migration(self):
        self.legacy(self.root / "demo")
        migrated = self.tmp / "migrated"
        shutil.copytree(self.root, migrated)
        MemoryStore.for_project(migrated, "demo")  # a writer migrates; the reads must see the same knowledge
        self.assertTrue((migrated / "demo/memory.jsonl").is_file())
        self.assert_unchanged_and_equal(migrated)
        self.assertEqual(sorted(os.listdir(self.root / "demo")), ["memory.json"])
        self.assertEqual(len(outcome("graph", self.root)[1]["edges"]), 1)

    def test_a_v2_store_without_a_lock_gets_none_from_reads(self):
        MemoryStore.for_project(self.root, "demo").put(record())
        (self.root / "demo/memory.lock").unlink()
        self.assert_unchanged_and_equal(self.root)
        self.assertNotIn("memory.lock", os.listdir(self.root / "demo"))
        self.assertEqual(outcome("search", self.root)[1]["items"][0]["record"]["title"], "Use integer cents")

    def test_a_write_action_still_creates_the_store(self):
        memory.invoke("put", {"project": "demo", "record": record()}, {"state_dir": str(self.root)})
        self.assertTrue((self.root / "demo/memory.jsonl").is_file())

    def test_a_shared_root_or_a_symlinked_project_is_still_refused_for_reads(self):
        self.private(self.root / "demo")
        os.chmod(self.root, 0o755)
        before = tree(self.root)
        with self.assertRaises(CoordinationError):
            memory.invoke("search", payload("search"), {"state_dir": str(self.root)})
        self.assertEqual(tree(self.root), before)
        os.chmod(self.root, 0o700)
        os.rmdir(self.root / "demo")
        self.private(self.tmp / "elsewhere")
        (self.root / "demo").symlink_to(self.tmp / "elsewhere")
        with self.assertRaises(memory.IsolationError):
            memory.invoke("graph", payload("graph"), {"state_dir": str(self.root)})
        self.assertEqual(os.listdir(self.tmp / "elsewhere"), [])


if __name__ == "__main__":
    unittest.main()
