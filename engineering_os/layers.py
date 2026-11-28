"""Machine-checked twenty-layer architecture: layer and role registries, source-bound verification.

`governance/layers.json` holds the twenty layer records (docs/specs/gaie-20-layers/CONTRACTS.md
section 1) and `governance/agent-roles.json` the owner's twenty specialist roles with their
least-privilege default grant templates. `verify` runs every test a layer lists in a fresh
subprocess and writes a receipt bound to the SHA-256 of the layer record, its test files and
every in-tree Python source the interfaces and tests imported (plus the relative import
closure of `.mjs` tests). A layer is VERIFIED only while all its tests passed in a receipt whose
sources still match the files on disk: a name, a file or a document is never evidence.

Receipts live in a private state directory outside Git. Their digests detect corruption and
staleness; they do not authenticate who ran the tests. Every test and interface probe gets an
exact minimal environment (PATH, a private HOME, TMPDIR, LANG; nothing else of the caller's)
and runs in the governor's OS sandbox where this host can build it (the repository read-only,
one private writable directory per run, no network; see `_run`). A test on the recorded
exception list (keyed by path and the SHA-256 of the reviewed bytes; an edited file runs strict),
or every test on a host without the sandbox, runs as an ordinary subprocess with that
environment; each receipt records the profile and tier actually used. Everything
here is deterministic code: no model is called, nothing is simulated, and nothing remote is
touched. SPDX-License-Identifier: MIT
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
import stat
import subprocess
import sys
import tempfile
import time

from .contracts import (GATED, LAYER_IDS, SIDE_EFFECTS, ContractError, sha256, side_effect_rank,
                        validate_engines, validate_grant, validate_layers, validate_receipt)
from .orchestration import CoordinationError, _atomic_write, _read_private, _safe_directory, load_json
from . import governor

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
    "L20": "Source-bound test receipts; engineering_os/assurance.py is not yet integrated; hashes do not authenticate reviewers",
}

# Subprocess programs. Each imports only what it is asked to and writes JSON to a result file,
# so nothing a test prints is parsed as a result. In-tree sources are observed without changing
# how tests run: no audit hook, no environment change (both alter subprocess and bytecode
# behaviour that some tests assert). The observation is the modules left in sys.modules plus the
# locations passed to importlib.util.spec_from_file_location, which is wrapped transparently.
_COLLECT = r'''
import importlib.util, json, os, sys
ROOT = os.path.realpath(sys.argv[1]); OUT = sys.argv[2]
sys.path.insert(0, ROOT)
LOADED = set()
_spec_from_file_location = importlib.util.spec_from_file_location
def _recording_spec_from_file_location(*args, **kwargs):
    location = kwargs.get("location", args[1] if len(args) > 1 else None)
    try:
        LOADED.add(os.path.abspath(os.fsdecode(os.fspath(location))))
    except TypeError:
        pass
    return _spec_from_file_location(*args, **kwargs)
importlib.util.spec_from_file_location = _recording_spec_from_file_location
def _files():
    found = {name for name in LOADED if name.endswith(".py")}
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
_RUN_SUITE = r'''
sys.argv = ["unittest"]
try:
    suite = _suite()
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
_UNITTEST = _COLLECT + r'''
import unittest
# Import the test module the way `python3 -m unittest discover -s tests` does: top level,
# from the tests directory, with the repository root importable as well.
NAME = sys.argv[3]
sys.path.insert(0, os.path.join(ROOT, "tests"))
def _suite():
    return unittest.defaultTestLoader.loadTestsFromName(NAME)
''' + _RUN_SUITE
# A reviewed process-only exception (PROCESS_ONLY_TESTS), started as `python -I -c`: no current
# directory, user site or PYTHON* variable on the path, standard modules imported before any
# repository path, the tests directory never on sys.path, and exactly the bytes whose SHA-256 was
# reviewed, compiled here (a __pycache__ entry is never used for the test module).
_PINNED_UNITTEST = "import hashlib, types, unittest\n" + _COLLECT + r'''
NAME, PIN = sys.argv[3], sys.argv[4]
def _suite():
    path = os.path.join(ROOT, "tests", NAME + ".py")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        source = stream.read()
    if hashlib.sha256(source).hexdigest() != PIN:
        raise ImportError("the test file is not the reviewed one (sha256 differs); not run")
    module = types.ModuleType(NAME)
    module.__file__ = path
    sys.modules[NAME] = module
    exec(compile(source, path, "exec", dont_inherit=True), module.__dict__)
    return unittest.defaultTestLoader.loadTestsFromModule(module)
''' + _RUN_SUITE


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
    if actions is not None:  # least privilege: the ceiling is exactly what the granted actions need
        needed = max(side_effect_rank(actions[engine][action]) for engine, granted in engines.items() for action in granted)
        _need(rank == needed, f"{rid}.default_grant: over-broad ceiling, {ceiling} where the granted actions "
                              f"need only {SIDE_EFFECTS[needed]}")


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


# Sandbox profiles of `_run` (governor.sandbox_run on its full tier):
#   strict    require_fs_isolation: repository read-only, /etc hidden, socket() denied (seccomp)
#   loopback  non-strict with a private loopback and /etc hidden, for tests that run a local server
# A test on PROCESS_ONLY_TESTS runs as a plain subprocess with the same scrubbed environment, but only
# while its bytes (and the fixture trees it executes) still match the digests reviewed below.
SANDBOX_MEMORY_MB = 16384  # RLIMIT_AS; V8 reserves far more address space than it uses
SANDBOX_FILE_MB = 256
SANDBOX_NOFILE = 1024
ETC_VISIBLE = ("/etc/ld.so.cache", "/etc/alternatives")
TOOLS = ("node",)  # tools the hub's tests start by name; their bin directory is mounted read-only
LOOPBACK_TESTS = frozenset({"tests/test_build_fixes_app.py",  # starts generated apps on 127.0.0.1
                            "tests/test_heal_fixes_2_findings.py"})  # its runtime detectors pick a free loopback port
# Measured 2026-11-28 (every layer-bound test file and the wave-2 candidates, strict and loopback):
# all others pass inside the strict profile. These cannot be measured there, so they run in the
# scrubbed process-only mode and each receipt names the reason.
#
# Each exception is keyed by its path AND the SHA-256 of the reviewed file bytes ("sha256"), plus the
# tree digest (`_tree_digest`) of every repository fixture tree the test executes outside a sandbox
# ("executes"; test_self_healing_loop and test_upgrade_engine rerun a fixture's suite in a plain
# subprocess). A file or fixture whose bytes differ from the review, or an entry without a valid digest,
# runs in the strict profile like any other test, and its receipt row says why. A matching file runs
# under `python -I` from the very bytes that were hashed (compiled by the runner, never read from a
# __pycache__ entry) with the tests directory off sys.path, so a module or bytecode planted next to it
# in tests/ is not executed. Still outside any sandbox: the repository modules the reviewed code
# imports, and a fixture swapped between the check and the run (detected after the run and reported as
# an error, not prevented). Hence SEC-12 reads "mitigated", not "fixed", while this list is non-empty.
# A legitimate edit of a listed file needs a review and a new digest here (`exception_digests`;
# tests/test_sec_fixes_2_layers.py names the stale entries); until then the file runs strict.
_NESTED = ("builds its own governor sandbox for the code it tests; namespaces cannot be nested inside the layer "
           "sandbox (inner tier measured plain), so inside it would only take its refusal branches")
_HEALING_FIXTURE = {"tests/fixtures/healing/webapp": "2188065d6fbfe193850e2963186f7ac581beecfcfda560be1a11381376676f91"}
_UPGRADE_FIXTURE = {"tests/fixtures/upgrade/taskapp": "b2d4137b308aefad07ea4daedace1913215f303ee0b1aa48662cf488af4538af"}
PROCESS_ONLY_TESTS = {
    "tests/test_p3_cage.py": {
        "sha256": "35d815d185a07601c19b21dedc642ad99e2a4e45540558a971806c80491a3df3", "executes": {},
        "reason": ("the swarm cage chowns its workspace to uid 65534; the layer sandbox's user namespace maps only the "
                   "caller, so chown gives EINVAL (frozen file)")},
    "tests/test_governor.py": {
        "sha256": "a9ecb86313c19d8a73e30360311794c4ad91caa4787b5c1eace7107193c7a297", "executes": {},
        "reason": "tests the governor sandbox itself and " + _NESTED},
    "tests/test_workspace_policy.py": {
        "sha256": "dc13ac40601b45cfa85ad78444915738ea5b06c64ba87291cfcc95946cabfdf8", "executes": {},
        "reason": "tests the strict workspace supervisor, which " + _NESTED},
    "tests/test_isolation_enforcement.py": {
        "sha256": "af6e81e816d029794ea308902b29109c33bb365f2d90414590f24edd3de02363", "executes": {},
        "reason": "measures the isolation walls, which " + _NESTED},
    "tests/test_healing.py": {
        "sha256": "c9db68edb535053202065cb05db121adef0e85f1df77326cc7ee784b652a3fea", "executes": _HEALING_FIXTURE,
        "reason": "runs detectors.Sandbox, which " + _NESTED},
    "tests/test_self_healing_loop.py": {
        "sha256": "32e838bb95d8233ed67eb24ba30548023d4d4f8929b18c5de92bda4dc797979b", "executes": _HEALING_FIXTURE,
        "reason": "runs heal() through detectors.Sandbox, which " + _NESTED},
    "tests/test_upgrade_engine.py": {
        "sha256": "97143ee5503475360eccba8169e41e1caa73f1831bd87a37395c36cc975ed1e6", "executes": _UPGRADE_FIXTURE,
        "reason": "runs upgrade() through detectors.Sandbox, which " + _NESTED},
    "tests/test_w2_fixes_healing.py": {
        "sha256": "5f602ee8413cccec99cf1e3d4894756889f2cdf35cc14e3e5b9b436f3bcd923c", "executes": {},
        "reason": "runs heal() through detectors.Sandbox, which " + _NESTED},
    "tests/test_w2_fixes_patch.py": {
        "sha256": "fa6bc19fb5b8f830087d0088c604e2552b2b2fd7db25c5b6000ebf7089089ba2", "executes": {},
        "reason": "runs heal() through detectors.Sandbox, which " + _NESTED},
    "tests/test_isolation_fixes_governor.py": {
        "sha256": "25694fea54903b7e591f0c600d87d5863ca5dcdd1b4b855150612f11e8c6e4e5", "executes": {},
        "reason": "tests the governor sandbox itself (pr30-isolation F4, F6, F7) and " + _NESTED},
    "tests/test_isolation_fixes_planted_git.py": {
        "sha256": "0393f5db1a9acc5252d68472eb2e0fee4ecd69037aaf75953556cb28a9e5ef57", "executes": {},
        "reason": "runs strict workspace children that plant Git metadata, which " + _NESTED},
    "tests/test_isolation_fixes_relaunch.py": {
        "sha256": "467105df68027a4d518911a8f7ba7799d1a10958cac109750095ffa47989539f", "executes": {},
        "reason": "relaunches the strict workspace supervisor, which " + _NESTED},
    "tests/test_isolation_fixes_mounts.py": {
        "sha256": "eee8c3e127a67022ebb55fc081b51f7fd9281bad18f9b03d5062552d0fe9da21", "executes": {},
        "reason": "reads the strict sandbox's own mount table (recheck-isolation item 1), which " + _NESTED},
    "tests/test_isolation_fixes_relaunch_binding.py": {
        "sha256": "9ed4a1a16cf9a3989cb738f14c23901b2b9a84cd42baa8d04bab9c224f9476dc", "executes": {},
        "reason": "binds --relaunch to a recorded strict launch, which " + _NESTED},
    "tests/test_gaie_memory_journal.py": {
        "sha256": "ed9d671fa9a2973a12e1cfe50b404a547ce69579994b6dba8b72eb6e2e582f5d", "executes": {},
        "reason": ("chowns its memory directories to uid 65534 to prove a foreign owner is refused; the layer "
                   "sandbox's user namespace maps only the caller, so chown gives EINVAL")},
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _python():
    """The interpreter file itself (/etc is hidden in the sandbox, so a link through
    /etc/alternatives would dangle); a virtual environment keeps its own launcher."""
    return sys.executable if sys.prefix != sys.base_prefix else os.path.realpath(sys.executable)


def _trusted_dir(real):
    """True when the real directory `real` may be shown read-only to a sandboxed test: outside every home
    directory, and neither it nor a directory above it can be changed by a non-root user. The governor's
    own rule for program mounts (governor._trusted_source) where this checkout has it; else the same rule
    in short (the caller's home, /root and /home; owner root and no group/other write bit up to /)."""
    check = getattr(governor, "_trusted_source", None)
    if check is not None:
        try:
            check(real)
            return True
        except governor.GovernorDenied:
            return False
    homes = {os.path.realpath(os.path.expanduser("~")), "/root", "/home"}
    if any(real == home or real.startswith(home + os.sep) for home in homes if home != "/"):
        return False
    current = real
    while True:
        try:
            info = os.lstat(current)
        except OSError:
            return False
        if info.st_uid != 0 or info.st_mode & 0o022:
            return False
        if current == os.sep:
            return True
        current = os.path.dirname(current)


def _outside_system(paths):
    """Real directories outside the system directories that must be mounted read-only (a tool's bin
    directory, a virtual environment's tree), never the caller's home directory itself or a directory
    that contains it, and only where `_trusted_dir` accepts them (recheck-isolation-2 item 4)."""
    home = os.path.realpath(os.path.expanduser("~"))
    found = set()
    for path in paths:
        real = os.path.realpath(path)
        if any(real == root or real.startswith(root + os.sep) for root in governor.SYSTEM_DIRS):
            continue
        if real in ("/", "/tmp", "/var/tmp") or home == real or home.startswith(real + os.sep):
            continue
        if os.path.isdir(real) and _trusted_dir(real):
            found.add(real)
    return sorted(found)


def _workspace(scratch, label):
    """A fresh private directory for one run: the only writable path inside the sandbox."""
    work = pathlib.Path(tempfile.mkdtemp(prefix=f"{label}-", dir=scratch))
    for name in ("home", "tmp"):
        (work / name).mkdir(mode=0o700)
    return work


def _git_metadata(root):
    """A linked worktree's .git is a pointer: its git directory and the common one must be
    readable for read-only git commands inside the sandbox (never writable)."""
    pointer = pathlib.Path(root) / ".git"
    try:
        if not pointer.is_file() or pointer.is_symlink():
            return []
        text = pointer.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return []
    if not text.startswith("gitdir:"):
        return []
    gitdir = (pathlib.Path(root) / text[len("gitdir:"):].strip()).resolve()
    found = [gitdir]
    try:
        common = (gitdir / "commondir").read_text(encoding="utf-8").strip()
        found.append((gitdir / common).resolve())
    except OSError:
        pass
    return [str(path) for path in found if path.is_dir()]


def _scrubbed_env(work):
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(work / "home"), "TMPDIR": str(work / "tmp"),
            "LANG": "C.UTF-8"}


