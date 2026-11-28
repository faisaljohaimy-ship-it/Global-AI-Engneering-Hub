"""Evidence-based repair proposals and disposable artifact checks.

No candidate code, shell command, provider or production environment is executed.
The fixed declarative checks prove artifact properties, not application behavior.
Caller-supplied evidence needs a trusted collector; hashes do not authenticate it.
SPDX-License-Identifier: MIT
"""

import ast
import copy
import hashlib
import math
import pathlib
import re
import tempfile
import time

from .orchestration import DIGEST, SECRET, SLUG, _text, canonical, sha
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
