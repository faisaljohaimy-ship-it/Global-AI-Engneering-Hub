"""pr30-isolation recheck item 1: what a strict run mounts for a program outside the system directories.

Before: the whole install prefix of cmd[0] (the parent of bin/) was mounted read-only, and a prefix inside the
home directory was accepted, so a strict child started as <prefix>/bin/tool printed a secret planted in
<prefix>/share/keyrings/ (SP/work/recheck-isolation/poc/f4_variants.py) and /root/.cargo/bin/cargo mounted
/root/.cargo. Now a strict run mounts, for cmd[0] and for the hub's own interpreter (pid 1), only the bin
directory, a Python interpreter's standard library and the shared libraries named by the ELF interpreter,
DT_RPATH and DT_RUNPATH (parsed as data, never run). A program under a home directory or in a directory a
non-root user can change is refused unless it is the hub's own interpreter (GitHub runners keep their Python in
/opt/hostedtoolcache, which the runner user owns). pid 1 reads the resulting mount table back from
/proc/self/mountinfo and the result carries it as "mounts".
"""

import json
import os
import pathlib
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import governor
from engineering_os.governor import GovernorDenied

FULL = governor.isolation_probe()["tier"] == "full"
STRICT_VISIBLE = tuple(d for d in governor.SYSTEM_DIRS if d != "/etc")


def elf(path, *, needed=(), runpath=None, rpath=None, interp=None, shared=False):
    """Write a minimal little-endian ELF64 file (headers only: it is parsed, never run)."""
    strings, offsets = bytearray(b"\0"), {}
    for text in (*needed, runpath, rpath):
        if text is not None and text not in offsets:
            offsets[text] = len(strings)
            strings += text.encode() + b"\0"
    base, phnum = 0x400000, 3
    interp_at = 64 + 56 * phnum
    blob = (interp.encode() + b"\0") if interp else b""
    strtab_at = interp_at + len(blob)
    dynamic_at = (strtab_at + len(strings) + 7) // 8 * 8
    entries = [(1, offsets[name]) for name in needed]
    entries += [(29, offsets[runpath])] if runpath is not None else []
    entries += [(15, offsets[rpath])] if rpath is not None else []
    entries += [(5, base + strtab_at), (0, 0)]
    dynamic = b"".join(struct.pack("<qQ", tag, value) for tag, value in entries)
    total = dynamic_at + len(dynamic)
    header = struct.pack("<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01" + bytes(9), 3 if shared else 2, 62, 1, 0, 64, 0,
                         0, 64, 56, phnum, 64, 0, 0)
    phdrs = struct.pack("<IIQQQQQQ", 1, 5, 0, base, base, total, total, 0x1000)
    phdrs += struct.pack("<IIQQQQQQ", 3 if interp else 4, 4, interp_at, base + interp_at, base + interp_at,
                         len(blob), len(blob), 1)
    phdrs += struct.pack("<IIQQQQQQ", 2, 6, dynamic_at, base + dynamic_at, base + dynamic_at, len(dynamic),
                         len(dynamic), 8)
    data = header + phdrs + blob + bytes(strings)
    path.write_bytes(data + bytes(dynamic_at - len(data)) + dynamic)
    path.chmod(0o755)
    return path


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-mnt-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.workspace = self.base / "ws"
        self.workspace.mkdir(mode=0o700)

    def toolcache(self, name="toolcache"):
        """A Python laid out like /opt/hostedtoolcache/Python/<v>/x64: shared libpython, RUNPATH $ORIGIN/../lib,
        with a secret planted in share/ and in etc/."""
        prefix = self.base / name
        for part in ("bin", "lib/python3.12/lib-dynload", "share/keyrings", "etc", "include"):
            (prefix / part).mkdir(parents=True)
        (prefix / "lib/python3.12/os.py").write_text("")
        (prefix / "share/keyrings/login.keyring").write_text("PLANTED-SHARE-SECRET\n")
        (prefix / "etc/credentials").write_text("PLANTED-ETC-SECRET\n")
        elf(prefix / "lib/libpython3.12.so.1.0", needed=["libc.so.6"], shared=True)
        elf(prefix / "lib/libextra.so.1.2", shared=True)
        (prefix / "lib/libextra.so.1").symlink_to("libextra.so.1.2")
        exe = elf(prefix / "bin/python3.12", needed=["libpython3.12.so.1.0", "libextra.so.1", "libc.so.6"],
                  runpath="$LIB/never:$ORIGIN/../lib", interp="/lib64/ld-linux-x86-64.so.2")
        return prefix, exe

    def assert_no_secret_paths(self, mounts, prefix):
        for pair in mounts:
            for path in pair:
                self.assertNotEqual(path, str(prefix))
                for hidden in ("share", "etc", "include"):
                    self.assertFalse(governor._is_inside(path, str(prefix / hidden)), path)