def _tree_digest(root, relative):
    """SHA-256 over every file below root/relative (repository-relative path and bytes, sorted), or None when the
    directory is missing, is reached through a link or holds anything but directories and regular files. Untracked
    files count (a planted __pycache__ entry changes the digest)."""
    if not _rel_ok(relative):
        return None
    base = pathlib.Path(root)
    for part in relative.split("/"):
        base = base / part
        if base.is_symlink():
            return None
    if not base.is_dir():
        return None
    rows = []
    for directory, folders, files in os.walk(base, followlinks=False):
        folders.sort()
        for name in sorted(folders + files):
            path = pathlib.Path(directory) / name
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                return None
            rows.append(f"{path.relative_to(root).as_posix()}\0{sha256(path.read_bytes())}")
    return sha256("\n".join(rows).encode("utf-8"))


def exception_digests(root=ROOT):
    """The digests PROCESS_ONLY_TESTS would need to match the files in `root` now: {test: {"sha256", "executes"}}.
    Review the change first; copying these values is what re-approves a file to run outside the sandbox."""
    root = pathlib.Path(root).resolve()
    return {test: {"sha256": _hash_file(root, test),
                   "executes": {tree: _tree_digest(root, tree) for tree in sorted((entry.get("executes") or {})
                                                                                  if isinstance(entry, dict) else {})}}
            for test, entry in sorted(PROCESS_ONLY_TESTS.items())}


