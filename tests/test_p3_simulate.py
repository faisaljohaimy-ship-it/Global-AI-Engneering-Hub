import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "swarm" / "phase3"))
import simulate  # noqa: E402

SVC = {"mean": 30.0, "sd": 8.0, "least": 2.0}


class SimulateTests(unittest.TestCase):
    def test_done_plus_failed_equals_taken(self):
        o = simulate.run(50, 500, 10, 20, SVC, 3, overhead=5.0, failure=0.1)
        self.assertEqual(o["tasks_done"] + o["tasks_failed"], 500)
        self.assertGreater(o["tasks_failed"], 0)
        self.assertEqual(o["kind"], "simulation: no agent ran")

    def test_peak_within_host(self):
        o = simulate.run(300, 1000, 5, 40, SVC, 1)
        self.assertLessEqual(o["peak_running"], 40)

    def test_same_seed_same_result(self):
        a = simulate.run(100, 300, 10, 30, SVC, 7, 3.0, 0.05)
        self.assertEqual(a, simulate.run(100, 300, 10, 30, SVC, 7, 3.0, 0.05))

    def test_more_host_not_slower(self):
        # Deterministic service times make the claim exact.
        svc = {"mean": 30.0, "sd": 0.0, "least": 1.0}
        walls = [simulate.run(100, 1000, 10, h, svc, 1)["wall_seconds"] for h in (10, 25, 50, 100)]
        self.assertEqual(walls, sorted(walls, reverse=True))

    def test_batch_ten_hundred_agents_finish_thousand(self):
        o = simulate.run(100, 1000, 10, 100, SVC, 1)
        self.assertEqual(o["tasks_done"], 1000)
        self.assertEqual(o["tasks_failed"], 0)

    def test_sweep_runs(self):
        self.assertEqual(simulate.main(["sweep"]), 0)


if __name__ == "__main__":
    unittest.main()
