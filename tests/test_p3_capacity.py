"""Tests of the capacity simulation: arithmetic, determinism, monotony, refusals."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
import capacity  # noqa: E402


def doc(**over):
    s = {"label": "x", "actual_agents": 10, "tasks": 10, "verified_tasks": 8,
         "sum_of_agent_seconds": 500.0, "wall_seconds": 120.0,
         "peak_concurrent_agents": 5,
         "queue": {"agent_calls_per_message": 5},
         "agent_tokens": {"input_total": 200000}}
    s.update(over)
    return {"stages": [s]}


class Capacity(unittest.TestCase):
    def test_arithmetic(self):
        p = capacity.parameters_from(doc(), "x")
        self.assertEqual(p["seconds_per_agent"]["value"], 50.0)
        self.assertEqual(p["agents_per_message"]["value"], 5)
        # (120 - 500/5) / 2 messages = 10
        self.assertEqual(p["seconds_per_message_beyond_agents"]["value"], 10.0)
        self.assertAlmostEqual(p["share_not_verified"]["value"], 0.2)
        self.assertEqual(p["input_tokens_per_agent"]["value"], 20000.0)
        for k in ("seconds_per_agent", "share_not_verified"):
            self.assertTrue(p[k]["from"])

    def ladder(self, **kw):
        p = capacity.parameters_from(doc(), "x")
        return capacity.ladder(p, sizes=(100, 200, 400), concurrencies=(20, 100), **kw)

    def test_deterministic(self):
        a = json.dumps(self.ladder(limit=10**9), sort_keys=True)
        b = json.dumps(self.ladder(limit=10**9), sort_keys=True)
        self.assertEqual(a, b)

    def test_monotony(self):
        rows = self.ladder()["rows"]
        for c in (20, 100):
            w = [r["wall_seconds"] for r in rows if r["concurrency"] == c]
            self.assertEqual(w, sorted(w))

    def test_labelled_simulation(self):
        d = self.ladder(limit=5 * 10**6)
        self.assertEqual(d["kind"], "simulation")
        self.assertIn("no agent ran", d["about"])
        self.assertTrue(all(r["kind"] == "simulation" for r in d["rows"]))
        small = [r for r in d["rows"] if r["agents"] == 100][0]
        big = [r for r in d["rows"] if r["agents"] == 400][0]
        self.assertTrue(small["fits_limit"])
        self.assertFalse(big["fits_limit"])
        self.assertEqual([r["sessions_of_20"] for r in d["rows"][:2]], [1, 5])

    def test_refusals(self):
        for over in ({"verified_tasks": 0}, {"actual_agents": 0}):
            with self.assertRaises(capacity.Refused) as e:
                capacity.parameters_from(doc(**over), "x")
            self.assertTrue(str(e.exception))
        with self.assertRaises(capacity.Refused):
            capacity.parameters_from(doc(), "missing")

    def test_large_ladder_is_fast(self):
        p = capacity.parameters_from(doc(), "x")
        d = capacity.ladder(p, sizes=(100000,), concurrencies=(20,))
        self.assertEqual(len(d["rows"]), 1)


if __name__ == "__main__":
    unittest.main()
