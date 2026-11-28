"""Machine-checked twenty-layer architecture: layer and role registries, source-bound verification.

`governance/layers.json` holds the twenty layer records (docs/specs/gaie-20-layers/CONTRACTS.md
section 1) and `governance/agent-roles.json` the owner's twenty specialist roles with their
least-privilege default grant templates. `verify` runs every test a layer lists in a fresh
subprocess and writes a receipt bound to the SHA-256 of the layer record, its test files and
every in-tree Python source the interfaces and tests imported (plus the relative import
closure of `.mjs` tests). A layer is VERIFIED only while all its tests passed in a receipt whose
sources still match the files on disk: a name, a file or a document is never evidence.

Receipts live in a private state directory outside Git. Their digests detect corruption and
staleness; they do not authenticate who ran the tests. Tests run as ordinary subprocesses, not
inside a sandbox. Everything here is deterministic code: no model is called, nothing is
simulated, and nothing remote is touched. SPDX-License-Identifier: MIT
"""
import datetime
import fnmatch
import json
import os
import pathlib
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from .contracts import (GATED, LAYER_IDS, SIDE_EFFECTS, ContractError, sha256, side_effect_rank,
                        validate_engines, validate_grant, validate_layers, validate_receipt)
from .orchestration import CoordinationError, _atomic_write, _read_private, _safe_directory, load_json

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAYERS_FILE = "governance/layers.json"
ROLES_FILE = "governance/agent-roles.json"
ENGINES_FILE = "governance/engines.json"

# The owner's twenty specialist roles (teams A-H), in the order of the directive.
ROLE_IDS = (
    "chief-engineering-architect", "twenty-layer-architecture-engineer", "control-plane-integration-engineer",
    "engineering-reasoning-engineer", "persistent-memory-engineer", "knowledge-intelligence-integration-engineer",
    "master-build-engine-engineer", "master-upgrade-engine-engineer", "nl-router-project-registry-engineer",
    "adaptive-agent-orchestration-engineer", "context-token-economics-engineer", "cinematic-production-engineer",
    "motion-sdk-animation-engineer", "gpu-3d-digital-twin-engineer", "agent-isolation-security-engineer",
    "enterprise-security-privacy-engineer", "testing-self-healing-engineer", "independent-assurance-engineer",
    "github-integration-release-engineer", "claude-code-integration-engineer",
)
TEAMS = tuple("ABCDEFGH")
# A default grant never reaches the network or a gated class; those need an explicit grant
# (and, for gated classes, an owner approval token). Reviewers write only private receipts.
DEFAULT_CEILING = "repo-write"
REVIEWER_CEILING = "state-write"
WORKSPACE_PREFIX = "workspace/"

STATUSES = ("VERIFIED", "FAILED", "INCOMPLETE", "UNVERIFIED")
RECEIPT_KIND = "gaie-layer-verification"
RECEIPT_FIELDS = frozenset({
    "schema_version", "kind", "layer", "name", "status", "reasons", "record_sha256", "interfaces", "tests",
    "sources", "source_sha256", "environment", "execution", "at", "duration_ms", "contract_receipt",
    "receipt_sha256"})
TEST_TIMEOUT = 900
OUTPUT_TAIL = 2000
MAX_SOURCES = 4000
_REL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@+-]*(?:/[A-Za-z0-9_.@+-]+)*$")
_PATTERN = re.compile(r"^[A-Za-z0-9_.*][A-Za-z0-9_.*@+-]*(?:/[A-Za-z0-9_.*@+-]+)*$")
_SKILL = re.compile(r"^skills/[a-z0-9][a-z0-9-]*/SKILL\.md$")
_PY_TEST = re.compile(r"^tests/[A-Za-z_]\w*\.py$")
_MJS_IMPORT = re.compile(
    r"""(?:\bimport\s*(?:[\w*{}\s,$]+\s*from\s*)?|\bexport\s*[\w*{}\s,$]*\s*from\s*|\bimport\s*\(\s*)['"]([^'"\n]+)['"]""")

