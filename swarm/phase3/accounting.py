#!/usr/bin/env python3
"""Who used what: the experiment's input tokens for agents, reviewers, development agents and orchestrators, each apart, and the sum.

    python3 swarm/phase3/accounting.py            print the account as JSON
    python3 swarm/phase3/accounting.py --save     also write swarm/phase3/evidence/accounting.json

Every figure is read from an evidence file in the repository; this script measures nothing.
The limit the owner set (150,000,000 input tokens) has counted agents since the first phase:
workers, probes, reviewers and development agents. Orchestrators were measured and reported
beside it. The owner asked for each kind apart and for the sum of all of them; the sum is
given here with the plain statement of whether it is over the limit.

An input token is counted each time it is read, cache reads included. It is not a price and
not a measure of a subscription's allowance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE_ALLOWANCE = 47977  # as in stage3.py: the two probe agents of each team session are in no evidence file; this is the second phase's probe stage
REVIEW_LANES = {"team.json": ["S1"], "team2.json": ["H1", "H7", "H11", "H12"]}  # lanes whose work was to attack or to review, not to build
NOT_MEASURED = ["the session that wrote the experiment and started the others (the authoring session), outside the first phase's stage windows",
                "what an orchestrating session read between stages (setting up, preparing and closing a stage, saving)",
                "the orchestrating sessions of the two development rounds",
                "the orchestrator during a security gate stage"]


def load(root: Path, rel: str):
    path = root / rel
    return json.loads(path.read_text()) if path.is_file() else None


def stages_of(document) -> list[dict]:
    return [s for s in (document or {}).get("stages", []) if not s.get("skipped")]


def tokens(stage: dict) -> int:
    return stage["agent_tokens"]["input_total"] + (stage.get("other_agents_during_the_stage") or {}).get("input_tokens", 0)


def orchestrator(stage: dict) -> int:
    return (stage.get("orchestrator_tokens") or {}).get("input_total", 0)


def build(root: Path = ROOT) -> dict:
    root = Path(root)
    first = (load(root, "swarm/evidence/summary.json") or {}).get("tokens", {})
    plan2 = load(root, "swarm/phase2/PLAN.json") or {}
    second = stages_of(load(root, "swarm/phase2/evidence/stages.json"))
    evidence = root / "swarm" / "phase3" / "evidence"
    attempts = {path.stem: stages_of(json.loads(path.read_text())) for path in sorted(evidence.glob("run-*.json"))}
    final_document = load(root, "swarm/phase3/evidence/stages.json")
    final = stages_of(final_document)
    teams = {path.name: json.loads(path.read_text()) for path in sorted(evidence.glob("team*.json"))}
    is_gate = lambda stage: stage.get("kind") == "probe"  # noqa: E731

    workers = {
        "first_phase_workers": first.get("all_agents_input_with_review", 0) - first.get("review_agents_input", 0),
        "second_phase_trial": (plan2.get("caps") or {}).get("preflight_input_tokens", 0),
        "second_phase_stages": sum(tokens(s) for s in second if not is_gate(s)),
        **{f"third_phase_{name.replace('-', '_')}": sum(tokens(s) for s in rows if not is_gate(s)) for name, rows in attempts.items()},
        "third_phase_final_run": sum(tokens(s) for s in final if not is_gate(s)),
    }
    probes = {
        "second_phase_probe_stage": sum(tokens(s) for s in second if is_gate(s)),
        **{f"third_phase_{name.replace('-', '_')}_gate_stage": sum(tokens(s) for s in rows if is_gate(s)) for name, rows in attempts.items()},
        "third_phase_final_run_gate_stage": sum(tokens(s) for s in final if is_gate(s)),
        "allowance_for_the_team_sessions_probes_an_estimate": PROBE_ALLOWANCE * len(teams),
    }
    reviewers = {"first_phase_review_agents": first.get("review_agents_input", 0)}
    builders = {}
    for name, document in teams.items():
        chosen = REVIEW_LANES.get(name, [])
        lanes = {row["lane"]: (row.get("agent") or {}).get("input_tokens", 0) for row in document.get("lanes", [])}
        reviewers[f"third_phase_review_and_attack_lanes_of_{name}"] = {lane: lanes.get(lane, 0) for lane in chosen}
        builders[f"third_phase_building_lanes_of_{name}"] = sum(count for lane, count in lanes.items() if lane not in chosen)
    orchestrators = {
        "first_phase_inside_stage_windows": first.get("orchestrator_inside_stage_windows", 0),
        "second_phase_run_inside_stage_windows": sum(orchestrator(s) for s in second),
        **{f"third_phase_{name.replace('-', '_')}_inside_stage_windows": sum(orchestrator(s) for s in rows) for name, rows in attempts.items()},
        "third_phase_final_run_inside_stage_windows": sum(orchestrator(s) for s in final),
    }
    flat = lambda group: sum(sum(v.values()) if isinstance(v, dict) else v for v in group.values())  # noqa: E731
    counted = flat(workers) + flat(probes) + flat(reviewers) + flat(builders)
    limit = ((final_document or {}).get("caps") or {}).get("cumulative_input_tokens") or (load(root, "swarm/phase3/PLAN3.json") or {}).get("caps", {}).get("cumulative_input_tokens")
    everything = counted + flat(orchestrators)
    return {
        "about": "Input tokens of the whole experiment, each kind of user apart, read from the repository's evidence files. Nothing here was measured by this script.",
        "unit": "input tokens as the host's records give them with each reply; a token is counted each time it is read, cache reads included",
        "agents": {"workers": workers, "probe_agents_of_the_security_gate": probes, "total": flat(workers) + flat(probes)},
        "reviewers": {**reviewers, "total": flat(reviewers), "which": "the first phase's review agents, and the lanes of the development rounds whose work was to attack or review and not to build"},
        "development_agents": {**builders, "total": flat(builders)},
        "orchestrators": {**orchestrators, "total_measured": flat(orchestrators), "not_measured_and_in_no_figure": NOT_MEASURED},
        "counted_against_the_limit": {"total": counted, "what": "agents, reviewers and development agents: the definition the limit has had since the first phase"},
        "limit": limit,
        "within_the_limit_as_defined": None if limit is None else counted <= limit,
        "everything_measured": {"total": everything, "what": "agents, reviewers, development agents and the measured part of the orchestrators"},
        "everything_measured_is_over_the_limit": None if limit is None else everything > limit,
    }


def render(account: dict) -> list[str]:
    """The account as lines of a report."""
    money = lambda value: f"{value:,}" if isinstance(value, int) else "not recorded"  # noqa: E731
    out = ["| who | input tokens |", "|---|---|",
           f"| agents: workers of the measured runs | {money(sum(account['agents']['workers'].values()))} |",
           f"| agents: probe agents of the security gate | {money(sum(account['agents']['probe_agents_of_the_security_gate'].values()))} |",
           f"| reviewers | {money(account['reviewers']['total'])} |",
           f"| development agents | {money(account['development_agents']['total'])} |",
           f"| **counted against the limit** (the four rows above) | **{money(account['counted_against_the_limit']['total'])}** |",
           f"| orchestrators, as far as measured | {money(account['orchestrators']['total_measured'])} |",
           f"| **everything measured** | **{money(account['everything_measured']['total'])}** |",
           f"| the limit | {money(account['limit'])} |", ""]
    if account["limit"] is not None:
        out.append("Counted against the limit as the limit has been defined since the first phase: " + ("within it." if account["within_the_limit_as_defined"] else "over it."))
        out.append("Everything measured, orchestrators included: " + ("over the limit by " + money(account["everything_measured"]["total"] - account["limit"]) + "." if account["everything_measured_is_over_the_limit"]
                                                                   else "under the limit."))
    out += ["", "Not measured, and in no figure above:", ""] + [f"- {item}" for item in account["orchestrators"]["not_measured_and_in_no_figure"]]
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    account = build()
    if "--save" in argv:
        out = ROOT / "swarm" / "phase3" / "evidence" / "accounting.json"
        out.write_text(json.dumps(account, indent=1) + "\n")
    print(json.dumps(account, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
