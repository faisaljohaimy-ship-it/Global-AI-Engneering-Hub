"""The separate account of agents, reviewers, development agents and orchestrators: it must add up, and agree with the run's own count."""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
P3 = ROOT / "swarm" / "phase3"
sys.path[:0] = [str(P3), str(ROOT / "swarm" / "phase2"), str(ROOT / "swarm")]
import accounting  # noqa: E402
import stage3  # noqa: E402


def flat(group: dict) -> int:
    return sum(sum(v.values()) if isinstance(v, dict) else v for k, v in group.items() if isinstance(v, (int, dict)) and k != "total")


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.account = accounting.build(ROOT)

    def test_every_group_adds_up_and_the_sums_are_the_sums(self):
        a = self.account
        self.assertEqual(a["agents"]["total"], sum(a["agents"]["workers"].values()) + sum(a["agents"]["probe_agents_of_the_security_gate"].values()))
        self.assertEqual(a["reviewers"]["total"], flat(a["reviewers"]))
        self.assertEqual(a["development_agents"]["total"], flat(a["development_agents"]))
        self.assertEqual(a["orchestrators"]["total_measured"], sum(v for k, v in a["orchestrators"].items() if isinstance(v, int) and k != "total_measured"))
        self.assertEqual(a["counted_against_the_limit"]["total"], a["agents"]["total"] + a["reviewers"]["total"] + a["development_agents"]["total"])
        self.assertEqual(a["everything_measured"]["total"], a["counted_against_the_limit"]["total"] + a["orchestrators"]["total_measured"])
        self.assertEqual(a["within_the_limit_as_defined"], a["counted_against_the_limit"]["total"] <= a["limit"])
        self.assertEqual(a["everything_measured_is_over_the_limit"], a["everything_measured"]["total"] > a["limit"])

    def test_it_agrees_with_what_the_run_counted(self):
        """Counted another way: what was carried into the run, and the run's own stages."""
        carried = stage3.carried_over()["total"]
        final = P3 / "evidence" / "stages.json"
        stages = [s for s in json.loads(final.read_text())["stages"] if not s.get("skipped")] if final.exists() else []
        mine = sum(s["agent_tokens"]["input_total"] + (s.get("other_agents_during_the_stage") or {}).get("input_tokens", 0) for s in stages)
        self.assertEqual(self.account["counted_against_the_limit"]["total"], carried + mine)
        if final.exists():
            self.assertEqual(self.account["counted_against_the_limit"]["total"], json.loads(final.read_text())["figures"]["input_tokens_counted"])

    def test_a_reviewer_is_counted_once_and_not_also_as_a_builder(self):
        for name, lanes in accounting.REVIEW_LANES.items():
            document = json.loads((P3 / "evidence" / name).read_text())
            whole = sum(row["agent"]["input_tokens"] for row in document["lanes"])
            reviewing = sum(self.account["reviewers"][f"third_phase_review_and_attack_lanes_of_{name}"].values())
            self.assertEqual(reviewing + self.account["development_agents"][f"third_phase_building_lanes_of_{name}"], whole)
            self.assertEqual(whole, document["totals"]["input_tokens"])

    def test_the_report_lines_say_both_sums_and_what_is_in_no_figure(self):
        text = "\n".join(accounting.render(self.account))
        self.assertIn(f"{self.account['counted_against_the_limit']['total']:,}", text)
        self.assertIn(f"{self.account['everything_measured']['total']:,}", text)
        self.assertIn("Not measured, and in no figure above", text)
        self.assertIn("authoring session", text)
        saved = P3 / "evidence" / "accounting.json"
        if saved.exists():
            self.assertEqual(json.loads(saved.read_text()), self.account, "the saved account is stale: run accounting.py --save")


if __name__ == "__main__":
    unittest.main()
