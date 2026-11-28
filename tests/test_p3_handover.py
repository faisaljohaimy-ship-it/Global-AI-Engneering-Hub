import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "swarm" / "phase3"))
import handover  # noqa: E402


def tree(base: Path):
    for rel, body in {"swarm/a.py": '"""Alpha does a thing. More."""\n', "swarm/ladder.py": '"""Ladder runs. Then more."""\n',
                      "swarm/phase2/stage.py": '"""Stage runs."""\n', "swarm/phase2/PLAN.json": "{}\n",
                      "swarm/phase3/CONTRACT.md": "# C\n\nintro\n\n## What\n\nOne. The third phase scales. Two.\n\n## Rules\n",
                      "tests/test_swarm_x.py": "x = 1\n", ".claude/agents/swarm-w.md": "w\n"}.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)


class Handover(unittest.TestCase):
    def test_receipts_sorted_stable(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            tree(root)
            (root / "swarm/phase3/HANDOVER.md").write_text("x")
            a = handover.receipts(root)
            self.assertEqual(a, handover.receipts(root))
            paths = [r["path"] for r in a]
            self.assertEqual(paths, sorted(paths))
            self.assertNotIn("swarm/phase3/HANDOVER.md", paths)
            self.assertIn(".claude/agents/swarm-w.md", paths)

    def test_change_changes_receipt(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            tree(root)
            before = handover.write(root)
            (root / "swarm/a.py").write_text("y = 2\n")
            self.assertNotEqual(before, handover.write(root))

    def test_no_absolute_path_and_content(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            tree(root)
            text = handover.write(root)
            self.assertNotIn(str(root), text)
            self.assertNotRegex(text, r"(?<![\w.~])/(home|tmp|root|Users)/")
            self.assertIn("Ladder runs.", text)
            self.assertIn("The third phase scales.", text)
            self.assertIn("Nothing in these phases was run from Codex", text)

    def test_check_fails_when_stale(self):
        page = HERE / handover.PAGE
        old = page.read_text() if page.exists() else None
        try:
            page.write_text(handover.write(HERE))
            run = lambda: subprocess.run([sys.executable, str(HERE / "swarm/phase3/handover.py"), "--check"],
                                         capture_output=True).returncode
            self.assertEqual(run(), 0)
            page.write_text(page.read_text() + "stale\n")
            self.assertEqual(run(), 1)
        finally:
            if old is None:
                page.unlink()
            else:
                page.write_text(old)


if __name__ == "__main__":
    unittest.main()
