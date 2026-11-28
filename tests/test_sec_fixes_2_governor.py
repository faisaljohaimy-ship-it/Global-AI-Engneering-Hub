"""recheck-security item 3 (M4 partial): the governor reads back only the bounded tail of each output
stream, and the writable paths of a run may grow by disk_mb at most.

Measured on the reviewer's case before the fix: 2 x 32 MiB of non-UTF-8 output raised the parent to
285 MB (both temp files read whole and decoded), and 12 files of 31 MiB stayed in the run directory.
The _launch tests run on every host (cage limits only, no namespaces); the sandbox_run tests use the
full tier where this host has it and otherwise assert the recorded refusal or the plain tier.
"""
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import governor  # noqa: E402
from engineering_os.governor import GovernorDenied  # noqa: E402

MIB = 1024 * 1024
TIER = governor.isolation_probe()["tier"]  # measured once, before any test patches what the probe itself uses
# Writes `count` files of 1 MiB, `pause` seconds apart, then a flag; a slow writer the poll must catch.
WRITER = r"""
import os, sys, time
count, pause = int(sys.argv[1]), float(sys.argv[2])
for i in range(count):
    with open(f"fill{i}", "wb") as handle:
        handle.write(os.urandom(1 << 20))
        handle.flush()
        os.fsync(handle.fileno())
    time.sleep(pause)
open("finished", "w").write("x")
"""


def limits(**extra):
    return {"cpu_seconds": 60, "memory_mb": 1024, "file_mb": 64, "nofile": 256, **extra}


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="gaie-sf2g-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.addCleanup(shutil.rmtree, tmp, True)
        self.work = pathlib.Path(os.path.realpath(tmp)) / "work"
        self.work.mkdir()

    def launch(self, code, *args, timeout=60, **extra):
        env = {"PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8", "HOME": str(self.work)}
        proc, out, err, limit = governor._launch([sys.executable, "-I", "-S", "-c", code, *map(str, args)],
                                                 cwd=str(self.work), env=env, timeout=timeout,
                                                 limits=limits(**extra), net_in_child=False)
        return proc, governor._text(out), governor._text(err), limit


class OutputTailTests(Case):
    def test_only_the_tail_is_read_and_the_drop_is_stated(self):
        with tempfile.TemporaryFile() as handle:
            handle.write(b"A" * (3 * MIB) + bytes(range(128, 256)) * 16384 + b"END\n")  # head, then 2 MiB non-UTF-8
            handle.flush()
            size = handle.tell()
            text = governor._text(handle)
        first, rest = text.split("\n", 1)
        self.assertEqual(first, f"[governor: the first {size - governor.OUTPUT_TAIL_BYTES} bytes of this stream were dropped]")
        self.assertNotIn("A", rest)  # the head was never part of what was read
        self.assertTrue(rest.endswith("END\n"))
        self.assertIn("�", rest)  # non-UTF-8 bytes decode lossily, never raise
        self.assertLessEqual(len(rest), governor.OUTPUT_TAIL_BYTES)

    def test_a_short_stream_is_returned_whole_without_a_marker(self):
        with tempfile.TemporaryFile() as handle:
            handle.write("ok é\n".encode("utf-8"))
            self.assertEqual(governor._text(handle), "ok é\n")

    def test_a_flood_on_both_streams_reaches_the_caller_as_two_bounded_tails(self):
        code = "import os\nchunk = bytes(range(128, 256)) * 8192\nfor _ in range(24):\n    os.write(1, chunk); os.write(2, chunk)\n"
        proc, out, err, limit = self.launch(code)
        self.assertEqual((proc.returncode, limit), (0, None))
        for text in (out, err):
            self.assertTrue(text.startswith("[governor: the first "), text[:80])
            self.assertLess(len(text), governor.OUTPUT_TAIL_BYTES + 200)


