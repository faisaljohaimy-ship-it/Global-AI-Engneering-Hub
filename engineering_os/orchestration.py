"""Private, file-backed task coordination. This protocol does not run agents.

State must live outside Git in a user-owned directory with mode 0700. Actors are
caller-supplied assertions under that OS account, not authenticated identities.
Leases fence coordinator writes, not arbitrary edits made outside this protocol.
"""

import argparse
import contextlib
import copy
import fcntl
import hashlib
import json
import math
import os
import pathlib
import re
import stat
import sys
import time
import uuid

ROLES = frozenset({"orchestrator", "architecture", "development", "database",
                   "security", "testing", "devops", "performance", "cinematic",
                   "research", "release"})
ENGINES = frozenset({"codex", "claude-code"})
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
DIGEST = re.compile(r"[a-f0-9]{64}")
SECRET = re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}|(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{40,}|(?<![A-Za-z0-9])sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}|(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])|(?<![A-Za-z0-9])sb_secret_[A-Za-z0-9_-]{20,}|(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{10,}|(?<![A-Za-z0-9])(?:sk|rk)_live_[A-Za-z0-9]{20,}|(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
MAX_BYTES = 8 * 1024 * 1024


class CoordinationError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise CoordinationError("Duplicate JSON key")
        result[key] = value
    return result


def load_json(data):
    return json.loads(data, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(CoordinationError("Invalid JSON number")))


def _text(value, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise CoordinationError("Invalid text length")
    if SECRET.search(value) or any(ord(char) < 32 for char in value):
        raise CoordinationError("Credential-shaped or control text refused")
    return value


def _slug(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value) or SECRET.search(value):
        raise CoordinationError("Invalid identifier")
    return value


def _number(value, minimum=0, maximum=2**53-1):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum or not math.isfinite(value):
        raise CoordinationError("Invalid finite number")
    return value


def _version(value):
    if type(value) is not int or value < 0:
        raise CoordinationError("Invalid version")
    return value


def _actor(value):
    if not isinstance(value, dict) or set(value) != {"id", "engine", "role"}:
        raise CoordinationError("Actor requires id, engine and role only")
    _slug(value["id"])
    if not isinstance(value["engine"], str) or not isinstance(value["role"], str) or value["engine"] not in ENGINES or value["role"] not in ROLES:
        raise CoordinationError("Unknown engine or role")
    return copy.deepcopy(value)


def _scope(value):
    if not isinstance(value, list) or not value or len(value) > 200:
        raise CoordinationError("Task needs bounded file scope")
    result = []
    for item in value:
        _text(item, 256)
        path = pathlib.PurePosixPath(item)
        if path.is_absolute() or ".." in path.parts or ".git" in path.parts or "\\" in item or any(char in item for char in "*?[]"):
            raise CoordinationError("Unsafe task file scope")
        if not path.parts or item.startswith("./") or "//" in item:
            raise CoordinationError("Noncanonical task file scope")
        result.append(item.rstrip("/"))
    if len(set(result)) != len(result):
        raise CoordinationError("Duplicate scope")
    return sorted(result)


def _branch(value):
    _text(value, 128)
    if not isinstance(value, str) or not re.fullmatch(r"(?:codex|claude)/[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", value):
        raise CoordinationError("Use an isolated codex/ or claude/ branch")
    if any(part in {"", ".", ".."} or part.startswith(".") or part.endswith(".lock") for part in value.split("/")) or ".." in value or value.endswith("."):
        raise CoordinationError("Unsafe branch")
    return value


def _receipts(value):
    if not isinstance(value, list) or not value or len(value) > 50:
        raise CoordinationError("Evidence receipt list required")
    result = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"kind", "sha256"}:
            raise CoordinationError("Evidence contains digests, not payloads or secrets")
        _slug(row["kind"])
        if not isinstance(row["sha256"], str) or not DIGEST.fullmatch(row["sha256"]):
            raise CoordinationError("Invalid evidence digest")
        result.append(copy.deepcopy(row))
    return result


def _safe_directory(path):
    path = pathlib.Path(path).absolute()
    for ancestor in [path, *path.parents]:
        if ancestor.is_symlink():
            raise CoordinationError("Symlink state directory refused")
        marker = ancestor / ".git"
        if marker.is_file() or (marker.is_dir() and (marker / "HEAD").exists()):
            raise CoordinationError("Task state must remain outside Git repositories")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise CoordinationError("State directory must be user-owned mode 0700")
    return path


def _open_private(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise CoordinationError("Unsafe state file permissions, owner or links")
    return fd


def _atomic_write(path, value, exclusive=False):
    data = canonical(value) + b"\n"
    if len(data) > MAX_BYTES:
        raise CoordinationError("State exceeds bounded file size")
    if path.is_symlink():
        raise CoordinationError("Symlink state file refused")
    if path.exists():
        fd = _open_private(path, os.O_RDONLY)
        os.close(fd)
    temporary = path.parent / (".write-" + uuid.uuid4().hex)
    try:
        fd = _open_private(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _read_private(path):
    fd = _open_private(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise CoordinationError("Oversized state file")
    return load_json(data)


PRODUCING = frozenset({"claim", "renew", "handover", "submit", "fail"})


def producers(state, task_id):
    """Every actor id that ever held or worked ``task_id``: claim, renew, handover, submit or fail.

    Read from the hash-chained audit events, so a handover or a fail-and-recover never
    clears it; review independence is checked against all of them, not the current owner.
    """
    return {event["actor"]["id"] for event in state["events"] if event["task"] == task_id and event["operation"] in PRODUCING}


def verify_state(state):
    if not isinstance(state, dict) or set(state) != {"schema_version", "revision", "tasks", "events"} or state["schema_version"] != 1:
        raise CoordinationError("Invalid state schema")
    _version(state["revision"])
    if not isinstance(state["tasks"], dict) or not isinstance(state["events"], list) or state["revision"] != len(state["events"]):
        raise CoordinationError("Invalid state revision")
    for key, task in state["tasks"].items():
        _validate_task(task)
        if key != task["id"]:
            raise CoordinationError("Task key/identity mismatch")
    previous = "0" * 64
    for index, event in enumerate(state["events"], 1):
        if not isinstance(event, dict) or set(event) != {"sequence", "at", "operation", "task", "actor", "details", "tasks_sha256", "previous", "sha256"}:
            raise CoordinationError("Invalid audit event")
        _number(event["at"])
        _actor(event["actor"])
        _slug(event["task"])
        if event["task"] not in state["tasks"] or event["operation"] not in {"create", "claim", "renew", "handover", "submit", "review", "fail", "recover"}:
            raise CoordinationError("Unknown audit operation/task")
        if not DIGEST.fullmatch(str(event["tasks_sha256"])):
            raise CoordinationError("Invalid task digest")
        details = event["details"]
        if event["operation"] == "review":
            if not isinstance(details, dict) or set(details) != {"decision"} or details["decision"] not in {"approved", "rejected"}:
                raise CoordinationError("Invalid review audit details")
        elif event["operation"] == "recover":
            if not isinstance(details, dict) or set(details) != {"receipts"}:
                raise CoordinationError("Invalid recovery details")
            _receipts(details["receipts"])
        elif details != {}:
            raise CoordinationError("Unexpected audit payload")
        if event["sequence"] != index or event["previous"] != previous:
            raise CoordinationError("Broken audit chain")
        calculated = sha({key: value for key, value in event.items() if key != "sha256"})
        if event["sha256"] != calculated:
            raise CoordinationError("Changed audit event")
        previous = calculated
    if state["events"]:
        if state["events"][-1]["tasks_sha256"] != sha(state["tasks"]):
            raise CoordinationError("Task data differs from audit receipt")
    elif state["tasks"]:
        raise CoordinationError("Tasks without audit evidence")
    worked = {}
    for event in state["events"]:
        if event["operation"] in PRODUCING:
            worked.setdefault(event["task"], set()).add(event["actor"]["id"])
    for key, task in state["tasks"].items():
        if any(row["actor"]["id"] in worked.get(key, ()) for row in task["approvals"].values()):
            raise CoordinationError("A reviewer of this task also held or worked it")
    return True


def _validate_task(task):
    fields = {"id", "project", "branch", "paths", "title", "priority", "role", "engine", "status", "created_at", "updated_at", "owner", "lease", "receipts", "approvals", "handover", "failures", "version"}
    if not isinstance(task, dict) or set(task) != fields:
        raise CoordinationError("Invalid persisted task fields")
    _slug(task["id"])
    _slug(task["project"])
    _branch(task["branch"])
    if _scope(task["paths"]) != task["paths"]:
        raise CoordinationError("Noncanonical persisted scope")
    _text(task["title"])
    if not isinstance(task["role"], str) or task["role"] not in ROLES or task["engine"] is not None and (not isinstance(task["engine"], str) or task["engine"] not in ENGINES):
        raise CoordinationError("Invalid task role or engine constraint")
    if type(task["priority"]) is not int or not 0 <= task["priority"] <= 3:
        raise CoordinationError("Invalid task priority")
    if task["status"] not in {"pending", "active", "handover", "review", "done", "failed", "blocked"}:
        raise CoordinationError("Invalid task state")
    _number(task["created_at"])
    _number(task["updated_at"])
    _version(task["version"])
    _version(task["failures"])
    if task["owner"] is not None:
        _actor(task["owner"])
    if task["status"] in {"active", "review", "done", "handover", "failed", "blocked"} and task["owner"] is None:
        raise CoordinationError("Working task lacks owner")
    if task["status"] == "active":
        lease = task["lease"]
        if not isinstance(lease, dict) or set(lease) != {"id", "expires_at"} or not re.fullmatch(r"[a-f0-9]{32}", str(lease["id"])):
            raise CoordinationError("Invalid task lease")
        _number(lease["expires_at"])
    elif task["lease"] is not None:
        raise CoordinationError("Non-active task retains lease")
    if task["receipts"] != []:
        _receipts(task["receipts"])
    if not isinstance(task["approvals"], dict) or not set(task["approvals"]) <= {"testing", "security", "release"}:
        raise CoordinationError("Invalid task approvals")
    reviewers = set()
    for role, approval in task["approvals"].items():
        if not isinstance(approval, dict) or set(approval) != {"actor", "decision", "receipts", "at"}:
            raise CoordinationError("Invalid approval record")
        reviewer = _actor(approval["actor"])
        if task["owner"] is None or reviewer["role"] != role or reviewer["id"] in reviewers or reviewer["id"] == task["owner"]["id"] or approval["decision"] not in {"approved", "rejected"}:
            raise CoordinationError("Invalid independent reviewer")
        reviewers.add(reviewer["id"])
        _receipts(approval["receipts"])
        _number(approval["at"])
    if task["status"] == "done" and (set(task["approvals"]) != {"testing", "security", "release"} or any(row["decision"] != "approved" for row in task["approvals"].values())):
        raise CoordinationError("Done task lacks all independent approvals")
    if task["handover"] is not None:
        row = task["handover"]
        if not isinstance(row, dict) or set(row) != {"from", "note", "receipts", "at"}:
            raise CoordinationError("Invalid handover record")
        _actor(row["from"])
        _text(row["note"], 1000)
        _receipts(row["receipts"])
        _number(row["at"])


class TaskStore:
    """Local ownership protocol with atomic state and compare-and-swap transitions."""

    def __init__(self, state_dir, clock=time.time):
        self.directory = _safe_directory(state_dir)
        self.path = self.directory / "state.json"
        self.clock = clock
        with self._locked():
            if not self.path.exists():
                _atomic_write(self.path, {"schema_version": 1, "revision": 0, "tasks": {}, "events": []})
            self._load()

    @contextlib.contextmanager
    def _locked(self):
        _safe_directory(self.directory)
        fd = _open_private(self.directory / "store.lock", os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _load(self):
        state = _read_private(self.path)
        verify_state(state)
        return state

    def snapshot(self):
        with self._locked():
            return copy.deepcopy(self._load())

    def tasks(self):
        return sorted(self.snapshot()["tasks"].values(), key=lambda row: (row["priority"], row["created_at"], row["id"]))

    def route(self, actor):
        """Recommend highest-priority claimable task; claim still performs atomic CAS."""
        actor = _actor(actor)
        tasks = self.tasks()
        occupied = {(row["project"], row["branch"]) for row in tasks if row["status"] == "active"}
        for task in tasks:
            if task["status"] in {"pending", "handover"} and task["role"] == actor["role"] and task["engine"] in {None, actor["engine"]} and (task["project"], task["branch"]) not in occupied:
                return task
        return None

    def _mutate(self, operation, task_id, actor, expected_version, change, expected_revision=None, details=None):
        actor = _actor(actor)
        now = _number(self.clock())
        with self._locked():
            state = self._load()
            if expected_revision is not None and state["revision"] != _version(expected_revision):
                raise CoordinationError("Stale store revision")
            task = state["tasks"].get(task_id)
            if task is not None:
                if task["version"] != _version(expected_version):
                    raise CoordinationError("Stale task version")
            elif operation != "create":
                raise CoordinationError("Unknown task")
            result = change(state, task, actor, now)
            result["version"] = 1 if task is None else task["version"] + 1
            result["updated_at"] = now
            state["tasks"][task_id] = result
            event = {"sequence": state["revision"] + 1, "at": now,
                     "operation": operation, "task": task_id, "actor": actor,
                     "details": details or {}, "tasks_sha256": sha(state["tasks"]),
                     "previous": state["events"][-1]["sha256"] if state["events"] else "0" * 64}
            event["sha256"] = sha(event)
            state["events"].append(event)
            state["revision"] += 1
            _atomic_write(self.path, state)
            return copy.deepcopy(result)

    def create_task(self, specification, actor, expected_revision):
        required = {"id", "project", "branch", "paths", "title", "priority"}
        if not isinstance(specification, dict) or not required <= set(specification) or not set(specification) <= required | {"role", "engine"}:
            raise CoordinationError("Task specification has unknown or missing fields")
        _slug(specification["id"])
        _slug(specification["project"])
        _branch(specification["branch"])
        scope = _scope(specification["paths"])
        _text(specification["title"])
        role, engine = specification.get("role", "development"), specification.get("engine")
        if not isinstance(role, str) or role not in ROLES or engine is not None and (not isinstance(engine, str) or engine not in ENGINES):
            raise CoordinationError("Invalid role or engine constraint")
        if type(specification["priority"]) is not int or not 0 <= specification["priority"] <= 3:
            raise CoordinationError("Priority must be P0 through P3 as integer")
        def change(state, task, owner, now):
            if owner["role"] != "orchestrator" or task is not None:
                raise CoordinationError("Only orchestrator creates a new unique task")
            return {**copy.deepcopy(specification), "paths": scope, "role": role, "engine": engine, "status": "pending",
                    "created_at": now, "updated_at": now, "owner": None, "lease": None,
                    "receipts": [], "approvals": {}, "handover": None, "failures": 0}
        return self._mutate("create", specification["id"], actor, 0, change,
                            expected_revision=expected_revision)

    @staticmethod
    def _lease(task, actor, lease_id, now):
        if task["status"] != "active" or task["owner"] != actor or not task["lease"] or task["lease"]["id"] != lease_id or task["lease"]["expires_at"] <= now:
            raise CoordinationError("Missing, stale or foreign task lease")

    def claim(self, task_id, actor, expected_version, ttl=900):
        _number(ttl, 1, 3600)
        def change(state, task, owner, now):
            if task["status"] not in {"pending", "handover"}:
                raise CoordinationError("Task is not claimable; recover expired work explicitly")
            if task["role"] != owner["role"] or task["engine"] not in {None, owner["engine"]}:
                raise CoordinationError("Task role or engine does not permit this actor")
            for other in state["tasks"].values():
                if other["id"] != task_id and other["project"] == task["project"] and other["branch"] == task["branch"] and other["status"] == "active":
                    raise CoordinationError("Branch is owned by another active task")
            task["owner"] = owner
            task["status"] = "active"
            task["lease"] = {"id": uuid.uuid4().hex, "expires_at": now + ttl}
            task["approvals"] = {}
            return task
        return self._mutate("claim", task_id, actor, expected_version, change)

    def renew(self, task_id, actor, expected_version, lease_id, ttl=900):
        _number(ttl, 1, 3600)
        def change(state, task, owner, now):
            self._lease(task, owner, lease_id, now)
            task["lease"]["expires_at"] = now + ttl
            return task
        return self._mutate("renew", task_id, actor, expected_version, change)

    def handover(self, task_id, actor, expected_version, lease_id, note, receipts):
        _text(note, 1000)
        receipts = _receipts(receipts)
        def change(state, task, owner, now):
            self._lease(task, owner, lease_id, now)
            task["status"] = "handover"
            task["lease"] = None
            task["handover"] = {"from": owner, "note": note, "receipts": receipts, "at": now}
            return task
        return self._mutate("handover", task_id, actor, expected_version, change)

    def submit(self, task_id, actor, expected_version, lease_id, receipts):
        receipts = _receipts(receipts)
        def change(state, task, owner, now):
            self._lease(task, owner, lease_id, now)
            task["status"] = "review"
            task["lease"] = None
            task["receipts"] = receipts
            return task
        return self._mutate("submit", task_id, actor, expected_version, change)

    def review(self, task_id, actor, expected_version, decision, receipts):
        if not isinstance(decision, str) or decision not in {"approved", "rejected"}:
            raise CoordinationError("Unknown review decision")
        receipts = _receipts(receipts)
        def change(state, task, reviewer, now):
            if task["status"] != "review" or reviewer["role"] not in {"testing", "security", "release"} or reviewer["id"] == task["owner"]["id"]:
                raise CoordinationError("Independent testing/security/release reviewer required")
            if reviewer["id"] in producers(state, task_id) | ({task["handover"]["from"]["id"]} if task["handover"] else set()):
                raise CoordinationError("A reviewer may not have held or worked this task (claim, renew, handover, submit or fail)")
            if any(row["actor"]["id"] == reviewer["id"] for role, row in task["approvals"].items() if role != reviewer["role"]):
                raise CoordinationError("A reviewer cannot approve multiple independent roles")
            task["approvals"][reviewer["role"]] = {"actor": reviewer, "decision": decision,
                                                       "receipts": receipts, "at": now}
            if decision == "rejected":
                task["status"] = "blocked"
            elif set(task["approvals"]) == {"testing", "security", "release"} and all(row["decision"] == "approved" for row in task["approvals"].values()):
                task["status"] = "done"
            return task
        return self._mutate("review", task_id, actor, expected_version, change,
                            details={"decision": decision})

    def fail(self, task_id, actor, expected_version, lease_id, receipts):
        receipts = _receipts(receipts)
        def change(state, task, owner, now):
            self._lease(task, owner, lease_id, now)
            task["status"] = "failed"
            task["lease"] = None
            task["receipts"] = receipts
            task["failures"] += 1
            return task
        return self._mutate("fail", task_id, actor, expected_version, change)

    def recover(self, task_id, actor, expected_version, receipts):
        receipts = _receipts(receipts)
        def change(state, task, owner, now):
            expired = task["status"] == "active" and task["lease"] and task["lease"]["expires_at"] <= now
            if owner["role"] != "orchestrator" or not (expired or task["status"] in {"failed", "blocked"}):
                raise CoordinationError("Recovery requires orchestrator and failed/blocked/expired work")
            task["status"] = "pending"
            task["lease"] = None
            task["owner"] = None
            task["approvals"] = {}
            task["receipts"] = []
            return task
        return self._mutate("recover", task_id, actor, expected_version, change,
                            details={"receipts": receipts})

    def checkpoint(self, destination):
        destination = pathlib.Path(destination).absolute()
        _safe_directory(destination.parent)
        if destination.exists() or destination.is_symlink():
            raise CoordinationError("Checkpoint destination already exists")
        state = self.snapshot()
        checkpoint = {"schema_version": 1, "state": state, "state_sha256": sha(state)}
        _atomic_write(destination, checkpoint, exclusive=True)
        return {"path": str(destination), "revision": state["revision"], "state_sha256": checkpoint["state_sha256"]}

    def restore(self, checkpoint):
        checkpoint = pathlib.Path(checkpoint).absolute()
        _safe_directory(checkpoint.parent)
        value = _read_private(checkpoint)
        if not isinstance(value, dict) or set(value) != {"schema_version", "state", "state_sha256"} or value["schema_version"] != 1 or sha(value["state"]) != value["state_sha256"]:
            raise CoordinationError("Checkpoint checksum/schema mismatch")
        verify_state(value["state"])
        with self._locked():
            existing = self._load()
            if existing["revision"] or existing["tasks"]:
                raise CoordinationError("Restore only into a new empty store")
            _atomic_write(self.path, value["state"])
        return {"revision": value["state"]["revision"], "state_sha256": value["state_sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=pathlib.Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    create = commands.add_parser("create")
    create.add_argument("--spec", required=True, type=pathlib.Path)
    create.add_argument("--revision", required=True, type=int)
    for name in ["create", "route", "claim", "renew", "handover", "submit", "review", "fail", "recover"]:
        command = create if name == "create" else commands.add_parser(name)
        command.add_argument("--actor", required=True)
        command.add_argument("--engine", required=True, choices=sorted(ENGINES))
        command.add_argument("--role", required=True, choices=sorted(ROLES))
        if name not in {"create", "route"}:
            command.add_argument("--task", required=True)
            command.add_argument("--version", required=True, type=int)
        if name in {"claim", "renew"}:
            command.add_argument("--ttl", type=int, default=900)
        if name in {"renew", "handover", "submit", "fail"}:
            command.add_argument("--lease", required=True)
        if name in {"handover", "submit", "review", "fail", "recover"}:
            command.add_argument("--receipts", required=True, type=pathlib.Path)
        if name == "handover":
            command.add_argument("--note", required=True)
        if name == "review":
            command.add_argument("--decision", choices=["approved", "rejected"], required=True)
    checkpoint = commands.add_parser("checkpoint")
    checkpoint.add_argument("--output", required=True, type=pathlib.Path)
    restore = commands.add_parser("restore")
    restore.add_argument("--input", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        def read_metadata(path):
            with path.open("rb") as stream:
                data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise CoordinationError("Oversized metadata file")
            return load_json(data)
        store = TaskStore(args.state_dir)
        if args.command == "status":
            value = store.snapshot()
            result = {"revision": value["revision"], "tasks": store.tasks(), "audit_verified": verify_state(value), "runtime": "manual local coordination; no daemon"}
        elif args.command == "checkpoint":
            result = store.checkpoint(args.output)
        elif args.command == "restore":
            result = store.restore(args.input)
        else:
            actor = {"id": args.actor, "engine": args.engine, "role": args.role}
            if args.command == "create":
                result = store.create_task(read_metadata(args.spec), actor, args.revision)
            elif args.command == "route":
                result = {"task": store.route(actor), "claimed": False}
            else:
                parameters = {"task_id": args.task, "actor": actor, "expected_version": args.version}
                if hasattr(args, "ttl"):
                    parameters["ttl"] = args.ttl
                if hasattr(args, "lease"):
                    parameters["lease_id"] = args.lease
                if hasattr(args, "receipts"):
                    parameters["receipts"] = read_metadata(args.receipts)
                if hasattr(args, "note"):
                    parameters["note"] = args.note
                if hasattr(args, "decision"):
                    parameters["decision"] = args.decision
                result = getattr(store, args.command)(**parameters)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (CoordinationError, OSError, KeyError, TypeError, json.JSONDecodeError):
        print("Coordination request failed; inspect private state and validated arguments.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
