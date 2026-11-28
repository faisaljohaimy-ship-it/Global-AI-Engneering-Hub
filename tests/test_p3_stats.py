"""Tests of swarm/phase3/stats.py on a hand-written evidence document."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "swarm" / "phase3"))
import stats  # noqa: E402


def stage(label, agents, wall, tasks=20, verified=20, cost=1000, size="small", **more):
    return {"label": label, "kind": "task", "size": size, "agent_type": "lean", "model": "m", "actual_agents": agents,
            "peak_concurrent_agents": agents, "tasks": tasks, "verified_tasks": verified, "wall_seconds": wall,
            "agent_tokens": {"input_total": 2000}, "cost_units": cost, **more}


DOC = {"stages": [stage("s8", 8, 50, cost=1600), stage("s1", 1, 400, cost=2000), stage("s4", 4, 100, cost=1200),
                  stage("s16", 16, 48, cost=2400), {"label": "s64", "skipped": "usage limit"},
                  stage("t1", 1, 100, size="large", tasks=5)]}


class Stats(unittest.TestCase):
    def setUp(self):
        self.result = stats.summary(DOC)
        self.small = next(g for g in self.result["groups"] if g["size"] == "small")

    def test_four_stages_and_balance(self):
        rows = self.small["rows"]
        self.assertEqual([r["agents"] for r in rows], [1, 4, 8, 16])
        self.assertEqual(rows[1]["speedup"], 4.0)
        self.assertEqual(rows[1]["efficiency"], 1.0)
        self.assertEqual(rows[0]["speedup"], 1.0)
        self.assertIsNone(rows[0]["gain_percent"])
        self.assertEqual(rows[2]["gain_percent"], 100.0)
        self.assertEqual(rows[3]["gain_percent"], 4.2)
        self.assertEqual(rows[1]["tasks_per_minute"], 12.0)
        self.assertEqual(rows[1]["input_per_verified"], 100.0)
        self.assertEqual(rows[1]["cost_per_verified"], 60.0)
        b = self.small["balance"]
        self.assertEqual((b["largest_worthwhile_agents"], b["cheapest_agents"]), (8, 4))
        self.assertTrue(b["sentence"].endswith("."))

    def test_single_stage_group(self):
        large = next(g for g in self.result["groups"] if g["size"] == "large")
        self.assertIsNone(large["balance"]["largest_worthwhile_agents"])
        self.assertIn("Fewer than two", large["balance"]["sentence"])
        self.assertEqual(large["rows"][0]["speedup"], 1.0)

    def test_skipped_listed_apart(self):
        self.assertEqual(self.result["skipped"], [{"label": "s64", "reason": "usage limit"}])
        self.assertEqual(sum(len(g["rows"]) for g in self.result["groups"]), 5)

    def test_no_verified_task(self):
        doc = {"stages": [stage("a", 1, 100), stage("b", 2, 60, verified=0)]}
        row = stats.summary(doc)["groups"][0]["rows"][1]
        self.assertIsNone(row["input_per_verified"])
        self.assertIsNone(row["cost_per_verified"])
        self.assertIsNotNone(row["speedup"])

    def test_missing_single_and_render(self):
        doc = {"stages": [stage("a", 2, 100), stage("b", 4, 60)]}
        rows = stats.summary(doc)["groups"][0]["rows"]
        self.assertIsNone(rows[0]["speedup"])
        self.assertIsNone(rows[1]["efficiency"])
        text = stats.render(stats.summary(DOC))
        self.assertIn("| agents |", text)
        self.assertIn("Skipped stages: s64 (usage limit).", text)
        self.assertEqual(stats.summary({}), {"groups": [], "skipped": []})


if __name__ == "__main__":
    unittest.main()
