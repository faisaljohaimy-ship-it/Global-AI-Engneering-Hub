#!/usr/bin/env python3
"""Measured isolation evidence: docs/evidence/gaie-20-layers/isolation.json.

    python3 scripts/isolation_evidence.py --out docs/evidence/gaie-20-layers/isolation.json
    python3 scripts/isolation_evidence.py --require-full      # exit 2 unless the full tier is built
    python3 scripts/isolation_evidence.py --check FILE        # exit 1 when FILE's sources are stale

The file is governor.isolation_report() (the base namespace probe, unchanged) plus one more
probe: the isolation property matrix. Every launcher that runs code on behalf of GAIE runs one
fixed probe program as a REAL child on this host; each property is recorded as

    enforced       the attempt was made inside and failed (and the host side saw nothing)
    not-enforced   the attempt succeeded (an explicit, recorded mode without that wall)
    refused        the launcher refused to run anything (nothing executed)
    not-available  this host cannot even attempt it (for example no IPv6 in the kernel)

The refusal rows force the governor's probe to the plain tier inside this process, which is
how a host without user namespaces is seen; that is stated in each row. The evidence is a
measurement of the host named in "host", not a claim about every host. `sources` binds the
file to the exact code measured (function-level digests); tests/test_isolation_enforcement.py
fails when that code changes and the file is not regenerated.
Standard library only. SPDX-License-Identifier: MIT
"""
import argparse
import ast
import contextlib
import hashlib
import json
import os
import pathlib
import shutil
import socket
import sys
import tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import detectors, governor, layers  # noqa: E402

STATUSES = ("enforced", "not-enforced", "refused", "not-available")
ENV_NAME = "GAIE_ISOLATION_PLANTED"
PROPERTIES = (
    "write_outside_workspace", "read_outside_file", "read_etc_passwd", "read_caller_home",
    "ambient_environment_variable", "af_inet_host_loopback", "af_inet_host_address", "af_inet6_host_loopback",
    "af_unix_outside", "git_pointer_write", "host_pid_visible", "capabilities", "child_process_contained",
    "descendant_outlives_run",
)
# Function-level sources: an edit elsewhere in these modules does not make the evidence stale.
SOURCES = {
    "engineering_os/governor.py": ("sandbox_run", "_run_full", "_run_plain", "_launch", "_environment",
                                   "_strict_paths", "_inspect_scope", "_exec_prefix", "_disable_socket_creation",
                                   "_loopback_up", "_sandbox_init", "isolation_probe", "_probe_sandbox",
                                   "isolation_report"),
    "engineering_os/detectors.py": ("DRIVER", "Sandbox", "_interpreter", "_tail", "_output_limit", "_sweep", "_stop"),
    "engineering_os/layers.py": ("_python", "_outside_system", "_workspace", "_git_metadata", "_scrubbed_env",
                                 "_profile", "_run"),
}

