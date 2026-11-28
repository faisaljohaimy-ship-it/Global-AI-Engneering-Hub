"""pr30-isolation recheck item 3: build_engine._git's config check fails closed.

Before: the check located the Git directories with one `rev-parse --git-dir --git-common-dir` call split
into lines and skipped itself unless exactly two lines came back, and it never looked at submodules. A
gitfile pointing at a Git directory whose name holds a newline, and a submodule with its own clean filter,
each ran a planted program on the host (SP/work/recheck-isolation/poc/f2_variants.py). Now each path is
asked for alone and taken whole, anything unexpected is refused, and a repository with submodules (a
gitlink or .gitmodules in the index, a .gitmodules file, a modules/ directory) is refused before Git runs.
"""

import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from engineering_os import build_engine

CLEAN_ENV = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
REAL_RUN = subprocess.run


def git(path, *args):
    return REAL_RUN(["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
                    env={**CLEAN_ENV, "HOME": str(path)}).stdout.strip()


def plain_git(path, *args):
    """The operator's ordinary Git, without any of the hub's hardening."""
    return REAL_RUN(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=60,
                    env={**CLEAN_ENV, "HOME": str(path)})


class BuildGitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-bg-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.marker = self.base / "host-program-ran"
        self.payload = self.base / "payload.sh"
        self.payload.write_text(f"#!/bin/sh\ntouch {self.marker}\ncat\n")
        self.payload.chmod(0o755)
        self.ws = self.base / "ws"
        self.ws.mkdir(mode=0o700)

    def assert_refused_and_nothing_ran(self, *commands):
        for args in commands or (("status", "--porcelain"), ("add", "--all"), ("rev-parse", "HEAD")):
            with self.subTest(args=args), self.assertRaisesRegex(build_engine.BuildError, "git refused"):
                build_engine._git(self.ws, *args)
        self.assertFalse(self.marker.exists())

    def premise(self, *args):
        plain_git(self.ws, *args)
        self.assertTrue(self.marker.exists(), f"premise: plain git {args[0]} runs the planted filter")
        self.marker.unlink()

    def test_a_git_directory_whose_name_holds_a_newline_is_still_checked(self):
        real = self.ws / "a\nb"
        real.mkdir()
        git(real, "init", "-q", "--bare")
        git(real, "config", "core.bare", "false")
        git(real, "config", "filter.x.clean", str(self.payload))
        (self.ws / ".git").write_text("gitdir: a\nb\n")
        (self.ws / ".gitattributes").write_text("* filter=x\n")
        (self.ws / "f").write_text("data")
        self.premise("add", "--all")
        plain_git(self.ws, "rm", "-q", "--cached", "-r", ".")
        self.marker.unlink(missing_ok=True)
        self.assert_refused_and_nothing_ran(("status", "--porcelain"), ("add", "--all"))

    def submodule(self):
        git(self.ws, "init", "-q", "-b", "main")
        sub = self.ws / "sub"
        sub.mkdir()
        git(sub, "init", "-q", "-b", "main")
        (sub / ".gitattributes").write_text("* filter=x\n")
        (sub / "f").write_text("data")
        git(sub, "add", "-A")
        git(sub, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "s")
        git(sub, "config", "filter.x.clean", str(self.payload))
        os.utime(sub / "f", (1, 1))  # stat-dirty inside the submodule
        git(self.ws, "update-index", "--add", "--cacheinfo", f"160000,{git(sub, 'rev-parse', 'HEAD')},sub")
        return sub

    def test_a_submodule_with_its_own_filter_is_refused(self):
        self.submodule()
        (self.ws / ".gitmodules").write_text('[submodule "sub"]\n\tpath = sub\n\turl = ./sub\n')
        git(self.ws, "add", ".gitmodules")
        git(self.ws, "-c", "user.name=a", "-c", "user.email=a@example.invalid", "commit", "-qm", "m")
        self.premise("status", "--porcelain")
        os.utime(self.ws / "sub" / "f", (3, 3))
        self.assert_refused_and_nothing_ran()

    def test_every_submodule_sign_is_refused(self):
        self.submodule()  # a gitlink in the index, no .gitmodules
        self.assert_refused_and_nothing_ran(("status", "--porcelain"))
        git(self.ws, "update-index", "--force-remove", "sub")
        self.assertEqual(build_engine._git(self.ws, "status", "--porcelain").returncode, 0)
        (self.ws / ".gitmodules").write_text("")  # an untracked .gitmodules file
        self.assert_refused_and_nothing_ran(("status", "--porcelain"))
        (self.ws / ".gitmodules").unlink()
        (self.ws / ".git" / "modules").mkdir()  # absorbed submodule Git directories
        self.assert_refused_and_nothing_ran(("status", "--porcelain"))

    def test_unexpected_locator_output_fails_closed(self):
        git(self.ws, "init", "-q", "-b", "main")
        self.assertEqual(build_engine._git(self.ws, "status", "--porcelain").returncode, 0)

        def answer(text):
            def fake(command, *args, **kwargs):
                if "--git-dir" in command:
                    return subprocess.CompletedProcess(command, 0, text, "")
                return REAL_RUN(command, *args, **kwargs)
            return fake

        for text in (f"{self.ws}/.git\n{self.ws}/.git\n", "", ".git\n", f"{self.ws}/.git", f"{self.base}/missing\n"):
            with self.subTest(text=text), mock.patch.object(build_engine.subprocess, "run", side_effect=answer(text)), \
                    self.assertRaisesRegex(build_engine.BuildError, "located exactly"):
                build_engine._git(self.ws, "status", "--porcelain")
        with self.assertRaisesRegex(build_engine.BuildError, "located exactly"):  # not a repository at all
            build_engine._git(self.base, "status", "--porcelain")

    def test_engine_repositories_and_local_bare_remotes_still_work(self):
        build_engine._git(self.ws, "init", "--quiet", "--template=", "-b", "main")
        (self.ws / "app.py").write_text("print('app')\n")
        build_engine._git(self.ws, "add", "--all")
        build_engine._git(self.ws, "commit", "--quiet", "-m", "app")
        self.assertEqual(build_engine._git(self.ws, "status", "--porcelain").stdout, "")
        bare = self.base / "demo.git"
        git(self.base, "init", "--bare", "--quiet", str(bare))
        self.assertEqual(build_engine._remote(str(bare), "demo"), (str(bare), "local-bare"))
        pushed = build_engine._git(self.ws, "push", "--porcelain", str(bare), "refs/heads/main:refs/heads/main")
        self.assertEqual(pushed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
