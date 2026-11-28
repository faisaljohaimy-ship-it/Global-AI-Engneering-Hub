"""Shared contracts of the 20-layer GAIE OS (see docs/specs/gaie-20-layers/CONTRACTS.md).

Plain-dict validators in the style of the rest of engineering_os: no third-party
imports, deterministic, every failure raises ContractError with the field at fault.
Engines, layers, grants and receipts that do not validate are never registered.
"""
import hashlib
import importlib
import json
import re

LAYER_IDS = tuple(f"L{n:02d}" for n in range(1, 21))
SIDE_EFFECTS = ("none", "state-write", "workspace-write", "repo-write", "network",
                "external-write", "production")
GATED = frozenset({"external-write", "production"})
PERMISSIONS = frozenset({
    "read:repo", "read:registry", "read:state", "write:state", "write:workspace",
    "write:repo-branch", "exec:sandbox", "net:fetch", "ext:github", "ext:deploy",
    "prod:deploy", "secrets:none",
})
SCENARIOS = frozenset("ABCDEFGHI")
_ENGINE_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_ROLE_ID = _ENGINE_ID
_REF = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
_TEST = re.compile(r"^tests/[\w.-]+\.(?:py|mjs)$")


class ContractError(ValueError):
    """A record does not satisfy the shared contract."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value):
    data = value if isinstance(value, bytes) else canonical(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def side_effect_rank(name):
    if name not in SIDE_EFFECTS:
        raise ContractError(f"unknown side-effect class: {name!r}")
    return SIDE_EFFECTS.index(name)


def _need(cond, message):
    if not cond:
        raise ContractError(message)


def _texts(value, field, *, minimum=0, maximum=64, limit=400):
    _need(isinstance(value, list) and minimum <= len(value) <= maximum, f"{field}: list of {minimum}-{maximum}")
    for item in value:
        _need(isinstance(item, str) and 0 < len(item) <= limit, f"{field}: non-empty strings up to {limit} chars")
    _need(len(set(value)) == len(value), f"{field}: duplicates")
    return value


def _bilingual(value, field):
    _need(isinstance(value, dict) and set(value) == {"en", "ar"}, f"{field}: needs exactly en and ar")
    for lang in ("en", "ar"):
        _need(isinstance(value[lang], str) and value[lang].strip(), f"{field}.{lang}: empty")
    return value


def resolve(ref):
    """Import 'package.module:callable' and return the callable (ContractError if missing)."""
    _need(isinstance(ref, str) and _REF.match(ref), f"bad reference: {ref!r}")
    module_name, attr = ref.split(":")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # the import itself is the evidence being checked
        raise ContractError(f"{ref}: import failed ({type(exc).__name__}: {exc})") from None
    target = getattr(module, attr, None)
    _need(callable(target), f"{ref}: not callable")
    return target


def validate_layer(record, *, check_imports=False):
    _need(isinstance(record, dict), "layer: object required")
    allowed = {"id", "name", "responsibilities", "interfaces", "inputs", "outputs", "depends_on",
               "permissions", "skills", "tools", "agents", "tests", "scenarios", "evidence"}
    _need(set(record) == allowed, f"layer {record.get('id')}: fields must be exactly {sorted(allowed)}")
    _need(record["id"] in LAYER_IDS, f"layer id: {record['id']!r}")
    _bilingual(record["name"], f"{record['id']}.name")
    _texts(record["responsibilities"], f"{record['id']}.responsibilities", minimum=1, maximum=12)
    _texts(record["interfaces"], f"{record['id']}.interfaces", minimum=1)
    for ref in record["interfaces"]:
        _need(_REF.match(ref), f"{record['id']}: interface {ref!r} is not module:callable")
        if check_imports:
            resolve(ref)
    _texts(record["inputs"], f"{record['id']}.inputs", minimum=1)
    _texts(record["outputs"], f"{record['id']}.outputs", minimum=1)
    _texts(record["depends_on"], f"{record['id']}.depends_on")
    for dep in record["depends_on"]:
        _need(dep in LAYER_IDS and dep != record["id"], f"{record['id']}: bad dependency {dep!r}")
    _texts(record["permissions"], f"{record['id']}.permissions", minimum=1)
    for perm in record["permissions"]:
        _need(perm in PERMISSIONS, f"{record['id']}: unknown permission {perm!r}")
    _texts(record["skills"], f"{record['id']}.skills")
    _texts(record["tools"], f"{record['id']}.tools")
    _texts(record["agents"], f"{record['id']}.agents", minimum=1)
    for role in record["agents"]:
        _need(_ROLE_ID.match(role), f"{record['id']}: bad role id {role!r}")
    _texts(record["tests"], f"{record['id']}.tests", minimum=1)
    for test in record["tests"]:
        _need(_TEST.match(test), f"{record['id']}: test path {test!r}")
    _texts(record["scenarios"], f"{record['id']}.scenarios")
    for scenario in record["scenarios"]:
        _need(scenario in SCENARIOS, f"{record['id']}: unknown scenario {scenario!r}")
    _need(record["evidence"] == {"rule": "tests-pass"}, f"{record['id']}: evidence rule must be tests-pass")
    return record


def validate_layers(records, *, check_imports=False):
    _need(isinstance(records, list) and [r.get("id") for r in records] == list(LAYER_IDS),
          "layers: exactly L01..L20 in order")
    for record in records:
        validate_layer(record, check_imports=check_imports)
    # acyclic dependency graph (Kahn)
    deps = {r["id"]: set(r["depends_on"]) for r in records}
    ready = [lid for lid, d in deps.items() if not d]
    seen = 0
    while ready:
        lid = ready.pop()
        seen += 1
        for other, d in deps.items():
            if lid in d:
                d.discard(lid)
                if not d:
                    ready.append(other)
    _need(seen == len(records), "layers: dependency cycle")
    return records


def validate_engine(record, *, check_imports=False):
    _need(isinstance(record, dict), "engine: object required")
    allowed = {"id", "layer", "title", "entrypoint", "actions", "health", "supersedes"}
    _need(set(record) == allowed, f"engine {record.get('id')}: fields must be exactly {sorted(allowed)}")
    _need(isinstance(record["id"], str) and _ENGINE_ID.match(record["id"]), f"engine id: {record['id']!r}")
    _need(record["layer"] in LAYER_IDS, f"{record['id']}: layer {record['layer']!r}")
    _bilingual(record["title"], f"{record['id']}.title")
    for ref in (record["entrypoint"], record["health"]):
        _need(isinstance(ref, str) and _REF.match(ref), f"{record['id']}: reference {ref!r}")
        if check_imports:
            resolve(ref)
    actions = record["actions"]
    _need(isinstance(actions, dict) and 0 < len(actions) <= 32, f"{record['id']}: 1-32 actions")
    for name, spec in actions.items():
        _need(_ENGINE_ID.match(name), f"{record['id']}: action name {name!r}")
        _need(isinstance(spec, dict) and set(spec) == {"side_effect", "permissions", "summary"},
              f"{record['id']}.{name}: needs side_effect, permissions, summary")
        side_effect_rank(spec["side_effect"])
        _texts(spec["permissions"], f"{record['id']}.{name}.permissions", minimum=1)
        for perm in spec["permissions"]:
            _need(perm in PERMISSIONS, f"{record['id']}.{name}: unknown permission {perm!r}")
        _need(isinstance(spec["summary"], str) and spec["summary"].strip(), f"{record['id']}.{name}: summary")
    _texts(record["supersedes"], f"{record['id']}.supersedes")
    return record


def validate_engines(records, *, check_imports=False):
    _need(isinstance(records, list) and records, "engines: non-empty list")
    ids = [r.get("id") for r in records]
    _need(len(set(ids)) == len(ids), "engines: duplicate ids")
    for record in records:
        validate_engine(record, check_imports=check_imports)
    return records


def validate_grant(grant):
    _need(isinstance(grant, dict), "grant: object required")
    allowed = {"grant_id", "role", "engines", "paths", "max_side_effect", "expires_at", "approvals"}
    _need(set(grant) == allowed, f"grant: fields must be exactly {sorted(allowed)}")
    _need(isinstance(grant["grant_id"], str) and re.match(r"^g-[A-Za-z0-9-]{3,64}$", grant["grant_id"]), "grant_id")
    _need(isinstance(grant["role"], str) and _ROLE_ID.match(grant["role"]), "grant role")
    _need(isinstance(grant["engines"], dict), "grant engines: object")
    for engine, actions in grant["engines"].items():
        _need(_ENGINE_ID.match(engine), f"grant engine id {engine!r}")
        _texts(actions, f"grant {engine} actions", minimum=1)
    _texts(grant["paths"], "grant paths", maximum=32, limit=500)
    side_effect_rank(grant["max_side_effect"])
    _need(isinstance(grant["expires_at"], str) and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", grant["expires_at"]),
          "grant expires_at: ISO-8601 UTC (YYYY-MM-DDTHH:MM:SSZ)")
    _need(isinstance(grant["approvals"], list) and len(grant["approvals"]) <= 16, "grant approvals: list")
    for approval in grant["approvals"]:
        _need(isinstance(approval, dict) and set(approval) == {"side_effect", "engine", "action", "approved_by", "token_sha256"},
              "approval: side_effect, engine, action, approved_by, token_sha256")
        _need(approval["side_effect"] in GATED, "approval: only gated classes need approvals")
        _need(re.match(r"^[0-9a-f]{64}$", approval["token_sha256"] or ""), "approval token_sha256")
    return grant


def validate_receipt(receipt):
    _need(isinstance(receipt, dict), "receipt: object required")
    allowed = {"request_sha256", "result_sha256", "grant_id", "side_effect", "duration_ms", "at", "source_sha256"}
    _need(set(receipt) == allowed, f"receipt: fields must be exactly {sorted(allowed)}")
    for field in ("request_sha256", "result_sha256", "source_sha256"):
        _need(isinstance(receipt[field], str) and re.match(r"^[0-9a-f]{64}$", receipt[field]), f"receipt {field}")
    side_effect_rank(receipt["side_effect"])
    _need(isinstance(receipt["duration_ms"], int) and 0 <= receipt["duration_ms"] < 86_400_000, "receipt duration_ms")
    return receipt
