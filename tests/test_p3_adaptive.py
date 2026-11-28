"""Tests for swarm/phase3/adaptive.py: one per rule, the caps, and six waves played through."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "swarm" / "phase3"))
from adaptive import next_wave  # noqa: E402

LIM = {"start": 4, "max_agents": 64, "max_batch": 8, "tokens_left": 10**9, "tasks_left": 10**6}


def wave(agents=8, batch=1, peak=None, tpm=100.0, rate=100, err=0, tok=1000):
    return {"agents": agents, "batch": batch, "peak_concurrent_agents": agents if peak is None else peak,
            "tasks_per_minute": tpm, "verified_success_rate": rate,
            "agents_with_limit_error": err, "input_tokens_per_agent": tok}


class Rules(unittest.TestCase):
    def test_no_history(self):
        r = next_wave([], LIM)
        self.assertEqual((r["agents"], r["batch"]), (4, 1))

    def test_limit_error_stops(self):
        self.assertEqual(next_wave([wave(err=2)], LIM)["agents"], 0)

    def test_low_rate_halves(self):
        r = next_wave([wave(agents=9, batch=2, rate=85)], LIM)
        self.assertEqual((r["agents"], r["batch"]), (4, 2))
        self.assertEqual(next_wave([wave(agents=1, rate=10)], LIM)["agents"], 1)

    def test_low_peak(self):
        r = next_wave([wave(agents=10, peak=7)], LIM)
        self.assertEqual(r["agents"], 7)
        self.assertEqual(next_wave([wave(agents=10, peak=8)], LIM)["agents"], 20)

    def test_growth_doubles_and_clamps(self):
        h = [wave(agents=4, tpm=100), wave(agents=8, tpm=110)]
        self.assertEqual(next_wave(h, LIM)["agents"], 16)
        h = [wave(agents=4, tpm=100), wave(agents=40, tpm=200)]
        self.assertEqual(next_wave(h, LIM)["agents"], 64)

    def test_flat_raises_batch(self):
        h = [wave(agents=8, tpm=100), wave(agents=16, tpm=105)]
        r = next_wave(h, LIM)
        self.assertEqual((r["agents"], r["batch"]), (16, 2))
        h = [wave(agents=8, batch=4, tpm=100), wave(agents=8, batch=4, tpm=100)]
        self.assertEqual(next_wave(h, LIM)["batch"], 8)

    def test_both_stopped_paying(self):
        h = [wave(batch=8, tpm=100), wave(batch=8, tpm=100)]
        r = next_wave(h, LIM)
        self.assertEqual(r["agents"], 0)
        self.assertIn("stopped paying", r["reason"])

    def test_missing_numbers_are_not_guessed(self):
        h = [wave(tpm=None, peak=8, rate=None), wave(tpm=None, rate=None)]
        self.assertEqual(next_wave(h, LIM)["batch"], 2)

    def test_reasons_are_one_sentence_with_numbers(self):
        for h in ([], [wave(err=1)], [wave(rate=50)], [wave(agents=10, peak=2)], [wave()]):
            r = next_wave(h, LIM)["reason"]
            self.assertTrue(r.endswith(".") and r.count(". ") == 0, r)
            self.assertTrue(any(c.isdigit() for c in r), r)


class Caps(unittest.TestCase):
    def test_task_cap(self):
        r = next_wave([wave(agents=8, tpm=100)], dict(LIM, tasks_left=10))
        self.assertEqual(r["agents"], 10 // r["batch"] if 16 > 10 else 16)
        self.assertLessEqual(r["agents"] * r["batch"], 10)

    def test_token_cap(self):
        r = next_wave([wave(agents=8, tok=1000)], dict(LIM, tokens_left=5500))
        self.assertEqual(r["agents"], 5)

    def test_nothing_fits(self):
        r = next_wave([wave(agents=8, tok=1000)], dict(LIM, tokens_left=999))
        self.assertEqual(r["agents"], 0)
        self.assertIn("999", r["reason"])
        self.assertEqual(next_wave([], dict(LIM, tasks_left=0))["agents"], 0)


class SixWaves(unittest.TestCase):
    def test_table(self):
        # (agents, batch, peak, tpm, rate, err) measured per wave; expected next (agents, batch)
        table = [
            ((4, 1, 4, 50, 100, 0), (8, 1)),
            ((8, 1, 8, 100, 100, 0), (16, 1)),
            ((16, 1, 12, 150, 100, 0), (12, 1)),
            ((12, 1, 12, 152, 96, 0), (12, 2)),
            ((12, 2, 12, 154, 80, 0), (6, 2)),
            ((6, 2, 6, 100, 100, 1), (0, 2)),
        ]
        history = []
        for (a, b, p, t, r, e), want in table:
            history.append(wave(agents=a, batch=b, peak=p, tpm=t, rate=r, err=e))
            got = next_wave(history, LIM)
            self.assertEqual((got["agents"], got["batch"]), want, got["reason"])


if __name__ == "__main__":
    unittest.main()
