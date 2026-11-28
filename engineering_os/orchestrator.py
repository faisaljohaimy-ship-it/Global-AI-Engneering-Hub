"""Adaptive Agent Orchestration engine (GAIE layer L03): plan, schedule, run and review work
across up to twenty specialist agents.

It integrates the engines that already exist instead of re-implementing them:

* role registry, owned paths and least-privilege grant templates: `layers.load_roles` and
  `layers.instantiate_grant` (governance/agent-roles.json), validated by `contracts.validate_grant`
  and enforceable by `governor.check`;
* hierarchical decomposition and dependency analysis: `reasoning.decompose` and
  `reasoning.analyze_dependencies` (sealed, deterministic receipts);
* wave assignment: `swarm/scheduler.py:plan` and adaptive concurrency: `economics.recommend_concurrency`
  (which wraps `swarm/phase3/adaptive.py:next_wave`), both swarm files loaded read-only by path;
* leases, handovers and independent approvals: `orchestration.TaskStore`;
* checkpoints and resume: the unified engineering memory `memory.MemoryStore`.

Public API:

    plan(goal_or_spec, *, roles=None, max_agents=20, per_role=1, frozen=(), now=None) -> plan
    schedule(plan, history, *, done=(), cpus=None) -> next wave size and the tasks in it
    lifecycle(task, *, state_dir, clock=None) -> Lifecycle (queued -> leased -> running -> submitted
                                                  -> reviewed -> merged | failed | resumed)
    review_assignment(task) -> independent reviewer and approval panel; never the implementer
    worktree_plan(plan, *, repo, base_dir, base_ref="HEAD") -> git worktree/branch commands per agent
    scenario_h(metrics, *, commits=None, cpus=4) -> Scenario H figures from measured wave metrics

Everything here is deterministic code: no model is called, no agent is started and no command is
run (`worktree_plan` only returns argv lists). Plans, schedules and simulations are not executions.
Minutes in a goal are planning estimates supplied by the caller, never measurements.
SPDX-License-Identifier: MIT
"""
import argparse
import copy
import datetime
import fnmatch
import json
import os
import pathlib
import re
import subprocess
import sys
import time

from . import agent_team, contracts
from .adapters import load_path_module
from .contracts import ContractError, SIDE_EFFECTS, side_effect_rank, validate_grant
from .economics import EconomicsError, recommend_concurrency
from .layers import TEAMS, LayerError, instantiate_grant, load_layers, load_roles, validate_roles
from .memory import MemoryError as MemoryStoreError, MemoryStore, MissingMemory
from .orchestration import CoordinationError, SLUG, TaskStore, _safe_directory, load_json
from .reasoning import ReasoningError, analyze_dependencies, decompose

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES_FILE = "governance/agent-roles.json"
ENGINES_FILE = "governance/engines.json"
PLAN_SCHEMA = "gaie.orchestration-plan/1"
EVIDENCE_KIND = "gaie.scenario-h/1"

# The three numbers come from the central agent-team policy (governance/policies/agent-team.json),
# which cites the evidence file behind each one; tests/test_agent_team.py pins them to that evidence.
_TEAM_POLICY = agent_team.load_policy(ROOT / agent_team.POLICY_FILE)
# One host session ran at most 20 agents at once (swarm/phase3/capacity.py SESSION, measured).
MAX_AGENTS = _TEAM_POLICY["session_limit"]
# Policy, not a measurement: at 11 agents on 4 shared CPUs, five agents' full-suite runs recorded fork
# EAGAIN, BlockingIOError and timeouts in load-sensitive subprocess tests (load average 8.5-29), see
# docs/evidence/gaie-20-layers/scenario-h.json host_pressure; 2 agents per CPU keeps a 4-CPU host at 8.
AGENTS_PER_CPU = _TEAM_POLICY["concurrency"]["agents_per_cpu"]
START_AGENTS = _TEAM_POLICY["concurrency"]["start"]
GRANT_TTL_SECONDS = 4 * 3600
LEASE_TTL = 900
MAX_TASKS = 128
MAX_PATHS = 32
ENGINE = "claude-code"
ORCHESTRATOR = {"id": "gaie-orchestrator", "engine": ENGINE, "role": "orchestrator"}

# The twenty GAIE roles act in the task store's coarser vocabulary (orchestration.ROLES).
STORE_ROLES = {
    "chief-engineering-architect": "architecture", "twenty-layer-architecture-engineer": "architecture",
    "control-plane-integration-engineer": "development", "engineering-reasoning-engineer": "research",
    "persistent-memory-engineer": "database", "knowledge-intelligence-integration-engineer": "research",
    "master-build-engine-engineer": "development", "master-upgrade-engine-engineer": "development",
    "nl-router-project-registry-engineer": "development", "adaptive-agent-orchestration-engineer": "devops",
    "context-token-economics-engineer": "performance", "cinematic-production-engineer": "cinematic",
    "motion-sdk-animation-engineer": "cinematic", "gpu-3d-digital-twin-engineer": "cinematic",
    "agent-isolation-security-engineer": "security", "enterprise-security-privacy-engineer": "security",
    "testing-self-healing-engineer": "testing", "independent-assurance-engineer": "testing",
    "github-integration-release-engineer": "release", "claude-code-integration-engineer": "devops",
}
# Contracts and architecture first, specialist engines in parallel, then assurance, then delivery.
TEAM_DEPENDS = {"A": (), "B": ("A",), "C": ("A",), "D": ("A",), "E": ("A",), "F": ("A",),
                "G": ("B", "C", "D", "E", "F"), "H": ("G",)}
# The task store's done state needs three distinct approvals (testing, security, release).
CAPACITIES = ("testing", "security", "release")
PANEL_CANDIDATES = {
    "testing": ("independent-assurance-engineer", "testing-self-healing-engineer"),
    "security": ("enterprise-security-privacy-engineer", "agent-isolation-security-engineer"),
    "release": ("github-integration-release-engineer", "chief-engineering-architect"),
}

STATES = ("queued", "leased", "running", "submitted", "reviewed", "merged", "failed", "resumed")
TRANSITIONS = {
    None: ("queued",),
    "queued": ("leased",),
    "leased": ("running", "submitted", "failed", "resumed"),
    "running": ("running", "submitted", "failed", "resumed"),
    "submitted": ("submitted", "reviewed", "failed"),
    "reviewed": ("merged",),
    "merged": (),
    "failed": ("resumed",),
    "resumed": ("leased",),
}

