"""Security Governor of the 20-layer GAIE OS (layers L01 owner & governance, L09 security).

Deny by default, fail closed. Every refusal raises GovernorDenied with a short,
machine-readable `reason`; nothing is allowed because a text says so.

    check(grant, engine_id, action, action_spec, *, paths=(), approval_token=None, now=None, base=None)
        -> {"allowed": True, "grant_id", "side_effect", "reason"}     (GovernorDenied otherwise)
    check_payload(payload) -> None                                    (GovernorDenied "secret-in-payload")
    audit(state_dir, event, *, now=None) -> None                      (append-only, hash-chained JSONL)
    verify_audit(state_dir) -> int                                    (records; GovernorDenied "audit-tampered")
    sandbox_run(cmd, *, cwd, timeout, network=False, env_allow=(), allowed_paths=(), read_paths=(),
                cpu_seconds=None, memory_mb=1024, file_mb=64, nofile=256,
                require_fs_isolation=False, read_only=False)
        -> {"returncode", "stdout", "stderr", "limit", "network_isolated", "fs_isolated"}
    isolation_probe() -> dict                                          (measured once per process)

Relative paths (grant paths and requested paths) resolve against `base`, which
defaults to the current working directory at call time; a relative grant path
must stay inside that base after realpath. The full threat model, guarantees and
non-guarantees are in docs/specs/gaie-20-layers/SECURITY_GOVERNOR.md.

Standard library only. The sandbox reuses swarm/phase3/cage.py (resource limits,
own process group, the root network probe) through a path loader; nothing of it
is copied here.
"""
import ctypes
import datetime
import errno
import fcntl
import functools
import hashlib
import hmac
import importlib.util
import json
import math
import os
import platform
import pwd
import re
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import sysconfig
import tempfile

from engineering_os import contracts
from scripts.security_scan import secret_findings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAGE_PATH = os.path.join(ROOT, "swarm", "phase3", "cage.py")
AUDIT_FILE = "governor-audit.jsonl"
REASONS = (
    "invalid-grant", "invalid-action-spec", "invalid-time", "grant-expired", "engine-not-granted",
    "action-not-granted", "side-effect-exceeds-grant", "approval-missing", "approval-mismatch",
    "invalid-path", "path-outside-grant", "secret-in-payload", "invalid-payload", "payload-too-large",
    "invalid-audit-event", "audit-in-repository", "audit-failed", "audit-tampered", "invalid-command",
    "invalid-env-name", "invalid-limit", "allowed-path-too-broad", "network-isolation-unavailable",
    "sandbox-setup-failed", "invalid-sandbox-mode", "filesystem-isolation-unavailable",
)
MAX_PAYLOAD_CHARS = 8 * 1024 * 1024
MAX_PAYLOAD_DEPTH = 64
MAX_TOKEN_CHARS = 4096
MAX_TIMEOUT = 86400
_UTC = datetime.timezone.utc
_HEX64 = frozenset("0123456789abcdef")


