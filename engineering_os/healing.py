"""Self-Healing & Recovery engine (L17): diagnostics, artifact checks and the governed loop.

``analyze`` and ``verify_repair`` never execute candidate code: they rank supplied
evidence and prove artifact properties of disposable copies. ``heal`` runs the
governed loop DISCOVER -> ANALYZE -> DESIGN -> IMPLEMENT -> TEST -> CRITIQUE -> REPAIR
-> VALIDATE over a target directory. It executes the target's own tests and app only
inside an isolated copy in ``workdir`` through ``detectors.Sandbox`` (child process,
fixed driver, loopback-only socket guard, timeouts; not an OS sandbox). The original
target is never written; the result is a unified diff, rollback data and a hash-chained
receipt per stage. No shell, provider, model or production environment is used.
Caller-supplied evidence needs a trusted collector; hashes do not authenticate it.
SPDX-License-Identifier: MIT
"""

import ast
import copy
import difflib
import hashlib
import keyword
import math
import os
import pathlib
import re
import shutil
import sqlite3
import tempfile
import time

from . import detectors
from .orchestration import DIGEST, SECRET, SLUG, _text, canonical, sha
from .reasoning import ReasoningError, root_causes
from scripts.security_scan import secret_findings

MAX_FILES = 50
MAX_CONTENT_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_ROWS = 200
VERSION = 1


class HealingError(ValueError):
    """Malformed or unbound healing evidence."""


def _fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise HealingError("Unknown or missing fields")