# Evidence boundary of each layer: what the current code proves, and what it does not.
# L01-L12 keep the twelve-layer wording of ARCHITECTURE.md verbatim.
EVIDENCE_BOUNDARY = {
    "L01": "Local policy/receipt validators; provider administration is separate",
    "L02": "Deterministic policy routing; actual model access must be evidenced",
    "L03": "Explicit invocations/file-state coordination; no continuous daemon claim",
    "L04": "Existing CLI, checksummed SDK and additive operational commands",
    "L05": "Local MCP/CLI implemented; other protocols remain per-adapter candidates",
    "L06": "Existing shared skills; project implementations remain private",
    "L07": "No shared production database provisioned; project-level verification required",
    "L08": "Preserve verified CSS/WAAPI/WebGL; new engines need their own runtime proof",
    "L09": "SHA-pinned CI and test/audit evidence; no blanket compliance claim",
    "L10": "Private registry outside public Git; local preparation differs from remote completion",
    "L11": "Existing provider projects preserved; incomplete permissions block relinking",
    "L12": "Read-only discovery and reviewed update proposals; no automatic execution",
    "L13": "Deterministic ranking of supplied alternatives and schedules; no model reasoning or inferred causality",
    "L14": "Private file-backed memory outside Git; lexical retrieval, not embeddings; checksums detect corruption only",
    "L15": "Deterministic command parsing and bounded request validation; engineering_os/requirements.py is wave 2",
    "L16": "Plans and checks artifacts against supplied receipts; generates no complete application and deploys nothing",
    "L17": "Repair proposals and fixed declarative checks; candidate code is never executed",
    "L18": "Source-bound inventory and engine-motion resolution; every render needs its own browser receipt",
    "L19": "Offline accounting over supplied ledgers; tokens, cost and subscription quota stay separate",
    "L20": "Source-bound test receipts; engineering_os/assurance.py is wave 2; hashes do not authenticate reviewers",
}

# Subprocess programs. Each imports only what it is asked to, records every in-tree .py file
# opened (imports included; a private pycache prefix forces source reads) and writes JSON to a
# result file, so test output on stdout/stderr can never forge a result.
_COLLECT = r'''
import json, os, sys
ROOT = os.path.realpath(sys.argv[1]); OUT = sys.argv[2]
sys.path.insert(0, ROOT)
OPENED = set()
def _hook(event, args):
    if event == "open" and args:
        try:
            path = os.fsdecode(os.fspath(args[0]))
        except TypeError:
            return
        if path.endswith(".py"):
            OPENED.add(os.path.abspath(path))
sys.addaudithook(_hook)
def _files():
    found = set(OPENED)
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if isinstance(name, str) and name.endswith(".py"):
            found.add(os.path.abspath(name))
    return sorted(found)
def _write(doc):
    doc["files"] = _files()
    with open(OUT, "w", encoding="utf-8") as stream:
        json.dump(doc, stream)
'''
_PROBE = _COLLECT + r'''
import importlib
rows = []
for ref in json.loads(sys.argv[3]):
    module_name, attr = ref.split(":")
    try:
        module = importlib.import_module(module_name)
        target = getattr(module, attr, None)
        ok = callable(target)
        rows.append({"ref": ref, "ok": ok, "file": getattr(module, "__file__", None),
                     "error": None if ok else "not callable"})
    except BaseException as exc:
        rows.append({"ref": ref, "ok": False, "file": None, "error": (type(exc).__name__ + ": " + str(exc))[:300]})
_write({"interfaces": rows})
'''
_UNITTEST = _COLLECT + r'''
import unittest
# Import the test module the way `python3 -m unittest discover -s tests` does: top level,
# from the tests directory, with the repository root importable as well.
NAME = sys.argv[3]
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.argv = ["unittest"]
try:
    suite = unittest.defaultTestLoader.loadTestsFromName(NAME)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    doc = {"ran": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
           "skipped": len(result.skipped), "expected_failures": len(result.expectedFailures),
           "unexpected_successes": len(result.unexpectedSuccesses), "successful": result.wasSuccessful(),
           "error": None}
except BaseException as exc:
    doc = {"ran": 0, "failures": 0, "errors": 1, "skipped": 0, "expected_failures": 0,
           "unexpected_successes": 0, "successful": False, "error": (type(exc).__name__ + ": " + str(exc))[:500]}
_write(doc)
'''


class LayerError(ValueError):
    """A layer or role record, a request or the state directory is not acceptable."""


def _need(condition, message):
    if not condition:
        raise LayerError(message)


def _read_json(path):
    path = pathlib.Path(path)
    _need(path.is_file() and not path.is_symlink(), f"{path.name}: regular file required")
    try:
        return load_json(path.read_bytes().decode("utf-8"))
    except (CoordinationError, ValueError) as exc:
        raise LayerError(f"{path.name}: {exc}") from None


def _rel_ok(relative):
    return isinstance(relative, str) and bool(_REL.match(relative)) and ".." not in relative.split("/") \
        and relative.split("/")[0] != ".git"


def _safe_file(root, relative):
    """Return root/relative if it is an in-tree regular file reached without symlinks, else None."""
    if not _rel_ok(relative):
        return None
    path = root
    for part in relative.split("/"):
        path = path / part
        if path.is_symlink():
            return None
    return path if path.is_file() else None


def _module_file(root, module_name):
    """Repository-relative source of an in-tree module, found without importing it."""
    base = module_name.replace(".", "/")
    for candidate in (base + ".py", base + "/__init__.py"):
        if _safe_file(root, candidate):
            return candidate
    return None


def _package_inits(root, module_name):
    parts = module_name.split(".")[:-1]
    return [p for p in ("/".join(parts[:i]) + "/__init__.py" for i in range(1, len(parts) + 1)) if _safe_file(root, p)]


def _relative(root, absolute):
    try:
        relative = pathlib.Path(absolute).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None
    return relative if _safe_file(root, relative) and "__pycache__" not in relative.split("/") else None


