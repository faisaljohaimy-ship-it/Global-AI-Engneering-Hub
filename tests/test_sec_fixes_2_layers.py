"""recheck-security item 1 (SEC-12 partial): layers.PROCESS_ONLY_TESTS is keyed by path AND the SHA-256 of
the reviewed bytes (and of every fixture tree the test executes).

A listed test whose bytes or fixture differ runs in the strict profile like any other test; a matching one
runs from the very bytes that were hashed, under `python -I`, with tests/ off sys.path, so a module or
bytecode planted beside it is never executed. Real boundary or measured refusal: on a host without the
governor's full tier the strict profile falls back to the recorded process-only mode, and these tests
assert that record instead of the walls. Planted values are random per run.
"""
import hashlib
import importlib.util
import os
import pathlib
import py_compile
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import governor, layers  # noqa: E402

FULL = governor.isolation_probe()["tier"] == "full"
REQUIRED = os.environ.get("GAIE_REQUIRE_FULL_SANDBOX") == "1"
REASON = "fixture exception: builds a sandbox of its own (test only)"

HOSTILE = '''
import os, unittest
MARKER, ESCAPE, ENV = {marker!r}, {escape!r}, {env!r}
class Hostile(unittest.TestCase):
    def test_reach(self):
        seen = ["ran"]
        if os.environ.get(ENV):
            seen.append("parent-environment")
        try:
            seen.append("read-outside:" + open(MARKER).read())
        except OSError:
            pass
        try:
            with open(ESCAPE, "w") as handle:
                handle.write("escaped")
            seen.append("write-outside")
        except OSError:
            pass
        print(" ".join(seen))
        self.assertEqual(seen, ["ran"])
'''
# A reviewed test that imports a standard module nothing else loads first (colorsys).
REVIEWED = '''
import colorsys, os, unittest
class Reviewed(unittest.TestCase):
    def test_standard_module_and_own_bytes(self):
        self.assertNotIn(os.sep + "tests" + os.sep, colorsys.__file__)
        self.assertEqual(colorsys.rgb_to_hsv(0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
'''
PLANTED = '''
with open({escape!r}, "w") as handle:
    handle.write("escaped " + __name__)
import os
os._exit(0)
'''


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="gaie-sf2-", dir="/tmp" if os.path.isdir("/tmp") else None)).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        (self.root / "tests").mkdir(parents=True)
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        self.marker, self.escape = self.outside / "marker.txt", self.outside / "escaped.txt"
        self.marker.write_text("host-only-" + os.urandom(6).hex())
        self.env = "GAIE_SF2_PLANTED"
        self.scratch = self.tmp / "scratch"
        self.scratch.mkdir(mode=0o700)

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
        return path

    def entry(self, text, executes=None, reason=REASON):
        return {"sha256": digest(textwrap.dedent(text).lstrip()), "executes": executes or {}, "reason": reason}

    def run_test(self, test, entries):
        with mock.patch.dict(layers.PROCESS_ONLY_TESTS, entries, clear=True), \
                mock.patch.dict(os.environ, {self.env: "planted-" + os.urandom(6).hex()}):
            row, _ = layers._run_python_test(self.root, test, self.scratch, 300)
        return row

    def hostile(self):
        return HOSTILE.format(marker=str(self.marker), escape=str(self.escape), env=self.env)

    def assert_contained_or_recorded(self, row):
        """Strict on the full tier (the walls hold); the recorded process-only fallback elsewhere."""
        isolation = row["isolation"]
        if not FULL:
            self.assertFalse(REQUIRED, "GAIE_REQUIRE_FULL_SANDBOX=1 but the full tier is missing")
            self.assertEqual((isolation["profile"], isolation["sandboxed"]), ("process-only", False))
            self.assertIn("unavailable on this host", isolation["reason"])
            return
        self.assertEqual((isolation["profile"], isolation["sandboxed"], isolation["tier"]), ("strict", True, "full"))
        self.assertFalse(self.escape.exists())
        self.assertNotIn("read-outside", row["output_tail"])
        self.assertNotIn("parent-environment", row["output_tail"])
        self.assertEqual(row["status"], "passed", row["output_tail"])


