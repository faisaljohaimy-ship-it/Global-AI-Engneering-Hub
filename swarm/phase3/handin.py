"""A cage for worker-written code at hand-in: a drop-in for workload.isolated.

What it does, in plain words. Code a worker wrote is run in a fresh workspace that holds
only a copy of what it needs: the folder it runs in (when one is given) and every file
named in the command (outside the Python installation). The copy is what runs, so the
code cannot see the withheld tests beside the task, other tasks or private state by a
relative path, and what it writes is thrown away: nothing is copied back and the
workspace is always removed. The run goes through cage.run (limits, no network, process
group killed whole, and another user when the caller is root).

From Python:

    import handin
    done = handin.isolated([sys.executable, "-I", "solution.py"], cwd=folder, timeout=20)
    previous = handin.install()      # workload.isolated now means handin.isolated
    handin.protect(stage_dir)        # stage folder, .hidden, .kit, .queue: owner only
    handin.selftest()                # list of what got through; [] when all is contained
    handin.walls()                   # per wall: "contained", "escaped" or "not enforced here"

Some walls need the caller to be root (os.geteuid() == 0): the unprivileged user that
cannot read an owner-only folder or write to an original path, and the limit on the
number of processes. When the caller is not root they are reported as "not enforced
here", never as passed. The network wall needs the kernel to allow a network namespace.

Command line: python3 handin.py selftest   prints each wall and what happened.
"""
import os
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]

import cage  # noqa: E402
import workload  # noqa: E402

NOT_ENFORCED = "not enforced here"
PRIVATE = (".hidden", ".kit", ".queue")


def _installation() -> list[Path]:
    roots = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
    roots |= {sysconfig.get_path(k) or "" for k in ("stdlib", "platstdlib", "purelib", "platlib")}
    return [Path(r).resolve() for r in roots if r and r != "/"]


def _in_python(path: Path) -> bool:
    exe = Path(sys.executable).resolve()
    return path == exe or any(path == r or r in path.parents for r in _installation())


def _open_tree(folder: Path) -> None:
    """Make the copy readable by the unprivileged user, and writable inside `work`."""
    root = os.geteuid() == 0
    for base, dirs, files in os.walk(folder):
        for name in dirs + files:
            p = Path(base, name)
            if p.is_symlink():
                continue
            if root:
                os.chown(p, cage.UNPRIVILEGED, cage.UNPRIVILEGED)
            p.chmod(0o755 if p.is_dir() else (p.stat().st_mode | 0o444))
    if root:
        os.chown(folder, cage.UNPRIVILEGED, cage.UNPRIVILEGED)
    folder.chmod(0o755)


def isolated(command, cwd=None, timeout=20) -> subprocess.CompletedProcess:
    """Run worker-written code in a fresh copy of what it needs; see the module doc."""
    command = [str(c) for c in command]
    space = Path(tempfile.mkdtemp(prefix="handin-"))
    try:
        space.chmod(0o755)
        argv = list(command)
        run_cwd = None
        base = Path(cwd).resolve() if cwd is not None else Path.cwd()
        if cwd is not None:
            work = space / "work"
            shutil.copytree(base, work, symlinks=True, ignore_dangling_symlinks=True)
            _open_tree(work)
            run_cwd = work
        for number, arg in enumerate(command):
            if number == 0 or arg.startswith("-") and not os.sep in arg:
                continue
            try:
                p = Path(arg) if os.path.isabs(arg) else base / arg
                if not p.is_file():
                    continue
                p = p.resolve()
            except (OSError, ValueError):
                continue
            if _in_python(p):
                continue
            if cwd is not None and base in p.parents and not os.path.isabs(arg):
                continue  # already inside the copied folder, reached by its relative name
            where = space / "in" / str(number)
            where.mkdir(parents=True)
            shutil.copyfile(p, where / p.name)
            argv[number] = str(where / p.name)
        if (space / "in").exists():
            _open_tree(space / "in")
            (space / "in").chmod(0o555)
        done = cage.run(argv, cwd=run_cwd, timeout=timeout)
        if done.limit == "timeout":
            raise subprocess.TimeoutExpired(command, timeout, done.stdout, done.stderr)
        done.args = command
        return done
    finally:
        _reap()
        cage.remove(space)


def _reap() -> None:
    """As root, end any process the unprivileged user still owns (one that left its group)."""
    if os.geteuid() != 0:
        return
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid == cage.UNPRIVILEGED:
                os.kill(int(entry.name), 9)
        except OSError:
            pass


def install():
    """Make workload.isolated this module's; returns the previous one."""
    previous = workload.isolated
    workload.isolated = isolated
    return previous


def protect(stage_dir) -> list[str]:
    """Owner-only: the stage folder, and `.hidden`, `.kit`, `.queue` inside it, whole.
    Returns the names changed."""
    stage = Path(stage_dir)
    changed = []
    for name in PRIVATE:
        folder = stage / name
        if not folder.is_dir():
            continue
        for base, dirs, files in os.walk(folder):
            for entry in dirs:
                Path(base, entry).chmod(0o700)
            for entry in files:
                Path(base, entry).chmod(0o600)
        folder.chmod(0o700)
        changed.append(name)
    stage.chmod(0o700)
    return [stage.name] + changed


