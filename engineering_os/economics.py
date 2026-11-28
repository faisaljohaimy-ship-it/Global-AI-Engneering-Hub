"""Offline engineering accounting over explicit, source-bound ledger metadata.

Input tokens include cached input; cached tokens are a priced subset, never added
again. Receipt digests are caller-supplied evidence references, not authenticated
provider invoices or proof of a real test run. Keep the underlying ledger private.
No subscription allowance is inferred, and no model or tool is invoked here.
SPDX-License-Identifier: MIT
"""

from decimal import Decimal, localcontext

from .model_router import _finite, _identifier, _integer, _money, select_model
from .orchestration import DIGEST, MAX_BYTES, canonical, sha

SCOPES = ("feature", "mvp", "enterprise")
CATEGORIES = ("human-review", "infrastructure", "maintenance", "rework")
LIMIT = 10000


class EconomicsError(ValueError):
    pass


def _object(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise EconomicsError("Unknown or missing ledger fields")
    return value


def _rows(value):
    if not isinstance(value, list) or len(value) > LIMIT:
        raise EconomicsError("Ledger collection exceeds bounded schema")
    return value


def _digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise EconomicsError("Evidence digest required")
    return value


def _count(value):
    return _integer(value, 0, 2**53 - 1)


def _charge(value, used_receipts):
    if value is None:
        return None
    _object(value, {"amount_usd", "receipt_sha256"})
    digest = _digest(value["receipt_sha256"])
    if digest in used_receipts:
        raise EconomicsError("Duplicate billed line-item receipt")
    used_receipts.add(digest)
    return _money(value["amount_usd"])


def _ratio(numerator, denominator):
    return None if denominator == 0 else str(Decimal(numerator) / denominator)


def _new_bucket():
    return {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
            "request_count": 0, "estimated_usd_known": Decimal(0),
            "estimated_usd_missing_items": 0, "charged_usd_known": Decimal(0),
            "charged_usd_missing_items": 0, "overhead_seconds": Decimal(0),
            "call_elapsed_seconds_sum": Decimal(0), "tasks": set(),
            "verified_tasks": set()}


def _add(bucket, *, task=None, verified=False, usage=None, estimated=None,
         charged=None, overhead_seconds=0):
    if task is not None:
        bucket["tasks"].add(task)
        if verified:
            bucket["verified_tasks"].add(task)
    if usage is not None:
        bucket["request_count"] += 1
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            bucket[key] += usage[key]
        bucket["call_elapsed_seconds_sum"] += Decimal(str(usage["ended_at"])) - Decimal(str(usage["started_at"]))
    bucket["overhead_seconds"] += Decimal(str(overhead_seconds))
    for kind, value in (("estimated", estimated), ("charged", charged)):
        if value is None:
            bucket[kind + "_usd_missing_items"] += 1
        else:
            bucket[kind + "_usd_known"] += value


def _finish(bucket):
    result = {key: value for key, value in bucket.items()
              if key not in {"tasks", "verified_tasks"}}
    for key in ("estimated_usd_known", "charged_usd_known", "overhead_seconds", "call_elapsed_seconds_sum"):
        result[key] = str(result[key])
    for kind in ("estimated", "charged"):
        result[kind + "_usd"] = (result[kind + "_usd_known"]
                                  if result[kind + "_usd_missing_items"] == 0 else None)
    result["total_tokens"] = bucket["input_tokens"] + bucket["output_tokens"]
    result["task_count"] = len(bucket["tasks"])
    result["verified_task_count"] = len(bucket["verified_tasks"])
    result["observed_tokens_per_verified_task"] = _ratio(result["total_tokens"], result["verified_task_count"])
    return result


def _summarize(ledger):
    _object(ledger, {"schema_version", "project", "actors", "tasks", "usage", "overheads"})
    if type(ledger["schema_version"]) is not int or ledger["schema_version"] != 1:
        raise EconomicsError("Unsupported ledger schema")
    project = _identifier(ledger["project"])
    actors, tasks, usage, overheads = {}, {}, _rows(ledger["usage"]), _rows(ledger["overheads"])
    for row in _rows(ledger["actors"]):
        _object(row, {"id", "role", "complete"})
        identity = _identifier(row["id"])
        if identity in actors or row["role"] not in {"coordinator", "worker"} or type(row["complete"]) is not bool:
            raise EconomicsError("Duplicate actor or malformed role/completeness")
        actors[identity] = row
    if not actors or not any(row["role"] == "coordinator" for row in actors.values()):
        raise EconomicsError("Coordinator accounting required")
    verification_receipts = set()
    for row in _rows(ledger["tasks"]):
        _object(row, {"id", "source_sha256", "scope", "verification"})
        identity = _identifier(row["id"])
        if identity in tasks:
            raise EconomicsError("Duplicate task")
        _digest(row["source_sha256"])
        _object(row["scope"], SCOPES)
        for value in row["scope"].values():
            if value is not None:
                _identifier(value)
        verification = row["verification"]
        if verification is not None:
            _object(verification, {"status", "source_sha256", "receipt_sha256"})
            if verification["status"] != "passed" or verification["source_sha256"] != row["source_sha256"]:
                raise EconomicsError("Verification must pass at the task source digest")
            receipt = _digest(verification["receipt_sha256"])
            if receipt in verification_receipts:
                raise EconomicsError("Verification receipt cannot count multiple tasks")
            verification_receipts.add(receipt)
        tasks[identity] = row

    total, by_role, by_actor = _new_bucket(), {}, {}
    by_scope = {kind: {} for kind in SCOPES}
    unallocated = {kind: _new_bucket() for kind in SCOPES}
    by_tool, by_model, by_category = {}, {}, {}
    seen_ids, usage_receipts, charged_receipts, seen_actors = set(), set(), set(), set()
    span_start, span_end = None, None
    approximate = False
    role_seconds = {"coordinator": Decimal(0), "worker": Decimal(0)}

    # Empty completed tasks still count in denominators; failed/retried work and
    # unassigned coordinator work remain in the whole-ledger numerator.
    for identity, row in tasks.items():
        total["tasks"].add(identity)
        if row["verification"] is not None:
            total["verified_tasks"].add(identity)
        for kind, scope in row["scope"].items():
            bucket = unallocated[kind] if scope is None else by_scope[kind].setdefault(scope, _new_bucket())
            bucket["tasks"].add(identity)
            if row["verification"] is not None:
                bucket["verified_tasks"].add(identity)

    def task_for(row):
        identity = row["task"]
        if identity is None:
            return None
        if not isinstance(identity, str) or identity not in tasks:
            raise EconomicsError("Unknown task in accounting item")
        return tasks[identity]

    def distribute(row, buckets, **values):
        task = task_for(row)
        options = {"task": None if task is None else task["id"],
                   "verified": task is not None and task["verification"] is not None, **values}
        for bucket in [total, *buckets]:
            _add(bucket, **options)
        for kind in SCOPES:
            scope = None if task is None else task["scope"][kind]
            target = unallocated[kind] if scope is None else by_scope[kind].setdefault(scope, _new_bucket())
            _add(target, **options)

    for row in usage:
        _object(row, {"id", "actor", "task", "attempt", "model", "tool", "source", "receipt_sha256",
                      "started_at", "ended_at", "input_tokens", "cached_input_tokens", "output_tokens", "pricing", "charge"})
        identity = _identifier(row["id"])
        receipt = _digest(row["receipt_sha256"])
        if identity in seen_ids or receipt in usage_receipts:
            raise EconomicsError("Duplicate request identity or usage receipt")
        seen_ids.add(identity)
        usage_receipts.add(receipt)
        _integer(row["attempt"], 1, 1000000)
        actor_id = _identifier(row["actor"])
        if actor_id not in actors:
            raise EconomicsError("Unknown usage actor")
        seen_actors.add(actor_id)
        if row["source"] not in {"provider-reported", "proxy"}:
            raise EconomicsError("Usage provenance required")
        approximate |= row["source"] == "proxy"
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            _count(row[key])
        if row["cached_input_tokens"] > row["input_tokens"]:
            raise EconomicsError("Cached input exceeds inclusive input total")
        started, ended = _finite(row["started_at"]), _finite(row["ended_at"])
        if ended < started:
            raise EconomicsError("Usage interval ends before it starts")
        span_start = started if span_start is None else min(span_start, started)
        span_end = ended if span_end is None else max(span_end, ended)
        role = actors[actor_id]["role"]
        role_seconds[role] += Decimal(str(ended)) - Decimal(str(started))
        model, tool = _identifier(row["model"]), _identifier(row["tool"])
        estimate = None
        if row["pricing"] is not None:
            pricing = _object(row["pricing"], {"input_per_million_usd", "cached_input_per_million_usd", "output_per_million_usd"})
            regular, cached, output = (_money(pricing[name]) for name in
                                      ("input_per_million_usd", "cached_input_per_million_usd", "output_per_million_usd"))
            estimate = ((row["input_tokens"] - row["cached_input_tokens"]) * regular
                        + row["cached_input_tokens"] * cached + row["output_tokens"] * output) / Decimal(1000000)
        distribute(row, [by_role.setdefault(role, _new_bucket()), by_actor.setdefault(actor_id, _new_bucket()),
                         by_model.setdefault(model, _new_bucket()), by_tool.setdefault(tool, _new_bucket())],
                   usage=row, estimated=estimate, charged=_charge(row["charge"], charged_receipts))

    for row in overheads:
        _object(row, {"id", "task", "category", "seconds", "estimate_usd", "charge"})
        identity = _identifier(row["id"])
        if identity in seen_ids or row["category"] not in CATEGORIES:
            raise EconomicsError("Duplicate item identity or unknown overhead category")
        seen_ids.add(identity)
        seconds = _finite(row["seconds"])
        estimate = None if row["estimate_usd"] is None else _money(row["estimate_usd"])
        distribute(row, [by_category.setdefault(row["category"], _new_bucket())],
                   overhead_seconds=seconds, estimated=estimate, charged=_charge(row["charge"], charged_receipts))

    missing_actors = sorted(set(actors) - seen_actors)
    incomplete_actors = sorted(identity for identity, row in actors.items() if not row["complete"])
    complete = not missing_actors and not incomplete_actors
    result = _finish(total)
    result["tokens_per_verified_task"] = result["observed_tokens_per_verified_task"] if complete and not approximate else None
    for kind in ("estimated", "charged"):
        result["observed_" + kind + "_usd"] = result[kind + "_usd"]
        if not complete:
            result[kind + "_usd"] = None
    result["scope"] = "all recorded coordinator and worker usage, including retries and unverified work"
    notes = ["Receipt references are supplied assertions; review original evidence independently.",
             "USD estimates use supplied rates; charges use supplied billed line items. Neither infers subscription allowance.",
             "Scope groups overlap across levels and are not additive; unattributed coordinator/overhead costs remain unallocated.",
             "Call elapsed sums include overlap; observed wall span is not full development time or CPU time."]
    if approximate:
        notes.append("Proxy tokens are approximate; exact tokens per verified task is unavailable.")
    if not complete:
        notes.append("Actor accounting is incomplete; observed totals are lower bounds, not whole-project measurements.")
    recommendations = []
    if not complete:
        recommendations.append("Collect final usage for every declared actor before comparing runs.")
    if result["estimated_usd_missing_items"]:
        recommendations.append("Supply reviewed explicit rates or overhead estimates before publishing a total cost estimate.")
    if result["charged_usd_missing_items"]:
        recommendations.append("Reconcile each item with a billed line-item receipt before reporting actual monetary cost.")
    if not result["verified_task_count"]:
        recommendations.append("Obtain source-bound passed test receipts before reporting verified-task efficiency.")
    return {"schema_version": 1, "project": project, "ledger_sha256": sha(ledger),
            "accounting_complete": complete, "missing_usage_actors": missing_actors,
            "incomplete_actors": incomplete_actors, "token_basis": "proxy-present" if approximate else "provider-reported",
            "summary": result, "by_role": {key: _finish(value) for key, value in sorted(by_role.items())},
            "by_actor": {key: _finish(value) for key, value in sorted(by_actor.items())},
            "by_scope": {kind: {key: _finish(value) for key, value in sorted(groups.items())} for kind, groups in by_scope.items()},
            "unallocated_by_scope": {kind: _finish(value) for kind, value in unallocated.items()},
            "by_model": {key: _finish(value) for key, value in sorted(by_model.items())},
            "by_tool": {key: _finish(value) for key, value in sorted(by_tool.items())},
            "overheads_by_category": {key: _finish(value) for key, value in sorted(by_category.items())},
            "time": {"observed_call_wall_span_seconds": None if span_start is None else str(Decimal(str(span_end)) - Decimal(str(span_start))),
                     "coordinator_call_seconds_sum": str(role_seconds["coordinator"]),
                     "worker_call_seconds_sum": str(role_seconds["worker"]),
                     "full_development_time_seconds": None},
            "recommendations": recommendations, "notes": notes,
            "provider_calls": 0, "subscription_allowance": None}


def summarize(ledger):
    """Validate and aggregate bounded metadata; never load a prompt or execute a tool.

    A task verification reference binds to its exact source digest. It does not
    authenticate the originating tester. Each completed task needs a distinct
    per-task verification receipt; shared test suites can issue task-specific
    receipts. Completed actor declarations are likewise
    caller assertions and should be reconciled with trusted host exports.
    """
    try:
        if len(canonical(ledger)) > MAX_BYTES:
            raise EconomicsError("Ledger exceeds bounded byte size")
        with localcontext() as context:
            context.prec = 64
            return _summarize(ledger)
    except (TypeError, KeyError, ArithmeticError, RecursionError, ValueError) as error:
        if isinstance(error, EconomicsError):
            raise
        raise EconomicsError("Malformed engineering accounting metadata") from error


def recommend_model(registry, request, evidence=None, *, environ=None, now=None):
    """Reuse the existing gated model router; selection is not usage or spending."""
    return select_model(registry, request, evidence, environ=environ, now=now)
