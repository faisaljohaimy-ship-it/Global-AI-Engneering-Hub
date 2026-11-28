import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "swarm" / "phase3"), str(ROOT / "swarm" / "phase2"), str(ROOT / "swarm")]
import economics  # noqa: E402


def stage(label, size, verified, cost, **more):
    base = {"label": label, "kind": "task", "size": size, "agent_type": "swarm-light", "model": "haiku", "actual_agents": 2, "tasks": 2,
            "verified_tasks": verified, "cost_units": cost, "sum_of_agent_seconds": 40.0, "tasks_per_minute": 6.0,
            "agent_tokens": {"input_total": 2000, "cache_read": 500, "output": 10}}
    base.update(more)
    return base


DOC = {"stages": [
    {"label": "p1", "kind": "probe"},
    stage("a", "small", 2, 1000),
    stage("b", "small", 2, 600),
    stage("z", "medium", 0, 900, tasks_per_minute=0.0),
    {"label": "k", "kind": "task", "size": "large", "skipped": "cap reached"},
]}


class Economics(unittest.TestCase):
    def test_rows(self):
        rows = {r["label"]: r for r in economics.per_task(DOC)}
        self.assertEqual(set(rows), {"a", "b", "z", "k"})
        a = rows["a"]
        self.assertEqual((a["input_tokens_per_task"], a["cost_units_per_task"], a["worker_seconds_per_task"], a["cache_read_share"]), (1000, 500, 20.0, 0.25))

    def test_nothing_verified_is_none(self):
        z = {r["label"]: r for r in economics.per_task(DOC)}["z"]
        for key in ("input_tokens_per_task", "cost_units_per_task", "worker_seconds_per_task", "tasks_per_minute"):
            self.assertIsNone(z[key])

    def test_skipped(self):
        k = {r["label"]: r for r in economics.per_task(DOC)}["k"]
        self.assertEqual(k["skipped"], "cap reached")
        self.assertIsNone(k["cost_units_per_task"])
        self.assertIsNone(k["agents"])
        self.assertIsNone(k["cache_read_share"])

    def test_missing_fields(self):
        rows = economics.per_task({"stages": [{"label": "q", "kind": "task", "size": "small", "verified_tasks": 1}]})
        self.assertIsNone(rows[0]["cost_units_per_task"])
        self.assertIsNone(rows[0]["cache_read_share"])
        self.assertEqual(economics.per_task({}), [])

    def test_project(self):
        a = economics.project(economics.per_task(DOC)[0], 10)
        self.assertEqual((a["input_tokens"]["value"], a["cost_units"]["value"], a["wall_minutes"]["value"]), (10000, 5000, 1.67))
        self.assertIn("projection from one stage", a["cost_units"]["basis"])

    def test_project_no_data(self):
        z = {r["label"]: r for r in economics.per_task(DOC)}["z"]
        p = economics.project(z, 10)
        self.assertIsNone(p["cost_units"]["value"])
        self.assertIsNone(p["wall_minutes"]["value"])

    def test_render(self):
        text = economics.render(DOC)
        self.assertIn("small: b at 300", text)
        self.assertIn("large: n/a", text)
        self.assertIn("medium: n/a", text)
        self.assertIn("a function", text)
        self.assertIn("module-sized feature", text)
        self.assertIn("not real customer work", text)
        about = json.loads((ROOT / "swarm" / "phase2" / "PLAN.json").read_text())["cost_weights"]["about"]
        self.assertIn(about, text)

    def test_command_line(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "e.json"
            path.write_text(json.dumps(DOC))
            done = subprocess.run([sys.executable, str(ROOT / "swarm" / "phase3" / "economics.py"), str(path), "--tasks", "50"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("| Stage |", done.stdout)


class Factory(unittest.TestCase):
    def rows(self, *stages):
        return economics.per_task({"stages": list(stages)})

    def test_arithmetic(self):
        rows = self.rows(stage("a", "small", 2, 1000, tasks=2), stage("b", "small", 2, 600, tasks=2),
                         stage("m", "medium", 9, 9000, tasks=10, sum_of_agent_seconds=90.0))
        f = economics.factory(rows, {"small": 10, "medium": 5})
        self.assertEqual(f["sizes"]["small"]["configuration"]["label"], "b")
        self.assertEqual(f["sizes"]["small"]["figure"]["cost_units"], 3000)
        self.assertEqual(f["sizes"]["medium"]["figure"]["cost_units"], 5000)
        t = f["totals"]
        # small: 1000 in per task x 10; medium: 2000 in over 1 verified-of-9 stage -> 222 per task x 5
        self.assertEqual(t["input_tokens"], 10 * 1000 + 5 * round(2000 / 9))
        self.assertEqual(t["cost_units"], 8000)
        self.assertAlmostEqual(t["agent_minutes"], 10 * (20 / 60) + 5 * (10 / 60), places=1)
        self.assertEqual(f["share_needing_second_attempt"], round(5 * 0.1 / 15, 4))

    def test_no_qualifying_row(self):
        rows = self.rows(stage("a", "small", 1, 100, tasks=2), stage("z", "medium", 0, 900, tasks=2))
        f = economics.factory(rows, {"small": 3, "medium": 2, "large": 1})
        for size in ("small", "medium", "large"):
            self.assertIsNone(f["sizes"][size]["figure"])
            self.assertIn("note", f["sizes"][size])
        self.assertEqual(f["sizes_without_a_figure"], ["small", "medium", "large"])
        self.assertIsNone(f["share_needing_second_attempt"])

    def test_render(self):
        text = economics.render_factory({"stages": [stage("a", "small", 2, 1000, tasks=2)]})
        for word in ("one task", "one feature", "one system", "not a price or a subscription allowance", "not comparable", "40 small"):
            self.assertIn(word, text)

    def test_second_phase_document(self):
        doc = json.loads((ROOT / "swarm" / "phase2" / "evidence" / "stages.json").read_text())
        self.assertIn("one system", economics.render_factory(doc))
        economics.render(doc)

    def test_zero_verified_no_division(self):
        doc = {"stages": [stage("z", "small", 0, 900, tasks=0, tasks_per_minute=0.0, sum_of_agent_seconds=0)]}
        f = economics.factory(economics.per_task(doc), {"small": 5})
        self.assertIsNone(f["sizes"]["small"]["figure"])
        economics.render_factory(doc)

    def test_gated_run_stages(self):
        doc = json.loads((ROOT / "tests" / "fixtures" / "p3-stand-in-stages.json").read_text())
        rows = economics.per_task(doc)
        self.assertEqual([r["label"] for r in rows], ["q4"])
        q = rows[0]
        self.assertEqual((q["input_tokens_per_task"], q["output_tokens_per_task"]), (16530, 180))
        self.assertEqual(q["orchestrator_input_per_task"], 0)
        self.assertEqual(q["failure_rate"], 0.0)
        economics.render_factory(doc)


if __name__ == "__main__":
    unittest.main()
