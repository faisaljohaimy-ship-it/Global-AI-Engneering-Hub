"""Tests for swarm/phase3/closure.py: a tree built from the stand-in fixture passes, each row fails once, an absent run is null."""
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "swarm" / "phase3"))
import closure  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "p3-stand-in-stages.json"


def rows(root):
    return {r["check"]: r for r in closure.check(root)["rows"]}


class Closure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.doc = json.loads(FIXTURE.read_text())
        plan = {"stages": [{"id": s["label"]} for s in self.doc["stages"]]}
        (self.root / "swarm/phase3/evidence").mkdir(parents=True)
        (self.root / "swarm/phase2/evidence").mkdir(parents=True)
        (self.root / closure.PLAN).write_text(json.dumps(plan))
        shutil.copy(FIXTURE, self.root / closure.P2)
        self.doc["plan_sha256"] = hashlib.sha256((self.root / closure.PLAN).read_bytes()).hexdigest()
        self.save()

    def save(self):
        (self.root / closure.P3).write_text(json.dumps(self.doc))

    def failing(self):
        return [k for k, r in rows(self.root).items() if r["passed"] is False]

    def test_fixture_tree_passes(self):
        result = closure.check(self.root)
        self.assertEqual(self.failing(), [])
        self.assertEqual(result["failed"], 0)
        self.assertNotIn(False, [r["passed"] for r in result["rows"]])

    def test_each_row_fails_once(self):
        def edit(fn):
            self.doc = json.loads(FIXTURE.read_text())
            self.doc["plan_sha256"] = hashlib.sha256((self.root / closure.PLAN).read_bytes()).hexdigest()
            fn(self.doc)
            self.save()
            return self.failing()
        g, q = 0, 1
        cases = {
            "third phase evidence validates": lambda d: d.pop("caps"),
            "the document names the plan it ran": lambda d: d.update(plan_sha256="0" * 64),
            "the first stage that ran is a passed security gate": lambda d: d["stages"][g]["security_gate"].update(passed=False),
            "task stages have a clean, reconciled ledger and an enforced guard": lambda d: d["stages"][q].update(guard_enforced=False),
            "counted input tokens are within the limit": lambda d: d["figures"].update(input_tokens_counted=d["caps"]["cumulative_input_tokens"] + 1),
            "no agent met a usage limit": lambda d: d["stages"][q].update(agents_with_limit_error=1),
            "real agents never exceed registered agents": lambda d: d["stages"][q].update(actual_agents=d["stages"][q]["registered_agents"] + 1),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                self.assertIn(name, edit(fn))
        # the plan lists a stage the document lacks and the last stage does not explain it
        plan = {"stages": [{"id": "g0"}, {"id": "q4"}, {"id": "zz"}]}
        (self.root / closure.PLAN).write_text(json.dumps(plan))
        self.doc = json.loads(FIXTURE.read_text())
        self.doc["plan_sha256"] = hashlib.sha256((self.root / closure.PLAN).read_bytes()).hexdigest()
        self.save()
        self.assertIn("every stage of the plan is run or skipped, or the end is explained", self.failing())
        self.doc["stages"][-1]["stopped"] = "a stop rule fired"
        self.save()
        self.assertNotIn("every stage of the plan is run or skipped, or the end is explained", self.failing())

    def test_second_phase_document_fails(self):
        (self.root / closure.P2).write_text(json.dumps({"stages": []}))
        self.assertIn("second phase evidence validates", self.failing())

    def test_capacity_label(self):
        (self.root / "swarm/phase3/evidence/capacity.json").write_text(json.dumps({"about": "A simulation of the queue."}))
        self.assertEqual(rows(self.root)["the capacity study is labelled a simulation"]["passed"], True)
        (self.root / "swarm/phase3/evidence/capacity.json").write_text(json.dumps({"about": "Measured."}))
        self.assertIn("the capacity study is labelled a simulation", self.failing())

    def test_leaks_in_evidence(self):
        name = "no evidence file holds a path, session id or model identifier"
        self.assertTrue(rows(self.root)[name]["passed"])
        for leak in ("/home/someone/x", "session_0123", "claude-sonnet-5-5"):
            with self.subTest(leak):
                f = self.root / "swarm/phase3/evidence/other.json"
                f.write_text(json.dumps({"x": leak}))
                self.assertIn(name, self.failing())
                f.unlink()

    def test_freeze(self):
        name = "the freeze still matches"
        (self.root / "FREEZE.json").write_text("{}")
        fake = type(sys)("freeze")
        fake.check = lambda root: ["file changed"]
        sys.modules["freeze"] = fake
        self.addCleanup(sys.modules.pop, "freeze", None)
        self.assertIn(name, self.failing())
        fake.check = lambda root: []
        self.assertTrue(rows(self.root)[name]["passed"])
        del sys.modules["freeze"]
        (self.root / "FREEZE.json").unlink()
        self.assertIsNone(rows(self.root)[name]["passed"])

    def test_absent_run_is_null_not_pass(self):
        with tempfile.TemporaryDirectory() as empty:
            result = closure.check(empty)
            self.assertEqual(result["failed"], 0)
            self.assertTrue(all(r["passed"] is None for r in result["rows"]))
            self.assertTrue(all("missing" in r["detail"] for r in result["rows"]))

    def test_command_exit_codes(self):
        self.assertEqual(closure.main(["closure", str(self.root)]), 0)
        self.doc["figures"]["input_tokens_counted"] = 10 ** 12
        self.save()
        self.assertEqual(closure.main(["closure", str(self.root)]), 1)


if __name__ == "__main__":
    unittest.main()