_PATH = re.compile(r"^[A-Za-z0-9_.*][A-Za-z0-9_.*@+-]*(?:/[A-Za-z0-9_.*@+-]+)*$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@^~-]{0,199}$")
_BRANCH = re.compile(r"^(?:codex|claude)/[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_LAYER = re.compile(r"^L(?:0[1-9]|1[0-9]|20)$")
_TASK_FIELDS = {"id", "title", "paths", "layers", "role", "reviewer", "depends_on", "minutes", "risk",
                "novelty", "confidence", "engines"}


class OrchestratorError(ValueError):
    """A goal, plan, schedule or lifecycle request does not satisfy the orchestration contract."""


class OwnershipConflict(OrchestratorError):
    """Two tasks, a task and a foreign role, or a task and a frozen area claim the same path."""

    def __init__(self, conflicts):
        self.conflicts = conflicts
        first = conflicts[0]
        super().__init__(f"{len(conflicts)} ownership conflict(s); first: {first['kind']} {first['detail']}")


class GrantEscalation(OrchestratorError):
    """A per-task grant would exceed its role's default grant."""


class ReviewIndependenceError(OrchestratorError):
    """A reviewer would be the implementer, or is not on the task's independent panel."""


class LifecycleError(OrchestratorError):
    """A lifecycle transition is not allowed from the task's current state."""


def _need(condition, message, error=OrchestratorError):
    if not condition:
        raise error(message)


def sha256(value):
    return contracts.sha256(value)


def _slug(value, what):
    _need(isinstance(value, str) and SLUG.fullmatch(value), f"{what}: lower-case slug up to 80 characters")
    return value


def _number(value, what, low, high, integer=False):
    ok = not isinstance(value, bool) and isinstance(value, (int, float)) and low <= value <= high
    _need(ok and (not integer or type(value) is int) and value == value, f"{what}: number from {low} to {high}")
    return value


# ---------------------------------------------------------------- paths and ownership

def _path(value, what="path"):
    _need(isinstance(value, str) and 0 < len(value) <= 256, f"{what}: 1-256 characters")
    value = value.rstrip("/")
    parts = value.split("/")
    _need(_PATH.match(value) and ".." not in parts and "." not in parts and parts[0] != ".git"
          and ".git" not in parts, f"{what}: unsafe or non-canonical path {value!r}")
    _need(not parts[0].startswith("*"), f"{what}: a pattern needs a literal first segment ({value!r})")
    return value


def _paths(values, what):
    _need(isinstance(values, (list, tuple)) and 0 < len(values) <= MAX_PATHS, f"{what}: 1-{MAX_PATHS} paths")
    result = [_path(value, what) for value in values]
    _need(len(set(result)) == len(result), f"{what}: duplicate path")
    return sorted(result)


def _static(pattern):
    index = pattern.find("*")
    return (pattern, False) if index < 0 else (pattern[:index], True)


def overlaps(first, second):
    """True when two path scopes can name the same file (conservative for patterns: fail closed).

    A plain path also stands for the directory of that name, so "a" overlaps "a/b"."""
    if first == second:
        return True
    a, a_glob = _static(first)
    b, b_glob = _static(second)
    if not a_glob and not b_glob:
        return first.startswith(second + "/") or second.startswith(first + "/")
    if not a_glob:
        return fnmatch.fnmatchcase(first, second) or first.startswith(b) or b.startswith(first + "/")
    if not b_glob:
        return fnmatch.fnmatchcase(second, first) or second.startswith(a) or a.startswith(second + "/")
    return a.startswith(b) or b.startswith(a)


def covers(pattern, path):
    """True when every file under `path` is inside `pattern` (a role's owned or granted scope)."""
    if pattern == path or fnmatch.fnmatchcase(path, pattern):
        return True
    if pattern.endswith("/*"):
        prefix = pattern[:-2]
        return "*" not in prefix and (path == prefix or path.startswith(prefix + "/"))
    return "*" not in pattern and path.startswith(pattern + "/")


def _store_scope(paths):
    """The task store refuses glob characters: a pattern becomes the directory it lives in."""
    scope = set()
    for path in paths:
        static, glob = _static(path)
        scope.add(static.rstrip("/") if glob else path)
    _need(all(scope), "task store scope: empty directory")
    return sorted(scope)


def registry_conflicts(document):
    """Pairs of different roles whose owned path patterns overlap in governance/agent-roles.json."""
    roles = document["roles"]
    found = []
    for i, first in enumerate(roles):
        for second in roles[i + 1:]:
            for a in first["owns"]:
                for b in second["owns"]:
                    if overlaps(a, b):
                        found.append({"kind": "registry-overlap", "roles": [first["id"], second["id"]],
                                      "paths": [a, b], "detail": f"{first['id']}:{a} overlaps {second['id']}:{b}"})
    return found


def detect_conflicts(tasks, *, document=None, frozen=()):
    """Every path ownership conflict among tasks (no two tasks may share any path), between a task and a
    path another role owns, and between a task and a frozen area owned by another session."""
    found = []
    for i, first in enumerate(tasks):
        for second in tasks[i + 1:]:
            for a in first["paths"]:
                for b in second["paths"]:
                    if overlaps(a, b):
                        found.append({"kind": "task-overlap", "tasks": [first["id"], second["id"]], "paths": [a, b],
                                      "detail": f"{first['id']}:{a} overlaps {second['id']}:{b}"})
    for task in tasks:
        for path in task["paths"]:
            for area in frozen:
                if overlaps(path, area):
                    found.append({"kind": "frozen", "tasks": [task["id"]], "paths": [path, area],
                                  "detail": f"{task['id']}:{path} is inside frozen area {area}"})
            if document is not None and task.get("role"):
                owners = sorted({role["id"] for role in document["roles"] if any(overlaps(own, path) for own in role["owns"])})
                foreign = [owner for owner in owners if owner != task["role"]]
                if foreign:
                    found.append({"kind": "foreign-owner", "tasks": [task["id"]], "paths": [path], "owners": owners,
                                  "detail": f"{task['id']} ({task['role']}) writes {path}, owned by {', '.join(foreign)}"})
    return found


# ---------------------------------------------------------------- registries

def _read_json(path):
    try:
        return load_json(pathlib.Path(path).read_bytes())
    except (OSError, ValueError) as error:
        raise OrchestratorError(f"cannot read {pathlib.Path(path).name}: {type(error).__name__}") from None


def _engines(root):
    document = _read_json(pathlib.Path(root) / ENGINES_FILE)
    records = document["engines"] if isinstance(document, dict) and "engines" in document else document
    try:
        contracts.validate_engines(records, check_imports=False)
    except ContractError as error:
        raise OrchestratorError(f"engines: {error}") from None
    return records


def _actions(engines):
    return {engine["id"]: {name: spec for name, spec in engine["actions"].items()} for engine in engines}


def _roles_document(roles, root):
    """(document, allowed role ids): the registry, a caller's role document, or a subset of role ids."""
    if isinstance(roles, dict):
        try:
            document = validate_roles(copy.deepcopy(roles), layers=load_layers(root), engines=_engines(root))
        except LayerError as error:
            raise OrchestratorError(f"roles: {error}") from None
        return document, [role["id"] for role in document["roles"]]
    try:
        document = load_roles(root)
    except LayerError as error:
        raise OrchestratorError(f"roles: {error}") from None
    ids = [role["id"] for role in document["roles"]]
    if roles is None:
        return document, ids
    _need(isinstance(roles, (list, tuple)) and roles, "roles: None, a role document or a non-empty list of role ids")
    unknown = [rid for rid in roles if rid not in ids]
    _need(not unknown, f"roles: unknown role(s) {unknown}")
    _need(len(set(roles)) == len(roles), "roles: duplicates")
    return document, [rid for rid in ids if rid in set(roles)]


def _by_id(document):
    return {role["id"]: role for role in document["roles"]}


# ---------------------------------------------------------------- goals

def _closest(team, present):
    """Nearest present prerequisite teams (skipping teams that have no role in this plan)."""
    result = []
    for before in TEAM_DEPENDS[team]:
        for item in ([before] if before in present else _closest(before, present)):
            if item not in result:
                result.append(item)
    return result


def goal_from_roles(goal_id, document, allowed):
    """One task per role: the role's owned paths, milestones per team (A -> B..F -> G -> H)."""
    _slug(goal_id, "goal")
    by_team = {}
    for role in document["roles"]:
        if role["id"] in allowed:
            by_team.setdefault(role["team"], []).append(role)
    milestones = []
    for team in TEAMS:
        if team not in by_team:
            continue
        milestones.append({"id": f"team-{team.lower()}",
                           "depends_on": [f"team-{item.lower()}" for item in _closest(team, set(by_team))],
                           "tasks": [{"id": role["id"], "title": f"{role['title']['en']}: {role['summary']}"[:200],
                                      "paths": list(role["owns"]), "layers": list(role["layers"]), "role": role["id"],
                                      "depends_on": [], "minutes": 30} for role in by_team[team]]})
    return {"goal": goal_id, "title": f"{len(allowed)}-role engineering goal", "project": goal_id,
            "milestones": milestones, "source": "roles"}


def goal_from_spec(spec):
    """A gaie.spec/1 requirement specification (layer L15) as build work in workspace/<slug>/."""
    from .requirements import SpecError, validate_spec
    try:
        validate_spec(spec)
    except SpecError as error:
        raise OrchestratorError(f"spec: {str(error)[:300]}") from None
    slug = _slug(spec["slug"], "spec slug")
    base = f"workspace/{slug}"
    data = [] if not spec["entities"] else [{"id": "data-model", "title": f"Data model of {slug}",
                                              "paths": [f"{base}/app/models"], "layers": ["L16"],
                                              "role": "master-build-engine-engineer", "depends_on": [], "minutes": 30}]
    features = []
    for feature in spec["features"]:
        fid = _slug(f"feature-{feature['id'].lower()}", "feature id")
        features.append({"id": fid, "title": f"Feature {feature['id']}: {feature['title']['en']}"[:200],
                         "paths": [f"{base}/app/features/{feature['id'].lower()}"], "layers": ["L16"],
                         "role": "master-build-engine-engineer", "depends_on": [row["id"] for row in data],
                         "minutes": 30})
    return {"goal": slug, "title": spec["title"]["en"][:200], "project": slug, "source": "spec", "milestones": [
        {"id": "design", "depends_on": [], "tasks": [
            {"id": "architecture", "title": f"Architecture of {slug}", "paths": [f"{base}/docs/ARCHITECTURE.md"],
             "layers": ["L01"], "role": "chief-engineering-architect", "depends_on": [], "minutes": 30}]},
        {"id": "build", "depends_on": ["design"], "tasks": data + features},
        {"id": "verify", "depends_on": ["build"], "tasks": [
            {"id": "tests", "title": f"Tests of {slug}", "paths": [f"{base}/tests"], "layers": ["L17"],
             "role": "testing-self-healing-engineer", "depends_on": [], "minutes": 30},
            {"id": "security-review", "title": f"Security review of {slug}", "paths": [f"{base}/docs/SECURITY.md"],
             "layers": ["L09"], "role": "enterprise-security-privacy-engineer", "depends_on": [], "minutes": 30}]},
        {"id": "deliver", "depends_on": ["verify"], "tasks": [
            {"id": "release", "title": f"Release notes of {slug}", "paths": [f"{base}/docs/RELEASE.md"],
             "layers": ["L11"], "role": "github-integration-release-engineer", "depends_on": [], "minutes": 30}]}]}


def _normal_task(row, milestone):
    _need(isinstance(row, dict) and {"id", "paths"} <= set(row) and set(row) <= _TASK_FIELDS,
          f"task: needs id and paths; optional {sorted(_TASK_FIELDS - {'id', 'paths'})}")
    tid = _slug(row["id"], "task id")
    title = row.get("title", tid)
    _need(isinstance(title, str) and title.strip() and len(title) <= 200 and title.isprintable(), f"{tid}: title")
    layers = row.get("layers", [])
    _need(isinstance(layers, list) and all(isinstance(x, str) and _LAYER.match(x) for x in layers)
          and len(set(layers)) == len(layers), f"{tid}: layers are unique L01-L20 ids")
    depends = row.get("depends_on", [])
    _need(isinstance(depends, list) and len(set(depends)) == len(depends), f"{tid}: depends_on list")
    task = {"id": tid, "title": title, "milestone": milestone, "paths": _paths(row["paths"], f"{tid}.paths"),
            "layers": sorted(layers), "declared_depends_on": sorted(_slug(d, f"{tid}.depends_on") for d in depends),
            "minutes": _number(row.get("minutes", 30), f"{tid}.minutes", 1, 100000, integer=True),
            "risk": _number(row.get("risk", 0.3), f"{tid}.risk", 0, 1),
            "novelty": _number(row.get("novelty", 0.3), f"{tid}.novelty", 0, 1),
            "confidence": _number(row.get("confidence", 0.7), f"{tid}.confidence", 0, 1)}
    for key in ("role", "reviewer"):
        if row.get(key) is not None:
            task[key] = _slug(row[key], f"{tid}.{key}")
    if row.get("engines") is not None:
        engines = row["engines"]
        _need(isinstance(engines, dict) and engines and all(
            isinstance(k, str) and isinstance(v, list) and v and all(isinstance(a, str) for a in v) and len(set(v)) == len(v)
            for k, v in engines.items()), f"{tid}.engines: {{engine: [actions]}}")
        task["engines"] = {k: sorted(v) for k, v in sorted(engines.items())}
    return task


def _goal(value, document, allowed):
    if isinstance(value, str):
        return goal_from_roles(value, document, allowed)
    _need(isinstance(value, dict), "goal_or_spec: a goal id, a goal object or a gaie.spec/1 document")
    if value.get("schema") == "gaie.spec/1":
        return goal_from_spec(value)
    allowed_keys = {"goal", "title", "project", "milestones", "tasks", "source"}
    _need("goal" in value and set(value) <= allowed_keys and (("milestones" in value) != ("tasks" in value)),
          "goal: needs goal and exactly one of milestones or tasks")
    goal = dict(value)
    if "tasks" in goal:
        goal["milestones"] = [{"id": "main", "depends_on": [], "tasks": goal.pop("tasks")}]
    goal.setdefault("source", "goal")
    return goal


def _assign(task, document, allowed):
    """Role by declaration, by owned paths (a role owning every path) or by layers (largest overlap)."""
    by_id = _by_id(document)
    if task.get("role"):
        _need(task["role"] in allowed, f"{task['id']}: role {task['role']} is not in this plan's roles")
        return task["role"], {"rule": "declared", "detail": "role named by the goal"}
    owners = [rid for rid in allowed if all(any(covers(own, path) for own in by_id[rid]["owns"]) for path in task["paths"])]
    if len(owners) == 1:
        return owners[0], {"rule": "owned-paths", "detail": f"{owners[0]} owns every path of the task"}
    if len(owners) > 1:
        raise OwnershipConflict([{"kind": "ambiguous-owner", "tasks": [task["id"]], "paths": task["paths"],
                                  "owners": owners, "detail": f"{task['id']} paths are owned by {', '.join(owners)}"}])
    scored = [(len(set(task["layers"]) & set(by_id[rid]["layers"])), -index, rid) for index, rid in enumerate(allowed)]
    best = max(scored)
    _need(best[0] > 0, f"{task['id']}: no role owns its paths or shares its layers; name a role", OrchestratorError)
    return best[2], {"rule": "layers", "detail": f"{best[2]} shares {best[0]} of the task's layers"}


# ---------------------------------------------------------------- grants

def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _instant(now):
    utc = datetime.timezone.utc
    if now is None:
        moment = datetime.datetime.now(utc)
    elif isinstance(now, datetime.datetime):
        _need(now.tzinfo is not None, "now: timezone-aware datetime")
        moment = now.astimezone(utc)
    elif isinstance(now, str):
        try:
            moment = datetime.datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=utc)
        except ValueError:
            raise OrchestratorError("now: YYYY-MM-DDTHH:MM:SSZ") from None
    elif not isinstance(now, bool) and isinstance(now, (int, float)) and 0 <= now < 10**11:
        moment = datetime.datetime.fromtimestamp(now, utc)
    else:
        raise OrchestratorError("now: datetime, ISO-8601 UTC text or epoch seconds")
    return moment.replace(microsecond=0)


