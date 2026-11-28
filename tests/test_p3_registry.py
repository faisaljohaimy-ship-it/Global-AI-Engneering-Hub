import collections
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
import registry  # noqa: E402


def mixed(n=1000):
    return [{"id": f"t{i:04d}", "size": registry.SIZES[i % 3]} for i in range(n)]


class RegistryTest(unittest.TestCase):
    def test_places(self):
        s = registry.slots()
        self.assertEqual(len(s), 1000)
        self.assertEqual(len({p["id"] for p in s}), 1000)
        self.assertTrue(all(p["status"] == "registered" for p in s))
        per = collections.Counter(p["role"] for p in s)
        self.assertEqual(len(per), 100)
        self.assertEqual(set(per.values()), {10})

    def test_every_size_has_100_places(self):
        s = registry.slots()
        for size in registry.SIZES:
            self.assertGreaterEqual(sum(size in p["sizes"] for p in s), 100)

    def test_assignment_respects_sizes(self):
        s = registry.slots()
        by_id = {p["id"]: p for p in s}
        tasks = mixed()
        got = registry.assign(tasks, s)
        self.assertEqual(len(got), 1000)
        for t in tasks:
            self.assertIn(t["size"], by_id[got[t["id"]]]["sizes"])
        load = collections.Counter(got.values())
        self.assertLessEqual(max(load.values()), 2)

    def test_deterministic(self):
        s = registry.slots()
        self.assertEqual(registry.assign(mixed(), s), registry.assign(list(reversed(mixed())), s))

    def test_missing_size(self):
        with self.assertRaises(ValueError):
            registry.assign([{"id": "x", "size": "huge"}], registry.slots())

    def test_check_on_committed_file(self):
        self.assertEqual(registry.main(["--check"]), 0)
        self.assertIn("not an agent that ran", registry.document())


if __name__ == "__main__":
    unittest.main()
