import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import governor
from engineering_os.workspace_policy import WorkspacePolicyError, WorkspaceSupervisor, validate_workspace


class WorkspacePolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-workspace-policy-")
        self.addCleanup(temporary.cleanup)
        self.directory = pathlib.Path(temporary.name).resolve()

    def git(self, path, *args):
        return subprocess.run(
            ["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    def fixture(self):
        source = self.directory / "source"
        source.mkdir(mode=0o700)
        self.git(source, "init", "--quiet", "--initial-branch=main")
        (source / "src").mkdir(mode=0o700)
        (source / "src" / "demo.txt").write_text("fixture")
        self.git(source, "add", "src/demo.txt")
        self.git(source, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--quiet", "-m", "fixture")
        self.git(source, "remote", "add", "origin", "https://github.com/owner/demo.git")
        self.git(source, "update-ref", "refs/remotes/origin/main", self.git(source, "rev-parse", "HEAD"))
        self.git(source, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        worktree = self.directory / "work"
        self.git(source, "worktree", "add", "--quiet", "-b", "codex/review", str(worktree))
        worktree.chmod(0o700)
        (worktree / "src").chmod(0o700)
        return source, worktree

    def candidate(self, name):
        path = self.directory / name
        path.mkdir(mode=0o700)
        return path

    def development(self, path, **kwargs):
        return validate_workspace(path, intent="upgrade", expected_repository="owner/demo", **kwargs)

    def test_build_must_be_empty_owner_only_and_outside_repository(self):
        build = self.candidate("build")
        self.assertEqual(validate_workspace(build, intent="build").root, build)
        build.chmod(0o755)
        with self.assertRaises(WorkspacePolicyError):
            validate_workspace(build, intent="build")
        build.chmod(0o700)
        sentinel = build / ".hidden"
        sentinel.touch()
        with self.assertRaises(WorkspacePolicyError):
            validate_workspace(build, intent="build")
        sentinel.unlink()
        source, worktree = self.fixture()
        for parent in (source, worktree):
            nested = parent / "candidate"
            nested.mkdir(mode=0o700)
            with self.subTest(parent=parent), self.assertRaises(WorkspacePolicyError):
                validate_workspace(nested, intent="build")
        bare = self.directory / "bare"
        self.git(self.directory, "init", "--bare", "--quiet", str(bare))
        nested = bare / "candidate"
        nested.mkdir(mode=0o700)
        with self.assertRaises(WorkspacePolicyError):
            validate_workspace(nested, intent="build")

    def test_only_exclusive_linked_clean_worktree_matches_registered_scope(self):
        source, worktree = self.fixture()
        scope = self.development(worktree, registered_path="src")
        self.assertEqual((scope.root, scope.checkout, scope.branch), (worktree / "src", worktree, "codex/review"))
        for path in (source, worktree / "src"):
            with self.assertRaises(WorkspacePolicyError):
                self.development(path)
        with self.assertRaises(WorkspacePolicyError):
            self.development(worktree, registered_path="../work")
        (worktree / "src" / "dirty.txt").touch()
        with self.assertRaises(WorkspacePolicyError):
            self.development(worktree)
        self.assertEqual(self.development(worktree, require_clean=False).branch, "codex/review")

    def test_missing_default_mismatched_origin_and_changed_push_url_fail_closed(self):
        source, worktree = self.fixture()
        self.git(source, "remote", "set-url", "--push", "origin", "https://github.com/owner/peer.git")
        with self.assertRaises(WorkspacePolicyError):
            self.development(worktree)
        self.git(source, "config", "--local", "--unset", "remote.origin.pushurl")
        self.git(source, "remote", "set-url", "origin", "https://github.com/owner/peer.git")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "remote.origin.url",
                                          "GIT_CONFIG_VALUE_0": "https://github.com/owner/demo.git"}):
            with self.assertRaises(WorkspacePolicyError):
                self.development(worktree)
        self.git(source, "remote", "set-url", "origin", "https://github.com/owner/demo.git")
        self.git(source, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        with self.assertRaises(WorkspacePolicyError):
            self.development(worktree)
        self.git(source, "update-ref", "refs/remotes/origin/codex/review", self.git(source, "rev-parse", "HEAD"))
        self.git(source, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/codex/review")
        with self.assertRaises(WorkspacePolicyError):
            self.development(worktree)

    def test_aliases_git_marker_spoofing_and_git_filters_cannot_pass(self):
        source, worktree = self.fixture()
        alias = self.directory / "alias"
        alias.symlink_to(worktree, target_is_directory=True)
        with self.assertRaises(WorkspacePolicyError):
            self.development(alias)
        spoof = self.candidate("spoof")
        (spoof / ".git").write_text((worktree / ".git").read_text())
        with self.assertRaises(WorkspacePolicyError):
            self.development(spoof)
        marker = self.directory / "filter-ran.txt"
        (worktree / ".gitattributes").write_text("*.txt filter=guard\n")
        self.git(source, "config", "--local", "filter.guard.clean", f"touch {marker}; cat")
        with self.assertRaisesRegex(WorkspacePolicyError, "filters"):
            self.development(worktree)
        self.assertFalse(marker.exists())

    def test_supervisor_checks_agent_and_single_fixed_write_root(self):
        build, peer = self.candidate("build"), self.candidate("peer")
        supervisor = WorkspaceSupervisor({
            "first": {"path": build, "intent": "build"},
            "second": {"path": peer, "intent": "build"},
        })
        with mock.patch.object(governor, "sandbox_run", return_value={
                "fs_isolated": True, "network_isolated": True,
        }) as launch:
            with self.assertRaises(WorkspacePolicyError):
                supervisor.run("unassigned", [sys.executable, "-c", "print('fixture')"], timeout=2)
            launch.assert_not_called()
            command = [sys.executable, "-c", "print('fixture')"]
            supervisor.run("first", command, timeout=2)
            launch.assert_called_once_with(command, cwd=build, timeout=2, network=False, env_allow=(),
                                           allowed_paths=(build,), require_fs_isolation=True)
        with self.assertRaises(WorkspacePolicyError):
            WorkspaceSupervisor({"first": {"path": build, "intent": "build"},
                                 "other": {"path": build, "intent": "build"}})
        with self.assertRaises(WorkspacePolicyError):
            WorkspaceSupervisor({"first": {"path": build, "intent": "build", "require_clean": False}})

    def test_supervisor_refuses_file_alias_and_replaced_scope(self):
        build = self.candidate("build")
        peer = self.candidate("peer")
        target = peer / "fixture.txt"
        target.write_text("peer")
        supervisor = WorkspaceSupervisor({"first": {"path": build, "intent": "build"}})
        os.link(target, build / "alias.txt")
        with self.assertRaisesRegex(WorkspacePolicyError, "hard links"):
            supervisor.run("first", ["false"], timeout=2)
        self.assertEqual(target.read_text(), "peer")
        (build / "alias.txt").unlink()
        build.rename(self.directory / "old")
        build.mkdir(mode=0o700)
        with self.assertRaisesRegex(WorkspacePolicyError, "changed identity"):
            supervisor.run("first", ["false"], timeout=2)

    def test_supervisor_requires_both_isolation_results_even_if_runner_returns(self):
        build = self.candidate("build")
        supervisor = WorkspaceSupervisor({"first": {"path": build, "intent": "build"}})
        with mock.patch.object(governor, "sandbox_run", return_value={
                "fs_isolated": False, "network_isolated": True,
        }):
            with self.assertRaisesRegex(WorkspacePolicyError, "required isolation"):
                supervisor.run("first", ["false"], timeout=2)

    def test_real_supervisor_boundary_or_refusal_before_launch(self):
        source, worktree = self.fixture()
        peer = self.candidate("peer")
        peer_file = peer / "fixture.txt"
        supervisor = WorkspaceSupervisor({
            "developer": {"path": worktree, "intent": "upgrade", "expected_repository": "owner/demo"},
            "peer": {"path": peer, "intent": "build"},
        })
        peer_file.write_text("unchanged")
        git_pointer = (worktree / ".git").read_bytes()
        main_head = self.git(source, "rev-parse", "HEAD")
        program = (
            "from pathlib import Path\n"
            "import sys\n"
            "Path('permitted.txt').write_text('self')\n"
            "for target in (Path(sys.argv[1]), Path('.git')):\n"
            "    try:\n"
            "        target.write_text('changed')\n"
            "    except OSError:\n"
            "        continue\n"
            "    raise AssertionError('unexpected workspace write')\n"
        )
        # Strict mode hides /etc. Name the interpreter file itself, because /usr/bin/python3 is a
        # Debian alternatives link through /etc on some hosts and would dangle inside the sandbox.
        command = [os.path.realpath("/usr/bin/python3"), "-I", "-S", "-c", program, str(peer_file)]
        if governor.isolation_probe()["tier"] == "full":
            result = supervisor.run("developer", command, timeout=10)
            self.assertEqual(result["returncode"], 0, result["stderr"])
            self.assertEqual((worktree / "permitted.txt").read_text(), "self")
        else:
            with self.assertRaises(governor.GovernorDenied) as refusal:
                supervisor.run("developer", command, timeout=10)
            self.assertEqual(refusal.exception.reason, "filesystem-isolation-unavailable")
            self.assertFalse((worktree / "permitted.txt").exists())
        self.assertEqual(peer_file.read_text(), "unchanged")
        self.assertEqual((worktree / ".git").read_bytes(), git_pointer)
        self.assertEqual(self.git(source, "rev-parse", "HEAD"), main_head)
