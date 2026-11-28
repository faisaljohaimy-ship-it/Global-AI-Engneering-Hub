"""Review fixes w2-memory-heal-orch M5 (root-cause evidence weight) and L6 (trade-off ties).

M5: analyze_root_causes called a hypothesis "supported" whenever it had any evidence row
and refutation did not exceed support, so one refuting row of weight 0 (or reliability 0)
turned "insufficient_evidence" into a confident "leading" root cause. Non-positive
weights and reliabilities are now refused, and the status follows the evidence weight:
no weight either way is unsupported, equal weight both ways is conflicting.

L6: trade_off with identical options picked the first option id as winner and called it
both ``tie`` and ``robust``. A tie is now reported with the tied options and is never
robust; a clear winner keeps its robustness verdict.
"""

import copy
import unittest

from engineering_os import reasoning as r
from engineering_os.reasoning import ReasoningError

D = "d" * 64


def rca_request(evidence=(), rules=(), logs=()):
    return {"schema_version": 1, "dependencies": {"db": [], "api": ["db"]},
            "observations": [{"id": "db", "status": "failed", "evidence_sha256": D},
                             {"id": "api", "status": "failed", "evidence_sha256": D}],
            "hypotheses": [{"id": "h-db", "node": "db", "prior": 0.5}],
            "logs": list(logs), "rules": list(rules), "evidence": list(evidence)}


def row(effect, weight, reliability=1, ident="e1"):
    return {"id": ident, "hypothesis": "h-db", "effect": effect, "weight": weight, "reliability": reliability, "sha256": D}


LOG = {"id": "db-log", "node": "db", "reliability": 0.9, "lines": ["db: connection refused"]}
RULE = {"id": "refused", "contains": "connection refused", "hypothesis": "h-db", "effect": "supports", "weight": 0.5}


class RootCauseEvidenceWeightTests(unittest.TestCase):
    def test_no_evidence_is_insufficient(self):
        out = r.analyze_root_causes(rca_request())
        self.assertEqual((out["conclusion"], out["leading"], out["hypotheses"][0]["status"]), ("insufficient_evidence", None, "unsupported"))

    def test_weightless_rows_are_refused_not_read_as_support(self):
        cases = {"refuting row, weight 0": rca_request([row("refutes", 0)]),
                 "refuting row, reliability 0": rca_request([row("refutes", 1, reliability=0)]),
                 "supporting row, weight 0": rca_request([row("supports", 0)]),
                 "rule weight 0": rca_request(rules=[dict(RULE, weight=0)], logs=[LOG]),
                 "log reliability 0": rca_request(rules=[RULE], logs=[dict(LOG, reliability=0)]),
                 "negative weight": rca_request([row("refutes", -0.5)])}
        for name, request in cases.items():
            with self.subTest(name=name), self.assertRaises(ReasoningError):
                r.analyze_root_causes(request)

    def test_evidence_that_rounds_to_zero_weight_is_insufficient(self):
        for effect in ("refutes", "supports"):
            with self.subTest(effect=effect):
                out = r.analyze_root_causes(rca_request([row(effect, 1e-12)]))
                hypothesis = out["hypotheses"][0]
                self.assertEqual((hypothesis["support"], hypothesis["refutation"]), (0.0, 0.0))
                self.assertEqual(hypothesis["status"], "unsupported")
                self.assertEqual(out["conclusion"], "insufficient_evidence")
                self.assertIsNone(out["leading"])

    def test_equal_support_and_refutation_is_conflicting_not_supported(self):
        out = r.analyze_root_causes(rca_request([row("supports", 0.2, ident="e1"), row("refutes", 0.2, ident="e2")]))
        hypothesis = out["hypotheses"][0]
        self.assertEqual(hypothesis["support"], hypothesis["refutation"])
        self.assertEqual(hypothesis["status"], "conflicting")
        self.assertEqual(out["conclusion"], "insufficient_evidence")
        self.assertIn("conflicting_signals", [need["reason"] for need in out["needs_evidence"]])

    def test_a_refuting_row_never_makes_a_hypothesis_leading(self):
        out = r.analyze_root_causes(rca_request([row("refutes", 0.1)]))
        self.assertEqual(out["hypotheses"][0]["status"], "refuted")
        self.assertNotEqual(out["conclusion"], "leading")

    def test_positive_support_still_leads(self):
        out = r.analyze_root_causes(rca_request([row("supports", 0.5)]))
        self.assertEqual((out["conclusion"], out["leading"], out["hypotheses"][0]["status"]), ("leading", "h-db", "supported"))
        out = r.analyze_root_causes(rca_request(rules=[RULE], logs=[LOG]))
        self.assertEqual((out["conclusion"], out["leading"]), ("leading", "h-db"))

    def test_the_request_is_not_mutated(self):
        request = rca_request([row("supports", 0.5)])
        before = copy.deepcopy(request)
        r.analyze_root_causes(request)
        self.assertEqual(request, before)



def trade_request(values, criteria=None, margin=0.2):
    return {"schema_version": 1, "decision": "d", "options": sorted(values), "robustness_margin": margin,
            "criteria": criteria or [{"id": "cost", "weight": 0.5, "direction": "lower"}, {"id": "speed", "weight": 0.5, "direction": "higher"}],
            "values": values}


class TradeOffTieTests(unittest.TestCase):
    def test_identical_options_are_a_tie_and_not_robust(self):
        out = r.trade_off(trade_request({"a": {"cost": 1, "speed": 1}, "b": {"cost": 1, "speed": 1}}))
        self.assertTrue(out["tie"])
        self.assertEqual(out["tied"], ["a", "b"])
        self.assertFalse(out["robust"])  # was True: an id-ordered pick reported as robust
        self.assertEqual(out["margin"], 0.0)
        self.assertIsNone(out["most_sensitive"])

    def test_one_criterion_identical_and_three_way_ties(self):
        one = r.trade_off(trade_request({"a": {"cost": 1}, "b": {"cost": 1}}, [{"id": "cost", "weight": 1.0, "direction": "lower"}]))
        self.assertEqual((one["tie"], one["tied"], one["robust"]), (True, ["a", "b"], False))
        three = r.trade_off(trade_request({o: {"cost": 2, "speed": 5} for o in ("x", "y", "z")}, margin=0))
        self.assertEqual((three["tie"], three["tied"], three["robust"]), (True, ["x", "y", "z"], False))

    def test_a_partial_tie_lists_only_the_tied_leaders(self):
        out = r.trade_off(trade_request({"a": {"cost": 1, "speed": 2}, "b": {"cost": 2, "speed": 3}, "c": {"cost": 2, "speed": 2}}))
        self.assertEqual((out["tie"], out["tied"], out["robust"]), (True, ["a", "b"], False))
        self.assertNotIn("c", out["tied"])

    def test_a_clear_winner_keeps_its_robustness_verdict(self):
        out = r.trade_off(trade_request({"a": {"cost": 1, "speed": 9}, "b": {"cost": 9, "speed": 1}}))
        self.assertEqual((out["winner"], out["tie"], out["tied"], out["robust"]), ("a", False, [], True))


if __name__ == "__main__":
    unittest.main()
