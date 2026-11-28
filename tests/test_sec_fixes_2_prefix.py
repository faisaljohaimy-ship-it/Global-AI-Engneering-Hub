"""recheck-isolation-2 item 4: layers._run passes no whole install prefix as a read path.

Before: the strict layer sandbox got sys.prefix, sys.base_prefix and each TOOLS program's install prefix
(the parent of its bin directory) read-only, so a tool under ~/.local showed ~/.local (share/, keys) to
every layer test, the class of the governor's strict-mount release blocker. Now the governor mounts the
hub's interpreter itself, a tool contributes only its bin directory, and only from a place outside every
home directory that no non-root user can change. Real boundary or measured refusal: the sandboxed checks
need the governor's full tier; elsewhere the recorded process-only fallback is asserted instead.
"""
import os
import pathlib
import shutil
import stat
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
FULL_PROBE = {"tier": "full"}


class Captured(Exception):
    pass


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="gaie-sf2p-", dir="/tmp" if os.path.isdir("/tmp") else None)).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        (self.root / "tests").mkdir(parents=True)
        self.scratch = self.tmp / "scratch"
        self.scratch.mkdir(mode=0o700)

    def tool(self, prefix, name="gaietool"):
        """A stand-in tool install: <prefix>/bin/<name> and a secret under <prefix>/share."""
        (prefix / "bin").mkdir(parents=True)
        (prefix / "share" / "keyrings").mkdir(parents=True)
        program = prefix / "bin" / name
        program.write_text("#!/bin/sh\necho tool-ran\n", encoding="utf-8")
        program.chmod(0o755)
        secret = prefix / "share" / "keyrings" / "secret.txt"
        secret.write_text("planted-" + os.urandom(8).hex(), encoding="utf-8")
        return program, secret

    def read_paths(self, **patches):
        """The read_paths layers._run hands to governor.sandbox_run for one strict run."""
        seen = {}

        def capture(command, **kwargs):
            seen.update(kwargs)
            raise Captured()
        with mock.patch.object(governor, "isolation_probe", return_value=FULL_PROBE), \
                mock.patch.object(governor, "sandbox_run", capture), self.assertRaises(Captured):
            layers._run(["true"], root=self.root, timeout=5, workspace=layers._workspace(self.scratch, "t"), **patches)
        return seen["read_paths"]


class ReadPathTests(Case):
    def test_a_tool_under_the_home_directory_exposes_nothing_of_it(self):
        home = self.tmp / "home"
        program, _ = self.tool(home / ".local")
        with mock.patch.dict(os.environ, {"HOME": str(home), "PATH": f"{program.parent}:{os.environ.get('PATH', '')}"}), \
                mock.patch.object(layers, "TOOLS", (program.name,)):
            self.assertEqual(shutil.which(program.name), str(program))
            paths = self.read_paths()
        self.assertFalse([path for path in paths if path == str(home) or path.startswith(str(home) + os.sep)], paths)

    def test_a_trusted_tool_contributes_its_bin_directory_never_its_prefix(self):
        program, _ = self.tool(self.tmp / "opt" / "tool")
        with mock.patch.dict(os.environ, {"PATH": f"{program.parent}:{os.environ.get('PATH', '')}"}), \
                mock.patch.object(layers, "TOOLS", (program.name,)), mock.patch.object(layers, "_trusted_dir", return_value=True, create=True):
            paths = self.read_paths()
        self.assertIn(str(program.parent), paths)
        self.assertNotIn(str(self.tmp / "opt" / "tool"), paths)
        self.assertFalse([path for path in paths if path.endswith(os.sep + "share")], paths)

    def test_the_interpreter_prefixes_are_left_to_the_governor(self):
        fake = self.tmp / "opt" / "python"
        (fake / "share").mkdir(parents=True)
        with mock.patch.object(sys, "base_prefix", str(fake)), mock.patch.object(sys, "prefix", str(fake)):
            paths = self.read_paths()
        self.assertNotIn(str(fake), paths)
        venv = self.tmp / "venv"
        venv.mkdir()
        with mock.patch.object(sys, "base_prefix", str(fake)), mock.patch.object(sys, "prefix", str(venv)), \
                mock.patch.object(layers, "_trusted_dir", return_value=True, create=True):
            self.assertIn(str(venv), self.read_paths())  # the launcher _python() names lives there

    def test_untrusted_places_are_refused(self):
        writable = self.tmp / "shared"
        writable.mkdir()
        writable.chmod(0o777)
        self.assertFalse(layers._trusted_dir(str(writable)))
        self.assertFalse(layers._trusted_dir(os.path.realpath(os.path.expanduser("~"))))
        self.assertTrue(layers._trusted_dir(os.path.realpath("/usr/bin")))


