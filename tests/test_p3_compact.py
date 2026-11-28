import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "swarm" / "phase3"), str(ROOT / "swarm" / "phase2"), str(ROOT / "swarm")]
import compact  # noqa: E402
import tasks  # noqa: E402


def body_of(text):
    return text.split(tasks.RULES, 1)[1] if tasks.RULES in text else text.split("\n\n", 1)[1]


class CompactTest(unittest.TestCase):
    def setUp(self):
        self.texts = [f(n, tasks.SEED)["text"] for f in (tasks.small, tasks.medium) for n in range(1, 21)]

    def test_later_render(self):
        for t in self.texts:
            out = compact.render(t, False)
            self.assertEqual(out.count(compact.SHORT), 1)
            self.assertNotIn(tasks.RULES, out)
            self.assertEqual(out.split("\n", 1)[0], t.split("\n", 1)[0])
            self.assertTrue(out.startswith("## Task "))
            self.assertEqual(out.split(compact.SHORT, 1)[1], t.split(tasks.RULES, 1)[1])

    def test_first_render(self):
        for t in self.texts:
            out = compact.render(t, True)
            self.assertEqual(out.count(tasks.RULES), 1)
            self.assertEqual(out.split(tasks.RULES, 1)[1], compact.render(t.split(tasks.RULES, 1)[1], True))

    def test_no_rules(self):
        t = "## Task X\n\n\n\nbody\n"
        self.assertEqual(compact.render(t, False), "## Task X\n\nbody\n")

    def test_saving(self):
        five = compact.saving(self.texts[:5])
        self.assertGreater(five["percent"], 0)
        self.assertLess(five["after"], five["before"])
        one = compact.saving(self.texts[:1])
        self.assertEqual(one["before"] - one["after"], len(self.texts[0]) - len(compact.render(self.texts[0], True)))
        self.assertEqual(compact.saving([])["percent"], None)


if __name__ == "__main__":
    unittest.main()
