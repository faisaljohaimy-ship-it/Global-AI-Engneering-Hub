"""Tests that each wall of swarm/phase3/cage.py holds."""
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
import cage  # noqa: E402

IS_ROOT = os.geteuid() == 0


def alive(pgid):
    """Live (not zombie) processes in a group; a killed orphan may linger as a zombie
    when the machine's init does not reap, which is not a running process."""
    found = []
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                f = open("/proc/%s/stat" % d).read()
            except OSError:
                continue
            rest = f[f.rindex(")") + 2:].split()
            if rest[0] != "Z" and int(rest[2]) == pgid:
                found.append(d)
    return found


class CageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        os.chmod(cls.base, 0o755)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def script(self, name, body):
        src = self.base / (name + ".py")
        src.write_text(body)
        folder = cage.workspace([src], base=self.base)
        self.addCleanup(cage.remove, folder)
        return folder, [sys.executable, "-I", str(folder / src.name)]

    def test_honest_script(self):
        folder, cmd = self.script("ok", "print('hello', 6*7)\n")
        r = cage.run(cmd, cwd=folder)
        self.assertEqual((r.returncode, r.stdout.strip(), r.limit), (0, "hello 42", None))

    def test_stdin_closed_and_env_empty(self):
        folder, cmd = self.script("io", "import os,sys\nprint(repr(sys.stdin.read()), 'HOME' in os.environ)\n")
        r = cage.run(cmd, cwd=folder)
        self.assertEqual(r.stdout.strip(), "'' False")

    def test_cpu_limit_before_timeout(self):
        folder, cmd = self.script("busy", "while True:\n    pass\n")
        t = time.time()
        r = cage.run(cmd, cwd=folder, timeout=15, cpu_seconds=1)
        self.assertLess(time.time() - t, 8)
        self.assertEqual(r.limit, "cpu")
        self.assertNotEqual(r.returncode, 0)

    def test_timeout_kills_group(self):
        folder, cmd = self.script("sleepy", "import time\ntime.sleep(60)\n")
        r = cage.run(cmd, cwd=folder, timeout=1)
        self.assertEqual(r.limit, "timeout")
        with self.assertRaises(ProcessLookupError):
            os.killpg(r.pgid, 0)

    def test_memory_limit(self):
        folder, cmd = self.script("mem", "try:\n    b = bytearray(2 * 1024**3)\n    print('allocated')\n"
                                  "except MemoryError:\n    print('refused')\n")
        r = cage.run(cmd, cwd=folder, memory_mb=512)
        self.assertEqual(r.stdout.strip(), "refused", r.stderr)

    def test_file_size_limit(self):
        folder, cmd = self.script("big", "import sys\ntry:\n    with open('scratch/big.bin','wb') as f:\n"
                                  "        f.write(b'x' * (3 * 1024**2)); f.flush()\n    print('wrote')\n"
                                  "except OSError as e:\n    print('refused', e.errno)\n")
        r = cage.run(cmd, cwd=folder, file_mb=1)
        self.assertTrue(r.stdout.startswith("refused") or r.limit == "file", (r.stdout, r.stderr))
        self.assertLessEqual(os.path.getsize(folder / "scratch" / "big.bin"), 1024**2)

    @unittest.skipUnless(IS_ROOT, "process limit needs the privilege drop, which needs root")
    def test_fork_loop_contained(self):
        folder, cmd = self.script("fork", "import os, time\nn = 0\nwhile n < 500:\n    try:\n"
                                  "        if os.fork() == 0:\n            time.sleep(30); os._exit(0)\n"
                                  "    except OSError:\n        break\n    n += 1\nprint('forks', n)\n")
        r = cage.run(cmd, cwd=folder, processes=16, timeout=10)
        n = int(r.stdout.split()[-1])
        self.assertLess(n, 20, r.stdout)
        time.sleep(0.2)
        self.assertEqual(alive(r.pgid), [])

    @unittest.skipUnless(IS_ROOT, "writing-elsewhere check needs the privilege drop, which needs root")
    def test_cannot_write_outside(self):
        target = self.base / "orchestrator.txt"
        folder, cmd = self.script("w", "try:\n    open(%r, 'w').write('x')\n    print('wrote')\n"
                                  "except OSError:\n    print('refused')\n" % str(target))
        r = cage.run(cmd, cwd=folder)
        self.assertEqual(r.stdout.strip(), "refused")

    def test_no_network(self):
        if not cage.network_wall():
            self.skipTest("unshare -n does not work on this machine")
        folder, cmd = self.script("net", "import socket\ns = socket.socket()\ns.settimeout(3)\ntry:\n"
                                  "    s.connect(('93.184.216.34', 80)); print('connected')\n"
                                  "except OSError:\n    print('refused')\n")
        r = cage.run(cmd, cwd=folder)
        self.assertEqual(r.stdout.strip(), "refused", r.stderr)


if __name__ == "__main__":
    unittest.main()
