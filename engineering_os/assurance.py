"""Independent Engineering Assurance (GAIE layer L20): the reviewer of a change is never its producer.

    assign(producer, *, reviewer=None, paths=())   -> the independent reviewer role for a work item
    record(review, *, producer, reviewer, paths, deleted=(), commit=None, root, state_dir)
                                                   -> a source-bound review receipt in private state
    verify(key, *, root, state_dir)                -> VERIFIED while the receipt is intact, consistent,
                                                      independent and every bound file hashes the same
    gate(items, *, root, state_dir)                -> which work items hold a valid independent approval
    status(*, root, state_dir)                     -> every receipt in the state directory, verified

`assign` reuses `orchestrator.review_assignment` (a role with the `reviewer` flag in
governance/agent-roles.json first, else the testing capacity of the approval panel; never the
producer) and adds one rule: a role that owns any changed path (its `owns` patterns, compared with
`orchestrator.overlaps`) is not independent of that change. A requested reviewer that is the
producer, is unknown or owns a changed path is refused; without a request the next panel
candidate that owns none of the paths is chosen.

`record` turns a reviewer's findings document ({"key", "target", "verdict", "findings": [{"severity",
...}]}) into a receipt that binds the producer and reviewer roles, the subject commit (when given),
the SHA-256 of every reviewed file, the paths the change deletes, the verdict and the findings, a
`contract_receipt` valid under `contracts.validate_receipt`, and a `receipt_sha256` over its own body.
`verify` re-checks all of it against the files on disk and the current role registry; editing a
bound file withdraws VERIFIED, restoring the bytes restores it. `gate` fails a work item with no
VERIFIED receipt, a `block` verdict or any open critical/high finding.

What a receipt does NOT prove: who reviewed. Producer and reviewer are role ids asserted by the
caller under one OS account; the digests detect staleness (a bound file changed) and corruption (the
receipt was edited), they do not authenticate anyone, and whoever can write the state directory can
write a consistent receipt. It does not prove that the review was thorough, that its findings are
true or complete, or anything about files it does not bind. Receipts live outside Git, as 0600 files
in a 0700 directory (default $GAIE_HOME/assurance). Everything here is deterministic local code: no
model is called, nothing is simulated, nothing remote is touched; the CLI's `--base` runs read-only
`git rev-parse`, `git diff --name-only` and `git status`. Standard library only.
SPDX-License-Identifier: MIT
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import time

from .contracts import ContractError, canonical, sha256, validate_receipt
from .layers import LayerError, _state, load_roles
from .orchestration import SECRET, SLUG, CoordinationError, _atomic_write, _read_private, load_json
from .orchestrator import (CAPACITIES, PANEL_CANDIDATES, OrchestratorError, ReviewIndependenceError,
                           overlaps, review_assignment)

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE = "independent-assurance"
LAYER = "L20"
MODE = "deterministic"
STATE_SUBDIR = "assurance"
RECEIPT_KIND = "gaie-independent-review"
GATE_SCHEMA = "gaie.assurance-gate/1"
VERDICTS = ("approve", "approve-with-fixes", "block")
SEVERITIES = ("critical", "high", "medium", "low")
BLOCKING = frozenset({"critical", "high"})
FINDING_STATES = ("open", "fixed")
STATUSES = ("VERIFIED", "UNVERIFIED")
REVIEW_FIELDS = frozenset({"key", "target", "verdict", "findings"})
REVIEW_OPTIONAL = frozenset({"tried", "summary"})
RECEIPT_FIELDS = frozenset({
    "schema_version", "kind", "key", "target", "producer", "reviewer", "commit", "files", "deleted",
    "source_sha256", "verdict", "findings", "tried", "summary", "review_sha256", "authenticated", "at",
    "duration_ms", "contract_receipt", "receipt_sha256"})
GRANT_ID = "local-cli"
MAX_FILES = 4000
MAX_FINDINGS = 500
MAX_ITEMS = 200
MAX_TEXT = 20000
LIMITS = ("Producer and reviewer are role ids asserted by the caller; the digests detect staleness and "
          "corruption, they do not authenticate who reviewed.")
_COMMIT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REV = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@^~-]{0,199}$")
_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_UNSAFE_PATH = re.compile(r"[\x00-\x1f\x7f\\*?\[\]]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class AssuranceError(ValueError):
    """A request, review document, state location or work item is not acceptable; nothing was written."""


class IndependenceError(AssuranceError):
    """The reviewer would be the producer, or owns a path of the change under review."""


def _need(condition, message, error=AssuranceError):
    if not condition:
        raise error(message)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- inputs

def _relpath(value, what):
    """A canonical repository-relative file path: no absolute, `.`/`..`, `.git`, control or glob characters."""
    _need(isinstance(value, str) and 0 < len(value) <= 512, f"{what}: 1-512 characters")
    _need(not _UNSAFE_PATH.search(value), f"{what}: control, backslash or glob characters in {value!r}")
    parts = value.split("/")
    _need(all(parts) and not any(part in (".", "..", ".git") for part in parts),
          f"{what}: not a canonical repository-relative path: {value!r}")
    return value


def _path_list(values, what):
    _need(isinstance(values, (list, tuple)) and len(values) <= MAX_FILES, f"{what}: a list of up to {MAX_FILES} paths")
    result = [_relpath(value, what) for value in values]
    _need(len(set(result)) == len(result), f"{what}: duplicate path")
    return sorted(result)


def _text(value, what, limit=MAX_TEXT, *, minimum=0, line=False):
    _need(isinstance(value, str) and minimum <= len(value) <= limit, f"{what}: text of {minimum}-{limit} characters")
    _need(not (_CONTROL.search(value) or (line and ("\n" in value or "\r" in value or "\t" in value))),
          f"{what}: control characters")
    return value


def _value(value, what):
    if value is None or isinstance(value, bool) or (type(value) is int and abs(value) < 2 ** 53):
        return value
    if isinstance(value, str):
        return _text(value, what)
    if isinstance(value, list):
        _need(len(value) <= 200, f"{what}: up to 200 items")
        return [_text(item, f"{what} item", 2000) for item in value]
    raise AssuranceError(f"{what}: text, integer, boolean, null or a list of texts")


def check_review(document):
    """Validate a reviewer's findings document and return its normal form.

    Required: key (slug), target (one line), verdict (approve | approve-with-fixes | block), findings
    (objects with a severity critical | high | medium | low). Optional: tried (list of texts), summary.
    A finding keeps its fields; `id` defaults to F<n> and `status` to open (open | fixed). An approve
    verdict with an open critical/high finding contradicts itself and is refused, as is any
    credential-shaped text (redact it before recording)."""
    _need(isinstance(document, dict), "review: JSON object required")
    keys = set(document)
    _need(REVIEW_FIELDS <= keys <= REVIEW_FIELDS | REVIEW_OPTIONAL,
          f"review: fields {sorted(REVIEW_FIELDS)} are required and only {sorted(REVIEW_OPTIONAL)} are optional")
    key = document["key"]
    _need(isinstance(key, str) and SLUG.fullmatch(key), "review key: lower-case slug of up to 80 characters")
    target = _text(document["target"], "review target", 300, minimum=1, line=True)
    verdict = document["verdict"]
    _need(verdict in VERDICTS, f"review verdict: one of {list(VERDICTS)}")
    findings = document["findings"]
    _need(isinstance(findings, list) and len(findings) <= MAX_FINDINGS, f"review findings: list of up to {MAX_FINDINGS}")
    normal, ids = [], set()
    for number, finding in enumerate(findings, 1):
        _need(isinstance(finding, dict) and 0 < len(finding) <= 32, f"finding {number}: object with 1-32 fields")
        row = {}
        for name, value in finding.items():
            _need(isinstance(name, str) and _FIELD.fullmatch(name), f"finding {number}: field name {name!r}")
            row[name] = _value(value, f"finding {number}.{name}")
        _need(row.get("severity") in SEVERITIES, f"finding {number}: severity one of {list(SEVERITIES)}")
        row.setdefault("status", "open")
        _need(row["status"] in FINDING_STATES, f"finding {number}: status one of {list(FINDING_STATES)}")
        row.setdefault("id", f"F{number}")
        _need(isinstance(row["id"], str) and 0 < len(row["id"]) <= 80 and row["id"] not in ids,
              f"finding {number}: id must be unique text")
        ids.add(row["id"])
        normal.append(row)
    blocking = [row["id"] for row in normal if row["status"] == "open" and row["severity"] in BLOCKING]
    _need(not (verdict == "approve" and blocking),
          f"review {key}: verdict approve with open critical/high finding(s) {blocking}; use approve-with-fixes or block")
    tried = document.get("tried", [])
    _need(isinstance(tried, list) and len(tried) <= 200, "review tried: list of up to 200 texts")
    tried = [_text(item, "review tried item") for item in tried]
    summary = document.get("summary")
    if summary is not None:
        _text(summary, "review summary")
    result = {"key": key, "target": target, "verdict": verdict, "findings": normal, "tried": tried, "summary": summary}
    _need(not SECRET.search(canonical(document)), "review: credential-shaped text refused; redact it before recording")
    return result


def load_review(data):
    """Parse a findings document from JSON text or bytes: duplicate keys and NaN/Infinity are refused."""
    try:
        document = load_json(data)
    except (CoordinationError, ValueError) as exc:
        raise AssuranceError(f"review JSON refused: {exc}") from None
    return check_review(document)


def _commit(value):
    _need(value is None or (isinstance(value, str) and _COMMIT.fullmatch(value)),
          "commit: a full lower-case hexadecimal object id (40 or 64 characters) or null")
    return value


def open_findings(findings):
    """Count of open findings per severity."""
    return {severity: sum(1 for row in findings if row["status"] == "open" and row["severity"] == severity)
            for severity in SEVERITIES}


# ---------------------------------------------------------------- roles and independence

def _roles(roles=None):
    if roles is not None:
        return roles
    try:
        return load_roles(ROOT)
    except LayerError as exc:
        raise AssuranceError(f"role registry: {exc}") from None


def _owned(role, paths):
    return sorted(path for path in paths if any(overlaps(own, path) for own in role["owns"]))


def assign(producer, *, reviewer=None, paths=(), roles=None):
    """The independent reviewer role for a producer's change to `paths`.

    Refused (IndependenceError): a reviewer equal to the producer, a requested reviewer that owns a
    changed path, or no candidate that owns none of them. Unknown roles raise AssuranceError."""
    document = _roles(roles)
    by_id = {role["id"]: role for role in document["roles"]}
    _need(isinstance(producer, str) and producer in by_id, f"unknown producer role {producer!r}")
    _need(reviewer is None or (isinstance(reviewer, str) and reviewer in by_id), f"unknown reviewer role {reviewer!r}")
    _need(reviewer != producer, f"self-review refused: the reviewer {reviewer} is the producer", IndependenceError)
    paths = _path_list(paths, "paths")
    task = {"id": "assurance", "role": producer, **({"reviewer": reviewer} if reviewer else {})}
    try:
        base = review_assignment(task, roles=document)
    except ReviewIndependenceError as exc:
        raise IndependenceError(str(exc)) from None
    except OrchestratorError as exc:
        raise AssuranceError(str(exc)) from None
    skipped = []
    if reviewer is not None:
        owned = _owned(by_id[reviewer], paths)
        _need(not owned, f"reviewer {reviewer} owns {len(owned)} changed path(s): {', '.join(owned[:5])}",
              IndependenceError)
        chosen = reviewer
    else:
        candidates = [base["reviewer"], *base["panel"].values(),
                      *(rid for capacity in CAPACITIES for rid in PANEL_CANDIDATES[capacity])]
        chosen = None
        for rid in dict.fromkeys(candidates):
            if rid == producer or rid not in by_id:
                continue
            owned = _owned(by_id[rid], paths)
            if not owned:
                chosen = rid
                break
            skipped.append({"role": rid, "owns": owned[:5]})
        _need(chosen is not None, f"no independent reviewer for {producer}: every candidate owns a changed path",
              IndependenceError)
    return {"producer": producer, "reviewer": chosen, "requested": reviewer is not None, "skipped": skipped,
            "paths": len(paths), "independent": True,
            "rule": "reviewer flag first, then the testing/security/release panel; never the producer, "
                    "never a role that owns a changed path"}


# ---------------------------------------------------------------- files and state

def _file_state(root, relative):
    """("file", sha256) for an in-tree regular file reached without symlinks; ("absent", None) when no
    entry exists; ("unsafe", None) for a symlink on the way, a directory or any other file type.
    Each component is opened relative to its parent's descriptor with O_NOFOLLOW, so a directory
    swapped for a symlink between checks is refused too."""
    parts = relative.split("/")
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return "unsafe", None
    try:
        for part in parts[:-1]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                return "absent", None
            except OSError:  # ELOOP (a symlink) or ENOTDIR
                return "unsafe", None
            os.close(directory)
            directory = child
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return "absent", None
        except OSError:
            return "unsafe", None
    finally:
        os.close(directory)
    if not stat.S_ISREG(os.fstat(fd).st_mode):  # a directory, FIFO or device
        os.close(fd)
        return "unsafe", None
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return "file", digest.hexdigest()


def default_state_dir(environ=None):
    """$GAIE_HOME/assurance (default ~/.gaie/assurance); never inside a Git work tree."""
    environ = os.environ if environ is None else environ
    home = pathlib.Path(environ.get("GAIE_HOME") or pathlib.Path.home() / ".gaie").expanduser()
    return home / STATE_SUBDIR


def _state_dir(state_dir, *, create):
    try:  # layers._state: private 0700 user-owned directory, no symlinked ancestor, outside Git
        return _state(state_dir if state_dir is not None else default_state_dir(), create=create)
    except LayerError as exc:
        raise AssuranceError(str(exc)) from None


def _key(value):
    _need(isinstance(value, str) and SLUG.fullmatch(value), "key: lower-case slug of up to 80 characters")
    return value


def _request(key, target, producer, reviewer, commit, source):
    return sha256({"key": key, "target": target, "producer": producer, "reviewer": reviewer, "commit": commit,
                   "source_sha256": source})


def record(review, *, producer, reviewer, paths, deleted=(), commit=None, root=ROOT, state_dir=None, at=None,
           roles=None):
    """Write the source-bound receipt of one independent review to <state>/<key>.json (0600, atomic).

    `paths` are the reviewed files (each must be a regular in-tree file reached without symlinks);
    `deleted` the paths the change removes (each must be absent). A new record for the same key
    replaces the earlier receipt."""
    started = time.monotonic()
    normal = check_review(review)
    paths, deleted = _path_list(paths, "paths"), _path_list(deleted, "deleted")
    _need(paths or deleted, "record: at least one reviewed or deleted path")
    _need(len(paths) + len(deleted) <= MAX_FILES and not set(paths) & set(deleted),
          f"record: up to {MAX_FILES} distinct paths, none both reviewed and deleted")
    _commit(commit)
    _need(isinstance(reviewer, str), "record: the reviewer role is named, never implied")
    assignment = assign(producer, reviewer=reviewer, paths=paths + deleted, roles=_roles(roles))
    root = pathlib.Path(root).resolve()
    files = {}
    for relative in paths:
        kind, digest = _file_state(root, relative)
        _need(kind == "file", f"{relative}: {'missing' if kind == 'absent' else 'not a regular file reached without symlinks'}")
        files[relative] = digest
    for relative in deleted:
        _need(_file_state(root, relative)[0] == "absent", f"{relative}: listed as deleted but present")
    at = at or _now()
    _need(isinstance(at, str) and _AT.fullmatch(at), "at: ISO-8601 UTC (YYYY-MM-DDTHH:MM:SSZ)")
    state = _state_dir(state_dir, create=True)
    source = sha256({"files": files, "deleted": deleted})
    duration = max(0, min(86_399_999, int((time.monotonic() - started) * 1000)))
    body = {
        "schema_version": 1, "kind": RECEIPT_KIND, "key": normal["key"], "target": normal["target"],
        "producer": producer, "reviewer": reviewer, "commit": commit, "files": files, "deleted": deleted,
        "source_sha256": source, "verdict": normal["verdict"], "findings": normal["findings"],
        "tried": normal["tried"], "summary": normal["summary"], "review_sha256": sha256(review),
        "authenticated": False, "at": at, "duration_ms": duration,
        "contract_receipt": validate_receipt({
            "request_sha256": _request(normal["key"], normal["target"], producer, reviewer, commit, source),
            "result_sha256": sha256({"verdict": normal["verdict"], "findings": normal["findings"]}),
            "grant_id": GRANT_ID, "side_effect": "state-write", "duration_ms": duration, "at": at,
            "source_sha256": source}),
    }
    receipt = {**body, "receipt_sha256": sha256(body)}
    path = state / f"{normal['key']}.json"
    try:
        _atomic_write(path, receipt)
    except (CoordinationError, OSError) as exc:
        raise AssuranceError(f"receipt not written: {exc}") from None
    return {"key": normal["key"], "path": str(path), "receipt_sha256": receipt["receipt_sha256"],
            "verdict": normal["verdict"], "producer": producer, "reviewer": reviewer, "commit": commit,
            "files": len(files), "deleted": len(deleted), "open_findings": open_findings(normal["findings"]),
            "assignment": assignment, "authenticated": False, "limits": LIMITS}


# ---------------------------------------------------------------- verification

def check_receipt(receipt, *, root=ROOT, roles=None):
    """Status a receipt supports now: VERIFIED while it is intact, internally consistent, the reviewer
    is not the producer and owns no bound path, and every bound file still hashes the same (every
    deleted path still absent); otherwise UNVERIFIED with the reason."""
    root = pathlib.Path(root).resolve()

    def unverified(reason, changed=(), missing=()):
        return {"status": "UNVERIFIED", "reason": reason, "changed": sorted(changed), "missing": sorted(missing)}

    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        return unverified("receipt fields do not match the schema")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    try:
        intact = receipt["receipt_sha256"] == sha256(body)
    except (TypeError, ValueError):
        intact = False
    if not intact:
        return unverified("receipt digest mismatch (tampered or corrupt receipt)")
    if receipt["schema_version"] != 1 or receipt["kind"] != RECEIPT_KIND:
        return unverified("receipt is for another kind or schema")
    try:
        normal = check_review({"key": receipt["key"], "target": receipt["target"], "verdict": receipt["verdict"],
                               "findings": receipt["findings"], "tried": receipt["tried"],
                               **({"summary": receipt["summary"]} if receipt["summary"] is not None else {})})
        files, deleted = receipt["files"], receipt["deleted"]
        _need(isinstance(files, dict) and all(isinstance(v, str) and _DIGEST.fullmatch(v) for v in files.values()),
              "files: {path: sha256}")
        _path_list(list(files), "files")
        _need(_path_list(deleted, "deleted") == deleted and (files or deleted) and not set(files) & set(deleted),
              "files and deleted: distinct paths, deleted sorted, at least one")
        _commit(receipt["commit"])
        for field in ("producer", "reviewer"):
            _need(isinstance(receipt[field], str) and SLUG.fullmatch(receipt[field]), f"{field}: role id")
        _need(receipt["authenticated"] is False, "authenticated: always false")
        _need(isinstance(receipt["at"], str) and _AT.fullmatch(receipt["at"]), "at: ISO-8601 UTC")
        _need(type(receipt["duration_ms"]) is int and 0 <= receipt["duration_ms"] < 86_400_000, "duration_ms")
        _need(isinstance(receipt["review_sha256"], str) and _DIGEST.fullmatch(receipt["review_sha256"]), "review_sha256")
        validate_receipt(receipt["contract_receipt"])
    except (AssuranceError, ContractError) as exc:
        return unverified(f"receipt body invalid ({exc})")
    if normal["findings"] != receipt["findings"]:
        return unverified("receipt findings are not in normal form")
    source = sha256({"files": files, "deleted": deleted})
    contract = receipt["contract_receipt"]
    if (receipt["source_sha256"] != source or contract["source_sha256"] != source
            or contract["request_sha256"] != _request(receipt["key"], receipt["target"], receipt["producer"],
                                                      receipt["reviewer"], receipt["commit"], source)
            or contract["result_sha256"] != sha256({"verdict": receipt["verdict"], "findings": receipt["findings"]})
            or contract["side_effect"] != "state-write" or contract["at"] != receipt["at"]):
        return unverified("receipt digests are inconsistent with its body")
    producer, reviewer = receipt["producer"], receipt["reviewer"]
    if producer == reviewer:
        return unverified("self-review: the reviewer is the producer")
    try:
        by_id = {role["id"]: role for role in _roles(roles)["roles"]}
    except AssuranceError as exc:
        return unverified(str(exc))
    if producer not in by_id or reviewer not in by_id:
        return unverified("producer or reviewer is not a role of the current registry")
    owned = _owned(by_id[reviewer], [*files, *deleted])
    if owned:
        return unverified(f"reviewer {reviewer} owns {len(owned)} bound path(s); the review is not independent", owned)
    changed, missing = [], []
    for relative, digest in files.items():
        kind, now = _file_state(root, relative)
        if kind != "file":
            missing.append(relative)
        elif now != digest:
            changed.append(relative)
    changed += [relative for relative in deleted if _file_state(root, relative)[0] != "absent"]
    reasons = []
    if missing:
        reasons.append(f"missing file: {len(missing)} bound file(s) absent or not regular files reached without symlinks")
    if changed:
        reasons.append(f"stale receipt: {len(changed)} bound path(s) changed")
    if reasons:
        return unverified("; ".join(reasons), changed, missing)
    return {"status": "VERIFIED", "reason": None, "changed": [], "missing": []}


def load_receipt(key, *, state_dir=None):
    """(receipt, None) from <state>/<key>.json, or (None, reason). The file must be a regular, user-owned,
    single-link 0600 file opened without following a symlink; duplicate JSON keys are refused."""
    _key(key)
    state = _state_dir(state_dir, create=False)
    path = state / f"{key}.json" if state is not None else None
    if path is None or not (path.exists() or path.is_symlink()):
        return None, "no receipt"
    try:
        return _read_private(path), None
    except (CoordinationError, OSError, ValueError) as exc:
        return None, f"unreadable receipt ({type(exc).__name__}: {exc})"


def _row(key, receipt, current):
    good = current["status"] == "VERIFIED"
    return {"key": key, **current,
            "producer": receipt["producer"] if good else None, "reviewer": receipt["reviewer"] if good else None,
            "verdict": receipt["verdict"] if good else None, "commit": receipt["commit"] if good else None,
            "files": len(receipt["files"]) if good else 0, "deleted": len(receipt["deleted"]) if good else 0,
            "open_findings": open_findings(receipt["findings"]) if good else None,
            "at": receipt["at"] if good else None, "receipt_sha256": receipt["receipt_sha256"] if good else None}


def _verified(key, *, root, state_dir, roles):
    receipt, error = load_receipt(key, state_dir=state_dir)
    if receipt is None:
        current = {"status": "UNVERIFIED", "reason": error, "changed": [], "missing": []}
    else:
        current = check_receipt(receipt, root=root, roles=roles)
    return receipt, _row(key, receipt, current)


def verify(key, *, root=ROOT, state_dir=None, roles=None):
    """Verification row of the receipt stored for `key` (UNVERIFIED with a reason when there is none)."""
    return _verified(key, root=root, state_dir=state_dir, roles=roles)[1]


def status(*, root=ROOT, state_dir=None, roles=None):
    """Every <key>.json receipt in the state directory, verified; never creates state."""
    state = _state_dir(state_dir, create=False)
    if state is None:
        return []
    document = _roles(roles)
    keys = sorted(path.stem for path in state.iterdir() if path.suffix == ".json" and SLUG.fullmatch(path.stem))
    return [verify(key, root=root, state_dir=state, roles=document) for key in keys]


def _item(value):
    if isinstance(value, str):
        value = {"key": value}
    _need(isinstance(value, dict) and "key" in value and set(value) <= {"key", "producer", "paths", "commit"},
          "gate item: a key or {key, producer?, paths?, commit?}")
    item = {"key": _key(value["key"])}
    if value.get("producer") is not None:
        _need(isinstance(value["producer"], str) and SLUG.fullmatch(value["producer"]), "gate item producer: role id")
        item["producer"] = value["producer"]
    if value.get("paths") is not None:
        item["paths"] = _path_list(value["paths"], "gate item paths")
    if value.get("commit") is not None:
        item["commit"] = _commit(value["commit"])
    return item


def gate(items, *, root=ROOT, state_dir=None, roles=None):
    """Which work items hold a valid independent approval. An item passes only with a VERIFIED receipt
    whose verdict is not `block` and that has no open critical/high finding; when the item names a
    producer, paths or a commit, the receipt must match the producer and commit and bind every path.
    `passed` is true only when every item passes."""
    _need(isinstance(items, (list, tuple)) and 0 < len(items) <= MAX_ITEMS, f"gate: 1-{MAX_ITEMS} work items")
    items = [_item(value) for value in items]
    _need(len({item["key"] for item in items}) == len(items), "gate: duplicate work item key")
    document = _roles(roles)
    rows = []
    for item in items:
        receipt, row = _verified(item["key"], root=root, state_dir=state_dir, roles=document)
        reasons = [] if row["status"] == "VERIFIED" else [row["reason"]]
        if row["status"] == "VERIFIED":
            if row["verdict"] == "block":
                reasons.append("verdict is block")
            blocking = [f["id"] for f in receipt["findings"] if f["status"] == "open" and f["severity"] in BLOCKING]
            if blocking:
                reasons.append(f"{len(blocking)} open critical/high finding(s): {', '.join(blocking[:10])}")
            if "producer" in item and item["producer"] != row["producer"]:
                reasons.append(f"receipt producer {row['producer']} is not the work item producer {item['producer']}")
            if "commit" in item and item["commit"] != row["commit"]:
                reasons.append("receipt is for another commit")
            uncovered = sorted(set(item.get("paths", ())) - set(receipt["files"]) - set(receipt["deleted"]))
            if uncovered:
                reasons.append(f"receipt does not bind {len(uncovered)} path(s) of the work item: {', '.join(uncovered[:5])}")
        rows.append({**row, "approved": not reasons, "reasons": reasons})
    return {"schema": GATE_SCHEMA, "mode": MODE, "passed": all(row["approved"] for row in rows),
            "approved": [row["key"] for row in rows if row["approved"]],
            "not_approved": [row["key"] for row in rows if not row["approved"]],
            "items": rows, "authenticated": False, "limits": LIMITS}


# ---------------------------------------------------------------- engine contract

_READ = ["read:repo", "read:registry", "read:state", "secrets:none"]
ENGINE_RECORD = {
    "id": ENGINE, "layer": LAYER,
    "title": {"en": "Independent Engineering Assurance", "ar": "الضمان الهندسي المستقل"},
    "entrypoint": "engineering_os.assurance:engine", "health": "engineering_os.assurance:health",
    "actions": {
        "assign": {"side_effect": "none", "permissions": ["read:registry", "secrets:none"],
                   "summary": "Independent reviewer role for a producer's change; refuses self-review and path owners."},
        "record": {"side_effect": "state-write", "permissions": ["read:repo", "read:registry", "write:state", "secrets:none"],
                   "summary": "Write a source-bound review receipt (0600) under the private state directory, in assurance/."},
        "verify": {"side_effect": "none", "permissions": list(_READ),
                   "summary": "VERIFIED or UNVERIFIED with the reason for the stored review receipt of one key."},
        "gate": {"side_effect": "none", "permissions": list(_READ),
                 "summary": "Pass only work items with a VERIFIED independent approval and no open critical/high finding."},
        "status": {"side_effect": "none", "permissions": list(_READ),
                   "summary": "Verification rows of every stored review receipt; creates nothing."},
    },
    "supersedes": [],
}
ENGINE_ACTIONS = ENGINE_RECORD["actions"]
_PAYLOADS = {
    "assign": ({"producer"}, {"producer", "reviewer", "paths"}),
    "record": ({"review", "producer", "reviewer", "paths"}, {"review", "producer", "reviewer", "paths", "deleted", "commit"}),
    "verify": ({"key"}, {"key"}),
    "gate": ({"items"}, {"items"}),
    "status": (set(), set()),
}


def engine(action, payload, ctx=None):
    """Control-plane entrypoint ``(action, payload, ctx) -> dict``. Payloads are data, never instructions.
    Files are read under ctx["root"] (default: this checkout); receipts live in ctx["state_dir"]/assurance
    (default $GAIE_HOME/assurance)."""
    _need(isinstance(action, str) and action in ENGINE_ACTIONS, f"unknown action {action!r}; allowed {sorted(ENGINE_ACTIONS)}")
    _need(isinstance(payload, dict), "payload must be an object")
    required, allowed = _PAYLOADS[action]
    _need(required <= set(payload) <= allowed,
          f"{action}: payload keys must include {sorted(required)} and stay within {sorted(allowed)}")
    ctx = {} if ctx is None else ctx
    _need(isinstance(ctx, dict), "ctx must be an object")
    root = ctx.get("root") or ROOT
    state = (pathlib.Path(ctx["state_dir"]) / STATE_SUBDIR if ctx.get("state_dir")
             else default_state_dir(ctx.get("environ")))
    if action == "assign":
        result = assign(payload["producer"], reviewer=payload.get("reviewer"), paths=payload.get("paths", ()))
    elif action == "record":
        result = record(payload["review"], producer=payload["producer"], reviewer=payload["reviewer"],
                        paths=payload["paths"], deleted=payload.get("deleted", ()), commit=payload.get("commit"),
                        root=root, state_dir=state, at=ctx.get("now"))
    elif action == "verify":
        result = verify(payload["key"], root=root, state_dir=state)
    elif action == "gate":
        result = gate(payload["items"], root=root, state_dir=state)
    else:
        rows = status(root=root, state_dir=state)
        result = {"count": len(rows), "rows": rows}
    return {"ok": True, "engine": ENGINE, "action": action, "mode": MODE, "request_sha256": sha256(payload), "result": result}


def health():
    """Side-effect-free self check: no role is assigned itself, self-review is refused, a probe review validates."""
    try:
        document = _roles()
        ids = [role["id"] for role in document["roles"]]
        independent = all(assign(rid, roles=document)["reviewer"] != rid for rid in ids)
        try:
            assign(ids[0], reviewer=ids[0], roles=document)
            refused = False
        except IndependenceError:
            refused = True
        probe = check_review({"key": "health", "target": "probe", "verdict": "approve-with-fixes",
                              "findings": [{"severity": "high", "summary": "probe"}]})
        ok = independent and refused and open_findings(probe["findings"])["high"] == 1
    except Exception as error:  # health reports, never raises
        return {"ok": False, "detail": f"assurance self-check failed: {type(error).__name__}"}
    return {"ok": ok, "detail": f"{len(ids)} roles; none is assigned to review itself; self-review refused; "
                                f"receipts are digest-checked, not authenticated"}


# ---------------------------------------------------------------- CLI

def changed_since(root, base):
    """(HEAD commit, present paths, deleted paths) of `base...HEAD` in the Git checkout `root`, refusing
    when any changed path differs from HEAD in the working tree (so the commit and the bound bytes agree)."""
    from .workspace_policy import WorkspacePolicyError, _git
    _need(isinstance(base, str) and _REV.fullmatch(base), "--base: a plain Git revision (branch, tag or commit)")
    root = pathlib.Path(root).resolve()
    try:
        head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").strip()
        start = _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").strip()
        names = _git(root, "diff", "--name-only", "-z", "--no-renames", f"{start}...{head}")
    except WorkspacePolicyError:
        raise AssuranceError(f"git could not resolve {base}...HEAD in {root}") from None
    paths = _path_list(sorted({name for name in names.split("\0") if name}), "changed path")
    _need(paths, f"no changed paths between {base} and HEAD")
    try:
        dirty = _git(root, "--literal-pathspecs", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    except WorkspacePolicyError:
        raise AssuranceError("git status failed") from None
    _need(not dirty, "changed paths differ from HEAD in the working tree; commit them first")
    present, deleted = [], []
    for relative in paths:
        kind = _file_state(root, relative)[0]
        _need(kind != "unsafe", f"{relative}: not a regular file reached without symlinks")
        (present if kind == "file" else deleted).append(relative)
    return head, present, deleted


def _print(result, as_json, text):
    print(json.dumps(result, ensure_ascii=False, indent=2) if as_json else text)


def _verify_line(row):
    tail = f" ({row['verdict']}, reviewer {row['reviewer']}, producer {row['producer']})" if row["status"] == "VERIFIED" else ""
    return f"{row['key']:<32} {row['status']:<10}{tail}" + (f" - {row['reason']}" if row["reason"] else "")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m engineering_os.assurance", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=str(ROOT), help="tree whose files are bound (default: this checkout)")
    common.add_argument("--state", help="private receipt directory (default: $GAIE_HOME/assurance)")
    common.add_argument("--json", action="store_true")
    assign_cmd = commands.add_parser("assign", parents=[common], help="independent reviewer for a producer's change")
    assign_cmd.add_argument("--producer", required=True)
    assign_cmd.add_argument("--reviewer")
    assign_cmd.add_argument("--paths", nargs="+", default=[])
    record_cmd = commands.add_parser("record", parents=[common], help="turn a findings JSON into a review receipt")
    record_cmd.add_argument("--review", required=True, help="reviewer's findings JSON file")
    record_cmd.add_argument("--producer", required=True)
    record_cmd.add_argument("--reviewer", required=True)
    scope = record_cmd.add_mutually_exclusive_group(required=True)
    scope.add_argument("--paths", nargs="+", help="reviewed files (repository-relative)")
    scope.add_argument("--base", help="bind every path changed in BASE...HEAD and record the HEAD commit")
    record_cmd.add_argument("--deleted", nargs="+", default=[], help="with --paths: paths the change deletes")
    verify_cmd = commands.add_parser("verify", parents=[common], help="verify the stored receipt of a key")
    verify_cmd.add_argument("key")
    gate_cmd = commands.add_parser("gate", parents=[common], help="independent-approval gate over work items")
    gate_cmd.add_argument("keys", nargs="*")
    gate_cmd.add_argument("--items", help="JSON file: list of keys or {key, producer?, paths?, commit?}")
    commands.add_parser("status", parents=[common], help="verify every stored receipt")
    args = parser.parse_args(argv)
    state = pathlib.Path(args.state).expanduser() if args.state else None
    try:
        if args.cmd == "assign":
            result = assign(args.producer, reviewer=args.reviewer, paths=args.paths)
            _print(result, args.json, f"reviewer: {result['reviewer']} (producer {result['producer']}, "
                                      f"{result['paths']} changed path(s))")
            return 0
        if args.cmd == "record":
            review_path = pathlib.Path(args.review)
            _need(review_path.is_file() and not review_path.is_symlink(), f"{args.review}: regular file required")
            document = load_json(review_path.read_bytes())
            if args.base:
                _need(not args.deleted, "--deleted is computed from git with --base")
                commit, paths, deleted = changed_since(args.root, args.base)
            else:
                commit, paths, deleted = None, args.paths, args.deleted
            result = record(document, producer=args.producer, reviewer=args.reviewer, paths=paths, deleted=deleted,
                            commit=commit, root=args.root, state_dir=state)
            _print(result, args.json, f"recorded {result['key']}: {result['verdict']}, reviewer {result['reviewer']}, "
                                      f"producer {result['producer']}, {result['files']} file(s) and "
                                      f"{result['deleted']} deletion(s) bound -> {result['path']}")
            return 0
        if args.cmd == "verify":
            row = verify(args.key, root=args.root, state_dir=state)
            _print(row, args.json, _verify_line(row))
            return 0 if row["status"] == "VERIFIED" else 1
        if args.cmd == "gate":
            _need(bool(args.keys) != bool(args.items), "gate: give keys or --items, not both")
            items = args.keys or load_json(pathlib.Path(args.items).read_bytes())
            result = gate(items, root=args.root, state_dir=state)
            lines = [f"{row['key']:<32} {'APPROVED' if row['approved'] else 'NOT APPROVED'}"
                     + (f" - {'; '.join(row['reasons'])}" if row["reasons"] else "") for row in result["items"]]
            _print(result, args.json, "\n".join(lines + [f"gate: {'PASSED' if result['passed'] else 'FAILED'}"]))
            return 0 if result["passed"] else 1
        rows = status(root=args.root, state_dir=state)
        _print({"count": len(rows), "rows": rows}, args.json, "\n".join(map(_verify_line, rows)) or "no receipts")
        return 0
    except (AssuranceError, CoordinationError, OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