def _exception(root, test):
    """The exception record of one listed test, measured now: reviewed and current digests and whether all match.
    None for a test that is not listed. A malformed entry never matches."""
    entry = PROCESS_ONLY_TESTS.get(test)
    if entry is None:
        return None
    entry = entry if isinstance(entry, dict) else {}
    reviewed, reason, trees = entry.get("sha256"), entry.get("reason"), entry.get("executes")
    current = _hash_file(root, test)
    record = {"reviewed_sha256": reviewed if isinstance(reviewed, str) else None, "sha256": current, "changed": [],
              "reason": reason if isinstance(reason, str) and reason.strip() else None}
    if not (isinstance(reviewed, str) and _SHA256.match(reviewed) and current == reviewed):
        record["changed"].append(test)
    if not isinstance(trees, dict):
        record["changed"].append("executes")
        trees = {}
    for tree, digest in sorted(trees.items()):
        if not (isinstance(digest, str) and _SHA256.match(digest) and _tree_digest(root, tree) == digest):
            record["changed"].append(tree)
    record["matched"] = not record["changed"] and record["reason"] is not None
    return record


def _profile(root, test):
    """(profile, reason, exception) for one test file: a reviewed exception whose bytes still match, a loopback test,
    or strict. A listed test whose file or executed fixture changed since its review runs strict."""
    exception = _exception(root, test)
    if exception is None:
        return ("loopback" if test in LOOPBACK_TESTS else "strict"), None, None
    if exception["matched"]:
        return "process-only", exception["reason"], exception
    return "strict", ("on the process-only exception list, but " + ", ".join(exception["changed"]) + " differs from "
                      "its review: runs strict until reviewed again"), exception