# The probe: one function per property, each returning (held: bool, observed: str).
PROBE = r'''
import ctypes, json, os, socket, subprocess, sys, time
C = json.loads(sys.argv[1])

def attempt(fn):
    try:
        return "ok:" + str(fn())[:60]
    except BaseException as exc:
        return type(exc).__name__ + ":" + str(getattr(exc, "errno", "") or "")

def raw_connect(family, address):
    import _socket
    sock = _socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(2)
        _socket.socket.connect(sock, address)  # the C method: no Python guard in the way
        return "connected"
    finally:
        sock.close()

def write_outside():
    seen = attempt(lambda: open(os.path.join(C["outside"], "escaped.txt"), "w").write("x"))
    return not seen.startswith("ok"), seen

def read_outside():
    seen = attempt(lambda: open(C["marker"]).read())
    return not seen.startswith("ok"), seen

def read_etc_passwd():
    seen = attempt(lambda: len(open("/etc/passwd").read()))
    return not seen.startswith("ok"), seen

def read_caller_home():
    if not C["home_entry"]:
        return None, "no caller HOME entry to look for"
    seen = attempt(lambda: os.stat(C["home_entry"]).st_mode)
    return not seen.startswith("ok"), seen

def ambient_env():
    leaked = C["env_name"] in os.environ or any(C["env_value"] in value for value in os.environ.values())
    return not leaked, "visible" if leaked else "absent; names: " + ",".join(sorted(os.environ))[:120]

def inet(address, port):
    seen = attempt(lambda: raw_connect(socket.AF_INET, (address, port)))
    return not seen.startswith("ok"), seen

def inet6():
    if not C["ipv6_port"]:
        return None, "host has no IPv6"
    seen = attempt(lambda: raw_connect(socket.AF_INET6, ("::1", C["ipv6_port"])))
    return not seen.startswith("ok"), seen

def unix_outside():
    def go():
        sock = socket.socket(socket.AF_UNIX)
        try:
            sock.connect(C["unix"])
            return "connected"
        finally:
            sock.close()
    seen = attempt(go)
    return not seen.startswith("ok"), seen

def git_pointer():
    if not C["git_pointer"]:
        return None, "no .git pointer in this launcher's writable scope"
    seen = attempt(lambda: open(C["git_pointer"], "a").write("x"))
    return not seen.startswith("ok"), seen

def host_pid():
    seen = attempt(lambda: os.kill(C["host_pid"], 0))
    return not seen.startswith("ok"), seen

def capabilities():
    eff = [line.split()[1] for line in open("/proc/self/status") if line.startswith("CapEff")][0]
    return eff == "0000000000000000", "CapEff " + eff + " euid " + str(os.geteuid())

def child():
    done = subprocess.run([sys.executable, "-I", "-S", "-c", "open(%r).read()" % C["marker"]],
                          capture_output=True, text=True, timeout=20)
    return done.returncode != 0, "child exit %d" % done.returncode

def descendant():
    subprocess.Popen(["sleep", "30", C["sleeper"]], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None, "started; checked from the host after the run"

CHECKS = {"write_outside_workspace": write_outside, "read_outside_file": read_outside, "read_etc_passwd": read_etc_passwd,
          "read_caller_home": read_caller_home, "ambient_environment_variable": ambient_env,
          "af_inet_host_loopback": lambda: inet("127.0.0.1", C["v4_port"]),
          "af_inet_host_address": (lambda: inet(C["host_address"], C["v4_port"])) if C["host_address"] else (lambda: (None, "no host address")),
          "af_inet6_host_loopback": inet6, "af_unix_outside": unix_outside, "git_pointer_write": git_pointer,
          "host_pid_visible": host_pid, "capabilities": capabilities, "child_process_contained": child,
          "descendant_outlives_run": descendant}

def run_all():
    out = {}
    for name, fn in CHECKS.items():
        try:
            out[name] = list(fn())
        except BaseException as exc:
            out[name] = [None, "probe error " + type(exc).__name__]
    return out
'''
SCRIPT = PROBE + '\nprint("ISOLATION-PROBE " + json.dumps(run_all(), sort_keys=True))\n'
TARGET_TEST = PROBE + '''
import unittest
RESULT = {}

class Walls(unittest.TestCase):
    pass

def _make(name):
    def test(self):
        held, seen = CHECKS[name]()
        if held is None:
            self.skipTest(seen)
        self.assertTrue(held, "OBSERVED " + seen)
    return test

for _name in CHECKS:
    setattr(Walls, "test_" + _name, _make(_name))
'''


def _source_digest(rel, names):
    """SHA-256 over the source text of the named top-level definitions, read from the file (AST)."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    found = {}
    for node in ast.parse(text).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found[node.name] = ast.get_source_segment(text, node)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            found[node.targets[0].id] = ast.get_source_segment(text, node)
    missing = [name for name in names if name not in found]
    if missing:
        raise KeyError(f"{rel}: measured definitions missing: {', '.join(missing)}")
    return hashlib.sha256("\0".join(found[name] for name in names).encode("utf-8")).hexdigest()


def sources():
    """SHA-256 of the generator itself and of the exact functions it measures."""
    found = {"scripts/isolation_evidence.py": hashlib.sha256((ROOT / "scripts/isolation_evidence.py").read_bytes()).hexdigest()}
    for rel, names in SOURCES.items():
        found[rel + ":" + ",".join(names)] = _source_digest(rel, names)
    return found


def host_address():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))  # selects a source address; sends nothing
        except OSError:
            return None
        address = probe.getsockname()[0]
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def _home_entry(exclude):
    """One existing entry of the caller's HOME that is no ancestor of the measured paths."""
    home = pathlib.Path(os.path.expanduser("~"))
    try:
        names = sorted(os.listdir(home))
    except OSError:
        return None
    for name in names:
        path = home / name
        if not any(str(other) == str(path) or str(other).startswith(str(path) + os.sep) for other in exclude):
            return str(path)
    return None