def _slug(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise HealingError("Invalid identifier")
    _text(value, 80)
    return value


def _digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise HealingError("Invalid SHA256")
    return value


def _finite(value, low=0, high=1e12):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not low <= value <= high or not math.isfinite(value):
        raise HealingError("Invalid finite metric")
    return value


def _rows(value):
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        raise HealingError("Bounded evidence list required")
    return value


def _tests(value):
    if not isinstance(value, dict) or not value or len(value) > MAX_ROWS:
        raise HealingError("Bounded test outcomes required")
    for key, outcome in value.items():
        _slug(key)
        if outcome not in ("passed", "failed"):
            raise HealingError("Unknown test outcome")
    return value


def analyze(request, *, now=None):
    """Return ranked hypotheses and proposals; never apply or deploy a repair.

    Request fields and result are versioned metadata shared by both agent hosts.
    Baseline test removal counts as a regression, not a successful smaller suite.
    """
    _fields(request, {"schema_version", "project", "source_sha256", "baseline_sha256", "baseline_tests", "current_tests", "failures", "performance", "dependencies", "evidence"})
    if type(request["schema_version"]) is not int or request["schema_version"] != VERSION:
        raise HealingError("Unknown schema version")
    project = _slug(request["project"])
    source, baseline = _digest(request["source_sha256"]), _digest(request["baseline_sha256"])
    before, after = _tests(request["baseline_tests"]), _tests(request["current_tests"])
    evidence = request["evidence"]
    _fields(evidence, {"project", "source_sha256", "baseline_sha256", "at", "sha256"})
    _digest(evidence["sha256"])
    at, current = _finite(evidence["at"]), _finite(time.time() if now is None else now)
    if evidence["project"] != project or evidence["source_sha256"] != source or evidence["baseline_sha256"] != baseline:
        raise HealingError("Evidence project or revision mismatch")
    if at > current or current - at > 86400:
        raise HealingError("Stale or future evidence")

    failures = {}
    for row in _rows(request["failures"]):
        _fields(row, {"id", "component", "kind", "error_sha256", "depends_on"})
        key = _slug(row["id"])
        _slug(row["component"])
        if row["kind"] not in {"test", "runtime", "dependency", "security", "performance"}:
            raise HealingError("Unknown failure kind")
        _digest(row["error_sha256"])
        deps = _rows(row["depends_on"])
        if any(_slug(item) == key for item in deps) or len(set(deps)) != len(deps) or key in failures:
            raise HealingError("Duplicate or self-referencing failure")
        failures[key] = row
    if any(dep not in failures for row in failures.values() for dep in row["depends_on"]):
        raise HealingError("Unknown failure dependency")
    pending, ordered = set(failures), []
    while pending:
        wave = sorted(key for key in pending if not set(failures[key]["depends_on"]) & pending)
        if not wave:
            raise HealingError("Cyclic failure dependencies")
        ordered.extend(wave)
        pending.difference_update(wave)

    regressions = sorted(key for key, status in before.items() if status == "passed" and after.get(key) != "passed")
    new_failures = sorted(key for key, status in after.items() if status == "failed" and key not in before)
    missing = sorted(set(before) - set(after))
    persistent_failures = sorted(key for key, status in after.items()
                                 if status == 'failed' and before.get(key) == 'failed')
    perf, seen = [], set()
    for row in _rows(request["performance"]):
        _fields(row, {"id", "baseline_ms", "current_ms", "max_ratio"})
        key = _slug(row["id"])
        if key in seen:
            raise HealingError("Duplicate performance metric")
        seen.add(key)
        old = _finite(row["baseline_ms"], 0.000001)
        new = _finite(row["current_ms"])
        limit = _finite(row["max_ratio"], 1, 1000)
        if new / old > limit:
            perf.append({"id": key, "ratio": new / old, "max_ratio": limit})

    conflicts, seen = [], set()
    for row in _rows(request["dependencies"]):
        _fields(row, {"package", "required", "installed"})
        package = _slug(row["package"])
        required = _rows(row["required"])
        versions = required + [row["installed"]]
        if not required or package in seen or any(not isinstance(v, str) or not re.fullmatch(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}(?:-[A-Za-z0-9.-]{1,40})?", v) for v in versions):
            raise HealingError("Unique package and exact version requirements required")
        seen.add(package)
        if len(set(required)) > 1 or row["installed"] not in required:
            conflicts.append({"package": package, "reason": "incompatible-exact-pins" if len(set(required)) > 1 else "installed-pin-mismatch", "required": sorted(set(required)), "installed": row["installed"]})

    hypotheses = []
    for key in ordered:
        row = failures[key]
        descendants = {key}
        for other in ordered:
            if set(failures[other]["depends_on"]) & descendants:
                descendants.add(other)
        hypotheses.append({"failure": key, "component": row["component"], "kind": row["kind"], "downstream_failures": len(descendants) - 1, "upstream": sorted(row["depends_on"]), "basis": "reported-dependency-correlation", "causal_proof": False})
    hypotheses.sort(key=lambda row: (-row["downstream_failures"], len(row["upstream"]), row["failure"]))
    proposals = []
    if regressions or new_failures:
        proposals.append({"kind": "restore-failing-contract", "targets": sorted(set(regressions + new_failures)), "required_checks": ["baseline-reproducer", "candidate-runtime-suite", "security", "independent-review"]})
    if missing:
        proposals.append({"kind": "restore-test-coverage", "targets": missing, "required_checks": ["unchanged-test-manifest"]})
    if persistent_failures:
        proposals.append({"kind": "investigate-persistent-failure", "targets": persistent_failures,
                          "required_checks": ["reproducer", "candidate-runtime-suite", "independent-review"]})
    if conflicts:
        proposals.append({"kind": "reconcile-dependency-pins", "targets": sorted(row["package"] for row in conflicts), "required_checks": ["lockfile-review", "dependency-audit", "runtime-suite"]})
    if perf:
        proposals.append({"kind": "profile-performance-regression", "targets": sorted(row["id"] for row in perf), "required_checks": ["repeat-same-device-benchmark", "correctness-suite"]})
    if failures and not proposals:
        proposals.append({"kind": "investigate-upstream-failure", "targets": [hypotheses[0]["failure"]], "required_checks": ["reproducer", "counterfactual-retest", "independent-review"]})
    result = {"schema_version": VERSION, "project": project, "source_sha256": source, "baseline_sha256": baseline, "request_sha256": sha(request), "evidence_sha256": sha(evidence), "regressions": regressions, "new_failures": new_failures, "missing_baseline_tests": missing, "performance_regressions": sorted(perf, key=lambda row: row["id"]), "dependency_conflicts": sorted(conflicts, key=lambda row: row["package"]), "root_cause_hypotheses": hypotheses, "proposals": proposals, "status": "review-required" if proposals else "no-regression-observed", "uncertainties": ["Supplied evidence is not independently authenticated.", "Dependency correlation is not causal proof.", "Performance samples need repeated comparable-device measurements."], "runtime_tests_executed": 0, "production_mutations": 0, "deployment_allowed": False}
    result["report_sha256"] = sha(result)
    return result


def _path(value):
    if not isinstance(value, str) or not value or len(value) > 128 or not re.fullmatch(r"[A-Za-z0-9_./-]+", value):
        raise HealingError("Unsafe artifact path")
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", "..", ".git"} for part in value.split("/")):
        raise HealingError("Unsafe artifact path")
    return value


def _files(value):
    if not isinstance(value, dict) or not value or len(value) > MAX_FILES:
        raise HealingError("Bounded artifact map required")
    total = 0
    for name, source in value.items():
        _path(name)
        if not isinstance(source, str):
            raise HealingError("Artifact must be UTF8 text")
        try:
            size = len(source.encode("utf-8"))
        except UnicodeError as error:
            raise HealingError("Artifact must be UTF8 text") from error
        total += size
        if size > MAX_CONTENT_BYTES or total > MAX_TOTAL_BYTES:
            raise HealingError("Artifact size exceeds bound")
        if SECRET.search(source) or secret_findings(name, source) or any(ord(c) < 32 and c not in "\n\r\t" for c in source):
            raise HealingError("Credential-shaped or control content refused")
    paths = sorted(value)
    if any(other.startswith(name + "/") for name in paths for other in paths if name != other):
        raise HealingError("File and directory path collision")
    return value


def artifact_digest(files):
    """Digest exact UTF8 bytes and paths without exposing contents in the receipt."""
    return sha({name: hashlib.sha256(source.encode("utf-8")).hexdigest() for name, source in _files(files).items()})


def _checks(values):
    _rows(values)
    if not values:
        raise HealingError("Checks may not be empty")
    seen = set()
    for row in values:
        if not isinstance(row, dict) or row.get("kind") not in {"sha256", "json-value", "python-syntax"}:
            raise HealingError("Unsupported declarative check")
        fields = {"id", "kind", "path"} | ({"expected"} if row["kind"] == "sha256" else {"pointer", "value"} if row["kind"] == "json-value" else set())
        _fields(row, fields)
        key = _slug(row["id"])
        if key in seen:
            raise HealingError("Duplicate check identifier")
        seen.add(key)
        _path(row["path"])
        if row["kind"] == "sha256":
            _digest(row["expected"])
        elif row["kind"] == "json-value":
            if not isinstance(row["pointer"], list) or len(row["pointer"]) > 20 or any(not (isinstance(key, str) and len(key) <= 100 or type(key) is int and 0 <= key < MAX_ROWS) for key in row["pointer"]):
                raise HealingError("Bounded JSON path required")
            try:
                value = canonical(row["value"])
            except (ValueError, TypeError, RecursionError) as error:
                raise HealingError("Invalid expected JSON value") from error
            if len(value) > 4096 or SECRET.search(value.decode("utf-8")) or secret_findings("check.json", value.decode("utf-8")):
                raise HealingError("Unsafe expected JSON value")
    return values


def _run_checks(root, checks):
    from .orchestration import load_json
    outcomes = []
    for check in checks:
        path = root / check["path"]
        passed = False
        if path.is_file():
            try:
                content = path.read_bytes()
                if check["kind"] == "sha256":
                    passed = hashlib.sha256(content).hexdigest() == check["expected"]
                elif check["kind"] == "python-syntax":
                    tree = ast.parse(content.decode("utf-8"))
                    passed = sum(1 for _ in ast.walk(tree)) <= 20000
                else:
                    value = load_json(content)
                    for key in check["pointer"]:
                        if isinstance(value, list) and type(key) is int or isinstance(value, dict) and isinstance(key, str):
                            value = value[key]
                        else:
                            raise ValueError("JSON path type mismatch")
                    passed = canonical(value) == canonical(check["value"])
            except (ValueError, SyntaxError, KeyError, IndexError, TypeError, UnicodeError, RecursionError):
                passed = False
        outcomes.append({"id": check["id"], "passed": passed})
    return outcomes


def verify_repair(request):
    """Check immutable baseline/candidate copies; never execute supplied code.

    A source-bound passing artifact receipt still requires runtime application tests
    and independent review. Neither this function nor its result authorizes release.
    Rollback is verified against the baseline bytes in another disposable directory.
    """
    _fields(request, {"schema_version", "project", "baseline_files", "candidate_files", "baseline_sha256", "candidate_sha256", "checks", "rollback_checks"})
    if type(request["schema_version"]) is not int or request["schema_version"] != VERSION:
        raise HealingError("Unknown schema version")
    project = _slug(request["project"])
    baseline, candidate = copy.deepcopy(_files(request["baseline_files"])), copy.deepcopy(_files(request["candidate_files"]))
    before_hash, after_hash = artifact_digest(baseline), artifact_digest(candidate)
    if before_hash != _digest(request["baseline_sha256"]) or after_hash != _digest(request["candidate_sha256"]):
        raise HealingError("Artifact checksum mismatch")
    checks, rollback_checks = _checks(request["checks"]), _checks(request["rollback_checks"])
    with tempfile.TemporaryDirectory(prefix="gaie-repair-") as directory:
        root = pathlib.Path(directory)
        for label, files in (("baseline", baseline), ("candidate", candidate), ("rollback", baseline)):
            destination = root / label
            destination.mkdir(mode=0o700)
            for name, content in files.items():
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with path.open("x", encoding="utf-8", newline="") as stream:
                    stream.write(content)
                path.chmod(0o600)
        before = _run_checks(root / "baseline", checks)
        after = _run_checks(root / "candidate", checks)
        rolled_back = _run_checks(root / "rollback", rollback_checks)
        restored = {name: (root / "rollback" / name).read_bytes().decode("utf-8") for name in baseline}
        rollback_hash = artifact_digest(restored)
    improved = any(not old["passed"] and new["passed"] for old, new in zip(before, after))
    candidate_passed = all(row["passed"] for row in after)
    rollback_passed = rollback_hash == before_hash and all(row["passed"] for row in rolled_back)
    result = {"schema_version": VERSION, "project": project, "baseline_sha256": before_hash, "candidate_sha256": after_hash, "checks_sha256": sha(checks), "rollback_checks_sha256": sha(rollback_checks), "baseline_checks": before, "candidate_checks": after, "rollback_checks": rolled_back, "artifact_improved": improved, "artifact_checks_passed": candidate_passed, "rollback_artifact_verified": rollback_passed, "rollback_sha256": rollback_hash, "status": "artifact-verified-awaiting-runtime-review" if improved and candidate_passed and rollback_passed else "blocked", "verification_scope": "disposable-artifact-copies-and-fixed-declarative-checks", "runtime_tested": False, "untrusted_code_executed": False, "os_sandbox_claimed": False, "requires_human_review": True, "production_mutations": 0, "deployment_allowed": False}
    result["receipt_sha256"] = sha(result)
    return result


# =========================================================================== governed self-healing loop (L17)

STAGES = ("DISCOVER", "ANALYZE", "DESIGN", "IMPLEMENT", "TEST", "CRITIQUE", "REPAIR", "VALIDATE")
POLICY = {"max_iterations": 3, "max_candidates": 40, "max_patch_lines": 200, "test_timeout_s": 120,
          "allowed_files": None, "allow_dead_code_removal": False, "network": False, "environment": "isolated-copy"}
POLICY_LIMITS = {"max_iterations": (1, 10), "max_candidates": (1, 200), "max_patch_lines": (1, 2000), "test_timeout_s": (1, 900)}
MAX_TARGET_FILES = 2000
MAX_TARGET_BYTES = 32 * 1024 * 1024
MAX_TRIALS = 400
PASSING = frozenset({"passed", "expected-failure"})
RANK = {name: index for index, name in enumerate(detectors.SEVERITIES)}
CAUSAL_KINDS = frozenset({"missing-route-handler", "route-missing-from-table", "duplicate-route", "pin-lock-mismatch",
                          "conflicting-pins", "range-violation", "unlocked-requirement", "schema-error", "query-error",
                          "database-integrity"})
STRATEGIES = {"missing-route-handler": "restore-route-handler", "pin-lock-mismatch": "align-pin-to-lock"}
PRIORITY = {"align-pin-to-lock": 0, "restore-route-handler": 1, "remove-dead-code": 2, "safe-mutation-search": 3}
_KIND_ORDER = {"compare": 0, "binop": 1, "boolop": 2, "not": 3, "return": 4, "int": 5}
_BINOP = {ast.Add: ast.Sub, ast.Sub: ast.Add}
_ZERO = "0" * 64


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _passed(outcome):
    return outcome in PASSING


def _under(rel, directory):
    return rel == directory or rel.startswith(directory.rstrip("/") + "/")


def _policy(policy):
    merged = dict(POLICY)
    if policy is not None:
        if not isinstance(policy, dict) or not set(policy) <= set(POLICY):
            raise HealingError("Unknown policy field")
        merged.update(policy)
    if merged["network"] is not False:
        raise HealingError("Network access refused: repairs run offline")
    if merged["environment"] != "isolated-copy":
        raise HealingError("Production or in-place repair refused: only an isolated copy is ever repaired")
    for key, (low, high) in POLICY_LIMITS.items():
        if type(merged[key]) is not int or not low <= merged[key] <= high:
            raise HealingError(f"Unbounded repair refused: {key} must be an integer in {low}..{high}")
    if type(merged["allow_dead_code_removal"]) is not bool:
        raise HealingError("allow_dead_code_removal must be a boolean")
    allowed = merged["allowed_files"]
    if allowed is not None and (not isinstance(allowed, list) or not 0 < len(allowed) <= 200):
        raise HealingError("allowed_files must be a bounded non-empty list")
    return merged


def safe_destination(base, relative):
    """Resolve ``relative`` under ``base`` for writing; refuse escapes, absolute paths and symlinks."""
    if not isinstance(relative, str) or not relative or len(relative) > 512 or "\0" in relative or "\\" in relative:
        raise HealingError("Refused write outside the workdir")
    if relative.startswith("/") or any(part in ("", ".", "..") for part in relative.split("/")):
        raise HealingError("Refused write outside the workdir")
    base = pathlib.Path(base).resolve(strict=True)
    current = base
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise HealingError("Refused write through a symlink")
    resolved = current.resolve()
    if base not in resolved.parents:
        raise HealingError("Refused write outside the workdir")
    return current


def _write_bytes(base, relative, data):
    path = safe_destination(base, relative)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    return path


def _snapshot(root):
    """{relative path: sha256} of the target; refuses symlinks that leave it and unbounded trees."""
    root = pathlib.Path(root)
    files, total = {}, 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in detectors.SKIP_DIRS)
        for name in dirnames + filenames:
            full = pathlib.Path(dirpath, name)
            if full.is_symlink():
                try:
                    absolute, resolved = os.path.isabs(os.readlink(full)), full.resolve()
                except (OSError, RuntimeError):
                    raise HealingError("Target contains an unresolvable symlink; an isolated copy cannot be guaranteed") from None
                if absolute or resolved != root and root not in resolved.parents:
                    raise HealingError("Target contains a symlink that leaves it (or is absolute); an isolated copy cannot be guaranteed")
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in sorted(filenames):
            if name.endswith((".pyc", ".pyo")):
                continue
            full = pathlib.Path(dirpath, name)
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                files[rel] = "symlink:" + hashlib.sha256(os.readlink(full).encode()).hexdigest()
            else:
                data = full.read_bytes()
                total += len(data)
                files[rel] = hashlib.sha256(data).hexdigest()
            if len(files) > MAX_TARGET_FILES or total > MAX_TARGET_BYTES:
                raise HealingError("Target exceeds the bounded size for an isolated copy")
    return dict(sorted(files.items()))


def _test_spec(tests, root):
    if not isinstance(tests, dict) or set(tests) != {"start", "pattern"}:
        raise HealingError("tests must be {start, pattern}")
    try:
        start = detectors.rel_path(tests["start"], "tests.start")
    except detectors.DetectorError as error:
        raise HealingError(str(error)) from None
    path = root / start
    if path.is_symlink() or not path.is_dir() or root not in path.resolve().parents:
        raise HealingError("tests.start must be a directory inside the target")
    pattern = tests["pattern"]
    if not isinstance(pattern, str) or not re.fullmatch(r"[A-Za-z0-9_*?\[\].-]{1,64}", pattern) or not pattern.endswith(".py"):
        raise HealingError("Unsafe test pattern")
    return {"start": start, "pattern": pattern}


def _allowed_files(policy, snapshot, spec, manifest):
    protected = {detectors.MANIFEST} | {manifest[k] for k in ("route_spec", "contracts", "security_baseline") if manifest.get(k)}
    protected |= {manifest["dependencies"]["lock"]} if manifest.get("dependencies", {}).get("lock") else set()
    protected |= {manifest["performance"]["baseline"]} if manifest.get("performance") else set()
    regular = {rel for rel, digest in snapshot.items() if not digest.startswith("symlink:")}
    if policy["allowed_files"] is None:
        return sorted(rel for rel in regular if rel not in protected and not _under(rel, spec["start"])
                      and (rel.endswith(".py") or re.fullmatch(r"(?:.*/)?requirements[\w.-]*\.txt", rel) and "lock" not in rel.rsplit("/", 1)[-1]))
    chosen = set()
    for rel in policy["allowed_files"]:
        try:
            detectors.rel_path(rel, "allowed_files")
        except detectors.DetectorError:
            raise HealingError("Refused write outside the workdir: allowed files must be relative paths inside the target") from None
        if _under(rel, spec["start"]):
            raise HealingError("Test files are the oracle; repairs may not edit them")
        if rel not in snapshot:
            raise HealingError("Allowed file does not exist in the target")
        if rel not in regular:
            raise HealingError("Allowed file is a symlink; refused")
        chosen.add(rel)
    return sorted(chosen)


def _test_slug(test_id):
    base = re.sub(r"[^a-z0-9_-]+", "-", test_id.lower()).strip("-_")[:50] or "t"
    return f"{base}-{hashlib.sha256(test_id.encode()).hexdigest()[:12]}"


def _diff(rel, before, after):
    lines = difflib.unified_diff(before.decode("utf-8").splitlines(keepends=True), after.decode("utf-8").splitlines(keepends=True), f"a/{rel}", f"b/{rel}")
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)


