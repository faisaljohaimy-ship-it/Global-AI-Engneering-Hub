"""Run scoped local stages for an already verified upstream master route.

The caller supplies the route from the trusted approval gate and a callback
restricted to its configured project scope. Route and approval metadata are
server state, never fields in an MCP request. Preview has no engine side effects.
SPDX-License-Identifier: MIT.
"""

import re

from .orchestration import DIGEST, _slug, sha


class MasterWorkflowError(ValueError):
    """A request falls outside the approved local workflow contract."""


PROMPTS = {
    "MASTER_BUILD": "prompts/MASTER_BUILD.md",
    "MASTER_UPGRADE": "prompts/MASTER_UPGRADE.md",
}
SHARED = (
    ("reasoning", "reasoning-plan"),
    ("memory", "memory-search"),
    ("economics", "economics"),
    ("cinematic", "cinematic"),
)
SPECIFIC = {
    "MASTER_BUILD": (("factory_plan", "factory-plan"), ("generation", "factory-generate")),
    "MASTER_UPGRADE": (("factory_evaluation", "factory-evaluate"), ("repair", "healing-repair")),
}
REPOSITORY = re.compile(r"https://github\.com/[a-zA-Z0-9][a-zA-Z0-9-]*/[a-zA-Z0-9_.-]+")


