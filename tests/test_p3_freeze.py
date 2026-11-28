"""Tests for swarm/phase3/freeze.py on temporary trees, plain and git."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "swarm" / "phase3"))
import freeze  # noqa: E402

FILES = {
    "swarm/a.py": "a",
    "swarm/phase3/b.json": "{}",
    "swarm/phase3/__pycache__/x.pyc": "skip",
    ".claude/agents/swarm-w.md": "agent",
    ".claude/agents/other.md": "not frozen",
    ".claude/settings.json": "{}",
    "tests/test_swarm_x.py": "t",
    "tests/test_p3_y.py": "t",
    "tests/test_other.py": "not frozen",
    "tests/fixtures/p3-doc.json": "{}",
    "tests/fixtures/other.json": "not frozen",
    "README.md": "not frozen",
}


def build(root):
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class Base:
    def make(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        build(self.root)
        self.prepare()
        return self.root

    def prepare(self):
        pass

    def add(self, rel, text="n"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        self.track(rel)

    def track(self, rel):
        pass

    def test_selection(self):
        root = self.make()
        doc = freeze.write(root)
        self.assertEqual(sorted(doc["files"]), [
            ".claude/agents/swarm-w.md", ".claude/settings.json", "swarm/a.py",
            "swarm/phase3/b.json", "tests/fixtures/p3-doc.json",
            "tests/test_p3_y.py", "tests/test_swarm_x.py"])
        self.assertEqual(doc["file_count"], 7)
        self.assertIn("scale-up phase is closed", doc["statement"])

    def test_unchanged(self):
        root = self.make()
        freeze.write(root)
        self.assertEqual(freeze.check(root), [])

    def test_one_byte(self):
        root = self.make()
        freeze.write(root)
        (root / "swarm/a.py").write_text("b")
        self.assertEqual(freeze.check(root), ["changed: swarm/a.py"])

    def test_added(self):
        root = self.make()
        freeze.write(root)
        self.add("swarm/new.py")
        self.assertEqual(freeze.check(root), ["added: swarm/new.py"])

    def test_removed(self):
        root = self.make()
        freeze.write(root)
        (root / "swarm/a.py").unlink()
        self.assertEqual(freeze.check(root), ["removed: swarm/a.py"])

    def test_renamed(self):
        root = self.make()
        freeze.write(root)
        (root / "swarm/a.py").rename(root / "swarm/c.py")
        self.track("swarm/c.py")
        self.assertEqual(freeze.check(root), ["removed: swarm/a.py", "added: swarm/c.py"])

    def test_same_twice(self):
        root = self.make()
        freeze.write(root)
        first = (root / freeze.FREEZE).read_bytes()
        freeze.write(root)
        self.assertEqual(first, (root / freeze.FREEZE).read_bytes())

    def test_freeze_file_tampered(self):
        root = self.make()
        freeze.write(root)
        p = root / freeze.FREEZE
        p.write_text(p.read_text().replace('"file_count": 7', '"file_count": 8'))
        self.assertTrue(freeze.check(root))

    def test_missing_freeze(self):
        root = self.make()
        self.assertEqual(len(freeze.check(root)), 1)


class WalkTree(Base, unittest.TestCase):
    pass


class GitTree(Base, unittest.TestCase):
    def prepare(self):
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")

    def track(self, rel):
        git(self.root, "add", "-A")

    def test_untracked_not_frozen(self):
        root = self.make()
        (root / "swarm/loose.py").write_text("x")
        doc = freeze.write(root)
        self.assertNotIn("swarm/loose.py", doc["files"])
        self.assertEqual(freeze.check(root), [])


class Command(unittest.TestCase):
    def test_command_on_real_script(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "swarm/phase3").mkdir(parents=True)
            (root / "swarm/phase3/freeze.py").write_text(
                (REPO / "swarm/phase3/freeze.py").read_text())
            script = str(root / "swarm/phase3/freeze.py")
            run = lambda c: subprocess.run([sys.executable, "-I", script, c],
                                           capture_output=True, text=True)
            self.assertEqual(run("write").returncode, 0)
            r = run("check")
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "frozen: 1 files unchanged"))
            (root / "swarm/extra.txt").write_text("new")
            r = run("check")
            self.assertEqual(r.returncode, 1)
            self.assertIn("added: swarm/extra.txt", r.stdout)


if __name__ == "__main__":
    unittest.main()