def apply_patch(files, patch):
    """Apply a unified diff exactly (no fuzz) to ``{path: text}``; HealingError on any mismatch."""
    result, lines, index = dict(files), patch.splitlines(keepends=True), 0
    while index < len(lines):
        if not lines[index].startswith("--- ") or index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise HealingError("Malformed patch header")
        old, new = lines[index][4:].rstrip("\n"), lines[index + 1][4:].rstrip("\n")
        rel = (new if new != "/dev/null" else old)[2:]
        source = "" if old == "/dev/null" else result.get(rel)
        if source is None:
            raise HealingError("Patch target missing")
        original, out, position = source.splitlines(keepends=True), [], 0
        index += 2
        while index < len(lines) and lines[index].startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[index])
            if not match:
                raise HealingError("Malformed hunk header")
            old_count = int(match[2] if match[2] is not None else 1)
            new_count = int(match[4] if match[4] is not None else 1)
            begin = int(match[1]) - 1 if old_count else int(match[1])
            if begin < position:
                raise HealingError("Overlapping hunks")
            out.extend(original[position:begin])
            position, index = begin, index + 1
            while old_count or new_count:
                if index >= len(lines):
                    raise HealingError("Truncated hunk")
                tag, body = lines[index][:1], lines[index][1:]
                index += 1
                if index < len(lines) and lines[index].startswith("\\"):
                    body, index = body[:-1] if body.endswith("\n") else body, index + 1
                if tag in (" ", "-"):
                    if position >= len(original) or original[position] != body or old_count < 1:
                        raise HealingError("Patch context does not match")
                    position, old_count = position + 1, old_count - 1
                    if tag == " ":
                        out.append(body)
                        new_count -= 1
                elif tag == "+" and new_count > 0:
                    out.append(body)
                    new_count -= 1
                else:
                    raise HealingError("Malformed hunk line")
        out.extend(original[position:])
        result[rel] = None if new == "/dev/null" else "".join(out)
    return result


def introduced(reference, detection):
    """What ``detection`` shows that ``reference`` did not: the fail-closed recheck of a repair.

    ``new_findings`` are findings of medium or higher severity (the loop's defect
    threshold) whose stable ``key`` is absent from every ``reference`` finding;
    ``not_rechecked`` are detectors that ran for ``reference`` but did not run now (an
    app that no longer starts skips its integrations, so their findings cannot vanish
    unseen). Both lists are deterministic: no measured evidence is copied.
    """
    known = {row["key"] for row in reference["findings"]}
    new = {}
    for row in detection["findings"]:
        if RANK[row["severity"]] >= RANK["medium"] and row["key"] not in known and row["key"] not in new:
            new[row["key"]] = {"key": row["key"], "detector": row["detector"], "kind": row["kind"], "severity": row["severity"],
                               "path": row["location"]["path"], "symbol": row["location"]["symbol"]}
    status = {row["detector"]: row["status"] for row in detection["detectors"]}
    lost = sorted(row["detector"] for row in reference["detectors"] if row["status"] == "ran" and status.get(row["detector"]) != "ran")
    ordered = sorted(new.values(), key=lambda row: (-RANK[row["severity"]], row["detector"], row["kind"], row["path"], str(row["symbol"]), row["key"]))
    return {"new_findings": ordered, "not_rechecked": lost}


def verify_receipts(receipts):
    """True when every stage receipt hashes correctly and links to its predecessor."""
    previous = _ZERO
    for row in receipts:
        body = {key: value for key, value in row.items() if key != "receipt_sha256"}
        if row.get("previous_sha256") != previous or sha(body) != row.get("receipt_sha256") or row.get("stage") not in STAGES:
            return False
        previous = row["receipt_sha256"]
    return bool(receipts)


# --------------------------------------------------------------------------- analysis helpers

