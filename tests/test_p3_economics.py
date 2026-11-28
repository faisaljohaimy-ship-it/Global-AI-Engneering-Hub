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


if __name__ == "__main__":
    unittest.main()
