"""pr30-isolation F1: the workspace preflight must never start a program a checkout's Git config names.

A partial-clone lazy fetch (extensions.partialClone, remote.<x>.promisor or .partialCloneFilter) makes an
object lookup such as `rev-parse --verify origin/main^{commit}` start the configured transport: the
upload-pack program of remote.<x>.uploadpack, or core.sshCommand for an ssh origin. Each case below first
proves that plain Git runs the program on this host, then that the preflight does not.
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import workspace_policy
from engineering_os.workspace_policy import WorkspacePolicyError, WorkspaceSupervisor, validate_workspace

ROOT = pathlib.Path(__file__).resolve().parents[1]
MISSING = "1" * 40  # a commit absent from the object store: the normal state of a partial clone


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
                          env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                               "HOME": str(path)}).stdout.strip()


class PromisorFetchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-f1-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.marker = self.base / "program-ran"
        self.source, self.work = self.fixture()

    def fixture(self, origin="https://github.com/owner/demo.git"):
        source = self.base / "source"
        source.mkdir(mode=0o700)
        git(source, "init", "--quiet", "--initial-branch=main")
        (source / "src").mkdir(mode=0o700)
        (source / "src" / "demo.txt").write_text("fixture")
        git(source, "add", "src/demo.txt")
        git(source, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "--quiet", "-m", "fixture")
        git(source, "remote", "add", "origin", origin)
        git(source, "update-ref", "refs/remotes/origin/main", git(source, "rev-parse", "HEAD"))
        git(source, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        work = self.base / "work"
        git(source, "worktree", "add", "--quiet", "-b", "codex/review", str(work))
        work.chmod(0o700)
        (work / "src").chmod(0o700)
        return source, work

    def lazy_remote(self, *settings):
        """A local promisor remote whose upload-pack program is the payload; origin/main becomes absent."""
        other = self.base / "other.git"
        git(self.base, "init", "--bare", "--quiet", str(other))
        for key, value in (("remote.lazy.url", str(other)),
                           ("remote.lazy.uploadpack", f"touch {self.marker}; git-upload-pack"), *settings):
            git(self.source, "config", key, value)
        (self.source / ".git" / "refs" / "remotes" / "origin" / "main").write_text(MISSING + "\n")

    def plain_lookup(self):
        subprocess.run(["git", "-C", str(self.work), "rev-parse", "--verify", "refs/remotes/origin/main^{commit}"],
                       capture_output=True, check=False, timeout=60,
                       env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        ran = self.marker.exists()
        self.marker.unlink(missing_ok=True)
        return ran

    def validate(self, **kwargs):
        return validate_workspace(self.work, intent="upgrade", expected_repository="owner/demo", **kwargs)

    def assert_refused_without_running(self):
        with self.assertRaisesRegex(WorkspacePolicyError, "partial-clone and protocol settings"):
            self.validate()
        with self.assertRaises(WorkspacePolicyError):
            self.validate(require_clean=False)
        with self.assertRaises(WorkspacePolicyError):
            validate_workspace(self.work, intent="upgrade", expected_repository="someone/else")
        with self.assertRaises(WorkspacePolicyError):
            WorkspaceSupervisor({"dev": {"path": self.work, "intent": "upgrade", "expected_repository": "owner/demo"}})
        self.assertFalse(self.marker.exists(), "the checkout-configured program ran during the preflight")

    def test_promisor_upload_pack_program_never_runs(self):
        for name, settings in (
                ("extensions.partialClone", (("core.repositoryFormatVersion", "1"),
                                             ("extensions.partialClone", "lazy"), ("remote.lazy.promisor", "true"))),
                ("remote.promisor", (("remote.lazy.promisor", "true"),)),
                ("remote.partialCloneFilter", (("remote.lazy.partialCloneFilter", "blob:none"),))):
            with self.subTest(vector=name):
                for key in ("core.repositoryFormatVersion", "extensions.partialClone", "remote.lazy.promisor",
                            "remote.lazy.partialCloneFilter"):
                    subprocess.run(["git", "-C", str(self.source), "config", "--unset", key], capture_output=True)
                self.lazy_remote(*settings)
                self.assertTrue(self.plain_lookup(), "premise: plain Git lazily fetches and runs uploadpack here")
                self.assert_refused_without_running()

    def test_origin_ssh_command_never_runs(self):
        git(self.source, "remote", "set-url", "origin", "ssh://git@github.com/owner/demo.git")
        for key, value in (("core.repositoryFormatVersion", "1"), ("extensions.partialClone", "origin"),
                           ("remote.origin.promisor", "true"), ("core.sshCommand", f"touch {self.marker}; false")):
            git(self.source, "config", key, value)
        (self.source / ".git" / "refs" / "remotes" / "origin" / "main").write_text(MISSING + "\n")
        self.assertTrue(self.plain_lookup(), "premise: plain Git lazily fetches through core.sshCommand here")
        self.assert_refused_without_running()

    def test_each_named_program_or_policy_key_is_refused(self):
        for key, value in (("core.sshCommand", "false"), ("core.gitProxy", "false"),
                           ("remote.origin.uploadpack", "false"), ("remote.origin.receivepack", "false"),
                           ("remote.origin.vcs", "probe"), ("remote.Mixed.Case.promisor", "true"),
                           ("protocol.file.allow", "always"), ("protocol.allow", "always"),
                           ("extensions.partialClone", "origin"), ("extensions.preciousObjects", "true"),
                           ("include.path", "/dev/null"), ("filter.probe.clean", "false")):
            with self.subTest(key=key):
                git(self.source, "config", key, value)
                with self.assertRaisesRegex(WorkspacePolicyError, "includes, URL rewrites, filters and hooks"):
                    self.validate()
                git(self.source, "config", "--unset", key)
        self.assertEqual(self.validate().branch, "codex/review")

    def test_worktree_config_extension_is_still_accepted(self):
        git(self.source, "config", "core.repositoryFormatVersion", "1")
        git(self.source, "config", "extensions.worktreeConfig", "true")
        self.assertEqual(self.validate().branch, "codex/review")
        metadata = self.source / ".git" / "worktrees" / "work" / "config.worktree"
        git(self.work, "config", "--worktree", "core.sshCommand", "false")
        metadata.chmod(0o600)
        with self.assertRaisesRegex(WorkspacePolicyError, "remote programs"):
            self.validate()

    def test_hardened_git_is_offline_even_when_the_config_allows_a_protocol(self):
        """The barrier holds on its own: the deny list is not what keeps _git from fetching."""
        self.lazy_remote(("remote.lazy.promisor", "true"), ("protocol.file.allow", "always"))
        self.assertTrue(self.plain_lookup(), "premise: plain Git runs the program despite any -c default")
        with self.assertRaises(WorkspacePolicyError):
            workspace_policy._git(self.work, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
        with self.assertRaises(WorkspacePolicyError):
            workspace_policy._git(self.work, "cat-file", "-e", MISSING)
        self.assertFalse(self.marker.exists())
        for flag in ("core.fsmonitor=false", "core.hooksPath=/dev/null", "protocol.allow=never"):
            self.assertIn(flag, workspace_policy.GIT_FLAGS)
        self.assertEqual(workspace_policy.GIT_OFFLINE_ENV["GIT_ALLOW_PROTOCOL"], "")

    def test_origin_is_verified_before_any_object_lookup(self):
        calls = []
        real = workspace_policy._git

        def recording(path, *args, absent=False):
            calls.append(args)
            return real(path, *args, absent=absent)

        with mock.patch.object(workspace_policy, "_git", recording):
            self.validate()
        commands = [" ".join(args[:2]) for args in calls]
        first_lookup = min(commands.index("rev-parse --verify"), commands.index("status --porcelain=v1"))
        self.assertLess(commands.index("remote get-url"), first_lookup)
        calls.clear()
        git(self.source, "remote", "set-url", "origin", "https://github.com/owner/peer.git")
        with mock.patch.object(workspace_policy, "_git", recording), self.assertRaisesRegex(
                WorkspacePolicyError, "matching registered fetch and push origin"):
            self.validate()
        self.assertNotIn("rev-parse --verify", [" ".join(args[:2]) for args in calls])

    def test_read_only_route_with_a_planted_promisor_runs_nothing(self):
        git(self.source, "remote", "set-url", "origin", "https://github.com/faisaljohaimy-ship-it/Wow-bus.git")
        self.lazy_remote(("remote.lazy.promisor", "true"))
        self.assertTrue(self.plain_lookup(), "premise")
        done = subprocess.run([sys.executable, "-B", str(ROOT / "hub.py"), "route", "upgrade wow bus",
                               "--workspace", str(self.work)], capture_output=True, text=True, timeout=120,
                              env={"PATH": os.environ.get("PATH", os.defpath), "TMPDIR": "/tmp",
                                   "HOME": str(self.base)}, cwd=str(self.base))
        self.assertEqual(done.returncode, 0, done.stderr[-400:])
        self.assertIn("partial-clone and protocol settings", done.stdout)
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
