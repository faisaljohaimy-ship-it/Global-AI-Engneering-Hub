"""Deterministic, fail-closed model selection; no provider invocation or spending.

Operational/project/pricing/quality receipts must come from an independently
trusted evaluator. This selector validates receipts; their presence is not proof
that an evaluator, credential, or provider exists. Routing does not reserve quota.
"""

import argparse
import decimal
import json
import math
import os
import re
import sys
import time

from .orchestration import DIGEST, SLUG, _text, canonical, load_json, sha

PHASES = {"DISCOVERED", "REVIEWED", "APPROVED", "INSTALLED", "OPERATIONAL", "TESTED", "PROJECT_VERIFIED"}
PRIVACY = {"public", "internal", "confidential", "restricted"}
PROVIDERS = {"openai", "anthropic", "google", "open-source", "local", "gateway"}


class RoutingError(ValueError):
    pass


def _integer(value, low=0, high=2**31-1):
    if type(value) is not int or not low <= value <= high:
        raise RoutingError("Invalid integer constraint")
    return value


def _finite(value, low=0, high=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value):
        raise RoutingError("Invalid finite metric")
    return value


def _money(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, decimal.Decimal)):
        raise RoutingError("Invalid monetary constraint")
    try:
        parsed = decimal.Decimal(str(value))
    except decimal.InvalidOperation as error:
        raise RoutingError("Invalid monetary constraint") from error
    if not parsed.is_finite() or parsed < 0 or parsed > decimal.Decimal("1000000000") or parsed.as_tuple().exponent < -12:
        raise RoutingError("Invalid monetary constraint")
    return parsed