def _hash_file(root, relative):
    path = _safe_file(root, relative)
    return sha256(path.read_bytes()) if path else None


def _exercised(root, record):
    """Static lower bound: every interface is named, with its module, in one of the layer's Python tests."""
    texts = [(_safe_file(root, t).read_text(encoding="utf-8", errors="replace"), t)
             for t in record["tests"] if t.endswith(".py")]
    missing = []
    for ref in record["interfaces"]:
        module_name, attr = ref.split(":")
        last = module_name.rsplit(".", 1)[-1]
        source = _module_file(root, module_name) or ""
        word = re.compile(rf"(?<![\w]){re.escape(attr)}(?![\w])")
        owner = re.compile(rf"(?<![\w]){re.escape(last)}(?![\w])")
        if not any(word.search(text) and (owner.search(text) or (source and source in text)) for text, _ in texts):
            missing.append(ref)
    return missing


def check_layers(records, *, root=ROOT):
    """Repository checks beyond the shared contract: files exist, interfaces are in-tree and exercised."""
    root = pathlib.Path(root).resolve()
    for record in records:
        lid = record["id"]
        for test in record["tests"]:
            _need(_safe_file(root, test) is not None, f"{lid}: missing test file {test}")
            _need(not test.endswith(".py") or _PY_TEST.match(test), f"{lid}: {test} is not an importable test module name")
        for skill in record["skills"]:
            _need(_SKILL.match(skill) and _safe_file(root, skill) is not None, f"{lid}: missing skill {skill}")
        for role in record["agents"]:
            _need(role in ROLE_IDS, f"{lid}: unknown role {role!r}")
        for ref in record["interfaces"]:
            _need(_module_file(root, ref.split(":")[0]) is not None, f"{lid}: interface {ref} is not a module in this tree")
        missing = _exercised(root, record)
        _need(not missing, f"{lid}: no listed Python test names interface(s) {', '.join(missing)}")
    return records


def load_layers(root=ROOT, *, check_imports=False):
    """Read governance/layers.json, validate it under the shared contract and the repository checks.

    check_imports=True resolves every interface in a fresh interpreter (see probe_interfaces), so the
    caller's own sys.path and module cache cannot make a missing callable look present."""
    root = pathlib.Path(root).resolve()
    records = _read_json(root / LAYERS_FILE)
    try:
        validate_layers(records, check_imports=False)
    except ContractError as exc:
        raise LayerError(str(exc)) from None
    check_layers(records, root=root)
    if check_imports:
        refs = sorted({ref for record in records for ref in record["interfaces"]})
        with tempfile.TemporaryDirectory(prefix="gaie-layers-") as scratch:
            failed = [row for row in probe_interfaces(refs, root=root, scratch=scratch)["interfaces"] if not row["ok"]]
        _need(not failed, "interfaces do not resolve: " + "; ".join(f"{r['ref']} ({r['error']})" for r in failed))
    return records


def select(records, layer_ids=None):
    """The records named by layer_ids (all when None), in layer order; unknown ids are refused."""
    by_id = {record["id"]: record for record in records}
    if layer_ids is None:
        return list(records)
    _need(isinstance(layer_ids, (list, tuple)) and layer_ids, "layer ids: non-empty list")
    for lid in layer_ids:
        _need(isinstance(lid, str) and lid in by_id, f"unknown layer id: {lid!r}")
    return [by_id[lid] for lid in LAYER_IDS if lid in set(layer_ids)]


# ---------------------------------------------------------------- roles

def _owned_patterns(value, field):
    _need(isinstance(value, list) and 0 < len(value) <= 32, f"{field}: 1-32 path patterns")
    for pattern in value:
        _need(isinstance(pattern, str) and _PATTERN.match(pattern) and ".." not in pattern.split("/")
              and pattern.split("/")[0] != ".git" and len(pattern) <= 200, f"{field}: unsafe pattern {pattern!r}")
    _need(len(set(value)) == len(value), f"{field}: duplicates")
    return value


def _engine_actions(engines):
    """{engine id: {action: side_effect}} from a contract-valid engine registry."""
    try:
        validate_engines(engines, check_imports=False)
    except ContractError as exc:
        raise LayerError(f"engines: {exc}") from None
    return {engine["id"]: {name: spec["side_effect"] for name, spec in engine["actions"].items()} for engine in engines}


