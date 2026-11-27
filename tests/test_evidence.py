import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class EvidenceTests(unittest.TestCase):
    def test_all_22_programs_have_sanitized_probe_evidence(self):
        catalog = json.loads((ROOT / "integrations/PROGRAMS.json").read_text())
        evidence = json.loads((ROOT / "integrations/EVIDENCE.json").read_text())
        expected = {item["name"] for item in catalog["programs"]}
        rows = evidence["programs"]
        self.assertEqual(len(expected), 22)
        self.assertEqual({item["program"] for item in rows}, expected)
        self.assertEqual(len(rows), 22)
        self.assertTrue(all(item["mutation"] is False for item in rows))
        self.assertTrue(all(item["budget_impact"] == 0 for item in rows))
        serialized = json.dumps(evidence).casefold()
        for forbidden in ("email", "account_id", "team_id", "balance", "access_token"):
            self.assertNotIn(f'"{forbidden}"', serialized)

    def test_probe_outcome_counts(self):
        rows = json.loads((ROOT / "integrations/EVIDENCE.json").read_text())["programs"]
        self.assertEqual(sum(item["result"] == "success" for item in rows), 12)
        self.assertEqual(sum(item["authenticated_read"] for item in rows), 10)
        self.assertEqual(sum(item["surface"] == "local_executable" for item in rows), 2)
        self.assertEqual(sum(item["result"] == "unavailable" for item in rows), 10)

    def test_recovery_manifest_is_index_only(self):
        data = json.loads((ROOT / "catalog/recovered-packages.json").read_text())
        self.assertEqual(len(data["packages"]), 3)
        self.assertTrue(all(item["status"] == "verified-source" for item in data["packages"]))
        self.assertTrue(all(item["imported"] is False for item in data["packages"]))


if __name__ == "__main__":
    unittest.main()
