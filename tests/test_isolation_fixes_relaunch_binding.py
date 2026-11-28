"""pr30-isolation recheck item 2: --relaunch is bound to a recorded earlier fresh launch.

Before: `--relaunch` was an unbound operator assertion. On the FIRST launch of a never-assigned, non-empty,
operator-owned 0700 directory (a stand-in for ~/.ssh) it skipped the empty check, and the strict child appended
a key to authorized_keys (SP/work/recheck-isolation/poc/f3_variants.py, step 7). Now every fresh run records the
agent's workspace identity (device, inode) and assignment digest in the operator's private launch record
(`hub.py workspace-run` keeps it next to the assignment file as <assignments>.launches), and a relaunch is
accepted only for exactly that record.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import governor, workspace_policy
from engineering_os.workspace_policy import WorkspacePolicyError, WorkspaceSupervisor

ROOT = pathlib.Path(__file__).resolve().parents[1]
FULL = governor.isolation_probe()["tier"] == "full"
ISOLATED = {"returncode": 0, "stdout": "", "stderr": "", "limit": None, "fs_isolated": True, "network_isolated": True}


class BindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-rl-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.build = self.private("build")
        self.dot_ssh = self.private("dot-ssh")  # never handed out fresh, holds the operator's keys
        (self.dot_ssh / "authorized_keys").write_text("ssh-ed25519 AAAA operator\n")
        (self.dot_ssh / "authorized_keys").chmod(0o600)
        self.assignments = {"builder": {"path": str(self.build), "intent": "build"},
                            "other": {"path": str(self.dot_ssh), "intent": "build"}}
        self.state = self.base / "assignments.json.launches"

    def private(self, name):
        path = self.base / name
        path.mkdir(mode=0o700)
        return path

    def launch(self, agent, *, relaunch=False, assignments=None, state=None):
        supervisor = WorkspaceSupervisor(assignments or self.assignments, selected=agent, relaunch=relaunch,
                                         state=state or self.state)
        with mock.patch.object(governor, "sandbox_run", return_value=dict(ISOLATED)) as sandbox:
            supervisor.run(agent, ["/bin/true"], timeout=5)
        return sandbox

    def refused(self, agent, message, **kwargs):
        with mock.patch.object(governor, "sandbox_run") as sandbox, self.assertRaisesRegex(WorkspacePolicyError, message):
            self.launch(agent, **kwargs)
        sandbox.assert_not_called()

    def test_relaunch_on_a_first_launch_of_a_private_directory_is_refused(self):
        self.refused("other", "must be empty")
        self.refused("other", "recorded fresh launch", relaunch=True)
        self.assertEqual((self.dot_ssh / "authorized_keys").read_text(), "ssh-ed25519 AAAA operator\n")
        self.assertEqual(workspace_policy._launches(self.state), {})

    def test_a_fresh_launch_records_what_a_relaunch_must_match(self):
        self.refused("builder", "recorded fresh launch", relaunch=True)
        self.launch("builder").assert_called_once()
        info = self.build.stat()
        record = workspace_policy._launches(self.state)
        settings = {"path": self.build, "intent": "build"}
        self.assertEqual(record, {"builder": {"device": info.st_dev, "inode": info.st_ino,
                                              "assignment_sha256": workspace_policy._assignment_digest("builder", settings)}})
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        (self.build / "work.txt").write_text("own work")
        self.refused("builder", "must be empty")  # fresh still means fresh
        self.launch("builder", relaunch=True).assert_called_once()
        self.launch("builder", relaunch=True).assert_called_once()  # a relaunch keeps the record

    def test_a_record_binds_identity_assignment_and_agent(self):
        self.launch("builder")
        (self.build / "work.txt").write_text("own work")
        # another agent named for the recorded directory
        swapped = {"builder": {"path": str(self.dot_ssh), "intent": "build"}, "peer": {"path": str(self.build), "intent": "build"}}
        self.refused("peer", "recorded fresh launch", relaunch=True, assignments=swapped)
        # the recorded agent pointed at another directory
        self.refused("builder", "recorded fresh launch", relaunch=True, assignments=swapped)
        # the same path, but a different directory (re-created and filled; the old one still exists, so the
        # inode cannot be reused)
        self.build.rename(self.base / "old-build")
        self.private("build")
        (self.build / "authorized_keys").write_text("ssh-ed25519 AAAA operator\n")
        self.assertNotEqual((self.base / "old-build").stat().st_ino, self.build.stat().st_ino)
        self.refused("builder", "recorded fresh launch", relaunch=True)

    def test_without_a_trustworthy_record_nothing_is_relaunched(self):
        self.launch("builder")
        (self.build / "work.txt").write_text("own work")
        with self.assertRaisesRegex(WorkspacePolicyError, "private record of an earlier fresh launch"):
            WorkspaceSupervisor(self.assignments, selected="builder", relaunch=True)
        original = self.state.read_bytes()
        cases = {
            "corrupt": lambda: self.state.write_text("{not json"),
            "wrong schema": lambda: self.state.write_text(json.dumps({"schema": "other", "launches": {}})),
            "readable by others": lambda: self.state.chmod(0o644),
            "hard link": lambda: os.link(self.state, self.base / "alias"),
        }
        for name, tamper in cases.items():
            with self.subTest(name):
                tamper()
                self.refused("builder", "launch record", relaunch=True)
                (self.base / "alias").unlink(missing_ok=True)
                self.state.chmod(0o600)
                self.state.write_bytes(original)
        link = self.base / "link.launches"
        link.symlink_to(self.state)
        self.refused("builder", "launch record", relaunch=True, state=link)
        shared = self.base / "shared"
        shared.mkdir(mode=0o777)
        shared.chmod(0o777)
        self.refused("builder", "launch record must lie", relaunch=True, state=shared / "x.launches")
        self.state.write_text("{not json")  # a fresh launch that cannot be recorded does not run either
        fresh = self.private("fresh")
        self.refused("new", "launch record", assignments={"new": {"path": str(fresh), "intent": "build"}})

    def test_cli_relaunch_needs_the_recorded_fresh_launch(self):
        config = self.base / "assignments.json"
        config.write_text(json.dumps(self.assignments))
        config.chmod(0o600)
        python = os.path.realpath(sys.executable)

        def run(agent, code, *extra):
            done = subprocess.run([sys.executable, "-B", str(ROOT / "hub.py"), "workspace-run", "--assignments",
                                   str(config), "--agent", agent, "--timeout", "20", *extra, "--", python, "-I", "-S",
                                   "-c", code], capture_output=True, text=True, timeout=120, env={**os.environ, "TMPDIR": "/tmp"})
            return done.returncode, json.loads(done.stdout)

        code, report = run("other", "open('authorized_keys', 'a').write('ssh-ed25519 AAAA child\\n')", "--relaunch")
        self.assertEqual((code, report["status"]), (3, "denied"))
        self.assertIn("recorded fresh launch", report["reason"])
        self.assertEqual((self.dot_ssh / "authorized_keys").read_text(), "ssh-ed25519 AAAA operator\n")
        if not FULL:
            self.skipTest("the fresh launch needs the full namespace sandbox")
        self.assertEqual(run("builder", "open('feature.txt', 'w').write('x')")[0], 0)
        self.assertIn("builder", json.loads((self.base / "assignments.json.launches").read_text())["launches"])
        code, report = run("builder", "print(open('feature.txt').read())", "--relaunch")
        self.assertEqual((code, report["stdout"]), (0, "x\n"))


if __name__ == "__main__":
    unittest.main()