class ElfTests(Fixture):
    def test_links_are_read_from_the_headers(self):
        _, exe = self.toolcache()
        self.assertEqual(governor._elf_links(str(exe)),
                         ("/lib64/ld-linux-x86-64.so.2", ["libpython3.12.so.1.0", "libextra.so.1", "libc.so.6"], [],
                          ["$LIB/never:$ORIGIN/../lib"]))
        self.assertEqual(governor._search_dirs(["$LIB/x:$ORIGIN/../lib:${ORIGIN}/a:relative"], "/opt/p/bin"),
                         ["/opt/p/lib", "/opt/p/bin/a"])

    def test_a_script_has_no_links_and_a_broken_elf_is_refused(self):
        script = self.base / "script"
        script.write_text("#!/usr/bin/python3\nprint(1)\n")
        self.assertIsNone(governor._elf_links(str(script)))
        self.assertEqual(governor._linked_libraries(str(script)), [])
        _, exe = self.toolcache()
        broken = self.base / "broken"
        broken.write_bytes(exe.read_bytes()[:100])
        with self.assertRaises(GovernorDenied) as caught:
            governor._elf_links(str(broken))
        self.assertEqual(caught.exception.reason, "program-not-visible")

    def test_libraries_resolve_through_runpath_and_links(self):
        prefix, exe = self.toolcache()
        lib = prefix / "lib"
        self.assertEqual(governor._linked_libraries(str(exe)), sorted([
            ("/lib64/ld-linux-x86-64.so.2", os.path.realpath("/lib64/ld-linux-x86-64.so.2")),
            (str(lib / "libextra.so.1"), str(lib / "libextra.so.1.2")),
            (str(lib / "libpython3.12.so.1.0"), str(lib / "libpython3.12.so.1.0"))]))

    def test_a_non_elf_file_named_as_a_library_is_never_mounted(self):
        prefix, exe = self.toolcache()
        (prefix / "lib/libextra.so.1").unlink()
        (prefix / "lib/libextra.so.1").symlink_to("../share/keyrings/login.keyring")
        with self.assertRaisesRegex(GovernorDenied, "not a bounded ELF file"):
            governor._linked_libraries(str(exe))