class GovernorDenied(PermissionError):
    """A request the governor refuses. `reason` is short and machine-readable; `detail` never
    holds a payload, a token or a matched secret value."""

    def __init__(self, reason, detail=""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def _safe(text, limit=200):
    """Text that may go into an error or an audit record: bounded, and never a secret."""
    text = str(text)[:limit]
    return "[redacted]" if secret_findings("detail.txt", text) else text


# ---------------------------------------------------------------- time

def _instant(now):
    if now is None:
        return datetime.datetime.now(_UTC)
    if isinstance(now, datetime.datetime):
        return now.replace(tzinfo=_UTC) if now.tzinfo is None else now.astimezone(_UTC)
    if isinstance(now, str):
        try:
            value = datetime.datetime.fromisoformat(now.replace("Z", "+00:00"))
        except ValueError:
            raise GovernorDenied("invalid-time", "now: ISO-8601 expected") from None
        if value.tzinfo is None:
            raise GovernorDenied("invalid-time", "now: needs a UTC offset")
        return value.astimezone(_UTC)
    if isinstance(now, (int, float)) and not isinstance(now, bool) and math.isfinite(now):
        return datetime.datetime.fromtimestamp(now, _UTC)
    raise GovernorDenied("invalid-time", "now: datetime, ISO-8601 text or epoch seconds")


def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------- check

def approval_token_sha256(token):
    """The digest a grant's approval carries for `token`: SHA-256 of its UTF-8 bytes (hex)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_digests(token):
    # The canonical form, and contracts.sha256(token) (SHA-256 of the JSON-quoted text) for
    # callers that hash with the shared contracts helper. Either needs the token itself.
    return (approval_token_sha256(token), contracts.sha256(token))


def _side_effect(action_spec):
    if not isinstance(action_spec, dict):
        raise GovernorDenied("invalid-action-spec", "object required")
    side_effect = action_spec.get("side_effect")
    if side_effect not in contracts.SIDE_EFFECTS:
        raise GovernorDenied("invalid-action-spec", "unknown side-effect class")
    permissions = action_spec.get("permissions", [])
    if not isinstance(permissions, list) or any(p not in contracts.PERMISSIONS for p in permissions):
        raise GovernorDenied("invalid-action-spec", "unknown permission")
    return side_effect


def _approve(grant, engine_id, action, side_effect, token):
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS:
        raise GovernorDenied("approval-missing", f"{side_effect} needs a human approval token")
    matching = [a for a in grant["approvals"]
                if a["engine"] == engine_id and a["action"] == action and a["side_effect"] == side_effect]
    if not matching:
        raise GovernorDenied("approval-missing", "no approval for this engine, action and side effect")
    digests = _token_digests(token)
    if not any(hmac.compare_digest(a["token_sha256"], d) for a in matching for d in digests):
        raise GovernorDenied("approval-mismatch", "approval token does not match")


def _is_inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def _text_path(value):
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str) or not value or "\0" in value:
        raise GovernorDenied("invalid-path", "paths are non-empty text without NUL")
    return value


def _grant_roots(grant_paths, base):
    roots = []
    for raw in grant_paths:
        if not os.path.isabs(raw):
            if ".." in raw.split("/"):
                raise GovernorDenied("invalid-grant", "relative grant path climbs with ..")
            root = os.path.realpath(os.path.join(base, raw))
            if not _is_inside(root, base):
                raise GovernorDenied("invalid-grant", "relative grant path resolves outside its base")
        else:
            root = os.path.realpath(raw)
        roots.append(root)
    return roots


def _check_paths(grant, paths, base):
    if isinstance(paths, (str, bytes, os.PathLike)) or not isinstance(paths, (list, tuple)):
        raise GovernorDenied("invalid-path", "paths: a list or tuple of paths")
    if not paths:
        return
    base = os.path.realpath(_text_path(os.getcwd() if base is None else base))
    roots = _grant_roots(grant["paths"], base)
    for raw in paths:
        resolved = os.path.realpath(os.path.join(base, _text_path(raw)))
        if not any(_is_inside(resolved, root) for root in roots):
            raise GovernorDenied("path-outside-grant", "a requested path resolves outside the granted paths")


def check(grant, engine_id, action, action_spec, *, paths=(), approval_token=None, now=None, base=None):
    """Allow one engine action under a grant, or raise GovernorDenied (deny by default).

    `action_spec` must come from the validated engine registry, never from the requester.
    `base` is the directory relative paths resolve against (default: the current directory)."""
    try:
        contracts.validate_grant(grant)
        expires = datetime.datetime.strptime(grant["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_UTC)
    except Exception as exc:  # noqa: BLE001 - any malformed grant is refused, whatever broke
        raise GovernorDenied("invalid-grant", _safe(exc)) from None
    side_effect = _side_effect(action_spec)
    if _instant(now) >= expires:
        raise GovernorDenied("grant-expired", grant["expires_at"])
    if not isinstance(engine_id, str) or engine_id not in grant["engines"]:
        raise GovernorDenied("engine-not-granted", _safe(engine_id, 80))
    if not isinstance(action, str) or action not in grant["engines"][engine_id]:
        raise GovernorDenied("action-not-granted", _safe(action, 80))
    if contracts.side_effect_rank(side_effect) > contracts.side_effect_rank(grant["max_side_effect"]):
        raise GovernorDenied("side-effect-exceeds-grant", f"{side_effect} > {grant['max_side_effect']}")
    gated = side_effect in contracts.GATED
    if gated:  # production can only get here when max_side_effect is production (top rank)
        _approve(grant, engine_id, action, side_effect, approval_token)
    _check_paths(grant, paths, base)
    return {"allowed": True, "grant_id": grant["grant_id"], "side_effect": side_effect,
            "reason": "approved" if gated else "granted"}


# ---------------------------------------------------------------- payloads

def _collect(value, texts, depth):
    if depth > MAX_PAYLOAD_DEPTH:
        raise ValueError("payload nests too deep")
    if isinstance(value, str):
        texts.append(value)
    elif isinstance(value, (bytes, bytearray)):
        texts.append(bytes(value).decode("utf-8", errors="replace"))
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("payload keys must be text")
            texts.append(key)
            _collect(item, texts, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect(item, texts, depth + 1)
    elif value is None or isinstance(value, (bool, int)):
        pass
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("payload number is not finite")
    else:
        raise TypeError("payload holds a value that is not JSON data")


def check_payload(payload):
    """None when no value of the payload looks like a credential; GovernorDenied otherwise.
    The error names the matched rules only, never the value."""
    texts = []
    try:
        _collect(payload, texts, 0)
        if isinstance(payload, (dict, list, tuple)):
            texts.append(contracts.canonical(payload))  # key/value context rules
    except (TypeError, ValueError, RecursionError):
        raise GovernorDenied("invalid-payload", "payload is not plain JSON data") from None
    if sum(len(t) for t in texts) > MAX_PAYLOAD_CHARS:
        raise GovernorDenied("payload-too-large", "too large to scan")
    rules = sorted({f.rule for text in texts for f in secret_findings("payload.json", text)})
    if rules:
        raise GovernorDenied("secret-in-payload", "matched rules: " + ",".join(rules))
    return None


def payload_sha256(payload):
    """SHA-256 of a payload: of its bytes, or of its canonical JSON (repr for non-JSON values)."""
    if isinstance(payload, (bytes, bytearray)):
        return hashlib.sha256(bytes(payload)).hexdigest()
    try:
        return contracts.sha256(payload)
    except (TypeError, ValueError):
        return hashlib.sha256(repr(payload).encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------- audit

def _inside_git_worktree(path):
    while True:
        marker = os.path.join(path, ".git")
        if os.path.islink(marker) or os.path.isfile(marker) or os.path.lexists(os.path.join(marker, "HEAD")):
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def _open_audit(state_dir, *, write):
    reason = "audit-failed" if write else "audit-tampered"
    directory = os.path.abspath(_text_path(state_dir))
    if os.path.realpath(directory) != directory:
        raise GovernorDenied(reason, "the audit directory may not pass through a symlink")
    if _inside_git_worktree(directory):
        raise GovernorDenied("audit-in-repository", "the audit log lives in a private state directory outside Git")
    flags = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    try:
        if write:
            os.makedirs(directory, mode=0o700, exist_ok=True)
        directory_fd = os.open(directory, flags | os.O_DIRECTORY)
        try:
            current = os.fstat(directory_fd)
            if current.st_uid != os.geteuid() or current.st_mode & 0o077:
                raise GovernorDenied(reason, "the audit directory must be private and owned by the caller")
            mode = os.O_RDWR | os.O_APPEND | os.O_CREAT if write else os.O_RDONLY
            fd = os.open(AUDIT_FILE, flags | mode, 0o600, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    except FileNotFoundError as exc:
        if not write:
            return None
        raise GovernorDenied(reason, os.strerror(exc.errno or 0)) from None
    except GovernorDenied:
        raise
    except OSError as exc:
        raise GovernorDenied(reason, os.strerror(exc.errno or 0)) from None
    try:
        current = os.fstat(fd)
        if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or current.st_mode & 0o077
                or current.st_uid != os.geteuid()):
            raise GovernorDenied(reason, "the audit log must be a private, single-linked regular file")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _private_log(fd):
    """The audit log must be a private regular file of the caller with one name (no hard link)."""
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise GovernorDenied("audit-failed", "the audit log is not a regular file")
    if info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
        raise GovernorDenied("audit-failed", "the audit log is not a private file of the caller (owner, mode 0600, one link)")


def _field(event, name, limit=200):
    value = event.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        return "[invalid]"
    return _safe(value, limit)


def _last_record(fd):
    size = os.fstat(fd).st_size
    if size == 0:
        return None
    tail = os.pread(fd, min(size, 65536), max(0, size - 65536))
    if not tail.endswith(b"\n"):
        raise GovernorDenied("audit-tampered", "the last record is incomplete")
    line = tail[:-1].rsplit(b"\n", 1)[-1]
    try:
        record = json.loads(line)
        return record["seq"], record["record_sha256"]
    except (ValueError, KeyError, TypeError):
        raise GovernorDenied("audit-tampered", "the last record is unreadable") from None


def audit(state_dir, event, *, now=None):
    """Append one decision to <state_dir>/governor-audit.jsonl (append-only, hash-chained).

    Written: seq, at, decision, reason, grant_id, engine, action, side_effect, payload_sha256,
    prev_sha256, record_sha256. A payload is hashed, never written; text fields that look like
    credentials are written as "[redacted]"; any other field of `event` is dropped."""
    if not isinstance(event, dict):
        raise GovernorDenied("invalid-audit-event", "object required")
    decision = event.get("decision")
    if decision is None and isinstance(event.get("allowed"), bool):
        decision = "allow" if event["allowed"] else "deny"
    if decision not in ("allow", "deny"):
        raise GovernorDenied("invalid-audit-event", "decision must be allow or deny")
    if "payload" in event:
        digest = payload_sha256(event["payload"])
    else:
        given = event.get("payload_sha256")
        digest = given if isinstance(given, str) and len(given) == 64 and set(given) <= _HEX64 else None
    record = {"seq": 0, "at": _stamp(_instant(now)), "decision": decision,
              "reason": _field(event, "reason", 120), "grant_id": _field(event, "grant_id", 80),
              "engine": _field(event, "engine", 80), "action": _field(event, "action", 80),
              "side_effect": _field(event, "side_effect", 40), "payload_sha256": digest, "prev_sha256": None}
    fd = _open_audit(state_dir, write=True)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        _private_log(fd)
        last = _last_record(fd)
        if last is not None:
            record["seq"], record["prev_sha256"] = last[0] + 1, last[1]
        record["record_sha256"] = contracts.sha256(record)
        line = (contracts.canonical(record) + "\n").encode("utf-8")
        if os.write(fd, line) != len(line):
            raise GovernorDenied("audit-failed", "short write")
        os.fsync(fd)
    except GovernorDenied:  # a PermissionError, so an OSError: keep its own reason
        raise
    except OSError as exc:
        raise GovernorDenied("audit-failed", os.strerror(exc.errno or 0)) from None
    finally:
        os.close(fd)


def verify_audit(state_dir):
    """Number of records when the chain is intact; GovernorDenied("audit-tampered") otherwise."""
    fd = _open_audit(state_dir, write=False)
    if fd is None:
        return 0
    prev, count = None, 0
    with os.fdopen(fd, "rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        for number, raw in enumerate(handle, 1):
            try:
                record = json.loads(raw)
                claimed = record.pop("record_sha256")
            except (ValueError, KeyError, TypeError, AttributeError):
                raise GovernorDenied("audit-tampered", f"line {number} unreadable") from None
            if (not raw.endswith(b"\n") or record.get("seq") != number - 1 or record.get("prev_sha256") != prev
                    or contracts.sha256(record) != claimed):
                raise GovernorDenied("audit-tampered", f"line {number}")
            prev, count = claimed, number
    return count


# ---------------------------------------------------------------- sandbox

SYSTEM_DIRS = ("/usr", "/etc", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32")
DEVICES = ("null", "zero", "full", "random", "urandom", "tty")
_KERNEL_TREES = ("/proc", "/sys", "/dev")
_ENV_NAME = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
_BOOT = ("import sys;sys.path.insert(0,sys.argv[1]);"
         "from engineering_os.governor import _sandbox_init;_sandbox_init(sys.argv[2])")
# mount(2) flags
MS_RDONLY, MS_NOSUID, MS_NODEV, MS_NOEXEC, MS_REMOUNT = 1, 2, 4, 8, 32
MS_NOATIME, MS_NODIRATIME, MS_BIND = 1024, 2048, 4096
MS_RELATIME, MS_STRICTATIME = 1 << 21, 1 << 24
MNT_DETACH = 2
SYS_PIVOT_ROOT = {"x86_64": 155, "amd64": 155, "aarch64": 41, "arm64": 41, "riscv64": 41,
                  "loongarch64": 41, "ppc64le": 203, "ppc64": 203, "s390x": 217, "i686": 217,
                  "i386": 217, "armv7l": 218, "armv6l": 218}


@functools.lru_cache(maxsize=1)
def _cage():
    """swarm/phase3/cage.py, loaded by path under a private name (read only, never modified)."""
    spec = importlib.util.spec_from_file_location("_gaie_governor_cage", CAGE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _quiet(argv, timeout=10):
    try:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout, env=dict(_cage().ENV)).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _real_path(value, what):
    path = os.path.realpath(_text_path(value))
    if not os.path.exists(path):
        raise GovernorDenied("invalid-path", f"{what} does not exist")
    if any(_is_inside(path, tree) for tree in _KERNEL_TREES):
        raise GovernorDenied("invalid-path", f"{what} lies in a kernel tree")
    if path == "/" or any(_is_inside(system, path) for system in SYSTEM_DIRS):
        raise GovernorDenied("allowed-path-too-broad", f"{what} covers / or a system directory")
    return path


def _paths(values, what):
    if isinstance(values, (str, bytes, os.PathLike)) or not isinstance(values, (list, tuple)):
        raise GovernorDenied("invalid-path", f"{what}: a list or tuple of paths")
    return sorted({_real_path(v, what) for v in values})


def _environment(env_allow, home):
    if isinstance(env_allow, (str, bytes)) or not isinstance(env_allow, (list, tuple, set, frozenset)):
        raise GovernorDenied("invalid-env-name", "env_allow: a list of variable names")
    env = {"PATH": _cage().ENV["PATH"], "HOME": home, "LANG": _cage().ENV["LANG"]}
    for name in env_allow:
        if (not isinstance(name, str) or not name or len(name) > 128 or not set(name) <= _ENV_NAME
                or name[0].isdigit()):
            raise GovernorDenied("invalid-env-name", "names are [A-Za-z_][A-Za-z0-9_]*")
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def _number(value, what, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise GovernorDenied("invalid-limit", f"{what}: {low}..{high}")
    return value


def _launch(argv, *, cwd, env, timeout, limits, net_in_child, pass_fds=()):
    """Start argv in a process group of its own with cage's limits; returns (proc, out, err, limit)."""
    cage = _cage()
    out, err = tempfile.TemporaryFile(), tempfile.TemporaryFile()
    preexec = cage._child(limits["memory_mb"], limits["cpu_seconds"], limits["file_mb"], limits["nofile"],
                          32, False, net_in_child, cage.UNPRIVILEGED)
    limit = None
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                pass_fds=pass_fds, start_new_session=True, preexec_fn=preexec)
    except BaseException:
        out.close()
        err.close()
        raise
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        limit = "timeout"
        cage._kill(proc.pid)
        proc.wait()
    finally:
        cage._kill(proc.pid)  # nothing it started may outlive the run
    return proc, out, err, limit


