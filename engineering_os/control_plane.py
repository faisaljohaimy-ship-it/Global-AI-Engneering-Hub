"""Engineering Control Plane (layer L04): one registry and one governed entry for every engine.

``governance/engines.json`` lists every engine with its layer, entrypoint, health
probe and actions (each with an honest side-effect class and permissions).
``invoke`` is the only governed way in:

    validate request -> governor.check (BEFORE any work; fail closed; the denial is
    audited and nothing runs) -> adapter -> receipt (contracts.validate_receipt) ->
    usage row in the private economics ledger -> checkpoint in engineering memory
    when ctx names a task.

Payloads are data and never instructions: authorization comes only from the grant
and ``ctx['approval_token']``, never from payload text. No model, provider, network
or deployment call is made here. Standard library only. SPDX-License-Identifier: MIT.
"""
import copy
import datetime
import importlib.util
import pathlib
import time

from . import adapters, contracts
from .orchestration import CoordinationError, SLUG, canonical, load_json

if importlib.util.find_spec(f"{__package__}.governor") is None:
    governor = None  # fail closed: discovery and health work, every invoke is refused
else:
    from . import governor

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINES_PATH = ROOT / "governance/engines.json"
MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024 * 1024
CTX_FIELDS = frozenset({"state_dir", "task_id", "project", "host", "now", "approval_token", "environ"})
HOSTS = frozenset({"claude-code", "codex"})
DEFAULT_PROJECT = "gaie-control-plane"


class ControlPlaneError(ValueError):
    """A request was refused or could not be completed; nothing is claimed."""


class EngineFailure(ControlPlaneError):
    """An authorized engine raised; the attempt is audited and recorded as failed usage."""


# ---------------------------------------------------------------- registry and discovery

def load_registry(path=None, *, check_imports=False):
    """Read and validate the engine registry; a record that does not validate is never used."""
    path = pathlib.Path(ENGINES_PATH if path is None else path)
    if path.is_symlink() or not path.is_file():
        raise ControlPlaneError("engine registry missing")
    try:
        records = load_json(path.read_bytes())
    except (ValueError, CoordinationError) as error:
        raise ControlPlaneError(f"engine registry is not strict JSON: {error}") from None
    contracts.validate_engines(records, check_imports=check_imports)
    return records


def _index():
    return {record["id"]: record for record in load_registry()}


def _summary(record):
    return {"id": record["id"], "layer": record["layer"], "title": copy.deepcopy(record["title"]),
            "actions": {name: spec["side_effect"] for name, spec in record["actions"].items()},
            "side_effects": sorted({spec["side_effect"] for spec in record["actions"].values()},
                                   key=contracts.side_effect_rank),
            "entrypoint": record["entrypoint"], "health": record["health"]}


def engines():
    """Every registered engine: id, layer, title, actions with side effects."""
    return [_summary(record) for record in load_registry()]


def layers():
    """{layer id: [engine ids]} for every layer that owns at least one engine."""
    result = {}
    for record in load_registry():
        result.setdefault(record["layer"], []).append(record["id"])
    return dict(sorted(result.items()))


def describe(engine_id):
    """The full engine record plus the source files bound into its receipts."""
    record = _index().get(engine_id)
    if record is None:
        raise ControlPlaneError("unknown engine")
    sources = adapters.source_digests(engine_id)
    return {**copy.deepcopy(record), "sources": sources, "source_sha256": contracts.sha256(sources),
            "path_fields": {action: list(adapters.PATH_FIELDS.get((engine_id, action), ()))
                            for action in record["actions"]}}


def _probe(record):
    try:
        value = contracts.resolve(record["health"])()
    except Exception as error:  # a broken probe is reported, not raised
        return {"id": record["id"], "ok": False, "detail": f"{type(error).__name__}: {str(error)[:200]}"}
    if not isinstance(value, dict) or set(value) != {"ok", "detail"} or type(value["ok"]) is not bool \
            or not isinstance(value["detail"], str):
        return {"id": record["id"], "ok": False, "detail": "health probe returned a malformed result"}
    return {"id": record["id"], **value}


def health(engine_id=None):
    """Side-effect-free health of one engine, or of all with an overall flag."""
    index = _index()
    if engine_id is not None:
        if engine_id not in index:
            raise ControlPlaneError("unknown engine")
        return _probe(index[engine_id])
    rows = [_probe(record) for record in index.values()]
    return {"ok": all(row["ok"] for row in rows), "engines": rows,
            "governor_installed": governor is not None}


# ---------------------------------------------------------------- invocation