class PlanTests(Fixture):
    def own(self, exe, prefix):
        return (mock.patch.object(sys, "executable", str(exe)), mock.patch.object(sys, "base_prefix", str(prefix)),
                mock.patch.object(sys, "base_exec_prefix", str(prefix)),
                mock.patch.object(governor.sysconfig, "get_path", lambda name: str(prefix / "lib/python3.12")))

    def test_the_hubs_toolcache_interpreter_gets_bin_stdlib_and_libraries_only(self):
        prefix, exe = self.toolcache()
        patches = self.own(exe, prefix)
        with patches[0], patches[1], patches[2], patches[3]:
            real, mounts = governor._strict_program("sh", "/usr/bin:/bin", "/", STRICT_VISIBLE)
        lib = prefix / "lib"
        self.assertEqual(mounts, sorted([(str(prefix / "bin"),) * 2, (str(lib / "python3.12"),) * 2,
                                         (str(lib / "libpython3.12.so.1.0"),) * 2,
                                         (str(lib / "libextra.so.1"), str(lib / "libextra.so.1.2"))]))
        self.assert_no_secret_paths(mounts, prefix)
        self.assertTrue(governor._is_inside(real, "/usr") or governor._is_inside(real, "/bin"))

    def test_the_hubs_interpreter_is_exempt_but_another_program_there_is_refused(self):
        prefix, exe = self.toolcache()  # under /tmp: world-writable above it
        with self.assertRaisesRegex(GovernorDenied, "non-root user can change"):
            governor._program_mounts(str(exe), STRICT_VISIBLE)
        with mock.patch.object(governor, "_foreign_writer", return_value=None):
            mounts = governor._program_mounts(str(exe), STRICT_VISIBLE)
        lib = prefix / "lib"
        self.assertEqual(mounts, [(str(prefix / "bin"),) * 2, (str(lib / "python3.12"),) * 2,
                                  (str(lib / "libextra.so.1"), str(lib / "libextra.so.1.2")),
                                  (str(lib / "libpython3.12.so.1.0"),) * 2])
        self.assert_no_secret_paths(mounts, prefix)

    def test_a_program_outside_a_bin_directory_is_mounted_alone(self):
        tool = self.base / "opt-tool" / "tool"
        tool.parent.mkdir()
        shutil.copy2(os.path.realpath("/bin/sh"), tool)
        (tool.parent / "secret.txt").write_text("PLANTED")
        with mock.patch.object(governor, "_foreign_writer", return_value=None):
            mounts = governor._program_mounts(str(tool), STRICT_VISIBLE)
        self.assertIn((str(tool), str(tool)), mounts)
        self.assertNotIn(str(tool.parent), [target for target, _ in mounts])

    def test_a_home_directory_prefix_is_refused(self):
        home = self.base / "home-of-someone"
        tool = home / ".local" / "bin" / "tool"
        tool.parent.mkdir(parents=True)
        shutil.copy2(os.path.realpath("/bin/sh"), tool)
        with mock.patch.dict(os.environ, {"HOME": str(home)}), \
                mock.patch.object(governor, "_foreign_writer", return_value=None):  # the home rule alone refuses it
            self.assertIn(str(home), governor._home_roots())
            with self.assertRaisesRegex(GovernorDenied, "under a home directory"):
                governor._strict_program(str(tool), "/usr/bin:/bin", "/", STRICT_VISIBLE)
            with self.assertRaisesRegex(GovernorDenied, "home directory|too broad"):
                governor._mountable_prefix(str(home / ".local"))
            self.assertEqual(governor._exec_prefix(str(tool), "/usr/bin:/bin", "/", []), [])  # legacy: not mounted
        for path in ("/root/.cargo", "/root/.local", "/home/user/.local"):
            with self.subTest(path=path), self.assertRaisesRegex(GovernorDenied, "under a home directory"):
                governor._trusted_source(path)

    def test_home_roots_and_foreign_writers(self):
        roots = governor._home_roots()
        self.assertLessEqual({"/root", "/home", os.path.realpath(os.path.expanduser("~"))}, set(roots))
        self.assertNotIn("/", roots)
        self.assertFalse(any(governor._is_inside(root, tree) for root in roots for tree in governor.SYSTEM_DIRS))
        shared = self.base / "shared"
        shared.mkdir(mode=0o777)
        shared.chmod(0o777)
        self.assertEqual(governor._foreign_writer(str(shared)), str(shared))
        chain = ["/", "/usr", "/usr/bin"]
        if all(os.stat(p).st_uid == 0 and not os.stat(p).st_mode & 0o022 for p in chain):
            self.assertIsNone(governor._foreign_writer("/usr/bin"))


