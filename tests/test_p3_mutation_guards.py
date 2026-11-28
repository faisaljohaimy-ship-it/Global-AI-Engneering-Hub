"""Tests of the second phase's gate (`guard.py`) and worker command (`kit.py`) that notice quiet breakage.

They were written after `swarm/phase3/mutate.py` changed the two files one small step at a time
(seed 1, limit 20, run against `tests.test_swarm_phase2`) and listed the changes nobody noticed.

Figures (mutants tried, noticed by the second phase's tests alone, noticed with this file added):
    guard.py: 17 tried, 17 noticed before, 17 noticed with these tests (the file has only 17 places to change)
    kit.py:   20 tried, 10 noticed before, 18 noticed with these tests
    together: 37 tried, 27 noticed before, 35 noticed with these tests

Survivors left, because no user can see the difference:
    kit.py `max(int(first or 1), 1)` written as `or 0`: the outer `max(..., 1)` gives the same line.
    kit.py `headroom()` with `and` turned into `or`: it only matters on a machine with Headroom half installed,
    which a test cannot make without installing it.
Rerun the "before" figures with `python3 swarm/phase3/mutate.py run swarm/phase2/kit.py tests.test_swarm_phase2`
(and guard.py), the "with" figures with the module argument "tests.test_swarm_phase2 tests.test_p3_mutation_guards".
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
sys.path.insert(0, str(ROOT / "swarm" / "phase2"))
sys.path.insert(0, str(ROOT / "swarm"))
import guard  # noqa: E402
import mutate  # noqa: E402
import kit  # noqa: E402
import tasks  # noqa: E402
from tests import test_swarm_phase2 as base  # noqa: E402


SAMPLE = """
def f(a, b):
    if a < b and not b == 3:
        return True
    return a >= 7 or b != 2