def _run(argv, *, root, timeout, workspace, profile="strict", reason=None, read=()):
    """Run argv with an exact minimal environment; kill everything it started on timeout.

    profile "strict"/"loopback" runs it in the governor sandbox (cwd = workspace, the only
    writable path; root and `read` read-only). Where the full tier is missing it runs as a
    plain subprocess instead and the returned isolation says so. Returns
    (returncode, output, elapsed_ms, timed_out, isolation)."""
    started = time.monotonic()
    work = pathlib.Path(workspace)
    env = _scrubbed_env(work)
    tier = governor.isolation_probe()["tier"]
    if profile != "process-only" and tier != "full":
        profile, reason = "process-only", f"governor full sandbox unavailable on this host (tier {tier})"
    if profile == "process-only":
        # the host's temp directory, as before: a test may drop to another uid (the swarm cage
        # chowns its workspace to 65534), which cannot traverse the private per-run directory
        env["TMPDIR"] = tempfile.gettempdir()
        process = subprocess.Popen(argv, cwd=root, env=env, stdin=subprocess.DEVNULL,
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
        try:
            os.killpg(process.pid, signal.SIGKILL)  # nothing it started in its group outlives the run
        except (ProcessLookupError, PermissionError):
            pass
        elapsed = int((time.monotonic() - started) * 1000)
        isolation = {"profile": "process-only", "sandboxed": False, "tier": tier, "environment": "scrubbed",
                     "reason": reason}
        return process.returncode, output.decode("utf-8", "replace"), elapsed, timed_out, isolation
    # env -i: exactly `env`; -C: the repository root is the working directory, as for
    # `python3 -m unittest discover` (the sandbox's own cwd must be the writable workspace)
    command = [shutil.which("env", path="/usr/bin:/bin") or "/usr/bin/env", "-i", "-C", str(root),
               *(f"{name}={value}" for name, value in sorted(env.items())), *argv]
    # No whole install prefix (recheck-isolation-2 item 4): the governor mounts the hub's interpreter itself
    # (in strict runs only its bin directory, standard library and linked libraries); a tool the tests start
    # by name contributes its bin directory only, and a virtual environment (the launcher _python names) its
    # own tree; each only from a place no non-root user can change and outside every home directory.
    tools = [os.path.dirname(os.path.realpath(found)) for found in map(shutil.which, TOOLS) if found]
    venv = [sys.prefix] if sys.prefix != sys.base_prefix else []
    readable = sorted({str(root), *_outside_system([*venv, *read, *tools]), *_git_metadata(root)})
    if profile == "strict":  # the linker's index and the alternatives links (no secret), for tools such as ffmpeg
        readable += [path for path in ETC_VISIBLE if os.path.exists(path)]

    isolation = {"profile": profile, "sandboxed": True, "tier": tier, "environment": "scrubbed", "reason": reason}
    try:
        run = governor.sandbox_run(command, cwd=str(work), timeout=timeout, allowed_paths=[str(work)], read_paths=readable,
                                   require_fs_isolation=profile == "strict", loopback=profile == "loopback",
                                   memory_mb=SANDBOX_MEMORY_MB, file_mb=SANDBOX_FILE_MB, nofile=SANDBOX_NOFILE)
    except governor.GovernorDenied as exc:  # nothing ran: reported as an error, never as a pass
        elapsed = int((time.monotonic() - started) * 1000)
        isolation.update(sandboxed=False, refused=exc.reason)
        return None, f"governor sandbox refused the run: {exc.reason}", elapsed, False, isolation
    elapsed = int((time.monotonic() - started) * 1000)
    if run["fs_isolated"] is not True or run["network_isolated"] is not True:
        isolation.update(sandboxed=False, refused="isolation-not-established")
        return None, "governor sandbox did not establish isolation", elapsed, False, isolation
    isolation["limit"] = run["limit"]
    return run["returncode"], run["stdout"] + run["stderr"], elapsed, run["limit"] == "timeout", isolation


def probe_interfaces(refs, *, root=ROOT, scratch, timeout=120):
    """Resolve 'module:callable' references in a fresh interpreter; report each and the in-tree files imported."""
    root = pathlib.Path(root).resolve()
    work = _workspace(scratch, "probe")
    out = work / f"probe-{sha256(list(refs))[:16]}.json"
    code, output, _, timed_out, isolation = _run([_python(), "-c", _PROBE, str(root), str(out), json.dumps(list(refs))],
                                                 root=root, timeout=timeout, workspace=work)
    if timed_out or not out.is_file() or out.is_symlink():
        reason = "timeout" if timed_out else f"probe exited {code}: {output[-300:]}"
        return {"interfaces": [{"ref": ref, "ok": False, "file": None, "error": reason} for ref in refs], "files": [],
                "isolation": isolation}
    doc = json.loads(out.read_text(encoding="utf-8"))
    doc["isolation"] = isolation
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
            expected_failures=0, duration_ms=0, returncode=None, output="", isolation=None):
    row = {"path": path, "runner": runner, "status": status, "ran": ran, "passed": passed, "failed": failed,
           "errors": errors, "skipped": skipped, "expected_failures": expected_failures,
           "duration_ms": duration_ms, "returncode": returncode, "reason": reason, "isolation": isolation}
    row["output_tail"] = output[-OUTPUT_TAIL:] if status in {"failed", "error"} else ""
    return row