def grant_within_default(grant, role):
    """Raise GrantEscalation unless the grant is a subset of the role's default grant template."""
    template = role["default_grant"]
    try:
        validate_grant(grant)
    except ContractError as error:
        raise GrantEscalation(f"{role['id']}: invalid grant ({error})") from None
    _need(grant["role"] == role["id"], f"grant is for {grant['role']}, not {role['id']}", GrantEscalation)
    for engine, granted in grant["engines"].items():
        _need(engine in template["engines"], f"{role['id']}: engine {engine} is not in the role default", GrantEscalation)
        extra = sorted(set(granted) - set(template["engines"][engine]))
        _need(not extra, f"{role['id']}: {engine} actions {extra} are not in the role default", GrantEscalation)
    _need(side_effect_rank(grant["max_side_effect"]) <= side_effect_rank(template["max_side_effect"]),
          f"{role['id']}: {grant['max_side_effect']} exceeds the default {template['max_side_effect']}", GrantEscalation)
    for path in grant["paths"]:
        _need(any(covers(own, path) for own in template["paths"]),
              f"{role['id']}: path {path} is outside the default grant paths", GrantEscalation)
    _need(grant["approvals"] == [], f"{role['id']}: default grants never carry approvals", GrantEscalation)
    return True


def task_grant(role, task, actions, grant_id, expires_at):
    """Least privilege for one task: the actions it needs (default: the role's), only the task paths the
    role may write, and the lowest side-effect class that covers them. Never wider than the role default."""
    base = instantiate_grant(role, grant_id, expires_at)
    requested = task.get("engines")
    notes = []
    if requested is None:
        engines = {engine: sorted(granted) for engine, granted in base["engines"].items()}
    else:
        for engine, granted in requested.items():
            _need(engine in base["engines"], f"{task['id']}: engine {engine} is not in {role['id']}'s default grant",
                  GrantEscalation)
            extra = sorted(set(granted) - set(base["engines"][engine]))
            _need(not extra, f"{task['id']}: {engine} actions {extra} exceed {role['id']}'s default grant", GrantEscalation)
        engines = copy.deepcopy(requested)
    writable = [path for path in task["paths"] if any(covers(own, path) for own in base["paths"])]
    write_rank = side_effect_rank("workspace-write")
    kept = {}
    for engine, granted in sorted(engines.items()):
        for action in granted:
            _need(engine in actions and action in actions[engine], f"{task['id']}: {engine}.{action} is not registered")
            if side_effect_rank(actions[engine][action]["side_effect"]) >= write_rank and not writable:
                _need(requested is None, f"{task['id']}: {engine}.{action} writes, but no task path is writable "
                                         f"under {role['id']}'s grant", GrantEscalation)
                notes.append(f"dropped {engine}.{action}: it writes and no task path is inside the role's grant paths")
                continue
            kept.setdefault(engine, []).append(action)
    effects = [side_effect_rank(actions[e][a]["side_effect"]) for e, granted in kept.items() for a in granted]
    ceiling = SIDE_EFFECTS[max(effects, default=0)]
    grant = {"grant_id": grant_id, "role": role["id"], "engines": kept,
             "paths": writable if side_effect_rank(ceiling) >= write_rank else [],
             "max_side_effect": ceiling, "expires_at": expires_at, "approvals": []}
    grant_within_default(grant, role)
    return grant, notes


# ---------------------------------------------------------------- review

def _review_document(roles, root):
    """The role document review_assignment reads. A caller's document is taken as given (plan() passes the
    one it already validated, and a subset may lack panel candidates), but its shape is checked here so a
    malformed one raises OrchestratorError, never a bare KeyError or TypeError."""
    if not (isinstance(roles, dict) and "roles" in roles):
        return _roles_document(roles, root)[0]
    rows = roles["roles"]
    _need(isinstance(rows, list) and all(isinstance(row, dict) and isinstance(row.get("id"), str)
                                         and isinstance(row.get("reviewer"), bool) for row in rows),
          "review: malformed role document: every role needs a string id and a boolean reviewer flag")
    _need(len({row["id"] for row in rows}) == len(rows), "review: malformed role document: duplicate role id")
    return roles


def review_assignment(task, *, roles=None, root=ROOT):
    """The independent reviewer and the testing/security/release approval panel for a task.

    The implementer's role is never the reviewer or on the panel; a reviewer the task asks for that is
    its own implementer is refused (ReviewIndependenceError)."""
    document = _review_document(roles, root)
    by_id = _by_id(document)
    _need(isinstance(task, dict) and isinstance(task.get("role"), str) and task["role"] in by_id,
          "review: task needs a known role")
    implementer = task["role"]
    requested = task.get("reviewer")
    if requested is not None:
        _need(isinstance(requested, str), f"{task.get('id')}: the reviewer must be a role id")
        _need(requested != implementer, f"{task.get('id')}: the reviewer {requested} is the implementer",
              ReviewIndependenceError)
        _need(requested in by_id, f"{task.get('id')}: unknown reviewer {requested}")
    panel = {}
    for capacity in CAPACITIES:
        panel[capacity] = next((rid for rid in PANEL_CANDIDATES[capacity] if rid != implementer and rid in by_id), None)
        _need(panel[capacity] is not None,
              f"{task.get('id')}: no independent {capacity} reviewer: the role document lacks every candidate "
              f"other than the implementer ({', '.join(PANEL_CANDIDATES[capacity])})", ReviewIndependenceError)
    flagged = [rid for rid in by_id if by_id[rid]["reviewer"] and rid != implementer]
    reviewer = requested or (flagged[0] if flagged else panel["testing"])
    _need(reviewer != implementer and implementer not in panel.values() and len(set(panel.values())) == len(CAPACITIES),
          f"{task.get('id')}: review panel is not independent of {implementer}", ReviewIndependenceError)
    return {"implementer": implementer, "reviewer": reviewer, "panel": panel, "independent": True,
            "rule": "reviewer flag first, else the testing capacity; never the implementer's role"}


