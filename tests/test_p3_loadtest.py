"""Small load test of the worker command: 40 tasks, 20 scripted workers."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
import loadtest  # noqa: E402


class LoadTest(unittest.TestCase):
    def test_small_run(self):
        with tempfile.TemporaryDirectory() as home:
            result = loadtest.run(40, 20, Path(home))
        self.assertEqual(result["kind"], "load test with scripted workers: no agent, no model")
        self.assertEqual(result["failed_commands"], 0)
        self.assertEqual(result["verified"], 40)
        self.assertTrue(result["all_verified"])
        self.assertEqual(result["hand_ins"], 40)
        self.assertGreater(result["hand_ins_per_second"], 0)
        self.assertIsNotNone(result["cores"])


if __name__ == "__main__":
    unittest.main()
