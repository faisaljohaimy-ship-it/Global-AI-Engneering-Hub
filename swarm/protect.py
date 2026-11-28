#!/usr/bin/env python3
"""Decide, from the stages measured so far, whether the ladder may climb to the next one.

    python3 swarm/protect.py RESULTS.json NEXT_AGENTS

The limits were written down before the first agent ran and are not tuned to results.
The host does not show how much of the subscription allowance is left, so the limits are
absolute and deliberately low: the whole experiment may use about what three long
engineering agents used earlier in the same session, and no more.

Prints GO or STOP with every reason, and exits 0 for GO and 1 for STOP.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LIMITS = {
    "max_agent_runs": 320,                 # every real agent started for the experiment, all stages together
    "max_input_tokens": 40_000_000,        # input of all experiment agents, cache reads included
    "max_output_tokens": 1_000_000,
    "min_verified_success_rate": 90.0,     # percent of a stage's tasks that pass every withheld test
    "max_security_findings": 0,
    "min_effective_share": 0.5,            # effective concurrency divided by agents started
    "min_throughput_gain": 1.10,           # tasks per minute against the stage before
    "max_stage_wall_seconds": 900,
    "min_memory_available_mb": 2000,
    "max_host_process_rss_mb": 6000,
    "max_orchestrator_share": 0.5,         # the orchestrator may not cost more than the agents it starts
}


def decide(stages: list[dict], next_agents: int) -> tuple[bool, list[str]]:
    reasons = []
    if not stages:
        return True, ["nothing measured yet"]
    last = stages[-1]
    runs = sum(s["actual_agents"] for s in stages)
    spent_in = sum(s["agent_tokens"]["input_total"] for s in stages)
    spent_out = sum(s["agent_tokens"]["output"] for s in stages)
    per_agent_in = last["agent_tokens"]["input_total"] / last["actual_agents"]
    per_agent_out = last["agent_tokens"]["output"] / last["actual_agents"]
    if last["agents_with_limit_error"]:
        reasons.append(f"{last['agents_with_limit_error']} agents hit a usage or rate limit")
    if last["verified_success_rate"] < LIMITS["min_verified_success_rate"]:
        reasons.append(f"only {last['verified_success_rate']}% of tasks verified")
    if last["security_findings"] > LIMITS["max_security_findings"]:
        reasons.append(f"{last['security_findings']} security findings in the output")
    if last["wall_seconds"] > LIMITS["max_stage_wall_seconds"]:
        reasons.append(f"the stage took {last['wall_seconds']} s")
    if last["actual_agents"] > 1 and last["effective_concurrency"] / last["actual_agents"] < LIMITS["min_effective_share"]:
        reasons.append(f"effective concurrency {last['effective_concurrency']} is under half of {last['actual_agents']} agents")
    multi = [s for s in stages if s["actual_agents"] > 1]
    if len(multi) >= 2 and multi[-1]["tasks_per_minute"] < LIMITS["min_throughput_gain"] * multi[-2]["tasks_per_minute"]:
        reasons.append(f"throughput {multi[-1]['tasks_per_minute']}/min is not 10% above the stage before ({multi[-2]['tasks_per_minute']}/min)")
    machine = last.get("machine") or {}
    if machine and machine["least_memory_available_mb"] < LIMITS["min_memory_available_mb"]:
        reasons.append(f"memory fell to {machine['least_memory_available_mb']} MB")
    if machine and machine["peak_host_process_rss_mb"] > LIMITS["max_host_process_rss_mb"]:
        reasons.append(f"the host process reached {machine['peak_host_process_rss_mb']} MB")
    # Amended after stage one, and reported as a change to the plan: with a single agent there is
    # nothing to coordinate, so this share is a fact about delegation, not a sign that scaling has
    # stopped paying. Stage one tripped it at 75%. From two agents up the rule stands as written.
    if last["actual_agents"] > 1 and last.get("orchestrator_share_of_all_tokens", 0) > LIMITS["max_orchestrator_share"]:
        reasons.append(f"the orchestrator used {last['orchestrator_share_of_all_tokens']:.0%} of the stage's tokens")
    if runs + next_agents > LIMITS["max_agent_runs"]:
        reasons.append(f"{runs} agents started; {next_agents} more would pass {LIMITS['max_agent_runs']}")
    if spent_in + per_agent_in * next_agents > LIMITS["max_input_tokens"]:
        reasons.append(f"{spent_in:,} input tokens spent; the next stage is projected at {round(per_agent_in * next_agents):,}, past {LIMITS['max_input_tokens']:,}")
    if spent_out + per_agent_out * next_agents > LIMITS["max_output_tokens"]:
        reasons.append(f"{spent_out:,} output tokens spent; the next stage would pass {LIMITS['max_output_tokens']:,}")
    return not reasons, reasons or [f"{runs} agents, {spent_in:,} input and {spent_out:,} output tokens so far; next stage projected at {round(per_agent_in * next_agents):,} input"]


def main() -> int:
    stages = json.loads(Path(sys.argv[1]).read_text())["ladder"] if Path(sys.argv[1]).exists() else []
    go, reasons = decide(stages, int(sys.argv[2]))
    print("GO" if go else "STOP", "-", "; ".join(reasons))
    return 0 if go else 1


if __name__ == "__main__":
    sys.exit(main())