def _text(handle):
    handle.seek(0)
    data = handle.read()
    handle.close()
    return data.decode("utf-8", errors="replace")


def _drain(fd):
    os.set_blocking(fd, False)
    chunks = []
    try:
        while True:
            block = os.read(fd, 4096)
            if not block:
                break
            chunks.append(block)
    except BlockingIOError:
        pass
    finally:
        os.close(fd)
    return b"".join(chunks).decode("ascii", errors="replace").split("\n")


def _classify(code, limit, cpu_used, cpu_seconds):
    if limit:
        return limit
    if code == -signal.SIGXCPU or (code == -signal.SIGKILL and cpu_used is not None and cpu_used >= cpu_seconds):
        return "cpu"
    if code == -signal.SIGXFSZ:
        return "file"
    return None


def _run_full(cmd, *, cwd, timeout, network, env, allowed, readable, limits, strict=False):
    """Run cmd inside user+mount+pid(+net) namespaces under a minimal read-only root."""
    unshare = shutil.which("unshare", path=_cage().ENV["PATH"])
    # pid 1 is this interpreter: after pivot_root it still imports C modules (os.wait4 loads resource)
    # from its own install, which lies outside the system directories on e.g. GitHub runners.
    system = tuple(d for d in SYSTEM_DIRS if not (strict and d == "/etc"))
    aliases = []
    if strict:  # /etc is hidden: pid 1 execs the host-resolved file itself, so alternatives links cannot dangle
        _, mounts = _strict_program(cmd[0], env["PATH"], cwd, system + tuple(allowed + readable))
        if any(_is_inside(root, path) or _is_inside(path, root) for pair in mounts for path in pair for root in allowed):
            raise GovernorDenied("invalid-sandbox-mode", "the writable workspace must not overlap a program prefix")
        runtime = [target for target, source in mounts if target == source]
        aliases = [[target, source] for target, source in mounts if target != source]
    else:
        runtime = interpreter_prefixes(system + tuple(allowed) + tuple(readable))
        runtime += _exec_prefix(cmd[0], env["PATH"], cwd, allowed + readable + runtime)
    readable = sorted(set(readable) | set(runtime))
    status_r, status_w = os.pipe()
    spec = {"cmd": list(cmd), "cwd": cwd, "allowed": allowed, "readable": readable,
            "env_names": sorted(env), "status_fd": status_w, "strict": strict}
    argv = [unshare, "--user", "--map-root-user", "--mount", "--propagation", "private",
            "--pid", "--fork", "--kill-child"] + ([] if network else ["--net"]) + [
            "--", sys.executable, "-I", "-B", "-S", "-c", _BOOT, ROOT, json.dumps(dict(spec, aliases=aliases))]
    try:
        proc, out, err, limit = _launch(argv, cwd="/", env=env, timeout=timeout, limits=limits,
                                        net_in_child=False, pass_fds=(status_w,))
    except BaseException:
        os.close(status_r)
        raise
    finally:
        os.close(status_w)
    lines = _drain(status_r)
    stdout, stderr = _text(out), _text(err)
    if "ready" not in lines and (strict or limit is None):
        first = stderr.strip().splitlines()[-1:] or ["no diagnostic"]
        raise GovernorDenied("sandbox-setup-failed", _safe(first[0]))
    code, cpu_used, table = proc.returncode, None, None
    for line in lines:
        if line.startswith("exit "):
            _, value, used = line.split()
            code, cpu_used = int(value), float(used)
        elif line.startswith("mounts "):  # what pid 1 mounted, reported before the command started
            try:
                table = json.loads(line[len("mounts "):])
            except ValueError:
                table = None
    return {"returncode": code, "stdout": stdout, "stderr": stderr,
            "limit": _classify(code, limit, cpu_used, limits["cpu_seconds"]),
            "network_isolated": not network, "fs_isolated": True, "mounts": table}


def _exec_prefix(program, path, cwd, visible):
    """The install prefix (parent of bin/) of the program cmd[0] names, when it is not already
    visible in the sandbox, so that a tool installed under e.g. /opt/<tool>/bin can start."""
    found = shutil.which(program, path=path) if "/" not in program else os.path.join(cwd, program)
    if not found:
        return []
    real = os.path.realpath(found)
    if any(_is_inside(real, root) for root in SYSTEM_DIRS + tuple(visible)):
        return []
    try:
        return [_install_prefix(real)]
    except GovernorDenied:
        return []


def _install_prefix(real):
    """The install prefix (parent of bin/) of a resolved program file, checked by _mountable_prefix."""
    return _mountable_prefix(os.path.dirname(os.path.dirname(real)))


def _mountable_prefix(path, *, trusted=False):
    """Never /, a whole top-level directory such as /opt, a system directory, a kernel tree, or a
    directory that holds a scratch root or a home directory. Unless `trusted` (the hub's own
    interpreter), also never a directory under a home directory or one a non-root user can change."""
    prefix = _real_path(path, "program prefix")
    common = {"/tmp", "/var/tmp", *_home_roots()}
    if prefix.count("/") < 2 or any(_is_inside(root, prefix) for root in common):
        raise GovernorDenied("program-not-visible", "an install prefix is too broad to mount read-only")
    if not trusted:
        _trusted_source(prefix)
    return prefix