def _reviewer_actor(role_id, capacity):
    return {"id": f"review-{role_id}"[:80], "engine": ENGINE, "role": capacity}


# ---------------------------------------------------------------- plan

def _verify_waves(tasks, waves, limit):
    order = {pair["task"]: number for number, wave in enumerate(waves) for pair in wave}
    by_id = {task["id"]: task for task in tasks}
    once = sorted(order) == sorted(by_id) and sum(len(w) for w in waves) == len(by_id)
    return {
        "every_task_once": once,
        "dependencies_first": once and all(d in order and order[d] < order[t] for t in by_id for d in by_id[t]["depends_on"]),
        "one_task_per_agent_per_wave": all(len({p["agent"] for p in w}) == len(w) for w in waves),
        "no_wave_above_limit": all(len(w) <= limit for w in waves),
    }


def plan(goal_or_spec, *, roles=None, max_agents=MAX_AGENTS, per_role=1, frozen=(), now=None, root=ROOT):
    """A hierarchical task graph (goal -> milestones -> tasks) with roles, agents, dependency waves,
    per-task least-privilege grants, independent reviewers and non-overlapping path ownership.

    Raises OwnershipConflict when any two tasks, a task and another role's owned path, or a task and a
    frozen area overlap. Deterministic for the same inputs and `now`; nothing is executed."""
    _number(max_agents, "max_agents", 1, MAX_AGENTS, integer=True)
    _number(per_role, "per_role", 1, MAX_AGENTS, integer=True)
    frozen = _paths(list(frozen), "frozen") if frozen else []
    root = pathlib.Path(root)
    document, allowed = _roles_document(roles, root)
    by_id = _by_id(document)
    goal = _goal(goal_or_spec, document, allowed)
    goal_id = _slug(goal["goal"], "goal")
    project = _slug(goal.get("project", goal_id), "project")
    title = goal.get("title", goal_id)
    _need(isinstance(title, str) and 0 < len(title) <= 200, "goal title: 1-200 characters")
    _need(isinstance(goal["milestones"], list) and 0 < len(goal["milestones"]) <= 32, "goal: 1-32 milestones")
    tasks, milestones = [], []
    for milestone in goal["milestones"]:
        _need(isinstance(milestone, dict) and set(milestone) == {"id", "depends_on", "tasks"},
              "milestone: id, depends_on, tasks")
        mid = _slug(milestone["id"], "milestone id")
        _need(isinstance(milestone["tasks"], list) and milestone["tasks"], f"{mid}: tasks list")
        rows = [_normal_task(row, mid) for row in milestone["tasks"]]
        milestones.append({"id": mid, "depends_on": milestone["depends_on"], "tasks": rows})
        tasks.extend(rows)
    _need(0 < len(tasks) <= MAX_TASKS, f"goal: 1-{MAX_TASKS} tasks")
    _need(len({t["id"] for t in tasks}) == len(tasks), "goal: duplicate task id")
    for task in tasks:
        task["role"], task["assignment"] = _assign(task, document, allowed)
        task["team"] = by_id[task["role"]]["team"]
    conflicts = detect_conflicts(tasks, document=document, frozen=frozen)
    if conflicts:
        raise OwnershipConflict(conflicts)
    try:
        decomposition = decompose({"schema_version": 1, "goal": goal_id, "milestones": [
            {"id": m["id"], "depends_on": m["depends_on"], "tasks": [
                {"id": t["id"], "depends_on": t["declared_depends_on"], "minutes": t["minutes"], "risk": t["risk"],
                 "novelty": t["novelty"], "confidence": t["confidence"]} for t in m["tasks"]]} for m in milestones]})
        depends = {node["id"]: node["depends_on"] for node in decomposition["plan_nodes"]}
        analysis = analyze_dependencies({"schema_version": 1, "items": [
            {"id": t["id"], "depends_on": depends[t["id"]], "minutes": t["minutes"], "status": "todo"} for t in tasks]})
    except ReasoningError as error:
        raise OrchestratorError(f"task graph: {error}") from None
    critical = set(analysis["critical_items"])
    roster, used = [], [rid for rid in allowed if any(t["role"] == rid for t in tasks)]
    for rid in used:
        count = min(per_role, sum(1 for t in tasks if t["role"] == rid))
        roster += [{"id": rid if count == 1 else f"{rid}-{n}", "role": rid, "team": by_id[rid]["team"]}
                   for n in range(1, count + 1)]
    _need(len(roster) <= MAX_AGENTS, f"plan needs {len(roster)} agents; one host session runs at most {MAX_AGENTS}")
    scheduler = load_path_module("scheduler", "swarm/scheduler.py")
    try:
        assigned = scheduler.plan(
            [{"id": t["id"], "team": t["role"], "role": t["role"], "write": t["paths"][0],
              "fingerprint": sha256(["orchestrator-task", t["id"]]), "needs": depends[t["id"]],
              "priority": 0 if t["id"] in critical else 2} for t in tasks],
            [{"id": agent["id"], "team": agent["role"], "role": agent["role"]} for agent in roster], max_agents)
    except ValueError as error:
        raise OrchestratorError(f"wave assignment: {error}") from None
    _need(not assigned["dropped_duplicates"] and assigned["scheduled"] == len(tasks), "wave assignment lost a task")
    moment = _instant(now)
    expires = _stamp(moment + datetime.timedelta(seconds=GRANT_TTL_SECONDS))
    actions = _actions(_engines(root))
    branches = {}
    for agent in roster:
        branch = f"claude/{goal_id[:48]}-{agent['id']}"
        _need(_BRANCH.match(branch), f"branch name for {agent['id']} is not safe")
        branches[agent["id"]] = branch
    agent_of = {pair["task"]: pair["agent"] for wave in assigned["waves"] for pair in wave}
    wave_of = {pair["task"]: number for number, wave in enumerate(assigned["waves"]) for pair in wave}
    by_task = {t["id"]: t for t in tasks}
    records = []
    for number, wave in enumerate(assigned["waves"]):
        for pair in wave:
            task = by_task[pair["task"]]
            grant, notes = task_grant(by_id[task["role"]], task, actions,
                                      "g-" + sha256([goal_id, task["id"]])[:24], expires)
            record = {"id": task["id"], "title": task["title"], "milestone": task["milestone"], "role": task["role"],
                      "team": task["team"], "layers": task["layers"], "paths": task["paths"],
                      "store_paths": _store_scope(task["paths"]), "declared_depends_on": task["declared_depends_on"],
                      "depends_on": depends[task["id"]], "minutes": task["minutes"], "critical": task["id"] in critical,
                      "priority": 0 if task["id"] in critical else 2, "assignment": task["assignment"],
                      "agent": agent_of[task["id"]], "branch": branches[agent_of[task["id"]]], "wave": wave_of[task["id"]],
                      "store_role": STORE_ROLES[task["role"]], "project": project, "plan_id": goal_id,
                      "grant": grant, "grant_notes": notes}
            if task.get("reviewer"):
                record["reviewer"] = task["reviewer"]
            record["review"] = review_assignment(record, roles=document)
            records.append(record)
    waves = [[{"task": p["task"], "agent": p["agent"], "role": by_task[p["task"]]["role"]} for p in wave]
             for wave in assigned["waves"]]
    checks = _verify_waves(records, waves, max_agents)
    checks.update({"no_path_overlap": not detect_conflicts(records, document=document, frozen=frozen),
                   "reviewer_never_implementer": all(r["review"]["reviewer"] != r["role"]
                                                     and r["role"] not in r["review"]["panel"].values() for r in records),
                   "grants_within_role_defaults": all(grant_within_default(r["grant"], by_id[r["role"]]) for r in records)})
    _need(all(checks.values()), f"plan self-check failed: {sorted(k for k, v in checks.items() if not v)}")
    body = {"schema": PLAN_SCHEMA, "plan_id": goal_id, "project": project,
            "goal": {"id": goal_id, "title": title, "source": goal.get("source", "goal")},
            "created_at": _stamp(moment), "max_agents": max_agents, "per_role": per_role, "frozen": frozen,
            "hierarchy": {"goal": goal_id, "milestones": decomposition["milestones"],
                          "milestone_waves": decomposition["milestone_waves"]},
            "tasks": records, "dependency_waves": analysis["waves"], "critical_path": analysis["critical_path"],
            "critical_path_minutes": analysis["critical_path_minutes"], "waves": waves,
            "agents": [dict(agent, branch=branches[agent["id"]],
                            tasks=[r["id"] for r in records if r["agent"] == agent["id"]]) for agent in roster],
            "ownership": {path: r["id"] for r in records for path in r["paths"]},
            "checks": checks,
            "receipts": {"decompose": decomposition["receipt"], "dependencies": analysis["receipt"]},
            "sources": {"roles_sha256": sha256(document), "engines_sha256": sha256(_engines(root))},
            "basis": "deterministic plan: no agent was started, no model was called, nothing was executed",
            "provider_calls": 0}
    return dict(body, plan_sha256=sha256(body))


def _required_frozen(frozen):
    return _paths(list(frozen), "frozen") if frozen else []


