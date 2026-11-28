import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "swarm" / "phase3")]
import timeline  # noqa: E402


def stamp(t):
    return "2026-01-01T00:%02d:%06.3fZ" % (int(t // 60), t % 60)


class TimelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def rec(self, name, start, end, reply):
        rows = [{"type": "user", "timestamp": stamp(start)},
                {"type": "assistant", "timestamp": stamp(reply)},
                {"type": "user", "timestamp": stamp(end)}]
        p = self.dir / (name + ".jsonl")
        p.write_text("\n".join(json.dumps(r) for r in rows))
        return p

    def test_together(self):
        ps = [self.rec("a%d" % i, 0, 10.5, 2) for i in range(10)]
        d = timeline.build(ps)
        self.assertEqual(d["peak"], 10)
        self.assertEqual(d["peak_seconds"], 11)
        self.assertEqual(d["active"], [[11, 10]])
        self.assertEqual(d["first_reply_delay"]["median"], 2)
        self.assertEqual(d["plateaus"], [])
        self.assertIn("does not prove", d["note"])

    def test_staggered(self):
        ps = [self.rec("a%d" % i, i, 30, i + 1) for i in range(10)]
        d = timeline.build(ps)
        self.assertEqual(d["peak"], 10)
        self.assertEqual(d["plateaus"], [])
        self.assertEqual(d["first_reply_delay"]["max"], 10)
        self.assertEqual(d["active"][0], [1, 1])
        self.assertEqual(d["duration"]["max"], 30)

    def test_limited(self):
        ps = [self.rec("a%d_%d" % (w, i), w * 5, w * 5 + 4.5, w * 5 + 1)
              for w in range(3) for i in range(10)]
        d = timeline.build(ps)
        self.assertEqual(d["peak"], 10)
        self.assertEqual(d["plateaus"],
                         [{"from_second": 0, "seconds": 10, "active": 10}])

    def test_empty_and_start(self):
        self.assertIsNone(timeline.build([])["peak"])
        p = self.rec("x", 5, 9, 6)
        d = timeline.build([p], start=timeline._ts(stamp(0)))
        self.assertEqual(d["first_reply_delay"]["max"], 6)


if __name__ == "__main__":
    unittest.main()