def _home_roots():
    """Every home directory of this host: /root, /home, the caller's HOME and each account's home
    directory except / and those inside a system directory (service accounts such as bin use /bin)."""
    roots = {"/root", "/home", os.path.expanduser("~"), os.environ.get("HOME") or "/"}
    try:
        roots.update(entry.pw_dir for entry in pwd.getpwall())
    except (OSError, KeyError):
        pass
    found = set()
    for root in roots:
        if isinstance(root, str) and os.path.isabs(root):
            real = os.path.realpath(root)
            if real != "/" and not any(_is_inside(real, tree) for tree in SYSTEM_DIRS + _KERNEL_TREES):
                found.add(real)
    return sorted(found)


def _foreign_writer(path):
    """The first of the real path `path` and the directories above it that someone other than root
    can change (another owner, a group or world write bit, an access ACL), or None."""
    current = path
    while True:
        info = os.lstat(current)
        try:
            os.getxattr(current, "system.posix_acl_access", follow_symlinks=False)
            acl = True
        except OSError as exc:
            acl = exc.errno not in (errno.ENODATA, errno.EOPNOTSUPP)  # an unreadable ACL counts as foreign
        if info.st_uid != 0 or info.st_mode & 0o022 or acl:
            return current
        if current == "/":
            return None
        current = os.path.dirname(current)


def _trusted_source(path):
    """GovernorDenied unless the real path `path` lies outside every home directory and neither it
    nor a directory above it can be changed by a non-root user (pr30-isolation recheck item 1)."""
    if any(_is_inside(path, home) for home in _home_roots()):
        raise GovernorDenied("program-not-visible", "a program under a home directory is not mounted")
    try:
        writer = _foreign_writer(path)
    except OSError:
        writer = path
    if writer is not None:
        raise GovernorDenied("program-not-visible", "a program in a directory a non-root user can change is not mounted")


def interpreter_prefixes(visible=SYSTEM_DIRS):
    """Read-only mounts the sandbox's own interpreter needs in a legacy or loopback run: its install
    prefixes outside `visible` (strict runs mount less, see _program_mounts)."""
    found = []
    for path in (sys.base_prefix, sys.base_exec_prefix, os.path.dirname(os.path.dirname(os.path.realpath(sys.executable)))):
        real = os.path.realpath(path)
        if not any(_is_inside(real, root) for root in tuple(visible) + tuple(found)):
            found = [prefix for prefix in found if not _is_inside(prefix, real)]
            found.append(_mountable_prefix(real, trusted=True))
    return found


_ELF_HEADER = {True: "HHIQQQIHHHHHH", False: "HHIIIIIHHHHHH"}  # after e_ident; ELF64 / ELF32
_ELF_PHDR = {True: "IIQQQQQQ", False: "IIIIIIII"}
_ELF_DYN = {True: "qQ", False: "iI"}
_PT_LOAD, _PT_DYNAMIC, _PT_INTERP = 1, 2, 3
_DT_NULL, _DT_NEEDED, _DT_STRTAB, _DT_RPATH, _DT_RUNPATH = 0, 1, 5, 15, 29
_PYTHON_FILE = re.compile(r"(?:lib)?python(\d+\.\d+t?)(?:\.so(?:\.\d+)*)?")


def _elf_links(path):
    """(PT_INTERP, DT_NEEDED names, DT_RPATH entries, DT_RUNPATH entries) of the ELF file `path`,
    read as data within fixed bounds: nothing is loaded or run (no ldd). None when the file is not
    ELF (a script); GovernorDenied when an ELF file cannot be parsed."""
    def bad(what):
        return GovernorDenied("program-not-visible", f"the program's ELF {what} cannot be read")

    with open(path, "rb") as handle:
        size = os.fstat(handle.fileno()).st_size

        def read(offset, length):
            if offset < 0 or length < 0 or offset + length > size:
                raise bad("layout")
            handle.seek(offset)
            data = handle.read(length)
            if len(data) != length:
                raise bad("layout")
            return data

        ident = handle.read(16)
        if len(ident) < 16 or ident[:4] != b"\x7fELF":
            return None
        if ident[4] not in (1, 2) or ident[5] not in (1, 2):
            raise bad("class")
        wide, order = ident[4] == 2, "<" if ident[5] == 1 else ">"
        header = struct.unpack(order + _ELF_HEADER[wide], read(16, struct.calcsize(order + _ELF_HEADER[wide])))
        phoff, phentsize, phnum = header[4], header[8], header[9]
        phdr = order + _ELF_PHDR[wide]
        if phnum > 1024 or phentsize < struct.calcsize(phdr):
            raise bad("program headers")
        loads, dynamic, interp = [], None, None
        for index in range(phnum):
            fields = struct.unpack(phdr, read(phoff + index * phentsize, struct.calcsize(phdr)))
            kind, offset, vaddr, filesz = ((fields[0], fields[2], fields[3], fields[5]) if wide
                                           else (fields[0], fields[1], fields[2], fields[4]))
            if kind == _PT_LOAD:
                loads.append((vaddr, offset, filesz))
            elif kind == _PT_DYNAMIC:
                dynamic = (offset, filesz)
            elif kind == _PT_INTERP:
                if filesz > 4096:
                    raise bad("interpreter")
                interp = os.fsdecode(read(offset, filesz).split(b"\0")[0])
        needed, rpath, runpath = [], [], []
        if dynamic is None:
            return interp, needed, rpath, runpath
        entry = order + _ELF_DYN[wide]
        offset, filesz = dynamic
        if filesz > 1 << 20:
            raise bad("dynamic section")
        strtab, names = None, []
        for tag, value in struct.iter_unpack(entry, read(offset, filesz - filesz % struct.calcsize(entry))):
            if tag == _DT_NULL:
                break
            if tag == _DT_STRTAB:
                strtab = value
            elif tag in (_DT_NEEDED, _DT_RPATH, _DT_RUNPATH):
                names.append((tag, value))
        if not names:
            return interp, needed, rpath, runpath
        base = next((off + strtab - va for va, off, length in loads if strtab is not None and va <= strtab < va + length), None)
        if base is None or len(names) > 4096:
            raise bad("string table")
        for tag, value in names:
            chunk = read(base + value, min(4096, size - base - value)) if 0 <= base + value < size else b""
            if b"\0" not in chunk:
                raise bad("string")
            text = os.fsdecode(chunk.split(b"\0")[0])
            {_DT_NEEDED: needed, _DT_RPATH: rpath, _DT_RUNPATH: runpath}[tag].append(text)
        return interp, needed, rpath, runpath


def _search_dirs(entries, origin):
    """DT_RPATH/DT_RUNPATH entries as absolute directories ($ORIGIN expanded; an entry with another
    dynamic string token such as $LIB or $PLATFORM is not searched, so nothing is guessed)."""
    found = []
    for entry in entries:
        for item in entry.split(":"):
            item = item.replace("${ORIGIN}", origin).replace("$ORIGIN", origin)
            if item and "$" not in item and os.path.isabs(item):
                found.append(os.path.normpath(item))
    return found


def _linked_libraries(program):
    """(path the loader opens, real file) for the ELF interpreter of `program` and every shared object
    it reaches through DT_RPATH or DT_RUNPATH, recursively. Objects the loader finds in its default
    directories are not listed: those lie in the system directories, which every sandbox shows."""
    links = _elf_links(program)
    if links is None:
        return []
    found = {}
    if links[0]:
        if not os.path.isabs(links[0]) or not os.path.isfile(links[0]):
            raise GovernorDenied("program-not-visible", "the program's ELF interpreter cannot be resolved")
        found[os.path.normpath(links[0])] = os.path.realpath(links[0])
    queue, seen, inherited = [(os.path.dirname(program), links)], {program}, None
    while queue:
        origin, (_, needed, rpath, runpath) = queue.pop(0)
        rpath, runpath = _search_dirs(rpath, origin), _search_dirs(runpath, origin)
        if inherited is None:  # the executable's DT_RPATH also applies to its libraries (unless it has DT_RUNPATH)
            inherited = [] if runpath else rpath
        directories = runpath or rpath + [d for d in inherited if d not in rpath]
        for name in needed:
            for directory in directories if "/" not in name else ():
                candidate = os.path.join(directory, name)
                if not os.path.isfile(candidate):
                    continue
                real = os.path.realpath(candidate)
                found.setdefault(candidate, real)
                if real not in seen:
                    seen.add(real)
                    sub = _elf_links(real)
                    if sub is None or len(seen) > 256:
                        raise GovernorDenied("program-not-visible", "a linked library is not a bounded ELF file")
                    queue.append((os.path.dirname(candidate), sub))
                break
    return sorted(found.items())