@unittest.skipUnless(FULL, "needs the full namespace sandbox")
class LiveTests(Fixture):
    def strict(self, cmd):
        return governor.sandbox_run(cmd, cwd=self.workspace, timeout=20, allowed_paths=[self.workspace],
                                    require_fs_isolation=True)

    def test_secrets_planted_under_share_and_etc_of_the_prefix_stay_hidden(self):
        prefix = self.base / "tool"
        for part in ("bin", "share/keyrings", "etc", "include"):
            (prefix / part).mkdir(parents=True)
        shutil.copy2(os.path.realpath("/bin/sh"), prefix / "bin" / "tool")
        (prefix / "share/keyrings/login.keyring").write_text("PLANTED-SHARE-SECRET\n")
        (prefix / "etc/credentials").write_text("PLANTED-ETC-SECRET\n")
        script = (f"cat {prefix}/share/keyrings/login.keyring; cat {prefix}/etc/credentials; "
                  f"echo listing; ls {prefix}; ls {prefix.parent}")
        with mock.patch.object(governor, "_foreign_writer", return_value=None):  # host-side planning trusts it
            ran = self.strict([str(prefix / "bin" / "tool"), "-c", script])
        self.assertNotIn("PLANTED", ran["stdout"] + ran["stderr"])
        self.assertEqual(ran["stdout"].split("listing\n", 1)[1].split(), ["bin", "tool", "ws"])  # prefix, then its parent
        shown = [row[0] for row in ran["mounts"]["mounts"]]
        self.assertIn(str(prefix / "bin"), shown)
        self.assertFalse([path for path in shown if path in (str(prefix), str(prefix / "share"), str(prefix / "etc"))])
        with self.assertRaisesRegex(GovernorDenied, "non-root user can change"):  # unmocked: /tmp is world-writable
            self.strict([str(prefix / "bin" / "tool"), "-c", script])

    def test_a_home_directory_program_is_refused_before_launch(self):
        home = self.base / "home-of-someone"
        tool = home / ".local" / "bin" / "tool"
        tool.parent.mkdir(parents=True)
        shutil.copy2(os.path.realpath("/bin/sh"), tool)
        (home / ".local" / "share").mkdir()
        (home / ".local" / "share" / "token").write_text("PLANTED")
        with mock.patch.dict(os.environ, {"HOME": str(home)}), \
                mock.patch.object(governor, "_foreign_writer", return_value=None), \
                self.assertRaises(GovernorDenied) as caught:
            self.strict([str(tool), "-c", f"cat {home}/.local/share/token"])
        self.assertEqual(caught.exception.reason, "program-not-visible")
        self.assertIn("home directory", str(caught.exception))

    def test_the_result_reports_the_mount_table(self):
        ran = self.strict(["/bin/sh", "-c", "true"])
        table = ran["mounts"]
        rows = {row[0]: row for row in table["mounts"]}
        self.assertEqual(rows[str(self.workspace)][3], "rw")
        self.assertEqual(rows["/usr"][3], "ro")
        self.assertEqual(rows["/"][2:], ["tmpfs", "ro"])
        self.assertNotIn("/etc", rows)  # strict hides /etc
        self.assertEqual([path for path, row in rows.items() if row[3] == "rw" and row[2] != "tmpfs"],
                         [str(self.workspace)])
        legacy = governor.sandbox_run(["/bin/sh", "-c", "true"], cwd=self.workspace, timeout=20,
                                      allowed_paths=[self.workspace])
        self.assertIn("/etc", {row[0] for row in legacy["mounts"]["mounts"]})

    def test_node_outside_the_system_directories_shows_only_its_bin_directory(self):
        node = shutil.which("node", path=governor._cage().ENV["PATH"])
        real = os.path.realpath(node) if node else ""
        if not node or any(governor._is_inside(real, d) for d in governor.SYSTEM_DIRS):
            self.skipTest("no node outside the system directories on the sandbox PATH")
        try:
            governor._trusted_source(real)
        except GovernorDenied:
            self.skipTest("node lies in a directory this host does not trust")
        prefix = os.path.dirname(os.path.dirname(real))
        ran = self.strict(["node", "-e", "const fs = require('fs');"
                           "console.log(JSON.stringify([fs.readdirSync(process.argv[1]), fs.existsSync(process.argv[1] + '/share')]))",
                           prefix])
        self.assertEqual(json.loads(ran["stdout"]), [["bin"], False], ran["stderr"])

    def test_system_compilers_still_run(self):
        if not shutil.which("cc", path=governor._cage().ENV["PATH"]):
            self.skipTest("no cc")
        ran = self.strict(["cc", "--version"])
        self.assertEqual(ran["returncode"], 0, ran["stderr"])

    def test_known_limitation_only_cmd0_is_resolved_on_the_host(self):
        """Recheck item 4, an honest record: links through the hidden /etc dangle for what the child starts."""
        report = " ".join(governor.isolation_report()["not_enforced"])
        self.assertIn("strict runs resolve only cmd[0] on the host", report)
        python = "/usr/bin/python3"
        if not os.path.islink(python) or not os.readlink(python).startswith("/etc/"):
            self.skipTest("/usr/bin/python3 is not an /etc/alternatives link on this host")
        direct = self.strict([python, "-I", "-S", "-c", "print('direct')"])
        self.assertEqual(direct["stdout"], "direct\n", direct["stderr"])
        script = self.workspace / "tool.py"
        script.write_text("#!/usr/bin/python3\nprint('script')\n")
        script.chmod(0o700)
        indirect = self.strict(["/bin/sh", "-c", "/usr/bin/python3 -c 'print(1)'; ./tool.py; echo rc=$?"])
        self.assertIn("not found", indirect["stderr"])
        self.assertTrue(indirect["stdout"].endswith("rc=127\n"), indirect)

    def test_the_report_records_the_strict_mount_table_without_private_paths(self):
        report = governor.isolation_report()
        probe = next(p for p in report["probes"] if p["name"].startswith("strict run mount table"))
        self.assertEqual(probe["result"]["returncode"], 0)
        self.assertIn(["<workspace>", "<workspace>"], [row[:2] for row in probe["result"]["mounts"]])
        self.assertNotIn("/etc", [row[0] for row in probe["result"]["mounts"]])
        text = json.dumps(report)
        for private in ("/root", "/home/", "/tmp/", "gaie-governor-mounts"):
            self.assertNotIn(private, text)
        self.assertTrue(report["enforced"]["strict_mounts_only_bin_stdlib_and_linked_libraries"])
        self.assertIn("share/, etc/, include/", " ".join(report["not_enforced"]))


if __name__ == "__main__":
    unittest.main()
