"""Tests of the coordinator scale measurement, with quick sizes. No agent, no model, no network."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
import coordinator_scale  # noqa: E402


class CoordinatorScale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = coordinator_scale.measure(quick=True)

    def test_every_id_claimed_exactly_once(self):
        sizes = [row["tasks"] for row in self.doc["measured"]["queue_by_size"]]
        self.assertEqual(sizes, [200, 1000])
        for row in self.doc["measured"]["queue_by_size"]:
            self.assertTrue(row["every_id_claimed_exactly_once"], row)
            self.assertEqual(row["status_waiting"], 0)

    def test_measured_and_estimated_are_apart(self):
        self.assertIn("measured", self.doc)
        self.assertIn("estimated", self.doc)
        self.assertEqual(self.doc["estimated"]["label"], "estimate, not measured")
        self.assertEqual(self.doc["measured"]["gate"]["installed_gate_exit_codes_seen"], [0])
        self.assertEqual(self.doc["measured"]["ledger_build"]["tool_calls_counted"], 4000)

    def test_nothing_looks_like_a_path(self):
        text = json.dumps(self.doc)
        self.assertIsNone(re.search(r"(^|[\s\"'=])(/[A-Za-z0-9_.-]+){2,}", text.replace("/proc", "")))
        self.assertNotIn("/home", text)
        self.assertNotIn("/tmp", text)


if __name__ == "__main__":
    unittest.main()
