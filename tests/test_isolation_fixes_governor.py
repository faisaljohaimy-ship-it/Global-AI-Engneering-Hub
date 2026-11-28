"""pr30-isolation governor fixes, measured on a real sandbox where the host allows it.

F4: strict mode hides /etc and /opt. The requested program is resolved on the host and its real file is
executed (so /etc/alternatives links cannot dangle), and the install prefixes of that program and of the
sandbox's own interpreter (pid 1 imports C modules such as resource after pivot_root) are mounted
read-only in both tiers. A whole top-level directory such as /opt is never mounted.

F6: a strict child cannot create a nested user namespace (which held a full capability set inside it):
unshare and clone with CLONE_NEWUSER are refused and clone3 reports ENOSYS so libc falls back to clone.

F7: every audit-log ownership check compares with the effective uid, the owner of files the process creates.
"""

import json
import os
import pathlib
import platform
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import governor
from engineering_os.governor import GovernorDenied

FULL = governor.isolation_probe()["tier"] == "full"


class Workspace(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-gov-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.workspace = self.base / "ws"
        self.workspace.mkdir(mode=0o700)

    def strict(self, cmd, **kwargs):
        return governor.sandbox_run(cmd, cwd=self.workspace, timeout=20, allowed_paths=[self.workspace],
                                    require_fs_isolation=True, **kwargs)


class PrefixRuleTests(Workspace):
    def test_broad_prefixes_are_never_mountable(self):
        for path in ("/", "/opt", "/usr", "/tmp", os.path.expanduser("~"), os.path.dirname(os.path.expanduser("~"))):
            with self.subTest(path=path), self.assertRaises(GovernorDenied):
                governor._mountable_prefix(path)
        self.assertEqual(governor._mountable_prefix(str(self.base)), str(self.base))

    def test_interpreter_prefix_outside_system_directories_is_reported_once(self):
        relocated = self.base / "toolcache" / "Python" / "x64"
        (relocated / "bin").mkdir(parents=True)
        executable = relocated / "bin" / "python3"
        executable.write_text("")
        with mock.patch.object(sys, "base_prefix", str(relocated)), \
                mock.patch.object(sys, "base_exec_prefix", str(relocated)), \
                mock.patch.object(sys, "executable", str(executable)):
            self.assertEqual(governor.interpreter_prefixes(), [str(relocated)])
            self.assertEqual(governor.interpreter_prefixes(governor.SYSTEM_DIRS + (str(self.base),)), [])
        with mock.patch.object(sys, "base_prefix", "/usr"), mock.patch.object(sys, "base_exec_prefix", "/usr"), \
                mock.patch.object(sys, "executable", "/usr/bin/python3"):
            self.assertEqual(governor.interpreter_prefixes(), [])
        with mock.patch.object(sys, "base_prefix", "/opt"), mock.patch.object(sys, "base_exec_prefix", "/opt"), \
                mock.patch.object(sys, "executable", "/opt/bin/python3"), self.assertRaises(GovernorDenied):
            governor.interpreter_prefixes()

    def test_strict_program_resolution_refuses_what_it_cannot_show(self):
        visible = governor.SYSTEM_DIRS + (str(self.workspace),)
        with self.assertRaisesRegex(GovernorDenied, "cannot be resolved"):
            governor._strict_program("governor-no-such-program", "/usr/bin:/bin", str(self.workspace), visible)
        data = self.workspace / "data.txt"
        data.write_text("not a program")
        with self.assertRaises(GovernorDenied):
            governor._strict_program("./data.txt", "/usr/bin:/bin", str(self.workspace), visible)
        tool = self.base / "bin" / "tool"
        tool.parent.mkdir()
        tool.write_text("#!/bin/sh\necho tool\n")
        tool.chmod(0o755)
        self.assertEqual(governor._strict_program(str(tool), "/usr/bin:/bin", "/", visible),
                         (str(tool), [str(self.base)]))
        real = os.path.realpath(shutil.which("sh", path="/usr/bin:/bin"))
        self.assertEqual(governor._strict_program("sh", "/usr/bin:/bin", "/", visible), (real, []))


@unittest.skipUnless(FULL, "needs the full namespace sandbox")
class StrictProgramTests(Workspace):
    def test_alternatives_linked_python_runs_and_keeps_its_argv0(self):
        python = "/usr/bin/python3"
        if not os.path.exists(python):
            self.skipTest("no /usr/bin/python3 on this host")
        ran = self.strict([python, "-I", "-S", "-c", "import sys; print(sys.orig_argv[0])"])
        self.assertEqual((ran["returncode"], ran["stdout"]), (0, python + "\n"), ran["stderr"])
        self.assertTrue(ran["fs_isolated"])

    def test_node_installed_outside_system_directories_runs(self):
        node = shutil.which("node", path=governor._cage().ENV["PATH"])
        if node is None:
            self.skipTest("node is not installed on the sandbox PATH")
        ran = self.strict(["node", "-e", "console.log(6*7)"])
        self.assertEqual(ran["stdout"], "42\n", ran["stderr"])
        prefix = governor._install_prefix(os.path.realpath(node))
        listing = self.strict(["node", "-e", "const fs = require('fs'), path = require('path');"
                               "console.log(JSON.stringify(fs.readdirSync(path.dirname(process.argv[1]))))", prefix])
        self.assertEqual(json.loads(listing["stdout"]), [os.path.basename(prefix)], listing["stderr"])

    def test_missing_program_is_refused_before_launch(self):
        with self.assertRaises(GovernorDenied) as caught:
            self.strict(["governor-no-such-program"])
        self.assertEqual(caught.exception.reason, "program-not-visible")

    def test_a_program_prefix_may_not_overlap_the_workspace(self):
        tool = self.base / "bin" / "tool"
        tool.parent.mkdir()
        tool.write_text("#!/bin/sh\necho tool\n")
        tool.chmod(0o755)
        with self.assertRaisesRegex(GovernorDenied, "overlap a program prefix"):
            self.strict([str(tool)])


NESTED = {
    "unshare": "import ctypes;l=ctypes.CDLL(None,use_errno=True);rc=l.unshare(0x10000000);"
               "print('ok' if rc==0 else ctypes.get_errno(),"
               "[x.split()[1] for x in open('/proc/self/status') if x.startswith('CapEff')][0])",
    "clone": "import ctypes,os\nl=ctypes.CDLL(None,use_errno=True);l.syscall.restype=ctypes.c_long\n"
             "rc=l.syscall(56,ctypes.c_ulong(0x10000000|17),0,0,0,0)\nif rc==0: os._exit(0)\n"
             "print('child' if rc>0 else ctypes.get_errno())\nif rc>0: os.waitpid(rc,0)",
    "clone3": "import ctypes;l=ctypes.CDLL(None,use_errno=True);l.syscall.restype=ctypes.c_long;"
              "l.syscall(435,0,0);print(ctypes.get_errno())",
    "fork_exec_thread": "import subprocess,threading;o=[];t=threading.Thread(target=lambda:o.append('thread'));"
                        "t.start();t.join();print(subprocess.run(['sh','-c','echo exec'],capture_output=True,"
                        "text=True).stdout.strip(),o[0])",
}


@unittest.skipUnless(FULL, "needs the full namespace sandbox")
class NestedNamespaceTests(Workspace):
    """Measured on this host before the fix: unshare 'ok 000001ffffffffff', clone 'child', clone3 22 (EINVAL),
    `unshare -U true` exit 0. After: 1 (EPERM) with CapEff 0, 1, 38 (ENOSYS), exit 1."""

    def child(self, code, **kwargs):
        if platform.machine() != "x86_64" and code is not NESTED["unshare"]:
            self.skipTest("raw clone/clone3 numbers in this test are x86_64")
        return self.strict([os.path.realpath(sys.executable), "-I", "-S", "-c", code], **kwargs)

    def test_nested_user_namespaces_are_refused_in_strict_mode(self):
        ran = self.child(NESTED["unshare"])
        self.assertEqual(ran["stdout"].split(), ["1", "0000000000000000"], ran["stderr"])
        self.assertEqual(self.child(NESTED["clone"])["stdout"].strip(), "1")
        self.assertEqual(self.child(NESTED["clone3"])["stdout"].strip(), "38")
        binary = self.strict(["unshare", "-U", "true"])
        self.assertNotEqual(binary["returncode"], 0)
        self.assertIn("Operation not permitted", binary["stderr"])

    def test_fork_exec_and_threads_still_work(self):
        ran = self.child(NESTED["fork_exec_thread"])
        self.assertEqual((ran["returncode"], ran["stdout"].strip()), (0, "exec thread"), ran["stderr"])

    def test_the_remaining_surface_is_stated(self):
        text = " ".join(governor.isolation_report()["not_enforced"])
        self.assertIn("clone with CLONE_NEWUSER", text)
        self.assertIn("legacy calls install no seccomp filter", text)


class AuditOwnerTests(Workspace):
    def test_audit_log_owner_is_compared_with_the_effective_uid(self):
        state = self.base / "state"
        euid = os.geteuid()
        with mock.patch.object(os, "getuid", return_value=euid + 1):  # ruid != euid, e.g. after os.seteuid
            governor.audit(state, {"decision": "deny", "reason": "fixture"})
            governor.audit(state, {"decision": "allow", "reason": "fixture"})
            self.assertEqual(governor.verify_audit(state), 2)
        self.assertEqual((state / governor.AUDIT_FILE).stat().st_uid, euid)
        with mock.patch.object(os, "geteuid", return_value=euid + 1), self.assertRaises(GovernorDenied) as caught:
            governor.audit(state, {"decision": "deny", "reason": "foreign"})  # someone else's log is refused
        self.assertEqual(caught.exception.reason, "audit-failed")
        self.assertEqual(governor.verify_audit(state), 2)
        fd = os.open(state / governor.AUDIT_FILE, os.O_RDONLY)
        try:
            with mock.patch.object(os, "getuid", return_value=euid + 1):
                governor._private_log(fd)
            with mock.patch.object(os, "geteuid", return_value=euid + 1), self.assertRaises(GovernorDenied):
                governor._private_log(fd)
        finally:
            os.close(fd)


if __name__ == "__main__":
    unittest.main()
