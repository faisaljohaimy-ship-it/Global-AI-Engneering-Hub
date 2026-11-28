"""A cage for running worker-written code: limits, own process group, no network.

Call it from Python:

    import cage
    result = cage.run([sys.executable, "-I", "script.py"], cwd=folder, timeout=20)
    result.returncode, result.stdout, result.stderr   # as subprocess.run gives
    result.limit        # None, or "timeout" or "cpu" (a limit was hit), or "file"
                        # (the file-size signal arrived); a failed allocation or
                        # write shows only as an error in the code's own output
    cage.limit_hit(result)   # the same as result.limit

It is a drop-in for workload.isolated, with these walls, all set in the child:
CPU seconds, address space, size of one written file, open files, no core files,
standard input closed, a process group of its own that is killed whole when the time
is up (and after the run, so no helper stays behind), no network where it can be
built, and an empty environment.

When the caller is root the child also drops to an unprivileged user and group
(nobody) with no extra groups. Then a limit on the number of processes (processes=)
applies to that user, and the code cannot write where the orchestrator can. The
price: that user must be able to read what it runs. A script under a private folder
(for example the root's home) is not readable. Run from a folder it can read, and
let `workspace(files)` make one: it copies the files into a new world-readable folder
with a writable `scratch` subfolder. Call `cage.remove(folder)` when done.
When the caller is not root nothing is dropped and the process limit is not set
(it would count the caller's own processes); the other walls still hold.

Command line: python3 cage.py [--timeout S] COMMAND...   runs the command caged and
prints its output, then the limit that was hit, if any.
"""
import ctypes
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

UNPRIVILEGED = 65534  # "nobody"
CLONE_NEWNET = 0x40000000
ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C"}
_NET = None


def network_wall():
    """True when a network namespace can be made here (checked once, with unshare -n)."""
    global _NET
    if _NET is None:
        try:
            _NET = subprocess.run(["unshare", "-n", "true"], capture_output=True,
                                  timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            _NET = False
    return _NET


def _child(memory_mb, cpu_seconds, file_mb, nofile, processes, drop, net, uid):
    def setup():
        def cap(which, soft, hard=None):
            resource.setrlimit(which, (soft, soft if hard is None else hard))
        cap(resource.RLIMIT_CPU, cpu_seconds, cpu_seconds + 1)  # SIGXCPU, then SIGKILL
        cap(resource.RLIMIT_AS, memory_mb * 1024 * 1024)
        cap(resource.RLIMIT_FSIZE, file_mb * 1024 * 1024)
        cap(resource.RLIMIT_NOFILE, nofile)
        cap(resource.RLIMIT_CORE, 0)
        if drop:
            cap(resource.RLIMIT_NPROC, processes)
        if net:  # needs privilege, so before the drop
            if ctypes.CDLL(None, use_errno=True).unshare(CLONE_NEWNET) != 0:
                raise OSError("cannot unshare network")
        if drop:
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)
    return setup


def run(command, cwd=None, timeout=20, memory_mb=512, cpu_seconds=10,
        file_mb=16, nofile=64, processes=32, uid=UNPRIVILEGED):
    """Run command caged. Returns a subprocess.CompletedProcess with extra
    attributes `limit` (see module doc) and `pgid` (the process group it ran in)."""
    drop = os.geteuid() == 0
    net = network_wall()
    argv = list(command)
    if net and not drop:
        argv = ["unshare", "-n"] + argv  # unprivileged caller: the tool does it
        net = False
    proc = subprocess.Popen(
        argv, cwd=cwd, env=dict(ENV), text=True, errors="replace",
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
        preexec_fn=_child(memory_mb, cpu_seconds, file_mb, nofile, processes,
                          drop, net, uid))
    pgid = proc.pid
    limit = None
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        limit = "timeout"
        _kill(pgid)
        out, err = proc.communicate()
    finally:
        _kill(pgid)  # nothing it started may outlive the run
    code = proc.returncode
    if limit is None and code == -signal.SIGXCPU:
        limit = "cpu"
    elif limit is None and code == -signal.SIGKILL and cpu_seconds:
        limit = "cpu" if _cpu_spent(cpu_seconds) else None
    elif limit is None and code == -signal.SIGXFSZ:
        limit = "file"
    result = subprocess.CompletedProcess(argv, code, out, err)
    result.limit = limit
    result.pgid = pgid
    return result


def _cpu_spent(cpu_seconds):
    """After a SIGKILL: true when the children's CPU time reached the hard limit."""
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime >= cpu_seconds


def _kill(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def limit_hit(result):
    """The limit a result hit: "timeout", "cpu", "file", or None."""
    return getattr(result, "limit", None)


def workspace(files, base=None):
    """Copy files (paths) into a new folder the unprivileged user can read and return it.
    The folder is readable by all, not writable; `scratch` inside it is writable."""
    folder = Path(tempfile.mkdtemp(prefix="cage-", dir=base))
    folder.chmod(0o755)
    for f in files:
        dest = folder / Path(f).name
        shutil.copyfile(f, dest)
        dest.chmod(0o644)
    scratch = folder / "scratch"
    scratch.mkdir()
    if os.geteuid() == 0:
        os.chown(scratch, UNPRIVILEGED, UNPRIVILEGED)
        scratch.chmod(0o755)
    else:
        scratch.chmod(0o777)
    return folder


def remove(folder):
    shutil.rmtree(folder, ignore_errors=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    timeout = 20
    if argv[:1] == ["--timeout"] and len(argv) > 2:
        timeout = float(argv[1])
        argv = argv[2:]
    if not argv:
        print(__doc__)
        return 2
    r = run(argv, timeout=timeout)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.limit:
        print("limit hit: " + r.limit, file=sys.stderr)
    return r.returncode if r.returncode >= 0 else 128 - r.returncode


if __name__ == "__main__":
    sys.exit(main())