def verify_plan(value, *, roles=None, frozen=(), root=ROOT):
    """Refuse a plan changed after planning (digest) or one whose invariants no longer hold.

    `frozen` names the frozen areas the verifier requires. The digest is a plain SHA-256 anyone can
    recompute, so a re-sealed plan could drop its own `frozen` list; a plan that does not cover every
    required area is refused, and its tasks are checked against both lists."""
    _need(isinstance(value, dict) and value.get("schema") == PLAN_SCHEMA and isinstance(value.get("plan_sha256"), str),
          f"plan: a {PLAN_SCHEMA} document")
    body = {key: item for key, item in value.items() if key != "plan_sha256"}
    _need(sha256(body) == value["plan_sha256"], "plan: changed after planning (digest mismatch)")
    required = _required_frozen(frozen)
    planned = value["frozen"]
    _need(isinstance(planned, list) and (not planned or _paths(planned, "plan frozen") == planned),
          "plan: frozen areas are not a canonical path list")
    dropped = [area for area in required if not any(covers(own, area) for own in planned)]
    if dropped:
        raise OwnershipConflict([{"kind": "frozen-dropped", "tasks": [], "paths": [area],
                                  "detail": f"the verifier's frozen area {area} is not frozen in the plan (dropped after planning?)"}
                                 for area in dropped])
    frozen = sorted(set(planned) | set(required))
    tasks = value["tasks"]
    overlapping = detect_conflicts(tasks, frozen=frozen)
    if overlapping:  # task-to-task and frozen-area conflicts (an OrchestratorError, with the details)
        raise OwnershipConflict(overlapping)
    document = _roles_document(roles if isinstance(roles, dict) else None, root)[0]
    _need(sha256(document) == value["sources"]["roles_sha256"],
          "plan: made with a different role registry (pass the same roles document)")
    by_id = _by_id(document)
    # The digest is a plain SHA-256 anyone can recompute, so ownership is rechecked against the role
    # registry exactly as plan() checks it: a re-sealed plan may not write another role's path.
    conflicts = detect_conflicts(tasks, document=document, frozen=frozen)
    if conflicts:
        raise OwnershipConflict(conflicts)
    for task in tasks:
        _need(task["store_paths"] == _store_scope(task["paths"]), f"{task['id']}: task store scope differs from its paths")
        _need(task["review"] == review_assignment(task, roles=document), f"{task['id']}: review assignment changed",
              ReviewIndependenceError)
        grant_within_default(task["grant"], by_id[task["role"]])
    checks = _verify_waves(tasks, value["waves"], value["max_agents"])
    _need(all(checks.values()), f"plan: schedule invariants broken {sorted(k for k, v in checks.items() if not v)}")
    return value


# ---------------------------------------------------------------- schedule

def host_cap(cpus=None, agents_per_cpu=AGENTS_PER_CPU):
    """Concurrent agents one host may run: CPUs x agents per CPU (policy), never above the session limit."""
    cpus = (os.cpu_count() or 1) if cpus is None else cpus
    _number(cpus, "cpus", 1, 4096, integer=True)
    _number(agents_per_cpu, "agents_per_cpu", 1, 64, integer=True)
    return {"cpus": cpus, "agents_per_cpu": agents_per_cpu, "session_limit": MAX_AGENTS,
            "cap": min(MAX_AGENTS, cpus * agents_per_cpu),
            "basis": "policy: agents per CPU from host-pressure observations; the session limit was measured"}


def schedule(plan_value, history, *, done=(), cpus=None, agents_per_cpu=AGENTS_PER_CPU, tokens_left=None, roles=None,
             frozen=(), root=ROOT):
    """Size of the next wave and its tasks: economics.recommend_concurrency over the measured waves
    (grow only when verified tasks per token improved; shrink on conflicts; stop on limit errors),
    capped by the plan's max_agents and the host cap, filled with ready tasks (one per agent).
    `frozen` names the frozen areas the caller requires (see verify_plan)."""
    plan_value = verify_plan(plan_value, roles=roles, frozen=frozen, root=root)
    _need(isinstance(history, list), "history: list of measured waves (economics wave records)")
    done = set(done)
    ids = [task["id"] for task in plan_value["tasks"]]
    _need(done <= set(ids), f"done: unknown task(s) {sorted(done - set(ids))}")
    host = host_cap(cpus, agents_per_cpu)
    remaining = [task for task in plan_value["tasks"] if task["id"] not in done]
    ready, busy = [], set()
    for task in remaining:
        if set(task["depends_on"]) <= done and task["agent"] not in busy:
            ready.append(task["id"])
            busy.add(task["agent"])
    cap = min(plan_value["max_agents"], host["cap"])
    limits = {"start": min(START_AGENTS, cap), "max_agents": cap, "max_batch": 1, "tasks_left": len(remaining)}
    if tokens_left is not None:
        limits["tokens_left"] = tokens_left
    try:
        decision = recommend_concurrency(copy.deepcopy(history), limits)
    except EconomicsError as error:
        raise OrchestratorError(f"history: {error}") from None
    size = min(decision["agents"], len(ready))
    return {"agents": size, "recommended_agents": decision["agents"], "wave": ready[:size], "ready": len(ready),
            "remaining": len(remaining), "complete": not remaining, "stop": decision["stop"] or not remaining,
            "rule": decision["rule"], "reason": decision["reason"], "host": host, "limits": limits,
            "decision": decision, "plan_sha256": plan_value["plan_sha256"],
            "basis": "measured waves and deterministic rules; nothing executed"}


# ---------------------------------------------------------------- lifecycle

def _receipt_list(receipts):
    _need(isinstance(receipts, list) and 0 < len(receipts) <= 50 and all(
        isinstance(row, dict) and set(row) == {"kind", "sha256"} and isinstance(row["kind"], str)
        and SLUG.fullmatch(row["kind"]) and isinstance(row["sha256"], str) and _DIGEST.match(row["sha256"])
        for row in receipts), "receipts: 1-50 {kind, sha256} digests (never payloads)")
    return [dict(row) for row in receipts]


