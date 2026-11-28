"""Thin engine adapters for the Engineering Control Plane (layer L04).

Each engine has one entrypoint ``(action, payload, ctx) -> dict`` and one
``health() -> {"ok", "detail"}``. The adapters only translate a JSON payload into
a call of the existing module that owns the logic; they contain no second
implementation. Payloads are data: no field is ever evaluated, executed, used as
a command line or treated as an instruction. Authorization is not decided here:
``control_plane.invoke`` asks the Security Governor before any adapter runs.

Memory and the usage ledger are reached only through ``memory_store`` and
``append_usage`` / ``read_usage`` so that a storage
switch (for example the unified engineering memory) is a change in one place.
Standard library only. SPDX-License-Identifier: MIT.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEDGER = ("economics", "ledger.jsonl")
MEMORY_DIR = "memory"
CONTEXT_DIR = "context"
MAX_PATH = 4096
MAX_LEDGER_ROWS = 10000
TEST_MODULE = re.compile(r"tests\.test_[a-z0-9_]{1,80}")
_TESTS = re.compile(r"Ran (\d+) tests? in")

# Files whose bytes define each engine's behaviour; hashed into every receipt.
COMMON_SOURCES = ("engineering_os/adapters.py", "engineering_os/control_plane.py", "governance/engines.json")
SOURCES = {
    "master-router": ("engineering_os/gaie_router.py", "governance/policies/gaie-routes.json",
                      "projects/registry.json", "projects/aliases.json", "skills/gaie-master-router/SKILL.md"),
    "master-build": ("engineering_os/factory.py", "engineering_os/gaie_router.py",
                     "governance/policies/gaie-routes.json", "skills/gaie-build/SKILL.md", "prompts/MASTER_BUILD.md",
                     "engineering_os/build_engine.py", "engineering_os/requirements.py",
                     "templates/app-stdlib/manifest.json"),
    "master-upgrade": ("engineering_os/factory.py", "engineering_os/gaie_router.py",
                       "governance/policies/gaie-routes.json", "skills/gaie-upgrade/SKILL.md", "prompts/MASTER_UPGRADE.md",
                       "engineering_os/upgrade_engine.py", "engineering_os/detectors.py", "engineering_os/healing.py",
                       "engineering_os/workspace_policy.py"),
    "master-audit": ("engineering_os/gaie_inventory.py", "engineering_os/control.py", "hub.py", "hublink.py",
                     "engineering_os/gaie_router.py", "governance/policies/gaie-routes.json", "skills/gaie-audit/SKILL.md"),
    "master-cinematic": ("engineering_os/cinematic.py", "engineering_os/gaie_router.py",
                         "governance/policies/gaie-routes.json", "skills/gaie-cinematic/SKILL.md",
                         "docs/evidence/nextgen-cinematic-inventory.json"),
    "master-release": ("scripts/verify_release.py", "sdk/engineering_sdk.py", "engineering_os/gaie_router.py",
                       "governance/policies/gaie-routes.json", "skills/gaie-release/SKILL.md"),
    "reasoning": ("engineering_os/reasoning.py",),
    "memory": ("engineering_os/memory.py", "engineering_os/orchestration.py"),
    "self-healing": ("engineering_os/healing.py", "engineering_os/detectors.py"),
    "economics": ("engineering_os/economics.py", "engineering_os/model_router.py", "swarm/phase3/adaptive.py",
                  "swarm/phase3/economics.py", "swarm/phase3/context_budget.py", "swarm/evidence/ladder.json",
                  "swarm/evidence/tool-audit.json", "swarm/phase2/evidence/stages.json", "swarm/phase2/RESULTS.md",
                  "swarm/phase2/PLAN.json", "swarm/phase3/evidence/team.json", "swarm/phase3/evidence/team2.json",
                  "swarm/phase3/evidence/coordinator-scale.json"),
    "capability-registry": ("engineering_os/control.py", "hub.py", "catalog/registry.json"),
    "layers": ("engineering_os/layers.py", "engineering_os/contracts.py", "governance/layers.json",
               "governance/agent-roles.json"),
    "motion-sdk": ("engineering_os/control.py", "hub.py", "motion-library/MOTION_CATALOG.json",
                   "packages/motion-sdk/index.mjs"),
    "context-intelligence": ("tools/headroom_context.py", "tools/headroom_worker.py",
                             "skills/ultra-context-optimization/scripts/hr.py"),
    "agent-swarm": ("swarm/scheduler.py", "engineering_os/orchestration.py"),
    "adaptive-scheduler": ("swarm/phase3/adaptive.py",),
    "security-governor": ("engineering_os/governor.py", "engineering_os/contracts.py"),
    "quality-assurance": ("engineering_os/governor.py", "engineering_os/contracts.py"),
    # Wave-2 engines (adding an engine: CONTROL_PLANE.md section 6).
    "orchestrator": ("engineering_os/orchestrator.py", "engineering_os/layers.py", "engineering_os/reasoning.py",
                     "engineering_os/economics.py", "engineering_os/orchestration.py", "governance/agent-roles.json",
                     "governance/layers.json", "swarm/scheduler.py", "swarm/phase3/adaptive.py"),
    "security-audit": ("engineering_os/security_audit.py", "engineering_os/governor.py", "scripts/security_scan.py"),
    "requirements": ("engineering_os/requirements.py",
                     *sorted(f"governance/domains/{p.name}" for p in (ROOT / "governance/domains").glob("*.json"))),
    "cinematic-production": ("engineering_os/video_pipeline.py", "engineering_os/cinematic.py",
                             "packages/motion-engines/registry.json"),
}

# Payload fields that name a filesystem location; the governor checks each one
# against the grant's paths (after realpath) before the adapter may touch it.
PATH_FIELDS = {
    ("master-router", "route"): ("workspace",),
    ("master-build", "evaluate"): ("artifact_root",),
    ("master-upgrade", "evaluate"): ("artifact_root",),
    ("master-audit", "inventory"): ("target",),
    ("master-audit", "health"): ("project",),
    ("master-release", "eligibility"): ("root",),
    ("memory", "search"): ("source_root",),
    ("memory", "index"): ("source_root",),
    ("memory", "checkpoint"): ("destination",),
    ("memory", "restore"): ("checkpoint",),
    ("memory", "verify"): ("source_root", "receipt_path"),
    ("context-intelligence", "optimize"): ("input",),
}
# Wave-2 location fields. Besides the governor's realpath check against the grant, each one must be
# canonical before the governor is asked: absolute, normalized and with no symbolic link in any
# existing component (adapters._location), so a link swapped in after the check cannot redirect a write.
CANONICAL_PATH_FIELDS = {
    ("orchestrator", "worktree-plan"): ("repo", "base_dir"),
    ("cinematic-production", "render"): ("out_dir", "voiceover_dir", "music_file"),
    ("cinematic-production", "qa"): ("path",),
    ("master-build", "build"): ("out_dir", "workspace"),
    ("master-build", "evaluate-app"): ("app_dir",),
    ("master-build", "request-repository"): ("app_dir",),
    ("master-upgrade", "audit"): ("target", "workdir"),
    ("master-upgrade", "upgrade"): ("target", "workdir"),
    ("self-healing", "detect"): ("target",),
    ("self-healing", "heal"): ("target", "workdir"),
    **{("memory", action): ("source_root",) for action in
       ("retrieve", "adr-get", "why", "solutions", "failure-recall", "brief", "where", "evidence-status")},
}
PATH_FIELDS.update(CANONICAL_PATH_FIELDS)
# Actions that always read the trusted Hub checkout: the grant must cover it.
HUB_READERS = frozenset({("quality-assurance", "run-tests"), ("security-audit", "audit")})


class AdapterError(ValueError):
    """A payload does not fit the data contract of the requested action."""


# ---------------------------------------------------------------- helpers

def _fields(payload, required=(), optional=()):
    if not isinstance(payload, dict):
        raise AdapterError("payload must be an object")
    keys = set(payload)
    if not set(required) <= keys or not keys <= set(required) | set(optional):
        raise AdapterError(f"payload fields: required {sorted(required)}, optional {sorted(optional)}")
    return payload


def _string(value, field, limit=MAX_PATH):
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise AdapterError(f"{field}: non-empty text up to {limit} characters")
    return value


def _integer(value, field, low, high):
    if type(value) is not int or not low <= value <= high:
        raise AdapterError(f"{field}: integer {low}-{high}")
    return value


def _rows(items):
    return {"count": len(items), "rows": items}


def _unknown(engine, action):
    raise AdapterError(f"{engine} has no action {action!r}")


def _state(ctx):
    state = ctx.get("state_dir") if isinstance(ctx, dict) else None
    if state is None:
        raise AdapterError("a private state directory is required")
    return pathlib.Path(state)


def load_path_module(name, relative):
    """Load a file that is not inside a package (swarm/, tools/, skill scripts) without
    registering it in sys.modules or keeping any sys.path change it makes."""
    path = ROOT / relative
    if path.is_symlink() or not path.is_file():
        raise AdapterError(f"module source missing: {relative}")
    spec = importlib.util.spec_from_file_location(f"gaie_cp_{name}", path)
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


def _governor():
    from . import control_plane
    if control_plane.governor is None:
        raise AdapterError("engineering_os.governor is not installed; governed actions are refused")
    return control_plane.governor


def _healthy(check):
    """Run a read-only probe; any failure is reported, never raised."""
    try:
        detail = check()
        return {"ok": True, "detail": detail}
    except Exception as error:  # health must report, not crash discovery
        return {"ok": False, "detail": f"{type(error).__name__}: {str(error)[:200]}"}


def _location(value, field):
    """A canonical absolute location: normalized text, no '..', no symbolic link in any existing component.
    The location itself need not exist yet (an output directory is created by its engine)."""
    raw = _string(value, field)
    path = pathlib.Path(raw)
    if not path.is_absolute() or raw != str(path) or ".." in path.parts or path == pathlib.Path(path.anchor):
        raise AdapterError(f"{field}: canonical absolute path required")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise AdapterError(f"{field}: a symbolic link in the path is refused")
    return raw


def _directory(value, field):
    """An existing canonical directory (see _location)."""
    raw = _location(value, field)
    if not pathlib.Path(raw).is_dir():
        raise AdapterError(f"{field}: existing directory required")
    return raw


def _flag(payload, field, default):
    value = payload.get(field, default)
    if type(value) is not bool:
        raise AdapterError(f"{field}: boolean")
    return value


def request_paths(engine, action, payload):
    """Filesystem locations named by a payload, for the governor's path check."""
    if not isinstance(payload, dict):
        raise AdapterError("payload must be an object")
    if (engine, action) in HUB_READERS:
        return (str(ROOT),)  # this adapter always reads the trusted Hub checkout
    paths = []
    for field in PATH_FIELDS.get((engine, action), ()):
        if payload.get(field) is not None:
            if engine == "master-audit":
                paths.append(_audit_directory(payload[field], field))
            elif (engine, action) in CANONICAL_PATH_FIELDS:
                paths.append(_location(payload[field], field))
            else:
                paths.append(_string(payload[field], field))
    return tuple(paths)


