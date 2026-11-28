import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "swarm" / "phase3")]
import cache_report  # noqa: E402

W = {"cache_write_5m": 1.25, "cache_read": 0.1}


def line(mid, inp, write, read):
    return json.dumps({"type": "assistant", "timestamp": "2026-01-01T00:00:00Z",
                       "message": {"id": mid, "usage": {
                           "input_tokens": inp, "cache_creation_input_tokens": write,
                           "cache_read_input_tokens": read, "output_tokens": 5}}})


class CacheReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def rec(self, name, lines):
        p = self.dir / name
        p.write_text("\n".join(lines) + ("\n" if lines else ""))
        return p

    def test_cold_agents(self):
        a = self.rec("a", [line("m1", 10, 1000, 0)])
        b = self.rec("b", [line("m1", 10, 800, 0)])
        r = cache_report.report([a, b], W)
        self.assertEqual(r["agents"], 2)
        self.assertEqual(r["share_first_request_half_cached"], 0.0)
        self.assertEqual(r["warm_prefix_estimate"]["tokens"], 800)
        self.assertAlmostEqual(r["warm_prefix_estimate"]["cost_units"], 800 * 1.15)

    def test_warm_agents(self):
        a = self.rec("a", [line("m1", 10, 1000, 0)])
        b = self.rec("b", [line("m1", 10, 50, 950), line("m2", 5, 0, 1000)])
        r = cache_report.report([a, b], W)
        self.assertEqual(r["share_first_request_half_cached"], 0.5)
        self.assertEqual(r["first_request"]["cache_read_tokens"], 950)
        self.assertEqual(r["whole_records"]["cache_read_tokens"], 1950)
        self.assertEqual(r["whole_records"]["cache_written_tokens"], 1050)
        self.assertEqual(r["warm_prefix_estimate"]["tokens"], 50)

    def test_duplicated_id_counted_once(self):
        a = self.rec("a", [line("m1", 10, 100, 0), line("m1", 10, 100, 0),
                           line("m2", 1, 0, 100)])
        r = cache_report.report([a], W)
        self.assertEqual(r["whole_records"]["cache_written_tokens"], 100)
        self.assertEqual(r["whole_records"]["cache_read_tokens"], 100)
        self.assertEqual(r["first_request"]["uncached_tokens"], 10)

    def test_empty_record(self):
        e = self.rec("e", [])
        r = cache_report.report([e], W)
        self.assertEqual(r["agents"], 0)
        self.assertEqual(r["empty_records"], 1)
        self.assertIsNone(r["share_first_request_half_cached"])
        self.assertIsNone(r["warm_prefix_estimate"]["tokens"])

    def test_missing_weights_gives_none(self):
        a = self.rec("a", [line("m1", 1, 100, 0)])
        b = self.rec("b", [line("m1", 1, 100, 0)])
        r = cache_report.report([a, b], {})
        self.assertIsNone(r["warm_prefix_estimate"]["cost_units"])
        self.assertEqual(r["warm_prefix_estimate"]["tokens"], 100)


if __name__ == "__main__":
    unittest.main()