def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _context(ctx):
    if not isinstance(ctx, dict) or not set(ctx) <= CTX_FIELDS:
        raise ControlPlaneError(f"ctx fields must be within {sorted(CTX_FIELDS)}")
    state = ctx.get("state_dir")
    if not isinstance(state, (str, pathlib.Path)) or not str(state) or not pathlib.Path(state).is_absolute():
        raise ControlPlaneError("ctx['state_dir'] must be an absolute private directory")
    state = pathlib.Path(state)
    for ancestor in (state, *state.parents):
        if ancestor.is_symlink():
            raise ControlPlaneError("state directory must not pass through a symlink")
        marker = ancestor / ".git"
        if marker.is_file() or (marker.is_dir() and (marker / "HEAD").exists()):
            raise ControlPlaneError("state directory must be outside every Git repository")
    result = {**ctx, "state_dir": state}
    task = ctx.get("task_id")
    if task is not None and (not isinstance(task, str) or not SLUG.fullmatch(task)):
        raise ControlPlaneError("ctx['task_id'] must be a lowercase slug")
    project = ctx.get("project", DEFAULT_PROJECT)
    if not isinstance(project, str) or not SLUG.fullmatch(project):
        raise ControlPlaneError("ctx['project'] must be a lowercase slug")
    host = ctx.get("host", "claude-code")
    if host not in HOSTS:
        raise ControlPlaneError("ctx['host'] must be claude-code or codex")
    token = ctx.get("approval_token")
    if token is not None and (not isinstance(token, str) or not 16 <= len(token) <= 512):
        raise ControlPlaneError("ctx['approval_token'] must be 16-512 characters")
    environ = ctx.get("environ")
    if environ is not None and (not isinstance(environ, dict)
                                or not all(isinstance(k, str) and isinstance(v, str) for k, v in environ.items())):
        raise ControlPlaneError("ctx['environ'] must map text to text")
    return {**result, "project": project, "host": host}


def _digest(value, limit, label):
    try:
        data = canonical(value)
    except (TypeError, ValueError, RecursionError) as error:
        raise ControlPlaneError(f"{label} must be finite JSON data ({type(error).__name__})") from None
    if len(data) > limit:
        raise ControlPlaneError(f"{label} exceeds {limit} bytes")
    return contracts.sha256(data)


def _safe_id(value):
    return value if isinstance(value, str) and contracts._ENGINE_ID.match(value) and len(value) <= 64 else "<invalid>"


def _grant_id(grant):
    value = grant.get("grant_id") if isinstance(grant, dict) else None
    return value if isinstance(value, str) and len(value) <= 80 and value.startswith("g-") else None


def _audit(gov, ctx, event, engine, action, grant, *, reason, side_effect=None, request_sha256=None):
    # The governor's audit log records security decisions (allow | deny). A rejected request is a deny;
    # a run that errored after an allow keeps decision "allow" and says so in its reason.
    decision = "allow" if event in ("allow", "error") else "deny"
    text = f"run-error: {reason}" if event == "error" else str(reason)
    row = {"at": _now(), "event": event, "decision": decision, "engine": _safe_id(engine), "action": _safe_id(action),
           "grant_id": _grant_id(grant), "side_effect": side_effect, "request_sha256": request_sha256,
           "payload_sha256": request_sha256, "task_id": ctx.get("task_id"), "reason": text[:120],
           "source": "control-plane"}
    gov.audit(str(ctx["state_dir"]), row)


def _audit_quietly(gov, ctx, event, engine, action, grant, **fields):
    """Audit a refusal or error; the refusal stands even when its audit row cannot be written."""
    try:
        _audit(gov, ctx, event, engine, action, grant, **fields)
        return True
    except Exception:  # noqa: BLE001 - never let an audit fault turn a refusal into a run
        return False


def _reject(gov, ctx, engine, action, grant, reason, request_sha256=None):
    _audit_quietly(gov, ctx, "reject", engine, action, grant, reason=reason, request_sha256=request_sha256)
    raise ControlPlaneError(reason)


def _usage(ctx, engine, action, grant_id, side_effect, started, request_sha256, result_sha256, source_sha256, status):
    return {"schema_version": 1, "kind": "control-plane-invocation", "at": _now(), "engine": engine, "action": action,
            "status": status, "task_id": ctx.get("task_id"), "project": ctx["project"], "grant_id": grant_id,
            "side_effect": side_effect, "duration_ms": _elapsed(started), "request_sha256": request_sha256,
            "result_sha256": result_sha256, "source_sha256": source_sha256,
            "execution": "deterministic-local", "model_calls": 0, "provider_calls": 0,
            "input_tokens": 0, "output_tokens": 0, "charged_usd": "0",
            "basis": "no model or provider call is made by the control plane or its adapters"}


def _elapsed(started):
    return max(0, min(86_399_999, int((time.monotonic() - started) * 1000)))