def source_files(engine):
    return (*COMMON_SOURCES, *SOURCES.get(engine, ()))


def source_digests(engine):
    """{relative path: sha256 or None if absent}; symlinks are never followed."""
    result = {}
    for relative in source_files(engine):
        path = ROOT / relative
        result[relative] = (hashlib.sha256(path.read_bytes()).hexdigest()
                            if path.is_file() and not path.is_symlink() else None)
    return result


def _route_spec(intent):
    """The registered GAIE route for one intent, bound to its skill/prompt bytes."""
    from . import gaie_router
    rules = gaie_router.policy()
    engine = rules["engines"][intent]
    skill = f"skills/{engine['skill']}/SKILL.md"
    files = {skill: None}
    if engine.get("prompt"):
        files[engine["prompt"]] = None
    for relative in files:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise AdapterError(f"route source missing: {relative}")
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    gates = [*rules["gates"]["all"], *rules["gates"].get(intent, [])]
    return {"intent": intent, "engine": engine["engine"], "skill": engine["skill"], "prompt": engine.get("prompt"),
            "scope": engine.get("scope"), "write": bool(engine["write"]), "workstreams": rules["workstreams"][intent],
            "hub_commands": rules["hub_commands"][intent], "gates": gates, "source_sha256": files,
            "execution": ("instructions for an agent host; this spec action plans and generates nothing (code is generated only "
                          "by the separate build or upgrade action under its own workspace-write grant)"),
            "evidence_boundary": "A route specification is a plan, not execution evidence."}


# ---------------------------------------------------------------- L03 master-router

