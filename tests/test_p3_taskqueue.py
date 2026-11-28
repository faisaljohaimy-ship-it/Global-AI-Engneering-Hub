"""Tests of the task queue: leases, reclaim, and exactly-once claims under load."""
import multiprocessing as mp
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "swarm" / "phase3")]
import taskqueue  # noqa: E402


def _worker(stage, name, barrier, out):
    barrier.wait()
    got = []
    while True:
        ident = taskqueue.claim(stage, name)
        if ident is None:
            break
        got.append(ident)
        taskqueue.release(stage, ident, name, "handed-in")
    out.put((name, got))


class Load(unittest.TestCase):
    def run_case(self, workers, tasks, batch):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            ids = [f"t{i:04d}" for i in range(tasks)]
            taskqueue.create(stage, ids, batch)
            barrier, out = mp.Barrier(workers + 1), mp.Queue()
            procs = [mp.Process(target=_worker, args=(stage, f"w{i}", barrier, out)) for i in range(workers)]
            for p in procs:
                p.start()
            barrier.wait()
            began = time.time()
            results = [out.get(timeout=50) for _ in procs]
            elapsed = time.time() - began
            for p in procs:
                p.join(10)
            claimed = [i for _, got in results for i in got]
            expected = min(tasks, workers * batch)
            self.assertEqual(len(claimed), len(set(claimed)))
            self.assertEqual(len(claimed), expected)
            self.assertTrue(all(len(got) <= batch for _, got in results))
            st = taskqueue.status(stage)
            self.assertEqual((st["waiting"], st["claimed"], st["handed_in"]), (tasks - expected, 0, expected))
            root = stage / ".queue"
            self.assertEqual(os.listdir(root / "reclaiming"), [])
            self.assertEqual(len(os.listdir(root / "waiting")) + len(os.listdir(root / "done")), tasks)
            print(f"\n{workers} processes, {tasks} tasks, batch {batch}: {len(claimed)} claims in "
                  f"{elapsed:.2f}s = {len(claimed) / max(elapsed, 1e-9):.0f} claims/s (measured here)")
            self.assertGreater(len(claimed) / max(elapsed, 1e-9), 1)

    def test_batch_9_120_processes(self):
        self.run_case(120, 1000, 9)

    def test_batch_10_100_processes(self):
        self.run_case(100, 1000, 10)

    def test_batch_8_125_processes(self):
        self.run_case(125, 1000, 8)

    def test_batch_1_caps_every_worker(self):
        self.run_case(100, 1000, 1)


class Small(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stage = Path(self.tmp.name)

    def test_empty_queue(self):
        taskqueue.create(self.stage, [], 3)
        self.assertIsNone(taskqueue.claim(self.stage, "a"))
        self.assertIsNone(taskqueue.status(self.stage)["oldest_claim_age"])
        self.assertEqual(taskqueue.reclaim(self.stage, 1e9), [])

    def test_bad_worker_name(self):
        taskqueue.create(self.stage, ["x"], 1)
        for bad in ("", "a b", "../x", "a" * 41):
            with self.assertRaises(ValueError):
                taskqueue.claim(self.stage, bad)
        with self.assertRaises(ValueError):
            taskqueue.release(self.stage, "x", "a/b", "failed")

    def test_unknown_outcome(self):
        taskqueue.create(self.stage, ["x"], 1)
        taskqueue.claim(self.stage, "a")
        with self.assertRaises(ValueError):
            taskqueue.release(self.stage, "x", "a", "done")
        self.assertEqual(taskqueue.holder(self.stage, "x"), "a")

    def test_release_twice(self):
        taskqueue.create(self.stage, ["x"], 1)
        taskqueue.claim(self.stage, "a")
        taskqueue.release(self.stage, "x", "a", "failed")
        taskqueue.release(self.stage, "x", "a", "handed-in")
        st = taskqueue.status(self.stage)
        self.assertEqual((st["failed"], st["handed_in"], st["claimed"]), (1, 0, 0))

    def test_age_and_reclaim_and_reclaim_again(self):
        taskqueue.create(self.stage, ["x", "y"], 1)
        self.assertEqual(taskqueue.claim(self.stage, "a", now=1000.0), "x")
        self.assertIsNone(taskqueue.claim(self.stage, "a", now=1000.0))  # batch of 1
        self.assertEqual(taskqueue.status(self.stage, now=1100.0)["oldest_claim_age"], 100.0)
        self.assertEqual(taskqueue.reclaim(self.stage, 1900.0), [])  # exactly the lease: not older
        self.assertEqual(taskqueue.reclaim(self.stage, 1901.0), ["x"])
        st = taskqueue.status(self.stage, now=1901.0)
        self.assertEqual((st["waiting"], st["claimed"], st["by_worker"]["a"]), (2, 0, []))
        self.assertEqual(taskqueue.claim(self.stage, "a", now=2000.0), "x")  # a worker may take it again
        self.assertEqual(taskqueue.claim(self.stage, "b", now=2000.0), "y")

    def test_late_hand_in_is_not_recorded(self):
        taskqueue.create(self.stage, ["x"], 2)
        taskqueue.claim(self.stage, "a", now=0.0)
        taskqueue.reclaim(self.stage, 5000.0)
        self.assertEqual(taskqueue.claim(self.stage, "b", now=5001.0), "x")
        taskqueue.release(self.stage, "x", "a", "handed-in")  # a's claim ran out
        self.assertEqual(taskqueue.holder(self.stage, "x"), "b")
        self.assertEqual(taskqueue.status(self.stage)["handed_in"], 0)
        taskqueue.release(self.stage, "x", "b", "handed-in")
        self.assertEqual(taskqueue.status(self.stage)["handed_in"], 1)

    def test_late_hand_in_before_reclaim_runs_is_not_possible_after_it(self):
        taskqueue.create(self.stage, ["x"], 1)
        taskqueue.claim(self.stage, "a", now=0.0)
        taskqueue.reclaim(self.stage, 5000.0)
        taskqueue.release(self.stage, "x", "a", "handed-in")  # back in waiting: nothing to hand in
        st = taskqueue.status(self.stage)
        self.assertEqual((st["waiting"], st["handed_in"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
