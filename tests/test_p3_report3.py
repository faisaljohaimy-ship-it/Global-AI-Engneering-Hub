"""Tests of the final report: absent files, the fixture as third phase, no paths, same text twice."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "swarm" / "phase3"))
import report3  # noqa: E402

EARLY = ["swarm/evidence/summary.json", "swarm/evidence/ladder.json", "swarm/evidence/host-limits.json", "swarm/phase2/evidence/stages.json"]


def make(third=False):
    root = Path(tempfile.mkdtemp())
    for rel in EARLY:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)
    if third:
        dest = root / "swarm/phase3/evidence/stages.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / "tests/fixtures/p3-stand-in-stages.json", dest)
    return root


class Report(unittest.TestCase):
    def test_without_third_phase(self):
        root = make()
        self.addCleanup(shutil.rmtree, root)
        text = report3.build(root)
        self.assertIn("not available: swarm/phase3/evidence/stages.json is not in the repository", text)
        self.assertIn("Simulation, not a measurement", text)
        self.assertIn("not available: swarm/phase3/evidence/capacity.json is not in the repository", text)
        sec = text.split("## 4.")[1].split("## 5.")[0]
        self.assertNotIn("worker command", sec)
        self.assertIn("## 9.", text)

    def test_with_fixture(self):
        root = make(True)
        self.addCleanup(shutil.rmtree, root)
        text = report3.build(root)
        self.assertIn("| g0 |", text)
        self.assertIn("| q4 |", text)
        self.assertIn("worker command 8", text)
        self.assertIn("72,125,176", text)
        data = json.loads((REPO / "tests/fixtures/p3-stand-in-stages.json").read_text())
        self.assertIn(f"{data['stages'][1]['per_verified_task']['input_total']:,}", text)

    def test_no_absolute_path_and_stable(self):
        for third in (False, True):
            root = make(third)
            self.addCleanup(shutil.rmtree, root)
            text = report3.build(root)
            self.assertEqual(text, report3.build(root))
            self.assertNotIn(str(root), text)
            self.assertNotIn(str(REPO), text)
            self.assertNotIn("/home/", text)
            self.assertNotIn("/tmp/", text)


if __name__ == "__main__":
    unittest.main()
