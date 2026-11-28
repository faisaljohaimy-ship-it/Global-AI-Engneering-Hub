import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "swarm" / "phase3")]
import trace as scripted  # noqa: E402


class TraceTest(unittest.TestCase):
    def test_two_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = scripted.run(Path(tmp), 2)
        # raw output is cut at the command's 60000 character cap: a missing answer is allowed only there
        bad = [r for r in result["rows"] if not r["answer_present"] and not (r["mode"] == "raw" and r["chars"] > 60000)]
        self.assertEqual(bad, [])
        self.assertTrue(result["all_answers_present"]["lean"])
        self.assertEqual(len(result["rows"]), 20)
        self.assertLess(result["total_chars"]["lean"], result["total_chars"]["raw"])
        self.assertTrue(result["kind"].startswith("scripted trace"))


if __name__ == "__main__":
    unittest.main()
