"""Review fix w2-memory-heal-orch L2: patches of files holding a form feed (or another
character ``str.splitlines`` treats as a line break) are exact and ``git apply`` cleanly.

Before the fix ``_diff`` and ``apply_patch`` split with ``str.splitlines``, so a form feed
(PEP 8 page break) split one diff line in two, the emitted patch was wrong and
``apply_patch`` raised "Malformed hunk line". The line-indexed candidate generators
(dead-code removal, handler insertion) indexed ``ast`` line numbers into the same split
and edited the wrong lines. Synthetic text in temporary directories only.
"""

import ast
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from engineering_os import healing
from engineering_os.healing import _diff, _insert_handler, _lines, _source_lines, apply_patch, heal

CASES = {
    "form feed page break": ("import os\n\x0c\ndef f():\n    return 1\n", "import os\n\x0c\ndef f():\n    return 0\n"),
    "form feed inside the changed line": ("a = 1\nb = '\x0c'\nc = 3\n", "a = 1\nb = '\x0c!'\nc = 3\n"),
    "crlf": ("a\r\nb\r\nc\r\n", "a\r\nB\r\nc\r\n"),
    "no final newline": ("a\nb", "a\nc"),
    "final newline removed": ("a\nb\n", "a\nb"),
    "empty to text": ("", "x\n"),
    "text to empty": ("x\n", ""),
    "other splitlines breaks": ("p = '\x1c\x1d\x1e'\nq = '\x85  '\nr = 1\n", "p = '\x1c\x1d\x1e'\nq = '\x85  '\nr = 2\n"),
    "crlf, form feed and no final newline": ("x = 1\r\n\x0c\r\ny = 2", "x = 1\r\n\x0c\r\ny = 3"),
}


class DiffRoundTripTests(unittest.TestCase):
    def test_lines_split_at_lf_only_and_rejoin_exactly(self):
        for name, (before, after) in CASES.items():
            for text in (before, after):
                with self.subTest(name=name, text=text):
                    parts = _lines(text)
                    self.assertEqual("".join(parts), text)
                    self.assertTrue(all(part.endswith("\n") for part in parts[:-1]))
                    self.assertEqual(sum(part.count("\n") for part in parts), text.count("\n"))

    def test_patch_and_reverse_apply_exactly(self):
        for name, (before, after) in CASES.items():
            with self.subTest(name=name):
                patch, reverse = _diff("m.py", before.encode(), after.encode()), _diff("m.py", after.encode(), before.encode())
                self.assertEqual(apply_patch({"m.py": before}, patch), {"m.py": after})
                self.assertEqual(apply_patch({"m.py": after}, reverse), {"m.py": before})
                for line in _lines(patch):
                    self.assertTrue(line.endswith("\n"), repr(line))
                    self.assertIn(line[:1], " +-@\\", repr(line))

    def test_form_feed_patch_has_one_hunk_line_per_source_line(self):
        before, after = CASES["form feed page break"]
        patch = _diff("m.py", before.encode(), after.encode())
        self.assertEqual(patch, "--- a/m.py\n+++ b/m.py\n@@ -1,4 +1,4 @@\n import os\n \x0c\n def f():\n-    return 1\n+    return 0\n")
        self.assertNotIn("No newline at end of file", patch)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_git_apply_accepts_every_patch(self):
        for name, (before, after) in CASES.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="gaie-l2-") as scratch:
                root = pathlib.Path(scratch)
                (root / "m.py").write_bytes(before.encode())
                (root / "fix.diff").write_bytes(_diff("m.py", before.encode(), after.encode()).encode())
                done = subprocess.run(["git", "apply", "--whitespace=nowarn", "fix.diff"], cwd=root, capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual((root / "m.py").read_bytes(), after.encode())

    def test_a_mismatching_patch_is_still_refused(self):
        before, after = CASES["form feed page break"]
        patch = _diff("m.py", before.encode(), after.encode())
        with self.assertRaises(healing.HealingError):
            apply_patch({"m.py": before.replace("\x0c", "")}, patch)


class SourceLineTests(unittest.TestCase):
    def test_source_lines_follow_ast_line_numbers(self):
        source = "a = 1\r\nb = 2\rc = 3\x0c\n\x0c\nd = 4  # \x85 \u2028\ne = 5"
        lines = _source_lines(source)
        self.assertEqual("".join(lines), source)
        for node in ast.parse(source).body:
            self.assertTrue(lines[node.lineno - 1].startswith(node.targets[0].id + " = "), (node.lineno, lines))

    def test_handler_insertion_after_a_form_feed_lands_after_the_function(self):
        source = 'import json\n\x0c\ndef health(conn, query):\n    return 200, "application/json", {"ok": True}\n\n\nROUTES = {}\n'
        code = 'def count_items(conn, query):\n    return 200, "application/json", {"count": 0}\n'
        result = _insert_handler(source, code, {"health"})
        tree = ast.parse(result)
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef)], ["health", "count_items"])
        self.assertTrue(result.startswith(source.split("\n\n\nROUTES")[0] + "\n\n\ndef count_items"))
        self.assertTrue(result.endswith("ROUTES = {}\n"))


class HealFormFeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-l2h-")
        self.base = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def target(self, files):
        root = self.base / "app"
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(text.encode())
        return root

    def test_mutation_repair_of_a_form_feed_file_yields_an_exact_patch(self):
        original = "import os\n\x0c\ndef is_adult(age):\n    return age > 18\n"
        root = self.target({"rules.py": original, "suite/case_rules.py":
                            "import unittest\nfrom rules import is_adult\n\n\nclass T(unittest.TestCase):\n"
                            "    def test_eighteen(self):\n        self.assertTrue(is_adult(18))\n"})
        result = heal(root, workdir=self.base / "work", tests={"start": "suite", "pattern": "case_*.py"}, now=1_800_000_000)
        validation = result["validation"]
        self.assertTrue(validation["checks"]["patch_and_reverse_apply"])  # was False: "Malformed hunk line"
        patch = result["patch"] or result["rejected_patch"]
        repaired = (pathlib.Path(result["isolated_copy"]) / "rules.py").read_text()
        self.assertEqual(repaired, original.replace("age > 18", "age >= 18"))
        self.assertEqual(apply_patch({"rules.py": original}, patch), {"rules.py": repaired})
        self.assertEqual(validation["targeted_still_failing"], [])
        # verify_repair's content policy refuses control characters other than \n, \r and \t; a
        # form feed is one, so the artifact check (not the patch) still stops this run from passing.
        if not validation["passed"]:
            self.assertEqual(result["status"], "validation-failed")
            self.assertEqual([name for name, ok in validation["checks"].items() if not ok], ["artifact_verified"])
            self.assertIn("control content", validation["artifact"]["reason"])

    def test_dead_code_removal_after_a_form_feed_removes_exactly_the_function(self):
        original = 'def used(value):\n    return value * 2\n\n\n\x0c\ndef orphan_formatter(value):\n    return "#" + str(value)\n\n\nLIMIT = 3\n'
        root = self.target({"helpers.py": original, "suite/case_helpers.py":
                            "import unittest\nfrom helpers import LIMIT, used\n\n\nclass T(unittest.TestCase):\n"
                            "    def test_used(self):\n        self.assertEqual(used(LIMIT), 6)\n"})
        result = heal(root, workdir=self.base / "work", tests={"start": "suite", "pattern": "case_*.py"}, now=1_800_000_000,
                      policy={"allow_dead_code_removal": True})
        kept = [row for row in result["trials"] if row["repair"] == "kept"]
        self.assertEqual([row["strategy"] for row in kept], ["remove-dead-code"])  # was rejected: syntax-error
        repaired = (pathlib.Path(result["isolated_copy"]) / "helpers.py").read_text()
        self.assertEqual(repaired, 'def used(value):\n    return value * 2\n\n\n\x0c\nLIMIT = 3\n')
        self.assertTrue(result["validation"]["checks"]["patch_and_reverse_apply"])


if __name__ == "__main__":
    unittest.main()