def _causal_graph(findings, failing, coverage, details):
    """Map failures and findings onto reasoning.root_causes over an explicit dependency DAG."""
    defects = sorted((f for f in findings if RANK[f["severity"]] >= RANK["medium"]), key=lambda f: (-RANK[f["severity"]], f["id"]))
    truncated = len(defects) > 60 or len(failing) > 60
    defects, failing = defects[:60], sorted(failing)[:60]

    def build(with_files):
        labels, edges = {}, {}

        def node(label):
            key = "n" + hashlib.sha256(label.encode()).hexdigest()[:24]
            labels[key] = label
            edges.setdefault(key, set())
            return key

        by_file, by_route = {}, {}
        for row in defects:
            key = node("finding:" + row["id"])
            if row["kind"] in CAUSAL_KINDS:
                by_file.setdefault(row["location"]["path"], []).append(key)
            route = row["evidence"].get("route") if isinstance(row["evidence"], dict) else None
            if route:
                by_route.setdefault(route, {}).setdefault(row["detector"], []).append(key)
        schema_errors = [node("finding:" + row["id"]) for row in defects if row["kind"] == "schema-error"]
        for row in defects:
            key = node("finding:" + row["id"])
            upstream = by_route.get(row["evidence"].get("route") if isinstance(row["evidence"], dict) else None, {})
            if row["detector"] == "broken-apis":
                edges[key].update(upstream.get("broken-routes", []))
            elif row["detector"] == "integrations":
                edges[key].update(upstream.get("broken-routes", []) + upstream.get("broken-apis", []))
            if row["kind"] == "query-error":
                edges[key].update(schema_errors)
        for test in failing:
            key = node("test:" + test)
            covered = coverage.get(test, {})
            touched = {row[0] for row in covered.get("functions", [])} | set(covered.get("files", []))
            touched |= {frame[0] for frame in details.get(test, {}).get("frames", [])}
            for rel in sorted(touched & set(by_file)):
                if with_files:
                    file_key = node("file:" + rel)
                    edges[file_key].update(by_file[rel])
                    edges[key].add(file_key)
                else:
                    edges[key].update(by_file[rel])
        return labels, edges

    labels, edges = build(True)
    if len(edges) > 128:
        labels, edges = build(False)
    failed = [key for key, label in labels.items() if not label.startswith("file:")]
    observations = [{"id": key, "status": "failed", "evidence_sha256": sha(labels[key])} for key in sorted(failed)]
    if not failed:
        return {"roots": [], "attribution": {}, "nodes": 0, "method": "no failed observations", "causality_proven": False}
    try:
        result = root_causes(observations, {key: sorted(value) for key, value in edges.items()})
        roots, affected = result["candidate_roots"], result["affected"]
        method = result["method"]
    except ReasoningError as error:
        roots, affected, method = sorted(failed), {key: [] for key in failed}, f"fallback: every failure is its own root ({error})"
    out, attribution = [], {}
    for key in roots:
        kind, ident = labels[key].split(":", 1)
        explains = sorted(labels[n] for n in affected.get(key, []) if not labels[n].startswith("file:"))
        out.append({"node": labels[key], "type": kind, "id": ident, "explains": explains})
        attribution.setdefault(labels[key], []).append(labels[key])
        for label in explains:
            attribution.setdefault(label, []).append(labels[key])
    out.sort(key=lambda row: row["node"])
    return {"roots": out, "attribution": {k: sorted(v) for k, v in sorted(attribution.items())}, "nodes": len(edges),
            "method": method, "causality_proven": False, "truncated": truncated}


def _localize(test_id, outcomes, coverage, allowed, flaky):
    """Ochiai spectrum ranking of functions covered by a failing test (allowed files only)."""
    counted = {t: o for t, o in outcomes.items() if o != "skipped" and t not in flaky}
    total_failed = sum(1 for o in counted.values() if not _passed(o))
    stats = {}
    for test, outcome in counted.items():
        for row in coverage.get(test, {}).get("functions", []):
            stats.setdefault(tuple(row), [0, 0])[0 if not _passed(outcome) else 1] += 1
    ranked = []
    for key in {tuple(row) for row in coverage.get(test_id, {}).get("functions", [])}:
        if key[0] in allowed and key[0].endswith(".py"):
            failed, passed = stats.get(key, [0, 0])
            score = failed / math.sqrt(total_failed * (failed + passed)) if failed and total_failed else 0.0
            ranked.append((-round(score, 9), key))
    ranked.sort()
    return [{"path": key[0], "function": key[1], "line": key[2], "ochiai": -score} for score, key in ranked[:3]]


class _Choice:
    """Deterministic stand-in for the random generator mutate.apply expects."""

    def __init__(self, value):
        self.value = value

    def choice(self, options):
        return self.value if self.value in options else options[0]


def _splice(source, node, replacement):
    data = source.encode("utf-8")
    starts = [0]
    for line in data.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    begin = starts[node.lineno - 1] + node.col_offset
    end = starts[node.end_lineno - 1] + node.end_col_offset
    return (data[:begin] + replacement.encode("utf-8") + data[end:]).decode("utf-8")


def _find_function(tree, qualname, firstline):
    name = qualname.rsplit(".", 1)[-1]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            if node.lineno == firstline or node.decorator_list and node.decorator_list[0].lineno == firstline:
                return node
    return None


def mutation_candidates(source, qualname, firstline):
    """Single-site safe mutations of one function, in a fixed order, as minimal source edits.

    The catalogue reuses ``swarm/phase3/mutate.py`` (comparison flip, and/or swap,
    ``not`` removal, int +/-1, returned boolean inversion) plus ``+``/``-`` swap. Each
    edit is accepted only if the edited source parses to exactly the mutated AST.
    """
    try:
        from swarm.phase3 import mutate
    except ImportError:
        raise HealingError("mutation catalogue swarm/phase3/mutate.py is not importable") from None
    tree = ast.parse(source)
    function = _find_function(tree, qualname, firstline)
    if function is None:
        return
    nodes = list(ast.walk(tree))

    def span(kind, node):
        return node.value if kind == "return" else node

    def inside(node):
        return function.lineno <= node.lineno and node.end_lineno <= function.end_lineno

    sites = [site for site in mutate.sites(tree) if inside(span(site[0], nodes[site[1]]))]
    sites += [("binop", number, 0) for number, node in enumerate(nodes) if isinstance(node, ast.BinOp) and type(node.op) in _BINOP and inside(node)]
    sites.sort(key=lambda site: (_KIND_ORDER[site[0]], span(site[0], nodes[site[1]]).lineno, span(site[0], nodes[site[1]]).col_offset, site[1], site[2]))
    for site in sites:
        kind, number, _ = site
        original = span(kind, nodes[number])
        for delta in ((1, -1) if kind == "int" else (None,)):
            if kind == "binop":
                mutated = copy.deepcopy(tree)
                target = list(ast.walk(mutated))[number]
                target.op = _BINOP[type(target.op)]()
            else:
                mutated = mutate.apply(tree, site, _Choice(delta))
            changed = list(ast.walk(mutated))[number]
            if kind in ("compare", "boolop", "binop"):
                replacement = ast.unparse(changed)
            elif kind == "not":
                replacement = ast.get_source_segment(source, nodes[number].operand) or ""
            elif kind == "int":
                replacement = str(original.value + delta)
            else:
                replacement = repr(not original.value)
            expected = ast.dump(mutated)
            for text in (replacement, f"({replacement})"):
                try:
                    candidate = _splice(source, original, text)
                    if ast.dump(ast.parse(candidate)) == expected:
                        before = (ast.get_source_segment(source, original) or "")[:120]
                        yield {"kind": kind, "line": original.lineno, "before": before, "after": text[:120], "source": candidate}
                        break
                except (SyntaxError, ValueError):
                    continue


def _literal(value):
    if isinstance(value, dict):
        return ast.Dict([ast.Constant(k) for k in value], [_literal(v) for v in value.values()])
    if isinstance(value, list):
        return ast.List([_literal(v) for v in value], ast.Load())
    return ast.Constant(value)


def handler_source(route, spec, *, root=None, schemas=()):
    """Generate a route handler from a declared spec template; HealingError when no safe template applies."""
    implementation = route.get("implementation")
    if not implementation:
        raise HealingError("route spec declares no implementation template")
    if spec.get("handler_convention") != detectors.CONVENTION:
        raise HealingError("unsupported handler convention")
    name, response = route["handler"], route["response"]
    if keyword.iskeyword(name) or name.startswith("_"):
        raise HealingError("unsafe handler name")
    if response.get("type", "json") != "json":
        raise HealingError("only JSON handlers are restorable from a template")
    status, content_type = response.get("status", 200), response.get("content_type", "application/json")
    if not isinstance(content_type, str) or not re.fullmatch(r"[a-z]+/[a-z0-9.+-]+(?:; ?charset=[a-z0-9-]+)?", content_type):
        raise HealingError("unsafe content type")
    template, shape = implementation["template"], response.get("shape", {})
    if template in ("sql-scalar", "sql-rows"):
        query, field = implementation.get("query"), implementation.get("field")
        if not isinstance(field, str) or not detectors.IDENTIFIER.fullmatch(field) or set(shape) - {field}:
            raise HealingError("template field must be an identifier that covers the declared shape")
        if not isinstance(query, str) or len(query) > 500 or not re.fullmatch(r"\s*SELECT\b[^;]*", query, re.I) or re.search(r"[?:@$]", query):
            raise HealingError("template query must be one parameterless SELECT")
        if not sqlite3.complete_statement(query + ";"):
            raise HealingError("template query is incomplete")
        if schemas:
            error = detectors.explain_query(root, schemas, query)
            if error:
                raise HealingError(f"template query does not match the declared schema: {error}")
        if template == "sql-scalar":
            body = [f"row = conn.execute({query!r}).fetchone()",
                    f"return {status}, {content_type!r}, {{{field!r}: row[0] if row is not None else None}}"]
        else:
            body = [f"cursor = conn.execute({query!r})", "columns = [column[0] for column in cursor.description]",
                    f"return {status}, {content_type!r}, {{{field!r}: [dict(zip(columns, row)) for row in cursor.fetchall()]}}"]
    else:
        value = implementation.get("body")
        try:
            encoded = canonical(value).decode("utf-8")
        except (TypeError, ValueError) as error:
            raise HealingError("static body must be JSON") from error
        if not isinstance(value, dict) or len(encoded) > 2048 or SECRET.search(encoded) or secret_findings("body.json", encoded) or detectors.shape_mismatches(value, shape):
            raise HealingError("static body must be a small JSON object matching the declared shape")
        body = [f"return {status}, {content_type!r}, {ast.unparse(_literal(value))}"]
    code = f"def {name}(conn, query):\n    \"\"\"Restored from the route spec ({template}) by the GAIE self-healing loop.\"\"\"\n"
    code += "".join(f"    {line}\n" for line in body)
    ast.parse(code)
    return code