def invoke(engine, action, payload, *, grant, ctx):
    """Run one engine action under a grant; returns {ok, engine, action, result, receipt}.

    Raises governor.GovernorDenied when the Security Governor refuses (nothing ran),
    ControlPlaneError for malformed or unknown requests (nothing ran) and
    EngineFailure when an authorized engine raised.
    """
    started = time.monotonic()
    ctx = _context(ctx)
    gov = governor
    if gov is None:
        raise ControlPlaneError("Security Governor (engineering_os.governor) is not installed; refusing every invocation")
    if not isinstance(payload, dict):
        _reject(gov, ctx, engine, action, grant, "payload must be an object")
    try:
        request_sha256 = _digest({"engine": engine, "action": action, "payload": payload}, MAX_PAYLOAD_BYTES, "payload")
    except ControlPlaneError as error:
        _reject(gov, ctx, engine, action, grant, str(error))
    try:
        record = _index().get(engine) if isinstance(engine, str) else None
    except (ControlPlaneError, contracts.ContractError) as error:
        _reject(gov, ctx, engine, action, grant, f"engine registry invalid: {error}", request_sha256)
    if record is None:
        _reject(gov, ctx, engine, action, grant, "unknown engine", request_sha256)
    if not isinstance(action, str) or action not in record["actions"]:
        _reject(gov, ctx, engine, action, grant, "unknown action", request_sha256)
    spec = copy.deepcopy(record["actions"][action])
    try:
        paths = adapters.request_paths(engine, action, payload)
    except adapters.AdapterError as error:
        _reject(gov, ctx, engine, action, grant, str(error), request_sha256)

    # Authorization strictly before any engine work. Only GovernorDenied or an explicit allow.
    refusal = {"side_effect": spec["side_effect"], "request_sha256": request_sha256}
    try:
        decision = gov.check(copy.deepcopy(grant), engine, action, copy.deepcopy(spec), paths=paths,
                             approval_token=ctx.get("approval_token"), now=ctx.get("now"))
    except gov.GovernorDenied as denial:
        _audit_quietly(gov, ctx, "deny", engine, action, grant, reason=getattr(denial, "reason", denial), **refusal)
        raise
    except Exception as error:  # any governor fault fails closed
        _audit_quietly(gov, ctx, "deny", engine, action, grant, reason=f"governor fault: {type(error).__name__}", **refusal)
        raise ControlPlaneError("Security Governor failed; nothing was run") from error
    if not isinstance(decision, dict) or decision.get("allowed") is not True \
            or decision.get("side_effect") != spec["side_effect"]:
        _audit_quietly(gov, ctx, "deny", engine, action, grant, reason="governor returned no explicit allow", **refusal)
        raise ControlPlaneError("Security Governor did not explicitly allow this action; nothing was run")
    grant_id = decision.get("grant_id")
    if not isinstance(grant_id, str) or grant_id != _grant_id(grant):
        _reject(gov, ctx, engine, action, grant, "governor decision names another grant", request_sha256)
    try:  # an allow that cannot be audited does not run
        _audit(gov, ctx, "allow", engine, action, grant, reason=decision.get("reason", "allowed"), **refusal)
    except Exception as error:
        raise ControlPlaneError("audit log unavailable; nothing was run") from error

    sources = adapters.source_digests(engine)
    source_sha256 = contracts.sha256(sources)
    engine_ctx = {"state_dir": ctx["state_dir"], "environ": ctx.get("environ"), "root": ROOT}
    try:
        result = contracts.resolve(record["entrypoint"])(action, copy.deepcopy(payload), engine_ctx)
        if not isinstance(result, dict):
            raise TypeError("engine result must be an object")
        result_sha256 = _digest(result, MAX_RESULT_BYTES, "engine result")
    except Exception as error:  # an authorized attempt is still audited and accounted
        message = f"{engine}.{action} failed: {type(error).__name__}: {str(error)[:300]}"
        # The audit row keeps the error class only; validator messages may quote payload data.
        _audit_quietly(gov, ctx, "error", engine, action, grant,
                       reason=f"{engine}.{action} failed: {type(error).__name__}", **refusal)
        try:
            adapters.append_usage(ctx, _usage(ctx, engine, action, grant_id, spec["side_effect"], started,
                                              request_sha256, None, source_sha256, "failed"))
        except Exception:  # noqa: BLE001 - the engine failure is the error to report
            pass
        raise EngineFailure(message) from error

    receipt = contracts.validate_receipt({
        "request_sha256": request_sha256, "result_sha256": result_sha256, "grant_id": grant_id,
        "side_effect": spec["side_effect"], "duration_ms": _elapsed(started), "at": _now(),
        "source_sha256": source_sha256})
    try:
        adapters.append_usage(ctx, _usage(ctx, engine, action, grant_id, spec["side_effect"], started,
                                          request_sha256, result_sha256, source_sha256, "ok"))
        if ctx.get("task_id"):
            adapters.record_checkpoint(ctx, task_id=ctx["task_id"], project=ctx["project"], host=ctx["host"],
                                       engine=engine, action=action, receipt=receipt)
    except Exception as error:  # the engine DID run: say so instead of returning an unaccounted result
        _audit_quietly(gov, ctx, "error", engine, action, grant,
                       reason=f"accounting failed after the engine ran: {type(error).__name__}", **refusal)
        raise ControlPlaneError(f"{engine}.{action} ran (result_sha256 {result_sha256}) but its usage or "
                                f"checkpoint could not be recorded: {type(error).__name__}") from error
    return {"ok": True, "engine": engine, "action": action, "result": result, "receipt": receipt}