class Fixture:
    """Host side of one measurement: planted marker, listeners, a unix socket, a sleeper tag."""

    def __init__(self, base):
        self.base = pathlib.Path(base)
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.marker = self.outside / "marker.txt"
        self.marker.write_text("host-only")
        self.v4 = socket.socket()
        self.v4.bind(("0.0.0.0", 0))
        self.v4.listen(8)
        self.v4.setblocking(False)
        self.v6 = None
        if socket.has_ipv6:
            with contextlib.suppress(OSError):
                self.v6 = socket.socket(socket.AF_INET6)
                self.v6.bind(("::1", 0))
                self.v6.listen(8)
                self.v6.setblocking(False)
        if self.v6 is not None and self.v6.fileno() < 0:
            self.v6 = None
        self.unix_path = self.outside / "control.sock"
        self.unix = socket.socket(socket.AF_UNIX)
        self.unix.bind(str(self.unix_path))
        self.unix.listen(8)
        self.unix.setblocking(False)
        self.value = "planted-" + hashlib.sha256(os.urandom(16)).hexdigest()[:24]
        self.sleeper = "gaie-isolation-sleeper-" + hashlib.sha256(os.urandom(8)).hexdigest()[:12]

    def config(self, git_pointer=None):
        return {"outside": str(self.outside), "marker": str(self.marker), "home_entry": _home_entry([self.base, ROOT]),
                "env_name": ENV_NAME, "env_value": self.value, "v4_port": self.v4.getsockname()[1],
                "host_address": host_address(), "ipv6_port": self.v6.getsockname()[1] if self.v6 else None,
                "unix": str(self.unix_path), "git_pointer": git_pointer, "host_pid": os.getpid(), "sleeper": self.sleeper}

    def contacted(self):
        seen = []
        for name, sock in (("v4", self.v4), ("v6", self.v6), ("unix", self.unix)):
            if sock is None:
                continue
            try:
                peer, _ = sock.accept()
                peer.close()
                seen.append(name)
            except (BlockingIOError, OSError):
                pass
        return seen

    def survivors(self):
        found = []
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                with contextlib.suppress(OSError):
                    if self.sleeper.encode() in pathlib.Path(f"/proc/{entry}/cmdline").read_bytes():
                        found.append(int(entry))
        return found

    def cleanup(self):
        for pid in self.survivors():
            with contextlib.suppress(OSError):
                os.kill(pid, 9)
        for sock in (self.v4, self.v6, self.unix):
            if sock is not None:
                sock.close()


def _status(held, host_ok=True):
    if held is None:
        return "not-available"
    return "enforced" if held and host_ok else "not-enforced"


def _matrix(observed, fixture, contacted, survivors):
    rows = {}
    for name in PROPERTIES:
        held, seen = observed.get(name, [None, "not measured"])
        host_ok = True
        if name == "write_outside_workspace":
            host_ok = not (fixture.outside / "escaped.txt").exists()
            seen += "; host sees escaped.txt: %s" % (not host_ok)
        if name in ("af_inet_host_loopback", "af_inet_host_address"):
            host_ok = "v4" not in contacted
        if name == "af_inet6_host_loopback":
            host_ok = "v6" not in contacted
        if name == "af_unix_outside":
            host_ok = "unix" not in contacted
        if name == "descendant_outlives_run":
            held, seen = not survivors, "host sees %d survivor(s) after the run" % len(survivors)
        rows[name] = {"status": _status(held, host_ok), "observed": seen.replace(str(fixture.base), "<tmp>")}
    return rows


def _scrub(text, fixture):
    home = os.path.expanduser("~")
    return text.replace(str(fixture.base), "<tmp>").replace(home, "<home>")


def _governor_launcher(fixture, strict):
    work = fixture.base / ("strict-ws" if strict else "loop-ws")
    work.mkdir(mode=0o700)
    pointer = work / ".git"
    pointer.write_text("gitdir: /isolation-fixture\n")
    config = fixture.config(git_pointer=str(pointer))
    argv = [os.path.realpath(sys.executable), "-I", "-S", "-c", SCRIPT, json.dumps(config)]
    with mock.patch.dict(os.environ, {ENV_NAME: fixture.value}):
        run = governor.sandbox_run(argv, cwd=str(work), timeout=60, allowed_paths=[str(work)],
                                   require_fs_isolation=strict, loopback=not strict)
    line = [row for row in run["stdout"].splitlines() if row.startswith("ISOLATION-PROBE ")]
    observed = json.loads(line[-1][len("ISOLATION-PROBE "):]) if line else {}
    return observed, {"fs_isolated": run["fs_isolated"], "network_isolated": run["network_isolated"]}