class Lifecycle:
    """One plan task through queued -> leased -> running -> submitted -> reviewed -> merged | failed | resumed.

    Ownership, leases and approvals live in the hash-chained TaskStore (state_dir/tasks); work-step
    checkpoints and lifecycle notes live in engineering memory (state_dir/memory/<project>), so a fresh
    process resumes from the last checkpoint. Both directories are private and outside Git."""

    def __init__(self, task, state_dir, *, clock=None, roles=None, frozen=(), root=ROOT):
        document = _roles_document(roles, root)[0]
        by_id = _by_id(document)
        required = {"id", "title", "role", "paths", "agent", "branch", "store_paths", "store_role", "project", "priority",
                    "grant", "review"}
        _need(isinstance(task, dict) and required <= set(task) and task["role"] in by_id, "lifecycle: a plan task")
        # A task can reach here without verify_plan (the documented lifecycle() API), so its scope is
        # rechecked exactly as plan() checks it: canonical paths, the store scope derived from them, no
        # path another role owns in the role registry and none inside a frozen area the caller names.
        _need(isinstance(task["paths"], list) and _paths(task["paths"], f"{task['id']}: paths") == task["paths"],
              f"{task['id']}: paths are not the planned canonical list")
        _need(task["store_paths"] == _store_scope(task["paths"]), f"{task['id']}: task store scope differs from its paths")
        conflicts = detect_conflicts([task], document=document, frozen=_required_frozen(frozen))
        if conflicts:
            raise OwnershipConflict(conflicts)
        _need(task["review"] == review_assignment(task, roles=document), f"{task['id']}: review assignment changed",
              ReviewIndependenceError)
        grant_within_default(task["grant"], by_id[task["role"]])
        _need(task["store_role"] == STORE_ROLES[task["role"]], f"{task['id']}: store role changed")
        self.task = copy.deepcopy(task)
        self.clock = clock or time.time
        try:
            directory = _safe_directory(pathlib.Path(state_dir))
            self.store = TaskStore(directory / "tasks", clock=self.clock)
        except CoordinationError as error:
            raise LifecycleError(f"task store: {error}") from None
        self.memory_root = directory / "memory"
        self.implementer = {"id": task["agent"], "engine": ENGINE, "role": task["store_role"]}

    # -- reading ------------------------------------------------------------

    def _memory(self, create=True):
        return MemoryStore.for_project(self.memory_root, self.task["project"], create=create)

    def _row(self):
        snapshot = self.store.snapshot()
        events = [event for event in snapshot["events"] if event["task"] == self.task["id"]]
        return snapshot["tasks"].get(self.task["id"]), events

    def _tag(self):
        tag = f"task-{self.task['id']}"
        return tag if len(tag) <= 80 else "task-" + sha256(self.task["id"])[:32]

    def _merged(self):
        try:
            rows = self._memory(create=False).entries(self.task["project"])
        except MissingMemory:
            return False
        return any(row["record"]["kind"] == "checkpoint" and {"lifecycle-merged", self._tag()} <= set(row["record"]["tags"])
                   for row in rows)

    def state(self):
        """The lifecycle state derived from the task store and memory; None before enqueue."""
        row, events = self._row()
        if row is None:
            return None
        status = row["status"]
        if status == "pending":
            return "resumed" if any(event["operation"] == "recover" for event in events) else "queued"
        if status == "handover":
            return "resumed"
        if status == "active":
            return "leased" if events[-1]["operation"] == "claim" else "running"
        if status == "review":
            return "submitted"
        if status == "done":
            return "merged" if self._merged() else "reviewed"
        return "failed"  # failed, or blocked by a rejected review

    def progress(self):
        """Work steps from the last memory checkpoint: what a resumed agent must not redo."""
        try:
            rows = self._memory(create=False).next_steps(self.task["project"], self.task["id"])
        except (MissingMemory, MemoryStoreError):
            return {"done": [], "remaining": [], "next": None, "version": 0}
        row = rows[0]
        return {"done": row["done"], "remaining": row["remaining"], "next": row["next"], "version": row["version"]}

    def status(self):
        row, events = self._row()
        lease = row["lease"] if row else None
        return {"task": self.task["id"], "state": self.state(), "store_status": row["status"] if row else None,
                "version": row["version"] if row else 0, "owner": row["owner"]["id"] if row and row["owner"] else None,
                "lease_expired": None if not lease else lease["expires_at"] <= self.clock(),
                "failures": row["failures"] if row else 0,
                "approvals": {} if not row else {k: v["decision"] for k, v in sorted(row["approvals"].items())},
                "progress": self.progress(), "events": len(events), "audit_verified": True,
                "agent": self.task["agent"], "branch": self.task["branch"]}

    # -- transitions --------------------------------------------------------

    def _expect(self, *allowed):
        current = self.state()
        if current not in allowed:
            raise LifecycleError(f"{self.task['id']}: {current or 'not queued'} cannot do this; needs {' or '.join(map(str, allowed))}")
        return current

    def _call(self, method, *args, **kwargs):
        row, _ = self._row()
        try:
            return method(self.task["id"], *args[:1], row["version"], *args[1:], **kwargs)
        except CoordinationError as error:
            raise LifecycleError(f"{self.task['id']}: {error}") from None

    def _note(self, state, receipts=()):
        """A memory checkpoint bound to the task store's latest audit event for this task."""
        _, events = self._row()
        event = events[-1]
        summary = (f"lifecycle {state}; store event {event['sequence']} sha256 {event['sha256']}; "
                   + "; ".join(f"{row['kind']} {row['sha256']}" for row in receipts))
        try:
            self._memory().put({"project": self.task["project"], "kind": "checkpoint",
                                "title": f"{self.task['id']}: {state}"[:200], "summary": summary.rstrip("; "),
                                "tags": sorted({"orchestrator", f"lifecycle-{state}", self._tag()}), "symbols": [],
                                "links": [], "provenance": {"engine": ENGINE, "source_sha256": event["sha256"]}})
        except MemoryStoreError as error:
            raise LifecycleError(f"memory checkpoint: {error}") from None
        return state

    def enqueue(self):
        row, _ = self._row()
        if row is not None:
            _need(row["paths"] == self.task["store_paths"] and row["branch"] == self.task["branch"],
                  f"{self.task['id']}: a different task with this id is already queued", LifecycleError)
            return {"state": self.state(), "created": False}
        spec = {"id": self.task["id"], "project": self.task["project"], "branch": self.task["branch"],
                "paths": self.task["store_paths"], "title": self.task["title"], "priority": self.task["priority"],
                "role": self.task["store_role"], "engine": ENGINE}
        try:
            self.store.create_task(spec, ORCHESTRATOR, self.store.snapshot()["revision"])
        except CoordinationError as error:
            raise LifecycleError(f"{self.task['id']}: {error}") from None
        return {"state": self._note("queued"), "created": True}

    def lease(self, ttl=LEASE_TTL):
        self._expect("queued", "resumed")
        row = self._call(self.store.claim, self.implementer, ttl=ttl)
        return {"state": self._note("leased"), "lease_id": row["lease"]["id"], "expires_at": row["lease"]["expires_at"],
                "grant": copy.deepcopy(self.task["grant"]), "branch": self.task["branch"], "progress": self.progress()}

    def start(self, lease_id, ttl=LEASE_TTL):
        self._expect("leased", "running")
        self._call(self.store.renew, self.implementer, lease_id, ttl=ttl)
        return {"state": self._note("running")}

    def checkpoint(self, lease_id, done, remaining, ttl=LEASE_TTL):
        """Renew the lease and record the work steps done and remaining in engineering memory."""
        self._expect("leased", "running")
        self._call(self.store.renew, self.implementer, lease_id, ttl=ttl)
        try:
            saved = self._memory().task_progress(self.task["project"], self.task["id"], self.task["title"], list(done),
                                                 list(remaining), status="done" if not remaining else "in-progress")
        except MemoryStoreError as error:
            raise LifecycleError(f"memory checkpoint: {error}") from None
        return {"state": self._note("running"), "checkpoint": saved["id"], "version": saved["version"],
                "next": saved["next"]}

    def submit(self, lease_id, receipts):
        receipts = _receipt_list(receipts)
        self._expect("leased", "running")
        self._call(self.store.submit, self.implementer, lease_id, receipts)
        return {"state": self._note("submitted", receipts)}

    def review(self, reviewer_role, decision, receipts):
        """One panel approval or rejection; the implementer's role and roles off the panel are refused."""
        receipts = _receipt_list(receipts)
        panel = self.task["review"]["panel"]
        _need(reviewer_role != self.task["role"], f"{self.task['id']}: {reviewer_role} implemented this task",
              ReviewIndependenceError)
        capacity = next((cap for cap, rid in panel.items() if rid == reviewer_role), None)
        _need(capacity is not None, f"{self.task['id']}: {reviewer_role} is not on the review panel {sorted(panel.values())}",
              ReviewIndependenceError)
        self._expect("submitted")
        row, _ = self._row()
        try:
            self.store.review(self.task["id"], _reviewer_actor(reviewer_role, capacity), row["version"], decision, receipts)
        except CoordinationError as error:
            raise LifecycleError(f"{self.task['id']}: {error}") from None
        return {"state": self._note(self.state(), receipts), "capacity": capacity,
                "decision": decision}

    def merge(self, receipts):
        """Record the integrator's merge (a commit digest) once every panel approval is in."""
        receipts = _receipt_list(receipts)
        self._expect("reviewed")
        return {"state": self._note("merged", receipts)}

    def fail(self, lease_id, receipts):
        receipts = _receipt_list(receipts)
        self._expect("leased", "running")
        self._call(self.store.fail, self.implementer, lease_id, receipts)
        return {"state": self._note("failed", receipts)}

    def handover(self, lease_id, note, receipts):
        receipts = _receipt_list(receipts)
        self._expect("leased", "running")
        self._call(self.store.handover, self.implementer, lease_id, note, receipts)
        return {"state": self._note("resumed", receipts)}

    def resume(self, receipts=None):
        """Return failed, rejected or lease-expired work to the queue; memory keeps the steps already done."""
        state = self._expect("failed", "leased", "running")
        row, _ = self._row()
        if state in ("leased", "running"):
            _need(row["lease"]["expires_at"] <= self.clock(), f"{self.task['id']}: the lease is still live", LifecycleError)
        receipts = _receipt_list(receipts or [{"kind": "resume-checkpoint", "sha256": sha256(self.progress())}])
        self._call(self.store.recover, ORCHESTRATOR, receipts)
        return {"state": self._note("resumed", receipts), "progress": self.progress()}


def lifecycle(task, *, state_dir, clock=None, roles=None, frozen=(), root=ROOT):
    """The lifecycle of one plan task, bound to a private state directory (see Lifecycle)."""
    return Lifecycle(task, state_dir, clock=clock, roles=roles, frozen=frozen, root=root)


# ---------------------------------------------------------------- worktrees

def _inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def worktree_plan(plan_value, *, repo, base_dir, base_ref="HEAD", roles=None, frozen=(), root=ROOT):
    """git worktree and branch commands, one isolated worktree per agent, outside the repository.

    Commands only (argv lists): nothing is executed here. Hooks and fsmonitor are disabled so that
    creating a worktree never runs repository code; removal refuses dirty worktrees and unmerged branches.
    `frozen` names the frozen areas the caller requires (see verify_plan)."""
    plan_value = verify_plan(plan_value, roles=roles, frozen=frozen, root=root)
    for value, what in ((repo, "repo"), (base_dir, "base_dir")):
        _need(isinstance(value, (str, os.PathLike)) and os.path.isabs(os.fspath(value)), f"{what}: absolute path")
    repo, base = os.path.realpath(os.fspath(repo)), os.path.realpath(os.fspath(base_dir))
    _need(not _inside(base, repo), "base_dir: worktrees stay outside the repository checkout")
    _need(isinstance(base_ref, str) and _REF.match(base_ref) and ".." not in base_ref, "base_ref: a safe ref")
    git = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-C", repo]
    agents = []
    for agent in plan_value["agents"]:
        path = os.path.join(base, agent["id"])
        agents.append({"agent": agent["id"], "role": agent["role"], "branch": agent["branch"], "path": path,
                       "tasks": agent["tasks"],
                       "create": [git + ["worktree", "add", "-b", agent["branch"], path, base_ref]],
                       "remove": [git + ["worktree", "remove", path], git + ["branch", "-d", agent["branch"]]]})
    return {"repo": repo, "base_dir": base, "base_ref": base_ref, "agents": agents, "executed": False,
            "plan_sha256": plan_value["plan_sha256"],
            "note": "commands only; one worktree and branch per agent; run them yourself in order"}


# ---------------------------------------------------------------- Scenario H (measured)

