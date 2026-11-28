"""Tests: the medium reference solutions keep their stated properties (30 variants per family),
and the property checks themselves catch deliberately broken references."""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
import properties  # noqa: E402

VARIANTS = 30


class ReferenceProperties(unittest.TestCase):
    def family(self, name):
        for index in range(VARIANTS):
            with self.subTest(family=name, variant=index):
                self.assertEqual(properties.check_variant(properties.number_of(name, index)), [])

    def test_ledger(self):
        self.family("ledger")

    def test_expr(self):
        self.family("expr")

    def test_rooms(self):
        self.family("rooms")

    def test_graph(self):
        self.family("graph")


class ChecksCatchBugs(unittest.TestCase):
    def broken(self, name, old, new, index=0):
        item = properties.tasks.medium(properties.number_of(name, index), properties.tasks.SEED)
        self.assertIn(old, item["reference"])
        reference = item["reference"].replace(old, new, 1)
        bad = []
        for n in range(6):
            bad += properties.CHECKS[name](item["text"], reference, random.Random(n))
        return bad

    def test_ledger_bugs(self):
        self.assertTrue(self.broken("ledger", "self.money[account] -= amount\n", "self.money[account] -= amount + 1\n"))
        self.assertTrue(self.broken("ledger", "(-self.money[name], name)", "(self.money[name], name)"))

    def test_rooms_bug(self):
        self.assertTrue(self.broken("rooms", "other_start < end", "other_start < start"))
        self.assertTrue(self.broken("rooms", "[at, start]", "[at, start + 1]"))

    def test_graph_bug(self):
        self.assertTrue(self.broken("graph", "and name in self._reach(other))", "and name in self.needs[other])"))
        self.assertTrue(self.broken("graph", "result.append(pick)", "result.insert(0, pick)"))

    def test_expr_bug(self):
        self.assertTrue(self.broken("expr", 'if token == "-":\n            return -factor()', 'if token == "-":\n            return factor()'))


if __name__ == "__main__":
    unittest.main()