# ---- hostile samples ------------------------------------------------------------------

NEEDS_ROOT = {"private_folder", "write_original", "write_swarm_home", "processes"}


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return state != "Z"
    except (OSError, IndexError):
        return False


def walls(timeout: int = 6) -> dict:
    """Run each hostile sample; map wall name -> "contained", "escaped: why" or
    "not enforced here"."""
    root = os.geteuid() == 0
    out = {}
    top = Path(tempfile.mkdtemp(prefix="handin-self-")).resolve()
    top.chmod(0o755)
    saved_env = {k: os.environ.get(k) for k in ("HANDIN_MARKER", "SWARM_HOME")}
    listener = None
    try:
        secret = f"marker-{os.getpid()}-{time.time_ns()}"
        private = top / "private"
        private.mkdir(mode=0o700)
        (private / "marker.txt").write_text(secret)
        stage = top / "stage"
        (stage / ".hidden").mkdir(parents=True)
        (stage / "t1").mkdir()
        (stage / ".hidden" / "t1.json").write_text(secret)
        home = top / "home"
        (home / "p3").mkdir(parents=True)
        os.environ["HANDIN_MARKER"] = secret
        os.environ["SWARM_HOME"] = str(home)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        sol = stage / "t1" / "solution.py"
        sol.write_text("x = 1\n")
        samples = {
            "private_folder": f"print(open({str(private / 'marker.txt')!r}).read())",
            "hidden_tests": "import os\nprint(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.hidden', 't1.json')).read())",
            "environment": "import os\nprint(os.environ)",
            "write_original": f"open({str(sol)!r}, 'a').write('# changed')\nopen({str(sol) + '.x'!r}, 'w').write('x')\nprint('wrote')",
            "write_swarm_home": f"open({str(home / 'p3' / 'x')!r}, 'w').write('x')\nprint('wrote')",
            "socket": f"import socket\ns = socket.socket()\ns.settimeout(2)\ns.connect(('127.0.0.1', {port}))\nprint('connected')",
            "processes": "import subprocess\nn = 0\nfor _ in range(200):\n    try:\n        subprocess.Popen(['sleep', '4']); n += 1\n    except OSError:\n        break\nprint('started', n)",
            "memory": "b = bytearray(2 * 1024 ** 3)\nfor i in range(0, len(b), 4096):\n    b[i] = 1\nprint('took 2 GB')",
            "process_left": "import subprocess\np = subprocess.Popen(['sleep', '30'], start_new_session=True)\nprint('child', p.pid)",
        }
        for name, source in samples.items():
            if name == "processes" and not root:
                out[name] = NOT_ENFORCED
                continue
            sol_file = top / f"{name}.py"
            sol_file.write_text(source + "\n")
            before = sol.read_text()
            got = None
            try:
                done = isolated([sys.executable, "-I", str(sol_file)], cwd=stage / "t1", timeout=timeout)
                got = done.stdout
            except subprocess.TimeoutExpired:
                got = ""
            bad = None
            if name in ("private_folder", "hidden_tests") and secret in got:
                bad = "read the marker"
            elif name == "environment" and secret in got:
                bad = "saw the marker in the environment"
            elif name == "write_original" and (sol.read_text() != before or Path(str(sol) + ".x").exists()):
                bad = "wrote beside the original"
            elif name == "write_swarm_home" and any((home / "p3").iterdir()):
                bad = "wrote under SWARM_HOME"
            elif name == "socket" and "connected" in got:
                bad = "opened a socket"
            elif name == "processes":
                n = int(got.split()[-1]) if got.startswith("started") else 0
                bad = f"started {n} processes" if n >= 200 else None
            elif name == "memory" and "took" in got:
                bad = "took 2 GB"
            elif name == "process_left":
                pid = int(got.split()[-1]) if got.startswith("child") else 0
                if pid and _alive(pid):
                    bad = "left a process behind"
                    os.kill(pid, 9)
            if bad is None:
                out[name] = "contained"
            elif name in NEEDS_ROOT and not root or name == "socket" and not cage.network_wall():
                out[name] = NOT_ENFORCED
            else:
                out[name] = "escaped: " + bad
        # the time limit
        slow = top / "slow.py"
        slow.write_text("import time\ntime.sleep(60)\n")
        t0 = time.time()
        try:
            isolated([sys.executable, "-I", str(slow)], timeout=2)
            out["time_limit"] = "escaped: ran past the time limit"
        except subprocess.TimeoutExpired:
            out["time_limit"] = "contained" if time.time() - t0 < 10 else "escaped: killed late"
    finally:
        if listener:
            listener.close()
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(top, ignore_errors=True)
    return out


def selftest() -> list[str]:
    """What got through: one line per wall that failed, and one per wall that this caller
    cannot enforce ("not enforced here"). Empty when everything is contained."""
    lines = []
    for name, what in walls().items():
        if what == "contained":
            continue
        lines.append(f"{name}: {what}" + (" (needs root)" if name in NEEDS_ROOT and what == NOT_ENFORCED else ""))
    return lines


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] != ["selftest"]:
        print(__doc__)
        return 2
    print("caller is root:", os.geteuid() == 0)
    result = walls()
    for name, what in result.items():
        print(f"{name}: {what}")
    return 1 if any(w.startswith("escaped") for w in result.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
