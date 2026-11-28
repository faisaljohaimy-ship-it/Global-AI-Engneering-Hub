"""recheck-isolation-2 item 4 (release blocker): layers._run passes no whole install prefix as a read path.

Before: the strict layer sandbox got sys.prefix, sys.base_prefix and each TOOLS program's install prefix
(the parent of its bin directory) read-only. Measured by the re-check (poc/i1_callers.py): with node in
<home>/.local/bin a strict layer child printed <home>/.local/share/keyrings/login.keyring, and with node under
~/.nvm it printed a planted etc/npmrc token; on this host strict layer children saw all of /opt/node22. Now the
governor mounts the hub's interpreter itself (since 64dee82 only bin, stdlib and linked libraries in strict
runs), node contributes only its bin directory, and only from a place outside every home directory that no
non-root user can change. Every case plants secrets under <prefix>/share and <prefix>/etc. Real boundary or
measured refusal: the sandboxed checks need the governor's full tier; elsewhere the recorded process-only
fallback is asserted instead.
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


def plant(prefix):
    """Secrets under <prefix>/share and <prefix>/etc, as a keyring and an npm token would sit there."""
    secrets = []
    for relative in ("share/keyrings/login.keyring", "etc/npmrc"):
        path = prefix / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("planted-" + os.urandom(8).hex(), encoding="utf-8")
        secrets.append(path)
    return secrets


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="gaie-sf2p-", dir="/tmp" if os.path.isdir("/tmp") else None)).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        (self.root / "tests").mkdir(parents=True)
        self.scratch = self.tmp / "scratch"
        self.scratch.mkdir(mode=0o700)

    def node(self, prefix):
        """A stand-in node install: <prefix>/bin/node plus secrets under <prefix>/share and <prefix>/etc."""
        (prefix / "bin").mkdir(parents=True)
        program = prefix / "bin" / "node"
        program.write_text("#!/bin/sh\necho node-ran\n", encoding="utf-8")
        program.chmod(0o755)
        return program, plant(prefix)

    def on_path(self, program, **extra):
        return mock.patch.dict(os.environ, {"PATH": f"{program.parent}:{os.environ.get('PATH', '')}", **extra})

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

    def run_probe(self, secrets, visible=None):
        """A strict layer test that must see `visible` (if given) and must not read any of `secrets`."""
        self.root.joinpath("tests/test_prefix_probe.py").write_text(textwrap.dedent(f'''
            import os, unittest
            class Prefix(unittest.TestCase):
                def test_bin_is_there_and_share_and_etc_are_not(self):
                    if {str(visible) if visible else None!r}:
                        self.assertTrue(os.path.isdir({str(visible) if visible else ""!r}))
                    for secret in {[str(path) for path in secrets]!r}:
                        with self.assertRaises(OSError, msg=secret):
                            open(secret).read()
        '''), encoding="utf-8")
        row, _ = layers._run_python_test(self.root, "tests/test_prefix_probe.py", self.scratch, 120)
        return row

    def assert_contained(self, row):
        if not FULL:
            self.assertFalse(REQUIRED, "GAIE_REQUIRE_FULL_SANDBOX=1 but the full tier is missing")
            self.assertEqual(row["isolation"]["profile"], "process-only")  # measured fallback, recorded
            return
        self.assertEqual((row["status"], row["isolation"]["profile"]), ("passed", "strict"), row["output_tail"])


class ReadPathTests(Case):
    def test_node_under_the_home_directory_exposes_nothing_of_it(self):
        home = self.tmp / "home"
        for prefix in (home / ".local", home / ".nvm" / "versions" / "node" / "v22.11.0"):
            with self.subTest(prefix=str(prefix.relative_to(home))):
                program, _ = self.node(prefix)
                with self.on_path(program, HOME=str(home)):
                    self.assertEqual(shutil.which("node"), str(program))
                    paths = self.read_paths()
                self.assertFalse([path for path in paths if path == str(home) or path.startswith(str(home) + os.sep)],
                                 paths)

    def test_a_trusted_node_contributes_its_bin_directory_never_its_prefix(self):
        program, _ = self.node(self.tmp / "opt" / "node22")
        with self.on_path(program), mock.patch.object(layers, "_trusted_dir", return_value=True, create=True):
            paths = self.read_paths()
        self.assertIn(str(program.parent), paths)
        self.assertNotIn(str(self.tmp / "opt" / "node22"), paths)
        self.assertFalse([path for path in paths if path.endswith((os.sep + "share", os.sep + "etc"))], paths)

    def test_the_interpreter_prefixes_are_left_to_the_governor(self):
        fake = self.tmp / "opt" / "python"
        plant(fake)
        with mock.patch.object(sys, "base_prefix", str(fake)), mock.patch.object(sys, "prefix", str(fake)):
            paths = self.read_paths()
        self.assertFalse([path for path in paths if path == str(fake) or path.startswith(str(fake) + os.sep)], paths)
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
    def test_a_layer_test_does_not_see_secrets_under_the_node_prefix(self):
        program, secrets = self.node(self.tmp / "opt" / "node22")
        with self.on_path(program), mock.patch.object(layers, "_trusted_dir", return_value=True, create=True):
            row = self.run_probe(secrets, program.parent)
        self.assertEqual(len(secrets), 2)
        self.assert_contained(row)

    def test_a_layer_test_does_not_see_secrets_under_a_home_directory_node(self):
        """The re-check's two layouts: <home>/.local/bin/node and ~/.nvm/versions/node/<v>/bin/node."""
        home = self.tmp / "home"
        for prefix in (home / ".local", home / ".nvm" / "versions" / "node" / "v22.11.0"):
            with self.subTest(prefix=str(prefix.relative_to(home))):
                program, secrets = self.node(prefix)
                with self.on_path(program, HOME=str(home)):
                    row = self.run_probe(secrets)
                self.assert_contained(row)

    def test_a_layer_test_does_not_see_secrets_under_the_interpreter_prefix(self):
        prefix = pathlib.Path(os.path.realpath(sys.base_prefix))
        if any(str(prefix) == root or str(prefix).startswith(root + os.sep) for root in governor.SYSTEM_DIRS):
            raise unittest.SkipTest(f"the hub interpreter lives in a system directory here ({prefix}), which every "
                                    "sandbox mounts whole; this case needs one outside them (a CI tool cache, or an "
                                    "/opt stand-in in a private mount namespace)")
        if not FULL:
            raise unittest.SkipTest("the governor's full tier is missing here")
        work = layers._workspace(self.scratch, "mounts")
        probe = governor.sandbox_run([sys.executable, "-I", "-S", "-c", "pass"], cwd=str(work), timeout=30,
                                     allowed_paths=[str(work)], require_fs_isolation=True)
        if "mounts" not in probe:
            raise unittest.SkipTest("this governor predates strict minimal program mounts (recheck-isolation item 1, "
                                    "commit 64dee82): it still mounts the interpreter's whole prefix")
        if not all(os.access(prefix / name if (prefix / name).is_dir() else prefix, os.W_OK) for name in ("share", "etc")):
            raise unittest.SkipTest(f"cannot plant files under {prefix}/share and {prefix}/etc on this host")
        secrets = []
        for relative in (f"share/gaie-sf2-{os.urandom(6).hex()}.keyring", f"etc/gaie-sf2-{os.urandom(6).hex()}.npmrc"):
            path = prefix / relative
            created = not path.parent.exists()
            path.parent.mkdir(exist_ok=True)
            if created:
                self.addCleanup(path.parent.rmdir)
            path.write_text("planted", encoding="utf-8")
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            self.addCleanup(path.unlink)
            secrets.append(path)
        row = self.run_probe(secrets, os.path.dirname(os.path.realpath(sys.executable)))
        self.assertEqual((row["status"], row["isolation"]["profile"]), ("passed", "strict"), row["output_tail"])


if __name__ == "__main__":
    unittest.main()