def master_router(action, payload, ctx):
    from . import gaie_router
    environ = ctx.get("environ")
    if action == "route":
        _fields(payload, ("text",), ("workspace",))
        return gaie_router.route(payload["text"], environ=environ, workspace_path=payload.get("workspace"))
    if action == "projects":
        _fields(payload)
        rows = [{key: row[key] for key in ("id", "repository", "visibility", "source", "aliases")}
                for row in gaie_router.projects(environ).values()]
        return _rows(rows)
    return _unknown("master-router", action)


def master_router_health():
    def check():
        from . import gaie_router
        rules = gaie_router.policy()
        missing = sorted(i for i, e in rules["engines"].items() if not (ROOT / "skills" / e["skill"] / "SKILL.md").is_file())
        if missing:
            raise AdapterError(f"route skills missing for {missing}")
        return f"route policy v{rules['policy_version']} with {len(rules['engines'])} intents; skills present"
    return _healthy(check)


# ---------------------------------------------------------------- L16 master-build / L06 master-upgrade

def _factory(engine, action, payload):
    from . import factory
    if action == "plan":
        return factory.plan_factory(payload)
    if action == "evaluate":
        _fields(payload, ("plan", "receipts", "artifact_root"))
        return factory.evaluate_factory(payload["plan"], payload["receipts"],
                                        artifact_root=_string(payload["artifact_root"], "artifact_root"))
    return _unknown(engine, action)


BUILD_ACTIONS = ("plan-app", "build", "evaluate-app", "request-repository")  # build_engine.publish is never registered


def _app_directory(value):
    """An application directory built by master-build: canonical, with its .gaie metadata not linked elsewhere."""
    from . import build_engine
    app = pathlib.Path(_directory(value, "app_dir"))
    for relative in (".gaie", build_engine.REQUEST_FILE, ".gaie/spec.json", build_engine.FACTORY_DIR):
        if (app / relative).is_symlink():
            raise AdapterError(f"app_dir: {relative} must not be a symbolic link")
    return app


def _build_engine(action, payload, ctx):
    """The real generator (engineering_os.build_engine); the workspace is always explicit and path-checked."""
    from . import build_engine
    if action == "plan-app":
        _fields(payload, ("spec",), ("allow_open_questions",))
        return build_engine.plan(payload["spec"], allow_open_questions=_flag(payload, "allow_open_questions", False))
    if action == "build":
        _fields(payload, ("spec", "out_dir", "workspace", "hub_revision"), ("now", "verify", "e2e"))
        return build_engine.build(payload["spec"], out_dir=_location(payload["out_dir"], "out_dir"),
                                  hub_revision=payload["hub_revision"], now=payload.get("now"),
                                  workspace=pathlib.Path(_directory(payload["workspace"], "workspace")),
                                  environ=ctx.get("environ"), verify=_flag(payload, "verify", True),
                                  e2e=_flag(payload, "e2e", True))
    if action == "evaluate-app":
        _fields(payload, ("app_dir",))
        return build_engine.evaluate(_app_directory(payload["app_dir"]))
    _fields(payload, ("app_dir",))  # request-repository: writes the owner's request file only; never contacts GitHub
    return build_engine.request_repository(_app_directory(payload["app_dir"]))


def master_build(action, payload, ctx):
    if action == "spec":
        _fields(payload)
        return _route_spec("build")
    if action in BUILD_ACTIONS:
        return _build_engine(action, payload, ctx)
    return _factory("master-build", action, payload)


UPGRADE_SCOPES = {"comprehensive": "upgrade", "performance": "accelerate", "self-healing": "repair"}


def master_upgrade(action, payload, ctx):
    if action == "spec":
        _fields(payload, (), ("scope",))
        scope = payload.get("scope", "comprehensive")
        if scope not in UPGRADE_SCOPES:
            raise AdapterError(f"scope must be one of {sorted(UPGRADE_SCOPES)}")
        return _route_spec(UPGRADE_SCOPES[scope])
    if action in ("audit", "upgrade"):
        # The real engine (engineering_os.upgrade_engine): audit reads only and accepts only an audit command;
        # upgrade works in an isolated copy under workdir and never writes the target.
        from . import upgrade_engine
        _fields(payload, ("target", "command", "workdir"), ("tests", "policy"))
        located = {"target": _directory(payload["target"], "target"), "workdir": _location(payload["workdir"], "workdir")}
        return upgrade_engine.engine(action, {**payload, **located}, {"environ": ctx.get("environ")})
    return _factory("master-upgrade", action, payload)


def _factory_health(intent, prompt, generator):
    def check():
        from . import factory
        spec = _route_spec(intent)
        if spec["prompt"] != prompt:
            raise AdapterError("route prompt changed")
        plan = factory.plan_factory({"schema_version": 1, "project": "health-probe", "source_revision": "0" * 40,
                                     "requirements": [{"id": "probe", "summary": "Health probe.", "acceptance": ["unit"]}],
                                     "targets": ["api"]})
        probe = generator()  # side-effect free self check of the generator module
        if not probe["ok"]:
            raise AdapterError(f"generator unhealthy: {probe['detail']}")
        return (f"{spec['engine']} route and {spec['skill']} skill present; factory plan of {len(plan['stages'])} stages; "
                f"generator: {probe['detail']}")
    return _healthy(check)


def master_build_health():
    from . import build_engine
    return _factory_health("build", "prompts/MASTER_BUILD.md", build_engine.health)


def master_upgrade_health():
    from . import upgrade_engine
    return _factory_health("upgrade", "prompts/MASTER_UPGRADE.md", upgrade_engine.health)


# ---------------------------------------------------------------- L12 master-audit

def _audit_directory(value, field):
    raw = _string(value, field)
    path = pathlib.Path(raw)
    if not path.is_absolute() or path == pathlib.Path(path.anchor) or raw != str(path) or ".." in path.parts:
        raise AdapterError(f"{field}: canonical absolute project directory required")
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_dir():
        raise AdapterError(f"{field}: existing project directory without symlinks required")
    return str(path)


def master_audit(action, payload, ctx):
    if action == "spec":
        _fields(payload)
        return _route_spec("audit")
    if action == "inventory":
        from . import gaie_inventory
        _fields(payload, ("target",))
        return gaie_inventory.inventory(_audit_directory(payload["target"], "target"))
    if action == "health":
        from . import control
        _fields(payload, (), ("project",))
        project = payload.get("project")
        return control.health(None if project is None else _audit_directory(project, "project"))
    if action == "hub-audit":
        import hub
        _fields(payload)
        return hub.audit()
    return _unknown("master-audit", action)


def master_audit_health():
    def check():
        from . import control, gaie_inventory
        _route_spec("audit")
        if not callable(gaie_inventory.inventory) or control.health()["scope"] != "hub":
            raise AdapterError("inventory or hub health projection unavailable")
        return "inventory, hub health projection and audit route present"
    return _healthy(check)