def _run_python_test(root, test, scratch, timeout):
    work = _workspace(scratch, "test")
    out = work / f"test-{sha256(test)[:16]}.json"
    name = test[len("tests/"):-len(".py")]
    profile, why, exception = _profile(root, test)
    pinned = profile == "process-only" and exception is not None
    argv = ([_python(), "-I", "-c", _PINNED_UNITTEST, str(root), str(out), name, exception["reviewed_sha256"]] if pinned
            else [_python(), "-c", _UNITTEST, str(root), str(out), name])
    code, output, elapsed, timed_out, isolation = _run(argv, root=root, timeout=timeout, workspace=work, profile=profile,
                                                       reason=why)
    if exception is not None:
        isolation["exception"] = {key: exception[key] for key in ("reviewed_sha256", "sha256", "matched", "changed")}
        after = _exception(root, test) if pinned else None
        if after is not None and not after["matched"]:  # swapped while it ran outside the sandbox: never a pass
            isolation["exception"]["changed_during_run"] = after["changed"]
            return _result(test, "python-unittest", "error", duration_ms=elapsed, returncode=code, output=output,
                           isolation=isolation, reason="process-only exception input changed during the run: "
                           + ", ".join(after["changed"])), []
    if timed_out:
        return _result(test, "python-unittest", "error", reason=f"timeout after {timeout}s", duration_ms=elapsed,
                       returncode=code, output=output, isolation=isolation), []
    if not out.is_file() or out.is_symlink():
        return _result(test, "python-unittest", "error", reason=f"runner exited {code} without a result",
                       duration_ms=elapsed, returncode=code, output=output, isolation=isolation), []
    doc = json.loads(out.read_text(encoding="utf-8"))
    files = sorted({rel for rel in (_relative(root, name) for name in doc["files"]) if rel})
    bad = doc["failures"] + doc["errors"] + doc["unexpected_successes"]
    counted = dict(ran=doc["ran"], passed=doc["ran"] - bad - doc["skipped"], failed=doc["failures"] + doc["unexpected_successes"],
                   errors=doc["errors"], skipped=doc["skipped"], expected_failures=doc["expected_failures"],
                   duration_ms=elapsed, returncode=code, output=output, isolation=isolation)
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
    real = os.path.realpath(node)
    profile, why, exception = _profile(root, test)
    if exception is not None:  # exceptions are Python files run from their reviewed bytes; a listed .mjs runs strict
        profile, why = "strict", "process-only exceptions apply to Python test files only"
    code, output, elapsed, timed_out, isolation = _run(
        [real, "--test", "--test-reporter=tap", str(pathlib.Path(root) / test)], root=root, timeout=timeout,
        workspace=_workspace(scratch, "node"), profile=profile, reason=why, read=[os.path.dirname(real)])
    tests, passed, failed = _tap(output, "tests"), _tap(output, "pass"), _tap(output, "fail")
    skipped, cancelled = _tap(output, "skipped") + _tap(output, "todo"), _tap(output, "cancelled")
    counted = dict(ran=tests, passed=passed, failed=failed + cancelled, skipped=skipped, duration_ms=elapsed,
                   returncode=code, output=output, isolation=isolation)
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
                               environment, int((time.monotonic() - started) * 1000),
                               execution=_execution([probe.get("isolation")] + [row.get("isolation") for row, _ in runs]))
            try:
                _atomic_write(state / f"{record['id']}.json", receipt)
            except (CoordinationError, OSError) as exc:
                raise LayerError(f"{record['id']}: receipt not written ({exc})") from None
            summaries.append(_summary(record, receipt, status, reasons))
    return {"ok": all(row["status"] == "VERIFIED" for row in summaries), "node": node_version,
            "state_dir": str(state), "layers": summaries}