def _layers_launcher(fixture, profile):
    scratch = fixture.base / ("layers-" + profile)
    scratch.mkdir(mode=0o700)
    work = layers._workspace(scratch, "probe")
    config = fixture.config()
    with mock.patch.dict(os.environ, {ENV_NAME: fixture.value}):
        _, output, _, _, isolation = layers._run([layers._python(), "-I", "-S", "-c", SCRIPT, json.dumps(config)],
                                                 root=ROOT, timeout=60, workspace=work, profile=profile,
                                                 reason="measurement" if profile == "process-only" else None)
    line = [row for row in output.splitlines() if row.startswith("ISOLATION-PROBE ")]
    return (json.loads(line[-1][len("ISOLATION-PROBE "):]) if line else {}), isolation


def _detectors_launcher(fixture, isolation):
    target = fixture.base / ("target-" + isolation)
    (target / "suite").mkdir(parents=True)
    (target / ".git").write_text("gitdir: /isolation-fixture\n")
    config = fixture.config(git_pointer=str(target / ".git"))
    (target / "suite" / "case_walls.py").write_text(
        TARGET_TEST.replace("json.loads(sys.argv[1])", "json.loads(%r)" % json.dumps(config)), encoding="utf-8")
    box = detectors.Sandbox(fixture.base / ("box-" + isolation), timeout=120, isolation=isolation)
    with mock.patch.dict(os.environ, {ENV_NAME: fixture.value}):
        result = box.run_tests(target, "suite", "case_*.py")
    observed = {}
    for name in PROPERTIES:
        test = "case_walls.Walls.test_" + name
        outcome = result.get("tests", {}).get(test)
        message = result.get("details", {}).get(test, {}).get("message", "")
        if outcome == "passed":
            observed[name] = [True, "held inside the target test"]
        elif outcome == "skipped":
            observed[name] = [None, "not applicable here"]
        elif outcome:
            observed[name] = [False, message.split("OBSERVED ", 1)[-1][:120]]
    return observed, {"status": result["status"], "isolation": result.get("isolation")}


def _refusals(fixture):
    """The launchers on a host without the full tier (probe forced to plain in this process)."""
    plain = {"tier": "plain", "root_netns": False, "userns_netns": False, "unshare": True,
             "root": os.geteuid() == 0, "full_checks": None}
    rows = {}
    work = fixture.base / "plain-ws"
    work.mkdir(mode=0o700)
    flag = work / "ran.txt"
    with mock.patch.object(governor, "isolation_probe", return_value=plain):
        for name, kwargs in (("governor.sandbox_run strict", {"require_fs_isolation": True}),
                             ("governor.sandbox_run loopback", {"loopback": True})):
            try:
                governor.sandbox_run(["sh", "-c", "echo ran > " + str(flag)], cwd=str(work), timeout=10,
                                     allowed_paths=[str(work)], **kwargs)
                rows[name] = {"status": "not-enforced", "observed": "ran on the plain tier"}
            except governor.GovernorDenied as exc:
                rows[name] = {"status": "refused", "observed": exc.reason}
        target = fixture.base / "plain-target"
        (target / "suite").mkdir(parents=True)
        (target / "suite" / "case_flag.py").write_text(
            "import unittest\nclass F(unittest.TestCase):\n    def test_flag(self):\n        open(%r, 'w').write('ran')\n" % str(flag))
        result = detectors.Sandbox(fixture.base / "plain-box").run_tests(target, "suite", "case_*.py")
        rows["detectors.Sandbox (default os)"] = {"status": "refused" if result["status"] == "refused" else "not-enforced",
                                                  "observed": result.get("reason", result["status"])}
        scratch = fixture.base / "plain-layers"
        scratch.mkdir(mode=0o700)
        _, _, _, _, isolation = layers._run(["true"], root=ROOT, timeout=10, workspace=layers._workspace(scratch, "x"))
        rows["layers._run (verify)"] = {"status": "not-enforced", "observed": "runs as %s with the scrubbed environment; "
                                        "recorded: %s" % (isolation["profile"], isolation["reason"])}
    for row in rows.values():
        row["observed"] = _scrub(row["observed"], fixture)
    rows["nothing executed by a refusing launcher"] = {"status": "enforced" if not flag.exists() else "not-enforced",
                                                       "observed": "flag file absent" if not flag.exists() else "flag written"}
    return rows