# ---------------------------------------------------------------- L18 master-cinematic

def master_cinematic(action, payload, ctx):
    if action == "spec":
        _fields(payload)
        return _route_spec("cinematic")
    if action == "audit":
        from . import cinematic
        if not isinstance(payload, dict):
            raise AdapterError("payload must be an object")
        return cinematic.audit_inventory(payload or None)
    return _unknown("master-cinematic", action)


def master_cinematic_health():
    def check():
        from . import cinematic
        _route_spec("cinematic")
        report = cinematic.audit_inventory()
        return f"source-bound inventory of {report['brief_count']} briefs; runtime claims need browser receipts"
    return _healthy(check)


# ---------------------------------------------------------------- L11 master-release

def master_release(action, payload, ctx):
    if action == "spec":
        _fields(payload)
        return _route_spec("release")
    if action == "provenance":
        from scripts import verify_release
        _fields(payload, ("commit", "repository", "runs", "jobs"))
        if not isinstance(payload["jobs"], dict):
            raise AdapterError("jobs: object keyed by workflow path")
        runs = verify_release.approved_runs(payload["runs"], payload["commit"], payload["repository"])
        workflows = []
        for path, run_id in sorted(runs.items()):
            if path not in payload["jobs"]:
                raise AdapterError(f"jobs missing for {path}")
            workflows.append({"workflow": path, "run_id": run_id,
                              "jobs": verify_release.approved_jobs(payload["jobs"][path], path, run_id, payload["commit"])})
        return {"commit": payload["commit"], "repository": payload["repository"], "workflows": workflows,
                "metadata_source": "caller-supplied workflow metadata; nothing was fetched",
                "product_deployment_performed": False}
    if action == "eligibility":
        from sdk import engineering_sdk
        _fields(payload, ("root", "evidence", "repository", "team", "project", "commit"))
        return engineering_sdk.release(pathlib.Path(_string(payload["root"], "root")), payload["evidence"],
                                       payload["repository"], payload["team"], payload["project"], payload["commit"])
    return _unknown("master-release", action)


def master_release_health():
    def check():
        from scripts import verify_release
        from sdk import engineering_sdk
        _route_spec("release")
        if not verify_release.WORKFLOWS or not callable(engineering_sdk.release):
            raise AdapterError("release provenance tooling unavailable")
        return f"provenance over {len(verify_release.WORKFLOWS)} required workflows; eligibility check never deploys"
    return _healthy(check)


# ---------------------------------------------------------------- L13 reasoning

# Further reasoning.ENGINE_RECORD actions: payload-only computations through reasoning.engine with an empty
# context (wall clock for `now`; route-model never sees host credentials).
REASONING_ACTIONS = ("strategy", "decompose", "plan-goal", "constraints", "dependencies", "rca", "counterfactual",
                     "uncertainty", "perspectives", "validate-decision", "trade-off", "route-model")


def reasoning(action, payload, ctx):
    from . import reasoning as module
    if action in REASONING_ACTIONS:
        if not isinstance(payload, dict):
            raise AdapterError("payload must be an object")
        return module.engine(action, payload, {})
    if action == "plan":
        return module.plan(payload)
    if action == "review":
        _fields(payload, ("plan", "reviews", "verification"))
        return module.review_decision(payload["plan"], payload["reviews"], payload["verification"])
    if action == "root-causes":
        _fields(payload, ("observations", "dependencies"))
        return module.root_causes(payload["observations"], payload["dependencies"])
    return _unknown("reasoning", action)


def reasoning_health():
    def check():
        from . import reasoning as module
        result = module.root_causes([], {"probe": []})
        if result["uncertain_nodes"] != ["probe"] or result["causality_proven"] is not False:
            raise AdapterError("root-cause probe changed")
        return "deterministic planner, review and root-cause analysis importable"
    return _healthy(check)


# ---------------------------------------------------------------- L14 memory

def memory_store(ctx, *, read_only=False):
    """Open the private memory store in the mode required by the governed action."""
    from .memory import MemoryStore
    return MemoryStore(_state(ctx) / MEMORY_DIR, read_only=read_only)


# Further MemoryStore actions (memory.ENGINE_RECORD): method, required and optional fields besides `project`.
# Reads open the store read-only and never create it; writes need their own state-write grant.
MEMORY_READS = {
    "retrieve": ("retrieve", (), ("query", "limit", "kinds", "tags", "include_symbols", "source_root")),
    "neighbours": ("neighbours", ("node",), ("relation", "direction")),
    "path": ("graph_path", ("source", "target"), ("max_depth", "relations")),
    "adr-get": ("adr", ("adr_id",), ("source_root",)),
    "why": ("why", ("question",), ("limit", "source_root")),
    "solutions": ("solutions", (), ("source_root",)),
    "failure-recall": ("recall_failure", ("signature",), ("limit", "source_root")),
    "next-steps": ("next_steps", (), ("task_id",)),
    "brief": ("brief", (), ("source_root",)),
    "where": ("where", ("name",), ("limit", "source_root")),
    "evidence-status": ("evidence_status", ("id",), ("source_root",)),
}
MEMORY_WRITES = {
    "adr-add": ("adr_add", ("title", "context", "decision", "consequences"), ("engine", "status", "supersedes", "tags", "symbols")),
    "adr-status": ("adr_status", ("adr_id", "status"), ()),
    "failure-record": ("record_failure", ("signature", "summary"), ("engine", "title", "root_cause", "fix", "tags", "symbols")),
    "task-progress": ("task_progress", ("task_id", "title", "done", "remaining"),
                      ("engine", "status", "summary", "decisions", "symbols")),
}
_MEMORY_LISTS = ("kinds", "tags", "relations", "decisions", "symbols", "done", "remaining")


def _memory_action(action, payload, ctx):
    from .memory import MissingMemory
    read = action in MEMORY_READS
    method, required, optional = (MEMORY_READS if read else MEMORY_WRITES)[action]
    _fields(payload, ("project", *required), optional)
    arguments = {("identifier" if key == "id" else key): value for key, value in payload.items() if key != "project"}
    if "source_root" in arguments:
        arguments["source_root"] = _location(arguments["source_root"], "source_root")
    for key in _MEMORY_LISTS:
        if key in arguments and not isinstance(arguments[key], list):
            raise AdapterError(f"{key}: list")
    try:
        result = getattr(memory_store(ctx, read_only=read), method)(payload["project"], **arguments)
    except MissingMemory:
        if not read:
            raise
        return {"project": payload["project"], "memory_present": False, "count": 0, "rows": []}
    return result if isinstance(result, dict) else _rows(result)


