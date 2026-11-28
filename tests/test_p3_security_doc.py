"""The threat model's table is checked against the files and the tests it cites."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
import security_doc  # noqa: E402


class SecurityDocTests(unittest.TestCase):
    def test_the_table_matches_the_files_the_tests_and_the_document(self):
        self.assertEqual(security_doc.check(), [])

    def test_a_row_citing_a_test_that_does_not_exist_is_reported(self):
        row = {"id": "Z1", "who": "x", "tries": "y", "controls": [], "status": "held",
               "tests": ["tests/test_p3_gate.py::DecisionTests.test_nothing_of_the_kind"], "left_open": "-"}
        security_doc.ROWS.append(row)
        try:
            self.assertTrue(any("test_nothing_of_the_kind" in p for p in security_doc.check()))
        finally:
            security_doc.ROWS.remove(row)

    def test_a_missing_control_function_is_reported(self):
        row = {"id": "Z2", "who": "x", "tries": "y", "controls": [("swarm/phase3/hook.py", "no_such_function")],
               "status": "open", "tests": [], "left_open": "-"}
        security_doc.ROWS.append(row)
        try:
            self.assertTrue(any("no_such_function" in p for p in security_doc.check()))
        finally:
            security_doc.ROWS.remove(row)

    def test_a_row_marked_open_may_claim_no_test(self):
        row = {"id": "Z3", "who": "x", "tries": "y", "controls": [], "status": "open",
               "tests": ["tests/test_p3_gate.py::DecisionTests.test_what_the_gate_does_not_know_it_refuses"], "left_open": "-"}
        security_doc.ROWS.append(row)
        try:
            self.assertTrue(any("marked open claims tests" in p for p in security_doc.check()))
        finally:
            security_doc.ROWS.remove(row)

    def test_the_rows_that_must_be_covered_are_there(self):
        who = " ".join(f"{r['who']} {r['tries']}" for r in security_doc.ROWS)
        for word in ("second shell command", "file tool", "another session", "starts an agent", "cannot read", "crash",
                     "cannot be written to the record", "unknown type", "secrets", "outside", "network", "time limit", "pushes", "orchestrator"):
            self.assertIn(word, who)
        text = security_doc.render()
        self.assertIn("not a sandbox", text)
        self.assertIn("was not measured", text)


if __name__ == "__main__":
    unittest.main()