def _insert_handler(source, code, handlers):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in handlers]
    guard = next((n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test)), None)
    if defs:
        index, text = max(n.end_lineno for n in defs), "\n\n" + code
    elif guard is not None:
        index, text = guard.lineno - 1, code + "\n\n"
    else:
        index, text = len(lines), "\n\n" + code
    return "".join(lines[:index]) + text + "".join(lines[index:])


# --------------------------------------------------------------------------- the loop

class _Heal:
    def __init__(self, target, run_dir, spec, manifest, policy, now, ffprobe, original, allowed):
        self.target, self.run_dir, self.spec, self.manifest = target, run_dir, spec, manifest
        self.policy, self.now, self.ffprobe, self.original, self.allowed = policy, now, ffprobe, original, set(allowed)
        self.copy = run_dir / "candidate"
        self.sandbox = detectors.Sandbox(run_dir / "sandbox", timeout=policy["test_timeout_s"])
        self.project = manifest.get("name") or "target"
        self.receipts, self.trials, self.accepted, self.iterations, self.journal = [], [], [], [], {}
        self.security_baseline, self.flaky, self.blocked, self.exhausted = None, [], None, set()
        # Detection of the current accepted state; a candidate may not add a defect to it.
        self.reference_detection = self.pending_detection = None

    # ----- state and receipts
    def tree_sha(self):
        digests = dict(self.original)
        for rel, row in self.journal.items():
            digests[rel] = hashlib.sha256(row["current"]).hexdigest()
        return sha(digests)

    def receipt(self, stage, iteration, inputs, outputs, status, side_effect="none"):
        row = {"stage": stage, "iteration": iteration, "status": status, "input_sha256": sha(inputs), "output_sha256": sha(outputs),
               "source_sha256": self.tree_sha(), "side_effect": side_effect, "at": _iso(self.now),
               "previous_sha256": self.receipts[-1]["receipt_sha256"] if self.receipts else _ZERO}
        row["receipt_sha256"] = sha(row)
        self.receipts.append(row)
        return row

    def read_copy(self, rel):
        return self.journal[rel]["current"] if rel in self.journal else safe_destination(self.run_dir, "candidate/" + rel).read_bytes()

    def write_copy(self, rel, data):
        if rel not in self.allowed:
            raise HealingError("Refused write: file outside the allowed repair set")
        destination = safe_destination(self.run_dir, "candidate/" + rel)
        if rel not in self.journal:
            before = destination.read_bytes()
            if hashlib.sha256(before).hexdigest() != self.original.get(rel):
                raise HealingError("Isolated copy diverged from the target before repair")
            self.journal[rel] = {"original": before, "current": before}
        _write_bytes(self.run_dir, "candidate/" + rel, data)
        self.journal[rel]["current"] = data

    def suite(self, *, only=None, coverage=False):
        return self.sandbox.run_tests(self.copy, self.spec["start"], self.spec["pattern"], only=only, coverage=coverage)

    def failing(self, outcomes):
        return sorted(t for t, o in outcomes.items() if not _passed(o) and o != "skipped" and t not in self.flaky)

    def defects(self, findings):
        return [f for f in findings if RANK[f["severity"]] >= RANK["medium"]]

    def regressions(self, reference, candidate):
        """Tests passing in ``reference`` that do not pass in ``candidate``, cross-checked by ``analyze``."""
        own = sorted(t for t, o in reference.items() if _passed(o) and t not in self.flaky and not _passed(candidate.get(t)))
        before = {_test_slug(t): "passed" if _passed(o) else "failed" for t, o in reference.items() if o != "skipped" and t not in self.flaky}
        after = {_test_slug(t): "passed" if _passed(o) else "failed" for t, o in candidate.items() if o != "skipped" and t not in self.flaky}
        report = {"regressions": own, "cross_checked": False, "agree": True}
        if 0 < len(before) <= MAX_ROWS and 0 < len(after) <= MAX_ROWS:
            source = self.tree_sha()
            request = {"schema_version": VERSION, "project": self.project, "source_sha256": source, "baseline_sha256": sha(self.original),
                       "baseline_tests": before, "current_tests": after, "failures": [], "performance": [], "dependencies": [],
                       "evidence": {"project": self.project, "source_sha256": source, "baseline_sha256": sha(self.original), "at": self.now, "sha256": sha(candidate)}}
            checked = analyze(request, now=self.now)
            report.update(cross_checked=True, agree=sorted(checked["regressions"]) == sorted(_test_slug(t) for t in own),
                          analyze_report_sha256=checked["report_sha256"])
        return report

    # ----- DISCOVER
    def discover(self, iteration):
        detection = detectors.run_all(self.copy, self.manifest, tests_dir=self.spec["start"], runtime=True, sandbox=self.sandbox,
                                      ffprobe=self.ffprobe, security_baseline=self.security_baseline)
        traced = self.suite(coverage=True)
        if iteration == 1:
            plain = self.suite()
            if traced["status"] != "ok" or plain["status"] != "ok" or not plain["tests"]:
                self.blocked = f"baseline test run did not complete ({plain['status']}/{traced['status']})"
            self.flaky = sorted(t for t in set(traced.get("tests", {})) | set(plain.get("tests", {})) if traced.get("tests", {}).get(t) != plain.get("tests", {}).get(t))
            self.baseline, self.reference = plain, dict(plain.get("tests", {}))
            self.security_baseline = sorted(f["evidence"]["fingerprint"] for f in detection["findings"] if f["detector"] == "security")
            self.initial = self.reference_detection = detection
        self.current, self.detection = traced, detection
        self.findings = {row["id"]: row for row in detection["findings"]}
        outputs = {"findings": sorted(self.findings), "tests": traced.get("tests", {}), "flaky": self.flaky, "blocked": self.blocked,
                   "detectors": [[r["detector"], r["status"]] for r in detection["detectors"]]}
        self.receipt("DISCOVER", iteration, {"tree": self.tree_sha(), "manifest": self.manifest, "tests": self.spec}, outputs,
                     "blocked" if self.blocked else "ok", "workspace-write")
        return detection

    # ----- ANALYZE
    def analyze_stage(self, iteration):
        outcomes = self.current.get("tests", {})
        failing = self.failing(outcomes)
        graph = _causal_graph(list(self.findings.values()), failing, self.current.get("coverage", {}), self.current.get("details", {}))
        graph["localization"] = {row["id"]: _localize(row["id"], outcomes, self.current.get("coverage", {}), self.allowed, set(self.flaky))
                                 for row in graph["roots"] if row["type"] == "test"}
        graph["failure_details"] = {t: self.current.get("details", {}).get(t, {}) for t in failing}
        self.receipt("ANALYZE", iteration, {"findings": sorted(self.findings), "failing": failing}, graph, "ok")
        return graph

    # ----- DESIGN
    def design(self, iteration, analysis):
        items = []
        for root in analysis["roots"]:
            targets = sorted(label[5:] for label in root["explains"] if label.startswith("test:"))
            if root["type"] == "finding":
                row = self.findings[root["id"]]
                item = {"strategy": STRATEGIES.get(row["kind"]), "root": root["node"], "finding": row["id"], "finding_key": row["key"],
                        "kind": row["kind"], "files": [row["location"]["path"]], "targets": targets}
                item.update(self.feasible(item, row))
            else:
                functions = analysis["localization"].get(root["id"], [])
                item = {"strategy": "safe-mutation-search", "root": root["node"], "finding": None, "finding_key": None, "kind": "failing-test",
                        "files": sorted({f["path"] for f in functions}), "targets": sorted(set(targets) | {root["id"]}), "functions": functions}
                item.update({"status": "planned", "reason": None} if functions else
                            {"status": "no-safe-repair", "reason": "no covered function in the allowed repair set"})
            items.append(item)
        if self.policy["allow_dead_code_removal"]:
            for row in self.findings.values():
                if row["kind"] == "dead-code":
                    item = {"strategy": "remove-dead-code", "root": "finding:" + row["id"], "finding": row["id"], "finding_key": row["key"],
                            "kind": "dead-code", "files": [row["location"]["path"]], "targets": []}
                    item.update(self.feasible(item, row))
                    items.append(item)
        items.sort(key=lambda item: (PRIORITY.get(item["strategy"], 9), item["root"]))
        for number, item in enumerate(items, 1):
            item["item"] = f"i{iteration}-{number}"
        self.receipt("DESIGN", iteration, {"roots": analysis["roots"], "policy": self.policy}, items, "ok")
        return items

    def feasible(self, item, row):
        if item["strategy"] is None:
            return {"status": "no-safe-repair", "reason": f"no deterministic repair strategy for {row['kind']}"}
        if not set(item["files"]) <= self.allowed:
            return {"status": "no-safe-repair", "reason": "file outside the allowed repair set"}
        evidence = row["evidence"]
        if item["strategy"] == "align-pin-to-lock" and not evidence.get("lock_has_integrity"):
            return {"status": "no-safe-repair", "reason": "lock entry carries no integrity hash; the correct version is ambiguous"}
        if item["strategy"] == "restore-route-handler":
            if not self.manifest.get("route_spec") or not evidence.get("spec_declares"):
                return {"status": "no-safe-repair", "reason": "route is not declared in a route spec"}
            try:
                self.route_code(row)
            except HealingError as error:
                return {"status": "no-safe-repair", "reason": str(error)}
        if item["strategy"] == "remove-dead-code" and evidence.get("proof") != "no-static-reference":
            return {"status": "no-safe-repair", "reason": "reference freedom unproven (dynamic name access)"}
        return {"status": "planned", "reason": None}

    # ----- candidate generators (bounded, deterministic)
    def route_code(self, row):
        spec = detectors.load_route_spec(self.copy, self.manifest["route_spec"])
        route = next((r for r in spec["routes"] if r["method"] == row["evidence"]["method"] and r["path"] == row["evidence"]["route"]), None)
        if route is None:
            raise HealingError("route is not declared in a route spec")
        return route, handler_source(route, spec, root=self.copy, schemas=self.manifest.get("database", {}).get("schema", []))

    def candidates(self, item):
        rel = item["files"][0] if item["files"] else None
        if item["strategy"] == "restore-route-handler":
            row = self.findings[item["finding"]]
            route, code = self.route_code(row)
            source = self.read_copy(rel).decode("utf-8")
            app = self.manifest.get("app", {})
            handlers = {e["handler"] for e in detectors.route_table(source, app.get("routes_variable", "ROUTES"))[1]}
            yield {"description": f"restore handler {route['handler']} for {route['method']} {route['path']} from {self.manifest['route_spec']} ({route['implementation']['template']})",
                   "edits": {rel: _insert_handler(source, code, handlers).encode("utf-8")}}
        elif item["strategy"] == "align-pin-to-lock":
            evidence, line = self.findings[item["finding"]]["evidence"], self.findings[item["finding"]]["location"]["line"]
            locked = evidence["locked"]
            if not re.fullmatch(r"[A-Za-z0-9.+!_-]{1,40}", locked) or detectors.version_key(locked) is None:
                return
            lines = self.read_copy(rel).decode("utf-8").splitlines(keepends=True)
            pattern = re.compile(r"^(\s*[A-Za-z0-9._-]+\s*(?:\[[^\]]*\])?\s*===?\s*)([^\s;#,\\]+)")
            match = pattern.match(lines[line - 1])
            if match and detectors.canonical_name(re.split(r"[\s\[=]", match[1].strip(), maxsplit=1)[0]) == evidence["package"]:
                lines[line - 1] = match[1] + locked + lines[line - 1][match.end():]
                yield {"description": f"align {evidence['package']} {evidence['required']} -> =={locked} ({evidence['lock']} carries an integrity hash)",
                       "edits": {rel: "".join(lines).encode("utf-8")}}
        elif item["strategy"] == "remove-dead-code":
            symbol = self.findings[item["finding"]]["location"]["symbol"]
            source = self.read_copy(rel).decode("utf-8")
            node = next((n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == symbol), None)
            if node is None or node.decorator_list:
                return
            lines = source.splitlines(keepends=True)
            end = node.end_lineno
            while end < len(lines) and end - node.end_lineno < 2 and not lines[end].strip():
                end += 1
            yield {"description": f"remove unreferenced {symbol} ({rel}:{node.lineno}-{node.end_lineno}); kept recoverable in the patch",
                   "edits": {rel: "".join(lines[:node.lineno - 1] + lines[end:]).encode("utf-8")}}
        elif item["strategy"] == "safe-mutation-search":
            budget = self.policy["max_candidates"]
            for function in item["functions"]:
                source = self.read_copy(function["path"]).decode("utf-8")
                for mutant in mutation_candidates(source, function["function"], function["line"]):
                    if budget <= 0:
                        return
                    budget -= 1
                    yield {"description": f"{mutant['kind']} mutation in {function['function']} ({function['path']}:{mutant['line']}): {mutant['before']!r} -> {mutant['after']!r}",
                           "edits": {function["path"]: mutant["source"].encode("utf-8")}}

    # ----- IMPLEMENT -> TEST -> CRITIQUE -> REPAIR for one candidate
    def trial(self, iteration, item, candidate):
        number = len(self.trials) + 1
        record = {"trial": number, "item": item["item"], "strategy": item["strategy"], "candidate": candidate["description"],
                  "files": sorted(candidate["edits"])}
        pre = {}
        try:
            for rel in sorted(candidate["edits"]):
                pre[rel] = self.read_copy(rel)
            record["diff"] = "".join(_diff(rel, pre[rel], data) for rel, data in sorted(candidate["edits"].items()))[:8000]
            for rel, data in sorted(candidate["edits"].items()):
                self.write_copy(rel, data)
            record["implement"] = "applied"
        except HealingError as error:
            for rel, data in pre.items():
                if rel in self.journal:
                    self.write_copy(rel, data)
            record.update(implement="refused", refusal=str(error), repair="refused", rollback_verified=all(self.read_copy(r) == d for r, d in pre.items()))
            self.receipt("IMPLEMENT", iteration, record["candidate"], record, "refused")
            self.trials.append(record)
            return False
        self.receipt("IMPLEMENT", iteration, {"item": item["item"], "candidate": record["candidate"]},
                     {"files": {rel: hashlib.sha256(data).hexdigest() for rel, data in candidate["edits"].items()}}, "applied", "workspace-write")
        targets = item["targets"]
        targeted = self.suite(only=targets) if targets else {"status": "ok", "tests": {}}
        full = None
        if targeted["status"] == "ok" and all(_passed(targeted["tests"].get(t)) for t in targets):
            full = self.suite()
        record["targeted"] = {t: targeted.get("tests", {}).get(t, targeted["status"]) for t in targets}
        record["full"] = None if full is None else {"status": full["status"], "passed": sum(1 for o in full.get("tests", {}).values() if _passed(o)),
                                                    "failed": len(self.failing(full.get("tests", {})))}
        self.receipt("TEST", iteration, {"item": item["item"], "targets": targets}, {"targeted": record["targeted"], "full": record["full"]}, "ok")
        verdict = self.critique(item, candidate, targeted, full, pre)
        record["critique"] = verdict
        self.receipt("CRITIQUE", iteration, {"item": item["item"], "trial": number}, verdict, "accepted" if verdict["accepted"] else "rejected")
        if verdict["accepted"]:
            self.reference = dict(full["tests"])
            self.reference_detection = self.pending_detection
            record.update(repair="kept", rollback_verified=None)
            self.accepted.append({"item": item["item"], "trial": number, "strategy": item["strategy"], "root": item["root"],
                                  "finding_key": item["finding_key"], "targets": targets, "description": candidate["description"],
                                  "files": record["files"], "diff_sha256": sha(record["diff"])})
        else:
            for rel, data in pre.items():
                self.write_copy(rel, data)
            verified = all(safe_destination(self.run_dir, "candidate/" + rel).read_bytes() == data for rel, data in pre.items())
            record.update(repair="rolled-back", rollback_verified=verified)
            if not verified:
                self.blocked = "rollback of a rejected candidate could not be verified"
        self.receipt("REPAIR", iteration, {"item": item["item"], "trial": number}, {"repair": record["repair"], "rollback_verified": record["rollback_verified"]},
                     record["repair"], "workspace-write")
        self.trials.append(record)
        return verdict["accepted"]

    def critique(self, item, candidate, targeted, full, pre):
        reasons, regression = [], None
        targets = item["targets"]
        if targeted["status"] != "ok":
            reasons.append(f"target-tests-{targeted['status']}")
        elif any(not _passed(targeted["tests"].get(t)) for t in targets):
            reasons.append("target-tests-still-failing")
        if full is not None:
            if full["status"] != "ok":
                reasons.append(f"full-suite-{full['status']}")
            else:
                if any(not _passed(full["tests"].get(t)) for t in targets):
                    reasons.append("target-tests-fail-in-full-suite")
                regression = self.regressions(self.reference, full["tests"])
                if regression["regressions"]:
                    reasons.append("regression")
                if not regression["agree"]:
                    reasons.append("regression-gate-disagreement")
        elif not reasons:
            reasons.append("full-suite-not-run")
        changed = sum(1 for rel, data in candidate["edits"].items() for line in _diff(rel, pre[rel], data).splitlines()
                      if line[:1] in "+-" and not line.startswith(("+++", "---")))
        if changed > self.policy["max_patch_lines"]:
            reasons.append("patch-exceeds-bound")
        for rel in candidate["edits"]:
            if rel.endswith(".py") and detectors._parse(self.read_copy(rel).decode("utf-8")) is None:
                reasons.append("syntax-error")
        security = detectors.detect_security(self.copy, sorted(candidate["edits"]), baseline=self.security_baseline)
        if any(f["evidence"]["baseline"] == "new" for f in security["findings"]):
            reasons.append("new-security-finding")
        resolved = None
        if not reasons and item["finding_key"]:
            check = {"restore-route-handler": lambda: detectors.detect_broken_routes(self.copy, None, self.manifest),
                     "align-pin-to-lock": lambda: detectors.detect_dependencies(self.copy, None, self.manifest),
                     "remove-dead-code": lambda: detectors.detect_dead_code(self.copy, None, tests_dir=self.spec["start"])}[item["strategy"]]()
            resolved = all(f["key"] != item["finding_key"] for f in check["findings"])
            if not resolved:
                reasons.append("finding-not-resolved")
            if item["strategy"] == "restore-route-handler" and self.manifest.get("app"):
                api, _ = detectors.detect_http(self.copy, None, self.manifest, sandbox=self.sandbox, only_routes={self.findings[item["finding"]]["evidence"]["route"]})
                if api["findings"] or api["status"] != "ran":
                    reasons.append("api-probe-failed")
        recheck, self.pending_detection = None, None
        if not reasons:
            # Fail closed: the passing tests are not the only oracle. Every detector (runtime
            # ones included) re-runs on the candidate; a defect the accepted state did not have,
            # or a detector that can no longer observe the copy, rejects (and rolls back) it.
            self.pending_detection = self.recheck()
            recheck = introduced(self.reference_detection, self.pending_detection)
            if recheck["new_findings"]:
                reasons.append("new-finding")
            if recheck["not_rechecked"]:
                reasons.append("detector-not-rechecked")
        return {"accepted": not reasons, "reasons": reasons, "regressions": regression, "changed_lines": changed, "finding_resolved": resolved,
                "recheck": recheck}

    def recheck(self):
        return detectors.run_all(self.copy, self.manifest, tests_dir=self.spec["start"], runtime=True, sandbox=self.sandbox,
                                 ffprobe=self.ffprobe, security_baseline=self.security_baseline)

    def execute(self, iteration, items):
        progressed = False
        for item in items:
            if item["status"] != "planned" or self.blocked:
                continue
            if item["strategy"] == "safe-mutation-search" and all(_passed(self.reference.get(t)) for t in item["targets"]):
                item.update(status="resolved-earlier", reason="targets already pass after an earlier repair")
                continue
            memo = sha([item["strategy"], item["root"], {rel: hashlib.sha256(self.read_copy(rel)).hexdigest() for rel in item["files"]}])
            if memo in self.exhausted:
                item.update(status="no-safe-repair", reason="candidates already exhausted on identical source in an earlier iteration")
                continue
            tried = 0
            try:
                for candidate in self.candidates(item):
                    if len(self.trials) >= MAX_TRIALS:
                        break
                    tried += 1
                    if self.trial(iteration, item, candidate):
                        item.update(status="repaired", reason=None)
                        progressed = True
                        break
                    if self.blocked:
                        break
            except HealingError as error:
                item.update(status="no-safe-repair", reason=f"candidate generation refused: {error}")
            if item["status"] == "planned":
                summary = {}
                for row in self.trials:
                    if row["item"] == item["item"]:
                        for reason in row.get("critique", {}).get("reasons", [row.get("refusal", "refused")]):
                            summary[reason] = summary.get(reason, 0) + 1
                item.update(status="no-safe-repair", reason=f"{tried} candidate(s) tried, none validated: {dict(sorted(summary.items()))}" if tried else "no candidate repair could be generated")
                self.exhausted.add(memo)
        return progressed

    # ----- VALIDATE
    def validate(self):
        final = self.suite()
        detection = detectors.run_all(self.copy, self.manifest, tests_dir=self.spec["start"], runtime=True, sandbox=self.sandbox,
                                      ffprobe=self.ffprobe, security_baseline=self.security_baseline)
        added = introduced(self.initial, detection)
        final_keys = {row["key"] for row in detection["findings"]}
        unresolved = sorted({row["finding_key"] for row in self.accepted if row["finding_key"] and row["finding_key"] in final_keys})
        outcomes = final.get("tests", {})
        regression = self.regressions(self.baseline.get("tests", {}), outcomes) if final["status"] == "ok" else {"regressions": ["<suite-did-not-run>"], "agree": False}
        targeted = sorted({t for row in self.accepted for t in row["targets"]})
        not_fixed = [t for t in targeted if not _passed(outcomes.get(t))]
        original_now = _snapshot(self.target)
        intact = all(hashlib.sha256((self.copy / rel).read_bytes()).hexdigest() == digest for rel, digest in self.original.items()
                     if rel not in self.journal and not digest.startswith("symlink:"))
        intact = intact and all(safe_destination(self.run_dir, "candidate/" + rel).read_bytes() == row["current"] for rel, row in self.journal.items())
        changed = {rel: row for rel, row in sorted(self.journal.items()) if row["current"] != row["original"]}
        patch = "".join(_diff(rel, row["original"], row["current"]) for rel, row in changed.items())
        reverse = "".join(_diff(rel, row["current"], row["original"]) for rel, row in changed.items())
        before = {rel: row["original"].decode("utf-8") for rel, row in changed.items()}
        after = {rel: row["current"].decode("utf-8") for rel, row in changed.items()}
        try:
            patch_ok = bool(changed) and apply_patch(before, patch) == after and apply_patch(after, reverse) == before
        except HealingError:
            patch_ok = False
        artifact = None
        if changed:
            checks = [{"id": f"c{i}", "kind": "sha256", "path": rel, "expected": hashlib.sha256(row["current"]).hexdigest()} for i, (rel, row) in enumerate(changed.items())]
            checks += [{"id": f"s{i}", "kind": "python-syntax", "path": rel} for i, rel in enumerate(changed) if rel.endswith(".py")]
            rollback = [{"id": f"r{i}", "kind": "sha256", "path": rel, "expected": hashlib.sha256(row["original"]).hexdigest()} for i, (rel, row) in enumerate(changed.items())]
            try:
                verified = verify_repair({"schema_version": VERSION, "project": self.project, "baseline_files": before, "candidate_files": after,
                                          "baseline_sha256": artifact_digest(before), "candidate_sha256": artifact_digest(after), "checks": checks, "rollback_checks": rollback})
                artifact = {"status": verified["status"], "receipt_sha256": verified["receipt_sha256"], "rollback_artifact_verified": verified["rollback_artifact_verified"]}
            except HealingError as error:
                artifact = {"status": "refused", "reason": str(error)}
        checks = {"repairs_accepted": bool(self.accepted), "no_regression": not regression["regressions"] and regression.get("agree", False),
                  "target_tests_pass": not not_fixed, "original_unchanged": original_now == self.original, "isolated_copy_intact": intact,
                  "patch_and_reverse_apply": patch_ok, "artifact_verified": bool(artifact) and artifact["status"] == "artifact-verified-awaiting-runtime-review",
                  "not_blocked": self.blocked is None, "no_new_findings": not added["new_findings"],
                  "detectors_rechecked": not added["not_rechecked"], "targeted_findings_resolved": not unresolved}
        validation = {"passed": all(checks.values()), "checks": checks, "regressions": regression["regressions"], "targeted_tests": targeted,
                      "targeted_still_failing": not_fixed, "final_tests": outcomes, "final_failing": self.failing(outcomes), "artifact": artifact,
                      "blocked": self.blocked, "new_findings": added["new_findings"], "detectors_not_rechecked": added["not_rechecked"],
                      "targeted_findings_unresolved": unresolved}
        self.receipt("VALIDATE", len(self.iterations), {"tree": self.tree_sha(), "accepted": self.accepted}, {k: v for k, v in validation.items() if k != "final_tests"},
                     "passed" if validation["passed"] else "failed")
        return validation, detection, patch, reverse, changed