class EditedExceptionTests(Case):
    def test_an_edited_exception_file_runs_strict_and_says_why(self):
        """The reviewer's case: a hostile edit of a listed file no longer runs outside the sandbox."""
        reviewed = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
        self.write("tests/test_listed.py", self.hostile())
        row = self.run_test("tests/test_listed.py", {"tests/test_listed.py": self.entry(reviewed)})
        exception = row["isolation"]["exception"]
        self.assertEqual((exception["matched"], exception["changed"]), (False, ["tests/test_listed.py"]))
        self.assertEqual(exception["reviewed_sha256"], digest(reviewed))
        self.assertEqual(exception["sha256"], digest(textwrap.dedent(self.hostile()).lstrip()))
        if FULL:
            self.assertIn("differs from its review: runs strict", row["isolation"]["reason"])
        self.assert_contained_or_recorded(row)

    def test_a_changed_fixture_tree_runs_strict(self):
        """test_self_healing_loop and test_upgrade_engine rerun a fixture's suite in a plain subprocess: a fixture
        edit must count as an edit of the exception."""
        text = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
        self.write("tests/test_listed.py", text)
        self.write("tests/fixtures/app/suite/case_a.py", "x = 1\n")
        tree = layers._tree_digest(self.root, "tests/fixtures/app")
        entries = {"tests/test_listed.py": self.entry(text, {"tests/fixtures/app": tree})}
        self.assertEqual(self.run_test("tests/test_listed.py", entries)["isolation"]["profile"], "process-only")
        self.write("tests/fixtures/app/suite/case_planted.py", "import os\n")
        row = self.run_test("tests/test_listed.py", entries)
        self.assertEqual(row["isolation"]["exception"]["changed"], ["tests/fixtures/app"])
        self.assertEqual(row["isolation"]["profile"], "strict" if FULL else "process-only")
        self.assertEqual(row["status"], "passed")

    def test_malformed_or_path_only_entries_never_match(self):
        text = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
        self.write("tests/test_listed.py", text)
        good = self.entry(text)
        for label, value in (("path only (the old shape)", "fixture exception"), ("no digest", {**good, "sha256": None}),
                             ("upper-case digest", {**good, "sha256": good["sha256"].upper()}),
                             ("no reason", {**good, "reason": " "}), ("executes not a mapping", {**good, "executes": []}),
                             ("unverifiable fixture", {**good, "executes": {"tests/fixtures/missing": "0" * 64}})):
            with self.subTest(label):
                with mock.patch.dict(layers.PROCESS_ONLY_TESTS, {"tests/test_listed.py": value}, clear=True):
                    profile, _, exception = layers._profile(self.root, "tests/test_listed.py")
                self.assertEqual((profile, exception["matched"]), ("strict", False))
        with mock.patch.dict(layers.PROCESS_ONLY_TESTS, {"tests/test_listed.py": good}, clear=True):
            self.assertEqual(layers._profile(self.root, "tests/test_listed.py")[0], "process-only")
            self.assertEqual(layers._profile(self.root, "tests/test_other.py"), ("strict", None, None))


class ReviewedExceptionTests(Case):
    def test_planted_module_and_bytecode_next_to_a_reviewed_file_are_not_executed(self):
        """An unchanged listed file: a module in tests/ that shadows a standard one it imports, and a hostile
        __pycache__ entry carrying the source's mtime and size, both used to run outside the sandbox."""
        test = self.write("tests/test_reviewed.py", REVIEWED)
        self.write("tests/colorsys.py", PLANTED.format(escape=str(self.escape)))
        evil = self.tmp / "evil.py"
        evil.write_text(PLANTED.format(escape=str(self.escape)), encoding="utf-8")
        cache = pathlib.Path(importlib.util.cache_from_source(str(test)))
        cache.parent.mkdir(exist_ok=True)
        py_compile.compile(str(evil), cfile=str(cache), dfile=str(test), doraise=True)
        header = bytearray(cache.read_bytes())  # magic, flags, source mtime, source size: valid for the source
        info = test.stat()
        header[8:12] = int(info.st_mtime).to_bytes(4, "little")
        header[12:16] = (info.st_size & 0xFFFFFFFF).to_bytes(4, "little")
        cache.write_bytes(bytes(header))
        row = self.run_test("tests/test_reviewed.py", {"tests/test_reviewed.py": self.entry(REVIEWED)})
        self.assertFalse(self.escape.exists(), self.escape.read_text() if self.escape.exists() else "")
        self.assertEqual((row["status"], row["isolation"]["profile"], row["isolation"]["exception"]["matched"]),
                         ("passed", "process-only", True), row["output_tail"])
        self.assertEqual(row["isolation"]["reason"], REASON)

    def test_the_premise_the_plain_runner_imports_the_planted_module(self):
        """Without the pinned runner (an unlisted test outside the sandbox) the planted module is what runs."""
        self.write("tests/test_reviewed.py", REVIEWED)
        self.write("tests/colorsys.py", PLANTED.format(escape=str(self.escape)))
        with mock.patch.object(governor, "isolation_probe", return_value={"tier": "plain"}):
            row = self.run_test("tests/test_reviewed.py", {})
        self.assertEqual(row["isolation"]["profile"], "process-only")
        self.assertEqual(self.escape.read_text(), "escaped colorsys")

    def test_a_fixture_swapped_during_the_run_is_an_error_never_a_pass(self):
        swap = f'''
            import pathlib, unittest
            class Swap(unittest.TestCase):
                def test_swap(self):
                    pathlib.Path({str(self.root / "tests/fixtures/app/x.py")!r}).write_text("y = 2\\n")
            '''
        self.write("tests/test_swap.py", swap)
        self.write("tests/fixtures/app/x.py", "x = 1\n")
        entries = {"tests/test_swap.py": self.entry(swap, {"tests/fixtures/app": layers._tree_digest(self.root, "tests/fixtures/app")})}
        row = self.run_test("tests/test_swap.py", entries)
        self.assertEqual(row["status"], "error")
        self.assertIn("changed during the run: tests/fixtures/app", row["reason"])
        self.assertEqual(row["isolation"]["exception"]["changed_during_run"], ["tests/fixtures/app"])