def _python_library(real, needed, own):
    """The standard library directories (lib/pythonX.Y, which holds lib-dynload and site-packages)
    of a Python interpreter installed as <prefix>/bin/<file>; [] for any other program."""
    bin_dir = os.path.dirname(real)
    if os.path.basename(bin_dir) != "bin":
        return []
    prefixes = {os.path.dirname(bin_dir)}
    versions = {match.group(1) for match in map(_PYTHON_FILE.fullmatch, [os.path.basename(real), *needed]) if match}
    found = set()
    if own:
        versions.add("%d.%d%s" % (*sys.version_info[:2], "t" if "t" in getattr(sys, "abiflags", "") else ""))
        prefixes |= {os.path.realpath(sys.base_prefix), os.path.realpath(sys.base_exec_prefix)}
        found |= {os.path.realpath(sysconfig.get_path(name)) for name in ("stdlib", "platstdlib")}
    for prefix in prefixes:
        for libdir in ("lib", "lib64"):
            for version in versions:
                directory = os.path.join(prefix, libdir, "python" + version)
                if os.path.isfile(os.path.join(directory, "os.py")) or os.path.isdir(os.path.join(directory, "lib-dynload")):
                    found.add(os.path.realpath(directory))
    return sorted(path for path in found if os.path.isdir(path))


def _program_mounts(real, visible, *, own=False):
    """Read-only (target, source) mounts a strict run of the resolved program file `real` needs from
    outside `visible`: its bin directory (the file alone when it does not live in one), the standard
    library of a Python interpreter, and the files its ELF interpreter, DT_RPATH and DT_RUNPATH name
    (mounted at the path the loader opens). Never share/, etc/ or the whole install prefix. Unless
    `own` (the hub's own interpreter), anything under a home directory or in a directory a non-root
    user can change is refused (GovernorDenied program-not-visible)."""
    def shown(path, extra=()):
        return any(_is_inside(path, root) for root in tuple(visible) + tuple(extra))

    if shown(real):
        return []
    if not own:
        _trusted_source(real)
    bin_dir = os.path.dirname(real)
    try:
        links = _elf_links(real)
        libraries = _linked_libraries(real)
    except OSError:
        raise GovernorDenied("program-not-visible", "the program file cannot be read") from None
    directories = [bin_dir] if os.path.basename(bin_dir) in ("bin", "sbin") else []
    directories += _python_library(real, links[1] if links else [], own)
    directories = sorted({_mountable_prefix(path, trusted=own) for path in directories if not shown(path)})
    directories = [d for d in directories if not shown(d, [o for o in directories if o != d])]
    files = [] if shown(real, directories) else [(real, real)]
    for target, source in libraries:
        if shown(target, directories):  # the link is visible: show the file it leads to
            target = source
        if not shown(source, directories) or target != source:
            files.append((target, source))
    mounts = [(path, path) for path in directories]
    for target, source in sorted(set(files)):
        if not own:
            _trusted_source(source)
        if not os.path.isfile(source):
            raise GovernorDenied("program-not-visible", "a linked library is not a regular file")
        mounts.append((target, source))
    return mounts


def _resolve_program(program, path, cwd):
    """The real file argv[0] names on the host view (pid 1 calls this again before pivot_root), or None."""
    found = shutil.which(program, path=path) if "/" not in program else os.path.join(cwd, program)
    real = os.path.realpath(found) if found else None
    return real if real and os.path.isfile(real) and os.access(real, os.X_OK) else None


def _strict_program(program, path, cwd, visible):
    """Resolve cmd[0] on the host for a strict run: (real file to exec, read-only (target, source)
    mounts for it and for the hub's own interpreter, which is pid 1, from outside `visible`)."""
    real = _resolve_program(program, path, cwd)
    if real is None:
        raise GovernorDenied("program-not-visible", "the program cannot be resolved to an executable file")
    own = os.path.realpath(sys.executable)
    mounts = _program_mounts(own, visible, own=True)
    if real != own:
        mounts += _program_mounts(real, tuple(visible) + tuple(t for t, s in mounts if t == s), own=False)
    return real, sorted(set(mounts))


def _run_plain(cmd, *, cwd, timeout, network, env, limits, probe):
    """Fallback when the full sandbox cannot be built: limits, own group, empty env, and a
    network namespace where one can be made. No filesystem isolation (fs_isolated False)."""
    argv, in_child = list(cmd), False
    if not network:
        if probe["root_netns"]:
            in_child = True
        elif probe["userns_netns"]:
            argv = [shutil.which("unshare", path=_cage().ENV["PATH"]), "--user", "--map-root-user", "--net", "--"] + argv
        else:
            raise GovernorDenied("network-isolation-unavailable", "no network namespace can be made on this host")
    proc, out, err, limit = _launch(argv, cwd=cwd, env=env, timeout=timeout, limits=limits, net_in_child=in_child)
    code = proc.returncode
    return {"returncode": code, "stdout": _text(out), "stderr": _text(err),
            "limit": _classify(code, limit, None, limits["cpu_seconds"]),
            "network_isolated": not network, "fs_isolated": False, "mounts": None}


def _strict_paths(allowed, readable, read_only):
    common_roots = {"/tmp", "/var/tmp", os.path.realpath(os.path.expanduser("~"))}
    if common_roots.intersection(allowed + readable):
        raise GovernorDenied("allowed-path-too-broad", "strict modes cannot expose a common scratch or home root")
    if read_only:
        if allowed or not readable:
            raise GovernorDenied("invalid-sandbox-mode", "read-only mode requires read paths and no writable paths")
        return
    if len(allowed) != 1 or not os.path.isdir(allowed[0]):
        raise GovernorDenied("invalid-sandbox-mode", "strict execution requires one writable workspace directory")
    root = allowed[0]
    mode = os.stat(root)
    if mode.st_uid != os.geteuid() or mode.st_mode & 0o077:
        raise GovernorDenied("invalid-sandbox-mode", "the writable workspace must be private and owned by the caller")
    if any(_is_inside(root, path) or _is_inside(path, root) for path in readable):
        raise GovernorDenied("invalid-sandbox-mode", "the writable workspace must not overlap read-only mounts")
    marker = os.path.join(root, ".git")
    if os.path.lexists(marker):
        pointer = os.lstat(marker)
        if not stat.S_ISREG(pointer.st_mode) or pointer.st_nlink != 1:
            raise GovernorDenied("invalid-sandbox-mode", "Git metadata requires an isolated linked worktree")


def _inspect_scope(paths, *, writable):
    """Reject mounted IPC endpoints and writes to inodes with aliases outside the workspace."""
    pending = list(paths)
    inspected = 0
    while pending:
        path = pending.pop()
        info = os.lstat(path)
        inspected += 1
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(path) as children:
                for child in children:
                    if inspected + len(pending) >= 100_000:
                        raise OSError(errno.E2BIG, "strict workspace inspection limit")
                    pending.append(child.path)
        elif stat.S_ISREG(info.st_mode):
            if writable and info.st_nlink != 1:
                raise OSError(errno.EMLINK, "hard-linked workspace file")
        elif not stat.S_ISLNK(info.st_mode):
            raise OSError(errno.EPERM, "special file in workspace")