def heal(target, *, workdir, tests, now=None, policy=None, ffprobe="auto"):
    """Run the governed self-healing loop on an isolated copy of ``target``; never edits it in place.

    ``tests`` is ``{"start": dir, "pattern": glob}`` for the target's unittest suite.
    ``policy`` bounds the loop (see ``POLICY``); network access, production or in-place
    repair and unbounded iteration are refused with ``HealingError``. Repairs are
    deterministic and bounded: restore a route handler from its declared spec
    template, align an exact pin to an integrity-bearing lock entry, a single safe
    mutation validated by the tests, or (opt-in) removal of provably unreferenced code.
    VALIDATE passes only if every targeted failing test now passes, no baseline
    passing test fails, every finding a repair targeted is gone, every detector that
    ran at the start ran again, and the final detection holds no medium-or-higher
    finding that was absent at the start (CRITIQUE already rejects and rolls back a
    candidate that adds one). Returns a report with findings, root causes, plan, trials,
    patch, rollback data and the hash-chained receipts; writes them into a new run
    directory under ``workdir``.
    """
    now = time.time() if now is None else _finite(now)
    policy = _policy(policy)
    if ffprobe not in ("auto", None) and not isinstance(ffprobe, str):
        raise HealingError("ffprobe must be 'auto', None or a path")
    try:
        root = pathlib.Path(target).resolve(strict=True)
    except (OSError, TypeError) as error:
        raise HealingError("Target directory required") from error
    if not root.is_dir():
        raise HealingError("Target directory required")
    try:
        workdir = pathlib.Path(workdir).resolve()
    except (OSError, TypeError, RuntimeError) as error:
        raise HealingError("Workdir path required") from error
    if workdir == root or root in workdir.parents:
        raise HealingError("Workdir inside the target would repair it in place; refused")
    spec = _test_spec(tests, root)
    try:
        manifest = detectors.load_manifest(root)
    except detectors.DetectorError as error:
        raise HealingError(f"Invalid healing manifest: {error}") from None
    original = _snapshot(root)
    allowed = _allowed_files(policy, original, spec, manifest)
    workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir = pathlib.Path(tempfile.mkdtemp(prefix="heal-", dir=workdir)).resolve()
    shutil.copytree(root, run_dir / "candidate", symlinks=True, ignore=shutil.ignore_patterns(*detectors.SKIP_DIRS, "*.pyc", "*.pyo"))
    run = _Heal(root, run_dir, spec, manifest, policy, now, ffprobe, original, allowed)
    if _snapshot(run.copy) != original:
        raise HealingError("Isolated copy does not match the target")
    try:
        for iteration in range(1, policy["max_iterations"] + 1):
            run.discover(iteration)
            record = {"iteration": iteration, "findings": sorted(run.findings), "failing": run.failing(run.current.get("tests", {}))}
            run.iterations.append(record)
            if run.blocked or not (record["failing"] or run.defects(run.findings.values()) or policy["allow_dead_code_removal"] and any(
                    f["kind"] == "dead-code" for f in run.findings.values())):
                break
            analysis = run.analyze_stage(iteration)
            items = run.design(iteration, analysis)
            record.update(roots=analysis["roots"], attribution=analysis["attribution"], localization=analysis["localization"], plan=items)
            progressed = run.execute(iteration, items)
            record["plan"] = items
            if not progressed:
                break
        validation, detection, patch, reverse, changed = run.validate()
    except detectors.DetectorError as error:
        raise HealingError(f"Detector configuration error: {error}") from None
    return _report_heal(run, validation, detection, patch, reverse, changed)