class TreeDigestTests(Case):
    def test_tree_digest_counts_every_file_and_refuses_links_and_special_files(self):
        self.write("tests/fixtures/app/a.py", "a = 1\n")
        first = layers._tree_digest(self.root, "tests/fixtures/app")
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.write("tests/fixtures/app/__pycache__/a.cpython-313.pyc", "planted")
        self.assertNotEqual(layers._tree_digest(self.root, "tests/fixtures/app"), first)
        shutil.rmtree(self.root / "tests/fixtures/app/__pycache__")
        self.assertEqual(layers._tree_digest(self.root, "tests/fixtures/app"), first)
        (self.root / "tests/fixtures/app/link.py").symlink_to(self.marker)
        self.assertIsNone(layers._tree_digest(self.root, "tests/fixtures/app"))
        (self.root / "tests/fixtures/app/link.py").unlink()
        os.mkfifo(self.root / "tests/fixtures/app/pipe")
        self.assertIsNone(layers._tree_digest(self.root, "tests/fixtures/app"))
        (self.root / "tests/fixtures/app/pipe").unlink()
        (self.root / "tests/fixtures/linked").symlink_to(self.root / "tests/fixtures/app")
        for bad in ("tests/fixtures/linked", "tests/fixtures/missing", "../outside", "/etc"):
            self.assertIsNone(layers._tree_digest(self.root, bad), bad)

    def test_exception_digests_report_what_the_list_would_need(self):
        text = "import unittest\n"
        self.write("tests/test_listed.py", text)
        self.write("tests/fixtures/app/a.py", "a = 1\n")
        with mock.patch.dict(layers.PROCESS_ONLY_TESTS, {"tests/test_listed.py": self.entry(
                text, {"tests/fixtures/app": "0" * 64})}, clear=True):
            self.assertEqual(layers.exception_digests(self.root), {"tests/test_listed.py": {
                "sha256": digest(text), "executes": {"tests/fixtures/app": layers._tree_digest(self.root, "tests/fixtures/app")}}})


class ShippedListTests(unittest.TestCase):
    def test_every_shipped_exception_is_pinned_to_the_reviewed_bytes_of_this_checkout(self):
        """A listed file or fixture edited without a new review runs strict: name it here so the reviewer re-pins
        deliberately (exception_digests) instead of finding out from a failing layer."""
        current = layers.exception_digests(ROOT)
        stale = {test: current[test] for test, entry in layers.PROCESS_ONLY_TESTS.items()
                 if not layers._exception(ROOT, test)["matched"]}
        self.assertEqual(stale, {}, "review these files, then set their PROCESS_ONLY_TESTS digests to the values shown")
        for test, entry in layers.PROCESS_ONLY_TESTS.items():
            self.assertEqual(set(entry), {"sha256", "reason", "executes"}, test)
            self.assertGreater(len(entry["reason"]), 40, test)


class ProcessOnlyOutputTests(unittest.TestCase):
    """sec-fixes-2 request 4: the process-only branch of layers._run reads back only the output's tail."""

    def run_code(self, code):
        from engineering_os import governor, layers
        with tempfile.TemporaryDirectory(prefix="gaie-sf2o-", dir="/tmp") as scratch:
            work = layers._workspace(pathlib.Path(scratch), "out")
            return layers._run([layers._python(), "-c", code], root=layers.ROOT, timeout=60, workspace=work,
                               profile="process-only", reason="output bound test"), governor.OUTPUT_TAIL_BYTES

    def test_a_flood_of_output_is_cut_to_the_governor_tail_and_says_so(self):
        (code, output, _, timed_out, isolation), limit = self.run_code(
            "import sys\nfor _ in range(48): sys.stdout.write('x' * 65536)\nprint('END')")
        self.assertEqual((code, timed_out, isolation["profile"]), (0, False, "process-only"))
        self.assertTrue(output.startswith("[governor: the first "), output[:80])
        self.assertTrue(output.rstrip().endswith("END"))
        self.assertLess(len(output), limit + 200)

    def test_ordinary_output_and_the_return_code_are_kept_whole(self):
        (code, output, _, timed_out, _), _ = self.run_code("print('ran'); raise SystemExit(3)")
        self.assertEqual((code, output, timed_out), (3, "ran\n", False))


if __name__ == "__main__":
    unittest.main()