"""


class Mutants(unittest.TestCase):
    def test_the_same_inputs_give_the_same_mutants_and_another_seed_another_order(self):
        first = mutate.mutants(SAMPLE, 6, 5)
        self.assertEqual(first, mutate.mutants(SAMPLE, 6, 5))
        self.assertNotEqual(first, mutate.mutants(SAMPLE, 6, 6))

    def test_every_mutant_parses_differs_from_the_source_and_from_the_others(self):
        import ast
        found = mutate.mutants(SAMPLE, 50, 1)
        self.assertGreaterEqual(len(found), 8)
        for text in found:
            ast.parse(text)
        self.assertEqual(len(set(found)), len(found))
        self.assertNotIn(ast.unparse(ast.parse(SAMPLE)), found)

    def test_the_limit_holds_and_a_source_with_nothing_to_change_gives_none(self):
        self.assertEqual(len(mutate.mutants(SAMPLE, 3, 1)), 3)
        self.assertEqual(mutate.mutants(SAMPLE, 0, 1), [])
        self.assertEqual(mutate.mutants("x = 'a'\n", 5, 1), [])

    def test_the_real_gate_and_command_give_mutants_that_all_parse(self):
        import ast
        for name in ("guard", "kit"):
            for text in mutate.mutants((ROOT / "swarm" / "phase2" / f"{name}.py").read_text(), 20, 1):
                ast.parse(text)


class GateCoversTheCommand(unittest.TestCase):
    def test_every_verb_of_the_command_has_a_shape_the_gate_lets_through(self):
        for verb in kit.VERBS:
            if verb in ("submit", "setline", "answer"):
                self.assertTrue(guard.allowed(f"swk {verb} L-0001 <<'EOF'\nx\nEOF"), verb)
                self.assertFalse(guard.allowed(f"swk {verb} L-0001"), verb)
            else:
                self.assertTrue(guard.allowed(f"swk {verb} L-0001"), verb)

    def test_the_gate_refuses_a_verb_the_command_does_not_have(self):
        for command in ("swk run L-0001", "swk rm L-0001", "swk SHOW L-0001", "swk"):
            self.assertFalse(guard.allowed(command), command)


class CommandEdges(base.Stage):
    def setUp(self):
        super().setUp()
        self.item = tasks.make(self.out, "large", 1, 1, mode="lean")[0]
        self.ident = self.item["id"]
        self.folder = self.out / self.ident

    def test_every_verb_refuses_one_argument_too_few_and_one_too_many(self):
        arities = {"show": (1, 1), "submit": (1, 1), "test": (1, 1), "read": (2, 3), "grep": (2, 3), "def": (2, 2), "callers": (2, 2),
                   "select": (4, 4), "setline": (3, 3), "answer": (1, 1)}  # written out: reading them from kit would test kit against itself
        self.assertEqual(sorted(arities), sorted(kit.VERBS))
        for verb, (least, most) in arities.items():
            few = self.swk(verb, *["L-0001"] * (least - 1)) if least > 1 else self.swk(verb)
            many = self.swk(verb, *["L-0001"] * (most + 1))
            for done in (few, many):
                self.assertEqual(done.returncode, 2, verb)
                self.assertIn("takes", done.stdout, verb)

    def test_a_path_that_leads_out_of_the_task_folder_is_refused_even_when_it_exists(self):
        outside = self.home / "secret.py"
        outside.write_text("SECRET = 1\n")
        (self.folder / "inv" / "link.py").symlink_to(outside)
        done = self.swk("read", self.ident, "inv/link.py")
        self.assertEqual(done.returncode, 2)
        self.assertNotIn("SECRET", done.stdout)
        self.assertEqual(self.swk("read", self.ident, "inv/nothing.py").returncode, 2)

    def test_read_cuts_at_the_cap_and_says_how_much_is_left(self):
        body = "x" * 70000
        (self.folder / "inv" / "big.py").write_text(body + "\n")
        shown = self.swk("read", self.ident, "inv/big.py").stdout
        self.assertEqual(shown.split("\n[")[0], ("1: " + body)[: kit.LEAN_CAP])
        self.assertIn(f"[{3 + len(body) - 4000} more characters not shown", shown)
        item = tasks.make(self.out, "large", 2, 1, mode="raw")[0]
        (self.out / item["id"] / "inv" / "big.py").write_text(body + "\n")
        shown = self.swk("read", item["id"], "inv/big.py").stdout
        self.assertEqual(shown.split("\n[")[0], ("1: " + body)[:60000])
        self.assertIn(f"[{3 + len(body) - 60000} more characters not shown", shown)

    def test_a_failing_run_is_summed_up_within_twice_the_lean_cap(self):
        many = "\n".join(f"    def test_a{n:04d}(self):\n        self.fail('no')" for n in range(400))
        (self.folder / "tests" / "test_many.py").write_text(f"import unittest\n\nclass Many(unittest.TestCase):\n{many}\n")
        shown = self.swk("test", self.ident).stdout
        self.assertGreater(len(shown), 4500)
        self.assertLessEqual(len(shown), 8000 + 200)
        self.assertIn("more characters not shown", shown)

    def test_setline_takes_a_line_of_400_characters_and_not_401_and_the_first_line_and_not_the_one_after_the_last(self):
        path = f"inv/m{self.item['truth']['fixed_function'].split('.')[0][1:]}.py"
        count = len((self.folder / path).read_text().splitlines())
        line = "x = 1  # "
        self.assertEqual(self.swk("setline", self.ident, path, "1", text=line + "a" * (400 - len(line))).returncode, 0)
        self.assertEqual((self.folder / path).read_text().splitlines()[0], line + "a" * (400 - len(line)))
        self.assertEqual(self.swk("setline", self.ident, path, "1", text=line + "a" * (401 - len(line))).returncode, 2)
        self.assertEqual(self.swk("setline", self.ident, path, "0", text="x = 1").returncode, 2)
        self.assertEqual(self.swk("setline", self.ident, path, str(count + 1), text="x = 1").returncode, 2)
        self.assertEqual(self.swk("setline", self.ident, path, str(count), text="x = 1").returncode, 0)

    def test_grep_without_a_file_reads_files_only_and_a_folder_name_keeps_it_to_that_folder(self):
        (self.folder / "inv" / "sub").mkdir()
        (self.folder / "data" / "extra.txt").write_text("NEEDLE here\n")
        (self.folder / "inv" / "extra.txt").write_text("NEEDLE there\n")
        everywhere = self.swk("grep", self.ident, "NEEDLE")
        self.assertEqual(everywhere.returncode, 0)
        self.assertEqual(sorted(line.split(":")[0] for line in everywhere.stdout.splitlines()), ["data/extra.txt", "inv/extra.txt"])
        only = self.swk("grep", self.ident, "NEEDLE", "inv")
        self.assertEqual([line.split(":")[0] for line in only.stdout.splitlines()], ["inv/extra.txt"])


if __name__ == "__main__":
    unittest.main()