def _identifier(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise RoutingError("Invalid routing identifier")
    return _text(value, 80)


def _permissions(values):
    if not isinstance(values, list) or len(values) > 50:
        raise RoutingError("Invalid permission set")
    if any(not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9:_/-]{0,79}", value) for value in values):
        raise RoutingError("Invalid permission")
    if len(values) != len(set(values)):
        raise RoutingError("Duplicate permission")
    return set(values)


def validate_registry(registry):
    if not isinstance(registry, dict) or registry.get("schema_version") != 1 or not isinstance(registry.get("models"), list):
        raise RoutingError("Invalid model registry")
    seen = set()
    for row in registry["models"]:
        if not isinstance(row, dict):
            raise RoutingError("Invalid model entry")
        identifier = _identifier(row.get("id"))
        if identifier in seen or not isinstance(row.get("status"), str) or not isinstance(row.get("provider"), str) or row["status"] not in PHASES or row["provider"] not in PROVIDERS:
            raise RoutingError("Duplicate model or unknown status/provider")
        allowed = {"id", "provider", "status", "model_id", "revision", "tasks", "max_complexity", "context_tokens", "credential_env", "runtime_sha256", "reviews", "pricing", "notes"}
        if not set(row) <= allowed:
            raise RoutingError("Unknown model fields; keep credentials out of the registry")
        seen.add(identifier)
    return True


def select_model(registry, request, evidence=None, *, environ=None, now=None):
    """Select only a model meeting explicit policy and fresh project evidence.

    Returns a blocked decision when no model is eligible; malformed constraints
    raise RoutingError. No API keys or raw prompts are accepted or returned.
    """
    validate_registry(registry)
    fields = {"project", "task", "complexity", "input_tokens", "output_tokens", "privacy", "permissions", "max_cost_usd", "min_quality", "max_latency_ms", "weights"}
    required = fields - {"weights"}
    if not isinstance(request, dict) or not required <= set(request) or not set(request) <= fields:
        raise RoutingError("Unknown or missing request fields; prompts and secrets are not routing metadata")
    project, task = _identifier(request["project"]), _identifier(request["task"])
    complexity = _integer(request["complexity"], 1, 5)
    input_tokens, output_tokens = _integer(request["input_tokens"]), _integer(request["output_tokens"], 1)
    if not isinstance(request["privacy"], str) or request["privacy"] not in PRIVACY:
        raise RoutingError("Unknown data privacy level")
    permissions = _permissions(request["permissions"])
    budget, minimum_quality = _money(request["max_cost_usd"]), _finite(request["min_quality"], 0, 1)
    maximum_latency = _finite(request["max_latency_ms"], 1)
    weights = request.get("weights", {"quality": 0.6, "speed": 0.2, "cost": 0.2})
    if not isinstance(weights, dict) or set(weights) != {"quality", "speed", "cost"}:
        raise RoutingError("Invalid ranking weights")
    weights = {key: _finite(value, 0, 1) for key, value in weights.items()}
    if abs(sum(weights.values()) - 1) > 1e-9:
        raise RoutingError("Ranking weights must sum to one")
    now = _finite(time.time() if now is None else now)
    age = _finite(registry.get("evidence_max_age_seconds", 3600), 1, 86400)
    environ = os.environ if environ is None else environ
    if evidence is None:
        evidence = {"schema_version": 1, "project": project, "models": {}}
    if not isinstance(evidence, dict) or set(evidence) != {"schema_version", "project", "models"} or evidence["schema_version"] != 1 or evidence["project"] != project or not isinstance(evidence["models"], dict):
        raise RoutingError("Project-specific evidence required")
    choices, rejected = [], {}
    for row in registry["models"]:
        identifier = row["id"]
        reasons = []
        if row["status"] != "PROJECT_VERIFIED":
            rejected[identifier] = ["not_project_verified"]
            continue
        try:
            revision = row.get("revision")
            if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", revision) or row.get("reviews") != {"license": "approved", "security": "approved", "commercial": "approved"}:
                reasons.append("unreviewed_or_unpinned")
            model_id = row.get("model_id")
            if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,159}", model_id) or re.search(r"(?:^|[-:/_.])(?:latest|auto|default)(?:$|[-:/_.])", model_id, re.I):
                reasons.append("missing_exact_model_identifier")
            else:
                _text(model_id, 160)
            tasks = row.get("tasks")
            if not isinstance(tasks, list) or task not in tasks or complexity > _integer(row.get("max_complexity"), 1, 5):
                reasons.append("task_or_complexity_mismatch")
            if input_tokens + output_tokens > _integer(row.get("context_tokens"), 1):
                reasons.append("context_capacity")
            receipt = evidence["models"].get(identifier)
            receipt_fields = {"revision", "operational", "tested", "project_verified", "at", "receipt_sha256", "quality", "latency_ms", "remaining_requests", "remaining_tokens", "permissions", "privacy", "runtime_sha256", "cost_approved", "free_allowance_verified"}
            if not isinstance(receipt, dict) or set(receipt) != receipt_fields:
                reasons.append("missing_or_malformed_operational_evidence")
            else:
                at = _finite(receipt["at"])
                if receipt["revision"] != revision or any(receipt[key] is not True for key in ["operational", "tested", "project_verified"]):
                    reasons.append("runtime_not_verified_at_pin")
                if at > now or now - at > age or not isinstance(receipt["receipt_sha256"], str) or not DIGEST.fullmatch(receipt["receipt_sha256"]):
                    reasons.append("stale_or_invalid_evidence")
                if not permissions <= _permissions(receipt["permissions"]):
                    reasons.append("permission_denied")
                if not isinstance(receipt["privacy"], list) or not set(receipt["privacy"]) <= PRIVACY or request["privacy"] not in receipt["privacy"]:
                    reasons.append("privacy_denied")
                if _integer(receipt["remaining_requests"]) < 1 or _integer(receipt["remaining_tokens"]) < input_tokens + output_tokens:
                    reasons.append("usage_limit")
                quality, latency = _finite(receipt["quality"], 0, 1), _finite(receipt["latency_ms"])
                if quality < minimum_quality:
                    reasons.append("quality_floor")
                if latency > maximum_latency:
                    reasons.append("latency_budget")
                if row["provider"] == "local":
                    expected = row.get("runtime_sha256")
                    if not isinstance(expected, str) or not DIGEST.fullmatch(expected) or receipt["runtime_sha256"] != expected:
                        reasons.append("local_runtime_unverified")
                else:
                    key = row.get("credential_env")
                    if not isinstance(key, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", key) or not isinstance(environ.get(key), str) or not environ[key].strip():
                        reasons.append("credential_unavailable")
                pricing = row.get("pricing")
                if not isinstance(pricing, dict) or set(pricing) != {"input_per_million_usd", "output_per_million_usd", "verified_at"}:
                    reasons.append("pricing_unverified")
                else:
                    pricing_at = _finite(pricing["verified_at"])
                    if pricing_at > now or now - pricing_at > age or receipt["cost_approved"] is not True:
                        reasons.append("pricing_or_cost_authority_expired")
                    with decimal.localcontext() as context:
                        context.prec = 64
                        estimated = (_money(pricing["input_per_million_usd"]) * input_tokens + _money(pricing["output_per_million_usd"]) * output_tokens) / decimal.Decimal(1000000)
                    if estimated > budget:
                        reasons.append("cost_budget")
                    if row["provider"] != "local" and estimated == 0 and receipt["free_allowance_verified"] is not True:
                        reasons.append("free_allowance_unverified")
                    if not reasons:
                        score = weights["quality"] * quality + weights["speed"] / (1 + latency/1000) + weights["cost"] / (1 + float(estimated))
                        choices.append({"id": identifier, "model_id": model_id, "provider": row["provider"], "revision": revision,
                                        "estimated_cost_usd": str(estimated), "ranking_score": score,
                                        "evidence_digest": sha(receipt)})
        except (ValueError, TypeError, KeyError, decimal.InvalidOperation):
            reasons.append("malformed_policy_or_evidence")
        if reasons:
            rejected[identifier] = sorted(set(reasons))
    choices.sort(key=lambda choice: (-choice["ranking_score"], decimal.Decimal(choice["estimated_cost_usd"]), choice["id"]))
    selected = choices[0] if choices else None
    return {"schema_version": 1, "decision": "eligible" if selected else "blocked", "selected": selected,
            "rejected": rejected, "provider_calls": 0, "quota_reserved": False,
            "note": "Eligibility uses supplied evaluator receipts, not live provider execution. Revalidate/reserve quota before invocation."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--evidence")
    args = parser.parse_args(argv)
    try:
        def read(path):
            with open(path, "rb") as stream:
                data = stream.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise RoutingError("Oversized routing metadata")
            return load_json(data)
        result = select_model(read(args.registry), read(args.request), read(args.evidence) if args.evidence else None)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if result["selected"] else 2
    except (OSError, ValueError, KeyError, TypeError):
        print("Model routing rejected malformed policy/request/evidence.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
