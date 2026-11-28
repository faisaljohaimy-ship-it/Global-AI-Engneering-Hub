"""The cage at hand-in: hostile samples are contained, and honest work still passes.
No agent and no model is started. Walls that need root are skipped, with the reason, when the test is not root."""
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
P2, P3 = ROOT / "swarm" / "phase2", ROOT / "swarm" / "phase3"
sys.path[:0] = [str(P3), str(P2), str(ROOT / "swarm")]
import handin  # noqa: E402
import tasks  # noqa: E402
import workload  # noqa: E402

IS_ROOT = os.geteuid() == 0


class WallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.walls = handin.walls()

    def check(self, name):
        what = self.walls[name]
        if what == handin.NOT_ENFORCED:
            self.skipTest(f"{name}: not enforced here" + ("" if IS_ROOT else " (needs root or a network namespace)"))
        self.assertEqual(what, "contained")

    def test_private_folder(self): self.check("private_folder")
    def test_hidden_tests(self): self.check("hidden_tests")
    def test_environment(self): self.check("environment")
    def test_write_original(self): self.check("write_original")
    def test_write_swarm_home(self): self.check("write_swarm_home")
    def test_socket(self): self.check("socket")
    def test_processes(self): self.check("processes")
    def test_memory(self): self.check("memory")
    def test_time_limit(self): self.check("time_limit")
    def test_process_left(self): self.check("process_left")

    def test_selftest_never_hides_a_wall_that_is_not_enforced(self):
        lines = handin.selftest()
        for name, what in self.walls.items():
            if what != "contained":
                self.assertTrue(any(line.startswith(name) for line in lines), name)
        if IS_ROOT:
            self.assertFalse([l for l in lines if "escaped" in l], lines)

    def test_the_old_runner_does_leak_the_hidden_tests(self):
        # a control: without the cage, the same sample reads the withheld file
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            (t / ".hidden").mkdir()
            (t / ".hidden" / "a.json").write_text("SECRET")
            (t / "a").mkdir()
            (t / "a" / "s.py").write_text("print(open('../.hidden/a.json').read())")
            old = workload.isolated([sys.executable, "-I", "s.py"], t / "a")
            new = handin.isolated([sys.executable, "-I", "s.py"], t / "a")
        self.assertIn("SECRET", old.stdout)
        self.assertNotIn("SECRET", new.stdout)


class ProtectTests(unittest.TestCase):
    def test_owner_only(self):
        with tempfile.TemporaryDirectory() as t:
            stage = pathlib.Path(t) / "s"
            for d in (".hidden", ".kit", ".queue"):
                (stage / d).mkdir(parents=True)
                (stage / d / "f").write_text("x")
            handin.protect(stage)
            for p in (stage, stage / ".hidden", stage / ".kit" / "f", stage / ".queue"):
                self.assertEqual(p.stat().st_mode & 0o077, 0, p)


class StillWorksTests(unittest.TestCase):
    def setUp(self):
        self.previous = handin.install()
        self.addCleanup(setattr, workload, "isolated", self.previous)

    def test_install_returns_the_previous(self):
        self.assertIs(workload.isolated, handin.isolated)
        self.assertIsNot(self.previous, handin.isolated)

    def test_reference_solution_passes(self):
        task = tasks.medium(1, 7)
        with tempfile.TemporaryDirectory() as t:
            sol = pathlib.Path(t) / "solution.py"
            sol.write_text(task["reference"])
            result = tasks.run_suite(sol, task["suite"])
        self.assertEqual(result["passed"], result["total"], result)

    def test_a_folder_with_its_own_tests_runs_with_cwd(self):
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            (t / "tests").mkdir()
            (t / "mod.py").write_text("def f():\n    return 3\n")
            (t / "tests" / "test_a.py").write_text(
                "import sys, unittest\nsys.path.insert(0, '.')\nimport mod\n"
                "class T(unittest.TestCase):\n    def test_f(self):\n        self.assertEqual(mod.f(), 3)\n")
            done = workload.isolated([sys.executable, "-B", "-s", "-E", "-m", "unittest", "discover", "-s", "tests"], t, 60)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertFalse((t / "tests" / "__pycache__").exists())

    def test_timeout_raises_as_the_original(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            handin.isolated([sys.executable, "-I", "-c", "import time; time.sleep(30)"], timeout=1)

    def test_workspace_is_always_removed(self):
        before = set(pathlib.Path(tempfile.gettempdir()).glob("handin-*"))
        handin.isolated([sys.executable, "-I", "-c", "print(1)"])
        try:
            handin.isolated([sys.executable, "-I", "-c", "import time; time.sleep(30)"], timeout=1)
        except subprocess.TimeoutExpired:
            pass
        self.assertEqual(set(pathlib.Path(tempfile.gettempdir()).glob("handin-*")) - before, set())

    def test_twenty_hand_ins_in_a_row(self):
        task = tasks.medium(1, 7)
        with tempfile.TemporaryDirectory() as t:
            sol = pathlib.Path(t) / "solution.py"
            sol.write_text(task["reference"])
            start = time.time()
            for _ in range(20):
                result = tasks.run_suite(sol, task["suite"])
                self.assertEqual(result["passed"], result["total"])
            print(f"\n20 hand-ins in a row: {time.time() - start:.1f} s (measured here, as root={IS_ROOT})")


if __name__ == "__main__":
    unittest.main()