class SandboxedLayerTests(Case):
    def run_probe(self, secret, visible):
        self.root.joinpath("tests/test_prefix_probe.py").write_text(textwrap.dedent(f'''
            import os, unittest
            class Prefix(unittest.TestCase):
                def test_bin_is_there_and_share_is_not(self):
                    self.assertTrue(os.path.isdir({str(visible)!r}))
                    with self.assertRaises(OSError):
                        open({str(secret)!r}).read()
        '''), encoding="utf-8")
        row, _ = layers._run_python_test(self.root, "tests/test_prefix_probe.py", self.scratch, 120)
        return row

    def test_a_layer_test_does_not_see_a_secret_under_a_tool_prefix(self):
        program, secret = self.tool(self.tmp / "opt" / "tool")
        with mock.patch.dict(os.environ, {"PATH": f"{program.parent}:{os.environ.get('PATH', '')}"}), \
                mock.patch.object(layers, "TOOLS", (program.name,)), mock.patch.object(layers, "_trusted_dir", return_value=True, create=True):
            row = self.run_probe(secret, program.parent)
        if not FULL:
            self.assertFalse(REQUIRED, "GAIE_REQUIRE_FULL_SANDBOX=1 but the full tier is missing")
            self.assertEqual(row["isolation"]["profile"], "process-only")  # measured fallback, recorded
            return
        self.assertEqual((row["status"], row["isolation"]["profile"]), ("passed", "strict"), row["output_tail"])

    def test_a_layer_test_does_not_see_a_secret_under_the_interpreter_prefix(self):
        prefix = os.path.realpath(sys.base_prefix)
        if any(prefix == root or prefix.startswith(root + os.sep) for root in governor.SYSTEM_DIRS):
            raise unittest.SkipTest(f"the hub interpreter lives in a system directory here ({prefix}), which every "
                                    "sandbox mounts whole; this case needs one outside them (a CI tool cache)")
        if not FULL:
            raise unittest.SkipTest("the governor's full tier is missing here")
        work = layers._workspace(self.scratch, "mounts")
        probe = governor.sandbox_run([sys.executable, "-I", "-S", "-c", "pass"], cwd=str(work), timeout=30,
                                     allowed_paths=[str(work)], require_fs_isolation=True)
        if "mounts" not in probe:
            raise unittest.SkipTest("this governor predates strict minimal program mounts (recheck-isolation item 1, "
                                    "commit 64dee82): it still mounts the interpreter's whole prefix")
        share = pathlib.Path(prefix) / "share"
        if not os.access(share if share.is_dir() else prefix, os.W_OK):
            raise unittest.SkipTest(f"cannot plant a file under {share} on this host")
        share.mkdir(exist_ok=True)
        secret = share / f"gaie-sf2-planted-{os.urandom(6).hex()}.txt"
        secret.write_text("planted", encoding="utf-8")
        secret.chmod(stat.S_IRUSR | stat.S_IWUSR)
        self.addCleanup(secret.unlink)
        row = self.run_probe(secret, os.path.dirname(os.path.realpath(sys.executable)))
        self.assertEqual((row["status"], row["isolation"]["profile"]), ("passed", "strict"), row["output_tail"])


if __name__ == "__main__":
    unittest.main()