def _ledger(run, detection, final_outcomes):
    first = next((it for it in run.iterations if "attribution" in it), {"attribution": {}, "plan": []})
    attribution = dict(first["attribution"])
    plans = [item for it in run.iterations for item in it.get("plan", [])]
    final_keys = {f["key"] for f in run.defects(detection["findings"])}
    # A finding can only be called gone if its detector looked again: one that did not run,
    # or an app that no longer starts (broken-apis then reports only app-start-failed and
    # integrations are skipped), leaves the initial finding unrepaired, never resolved.
    blind = {row["detector"] for row in detection["detectors"] if row["status"] != "ran"}
    if any(f["kind"] == "app-start-failed" for f in detection["findings"]):
        blind |= {"broken-apis", "integrations"}
    entries = []
    defects = [("finding:" + f["id"], f) for f in run.defects(run.initial["findings"])]
    defects += [("test:" + t, None) for t in run.failing(run.baseline.get("tests", {}))]
    for label, row in defects:
        unseen = bool(row) and row["key"] not in final_keys and row["detector"] in blind
        present = (row["key"] in final_keys or unseen) if row else not _passed(final_outcomes.get(label[5:]))
        roots = attribution.get(label, [label])
        repair = next((a for a in run.accepted if a["root"] in roots or label[5:] in a["targets"]), None)
        plan = next((p for p in plans if p["root"] in roots), None)
        status = "unrepaired" if present else "repaired" if repair else "resolved-indirectly"
        reason = None if not present else (f"not re-checked: the {row['detector']} detector could not observe the final copy" if unseen
                                           else plan["reason"] if plan and plan.get("reason") else "no repair attempted within the iteration bound")
        entries.append({"defect": label, "type": "finding" if row else "test", "kind": row["kind"] if row else "failing-test",
                        "severity": row["severity"] if row else "high", "location": row["location"] if row else None,
                        "root_causes": roots, "status": status, "repair": repair["item"] if repair else None, "reason": reason})
    known, seen = {f["key"] for f in run.initial["findings"]}, set()
    for row in run.defects(detection["findings"]):
        if row["key"] not in known and row["key"] not in seen:
            seen.add(row["key"])
            entries.append({"defect": "finding:" + row["id"], "type": "finding", "kind": row["kind"], "severity": row["severity"],
                            "location": row["location"], "root_causes": [], "status": "introduced", "repair": None,
                            "reason": "absent at the start, present in the final detection of the repaired copy"})
    return entries


