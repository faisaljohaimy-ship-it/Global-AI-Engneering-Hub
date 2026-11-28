"""pr30-isolation F3: `hub.py workspace-run` is not one-shot, and agents stay independent.

The CLI builds a supervisor per call. It validates the selected agent in full (fresh, or with --relaunch
as a workspace that already holds its own work) and checks the other assignments only for canonical,
private, independent roots, so one agent's write neither blocks its own relaunch nor a peer.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import governor
from engineering_os.workspace_policy import WorkspacePolicyError, WorkspaceSupervisor

ROOT = pathlib.Path(__file__).resolve().parents[1]
FULL = governor.isolation_probe()["tier"] == "full"
ISOLATED = {"returncode": 0, "stdout": "", "stderr": "", "limit": None, "fs_isolated": True, "network_isolated": True}


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
                          env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                               "HOME": str(path)}).stdout.strip()


class RelaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-f3-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.source, self.work = self.linked()
        self.peer = self.private("peer")
        self.assignments = {
            "dev": {"path": str(self.work), "intent": "upgrade", "expected_repository": "owner/demo"},
            "peer": {"path": str(self.peer), "intent": "build"},
        }

    def private(self, name):
        path = self.base / name
        path.mkdir(mode=0o700)
        return path

    def linked(self):
        source = self.private("source")
        git(source, "init", "--quiet", "--initial-branch=main")
        (source / "src").mkdir(mode=0o700)
        (source / "src" / "demo.txt").write_text("fixture")
        git(source, "add", "src/demo.txt")
        git(source, "-c", "user.name=f", "-c", "user.email=f@example.invalid", "commit", "--quiet", "-m", "f")
        git(source, "remote", "add", "origin", "https://github.com/owner/demo.git")
        git(source, "update-ref", "refs/remotes/origin/main", git(source, "rev-parse", "HEAD"))
        git(source, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        work = self.base / "work"
        git(source, "worktree", "add", "--quiet", "-b", "codex/review", str(work))
        work.chmod(0o700)
        (work / "src").chmod(0o700)
        return source, work

    def launch(self, agent, *, relaunch=False, assignments=None):
        supervisor = WorkspaceSupervisor(assignments or self.assignments, selected=agent, relaunch=relaunch)
        with mock.patch.object(governor, "sandbox_run", return_value=dict(ISOLATED)) as sandbox:
            supervisor.run(agent, ["/bin/true"], timeout=5)
        return sandbox

    def write_as_agents(self):
        (self.work / "feature.txt").write_text("dev work")
        (self.peer / "output.txt").write_text("peer work")

    def test_relaunch_after_a_write_succeeds_and_fresh_still_means_fresh(self):
        self.write_as_agents()
        with self.assertRaisesRegex(WorkspacePolicyError, "clean dedicated worktree"):
            WorkspaceSupervisor(self.assignments, selected="dev")
        with self.assertRaisesRegex(WorkspacePolicyError, "must be empty"):
            WorkspaceSupervisor(self.assignments, selected="peer")
        self.launch("dev", relaunch=True).assert_called_once()
        sandbox = self.launch("peer", relaunch=True)
        self.assertEqual(sandbox.call_args.kwargs["allowed_paths"], (self.peer,))
        with self.assertRaises(WorkspacePolicyError):  # the all-fresh constructor keeps its meaning
            WorkspaceSupervisor(self.assignments)

    def test_a_peer_is_unaffected_by_another_agents_writes(self):
        (self.work / "feature.txt").write_text("dev work")
        (self.work / "src" / "nested").mkdir()
        self.launch("peer").assert_called_once()  # a fresh first launch of the untouched peer
        (self.peer / "output.txt").write_text("peer work")
        self.launch("dev", relaunch=True).assert_called_once()

    def test_only_the_selected_agent_can_run(self):
        supervisor = WorkspaceSupervisor(self.assignments, selected="peer")
        with mock.patch.object(governor, "sandbox_run") as sandbox, self.assertRaisesRegex(
                WorkspacePolicyError, "no assigned write workspace"):
            supervisor.run("dev", ["/bin/true"], timeout=5)
        sandbox.assert_not_called()
        for selected, relaunch in (("nobody", False), (None, True), ("dev", "yes")):
            with self.subTest(selected=selected, relaunch=relaunch), self.assertRaises(WorkspacePolicyError):
                WorkspaceSupervisor(self.assignments, selected=selected, relaunch=relaunch)

    def test_the_selected_workspace_still_gets_the_full_check(self):
        self.write_as_agents()
        cases = []

        def nested_git():
            (self.work / "src" / ".git").mkdir()
            (self.work / "src" / ".git" / "config").write_text("[core]\n")
            return lambda: __import__("shutil").rmtree(self.work / "src" / ".git")

        def hard_link():
            os.link(self.peer / "output.txt", self.work / "alias.txt")
            return lambda: (self.work / "alias.txt").unlink()

        def other_origin():
            git(self.source, "remote", "set-url", "origin", "https://github.com/owner/peer.git")
            return lambda: git(self.source, "remote", "set-url", "origin", "https://github.com/owner/demo.git")

        def hooks_path():
            git(self.source, "config", "core.hooksPath", str(self.base))
            return lambda: git(self.source, "config", "--unset", "core.hooksPath")

        def opened_up():
            self.work.chmod(0o755)
            return lambda: self.work.chmod(0o700)

        cases = (("nested git", nested_git), ("hard link", hard_link), ("origin", other_origin),
                 ("hooks", hooks_path), ("mode", opened_up))
        for name, tamper in cases:
            with self.subTest(name):
                undo = tamper()
                with mock.patch.object(governor, "sandbox_run") as sandbox, self.assertRaises(WorkspacePolicyError):
                    WorkspaceSupervisor(self.assignments, selected="dev", relaunch=True).run("dev", ["/bin/true"],
                                                                                            timeout=5)
                sandbox.assert_not_called()
                undo()
        self.launch("dev", relaunch=True).assert_called_once()
        git(self.peer, "init", "--quiet")  # a build workspace that became a repository
        with self.assertRaises(WorkspacePolicyError):
            WorkspaceSupervisor(self.assignments, selected="peer", relaunch=True)

    def test_tampering_with_a_peers_identity_is_still_refused(self):
        self.write_as_agents()
        alias = self.base / "alias"
        alias.symlink_to(self.peer, target_is_directory=True)
        inside = self.work / "src" / "box"
        inside.mkdir(mode=0o700)
        second = self.base / "second"
        git(self.source, "worktree", "add", "--quiet", "-b", "codex/peer", str(second))
        second.chmod(0o700)
        (second / "src").chmod(0o700)
        self.launch("dev", relaunch=True, assignments={"dev": self.assignments["dev"], "other": {
            "path": str(second), "intent": "upgrade", "expected_repository": "owner/demo", "registered_path": "src"}})
        variants = {
            "symlinked peer": {"path": str(alias), "intent": "build"},
            "same root as the selected agent": {"path": str(self.work), "intent": "build"},
            "peer nested in the selected root": {"path": str(inside), "intent": "build"},
            "missing peer": {"path": str(self.base / "missing"), "intent": "build"},
            "peer without a worktree pointer": {"path": str(self.peer), "intent": "upgrade",
                                                "expected_repository": "owner/demo"},
            "unsafe registered path": {"path": str(second), "intent": "upgrade", "registered_path": "../work"},
            "registered path through a symlink": {"path": str(second), "intent": "upgrade", "registered_path": "link"},
            "unknown intent": {"path": str(self.peer), "intent": "deploy"},
            "extra key": {"path": str(self.peer), "intent": "build", "require_clean": False},
        }
        (second / "link").symlink_to(second / "src", target_is_directory=True)
        for name, peer in variants.items():
            with self.subTest(name), self.assertRaises(WorkspacePolicyError):
                self.launch("dev", relaunch=True, assignments={"dev": self.assignments["dev"], "other": peer})
        self.peer.chmod(0o755)
        with self.assertRaises(WorkspacePolicyError):
            self.launch("dev", relaunch=True)
        self.peer.chmod(0o700)
        self.peer.rename(self.base / "moved")
        with self.assertRaises(WorkspacePolicyError):
            self.launch("dev", relaunch=True)

    @unittest.skipUnless(FULL, "needs the full namespace sandbox for real workspace-run launches")
    def test_cli_relaunch_and_peer_after_a_write(self):
        config = self.base / "assignments.json"
        config.write_text(json.dumps(self.assignments))
        config.chmod(0o600)
        python = os.path.realpath(sys.executable)

        def run(agent, code, *extra):
            done = subprocess.run([sys.executable, "-B", str(ROOT / "hub.py"), "workspace-run", "--assignments",
                                   str(config), "--agent", agent, "--timeout", "20", *extra, "--", python, "-I",
                                   "-S", "-c", code], capture_output=True, text=True, timeout=120,
                                  env={**os.environ, "TMPDIR": "/tmp"})
            return done.returncode, json.loads(done.stdout)

        self.assertEqual(run("dev", "open('feature.txt', 'w').write('x')")[0], 0)
        code, report = run("dev", "print('again')")
        self.assertEqual((code, report["status"]), (3, "denied"))
        code, report = run("dev", "print('again')", "--relaunch")
        self.assertEqual((code, report["stdout"]), (0, "again\n"))
        code, report = run("peer", "print('peer')")
        self.assertEqual((code, report["stdout"]), (0, "peer\n"))
        self.assertEqual((self.work / "feature.txt").read_text(), "x")


if __name__ == "__main__":
    unittest.main()