def _request(value):
    if (not isinstance(value, dict)
            or set(value) != {"schema_version", "project", "mode", "inputs"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["mode"] not in ("preview", "execute")
            or not isinstance(value["inputs"], dict)):
        raise MasterWorkflowError("Invalid master workflow request")
    _slug(value["project"])
    return value["project"], value["mode"], value["inputs"]


def _route_blockers(route, project):
    engine = route.get("engine")
    if not isinstance(engine, str) or engine not in PROMPTS:
        return ["unsupported-master-engine"]
    if route.get("prompt") != PROMPTS[engine] or route.get("read_only") is not False:
        return ["invalid-master-route"]
    prohibited = route.get("prohibited", [])
    if not isinstance(prohibited, list) or any(not isinstance(verb, str) for verb in prohibited):
        return ["invalid-master-route"]
    if engine == "MASTER_BUILD":
        if route.get("intent") != "build" or route.get("target_scope") != "new-project" or route.get("targets") != []:
            return ["expected-local-new-project"]
        if "build" in prohibited:
            return ["upstream-prohibits-local-profile"]
    else:
        if (route.get("intent") not in ("upgrade", "repair")
                or route.get("scope") not in ("comprehensive", "focused", "self-healing")):
            return ["unsupported-upgrade-profile"]
        if any(verb in prohibited for verb in ("upgrade", "repair")):
            return ["upstream-prohibits-local-profile"]
        targets = route.get("targets")
        if (route.get("target_scope") != "single-project" or not isinstance(targets, list)
                or len(targets) != 1 or not isinstance(targets[0], dict)
                or targets[0].get("id") != project):
            return ["expected-one-configured-project"]
        target = targets[0]
        repository = target.get("repository")
        if not isinstance(repository, str) or not REPOSITORY.fullmatch(repository) or repository.rsplit("/", 1)[-1] in {".", ".."}:
            return ["invalid-project-repository"]
        if target.get("workspace_matches") is not True:
            return ["workspace-origin-unverified"]
        if route.get("scope") == "focused":
            focus = route.get("focus")
            if not isinstance(focus, list) or not any(item in ("database", "defects") for item in focus):
                return ["unsupported-upgrade-profile"]
    if route.get("write_allowed") is not True:
        return ["upstream-route-denied-execution"]
    return []


def _bound_inputs(inputs, mappings, project):
    supported = dict(mappings)
    if set(inputs) - supported.keys():
        raise MasterWorkflowError("Unknown or out-of-profile stage input")
    for name, payload in inputs.items():
        if not isinstance(payload, dict):
            raise MasterWorkflowError("Each stage input must be an object")
        if name == "cinematic":
            continue  # This request addresses the public motion inventory.
        if name == "factory_evaluation":
            plan = payload.get("plan")
            payload = plan.get("request") if isinstance(plan, dict) else None
        if not isinstance(payload, dict) or payload.get("project") != project:
            raise MasterWorkflowError("Stage input targets another project")


def _stage_summary(operation, payload, value, project):
    if operation == "memory-search":
        if not isinstance(value, list):
            raise MasterWorkflowError("Memory search returned invalid evidence")
        return {"matches": len(value)}
    if not isinstance(value, dict):
        raise MasterWorkflowError("Stage returned invalid evidence")
    if (value.get("provider_calls", 0) != 0 or value.get("production_mutations", 0) != 0
            or value.get("deployment_authorized", False) is not False):
        raise MasterWorkflowError("Stage exceeded local workflow authority")
    if operation == "architecture":
        layers = value.get("layers")
        if (not isinstance(layers, list) or any(not isinstance(layer, dict) for layer in layers)
                or [layer.get("id") for layer in layers] != [f"L{i:02d}" for i in range(1, 21)]):
            raise MasterWorkflowError("Expected the twenty-layer contract")
        return {"layer_count": len(layers)}
    if operation == "reasoning-plan":
        if (value.get("project") != project or value.get("status") != "provisional"
                or value.get("request_sha256") != sha(payload) or not _bound_digest(value, "plan_sha256")):
            raise MasterWorkflowError("Reasoning did not find a feasible local plan")
        return {"plan_sha256": value["plan_sha256"], "status": value["status"]}
    if operation == "factory-plan":
        from .factory import _request as normalize_requirements

        if (value["request"]["project"] != project
                or value.get("request_sha256") != sha(normalize_requirements(payload))
                or not _bound_digest(value, "plan_sha256")):
            raise MasterWorkflowError("Factory plan does not match these requirements")
        return {"plan_sha256": value["plan_sha256"], "stage_count": len(value["stages"])}
    if operation == "factory-evaluate":
        if value.get("project") != project or value.get("delivery_review_ready") is not True:
            raise MasterWorkflowError("Existing artifact evidence has incomplete stages")
        return {"plan_sha256": value["plan_sha256"], "verified_count": value["verified_count"]}
    if operation == "factory-generate":
        from .factory_generate import _request as normalize_generation

        verification = value.get("verification")
        if (value.get("project") != project or value.get("profile") != "private-sqlite-crud"
                or value.get("source_revision") != payload["source_revision"]
                or value.get("request_sha256") != sha(normalize_generation(payload))
                or not isinstance(verification, dict) or verification.get("status") != "passed"
                or not _bound_digest(value, "manifest_sha256")):
            raise MasterWorkflowError("Generated output lacks a verified local manifest")
        return {"manifest_sha256": value["manifest_sha256"], "profile": value["profile"],
                "checks": verification["checks"]}
    if operation in ("healing-repair", "healing-replay"):
        original = payload if operation == "healing-repair" else payload["request"]
        if (value.get("project") != project or value.get("status") not in ("healthy", "repair-verified")
                or value.get("baseline_sha256") != original["settings_sha256"]
                or value.get("runtime_tested") is not True or value.get("rollback_verified") is not True
                or value.get("production_mutations") != 0 or value.get("deployment_allowed") is not False
                or not _bound_digest(value, "receipt_sha256")):
            raise MasterWorkflowError("SQLite repair or rollback evidence failed")
        summary = {"receipt_sha256": value["receipt_sha256"], "status": value["status"],
                   "rollback_verified": True}
        if operation == "healing-repair" and value["status"] == "repair-verified":
            summary["candidate_json"] = value["candidate_json"]
            summary["candidate_sha256"] = value["candidate_sha256"]
        return summary
    if operation == "economics":
        if type(value["accounting_complete"]) is not bool:
            raise MasterWorkflowError("Invalid economics evidence")
        return {"accounting_complete": value["accounting_complete"]}
    if operation == "cinematic":
        return {"verified_for_requested_browsers": value["operational_for_requested_browsers_count"]}
    raise MasterWorkflowError("Unsupported engine stage")


def _bound_digest(value, key):
    digest = value.get(key)
    return (isinstance(digest, str) and DIGEST.fullmatch(digest) is not None
            and digest == sha({field: item for field, item in value.items() if field != key}))


def run_master(route, request, *, approval_revision, invoke, available):
    """Preview or execute a fixed local profile after upstream source approval.

    The callback must dispatch through the same per-project policy as individual
    MCP calls. No command, provider, repository write or release operation is
    accepted. Build publishes its verified private output at the last stage.
    Upgrade reproduces and replays a SQLite repair in disposable storage.
    """
    project, mode, inputs = _request(request)
    approval = route.get("master_approval") if isinstance(route, dict) else None
    if (not isinstance(approval_revision, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", approval_revision)
            or not isinstance(approval, dict) or approval.get("revision") != approval_revision
            or type(route.get("schema_version")) is not int or route["schema_version"] != 1):
        raise MasterWorkflowError("A verified, revision-bound master route is required")

    engine = route.get("engine")
    report = {"schema_version": 1, "project": project, "mode": mode,
              "engine": engine if isinstance(engine, str) and engine in PROMPTS else None,
              "approval_revision": approval_revision, "route_sha256": sha(route),
              "request_sha256": sha(request), "operations": [], "stages": [],
              "provider_calls": 0, "production_mutations": 0,
              "deployment_authorized": False, "requires_review_before_adoption": True}
    if route.get("status") != "routed":
        report.update(status="needs-clarification", blockers=["upstream-route-unresolved"])
    else:
        blockers = _route_blockers(route, project)
        if report["engine"] is None:
            report.update(status="blocked", blockers=blockers)
        else:
            _prepare(report, route, inputs, blockers, invoke, frozenset(available))
    report["workflow_sha256"] = sha(report)
    return report


def _prepare(report, route, inputs, blockers, invoke, enabled):
    engine = report["engine"]
    mappings = (*SHARED, *SPECIFIC[engine])
    _bound_inputs(inputs, mappings, report["project"])
    primary_input, primary_operation = SPECIFIC[engine][-1]
    stages = [("architecture", {})] + [(operation, inputs[name]) for name, operation in mappings[:-1] if name in inputs]
    stages.append((primary_operation, inputs.get(primary_input)))
    if engine == "MASTER_UPGRADE":
        stages.append(("healing-replay", None))
    report["operations"] = [operation for operation, _ in stages]
    report["upstream_gates"] = route.get("gates", [])
    report["missing_inputs"] = [] if primary_input in inputs else [primary_input]
    report["unavailable_operations"] = [operation for operation, _ in stages if operation not in enabled]
    report["blockers"] = blockers
    if report["mode"] == "preview":
        report["status"] = "preview"
        return
    if report["missing_inputs"]:
        blockers.append("missing-structured-input")
    if report["unavailable_operations"]:
        blockers.append("operation-not-authorized")
    if blockers:
        report["status"] = "blocked"
        return
    _execute(report, stages, invoke)


def _execute(report, stages, invoke):
    repair = None
    pending = []
    for operation, payload in stages:
        if operation == "healing-replay":
            payload = {"request": repair[0], "report": repair[1]}
        row = {"operation": operation, "input_sha256": sha(payload)}
        try:
            value = invoke(operation, payload)
            summary = _stage_summary(operation, payload, value, report["project"])
            if operation == "healing-repair":
                repair = payload, value
            if operation == "healing-replay" and value["receipt_sha256"] != repair[1]["receipt_sha256"]:
                raise MasterWorkflowError("SQLite replay returned a different receipt")
            status = "completed"
            if operation == "reasoning-plan":
                status = "provisional"
            elif operation == "factory-plan":
                status = "planned"
            elif operation == "economics" and not summary["accounting_complete"]:
                status = "incomplete"
            elif operation == "cinematic" and not summary["verified_for_requested_browsers"]:
                status = "evidence-unavailable"
            if status != "completed":
                pending.append(operation)
            row.update(status=status, result_sha256=sha(value), summary=summary)
        except (ValueError, OSError, KeyError, TypeError, RecursionError, SyntaxError, OverflowError):
            row["status"] = "failed"
            report["stages"].append(row)
            report.update(status="blocked", blockers=["local-stage-failed"])
            return
        report["stages"].append(row)
    report.update(status="review-pending" if pending else "local-verified",
                  local_profile_verified=True, pending_review_operations=pending)