def _agent_rows(metrics):
    _need(isinstance(metrics, dict) and isinstance(metrics.get("waves"), list) and metrics["waves"],
          "metrics: {waves: [...]}")
    rows, running, started = [], [], None
    for wave in metrics["waves"]:
        _need(isinstance(wave, dict) and isinstance(wave.get("agents"), list), "metrics wave: agents list")
        started = started or wave.get("started_utc")
        running += list(wave.get("still_running", []))
        for agent in wave["agents"]:
            for key in ("tokens", "tool_uses", "duration_s", "gate_reruns"):
                _number(agent.get(key), f"{agent.get('id')}.{key}", 0, 10**12)
            _need(isinstance(agent.get("merged"), bool) and isinstance(agent.get("conflicts"), list),
                  f"{agent.get('id')}: merged flag and conflicts list")
            follow = agent.get("followup") or {}
            # The metrics note says the resumed agent's subagent_tokens are cumulative: the follow-up figure
            # already includes the first run. Tool uses and durations are per run and add up.
            tokens = max(agent["tokens"], follow.get("tokens", 0))
            texts = [str(item) for item in agent["conflicts"]]
            rows.append({"id": agent["id"], "role": agent.get("role"), "merged": agent["merged"], "tokens": tokens,
                         "tokens_if_followup_additive": agent["tokens"] + follow.get("tokens", 0),
                         "tool_uses": agent["tool_uses"] + follow.get("tool_uses", 0),
                         "duration_s": agent["duration_s"], "active_s": agent["duration_s"] + follow.get("duration_s", 0),
                         "gate_reruns": agent["gate_reruns"], "conflicts": texts,
                         "integrator_fixes": sum("fixed by integrator" in text for text in texts),
                         "sent_back": sum("sent back" in text for text in texts)})
    return rows, running, started


def _conflict_kind(text):
    return "security-scan-fixture" if ("secret-scan" in text or "security scan" in text) else "cross-module-contract"


def _r(value, digits=4):
    return round(value + 0.0, digits)


def _parse_utc(text):
    for pattern in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            moment = datetime.datetime.strptime(text, pattern)
            return moment.replace(tzinfo=moment.tzinfo or datetime.timezone.utc)
        except ValueError:
            continue
    raise OrchestratorError(f"time {text!r}: ISO-8601")


_AGENT_MERGE = re.compile(r"^Merge (?:branch ')?gaie/([a-z0-9][a-z0-9-]*)'? into ")


def git_metrics(commits, started_utc):
    """Merge times and integrator commits from first-parent integration history (oldest first)."""
    _need(isinstance(commits, list) and commits, "commits: non-empty list of {commit, at, subject}")
    start = _parse_utc(started_utc)
    merges, fixes, after_main = [], [], False
    for row in commits:
        _need(isinstance(row, dict) and set(row) == {"commit", "at", "subject"}, "commit: commit, at, subject")
        minutes = (_parse_utc(row["at"]) - start).total_seconds() / 60
        match = _AGENT_MERGE.match(row["subject"])
        if match:
            merges.append({"agent": match.group(1), "commit": row["commit"], "minutes_after_start": _r(minutes, 2)})
            after_main = False
        elif row["subject"].startswith("Merge "):
            after_main = "origin/main" in row["subject"]
        else:
            fixes.append({"commit": row["commit"], "subject": row["subject"],
                          "cause": "main-moved" if after_main else "agent-output"})
    _need(merges, "commits: no agent merge found")
    last = merges[-1]["minutes_after_start"]
    rework = [fix for fix in fixes if fix["cause"] == "agent-output"]
    return {"agent_merges": len(merges), "merges": merges, "first_merge_minutes": merges[0]["minutes_after_start"],
            "last_merge_minutes": last, "merges_per_hour": _r(len(merges) / (last / 60)),
            "integrator_commits": len(fixes), "integrator_commits_detail": fixes,
            "integrator_rework_commits": len(rework), "integrator_rework_per_merge": _r(len(rework) / len(merges)),
            "definition": "first-parent commits of the integration branch: agent merges by subject; non-merge "
                          "commits are the integrator's own; those after a merge of origin/main and before the "
                          "next agent merge are attributed to main moving, the rest to agent output"}


def scenario_h(metrics, *, commits=None, cpus=4, agents_per_cpu=AGENTS_PER_CPU, source=None):
    """Throughput, tokens per merged task, conflict and rework rates, concurrency, and the next-wave size
    recommend_concurrency gives for a host with `cpus`, all computed from measured wave metrics."""
    rows, running, started = _agent_rows(metrics)
    merged = [row for row in rows if row["merged"]]
    _need(merged, "metrics: no merged agent")
    span = max(max(row["duration_s"] for row in rows), max(row["active_s"] for row in rows))
    tokens = sum(row["tokens"] for row in rows)
    entries = [text for row in rows for text in row["conflicts"]]
    kinds = {}
    for text in entries:
        kinds[_conflict_kind(text)] = kinds.get(_conflict_kind(text), 0) + 1
    started_together = len(rows) + len(running)
    edges = sorted({0.0, *[row["duration_s"] for row in rows]})
    timeline = [[edge, sum(row["duration_s"] > edge for row in rows) + len(running)] for edge in edges if edge < span]
    mean = (sum(min(row["duration_s"], span) for row in rows) + len(running) * span) / span
    host = host_cap(cpus, agents_per_cpu)
    wave = {"label": "wave 1+2a measured cohort", "agents": len(rows), "duration_seconds": int(round(span)),
            "tasks_verified": len(merged), "tokens": tokens, "conflicts": len(entries),
            "failures": len(rows) - len(merged), "batch": 1}
    if source:
        wave["source"] = str(source)[:200]
    limits = {"start": min(START_AGENTS, host["cap"]), "max_agents": host["cap"], "max_batch": 1}
    try:
        decision = recommend_concurrency([wave], limits)
    except EconomicsError as error:
        raise OrchestratorError(f"metrics: {error}") from None
    results = {
        "agents_started_together": started_together, "agents_measured": len(rows), "agents_still_running": len(running),
        "still_running": sorted(running), "merged": len(merged), "not_merged": len(rows) - len(merged),
        "wall_clock_seconds": span,
        "throughput": {
            "merged_tasks_per_hour": _r(len(merged) / (span / 3600)),
            "merged_tasks_per_agent_hour": _r(len(merged) / (sum(row["active_s"] for row in rows) / 3600)),
            "definition": "merged agents in the file / wall-clock hours from the common start to the last measured "
                          "agent's finish; integration time after an agent finished is not in the file"},
        "tokens": {"total": tokens, "per_merged_task": _r(tokens / len(merged), 2),
                   "per_measured_task": _r(tokens / len(rows), 2),
                   "per_merged_task_if_followup_additive": _r(sum(r["tokens_if_followup_additive"] for r in rows) / len(merged), 2),
                   "verified_tasks_per_million_tokens": _r(len(merged) / (tokens / 1e6)),
                   "definition": "all tokens of measured agents (merged or not) / merged agents; the resumed agent's "
                                 "follow-up figure is taken as cumulative, as the metrics note says"},
        "tool_uses": {"total": sum(row["tool_uses"] for row in rows),
                      "per_merged_task": _r(sum(row["tool_uses"] for row in rows) / len(merged), 2)},
        "conflicts": {"entries": len(entries), "agents_with_conflicts": sum(1 for row in rows if row["conflicts"]),
                      "rate_agents_with_conflicts": _r(sum(1 for row in rows if row["conflicts"]) / len(rows)),
                      "entries_per_measured_task": _r(len(entries) / len(rows)), "by_kind": dict(sorted(kinds.items())),
                      "definition": "conflict entries as listed per agent (an incident two agents report counts twice); "
                                    "kind by keyword: secret-scan/security scan -> security-scan-fixture"},
        "rework": {"integrator_fixes": sum(row["integrator_fixes"] for row in rows),
                   "agents_with_integrator_fixes": sum(1 for row in rows if row["integrator_fixes"]),
                   "integrator_rework_rate": _r(sum(1 for row in merged if row["integrator_fixes"]) / len(merged)),
                   "sent_back": sum(1 for row in rows if row["sent_back"]),
                   "sent_back_rate": _r(sum(1 for row in rows if row["sent_back"]) / len(rows)),
                   "gate_reruns": sum(row["gate_reruns"] for row in rows),
                   "agents_with_gate_reruns": sum(1 for row in rows if row["gate_reruns"]),
                   "gate_rerun_rate": _r(sum(1 for row in rows if row["gate_reruns"]) / len(rows)),
                   "definition": "integrator_rework_rate = merged agents with at least one conflict 'fixed by "
                                 "integrator' / merged agents; sent back = returned to the agent; gate re-runs as recorded"},
        "concurrency": {"peak": started_together, "peak_until_seconds": min(row["duration_s"] for row in rows),
                        "mean_over_wall_clock": _r(mean),
                        "timeline": timeline,
                        "definition": "every agent started at started_utc; an agent counts until its own duration; "
                                      "still-running agents count for the whole wall clock"},
        "next_wave": {"host": host, "wave_record": wave, "limits": limits, "decision": decision,
                      "agents": decision["agents"], "rule": decision["rule"]},
    }
    if commits is not None:
        results["git"] = git_metrics(commits, started)
    return results


HOST_PRESSURE = re.compile(r"EAGAIN|BlockingIOError|load avg|load average", re.I)
CLAIMS_NOT_MADE = (
    "No 20-agent concurrent run happened in this effort: the measured peak is the 11 agents of wave 1+2a.",
    "The 1,000-agent research run belongs to the swarm session; no result of it is in this tree, so it is pending here.",
    "Token figures are host-reported subagent token counts; no money or subscription quota is derived from them.",
    "The simulated 20-agent schedule is a plan produced by plan() and schedule(); no agent ran for it.",
)


