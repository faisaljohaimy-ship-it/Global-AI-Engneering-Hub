"""Central agent-team policy (GAIE layer L03): which specialist roles staff a build or an upgrade,
and how many of them may run at the same moment on a host.

`governance/policies/agent-team.json` names the twenty registry roles, the roster per intent, the
session limit and the concurrency rule, with the evidence file behind every number. This module
loads it strictly (duplicate keys, unknown fields and out-of-range numbers are refused), resolves
the team and the concurrency for an intent and a host, and checks a plan's staffing: every roster
role is staffed or listed as omitted with a reason, never more than the session limit, never an
unknown role, never a reviewer that produced the work it reviews.

    load_policy(path=None) -> validated policy
    validate(policy, registry=None) -> policy (AgentTeamError when it breaks a rule)
    team_for(intent, cpus=None) -> {"roles", "omitted", "policy_version", "policy_sha256", "concurrency"}
    check_staffing(plan, intent=None) -> staffed and omitted roles with reasons
    role_card(role_id) -> owned paths, default grant and reviewer of one role

Standalone and standard library only: it is vendored beside the router into other projects. It
finds its policy and the role registry beside itself (vendored layout) or under the hub root, and
imports nothing else from engineering_os. A team here is a staffing plan: nothing in this module
starts an agent, calls a model or runs a command.
SPDX-License-Identifier: MIT
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
POLICY_FILE = "governance/policies/agent-team.json"
REGISTRY_FILE = "governance/agent-roles.json"
IMPLEMENTATION = "engineering_os/agent_team.py"
# Measured host limit (swarm/phase2/README.md finding 2): editing the policy can lower it, never raise it.
HARD_SESSION_LIMIT = 20
MAX_BYTES = 1024 * 1024
RUNNERS = ("agent", "workflow")
SUPPORTS = ("session_limit", "agents_per_cpu", "start", "workflow_runner")
EVIDENCE_KINDS = ("measured", "policy", "documented")
READS = ("session_limit", "concurrency.agents_per_cpu", "concurrency.start", "concurrency.workflow_runner",
         "rosters", "mandatory_roles", "review", "omission")
FIELDS = {"schema_version", "policy_version", "implementation", "authority", "registry", "roles", "rosters",
          "intents_without_roster", "mandatory_roles", "session_limit", "concurrency", "waves", "omission", "review",
          "consumers", "declared_vs_enforced"}
_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_VERSION = re.compile(r"^(?:0|[1-9]\d{0,3})\.(?:0|[1-9]\d{0,3})\.(?:0|[1-9]\d{0,3})$")
_REL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@+-]*(?:/[A-Za-z0-9_.@+-]+)*$")
_TEST = re.compile(r"^tests\.test_\w+\.[A-Z]\w*\.test_\w+$")


class AgentTeamError(ValueError):
    """The policy, the registry or a plan breaks the agent-team rules."""


class PolicyNotInstalled(AgentTeamError):
    """Neither the vendored copy nor the hub layout has the file (an older install); a caller may degrade."""


class NoStandingTeam(AgentTeamError):
    """The intent is listed in intents_without_roster: it keeps its own sizing and has no standing team."""


def _need(condition, message):
    if not condition:
        raise AgentTeamError(message)


def _pairs(rows):
    result = {}
    for key, value in rows:
        _need(key not in result, f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _refuse_constant(name):
    raise AgentTeamError(f"invalid JSON number {name}")


def _strict_json(text):
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_refuse_constant)
    except json.JSONDecodeError as error:
        raise AgentTeamError(f"invalid JSON: {error.msg} at line {error.lineno}") from None


def _read(path):
    path = pathlib.Path(path)
    _need(path.is_file(), f"not found: {path}")
    _need(path.stat().st_size <= MAX_BYTES, f"{path.name}: larger than {MAX_BYTES} bytes")
    return _strict_json(path.read_text(encoding="utf-8"))


def _first(beside, hub_relative):
    for candidate in (HERE / beside, ROOT / hub_relative):
        if candidate.is_file():
            return candidate
    raise PolicyNotInstalled(f"{beside} is not installed beside {HERE.name}/ or at {hub_relative}")


def digest(value):
    """SHA-256 of canonical JSON (sorted keys, no whitespace), the form the hub uses for receipts."""
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _int(value, name, low, high):
    _need(isinstance(value, int) and not isinstance(value, bool) and low <= value <= high,
          f"{name}: an integer from {low} to {high}")
    return value


def _text(value, name, limit=600):
    _need(isinstance(value, str) and value.strip() and len(value) <= limit, f"{name}: text of 1-{limit} characters")
    return value


def _ids(value, name, *, limit=HARD_SESSION_LIMIT, empty=False):
    _need(isinstance(value, list) and (empty or value) and len(value) <= limit,
          f"{name}: a list of {'0' if empty else '1'}-{limit} role ids")
    _need(all(isinstance(item, str) and _ID.match(item) for item in value), f"{name}: role ids are lowercase slugs")
    _need(len(set(value)) == len(value), f"{name}: duplicate role id")
    return value


def _keys(value, name, keys):
    _need(isinstance(value, dict) and set(value) == set(keys), f"{name}: needs exactly {', '.join(sorted(keys))}")
    return value


# ---------------------------------------------------------------- registry

def load_registry(path=None):
    """The role registry: governance/agent-roles.json in the hub, agent-roles.json beside a vendored copy."""
    document = _read(path if path is not None else _first("agent-roles.json", REGISTRY_FILE))
    _need(isinstance(document, dict) and document.get("schema_version") == 1 and isinstance(document.get("roles"), list),
          "role registry: schema_version 1 with a roles list")
    seen = set()
    for role in document["roles"]:
        _need(isinstance(role, dict) and isinstance(role.get("id"), str) and _ID.match(role["id"]),
              "role registry: every role needs an id")
        _need(role["id"] not in seen, f"role registry: duplicate role {role['id']}")
        seen.add(role["id"])
        _need(isinstance(role.get("owns"), list) and isinstance(role.get("reviewer"), bool)
              and isinstance(role.get("default_grant"), dict), f"{role['id']}: owns, reviewer and default_grant")
    _need(0 < len(seen) <= HARD_SESSION_LIMIT, f"role registry: 1-{HARD_SESSION_LIMIT} roles")
    return document


def _registry(registry):
    return load_registry() if registry is None else registry if isinstance(registry, dict) else load_registry(registry)


# ---------------------------------------------------------------- policy

def _evidence(rows):
    _need(isinstance(rows, list) and rows, "concurrency.evidence: a non-empty list")
    for row in rows:
        _need(isinstance(row, dict) and {"supports", "kind", "file"} <= set(row)
              and set(row) <= {"supports", "kind", "file", "pointer", "value", "contains"},
              "evidence: supports, kind, file and a pointer with value or contains")
        _need(row["supports"] in SUPPORTS, f"evidence: supports one of {', '.join(SUPPORTS)}")
        _need(row["kind"] in EVIDENCE_KINDS, f"evidence: kind one of {', '.join(EVIDENCE_KINDS)}")
        _need(isinstance(row["file"], str) and _REL.match(row["file"]) and ".." not in row["file"].split("/"),
              f"evidence: {row['file']!r} must be a relative path in the tree")
        _need(("value" in row) != ("contains" in row), f"evidence {row['file']}: exactly one of value or contains")
        if "value" in row:
            _need("pointer" in row and isinstance(row["value"], (int, bool, str)), f"evidence {row['file']}: a value needs a pointer")
        else:
            _text(row["contains"], f"evidence {row['file']}: contains", 200)
        if "pointer" in row:
            _need(isinstance(row["pointer"], list) and 0 < len(row["pointer"]) <= 8 and all(
                isinstance(part, str) or (isinstance(part, int) and not isinstance(part, bool) and part >= 0)
                for part in row["pointer"]), f"evidence {row['file']}: pointer of keys and indexes")
    for name in SUPPORTS:
        _need(any(row["supports"] == name for row in rows), f"concurrency.evidence: nothing supports {name}")
    _need(any(row["supports"] == "session_limit" and row["kind"] == "measured" for row in rows),
          "concurrency.evidence: the session limit needs a measured source")
    return rows


def validate(policy, registry=None):
    """Return the policy when it satisfies every rule; raise AgentTeamError otherwise.

    With a registry (a document or a path), the role list must equal the registry's ids in order and
    every role the registry flags as reviewer must be mandatory."""
    _need(isinstance(policy, dict), "agent-team policy: a JSON object")
    missing, extra = sorted(FIELDS - set(policy)), sorted(set(policy) - FIELDS)
    _need(not missing and not extra, f"agent-team policy: missing {missing}, unknown {extra}")
    _need(policy["schema_version"] == 1 and not isinstance(policy["schema_version"], bool), "schema_version: 1")
    _need(isinstance(policy["policy_version"], str) and _VERSION.match(policy["policy_version"]),
          "policy_version: MAJOR.MINOR.PATCH")
    _need(policy["implementation"] == IMPLEMENTATION, f"implementation: {IMPLEMENTATION}")
    _text(policy["authority"], "authority", 1000)
    _need(policy["registry"] == REGISTRY_FILE, f"registry: {REGISTRY_FILE}")
    roles = _ids(policy["roles"], "roles")
    limit = _int(policy["session_limit"], "session_limit", 1, HARD_SESSION_LIMIT)
    rosters = policy["rosters"]
    _need(isinstance(rosters, dict) and rosters, "rosters: at least one intent")
    mandatory = _ids(policy["mandatory_roles"], "mandatory_roles")
    _need(set(mandatory) <= set(roles), "mandatory_roles: every mandatory role is a policy role")
    for intent, roster in rosters.items():
        _need(isinstance(intent, str) and _ID.match(intent), f"rosters: intent {intent!r}")
        _ids(roster, f"rosters.{intent}", limit=limit)
        unknown = [rid for rid in roster if rid not in roles]
        _need(not unknown, f"rosters.{intent}: unknown role(s) {unknown}")
        _need(roster == [rid for rid in roles if rid in roster], f"rosters.{intent}: keep the registry order")
        _need(set(mandatory) <= set(roster), f"rosters.{intent}: missing mandatory role(s) {sorted(set(mandatory) - set(roster))}")
    without = policy["intents_without_roster"]
    _need(isinstance(without, dict) and all(isinstance(k, str) and _ID.match(k) for k in without),
          "intents_without_roster: intent -> reason")
    _need(not set(without) & set(rosters), "intents_without_roster: an intent has a roster or a reason, not both")
    for intent, reason in without.items():
        _text(reason, f"intents_without_roster.{intent}", 300)
    concurrency = _keys(policy["concurrency"], "concurrency",
                        {"agents_per_cpu", "start", "workflow_runner", "rule", "labels", "evidence"})
    _int(concurrency["agents_per_cpu"], "concurrency.agents_per_cpu", 1, 64)
    _int(concurrency["start"], "concurrency.start", 1, limit)
    runner = _keys(concurrency["workflow_runner"], "concurrency.workflow_runner", {"cap", "reserved_cpus"})
    _int(runner["cap"], "concurrency.workflow_runner.cap", 1, limit)
    _int(runner["reserved_cpus"], "concurrency.workflow_runner.reserved_cpus", 0, 64)
    _text(concurrency["rule"], "concurrency.rule", 1000)
    labels = _keys(concurrency["labels"], "concurrency.labels", set(SUPPORTS))
    for name in SUPPORTS:
        _text(labels[name], f"concurrency.labels.{name}", 300)
    _evidence(concurrency["evidence"])
    for section, keys in (("waves", {"order", "size", "next", "implementation"}),
                          ("omission", {"rule", "default_reason", "implementation"})):
        for key in sorted(_keys(policy[section], section, keys)):
            _text(policy[section][key], f"{section}.{key}", 600)
    review = _keys(policy["review"], "review", {"rule", "testing_reviewers", "approvals", "implementation"})
    _text(review["rule"], "review.rule")
    _text(review["implementation"], "review.implementation")
    testers = _ids(review["testing_reviewers"], "review.testing_reviewers")
    _need(len(testers) >= 2 and set(testers) <= set(roles),
          "review.testing_reviewers: two or more policy roles, so a producer can always be reviewed by another")
    _need(review["approvals"] == ["testing", "security", "release"], "review.approvals: testing, security, release")
    consumers = policy["consumers"]
    _need(isinstance(consumers, list) and len(consumers) <= 32, "consumers: a list")
    for row in consumers:
        _need(isinstance(row, dict) and set(row) == {"file", "reads"} and isinstance(row["file"], str)
              and _REL.match(row["file"]) and isinstance(row["reads"], list) and row["reads"]
              and all(item in READS for item in row["reads"]), f"consumers: file and reads ({', '.join(READS)})")
    split = _keys(policy["declared_vs_enforced"], "declared_vs_enforced", {"enforced_in_ci", "declared_only"})
    _need(isinstance(split["enforced_in_ci"], list) and split["enforced_in_ci"], "declared_vs_enforced.enforced_in_ci: a list")
    for row in split["enforced_in_ci"]:
        _need(isinstance(row, dict) and set(row) == {"claim", "tests"} and isinstance(row["tests"], list) and row["tests"]
              and all(isinstance(t, str) and _TEST.match(t) for t in row["tests"]),
              "enforced_in_ci: claim and tests named tests.<module>.<Class>.<test_method>")
        _text(row["claim"], "enforced_in_ci.claim", 300)
    _need(isinstance(split["declared_only"], list) and split["declared_only"], "declared_vs_enforced.declared_only: a list")
    for row in split["declared_only"]:
        _need(isinstance(row, dict) and set(row) == {"claim", "why"}, "declared_only: claim and why")
        _text(row["claim"], "declared_only.claim", 300)
        _text(row["why"], "declared_only.why", 600)
    if registry is not None:
        document = _registry(registry)
        ids = [role["id"] for role in document["roles"]]
        _need(roles == ids, "roles: the policy's role list differs from the registry (same ids, same order)")
        flagged = sorted(role["id"] for role in document["roles"] if role["reviewer"])
        _need(set(flagged) <= set(mandatory), f"mandatory_roles: the registry's reviewer role(s) {flagged} must be mandatory")
    return policy


def load_policy(path=None):
    """Read and validate the agent-team policy (beside this file when vendored, else under the hub root)."""
    return validate(_read(path if path is not None else _first("agent-team.json", POLICY_FILE)))


def _policy(policy):
    return load_policy() if policy is None else validate(policy) if isinstance(policy, dict) else load_policy(policy)


# ---------------------------------------------------------------- team and concurrency

def concurrency(cpus=None, *, runner="agent", policy=None):
    """How many agents may run at the same moment on a host with `cpus` CPUs."""
    policy = _policy(policy)
    cpus = (os.cpu_count() or 1) if cpus is None else cpus
    _int(cpus, "cpus", 1, 4096)
    _need(runner in RUNNERS, f"runner: one of {', '.join(RUNNERS)}")
    rules = policy["concurrency"]
    limit = policy["session_limit"]
    host_cap = min(limit, cpus * rules["agents_per_cpu"])
    spare = cpus - rules["workflow_runner"]["reserved_cpus"]
    workflow = min(rules["workflow_runner"]["cap"], spare) if spare >= 1 else None
    if runner == "workflow":
        _need(workflow is not None, f"the workflow runner's documented cap is not positive on {cpus} CPU(s)")
        effective = min(host_cap, workflow)
    else:
        effective = host_cap
    return {"session_limit": limit, "effective": effective, "start": min(rules["start"], effective),
            "workflow_runner": workflow, "host_cap": host_cap, "cpus": cpus, "agents_per_cpu": rules["agents_per_cpu"],
            "runner": runner, "rule": rules["rule"], "basis": "policy numbers and the CPU count; nothing was started"}


def team_for(intent, cpus=None, *, runner="agent", policy=None, registry=None):
    """The standing team of an intent: roster roles, registry roles left out with a reason, concurrency."""
    policy = validate(_policy(policy), _registry(registry))
    if intent not in policy["rosters"]:
        reason = policy["intents_without_roster"].get(intent)
        _need(reason is not None, f"intent {intent!r} is not in the agent-team policy")
        raise NoStandingTeam(f"{intent}: no standing team. {reason}")
    roster = policy["rosters"][intent]
    version = policy["policy_version"]
    omitted = [{"role": rid, "reason": f"not in the {intent} roster of agent-team policy {version}"}
               for rid in policy["roles"] if rid not in roster]
    return {"intent": intent, "roles": list(roster), "size": len(roster), "omitted": omitted,
            "mandatory": list(policy["mandatory_roles"]), "policy_version": version, "policy_sha256": digest(policy),
            "concurrency": concurrency(cpus, runner=runner, policy=policy), "waves": policy["waves"]["size"],
            "basis": "staffing plan from the agent-team policy; no agent was started"}


def reviewer_for(role_id, *, policy=None, registry=None):
    """The independent reviewer of a work item a role produced (the orchestrator's review rule)."""
    policy, document = _policy(policy), _registry(registry)
    ids = [role["id"] for role in document["roles"]]
    _need(role_id in ids, f"unknown role {role_id!r}")
    flagged = [role["id"] for role in document["roles"] if role["reviewer"] and role["id"] != role_id]
    if flagged:
        return flagged[0]
    others = [rid for rid in policy["review"]["testing_reviewers"] if rid != role_id and rid in ids]
    _need(others, f"{role_id}: no independent reviewer in the registry")
    return others[0]


def role_card(role_id, *, policy=None, registry=None):
    """What a specialist needs before it starts: owned paths, default grant, reviewer and rosters."""
    policy, document = _policy(policy), _registry(registry)
    validate(policy, document)
    role = next((row for row in document["roles"] if row["id"] == role_id), None)
    _need(role is not None, f"unknown role {role_id!r}")
    title = role.get("title")
    return {"role": role_id, "team": role.get("team"), "title": title.get("en") if isinstance(title, dict) else title,
            "owns": list(role["owns"]), "default_grant": role["default_grant"], "is_reviewer": role["reviewer"],
            "reviewer": reviewer_for(role_id, policy=policy, registry=document),
            "rosters": [intent for intent, roster in policy["rosters"].items() if role_id in roster],
            "policy_version": policy["policy_version"], "policy_sha256": digest(policy),
            "rule": "Write only inside the work item's paths, or inside owns when the work item names none; "
                    "never review your own work; hand it to the reviewer with changed paths and test receipts."}


# ---------------------------------------------------------------- staffing

def _plan_roles(plan, known):
    roles, items, reviewing = [], {}, {}
    for key in ("tasks", "agents"):
        rows = plan.get(key, [])
        _need(isinstance(rows, list), f"plan.{key}: a list")
        for row in rows:
            _need(isinstance(row, dict) and isinstance(row.get("role"), str), f"plan.{key}: every entry names a role")
            roles.append(row["role"])
            items.setdefault(row["role"], [])
            if key == "tasks":
                items[row["role"]].append(str(row.get("id")))
                review = row.get("review")
                if review is not None:
                    _need(isinstance(review, dict) and isinstance(review.get("reviewer"), str),
                          f"plan task {row.get('id')}: review names a reviewer")
                    _need(review["reviewer"] != row["role"],
                          f"plan task {row.get('id')}: the reviewer {review['reviewer']} produced the work item")
                    for rid in {review["reviewer"], *(review.get("panel") or {}).values()}:
                        roles.append(rid)
                        reviewing.setdefault(rid, set()).add(str(row.get("id")))
    listed = plan.get("roles", [])
    _need(isinstance(listed, list) and all(isinstance(rid, str) for rid in listed), "plan.roles: a list of role ids")
    roles += listed
    for rid in listed:
        items.setdefault(rid, [])
    unknown = sorted({rid for rid in roles if rid not in known})
    _need(not unknown, f"plan: unknown role(s) {unknown}")
    return items, reviewing


def check_staffing(plan, intent=None, *, policy=None, registry=None):
    """Staffed and omitted roles of a plan, each omitted role with a reason; fails closed.

    `plan` is an engineering_os.orchestrator plan (tasks and agents with roles) or a staffing record
    {"intent", "roles"}; an optional "omitted" list of {"role", "reason"} carries the planner's own
    reasons. Refused: more agents than the session limit, an unknown role, a role outside the intent's
    roster, a reviewer that produced its work item, a mandatory role that neither works nor reviews,
    and a policy whose roles differ from the registry."""
    _need(isinstance(plan, dict), "plan: a JSON object")
    document = _registry(registry)
    policy = validate(_policy(policy), document)
    intent = intent if intent is not None else plan.get("intent")
    _need(isinstance(intent, str), "plan: name the intent (for example build or upgrade)")
    team = team_for(intent, 1, policy=policy, registry=document)
    roster, limit = team["roles"], policy["session_limit"]
    items, reviewing = _plan_roles(plan, set(policy["roles"]))
    outside = [rid for rid in items if rid not in roster]
    _need(not outside, f"plan: role(s) {outside} are not in the {intent} roster")
    agents = len(plan["agents"]) if isinstance(plan.get("agents"), list) else len(items)
    _need(agents <= limit, f"plan: {agents} agents; the agent-team policy allows at most {limit} in one session")
    declared = {}
    for row in plan.get("omitted", []):
        _need(isinstance(row, dict) and set(row) == {"role", "reason"} and row["role"] in roster,
              "plan.omitted: {role, reason} for a roster role")
        _need(row["role"] not in items, f"plan.omitted: {row['role']} has work in the plan")
        _need(row["role"] not in declared, f"plan.omitted: {row['role']} listed twice")
        declared[row["role"]] = _text(row["reason"], f"plan.omitted.{row['role']}", 300)
    staffed = [{"role": rid, "work_items": items[rid]} for rid in roster if rid in items]
    omitted = []
    for rid in roster:
        if rid in items:
            continue
        if rid in declared:
            reason = declared[rid]
        elif rid in reviewing:
            reason = (f"no work item of its own; reviews {len(reviewing[rid])} work item(s) as independent reviewer "
                      "or approval-panel member")
        else:
            reason = policy["omission"]["default_reason"]
        omitted.append({"role": rid, "reason": reason})
    for rid in policy["mandatory_roles"]:
        _need(rid in items or rid in reviewing,
              f"plan: mandatory role {rid} neither produces nor reviews any work item (independent review is mandatory)")
    omitted += team["omitted"]
    _need(len(staffed) + len(omitted) == len(policy["roles"]), "staffing: every registry role is staffed or omitted")
    return {"intent": intent, "policy_version": team["policy_version"], "policy_sha256": team["policy_sha256"],
            "session_limit": limit, "agents": agents, "staffed": staffed, "omitted": omitted,
            "counts": {"roles": len(policy["roles"]), "roster": len(roster), "staffed": len(staffed), "omitted": len(omitted)},
            "basis": "staffing check of a plan against the agent-team policy; nothing was started"}


# ---------------------------------------------------------------- evidence

def evidence_status(policy=None, root=ROOT):
    """Compare every cited evidence value with the file it names; files absent from a vendored copy are 'absent'."""
    policy = _policy(policy)
    root = pathlib.Path(root)
    rows = []
    for row in policy["concurrency"]["evidence"]:
        path = root / row["file"]
        result = {"supports": row["supports"], "file": row["file"], "pointer": row.get("pointer")}
        if not path.is_file():
            rows.append(dict(result, status="absent"))
            continue
        try:
            found = path.read_text(encoding="utf-8")
            if "pointer" in row:
                found = json.loads(found)
                for part in row["pointer"]:
                    found = found[part]
        except (ValueError, KeyError, IndexError, TypeError):
            rows.append(dict(result, status="mismatch", found="pointer does not resolve"))
            continue
        if "value" in row:
            ok = found == row["value"] and type(found) is type(row["value"])
        else:
            ok = isinstance(found, str) and row["contains"] in found
        rows.append(dict(result, status="ok" if ok else "mismatch", found=found if "value" in row else ok))
    return rows


# ---------------------------------------------------------------- command line

def _print(command, value, as_json):
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if command == "show":
        c = value["concurrency"]
        print(f"agent-team policy {value['policy_version']} (sha256 {value['policy_sha256'][:12]})")
        print(f"intent {value['intent']}: {value['size']} roles, {len(value['omitted'])} omitted, "
              f"mandatory {', '.join(value['mandatory'])}")
        workflow = "n/a" if c["workflow_runner"] is None else c["workflow_runner"]
        print(f"concurrency on {c['cpus']} CPU(s), {c['runner']} runner: session limit {c['session_limit']}, "
              f"effective {c['effective']}, start {c['start']}, workflow runner {workflow}")
        print("roles: " + ", ".join(value["roles"]))
        for row in value["omitted"]:
            print(f"omitted {row['role']}: {row['reason']}")
    elif command == "check":
        print(f"{value['intent']}: {value['counts']['staffed']} staffed, {value['counts']['omitted']} omitted, "
              f"{value['agents']} agents (limit {value['session_limit']}), policy {value['policy_version']}")
        for row in value["staffed"]:
            print(f"staffed {row['role']}: {len(row['work_items'])} work item(s)")
        for row in value["omitted"]:
            print(f"omitted {row['role']}: {row['reason']}")
    elif command == "role":
        print(f"{value['role']} (team {value['team']}): reviewer {value['reviewer']}, "
              f"max side effect {value['default_grant'].get('max_side_effect')}")
        print("owns: " + (", ".join(value["owns"]) or "nothing"))
    else:
        for row in value:
            print(f"{row['status']:8} {row['supports']:15} {row['file']} {row.get('pointer') or ''}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agent_team", description="Central agent-team policy: team, concurrency, staffing.")
    parser.add_argument("--policy", help="policy file (default: beside this file or the hub's governance/policies)")
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show", help="the standing team and concurrency of an intent")
    show.add_argument("--intent", default="build")
    show.add_argument("--cpus", type=int)
    show.add_argument("--runner", choices=RUNNERS, default="agent")
    check = commands.add_parser("check", help="staffing check of a plan JSON file")
    check.add_argument("plan")
    check.add_argument("--intent")
    role = commands.add_parser("role", help="owned paths, default grant and reviewer of one role")
    role.add_argument("role_id")
    commands.add_parser("evidence", help="compare every cited number with its evidence file")
    for sub in (show, check, role, commands.choices["evidence"]):
        sub.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.policy)
        if args.command == "show":
            value = team_for(args.intent, args.cpus, runner=args.runner, policy=policy)
        elif args.command == "check":
            value = check_staffing(_read(args.plan), args.intent, policy=policy)
        elif args.command == "role":
            value = role_card(args.role_id, policy=policy)
        else:
            value = evidence_status(policy)
    except AgentTeamError as error:
        print(f"agent-team: {error}", file=sys.stderr)
        return 2
    _print(args.command, value, args.json)
    return 1 if args.command == "evidence" and any(row["status"] == "mismatch" for row in value) else 0


if __name__ == "__main__":
    sys.exit(main())