def _execution(isolations):
    """How the probe and the tests of one receipt actually ran (profile counts, exceptions, tier)."""
    ran = [row for row in isolations if row]
    profiles = {}
    for row in ran:
        profiles[row["profile"]] = profiles.get(row["profile"], 0) + 1
    sandboxed = bool(ran) and all(row["sandboxed"] for row in ran)
    return {"mode": "governor-sandbox" if sandboxed else "subprocess" if not any(r["sandboxed"] for r in ran) else "mixed",
            "sandboxed": sandboxed, "simulated": False, "model_calls": 0, "environment": "scrubbed",
            "tier": governor.isolation_probe()["tier"], "profiles": dict(sorted(profiles.items())),
            "process_only": sorted({row["reason"] for row in ran if row["profile"] == "process-only" and row["reason"]}),
            "refused": sorted({row["refused"] for row in ran if row.get("refused")})}


def _receipt(record, status, reasons, interfaces, tests, sources, environment, duration_ms, execution=None):
    at = _now()
    source_digest = sha256(sources)
    body = {
        "schema_version": 1, "kind": RECEIPT_KIND, "layer": record["id"], "name": record["name"],
        "status": status, "reasons": reasons, "record_sha256": sha256(record),
        "interfaces": interfaces, "tests": tests, "sources": sources, "source_sha256": source_digest,
        "environment": environment,
        "execution": execution or _execution([]),
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
