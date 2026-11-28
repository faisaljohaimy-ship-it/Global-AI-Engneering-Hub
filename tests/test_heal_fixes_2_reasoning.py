"""Follow-up fix recheck-w2-heal (e): a root cause leads only with a minimum of net evidence.

Structure alone can reach the leading score (an observed root at prior 0.5 scores 0.731 >= 0.7),
so one supporting row of negligible weight (1e-9; score unchanged at 0.731059) turned
"insufficient_evidence" into a confident "leading". A hypothesis now leads only when its net
evidence support (support - refutation, log-odds) is at least ``MIN_SUPPORT`` (0.3: one fully
reliable row of weight 0.1); each hypothesis reports ``net_support`` and ``structural_score``,
so a leading score visibly carries the evidence.
"""

import math
import pathlib
import unittest

from engineering_os import reasoning as r

D = "d" * 64


def request(evidence=(), rules=(), logs=()):
    return {"schema_version": 1, "dependencies": {"db": [], "api": ["db"]},
            "observations": [{"id": "db", "status": "failed", "evidence_sha256": D},
                             {"id": "api", "status": "failed", "evidence_sha256": D}],
            "hypotheses": [{"id": "h-db", "node": "db", "prior": 0.5}],
            "logs": list(logs), "rules": list(rules), "evidence": list(evidence)}


def row(effect, weight, reliability=1, ident="e1"):
    return {"id": ident, "hypothesis": "h-db", "effect": effect, "weight": weight, "reliability": reliability, "sha256": D}


def logit(p):
    return math.log(p / (1 - p))


class MinimumSupportTests(unittest.TestCase):
    def test_the_threshold_is_one_fully_reliable_row_of_weight_one_tenth(self):
        self.assertEqual(r.MIN_SUPPORT, 0.3)
        out = r.analyze_root_causes(request())
        self.assertGreaterEqual(out["hypotheses"][0]["score"], r.LEADING_SCORE)  # why structure alone is not enough
        self.assertEqual(out["conclusion"], "insufficient_evidence")

    def test_negligible_support_never_leads(self):
        for name, evidence in {"weight 1e-9": [row("supports", 1e-9)],
                               "weight 0.01 x reliability 0.01": [row("supports", 0.01, 0.01)],
                               "weight 0.099": [row("supports", 0.099)]}.items():
            with self.subTest(name=name):
                out = r.analyze_root_causes(request(evidence))
                top = out["hypotheses"][0]
                self.assertEqual(top["status"], "supported")
                self.assertLess(top["net_support"], r.MIN_SUPPORT)
                self.assertEqual((out["conclusion"], out["leading"]), ("insufficient_evidence", None))
                need = next(n for n in out["needs_evidence"] if n["reason"] == "weak_support")
                self.assertIn(f"net evidence support >= {r.MIN_SUPPORT}", need["request"])

    def test_support_at_the_threshold_leads(self):
        out = r.analyze_root_causes(request([row("supports", 0.1)]))
        top = out["hypotheses"][0]
        self.assertEqual(top["net_support"], 0.3)
        self.assertEqual((out["conclusion"], out["leading"]), ("leading", "h-db"))

    def test_the_rule_is_on_net_support(self):
        cases = {(0.2, 0.1): "leading",              # 0.6 - 0.3 = 0.3
                 (0.2, 0.15): "insufficient_evidence"}  # 0.6 - 0.45 = 0.15, still "supported"
        for (support, refute), conclusion in cases.items():
            with self.subTest(support=support, refute=refute):
                out = r.analyze_root_causes(request([row("supports", support), row("refutes", refute, ident="e2")]))
                self.assertEqual(out["hypotheses"][0]["status"], "supported")
                self.assertEqual(out["conclusion"], conclusion)

    def test_log_rules_count_through_the_same_rule(self):
        rule = {"id": "refused", "contains": "connection refused", "hypothesis": "h-db", "effect": "supports", "weight": 1}
        weak = r.analyze_root_causes(request(rules=[rule], logs=[{"id": "l", "node": "db", "reliability": 0.05,
                                                                  "lines": ["db: connection refused"]}]))
        strong = r.analyze_root_causes(request(rules=[rule], logs=[{"id": "l", "node": "db", "reliability": 0.1,
                                                                    "lines": ["db: connection refused"]}]))
        self.assertEqual((weak["conclusion"], strong["conclusion"]), ("insufficient_evidence", "leading"))

    def test_the_score_reflects_the_evidence_mass(self):
        for weight in (1e-9, 0.1, 0.5, 1):
            with self.subTest(weight=weight):
                out = r.analyze_root_causes(request([row("supports", weight)]))
                top = out["hypotheses"][0]
                self.assertEqual(top["structural_score"], r.analyze_root_causes(request())["hypotheses"][0]["score"])
                self.assertAlmostEqual(logit(top["score"]) - logit(top["structural_score"]), top["net_support"], places=4)
                if out["conclusion"] == "leading":
                    self.assertGreater(top["score"], top["structural_score"])
                    self.assertGreaterEqual(top["net_support"], r.MIN_SUPPORT)

    def test_the_rule_is_documented(self):
        text = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "specs" / "gaie-20-layers" / "REASONING.md").read_text(encoding="utf-8")
        self.assertIn("net evidence support ≥ 0.3", text)
        self.assertIn("`structural_score`", text)
        self.assertIn(f"leading needs net support >= {r.MIN_SUPPORT}", r.analyze_root_causes(request())["method"])


if __name__ == "__main__":
    unittest.main()