def sandbox_run(cmd, *, cwd, timeout, network=False, env_allow=(), allowed_paths=(), read_paths=(),
                cpu_seconds=None, memory_mb=1024, file_mb=64, nofile=256,
                require_fs_isolation=False, read_only=False):
    """Run argv `cmd` (no shell) isolated; GovernorDenied when a precondition fails.

    Environment: empty except PATH, HOME (= cwd), LANG and the names in env_allow.
    cwd must lie inside allowed_paths (after realpath). With the full sandbox (see
    isolation_probe) the command sees a read-only minimal root (system directories, read_paths)
    where only allowed_paths are writable, has no capabilities, its own pid namespace, and no
    network unless network=True. stdout/stderr are capped by file_mb. The result's "mounts" is
    the mount table pid 1 read back from /proc/self/mountinfo before the command started
    (None in the plain tier, which has no filesystem isolation).

    A strict run (require_fs_isolation or read_only) adds, for cmd[0] and for this interpreter
    when they lie outside the system directories, only their bin directory, a Python
    interpreter's standard library directory and the shared libraries their ELF interpreter,
    DT_RPATH and DT_RUNPATH name; never share/, etc/ or a whole install prefix. A program under
    a home directory or in a directory a non-root user can change is refused
    (program-not-visible) unless it is this interpreter.

    Use require_fs_isolation for governed execution. It refuses the plain tier, network
    and inherited environment, and permits writes only to one private workspace.
    read_only implies those restrictions and exposes no writable host mounts; cwd then
    lies under read_paths. Both modes keep ephemeral /tmp and deny socket creation."""
    if isinstance(cmd, (str, bytes)) or not isinstance(cmd, (list, tuple)) or not cmd or not all(
            isinstance(a, str) and "\0" not in a for a in cmd) or not cmd[0]:
        raise GovernorDenied("invalid-command", "argv list of text, no shell string")
    timeout = _number(timeout, "timeout", 0.001, MAX_TIMEOUT)
    limits = {"cpu_seconds": int(_number(cpu_seconds if cpu_seconds is not None else max(1, math.ceil(timeout)),
                                         "cpu_seconds", 1, MAX_TIMEOUT)),
              "memory_mb": int(_number(memory_mb, "memory_mb", 64, 65536)),
              "file_mb": int(_number(file_mb, "file_mb", 1, 65536)),
              "nofile": int(_number(nofile, "nofile", 16, 65536))}
    allowed = _paths(allowed_paths, "allowed path")
    readable = _paths(read_paths, "read path")
    if not isinstance(require_fs_isolation, bool) or not isinstance(read_only, bool):
        raise GovernorDenied("invalid-sandbox-mode", "isolation mode flags must be boolean")
    if not isinstance(network, bool):
        raise GovernorDenied("invalid-limit", "network: True or False")
    strict = require_fs_isolation or read_only
    if strict:
        if network or env_allow:
            raise GovernorDenied("invalid-sandbox-mode", "strict execution is offline without environment passthrough")
        _strict_paths(allowed, readable, read_only)
        try:
            _inspect_scope(allowed, writable=True)
            _inspect_scope(readable, writable=False)
        except OSError as exc:
            raise GovernorDenied("invalid-sandbox-mode", "strict mount scope is unsafe or cannot be inspected") from exc
    cwd_paths = readable if read_only else allowed
    real_cwd = os.path.realpath(_text_path(cwd))
    if not os.path.isdir(real_cwd):
        raise GovernorDenied("invalid-path", "cwd is not a directory")
    if not any(_is_inside(real_cwd, root) and os.path.isdir(root) for root in cwd_paths):
        raise GovernorDenied("path-outside-grant", "cwd lies outside permitted workspace paths")
    env = _environment(env_allow, real_cwd)
    probe = isolation_probe()
    if probe["tier"] == "full":
        return _run_full(cmd, cwd=real_cwd, timeout=timeout, network=network, env=env,
                         allowed=allowed, readable=readable, limits=limits, strict=strict)
    if strict:
        raise GovernorDenied("filesystem-isolation-unavailable", "the full namespace sandbox is required")
    return _run_plain(cmd, cwd=real_cwd, timeout=timeout, network=network, env=env, limits=limits, probe=probe)


# ------------------------------------------------- inside the sandbox (pid 1 of the new pid ns)

class _ArgCmp(ctypes.Structure):  # libseccomp struct scmp_arg_cmp
    _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_int), ("datum_a", ctypes.c_uint64),
                ("datum_b", ctypes.c_uint64)]


CLONE_NEWUSER = 0x10000000
SCMP_CMP_MASKED_EQ = 7


def _disable_socket_creation():
    """Deny network and pathname socket creation for strict children, including io_uring, and nested
    user namespaces: unshare is refused, clone with CLONE_NEWUSER is refused, and clone3 (whose flags
    seccomp cannot read) reports ENOSYS so the C library falls back to clone, where the flag is checked."""
    try:
        library = ctypes.CDLL("libseccomp.so.2")
        library.seccomp_init.argtypes = [ctypes.c_uint32]
        library.seccomp_init.restype = ctypes.c_void_p
        library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
        library.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
        library.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint,
                                                   ctypes.POINTER(_ArgCmp)]
        library.seccomp_load.argtypes = [ctypes.c_void_p]
        library.seccomp_release.argtypes = [ctypes.c_void_p]
        library.seccomp_release.restype = None
    except (AttributeError, OSError):
        raise OSError(errno.ENOSYS, "seccomp support is required") from None
    context = library.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise OSError(errno.ENOMEM, "seccomp initialization failed")
    try:
        deny = 0x00050000 | errno.EPERM  # SCMP_ACT_ERRNO(EPERM)
        flags = _ArgCmp(1 if platform.machine().startswith("s390") else 0, SCMP_CMP_MASKED_EQ,
                        CLONE_NEWUSER, CLONE_NEWUSER)  # s390 passes clone's flags second
        for name, action, condition in ((b"socket", deny, None), (b"io_uring_setup", deny, None),
                                        (b"unshare", deny, None), (b"clone", deny, flags),
                                        (b"clone3", 0x00050000 | errno.ENOSYS, None)):
            number = library.seccomp_syscall_resolve_name(name)
            if number < 0:
                raise OSError(errno.ENOSYS, "unsupported system call table")
            if condition is None:
                result = library.seccomp_rule_add(context, action, number, 0)
            else:
                result = library.seccomp_rule_add_array(context, action, number, 1, ctypes.byref(condition))
            if result < 0:
                raise OSError(-result, "seccomp rule could not be installed")
        result = library.seccomp_load(context)
        if result < 0:
            raise OSError(-result, "seccomp could not be enabled")
    finally:
        library.seccomp_release(context)