class DiskCapTests(Case):
    def test_a_run_past_its_disk_cap_is_killed_and_recorded(self):
        proc, _, _, limit = self.launch(WRITER, 40, 0.1, watch=(str(self.work),), disk_mb=8)
        self.assertEqual(limit, "disk")
        self.assertFalse((self.work / "finished").exists())
        written = sum(path.stat().st_size for path in self.work.iterdir())
        self.assertGreater(written, 8 * MIB)
        self.assertLess(written, 20 * MIB)  # the poll caught it long before the 40 MiB the writer wanted

    def test_a_run_that_ends_between_two_polls_above_the_cap_is_recorded(self):
        with mock.patch.object(governor, "DISK_POLL_SECONDS", 60):
            proc, _, _, limit = self.launch(WRITER, 12, 0, watch=(str(self.work),), disk_mb=4)
        self.assertEqual((proc.returncode, limit), (0, "disk"))
        self.assertTrue((self.work / "finished").exists())

    def test_growth_is_measured_from_the_start_and_a_run_within_the_cap_is_untouched(self):
        (self.work / "existing.bin").write_bytes(os.urandom(6 * MIB))  # present before the run: not growth
        proc, _, _, limit = self.launch(WRITER, 2, 0, watch=(str(self.work),), disk_mb=4)
        self.assertEqual((proc.returncode, limit), (0, None))
        self.assertTrue((self.work / "finished").exists())

    def test_a_tree_too_large_to_measure_is_refused_before_anything_runs(self):
        for index in range(8):
            (self.work / f"f{index}").write_text("x")
        with mock.patch.object(governor, "DISK_WALK_ENTRIES", 5), self.assertRaises(GovernorDenied) as caught:
            self.launch("open('ran', 'w').write('x')", watch=(str(self.work),), disk_mb=4)
        self.assertEqual(caught.exception.reason, "invalid-limit")
        self.assertFalse((self.work / "ran").exists())

    def test_usage_counts_allocated_bytes_once_and_never_follows_links(self):
        (self.work / "a.bin").write_bytes(b"x" * MIB)
        os.link(self.work / "a.bin", self.work / "b.bin")
        (self.work / "sub").mkdir()
        outside = self.work.parent / "outside.bin"
        outside.write_bytes(b"y" * (4 * MIB))
        (self.work / "sub" / "link").symlink_to(outside)
        used = governor._disk_usage([str(self.work)])
        self.assertGreaterEqual(used, MIB)
        self.assertLess(used, 2 * MIB)

    def test_sandbox_run_defaults_the_cap_to_a_multiple_of_file_mb_and_validates_it(self):
        seen = {}

        def capture(argv, **kw):
            seen.update(kw["limits"])
            raise GovernorDenied("sandbox-setup-failed", "captured")
        with mock.patch.object(governor, "_launch", capture):
            for disk_mb, expected in ((None, governor.DISK_FACTOR * 16), (3, 3)):
                seen.clear()
                with self.assertRaises(GovernorDenied):
                    governor.sandbox_run(["true"], cwd=str(self.work), timeout=5, allowed_paths=[str(self.work)],
                                         file_mb=16, disk_mb=disk_mb)
                if seen:  # a host that refuses earlier (no network namespace) never reaches _launch
                    self.assertEqual((seen["disk_mb"], seen["watch"]), (expected, (str(self.work),)))
        for bad in (0, -1, "8", True, 1 << 21):
            with self.subTest(disk_mb=bad), self.assertRaises(GovernorDenied) as caught:
                governor.sandbox_run(["true"], cwd=str(self.work), timeout=5, allowed_paths=[str(self.work)],
                                     disk_mb=bad)
            self.assertEqual(caught.exception.reason, "invalid-limit")


class SandboxRunTests(Case):
    def test_the_full_sandbox_kills_a_run_that_fills_its_workspace(self):
        if TIER != "full":
            raise unittest.SkipTest("the full tier is missing here; the _launch tests above cover the cap on every host")
        run = governor.sandbox_run([sys.executable, "-I", "-S", "-c", WRITER, "40", "0.1"], cwd=str(self.work),
                                   timeout=60, allowed_paths=[str(self.work)], disk_mb=8)
        self.assertEqual((run["limit"], run["fs_isolated"]), ("disk", True))
        self.assertFalse((self.work / "finished").exists())
        self.assertLess(sum(path.stat().st_size for path in self.work.iterdir()), 20 * MIB)


if __name__ == "__main__":
    unittest.main()