def _report_heal(run, validation, detection, patch, reverse, changed):
    ledger = _ledger(run, detection, validation["final_tests"])
    remaining = [row for row in ledger if row["status"] in ("unrepaired", "introduced")]
    if run.accepted and validation["passed"]:
        status = "partially-repaired" if remaining else "repaired"
    elif run.accepted:
        status = "validation-failed"
    elif run.blocked:
        status = "blocked"
    else:
        status = "no-safe-repair" if ledger else "no-defects-found"
    artifacts = {}
    if changed:
        name = "patch.diff" if validation["passed"] else "rejected.diff"
        _write_bytes(run.run_dir, name, patch.encode("utf-8"))
        _write_bytes(run.run_dir, "reverse.diff", reverse.encode("utf-8"))
        for rel, row in changed.items():
            _write_bytes(run.run_dir, "rollback/" + rel, row["original"])
        artifacts = {"patch": str(run.run_dir / name), "reverse_patch": str(run.run_dir / "reverse.diff"), "rollback_dir": str(run.run_dir / "rollback")}
    rollback = {"original_tree_sha256": sha(run.original), "repaired_tree_sha256": run.tree_sha(),
                "method": "The target was never written. To undo an applied patch apply reverse.diff, or restore the files under rollback/.",
                "files": {rel: {"original_sha256": hashlib.sha256(row["original"]).hexdigest(), "repaired_sha256": hashlib.sha256(row["current"]).hexdigest(),
                                "backup": f"rollback/{rel}"} for rel, row in changed.items()},
                "reverse_patch_sha256": hashlib.sha256(reverse.encode("utf-8")).hexdigest() if changed else None,
                "verified": validation["checks"]["patch_and_reverse_apply"]}
    initial = run.initial
    result = {
        "schema_version": VERSION, "engine": "gaie-self-healing", "layer": "L17", "status": status, "project": run.project,
        "target": {"original_sha256": sha(run.original), "files": len(run.original), "unchanged": validation["checks"]["original_unchanged"]},
        "run_dir": str(run.run_dir), "isolated_copy": str(run.copy), "tests": run.spec,
        "policy": run.policy, "allowed_files": sorted(run.allowed),
        "detectors": [{k: r[k] for k in ("detector", "status", "reason", "method")} | {"findings": len(r["findings"])} for r in initial["detectors"]],
        "findings": initial["findings"], "final_findings": detection["findings"],
        "baseline_tests": run.baseline.get("tests", {}), "flaky_tests": run.flaky,
        "root_causes": next((it["roots"] for it in run.iterations if "roots" in it), []),
        "iterations": run.iterations, "trials": run.trials, "repairs": run.accepted, "defects": ledger,
        "validation": validation, "patch": patch if changed and validation["passed"] else None,
        "rejected_patch": patch if changed and not validation["passed"] else None,
        "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest() if changed else None,
        "artifacts": artifacts, "rollback": rollback, "receipts": run.receipts, "receipt_chain_valid": verify_receipts(run.receipts),
        "guarantees": {"applied_in_place": False, "isolated_copy": True, "original_unchanged": validation["checks"]["original_unchanged"],
                       "network_guard": "python-socket-loopback-only", "os_sandbox_claimed": False, "shell_used": False,
                       "production_mutations": 0, "deployment_allowed": False, "model_calls": 0, "requires_human_review": True},
        "evidence": {"deterministic": ["static detectors", "test outcomes", "root-cause graph", "repair candidates", "patch"],
                     "measured": ["performance timings", "memory samples"], "simulated": [], "ai_reasoning": []},
        "limits": ("Root causes are candidate roots over declared/observed dependencies, not causal proof. Repairs are only as good as "
                   "the tests; a passing validation is not a release approval. The socket guard is Python-level, not an OS sandbox."),
    }
    result["report_sha256"] = sha(result)
    _write_bytes(run.run_dir, "receipts.json", canonical(run.receipts))
    _write_bytes(run.run_dir, "report.json", canonical(result))
    return result