def memory(action, payload, ctx):
    from .memory import MissingMemory
    if action in MEMORY_READS or action in MEMORY_WRITES:
        return _memory_action(action, payload, ctx)
    if action == "put":
        return memory_store(ctx).put(payload)
    if action == "search":
        _fields(payload, ("project", "query"), ("limit", "source_root"))
        try:
            rows = memory_store(ctx, read_only=True).search(payload["project"], payload["query"],
                                                            limit=payload.get("limit", 10),
                                                            source_root=payload.get("source_root"))
        except MissingMemory:
            return _rows([])
        return _rows(rows)
    if action == "graph":
        _fields(payload, ("project",))
        try:
            return memory_store(ctx, read_only=True).graph(payload["project"])
        except MissingMemory:
            return {"project": payload["project"], "nodes": [], "edges": []}
    if action == "index":
        _fields(payload, ("project", "path", "source_root", "engine"))
        return _rows(memory_store(ctx).index_python(payload["project"], payload["path"],
                                                    _string(payload["source_root"], "source_root"), payload["engine"]))
    if action == "checkpoint":
        _fields(payload, ("destination",))
        return memory_store(ctx).checkpoint(_string(payload["destination"], "destination"))
    if action == "restore":
        _fields(payload, ("checkpoint",))
        return memory_store(ctx).restore(_string(payload["checkpoint"], "checkpoint"))
    if action == "verify":
        _fields(payload, ("project", "id", "source_root", "receipt_path", "receipt_sha256"))
        return memory_store(ctx).verify_solution(payload["project"], payload["id"],
                                                 _string(payload["source_root"], "source_root"),
                                                 _string(payload["receipt_path"], "receipt_path"), payload["receipt_sha256"])
    return _unknown("memory", action)


def memory_health():
    def check():
        from . import memory as module
        if not {"checkpoint", "solution"} <= module.KINDS or not callable(module.MemoryStore):
            raise AdapterError("memory store API changed")
        engine = module.health()  # side-effect free: secret guard and state serialization checked in memory
        if not engine["ok"]:
            raise AdapterError(f"memory engine unhealthy: {engine['detail']}")
        return "MemoryStore API present (private state directory outside Git; opened per invocation); " + engine["detail"]
    return _healthy(check)


# ---------------------------------------------------------------- L17 self-healing

_NO_SANDBOX = object()  # detectors.run_all with runtime=False never uses (or creates) a sandbox


def self_healing(action, payload, ctx):
    from . import healing
    if action == "analyze":
        return healing.analyze(payload)
    if action == "verify-repair":
        return healing.verify_repair(payload)
    if action == "detect":
        from . import detectors
        _fields(payload, ("target",), ("tests_dir", "only"))
        tests_dir = payload.get("tests_dir")
        if tests_dir is not None:
            _string(tests_dir, "tests_dir", 200)
        only = payload.get("only")
        if only is not None and (not isinstance(only, list) or not all(isinstance(name, str) for name in only)):
            raise AdapterError("only: list of detector names")
        # Static detectors only: target code is never executed and no external decoder is started.
        return detectors.run_all(_directory(payload["target"], "target"), tests_dir=tests_dir, runtime=False,
                                 sandbox=_NO_SANDBOX, ffprobe=None, only=only)
    if action == "heal":
        _fields(payload, ("target", "workdir", "tests"), ("policy",))
        return healing.heal(_directory(payload["target"], "target"), workdir=_location(payload["workdir"], "workdir"),
                            tests=payload["tests"], policy=payload.get("policy"), ffprobe=None)
    return _unknown("self-healing", action)


def self_healing_health():
    def check():
        from . import detectors, healing
        if healing.VERSION != 1 or not all(callable(f) for f in (healing.verify_repair, healing.heal, detectors.run_all)):
            raise AdapterError("healing API changed")
        return ("repair analysis, disposable-copy verification, static detectors and the isolated-copy heal loop importable; "
                "heal runs target code in the governor's full OS sandbox by default and refuses where the host lacks "
                "that tier (an audited process-only opt-in has no OS isolation); each heal report records the tier "
                "used in its sandbox field")
    return _healthy(check)


# ---------------------------------------------------------------- L19 economics

def _ledger_path(ctx):
    return _state(ctx).joinpath(*LEDGER)


def append_usage(ctx, row):
    """Append one usage row to the private economics ledger (JSON Lines)."""
    from .orchestration import _open_private, _safe_directory, canonical
    path = _ledger_path(ctx)
    _safe_directory(_state(ctx))
    _safe_directory(path.parent)
    line = canonical(row) + b"\n"
    fd = _open_private(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line)
        os.fsync(fd)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    return str(path)