def _sandbox_init(raw):
    """Build the minimal root, drop every capability, run the command as a child and report its
    status. Runs as root of a fresh user namespace (no host privilege). Never returns."""
    spec = json.loads(raw)
    status = spec["status_fd"]
    os.set_inheritable(status, False)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p]
    libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    step = "start"

    def call(result, what):
        if result != 0:
            raise OSError(ctypes.get_errno(), what)

    def mount(source, target, fstype, flags, data=None):
        enc = lambda s: None if s is None else s.encode("utf-8", "surrogateescape")  # noqa: E731
        call(libc.mount(enc(source), enc(target), enc(fstype), flags, enc(data)), "mount")

    def grab(path):  # an O_PATH handle whose real path is exactly `path` (no swapped symlink)
        fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
        if os.readlink(f"/proc/self/fd/{fd}") != path:
            raise OSError(errno.ELOOP, "path changed")
        return fd

    def bind(fd, target, readonly, devices=False):
        mount(f"/proc/self/fd/{fd}", target, None, MS_BIND)
        flag = os.statvfs(target).f_flag
        flags = MS_REMOUNT | MS_BIND | MS_NOSUID | (0 if devices else MS_NODEV)
        flags |= MS_RDONLY if readonly or flag & os.ST_RDONLY else 0
        flags |= MS_NOEXEC if flag & os.ST_NOEXEC else 0
        flags |= MS_NODIRATIME if flag & os.ST_NODIRATIME else 0
        flags |= MS_NOATIME if flag & os.ST_NOATIME else MS_RELATIME if flag & os.ST_RELATIME else MS_STRICTATIME
        mount(None, target, None, flags)

    try:
        step = "pid namespace"
        if os.getpid() != 1:
            raise OSError(errno.EPERM, "not pid 1")
        step = "open sources"
        exe = _resolve_program(spec["cmd"][0], os.environ.get("PATH", os.defpath), spec["cwd"]) if spec["strict"] else None
        handles = {}
        links = {}
        for path in SYSTEM_DIRS:
            if spec["strict"] and path == "/etc":
                continue
            if os.path.islink(path):
                links[path] = os.readlink(path)
            elif os.path.isdir(path):
                handles[path] = (grab(path), True)
        for path in spec["readable"]:
            handles[path] = (grab(path), True)
        for target, source in spec.get("aliases", ()):  # a linked library: its file at the path the loader opens
            if not os.path.isabs(target) or os.path.normpath(target) != target or target in handles:
                raise OSError(errno.EINVAL, "alias target")
            handles[target] = (grab(source), True)
            if not stat.S_ISREG(os.fstat(handles[target][0]).st_mode):
                raise OSError(errno.EPERM, "an aliased mount is not a regular file")
        for path in spec["allowed"]:
            handles[path] = (grab(path), False)
            marker = os.path.join(path, ".git")
            if spec["strict"] and os.path.lexists(marker):
                fd = grab(marker)
                pointer = os.fstat(fd)
                if not stat.S_ISREG(pointer.st_mode) or pointer.st_nlink != 1:
                    raise OSError(errno.EPERM, "Git metadata is not a worktree pointer")
                handles[marker] = (fd, True)
        devices = {name: grab("/dev/" + name) for name in DEVICES if os.path.exists("/dev/" + name)}
        with open("/proc/sys/kernel/cap_last_cap") as handle:
            last_cap = int(handle.read())
        step = "new root"
        root = "/tmp"
        mount("tmpfs", root, "tmpfs", MS_NOSUID | MS_NODEV, "size=8m,mode=0755")
        for name in ("dev", "proc", "tmp"):
            os.mkdir(f"{root}/{name}", 0o755)
        mount("tmpfs", f"{root}/dev", "tmpfs", MS_NOSUID | MS_NODEV | MS_NOEXEC, "size=16m,mode=0755")
        os.mkdir(f"{root}/dev/shm")
        os.chmod(f"{root}/dev/shm", 0o1777)
        for name, fd in devices.items():
            os.close(os.open(f"{root}/dev/{name}", os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC, 0o666))
            bind(fd, f"{root}/dev/{name}", readonly=True, devices=True)
        for name, target in (("fd", "/proc/self/fd"), ("stdin", "/proc/self/fd/0"),
                             ("stdout", "/proc/self/fd/1"), ("stderr", "/proc/self/fd/2")):
            os.symlink(target, f"{root}/dev/{name}")
        mount("proc", f"{root}/proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC | MS_RDONLY)
        mount("tmpfs", f"{root}/tmp", "tmpfs", MS_NOSUID | MS_NODEV, "size=64m,mode=1777")
        for path, target in links.items():
            os.symlink(target, root + path)
        step = "bind paths"
        for path in sorted(handles, key=lambda p: p.split("/")):
            fd, readonly = handles[path]
            target = root + path
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                if not os.path.lexists(target):
                    os.close(os.open(target, os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC, 0o644))
            bind(fd, target, readonly=readonly)
        for fd, _ in handles.values():
            os.close(fd)
        for fd in devices.values():
            os.close(fd)
        step = "pivot root"
        number = SYS_PIVOT_ROOT.get(platform.machine())
        if number is None:
            raise OSError(errno.ENOSYS, "pivot_root number unknown")
        os.chdir(root)
        call(libc.syscall(number, b".", b"."), "pivot_root")
        call(libc.umount2(b".", MNT_DETACH), "umount old root")
        os.chdir("/")
        mount(None, "/", None, MS_REMOUNT | MS_BIND | MS_RDONLY | MS_NOSUID | MS_NODEV)
        os.chdir(spec["cwd"])
        if spec["strict"]:
            step = "inspect mounted workspace"
            _inspect_scope(spec["allowed"], writable=True)
            _inspect_scope(spec["readable"], writable=False)
        step = "drop capabilities"
        for cap in range(last_cap + 1):
            call(libc.prctl(24, cap, 0, 0, 0), "PR_CAPBSET_DROP")
        call(libc.prctl(28, 0xEF, 0, 0, 0), "PR_SET_SECUREBITS")  # noroot, no fixups, no ambient, all locked
        call(libc.prctl(47, 4, 0, 0, 0), "PR_CAP_AMBIENT_CLEAR_ALL")
        header = (ctypes.c_uint32 * 2)(0x20080522, 0)
        data = (ctypes.c_uint32 * 6)()
        call(libc.capset(header, data), "capset")
        call(libc.prctl(38, 1, 0, 0, 0), "PR_SET_NO_NEW_PRIVS")
        call(libc.prctl(4, 0, 0, 0, 0), "PR_SET_DUMPABLE")
        if spec["strict"]:
            step = "restrict socket creation"
            _disable_socket_creation()
        env = {name: os.environ[name] for name in spec["env_names"] if name in os.environ}
        cmd = spec["cmd"]
    except OSError as exc:
        os.write(2, f"governor-sandbox: setup failed at {step}: {os.strerror(exc.errno or 0)}\n".encode())
        os._exit(125)
    report = "mounts " + json.dumps(_mount_table(links, spec.get("aliases", ())), sort_keys=True)
    os.write(status, (report if len(report) < 32768 else 'mounts {"omitted": "larger than 32 KiB"}').encode() + b"\n")
    os.write(status, b"ready\n")
    child = os.fork()
    if child == 0:
        try:
            os.execve(exe, cmd, env) if exe else os.execvpe(cmd[0], cmd, env)
        except OSError as exc:
            os.write(2, f"governor-sandbox: cannot execute: {exc.strerror}\n".encode())
        os._exit(127)
    while True:  # pid 1: reap everything, report the command, then end the namespace
        try:
            pid, wstatus, usage = os.wait4(-1, 0)
        except ChildProcessError:
            os._exit(125)
        except InterruptedError:
            continue
        if pid == child:
            code = os.waitstatus_to_exitcode(wstatus)
            os.write(status, f"exit {code} {usage.ru_utime + usage.ru_stime:.3f}\n".encode())
            os._exit(code if code >= 0 else 128 - code)


def _mount_table(links, aliases):
    """What this mount namespace shows, read back from /proc/self/mountinfo after the root is built:
    {"mounts": [[path, path inside its filesystem, filesystem type, "ro" or "rw"], ...], "links":
    {path: target} for the system directories that are symlinks, "aliases": {path: real file}}."""
    def text(field):
        return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), field)

    rows = []
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="surrogateescape") as handle:
            for line in handle:
                left, _, right = line.partition(" - ")
                fields, tail = left.split(), right.split()
                rows.append([text(fields[4]), text(fields[3]), tail[0], "ro" if "ro" in fields[5].split(",") else "rw"])
    except (OSError, IndexError):
        return {"error": "the mount table cannot be read"}
    return {"mounts": rows, "links": dict(sorted(links.items())), "aliases": {t: s for t, s in aliases}}


# ---------------------------------------------------------------- probe

_PROBE_CODE = r"""
import ctypes, json, os, socket, sys
outside, port, hostpid = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
r = {}
def attempt(name, fn):
    try:
        fn(); r[name] = "ok"
    except OSError as exc:
        r[name] = exc.__class__.__name__ + ":" + str(exc.errno)
attempt("write_inside", lambda: open("inside.txt", "w").write("x"))
attempt("write_outside", lambda: open(os.path.join(outside, "escaped.txt"), "w").write("x"))
attempt("read_outside", lambda: open(os.path.join(outside, "marker.txt")).read())
attempt("write_usr", lambda: open("/usr/governor-probe.txt", "w").write("x"))
attempt("tcp_loopback", lambda: socket.create_connection(("127.0.0.1", port), timeout=2).close())
attempt("signal_host_pid", lambda: os.kill(hostpid, 0))
libc = ctypes.CDLL(None, use_errno=True)
rc = libc.mount(None, b"/", None, ctypes.c_ulong(32 | 4096), None)
r["remount_rw"] = "ok" if rc == 0 else "errno:" + str(ctypes.get_errno())
r["cap_eff"] = [l.split()[1] for l in open("/proc/self/status") if l.startswith("CapEff")][0]
print(json.dumps(r, sort_keys=True))
"""


