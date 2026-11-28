"""recheck-security item 4 (L1 variant): in the opt-in process-only mode of detectors.Sandbox, no helper
outlives its run, whatever it does to its environment, session or working directory.

Measured before the fix with the reviewer's l1_variant.py: a setsid helper started with env={} survived
(the sweep looked for the run marker in /proc/<pid>/environ only). The driver now runs under a child
subreaper (detectors.REAPER) that kills and reaps every descendant the run orphans; the marker sweep also
kills whatever shares a session or process group with a marked process. These tests use the process-only
mode, which runs on every host (no namespaces); the OS mode ends its pid namespace and is covered by
tests/test_isolation_enforcement.py.
"""
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import detectors  # noqa: E402


def tagged(tag):
    """Live (not zombie) processes whose command line carries `tag`."""
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            if tag.encode() not in pathlib.Path(f"/proc/{entry}/cmdline").read_bytes():
                continue
            state = pathlib.Path(f"/proc/{entry}/stat").read_bytes().rsplit(b")", 1)[1].split()[0]
        except (OSError, IndexError):
            continue
        if state != b"Z":
            found.append(int(entry))
    return found


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="gaie-sf2s-", dir="/tmp" if os.path.isdir("/tmp") else None))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tag = "sf2sweep-" + os.urandom(4).hex()
        self.addCleanup(self.kill_tagged)

    def kill_tagged(self):
        for pid in tagged(self.tag):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def target(self, body):
        root = self.tmp / "target"
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "test_helpers.py").write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        return root

    def run_box(self, root, timeout=60):
        box = detectors.Sandbox(self.tmp / "box", timeout=timeout, isolation="process-only")
        return box.run_tests(root, "tests", "test_*.py")


HELPERS = '''
    import os, subprocess, sys, unittest
    TAG = {tag!r}
    SLEEP = "import time; time.sleep(60)"
    DOUBLE = ("import os, subprocess, sys\\n"
              "if os.fork():\\n    os._exit(0)\\n"
              "os.setsid(); os.chdir('/')\\n"
              "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', sys.argv[1] + '-grandchild'], env={{}},"
              " start_new_session=True, cwd='/')\\n")
    class Helpers(unittest.TestCase):
        def test_spawn(self):
            # 1 the reviewer's case: own session, empty environment
            subprocess.Popen([sys.executable, "-c", SLEEP, TAG + "-noenv"], env={{}}, start_new_session=True)
            # 2 empty environment, own session, working directory outside the run, started through a double fork
            subprocess.run([sys.executable, "-c", DOUBLE, TAG + "-double"], env={{}}, cwd="/", check=True)
            # 3 empty environment but the run's own session (no setsid)
            subprocess.Popen([sys.executable, "-c", SLEEP, TAG + "-session"], env={{}})
            # 4 the plain helper (keeps the marker)
            subprocess.Popen([sys.executable, "-c", SLEEP, TAG + "-plain"], start_new_session=True)
{extra}
'''


class SweepTests(Case):
    def test_no_helper_outlives_the_run_whatever_it_sheds(self):
        root = self.target(HELPERS.format(tag=self.tag, extra=""))
        result = self.run_box(root)
        self.assertEqual(result["status"], "ok", result.get("log_tail"))
        self.assertEqual(result["tests"], {"test_helpers.Helpers.test_spawn": "passed"})
        self.assertEqual(result["isolation"]["mode"], "process-only")
        self.assertEqual(tagged(self.tag), [])

    def test_a_stopped_run_is_reaped_too(self):
        """Timeout: the driver ignores SIGTERM and sleeps; its helpers shed the marker and the session."""
        extra = '''
            def test_hang(self):
                import signal, time
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                self.test_spawn()
                time.sleep(120)
        '''
        root = self.target(HELPERS.format(tag=self.tag, extra=textwrap.indent(textwrap.dedent(extra), " " * 8)))
        started = time.monotonic()
        result = self.run_box(root, timeout=8)
        self.assertEqual(result["status"], "timeout")
        self.assertLess(time.monotonic() - started, 40)
        self.assertEqual(tagged(self.tag), [])

    def test_the_driver_exit_code_and_signal_reach_the_caller_unchanged(self):
        root = self.target('''
            import os, signal, unittest
            class Dies(unittest.TestCase):
                def test_dies(self):
                    os.kill(os.getpid(), signal.SIGKILL)
        ''')
        result = self.run_box(root)
        self.assertEqual((result["status"], result["exit_code"]), ("crashed", -signal.SIGKILL))


class ReaperTests(Case):
    def test_without_the_subreaper_nothing_runs(self):
        flag = self.tmp / "ran"
        refuse = ("import ctypes\nclass _Libc:\n    def prctl(self, *args):\n        return -1\n"
                  "ctypes.CDLL = lambda *args, **kwargs: _Libc()\n")
        done = subprocess.run([sys.executable, "-I", "-S", "-c", refuse + detectors.REAPER, sys.executable, "-c",
                               f"open({str(flag)!r}, 'w').write('x')"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 125)
        self.assertIn("PR_SET_CHILD_SUBREAPER refused", done.stderr)
        self.assertFalse(flag.exists())

    def test_the_reaper_passes_the_exit_code_through(self):
        done = subprocess.run([sys.executable, "-I", "-S", "-c", detectors.REAPER, sys.executable, "-c",
                               "import sys; sys.exit(7)"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 7)

    def test_the_marker_sweep_spares_unrelated_sessions(self):
        """The session/group expansion only follows marked processes: an unrelated process with no marker,
        in a session of its own, is left alone."""
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", self.tag + "-bystander"],
                                     start_new_session=True)
        self.addCleanup(bystander.wait)
        self.addCleanup(bystander.kill)
        detectors._sweep("0" * 32)
        time.sleep(0.2)
        self.assertIsNone(bystander.poll())


if __name__ == "__main__":
    unittest.main()