def read_usage(ctx, limit=MAX_LEDGER_ROWS):
    from .orchestration import _open_private, load_json
    path = _ledger_path(ctx)
    if not path.exists() and not path.is_symlink():
        return []
    fd = _open_private(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as stream:
        data = stream.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise AdapterError("usage ledger exceeds its bound")
    rows = [load_json(line) for line in data.splitlines() if line.strip()]
    return rows[-limit:]


# Further economics.ACTIONS: exact payload fields (required, optional); the repository root is this checkout.
ECONOMICS_FIELDS = {
    "assess": (("ledger",), ()),
    "recommend-concurrency": (("waves", "limits"), ()),
    "estimate-scope": (("scope",), ("assumptions",)),
    "estimate-infrastructure": (("assumptions",), ()),
    "estimate-maintenance": (("scope",), ("build_assumptions", "assumptions")),
    "estimate-rework": (("scope",), ("build_assumptions", "assumptions")),
    "context-footprint": ((), ()),
    "measured-baseline": ((), ()),
}


def economics(action, payload, ctx):
    from . import economics as module
    if action in ECONOMICS_FIELDS:
        _fields(payload, *ECONOMICS_FIELDS[action])
        return module.engine(action, payload, {"root": str(ROOT)})
    if action == "summarize":
        return module.summarize(payload)
    if action == "recommend-model":
        _fields(payload, ("registry", "request"), ("evidence",))
        # secrets:none - credential presence is never read from the host environment.
        return module.recommend_model(payload["registry"], payload["request"], payload.get("evidence"), environ={})
    if action == "ledger":
        _fields(payload, (), ("limit",))
        rows = read_usage(ctx, _integer(payload.get("limit", 100), "limit", 1, MAX_LEDGER_ROWS))
        by_engine = {}
        for row in rows:
            key = f"{row.get('engine')}.{row.get('action')}"
            by_engine[key] = by_engine.get(key, 0) + 1
        return {"count": len(rows), "rows": rows, "invocations_by_action": dict(sorted(by_engine.items())),
                "model_calls": sum(int(row.get("model_calls", 0)) for row in rows),
                "basis": "control-plane usage rows; tokens, charges and quota are separate fields and never mixed"}
    return _unknown("economics", action)


def economics_health():
    def check():
        from . import economics as module
        if module.SCOPES != ("feature", "mvp", "enterprise"):
            raise AdapterError("economics scopes changed")
        return "offline ledger summary and gated model recommendation importable"
    return _healthy(check)


# ---------------------------------------------------------------- L04 capability-registry

def capability_registry(action, payload, ctx):
    from . import control
    if action == "list":
        _fields(payload, (), ("query", "state"))
        query = payload.get("query", "")
        return _rows(control.capabilities(_string(query, "query", 200) if query != "" else "", payload.get("state")))
    if action == "search":
        import hub
        _fields(payload, ("query",))
        needle = _string(payload["query"], "query", 200).casefold()
        return _rows([item for item in hub.registry() if needle in json.dumps(item).casefold()])
    if action == "recommend":
        import hub
        _fields(payload, ("query",))
        return _rows(hub.recommend(_string(payload["query"], "query", 200)))
    if action == "integrations":
        _fields(payload)
        return control.integrations()
    if action == "architecture":
        _fields(payload)
        return control.architecture()
    return _unknown("capability-registry", action)


def capability_registry_health():
    def check():
        import hub
        rows = hub.registry()
        return f"{len(rows)} catalog entries validated; skills and lifecycle projection available"
    return _healthy(check)


# ---------------------------------------------------------------- L04 layers

def _layer_ids(payload):
    ids = payload.get("layers")
    if ids is None:
        return None
    if not isinstance(ids, list) or not 1 <= len(ids) <= 20 or not all(isinstance(i, str) for i in ids):
        raise AdapterError("layers: list of 1-20 layer ids")
    return ids


def layers(action, payload, ctx):
    """Twenty-layer registry. Receipts live under the control plane's private state dir, in layers/."""
    from . import layers as module
    if action == "status":
        _fields(payload, (), ("layers",))
        return _rows(module.status(_layer_ids(payload), state_dir=_state(ctx) / "layers"))
    if action == "verify":
        _fields(payload, (), ("layers",))
        return module.verify(_layer_ids(payload), state_dir=_state(ctx) / "layers")
    return _unknown("layers", action)


def layers_health():
    def check():
        from . import layers as module
        records = module.load_layers()
        if [record["id"] for record in records] != [f"L{n:02d}" for n in range(1, 21)]:
            raise AdapterError("layer registry is not L01..L20")
        return "twenty-layer registry validates (contract and repository checks); status reads receipts only"
    return _healthy(check)


# ---------------------------------------------------------------- L08 motion-sdk

def motion_sdk(action, payload, ctx):
    import hub
    if action == "catalog":
        _fields(payload, (), ("query",))
        needle = _string(payload["query"], "query", 200).casefold() if "query" in payload else ""
        return _rows([row for row in hub.motion_catalog() if needle in json.dumps(row, ensure_ascii=False).casefold()])
    if action == "components":
        _fields(payload)
        return _rows(hub.motion_components())
    if action == "runtime":
        from . import control
        _fields(payload)
        return control.motions()
    return _unknown("motion-sdk", action)


def motion_sdk_health():
    def check():
        import hub
        rows = hub.motion_catalog()
        if not (ROOT / "packages/motion-sdk/index.mjs").is_file():
            raise AdapterError("packages/motion-sdk/index.mjs missing")
        return f"motion catalog of {len(rows)} entries and motion SDK package present; runtime needs browser receipts"
    return _healthy(check)


# ---------------------------------------------------------------- L02 context-intelligence

def context_intelligence(action, payload, ctx):
    if action == "status":
        _fields(payload)
        return load_path_module("headroom_context", "tools/headroom_context.py").status(None)
    if action == "view":
        _fields(payload, ("text",), ("head", "tail"))
        text = _string(payload["text"], "text", 2 * 1024 * 1024)
        head = _integer(payload.get("head", 30), "head", 1, 1000)
        tail = _integer(payload.get("tail", 30), "tail", 1, 1000)
        hr = load_path_module("hr", "skills/ultra-context-optimization/scripts/hr.py")
        view = hr.plain_view(text, head, tail)
        kept = [line for _, line in hr.must_keep(text) if line not in view]
        return {"view": view, "kept_error_lines": kept, "input_chars": len(text),
                "output_chars": len(view) + sum(len(line) + 1 for line in kept),
                "method": "plain head/tail view plus every error line verbatim; no SDK, no tokenizer"}
    tool = load_path_module("headroom_context", "tools/headroom_context.py")
    store = _state(ctx) / CONTEXT_DIR
    if action == "retrieve":
        _fields(payload, ("id",), ("query", "full"))
        full = payload.get("full", False)
        if type(full) is not bool:
            raise AdapterError("full: boolean")
        return tool.retrieve(str(store), payload["id"], payload.get("query"), full)
    if action == "optimize":
        _fields(payload, ("input", "kind"))
        return tool.optimize(pathlib.Path(_string(payload["input"], "input")), str(store), payload["kind"])
    return _unknown("context-intelligence", action)


def context_intelligence_health():
    def check():
        status = load_path_module("headroom_context", "tools/headroom_context.py").status(None)
        load_path_module("hr", "skills/ultra-context-optimization/scripts/hr.py")
        sdk = status["installed_sdk_version"] or "not installed"
        return (f"headroom tool importable (required SDK {status['required_sdk_version']}, installed {sdk}); "
                "without the SDK results are passthrough or plain views")
    return _healthy(check)


# ---------------------------------------------------------------- L03 agent-swarm / adaptive-scheduler

def agent_swarm(action, payload, ctx):
    scheduler = load_path_module("scheduler", "swarm/scheduler.py")
    if action == "plan":
        _fields(payload, ("tasks", "agents", "limit"))
        if not isinstance(payload["tasks"], list) or not isinstance(payload["agents"], list):
            raise AdapterError("tasks and agents: lists")
        if any(not isinstance(row, dict) for row in payload["tasks"] + payload["agents"]):
            raise AdapterError("tasks and agents: lists of objects")
        return scheduler.plan(payload["tasks"], payload["agents"], _integer(payload["limit"], "limit", 1, 1000))
    if action == "simulate":
        _fields(payload, (), ("limit", "agents"))
        return scheduler.simulate(_integer(payload.get("limit", 10), "limit", 1, 1000),
                                  _integer(payload.get("agents", 100), "agents", 1, 1000))
    return _unknown("agent-swarm", action)


def agent_swarm_health():
    def check():
        scheduler = load_path_module("scheduler", "swarm/scheduler.py")
        result = scheduler.plan([{"id": "a", "team": "t", "write": "w/a", "fingerprint": "a"}],
                                [{"id": "x", "team": "t", "role": "r"}], 1)
        if result["scheduled"] != 1:
            raise AdapterError("scheduler probe failed")
        return "wave scheduler importable by path (read-only); no agent is started"
    return _healthy(check)


def _finite_tree(value, depth=0):
    if depth > 4:
        raise AdapterError("adaptive input nests too deeply")
    if isinstance(value, dict):
        for item in value.values():
            _finite_tree(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _finite_tree(item, depth + 1)
    elif isinstance(value, bool) or not (value is None or isinstance(value, (int, float, str))):
        raise AdapterError("adaptive inputs are numbers, text or null")
    elif isinstance(value, float) and value != value:
        raise AdapterError("adaptive inputs must be finite")


def adaptive_scheduler(action, payload, ctx):
    if action == "next-wave":
        _fields(payload, ("history", "limits"))
        history, limits = payload["history"], payload["limits"]
        if not isinstance(history, list) or len(history) > 1000 or any(not isinstance(row, dict) for row in history):
            raise AdapterError("history: list of wave objects")
        if not isinstance(limits, dict) or type(limits.get("start")) is not int or limits["start"] < 0:
            raise AdapterError("limits: object with an integer start")
        _finite_tree(payload)
        adaptive = load_path_module("adaptive", "swarm/phase3/adaptive.py")
        try:
            return adaptive.next_wave(history, limits)
        except (TypeError, ZeroDivisionError) as error:
            raise AdapterError(f"adaptive inputs do not fit the wave rules ({type(error).__name__})") from None
    return _unknown("adaptive-scheduler", action)


def adaptive_scheduler_health():
    def check():
        adaptive = load_path_module("adaptive", "swarm/phase3/adaptive.py")
        decision = adaptive.next_wave([], {"start": 2, "max_agents": 4, "max_batch": 2, "tokens_left": None, "tasks_left": None})
        if decision["agents"] != 2:
            raise AdapterError("adaptive probe failed")
        return "next_wave importable by path (pure: no files, clock or network)"
    return _healthy(check)


# ---------------------------------------------------------------- L01 security-governor

def security_governor(action, payload, ctx):
    from . import contracts
    if action == "validate-grant":
        _fields(payload, ("grant",))
        try:
            contracts.validate_grant(payload["grant"])
        except contracts.ContractError as error:
            return {"valid": False, "reason": str(error)}
        return {"valid": True, "reason": "grant matches the shared contract"}
    if action == "check":
        from . import control_plane
        _fields(payload, ("grant", "engine", "action"), ("paths",))
        record = {row["id"]: row for row in control_plane.load_registry()}.get(payload["engine"])
        if record is None or payload["action"] not in record["actions"]:
            return {"allowed": False, "reason": "unknown engine or action", "dry_run": True}
        paths = payload.get("paths", [])
        if not isinstance(paths, list) or len(paths) > 32:
            raise AdapterError("paths: list of up to 32 locations")
        governor = _governor()
        try:
            decision = governor.check(payload["grant"], payload["engine"], payload["action"],
                                      dict(record["actions"][payload["action"]]),
                                      paths=tuple(_string(p, "paths") for p in paths), approval_token=None)
        except governor.GovernorDenied as denial:
            return {"allowed": False, "reason": str(getattr(denial, "reason", denial)), "dry_run": True}
        return {**decision, "dry_run": True}
    return _unknown("security-governor", action)


def security_governor_health():
    def check():
        governor = _governor()
        missing = [name for name in ("check", "audit", "sandbox_run") if not callable(getattr(governor, name, None))]
        if missing or not issubclass(governor.GovernorDenied, PermissionError):
            raise AdapterError(f"governor API incomplete: {missing or ['GovernorDenied']}")
        return "governor check, audit and sandbox_run present; deny by default"
    return _healthy(check)


# ---------------------------------------------------------------- L09 quality-assurance

def quality_assurance(action, payload, ctx):
    if action == "run-tests":
        _fields(payload, ("modules",), ("timeout",))
        modules = payload["modules"]
        if not isinstance(modules, list) or not 1 <= len(modules) <= 50 or len(set(modules)) != len(modules):
            raise AdapterError("modules: 1-50 distinct test module names")
        for name in modules:
            if not isinstance(name, str) or not TEST_MODULE.fullmatch(name) or not (ROOT / (name.replace(".", "/") + ".py")).is_file():
                raise AdapterError("modules: existing tests.test_* modules only")
        timeout = _integer(payload.get("timeout", 600), "timeout", 1, 1800)
        governor = _governor()
        interpreter = pathlib.Path(sys.executable).resolve()
        runtime = pathlib.Path(sys.base_prefix).resolve()
        readable = [str(ROOT)]
        if not any(runtime.is_relative_to(path) for path in governor.SYSTEM_DIRS):
            readable.append(str(runtime))
        runner = "import sys, unittest; sys.path.insert(0, sys.argv.pop(1)); unittest.main(module=None)"
        with tempfile.TemporaryDirectory(prefix="gaie-qa-", dir="/tmp") as workspace:
            run = governor.sandbox_run([str(interpreter), "-I", "-B", "-c", runner, str(ROOT), *modules],
                                       cwd=workspace, timeout=timeout, allowed_paths=(workspace,),
                                       read_paths=tuple(readable), require_fs_isolation=True)
        if run.get("fs_isolated") is not True or run.get("network_isolated") is not True:
            raise AdapterError("test runner did not establish filesystem and network isolation")
        output = f"{run.get('stdout', '')}\n{run.get('stderr', '')}"
        counted = _TESTS.findall(output)
        lines = [line for line in output.splitlines() if line.strip()]
        return {"modules": modules, "returncode": run["returncode"], "passed": run["returncode"] == 0,
                "tests_ran": int(counted[-1]) if counted else None, "summary": lines[-1][:300] if lines else "",
                "network_isolated": run["network_isolated"], "fs_isolated": run["fs_isolated"], "limit": run.get("limit"),
                "evidence_boundary": "Local test process in the governor sandbox; not CI or project verification."}
    if action == "contracts":
        from . import contracts, control_plane
        from .orchestration import load_json
        _fields(payload)
        result = {}
        try:
            result["engines"] = {"valid": True, "count": len(control_plane.load_registry(check_imports=True))}
        except (contracts.ContractError, ValueError, OSError) as error:
            result["engines"] = {"valid": False, "reason": str(error)[:300]}
        layers = ROOT / "governance/layers.json"
        if not layers.is_file():
            result["layers"] = {"present": False, "valid": None}
        else:
            try:
                rows = contracts.validate_layers(load_json(layers.read_bytes()), check_imports=True)
                result["layers"] = {"present": True, "valid": True, "count": len(rows)}
            except (contracts.ContractError, ValueError, OSError) as error:
                result["layers"] = {"present": True, "valid": False, "reason": str(error)[:300]}
        result["passed"] = result["engines"]["valid"] and result["layers"]["valid"] is not False
        return result
    return _unknown("quality-assurance", action)


def quality_assurance_health():
    def check():
        governor = _governor()
        if not callable(getattr(governor, "sandbox_run", None)) or not (ROOT / "tests").is_dir():
            raise AdapterError("sandboxed test runner unavailable")
        return "unittest runner through governor.sandbox_run (no network) and registry contract checks"
    return _healthy(check)


# ---------------------------------------------------------------- wave-2 engines
# Each wave-2 module already exposes engine(action, payload, ctx) and health(); these wrappers add what
# the control-plane contract needs and those entrypoints do not give: a known action set (an unknown
# action is an AdapterError), exact payload fields, canonical locations, and no fallback to host state.

# ---------------------------------------------------------------- L03 orchestrator

ORCHESTRATOR_ACTIONS = ("plan", "schedule", "review-assignment", "worktree-plan", "scenario-h")


def orchestrator(action, payload, ctx):
    """Plans, schedules and git worktree commands for up to twenty agents; nothing is started or run."""
    from . import orchestrator as module
    if action not in ORCHESTRATOR_ACTIONS:
        return _unknown("orchestrator", action)
    if not isinstance(payload, dict):
        raise AdapterError("payload must be an object")
    if action == "worktree-plan":
        _fields(payload, ("plan", "repo", "base_dir"), ("base_ref",))
        payload = {**payload, "repo": _directory(payload["repo"], "repo"), "base_dir": _location(payload["base_dir"], "base_dir")}
    return module.engine(action, payload)


def orchestrator_health():
    def check():
        from . import orchestrator as module
        probe = module.health()
        if not probe["ok"]:
            raise AdapterError(probe["detail"])
        return "twenty-role plan and verify_plan: " + probe["detail"]
    return _healthy(check)


# ---------------------------------------------------------------- L09 security-audit

def security_audit(action, payload, ctx):
    """The repeatable L09 audit of this checkout and the audit-log anchor of the control plane's state."""
    from . import security_audit as module
    if action == "scan":
        _fields(payload)
        return module.run(ROOT, probes=False)
    if action == "audit":
        _fields(payload)
        return module.run(ROOT, probes=True)
    if action == "anchor":
        _fields(payload)
        return module.audit_anchor(str(_state(ctx)))
    if action == "verify-anchor":
        _fields(payload, ("anchor",))
        governor = _governor()
        try:
            count = module.verify_audit_anchor(str(_state(ctx)), payload["anchor"])
        except governor.GovernorDenied as denial:
            return {"intact": False, "reason": str(getattr(denial, "reason", denial))}
        return {"intact": True, "records": count}
    return _unknown("security-audit", action)


def security_audit_health():
    def check():
        from . import security_audit as module
        if not module.FINDINGS or not all(callable(f) for f in (module.run, module.audit_anchor, module.verify_audit_anchor)):
            raise AdapterError("security audit API changed")
        return (f"{len(module.FINDINGS)} registered findings with probes and static rules importable; "
                "nothing is run by this probe")
    return _healthy(check)


# ---------------------------------------------------------------- L15 requirements

REQUIREMENTS_ACTIONS = ("parse", "refine", "validate", "diff", "acceptance", "packs")


def requirements(action, payload, ctx):
    """Owner command or brief to gaie.spec/1 and back; deterministic lexicon matching, no model."""
    from . import requirements as module
    if action not in REQUIREMENTS_ACTIONS:
        return _unknown("requirements", action)
    return module.engine(action, payload)  # exact payload fields are checked by the module


def requirements_health():
    def check():
        from . import requirements as module
        probe = module.health()
        if not probe["ok"]:
            raise AdapterError(probe["detail"])
        return "deterministic parser and validator importable; " + probe["detail"]
    return _healthy(check)


# ---------------------------------------------------------------- L18 cinematic-production

def cinematic_production(action, payload, ctx):
    """The video pipeline: storyboard checks, subtitles, headless rendering and measured media QA."""
    from . import video_pipeline as module
    if action == "inventory":
        _fields(payload)
        return module.inventory()
    if action in ("validate", "direct", "subtitles"):
        _fields(payload, ("storyboard",))
        return module.engine(action, payload)
    if action == "probe":
        _fields(payload)
        return module.engine("probe", {})
    if action == "render":
        # out_dir is required: the private state directory is never used as a media fallback.
        _fields(payload, ("storyboard", "out_dir"), ("name", "voiceover_dir", "music_file", "music_license"))
        located = {field: _location(payload[field], field) for field in ("out_dir", "voiceover_dir", "music_file")
                   if field in payload}
        return module.engine("render", {**payload, **located})
    if action == "qa":
        _fields(payload, ("path", "expect"))
        path = pathlib.Path(_location(payload["path"], "path"))
        if not path.is_file():
            raise AdapterError("path: an existing regular media file is required")
        if not isinstance(payload["expect"], dict):
            raise AdapterError("expect: object")
        return module.qa_media(path, payload["expect"])
    return _unknown("cinematic-production", action)


def cinematic_production_health():
    def check():
        from . import video_pipeline as module
        plan = module.build_plan(module.validate_storyboard(module.SAMPLE_STORYBOARD))
        native = module.inventory()["native_total"]
        tools = module.health()
        return (f"storyboard validation and planning importable ({plan['frames']} frames for the sample); "
                f"{native} native motions in the registry; render/qa/probe tools: {tools['detail']}")
    return _healthy(check)