def _check_grant_template(role, template, actions):
    rid = role["id"]
    _need(isinstance(template, dict) and set(template) == {"engines", "paths", "max_side_effect"},
          f"{rid}.default_grant: needs exactly engines, paths, max_side_effect")
    ceiling = template["max_side_effect"]
    _need(ceiling in SIDE_EFFECTS, f"{rid}.default_grant: unknown side-effect class {ceiling!r}")
    rank = side_effect_rank(ceiling)
    _need(ceiling not in GATED and rank <= side_effect_rank(DEFAULT_CEILING),
          f"{rid}.default_grant: privilege escalation, {ceiling} exceeds the default ceiling {DEFAULT_CEILING}")
    if role["reviewer"]:
        _need(rank <= side_effect_rank(REVIEWER_CEILING),
              f"{rid}.default_grant: privilege escalation, a reviewer is limited to {REVIEWER_CEILING}")
    engines = template["engines"]
    _need(isinstance(engines, dict) and 0 < len(engines) <= 16, f"{rid}.default_grant.engines: 1-16 engines")
    paths = template["paths"]
    _need(isinstance(paths, list) and len(paths) <= 16 and len(set(paths)) == len(paths),
          f"{rid}.default_grant.paths: list of up to 16 unique paths")
    writes = rank >= side_effect_rank("workspace-write")
    _need(bool(paths) == writes, f"{rid}.default_grant.paths: write classes need scoped paths and only they may have any")
    for path in paths:
        _need(isinstance(path, str) and _PATTERN.match(path) and ".." not in path.split("/"),
              f"{rid}.default_grant.paths: unsafe path {path!r}")
        if ceiling == "workspace-write":
            _need(path.startswith(WORKSPACE_PREFIX), f"{rid}.default_grant.paths: workspace writes stay under {WORKSPACE_PREFIX}")
        else:
            _need(any(path == own or fnmatch.fnmatchcase(path, own) for own in role["owns"]),
                  f"{rid}.default_grant.paths: privilege escalation, {path} is not owned by the role")
    for engine, granted in engines.items():
        _need(isinstance(engine, str) and re.match(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", engine), f"{rid}: engine id {engine!r}")
        _need(isinstance(granted, list) and granted and len(set(granted)) == len(granted), f"{rid}.{engine}: actions list")
        for action in granted:
            _need(isinstance(action, str) and re.match(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", action), f"{rid}.{engine}: action {action!r}")
            if actions is not None:
                _need(engine in actions and action in actions[engine], f"{rid}: unknown engine action {engine}.{action}")
                effect = actions[engine][action]
                _need(effect not in GATED and side_effect_rank(effect) <= rank,
                      f"{rid}: privilege escalation, {engine}.{action} is {effect} above {ceiling}")


def validate_roles(document, *, layers=None, engines=None):
    """Validate the role registry. With layers, roles and layer agents must agree both ways; with an
    engine registry, every granted action must exist and stay within the template's side-effect class."""
    _need(isinstance(document, dict) and set(document) == {"schema_version", "teams", "roles"}, "roles: needs schema_version, teams, roles")
    _need(document["schema_version"] == 1, "roles: schema_version 1")
    teams = document["teams"]
    _need(isinstance(teams, dict) and tuple(sorted(teams)) == TEAMS, "roles: teams A-H")
    for key, title in teams.items():
        _need(isinstance(title, dict) and set(title) == {"en", "ar"} and all(isinstance(title[k], str) and title[k].strip() for k in title),
              f"team {key}: bilingual title")
    roles = document["roles"]
    _need(isinstance(roles, list), "roles: list required")
    ids = [role.get("id") if isinstance(role, dict) else None for role in roles]
    unknown = [rid for rid in ids if rid not in ROLE_IDS]
    _need(not unknown, f"roles: unknown role(s) {unknown}")
    _need(len(set(ids)) == len(ids), "roles: duplicate role ids")
    _need(tuple(ids) == ROLE_IDS, "roles: exactly the owner's twenty roles, in order")
    actions = _engine_actions(engines) if engines is not None else None
    for role in roles:
        rid = role["id"]
        _need(set(role) == {"id", "team", "title", "summary", "layers", "owns", "reviewer", "default_grant"},
              f"{rid}: fields must be id, team, title, summary, layers, owns, reviewer, default_grant")
        _need(role["team"] in TEAMS, f"{rid}: team {role['team']!r}")
        title = role["title"]
        _need(isinstance(title, dict) and set(title) == {"en", "ar"} and all(isinstance(title[k], str) and title[k].strip() for k in title),
              f"{rid}: bilingual title")
        _need(isinstance(role["summary"], str) and 0 < len(role["summary"]) <= 300, f"{rid}: summary")
        _need(isinstance(role["layers"], list) and role["layers"] and all(lid in LAYER_IDS for lid in role["layers"])
              and role["layers"] == sorted(set(role["layers"])), f"{rid}: layers must be sorted unique L01-L20 ids")
        _owned_patterns(role["owns"], f"{rid}.owns")
        _need(isinstance(role["reviewer"], bool), f"{rid}: reviewer flag")
        _check_grant_template(role, role["default_grant"], actions)
    _need(set(TEAMS) == {role["team"] for role in roles}, "roles: every team A-H needs a role")
    if layers is not None:
        listed = {rid: sorted(r["id"] for r in layers if rid in r["agents"]) for rid in ROLE_IDS}
        for role in roles:
            _need(role["layers"] == listed[role["id"]],
                  f"{role['id']}: role layers {role['layers']} differ from the layers that list it {listed[role['id']]}")
    return document


def load_roles(root=ROOT, *, layers=None):
    """Read and validate governance/agent-roles.json against the layers and, when present, governance/engines.json."""
    root = pathlib.Path(root).resolve()
    document = _read_json(root / ROLES_FILE)
    records = layers if layers is not None else load_layers(root)
    engines = _read_json(root / ENGINES_FILE) if (root / ENGINES_FILE).exists() else None
    if isinstance(engines, dict) and "engines" in engines:  # tolerate a {"schema_version", "engines"} wrapper
        engines = engines["engines"]
    return validate_roles(document, layers=records, engines=engines)


def instantiate_grant(role, grant_id, expires_at):
    """Turn a role's default template into a contract-valid grant (no approvals: defaults are never gated)."""
    template = role["default_grant"]
    grant = {"grant_id": grant_id, "role": role["id"],
             "engines": {engine: list(granted) for engine, granted in template["engines"].items()},
             "paths": list(template["paths"]), "max_side_effect": template["max_side_effect"],
             "expires_at": expires_at, "approvals": []}
    try:
        return validate_grant(grant)
    except ContractError as exc:
        raise LayerError(f"{role['id']}: {exc}") from None


def validate(root=ROOT):
    """Full static and import check of both registries (interfaces resolved in a fresh interpreter)."""
    records = load_layers(root, check_imports=True)
    roles = load_roles(root, layers=records)
    return {"layers": len(records), "roles": len(roles["roles"]), "ok": True}


# ---------------------------------------------------------------- state

def default_state_dir(environ=None):
    """$GAIE_HOME/layers (default ~/.gaie/layers); never inside a Git work tree."""
    environ = os.environ if environ is None else environ
    home = pathlib.Path(environ.get("GAIE_HOME") or pathlib.Path.home() / ".gaie").expanduser()
    return home / "layers"


def _state(state_dir, *, create):
    path = pathlib.Path(state_dir if state_dir is not None else default_state_dir()).expanduser().absolute()
    if not create and not path.exists():
        return None
    try:
        return _safe_directory(path)
    except (CoordinationError, OSError) as exc:
        raise LayerError(f"state directory refused: {exc}") from None


# ---------------------------------------------------------------- execution

def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env(scratch, extra=None):
    env = dict(os.environ)
    env["PYTHONPYCACHEPREFIX"] = str(pathlib.Path(scratch) / "pycache")
    env.update(extra or {})
    return env


def _run(argv, *, root, scratch, timeout, extra_env=None):
    """Run argv in its own process group; kill the whole group on timeout."""
    started = time.monotonic()
    process = subprocess.Popen(argv, cwd=root, env=_env(scratch, extra_env), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        output, _ = process.communicate()
        timed_out = True
    elapsed = int((time.monotonic() - started) * 1000)
    return process.returncode, output.decode("utf-8", "replace"), elapsed, timed_out


def probe_interfaces(refs, *, root=ROOT, scratch, timeout=120):
    """Resolve 'module:callable' references in a fresh interpreter; report each and the in-tree files imported."""
    root = pathlib.Path(root).resolve()
    out = pathlib.Path(scratch) / f"probe-{sha256(list(refs))[:16]}.json"
    code, output, _, timed_out = _run([sys.executable, "-c", _PROBE, str(root), str(out), json.dumps(list(refs))],
                                      root=root, scratch=scratch, timeout=timeout)
    if timed_out or not out.is_file():
        reason = "timeout" if timed_out else f"probe exited {code}: {output[-300:]}"
        return {"interfaces": [{"ref": ref, "ok": False, "file": None, "error": reason} for ref in refs], "files": []}
    doc = json.loads(out.read_text(encoding="utf-8"))
    for row in doc["interfaces"]:
        row["file"] = _relative(root, row["file"]) if row["file"] else None
        if row["ok"] and row["file"] is None:
            row.update(ok=False, error="resolved outside this tree")
    doc["files"] = sorted({rel for rel in (_relative(root, name) for name in doc["files"]) if rel})
    return doc


def _mjs_closure(root, test):
    """Relative ES-module import closure of an .mjs test (bare and node: specifiers are not in-tree)."""
    seen, pending = set(), [test]
    while pending and len(seen) < MAX_SOURCES:
        relative = pending.pop()
        if relative in seen:
            continue
        path = _safe_file(root, relative)
        if path is None:
            continue
        seen.add(relative)
        if not relative.endswith((".mjs", ".js")):
            continue
        for spec in _MJS_IMPORT.findall(path.read_text(encoding="utf-8", errors="replace")):
            if spec.startswith(("./", "../")):
                target = _relative(root, (path.parent / spec.split("?")[0]).resolve())
                if target:
                    pending.append(target)
    return sorted(seen)


def _result(path, runner, status, *, reason=None, ran=0, passed=0, failed=0, errors=0, skipped=0,
            expected_failures=0, duration_ms=0, returncode=None, output=""):
    row = {"path": path, "runner": runner, "status": status, "ran": ran, "passed": passed, "failed": failed,
           "errors": errors, "skipped": skipped, "expected_failures": expected_failures,
           "duration_ms": duration_ms, "returncode": returncode, "reason": reason}
    row["output_tail"] = output[-OUTPUT_TAIL:] if status in {"failed", "error"} else ""
    return row


def _run_python_test(root, test, scratch, timeout):
    out = pathlib.Path(scratch) / f"test-{sha256(test)[:16]}.json"
    name = test[len("tests/"):-len(".py")]
    code, output, elapsed, timed_out = _run(
        [sys.executable, "-c", _UNITTEST, str(root), str(out), name], root=root, scratch=scratch, timeout=timeout)
    if timed_out:
        return _result(test, "python-unittest", "error", reason=f"timeout after {timeout}s", duration_ms=elapsed,
                       returncode=code, output=output), []
    if not out.is_file():
        return _result(test, "python-unittest", "error", reason=f"runner exited {code} without a result",
                       duration_ms=elapsed, returncode=code, output=output), []
    doc = json.loads(out.read_text(encoding="utf-8"))
    files = sorted({rel for rel in (_relative(root, name) for name in doc["files"]) if rel})
    bad = doc["failures"] + doc["errors"] + doc["unexpected_successes"]
    counted = dict(ran=doc["ran"], passed=doc["ran"] - bad - doc["skipped"], failed=doc["failures"] + doc["unexpected_successes"],
                   errors=doc["errors"], skipped=doc["skipped"], expected_failures=doc["expected_failures"],
                   duration_ms=elapsed, returncode=code, output=output)
    if doc["error"]:
        return _result(test, "python-unittest", "error", reason=doc["error"], **counted), files
    if not doc["successful"] or bad:
        return _result(test, "python-unittest", "failed", reason=f"{bad} failing test(s)", **counted), files
    if doc["ran"] - doc["skipped"] <= 0:
        return _result(test, "python-unittest", "skipped", reason="no test ran (all skipped or none collected)", **counted), files
    return _result(test, "python-unittest", "passed", **counted), files


def _tap(output, key):
    match = re.search(rf"^# {key} (\d+)\s*$", output, re.MULTILINE)
    return int(match.group(1)) if match else 0


def _run_node_test(root, test, scratch, timeout, node):
    files = _mjs_closure(root, test)
    if not node:
        return _result(test, "node-test", "skipped", reason="node is not available on this host"), files
    code, output, elapsed, timed_out = _run([node, "--test", "--test-reporter=tap", test], root=root,
                                            scratch=scratch, timeout=timeout)
    tests, passed, failed = _tap(output, "tests"), _tap(output, "pass"), _tap(output, "fail")
    skipped, cancelled = _tap(output, "skipped") + _tap(output, "todo"), _tap(output, "cancelled")
    counted = dict(ran=tests, passed=passed, failed=failed + cancelled, skipped=skipped, duration_ms=elapsed,
                   returncode=code, output=output)
    if timed_out:
        return _result(test, "node-test", "error", reason=f"timeout after {timeout}s", **counted), files
    if code != 0 or failed or cancelled:
        return _result(test, "node-test", "failed", reason=f"exit {code}, {failed + cancelled} failing test(s)", **counted), files
    if passed <= 0:
        return _result(test, "node-test", "skipped", reason="no test passed (all skipped or none collected)", **counted), files
    return _result(test, "node-test", "passed", **counted), files


def _declared(root, record):
    """Sources a receipt must always bind: interface modules (with their packages) and test files."""
    declared = set(record["tests"])
    for ref in record["interfaces"]:
        module_name = ref.split(":")[0]
        declared.add(_module_file(root, module_name))
        declared.update(_package_inits(root, module_name))
    return sorted(p for p in declared if p)


def verify(layer_ids=None, *, state_dir=None, root=ROOT, timeout=TEST_TIMEOUT, node="auto"):
    """Run each selected layer's tests and write one source-bound receipt per layer to the private state dir.

    node="auto" uses the node on PATH; node=None (or False) reports .mjs tests as skipped, never as passed.
    Each test file runs once per call even when several layers list it."""
    root = pathlib.Path(root).resolve()
    records = select(load_layers(root), layer_ids)
    state = _state(state_dir, create=True)
    node_path = shutil.which("node") if node == "auto" else (node or None)
    node_version = None
    if node_path:
        try:
            node_version = subprocess.run([node_path, "--version"], capture_output=True, text=True, timeout=30).stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            node_path = None
    environment = {"python": platform.python_version(), "node": node_version, "platform": sys.platform}
    cache, summaries = {}, []
    with tempfile.TemporaryDirectory(prefix="gaie-layers-") as scratch:
        for record in records:
            started = time.monotonic()
            declared = _declared(root, record)
            before = {path: _hash_file(root, path) for path in declared}
            probe = probe_interfaces(record["interfaces"], root=root, scratch=scratch)
            runs = []
            for test in record["tests"]:
                if test not in cache:
                    if test.endswith(".py"):
                        cache[test] = _run_python_test(root, test, scratch, timeout)
                    else:
                        cache[test] = _run_node_test(root, test, scratch, timeout, node_path)
                runs.append(cache[test])
            observed = set(declared) | set(probe["files"])
            for _, files in runs:
                observed.update(files)
            _need(len(observed) <= MAX_SOURCES, f"{record['id']}: more than {MAX_SOURCES} source files")
            sources = {path: _hash_file(root, path) for path in sorted(observed)}
            reasons = [f"interface {row['ref']} did not resolve: {row['error']}" for row in probe["interfaces"] if not row["ok"]]
            reasons += [f"{row['path']}: {row['status']} ({row['reason']})" for row, _ in runs if row["status"] != "passed"]
            moved = sorted(path for path in declared if before[path] != sources.get(path))
            if moved:
                reasons.append("sources changed during verification: " + ", ".join(moved))
            missing = sorted(path for path, digest in sources.items() if digest is None)
            sources = {path: digest for path, digest in sources.items() if digest is not None}
            if any(not row["ok"] for row in probe["interfaces"]) or moved or any(p in declared for p in missing) \
                    or any(row["status"] in {"failed", "error"} for row, _ in runs):
                status = "FAILED"
            elif any(row["status"] == "skipped" for row, _ in runs):
                status = "INCOMPLETE"
            else:
                status = "VERIFIED"
            receipt = _receipt(record, status, reasons, probe["interfaces"], [row for row, _ in runs], sources,
                               environment, int((time.monotonic() - started) * 1000))
            try:
                _atomic_write(state / f"{record['id']}.json", receipt)
            except (CoordinationError, OSError) as exc:
                raise LayerError(f"{record['id']}: receipt not written ({exc})") from None
            summaries.append(_summary(record, receipt, status, reasons))
    return {"ok": all(row["status"] == "VERIFIED" for row in summaries), "node": node_version,
            "state_dir": str(state), "layers": summaries}


def _receipt(record, status, reasons, interfaces, tests, sources, environment, duration_ms):
    at = _now()
    source_digest = sha256(sources)
    body = {
        "schema_version": 1, "kind": RECEIPT_KIND, "layer": record["id"], "name": record["name"],
        "status": status, "reasons": reasons, "record_sha256": sha256(record),
        "interfaces": interfaces, "tests": tests, "sources": sources, "source_sha256": source_digest,
        "environment": environment,
        "execution": {"mode": "subprocess", "sandboxed": False, "simulated": False, "model_calls": 0},
        "at": at, "duration_ms": duration_ms,
        "contract_receipt": {
            "request_sha256": sha256({"layer": record["id"], "record_sha256": sha256(record), "tests": record["tests"]}),
            "result_sha256": sha256({"status": status, "interfaces": interfaces,
                                     "tests": [{k: row[k] for k in ("path", "status", "ran", "passed", "failed", "errors", "skipped")}
                                               for row in tests]}),
            "grant_id": "local-cli", "side_effect": "workspace-write", "duration_ms": duration_ms,
            "at": at, "source_sha256": source_digest},
    }
    return {**body, "receipt_sha256": sha256(body)}


def _summary(record, receipt, status, reasons):
    tests = receipt["tests"]
    return {"id": record["id"], "name": record["name"], "status": status,
            "tests_passed": sum(row["status"] == "passed" for row in tests), "tests_total": len(tests),
            "test_cases": sum(row["passed"] for row in tests), "sources": len(receipt["sources"]),
            "at": receipt["at"], "reasons": reasons}


# ---------------------------------------------------------------- receipts and status

def receipt_status(record, receipt, *, root=ROOT):
    """Status a receipt still supports for a layer record now: its own status while it is intact,
    consistent and bound to the current record and files, else UNVERIFIED with the reason."""
    root = pathlib.Path(root).resolve()

    def unverified(reason, changed=()):
        return {"status": "UNVERIFIED", "reason": reason, "changed": list(changed),
                "at": receipt.get("at") if isinstance(receipt, dict) else None}

    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        return unverified("receipt fields do not match the schema")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt["receipt_sha256"] != sha256(body):
        return unverified("receipt digest mismatch (corrupt or edited receipt)")
    if receipt["schema_version"] != 1 or receipt["kind"] != RECEIPT_KIND or receipt["layer"] != record["id"]:
        return unverified("receipt is for another kind or layer")
    if receipt["status"] not in {"VERIFIED", "FAILED", "INCOMPLETE"}:
        return unverified("receipt status outside the vocabulary")
    try:
        validate_receipt(receipt["contract_receipt"])
    except ContractError as exc:
        return unverified(f"contract receipt invalid ({exc})")
    sources = receipt["sources"]
    if not isinstance(sources, dict) or receipt["source_sha256"] != sha256(sources) \
            or receipt["contract_receipt"]["source_sha256"] != receipt["source_sha256"]:
        return unverified("source digest mismatch")
    if receipt["record_sha256"] != sha256(record):
        return unverified("layer record changed since the receipt")
    tests, interfaces = receipt["tests"], receipt["interfaces"]
    if not isinstance(tests, list) or [row.get("path") for row in tests if isinstance(row, dict)] != record["tests"] \
            or not isinstance(interfaces, list) or [row.get("ref") for row in interfaces if isinstance(row, dict)] != record["interfaces"]:
        return unverified("receipt does not cover exactly the layer's tests and interfaces")
    if not set(_declared(root, record)) <= set(sources):
        return unverified("receipt does not bind every interface module and test file")
    if receipt["status"] == "VERIFIED" and not (all(row.get("status") == "passed" for row in tests)
                                                and all(row.get("ok") is True for row in interfaces)):
        return unverified("receipt claims VERIFIED without every test passing")
    changed = []
    for relative, digest in sorted(sources.items()):
        if not _rel_ok(relative) or _hash_file(root, relative) != digest:
            changed.append(relative)
    if changed:
        return unverified(f"stale receipt: {len(changed)} source file(s) changed", changed)
    return {"status": receipt["status"], "reason": "; ".join(receipt["reasons"]) or None, "changed": [],
            "at": receipt["at"]}


def status(layer_ids=None, *, state_dir=None, root=ROOT):
    """Read-only status of each layer from its latest receipt; never runs tests or creates state."""
    root = pathlib.Path(root).resolve()
    records = select(load_layers(root), layer_ids)
    state = _state(state_dir, create=False)
    rows = []
    for record in records:
        path = state / f"{record['id']}.json" if state else None
        if path is None or not (path.exists() or path.is_symlink()):
            current = {"status": "UNVERIFIED", "reason": "no receipt", "changed": [], "at": None}
        else:
            try:
                current = receipt_status(record, _read_private(path), root=root)
            except (CoordinationError, OSError, ValueError) as exc:
                current = {"status": "UNVERIFIED", "reason": f"unreadable receipt ({exc})", "changed": [], "at": None}
        rows.append({"id": record["id"], "name": record["name"], **current})
    return rows


def architecture(*, state_dir=None, root=ROOT):
    """The twenty-layer projection. L01-L12 keep every field of control.architecture() and its
    evidence-boundary wording; each row adds names, interfaces, tests and receipt status."""
    from . import control
    root = pathlib.Path(root).resolve()
    base = control.architecture()
    legacy = {row["id"]: row for row in base["layers"]}
    records = load_layers(root)
    try:
        statuses = {row["id"]: row for row in status(state_dir=state_dir, root=root)}
    except LayerError as exc:
        statuses = {lid: {"status": "UNVERIFIED", "reason": str(exc)} for lid in LAYER_IDS}
    rows = []
    for record in records:
        lid = record["id"]
        sources = sorted(set(_declared(root, record)))
        old = legacy.get(lid)
        row = dict(old) if old else {
            "id": lid, "name": record["name"]["en"], "target": True,
            "available_source": [p for p in sources if _safe_file(root, p)],
            "missing_source": [p for p in sources if not _safe_file(root, p)],
            "operational_proof": "See module-specific receipts; file existence alone is not proof."}
        row.update({"legacy_name": old["name"] if old else None, "name": record["name"]["en"],
                    "name_ar": record["name"]["ar"], "evidence_boundary": EVIDENCE_BOUNDARY[lid],
                    "depends_on": record["depends_on"], "interfaces": record["interfaces"], "tests": record["tests"],
                    "status": statuses[lid]["status"], "status_reason": statuses[lid].get("reason")})
        rows.append(row)
    return {**{k: v for k, v in base.items() if k != "layers"}, "layer_count": len(rows),
            "registry": LAYERS_FILE, "legacy_projection": "engineering_os.control:architecture (L01-L12)",
            "evidence_rule": "A layer is VERIFIED only when every listed test passes in a receipt bound to the "
                             "SHA-256 of its current sources (python3 hub.py layers --verify).",
            "layers": rows}


def table(rows):
    """Plain-text table: id, English and Arabic names, status (and the reason when not VERIFIED)."""
    lines = [f"{'ID':<4} {'STATUS':<11} {'LAYER':<46} ARABIC NAME", "-" * 96]
    for row in rows:
        lines.append(f"{row['id']:<4} {row['status']:<11} {row['name']['en']:<46} {row['name']['ar']}")
        reason = row.get("reason") or ("; ".join(row.get("reasons") or []) if row["status"] != "VERIFIED" else None)
        if reason and row["status"] != "VERIFIED":
            lines.append(f"{'':<4} {'':<11} - {reason[:160]}")
    counts = {name: sum(row["status"] == name for row in rows) for name in STATUSES}
    lines.append("-" * 96)
    lines.append("  ".join(f"{name}={count}" for name, count in counts.items()))
    return "\n".join(lines)