def _probe_sandbox():
    """Run the full sandbox once on a probe program and check from both sides that its walls hold."""
    work = tempfile.mkdtemp(prefix="gaie-governor-probe-")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        allowed, outside = os.path.join(work, "allowed"), os.path.join(work, "outside")
        os.mkdir(allowed)
        os.mkdir(outside)
        with open(os.path.join(outside, "marker.txt"), "w") as handle:
            handle.write("host-only")
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.setblocking(False)
        env = _environment((), allowed)
        limits = {"cpu_seconds": 10, "memory_mb": 1024, "file_mb": 4, "nofile": 64}
        cmd = [sys.executable, "-I", "-S", "-c", _PROBE_CODE, outside, str(listener.getsockname()[1]), str(os.getpid())]
        result = _run_full(cmd, cwd=allowed, timeout=20, network=False, env=env, allowed=[allowed],
                           readable=[], limits=limits)
        seen = json.loads(result["stdout"].strip().splitlines()[-1])
        try:
            listener.accept()
            seen["host_listener_contacted"] = True
        except BlockingIOError:
            seen["host_listener_contacted"] = False
        seen["host_sees_inside_write"] = os.path.exists(os.path.join(allowed, "inside.txt"))
        seen["host_sees_outside_write"] = os.path.exists(os.path.join(outside, "escaped.txt"))
        return seen
    except (GovernorDenied, OSError, ValueError, IndexError) as exc:
        return {"error": _safe(getattr(exc, "reason", type(exc).__name__))}
    finally:
        listener.close()
        shutil.rmtree(work, ignore_errors=True)


@functools.lru_cache(maxsize=1)
def isolation_probe():
    """What this host can enforce, measured once per process (the sandbox's tier decision)."""
    unshare = shutil.which("unshare", path=_cage().ENV["PATH"])
    probe = {"unshare": bool(unshare), "root": os.geteuid() == 0,
             "userns_netns": bool(unshare) and _quiet([unshare, "--user", "--map-root-user", "--net", "--", "true"]),
             "root_netns": os.geteuid() == 0 and _cage().network_wall(),
             "full_checks": None, "tier": "plain"}
    if probe["userns_netns"] and _quiet([unshare, "--user", "--map-root-user", "--mount", "--pid", "--fork", "--", "true"]):
        seen = _probe_sandbox()
        probe["full_checks"] = seen
        held = (seen.get("write_inside") == "ok" and seen.get("host_sees_inside_write") is True
                and seen.get("write_outside", "ok") != "ok" and seen.get("host_sees_outside_write") is False
                and seen.get("read_outside", "ok") != "ok" and seen.get("write_usr", "ok") != "ok"
                and seen.get("tcp_loopback", "ok") != "ok" and seen.get("host_listener_contacted") is False
                and seen.get("signal_host_pid", "ok") != "ok" and seen.get("remount_rw", "ok") != "ok"
                and seen.get("cap_eff") == "0000000000000000")
        probe["tier"] = "full" if held else "plain"
    return probe


def _strict_mount_probe():
    """One strict run of this interpreter: the mount table pid 1 read back. The workspace and any path
    under /tmp or a home directory are masked, because the evidence is public."""
    work = os.path.realpath(tempfile.mkdtemp(prefix="gaie-governor-mounts-"))
    try:
        ran = sandbox_run([os.path.realpath(sys.executable), "-I", "-S", "-c", "pass"], cwd=work, timeout=20,
                          allowed_paths=[work], require_fs_isolation=True)
    except GovernorDenied as exc:
        return {"error": exc.reason}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    private = ("/tmp", "/var/tmp", *_home_roots())

    def mask(path):
        if _is_inside(path, work):
            return "<workspace>"
        if path == "/tmp":  # the sandbox's own memory-backed /tmp
            return path
        return "<private>" if any(_is_inside(path, root) for root in private) else path

    table = ran.get("mounts") or {}
    rows = [[mask(at), "<workspace>" if mask(at) == "<workspace>" else mask(source), kind, mode]
            for at, source, kind, mode in table.get("mounts", [])]
    return {"returncode": ran["returncode"], "mounts": rows, "links": table.get("links", {}),
            "aliases": {mask(t): mask(s) for t, s in table.get("aliases", {}).items()}}


def isolation_report():
    """Public-safe evidence for the base namespace tier probe."""
    probe = isolation_probe()
    unshare = shutil.which("unshare", path=_cage().ENV["PATH"])
    version = ""
    if unshare:
        try:
            version = subprocess.run([unshare, "--version"], capture_output=True, text=True, timeout=10,
                                     env=dict(_cage().ENV)).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            version = ""
    full = probe["tier"] == "full"
    checks = probe["full_checks"] or {}
    return {
        "schema": "gaie-isolation/v1", "measured": True, "simulated": False,
        "measured_on": datetime.datetime.now(_UTC).strftime("%Y-%m-%d"),
        "tests": ["tests/test_governor.py"],
        "host": {"kernel": ".".join(platform.release().split(".")[:2]), "machine": platform.machine(),
                 "caller_is_root": probe["root"], "python": platform.python_version(), "unshare": version},
        "tier": probe["tier"],
        "probes": [
            {"name": "user+net namespace", "command": "unshare --user --map-root-user --net -- true",
             "result": probe["userns_netns"]},
            {"name": "root network namespace (cage.network_wall)", "command": "unshare -n true",
             "result": probe["root_netns"]},
            {"name": "full sandbox walls, checked from inside and from the host",
             "command": ("unshare --user --map-root-user --mount --propagation private --pid --fork --kill-child "
                         "--net -- python3 -I -B -S -c <governor._sandbox_init> <spec>; then python3 -I -S -c <probe>"),
             "result": checks},
            {"name": "strict run mount table, read back by pid 1 from /proc/self/mountinfo",
             "command": "governor.sandbox_run([<this interpreter>, '-I', '-S', '-c', 'pass'], require_fs_isolation=True)['mounts']",
             "result": _strict_mount_probe() if full else {"not_measured": "the full namespace sandbox is not available"}},
        ],
        "enforced": {
            "network_off_by_default": full or probe["userns_netns"] or probe["root_netns"],
            "filesystem_writes_only_in_allowed_paths": full,
            "host_files_outside_read_paths_hidden": full,
            "no_capabilities_in_sandbox": full,
            "own_pid_namespace": full,
            "empty_environment": True,
            "cpu_memory_file_nofile_limits": True,
            "own_process_group_killed_after_run": True,
            "process_count_limit": False,
            "strict_mounts_only_bin_stdlib_and_linked_libraries": full,
        },
        "not_enforced": [
            "number of processes: a sandbox mapped to uid 0 is exempt from RLIMIT_NPROC (bounded by timeout only)",
            "the base probe does not measure strict profile socket, filesystem or environment restrictions",
            "legacy calls can reach visible unix sockets and opt into the host network",
            "system runtime directories are read-only; legacy calls can also read host /etc",
            "strict runs filter only socket, io_uring_setup, unshare, clone with CLONE_NEWUSER and clone3; "
            "other kernel interfaces (keyctl, bpf, perf_event_open, userfaultfd) are not filtered",
            "legacy calls install no seccomp filter: a child can create a nested user namespace and hold a "
            "full capability set inside it (the mount walls are locked, measured in pr30-isolation F6)",
            "strict runs show the whole bin directory of a program installed outside the system directories and "
            "the whole standard library directory of a Python interpreter (site-packages included); the rest of "
            "its install prefix (share/, etc/, include/) stays hidden",
            "legacy and loopback calls mount the whole install prefix (the parent of bin/) of cmd[0] and of the "
            "hub's interpreter read-only; a cmd[0] prefix under a home directory or in a directory a non-root "
            "user can change is not mounted there (the program exits 127)",
            "strict runs resolve only cmd[0] on the host: a program the child starts itself (sh -c cc, make "
            "recipes), a #! interpreter (#!/usr/bin/python3, #!/usr/bin/env node) and every link through "
            "/etc/alternatives resolve inside the sandbox, where /etc and programs outside the system "
            "directories are hidden, and exit 127 (cc, gcc, /usr/bin/python3 and node from sh -c; npm)",
        ],
    }


if __name__ == "__main__":
    json.dump(isolation_report(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