def scenario_h_evidence(metrics_bytes, metrics_path, *, commits=None, revision_range=None, observations=(),
                        cpus=4, now="2026-11-28T06:36:23Z", root=ROOT):
    """The docs/evidence/gaie-20-layers/scenario-h.json document: the measured figures with their method,
    the source snapshot and digests, host-pressure observations, a clearly labelled simulated 20-agent
    schedule and the status of the swarm session's 1,000-agent run."""
    metrics = load_json(metrics_bytes)
    results = scenario_h(metrics, commits=commits, cpus=cpus, source=metrics_path)
    twenty = plan("gaie-20-layer", now=now, root=root)
    first = schedule(twenty, [], cpus=cpus, root=root)
    present = sorted(path.name for path in (pathlib.Path(root) / "swarm/phase3/evidence").glob("*.json"))
    return {
        "schema": EVIDENCE_KIND, "scenario": "H", "kind": "measured", "simulated": False,
        "title": "Adaptive agent orchestration measured on the GAIE 20-layer integration effort",
        "method": ("Figures are computed by engineering_os.orchestrator.scenario_h from the wave-metrics snapshot "
                   "below (host task notifications and integrator gate logs of real agents) and, for merge times, "
                   "from the first-parent history of the integration branch. Each result carries its definition. "
                   "The next-wave size is economics.recommend_concurrency on the measured cohort with the host cap "
                   "of a 4-CPU host. Deterministic code; no model was called."),
        "source": {"path": str(metrics_path), "sha256": contracts.sha256(metrics_bytes),
                   "snapshot_sha256": sha256(metrics), "snapshot": metrics,
                   "note": "the metrics file is a snapshot taken while three agents were still running"},
        "git_source": None if commits is None else {
            "branch": "claude/gaie-20-layer-integration", "range": revision_range,
            "command": f"git log --first-parent --reverse --format='%h %cI %s' {revision_range}", "commits": commits},
        "results": results,
        "host_cap_policy": dict(host_cap(cpus), rationale=(
            "Agents run model calls remotely but tests, builds and gates locally; the observations below show "
            "load-sensitive subprocess tests failing at 11 concurrent agents on 4 shared CPUs.")),
        "host_pressure": list(observations),
        "simulated_20_agent_schedule": {
            "simulated": True, "kind": "simulated",
            "about": "plan() of the twenty-role goal and schedule() with no history; no agent was started",
            "plan_sha256": twenty["plan_sha256"], "tasks": len(twenty["tasks"]), "agents": len(twenty["agents"]),
            "wave_sizes": [len(wave) for wave in twenty["waves"]], "critical_path": twenty["critical_path"],
            "checks": twenty["checks"], "first_wave": {key: first[key] for key in ("agents", "recommended_agents",
                                                                                 "wave", "rule", "reason")}},
        "swarm_1000_agent_run": {
            "status": "pending", "owner": "swarm session",
            "evidence_files_in_tree": [f"swarm/phase3/evidence/{name}" for name in present],
            "note": "the files present describe the third phase's development agents and coordinator, not the "
                    "1,000-agent run, whose results are not in this tree"},
        "claims_not_made": list(CLAIMS_NOT_MADE),
        "reproduce": ("python3 -m engineering_os.orchestrator scenario-h --metrics <wave-metrics.json> "
                      f"--git-range {revision_range} --checkpoints <checkpoints dir> --evidence"),
        "provider_calls": 0}


def host_pressure_observations(directory):
    """Quoted test notes from agent checkpoints that report host-load failures (fork EAGAIN, timeouts)."""
    found = []
    for path in sorted(pathlib.Path(directory).glob("*.json")):
        try:
            value = load_json(path.read_bytes())
        except (OSError, ValueError):
            continue
        tests = value.get("tests") if isinstance(value, dict) else None
        notes = [tests] if isinstance(tests, dict) else []
        notes += [item for item in (tests or {}).values() if isinstance(item, dict)] if isinstance(tests, dict) else []
        for row in notes:
            note = row.get("note")
            if isinstance(note, str) and HOST_PRESSURE.search(note):
                found.append({"source": str(path), "task_id": value.get("task_id"), "note": note[:600]})
    return found


def first_parent_commits(repo, revision_range):
    """Read-only `git log --first-parent` rows (oldest first) for Scenario H's merge timeline."""
    _need(isinstance(revision_range, str) and re.fullmatch(r"[0-9a-f]{7,40}\.\.[0-9a-f]{7,40}", revision_range),
          "range: <sha>..<sha>")
    output = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", os.fspath(repo), "log", "--first-parent",
                             "--reverse", "--format=%h%x1f%cI%x1f%s", revision_range],
                            capture_output=True, text=True, timeout=60, check=True).stdout
    return [dict(zip(("commit", "at", "subject"), line.split("\x1f"))) for line in output.splitlines() if line]


# ---------------------------------------------------------------- contract engine and CLI

def engine(action, payload, ctx=None):
    """Control-plane entrypoint `(action, payload, ctx) -> dict`; every action is side-effect free."""
    _need(isinstance(payload, dict), "payload: object")
    if action == "plan":
        _need(set(payload) <= {"goal", "roles", "max_agents", "per_role", "frozen", "now"} and "goal" in payload,
              "plan payload: goal, optional roles, max_agents, per_role, frozen, now")
        return plan(payload["goal"], roles=payload.get("roles"), max_agents=payload.get("max_agents", MAX_AGENTS),
                    per_role=payload.get("per_role", 1), frozen=payload.get("frozen", ()), now=payload.get("now"))
    if action == "schedule":
        _need(set(payload) <= {"plan", "history", "done", "cpus", "frozen"} and {"plan", "history"} <= set(payload),
              "schedule payload: plan, history, optional done, cpus, frozen")
        return schedule(payload["plan"], payload["history"], done=payload.get("done", ()), cpus=payload.get("cpus"),
                        frozen=payload.get("frozen", ()))
    if action == "review-assignment":
        _need(set(payload) == {"task"}, "review-assignment payload: task")
        return review_assignment(payload["task"])
    if action == "worktree-plan":
        _need({"plan", "repo", "base_dir"} <= set(payload) <= {"plan", "repo", "base_dir", "base_ref", "frozen"},
              "worktree-plan payload: plan, repo, base_dir, optional base_ref, frozen")
        return worktree_plan(payload["plan"], repo=payload["repo"], base_dir=payload["base_dir"],
                             base_ref=payload.get("base_ref", "HEAD"), frozen=payload.get("frozen", ()))
    if action == "scenario-h":
        _need({"metrics"} <= set(payload) <= {"metrics", "commits", "cpus"}, "scenario-h payload: metrics, optional commits, cpus")
        return scenario_h(payload["metrics"], commits=payload.get("commits"), cpus=payload.get("cpus", 4))
    raise OrchestratorError(f"orchestrator has no action {action!r}")


def health():
    """Plan the twenty-role goal and verify it; no side effects."""
    try:
        value = plan("gaie-health", now="2026-01-01T00:00:00Z")
        verify_plan(value)
        return {"ok": True, "detail": f"{len(value['tasks'])} tasks, {len(value['waves'])} waves, no path overlap, "
                                      "independent reviewers; deterministic, nothing executed"}
    except Exception as error:  # health reports, never raises
        return {"ok": False, "detail": f"{type(error).__name__}: {str(error)[:200]}"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("plan", help="plan a goal id (one task per role) or a goal/spec JSON file")
    make.add_argument("goal")
    make.add_argument("--max-agents", type=int, default=MAX_AGENTS)
    make.add_argument("--per-role", type=int, default=1)
    make.add_argument("--now")
    make.add_argument("--summary", action="store_true")
    scenario = commands.add_parser("scenario-h", help="compute Scenario H from measured wave metrics")
    scenario.add_argument("--metrics", required=True, type=pathlib.Path)
    scenario.add_argument("--git-range", help="<sha>..<sha> of the integration branch (read-only git log)")
    scenario.add_argument("--cpus", type=int, default=4)
    scenario.add_argument("--checkpoints", type=pathlib.Path, help="agent checkpoint directory (host-pressure notes)")
    scenario.add_argument("--evidence", action="store_true", help="print the full scenario-h.json document")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            goal = args.goal
            if goal.endswith(".json"):
                goal = _read_json(goal)
            result = plan(goal, max_agents=args.max_agents, per_role=args.per_role, now=args.now)
            if args.summary:
                result = {"plan_sha256": result["plan_sha256"], "tasks": len(result["tasks"]),
                          "waves": [len(w) for w in result["waves"]], "critical_path": result["critical_path"],
                          "checks": result["checks"]}
        else:
            commits = first_parent_commits(ROOT, args.git_range) if args.git_range else None
            if args.evidence:
                observations = host_pressure_observations(args.checkpoints) if args.checkpoints else ()
                result = scenario_h_evidence(args.metrics.read_bytes(), args.metrics, commits=commits,
                                             revision_range=args.git_range, observations=observations, cpus=args.cpus)
            else:
                result = scenario_h(_read_json(args.metrics), commits=commits, cpus=args.cpus, source=args.metrics)
        print(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    except (OrchestratorError, subprocess.SubprocessError, OSError) as error:
        print(f"orchestrator: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
