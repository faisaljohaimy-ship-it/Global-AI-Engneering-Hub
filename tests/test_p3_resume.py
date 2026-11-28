"""Tests of swarm/phase3/resume.py with temporary files only."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
import resume  # noqa: E402

PLAN = {"stages": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]}


class ResumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.plan_file = self.dir / "PLAN.json"
        self.plan_bytes = b'{"stages":[{"id":"a"},{"id":"b"},{"id":"c"},{"id":"d"}]}   \n'
        self.plan_file.write_bytes(self.plan_bytes)
        self.sha = hashlib.sha256(self.plan_bytes).hexdigest()
        self.evidence = {"plan_sha256": self.sha, "stages": [
            {"label": "a", "x": 1}, {"label": "b", "skipped": "too dear"}]}
        self.ev_file = self.dir / "ev.json"
        self.ev_file.write_text(json.dumps(self.evidence))

    def tearDown(self):
        self.tmp.cleanup()

    def test_position_follows_plan_order(self):
        got = resume.position(self.evidence, PLAN, self.plan_bytes)
        self.assertEqual(got, {"done": ["a"], "skipped": ["b"], "next": "c"})

    def test_position_all_finished(self):
        ev = dict(self.evidence, stages=[{"label": x} for x in "dcba"])
        self.assertIsNone(resume.position(ev, PLAN, self.plan_bytes)["next"])
        self.assertEqual(resume.position(ev, PLAN, self.plan_bytes)["done"], list("abcd"))

    def test_position_without_bytes_uses_canonical_forms(self):
        ev = {"plan_sha256": hashlib.sha256((json.dumps(PLAN, indent=1) + "\n").encode()).hexdigest(), "stages": []}
        self.assertEqual(resume.position(ev, PLAN)["next"], "a")

    def test_refuses_other_plan(self):
        with self.assertRaises(ValueError):
            resume.position(dict(self.evidence, plan_sha256="0" * 64), PLAN, self.plan_bytes)
        with self.assertRaises(ValueError):
            resume.position(self.evidence, PLAN)  # no bytes, not a canonical form
        with self.assertRaises(ValueError):
            resume.position({"stages": []}, PLAN, self.plan_bytes)

    def test_rebuild_writes_when_missing(self):
        out = self.dir / "sub" / "results.json"
        self.assertTrue(resume.rebuild(self.ev_file, out, self.plan_file))
        self.assertEqual(json.loads(out.read_text()), {"stages": self.evidence["stages"]})

    def test_rebuild_never_overwrites(self):
        out = self.dir / "results.json"
        out.write_text("mine")
        self.assertFalse(resume.rebuild(self.ev_file, out, self.plan_file))
        self.assertEqual(out.read_text(), "mine")

    def test_rebuild_refuses_other_plan(self):
        self.plan_file.write_bytes(self.plan_bytes + b" ")
        out = self.dir / "results.json"
        with self.assertRaises(ValueError):
            resume.rebuild(self.ev_file, out, self.plan_file)
        self.assertFalse(out.exists())

    def test_command_line(self):
        out = self.dir / "r.json"
        self.assertEqual(resume.main([str(self.ev_file), str(self.plan_file), str(out)]), 0)
        self.assertTrue(out.exists())
        self.plan_file.write_bytes(b"{}")
        self.assertEqual(resume.main([str(self.ev_file), str(self.plan_file)]), 1)


if __name__ == "__main__":
    unittest.main()