LAUNCHERS = {
    "governor.sandbox_run strict": ("governor sandbox, require_fs_isolation=True (quality-assurance.run-tests, "
                                    "workspace supervisor, layers.verify strict profile)", lambda f: _governor_launcher(f, True)),
    "governor.sandbox_run loopback": ("governor sandbox, loopback=True (non-strict, private loopback, /etc hidden)",
                                      lambda f: _governor_launcher(f, False)),
    "detectors.Sandbox os": ("self-healing and upgrade runs of target tests (default isolation 'os')",
                             lambda f: _detectors_launcher(f, "os")),
    "detectors.Sandbox process-only": ("explicit, audited opt-in without OS isolation (recorded in every result)",
                                       lambda f: _detectors_launcher(f, "process-only")),
    "layers._run strict": ("layers.verify default profile", lambda f: _layers_launcher(f, "strict")),
    "layers._run loopback": ("layers.verify profile for tests that run a local server", lambda f: _layers_launcher(f, "loopback")),
    "layers._run process-only": ("layers.verify exception list and hosts without the full tier",
                                 lambda f: _layers_launcher(f, "process-only")),
}


def measure(names=None):
    """Run every launcher (or `names`) on this host; returns the property matrix block."""
    tier = governor.isolation_probe()["tier"]
    launchers = {}
    for name, (role, run) in LAUNCHERS.items():
        if names is not None and name not in names:
            continue
        base = pathlib.Path(tempfile.mkdtemp(prefix="gaie-iso-", dir="/tmp" if os.path.isdir("/tmp") else None))
        fixture = Fixture(base)
        try:
            if tier != "full" and not name.endswith("process-only"):
                launchers[name] = {"role": role, "ran": False,
                                   "properties": {prop: {"status": "refused" if name.startswith(("governor", "detectors")) else "not-available",
                                                         "observed": f"tier {tier}"} for prop in PROPERTIES}}
                continue
            observed, info = run(fixture)
            launchers[name] = {"role": role, "ran": True, "launch": info,
                               "properties": _matrix(observed, fixture, fixture.contacted(), fixture.survivors())}
        finally:
            fixture.cleanup()
            shutil.rmtree(base, ignore_errors=True)
    base = pathlib.Path(tempfile.mkdtemp(prefix="gaie-iso-", dir="/tmp" if os.path.isdir("/tmp") else None))
    fixture = Fixture(base)
    try:
        refusals = _refusals(fixture) if names is None else {}
    finally:
        fixture.cleanup()
        shutil.rmtree(base, ignore_errors=True)
    return {"statuses": list(STATUSES), "properties": list(PROPERTIES), "launchers": launchers,
            "plain_tier_behaviour": refusals}


def _host_facts():
    def read(path):
        try:
            return pathlib.Path(path).read_text().strip()
        except OSError:
            return None
    return {"uid_is_root": os.geteuid() == 0, "max_user_namespaces": read("/proc/sys/user/max_user_namespaces"),
            "unprivileged_userns_clone": read("/proc/sys/kernel/unprivileged_userns_clone"),
            "apparmor_restrict_unprivileged_userns": read("/proc/sys/kernel/apparmor_restrict_unprivileged_userns"),
            "ipv6": os.path.exists("/proc/net/if_inet6"), "libseccomp": _libseccomp(),
            "measured_here_only": "values hold for this host; other hosts measure their own tier"}


def _libseccomp():
    import ctypes
    try:
        ctypes.CDLL("libseccomp.so.2")
        return True
    except OSError:
        return False


def build():
    report = governor.isolation_report()
    report["tests"] = sorted(set(report["tests"]) | {"tests/test_isolation_enforcement.py"})
    report["host"].update(_host_facts())
    matrix = measure()
    matrix["sources"] = sources()
    report["probes"].append({"name": "isolation property matrix: real children per launcher, checked inside and from the host",
                             "command": "python3 scripts/isolation_evidence.py --out docs/evidence/gaie-20-layers/isolation.json",
                             "result": matrix})
    return report


def stale(path):
    """Sources whose digest differs from the evidence in `path` (empty when current)."""
    document = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    recorded = next((probe["result"].get("sources") for probe in document["probes"]
                     if isinstance(probe.get("result"), dict) and "sources" in probe["result"]), None) or {}
    current = sources()
    return sorted(name for name in set(recorded) | set(current) if recorded.get(name) != current.get(name))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out")
    parser.add_argument("--check")
    parser.add_argument("--require-full", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        changed = stale(args.check)
        print(json.dumps({"stale_sources": changed}, indent=2))
        return 1 if changed else 0
    tier = governor.isolation_probe()["tier"]
    if args.require_full and tier != "full":
        print(json.dumps({"error": "the governor's full sandbox tier is required", "tier": tier}))
        return 2
    text = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.out:
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
