#!/usr/bin/env python3
"""Drive the third phase's measured run: workers draw tasks from a queue, in stages up to 1,000 agents.

    python3 swarm/phase3/stage3.py setup       install the queue worker's command and the session gate, find the host's records
    python3 swarm/phase3/stage3.py plan        the stages in order, and where the run stands
    python3 swarm/phase3/stage3.py prep        write the next stage's tasks, fill its queue, print what to launch
    python3 swarm/phase3/stage3.py finish      score the open stage, record it, and name the next stage or the end
    python3 swarm/phase3/stage3.py report      rewrite RESULTS.md and the state files from the evidence

This is the second phase's stage driver with three differences. The plan is PLAN3.json.
A stage's tasks go into a queue (taskqueue.py) and every agent of the stage gets the same
prompt, so the agents' records are told apart by their agent type and not by a task id in
the prompt. And what was spent before this run is not typed into the plan: it is added up
from the repository's own evidence when this script starts, and written into this run's
evidence with its parts.

The agents themselves are started by the agent host, not by this script.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SWARM_REPORT_DIR", str(HERE))
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]
import measure  # noqa: E402
import stage  # noqa: E402
import taskqueue  # noqa: E402

HOME = Path(os.environ.get("SWARM_HOME", Path.home() / ".gaie-swarm")) / "p3"
BIN = Path(os.environ.get("SWARM_BIN", "/usr/local/bin"))
ROOT = HERE.parents[1]
PROBE_ALLOWANCE = 47977  # two probe agents ran in the team's session and are in no evidence file; this is what the same probe used in the second phase


def carried_over() -> dict:
    """What counts against the limit before this run, from the evidence in the repository."""
    plan3 = json.loads((HERE / "PLAN3.json").read_text())
    parts = {"first_phase": plan3["caps"]["first_phase_input_tokens"]}
    plan2 = json.loads((HERE.parent / "phase2" / "PLAN.json").read_text())
    parts["second_phase_trial_in_the_authoring_session"] = plan2["caps"]["preflight_input_tokens"]
    second = HERE.parent / "phase2" / "evidence" / "stages.json"
    parts["second_phase_stages"] = sum(s["agent_tokens"]["input_total"] for s in json.loads(second.read_text())["stages"] if not s.get("skipped")) if second.exists() else 0
    team = HERE / "evidence" / "team.json"
    parts["third_phase_development_team"] = json.loads(team.read_text())["totals"]["input_tokens"] if team.exists() else 0
    parts["allowance_for_two_probe_agents_of_the_team_session"] = PROBE_ALLOWANCE if team.exists() else 0
    return {"total": sum(parts.values()), "parts": parts}


def configure() -> dict:
    """Point the second phase's driver at this phase's plan, folders and worker types."""
    plan = json.loads((HERE / "PLAN3.json").read_text())
    carried = carried_over()
    plan["caps"]["spent_before_phase2"] = carried["total"]
    stage.PLAN, stage.HOME, stage.BIN = plan, HOME, BIN
    stage.RESULTS = HOME / "results.json"
    stage.OUT = Path(os.environ["SWARM_REPORT_DIR"])
    stage.EVIDENCE = stage.OUT / "evidence" / "stages.json"
    stage.GUARDED = (*stage.GUARDED, "swarm-queue", "swarm-queue-1")
    stage.card = card
    return carried


def card(spec: dict, model: str, ids: list[str], out: Path) -> str:
    lines = [f"STAGE {spec['id']}: start {spec['agents']} agents, in the foreground."]
    if spec["kind"] == "probe":
        lines += [f"  subagent_type: {spec['agent_type']}   model: {model}   effort: {spec['effort']}", "  All in ONE message. Prompts, one agent each, exactly:",
                  *[f"    {prompt}" for prompt in spec["prompts"]]]
    else:
        per = min(spec["per_message"], spec["agents"])
        messages = -(-spec["agents"] // per)
        lines += [f"  subagent_type: {spec['agent_type']}   model: {model}   effort: {spec['effort']}",
                  f"  prompt of every agent: the single word go      description of every agent: {spec['id']}",
                  f"  {per} Agent calls in one message" + (f", {messages} messages one after the other, {spec['agents']} calls in all." if messages > 1 else "."),
                  "  If the host does not take that many calls in one message, halve the number per message and go on until all are started.",
                  f"  The stage holds {len(ids)} tasks in a queue; each agent takes up to {spec['batch']}."]
    lines.append("When every agent has returned, run: python3 swarm/phase3/stage3.py finish")
    return "\n".join(lines)


def setup() -> int:
    for folder in ("work", "state", "samples", "runs"):
        (HOME / folder).mkdir(parents=True, exist_ok=True)
    os.chmod(HOME / "state", 0o700)
    for name, line in (("swk", f"SWARM_HOME='{HOME.parent}' exec python3 -I '{HERE / 'kit3.py'}' \"$@\""),
                       ("swk-guard", f"exec python3 -I '{HERE.parent / 'phase2' / 'guard.py'}' \"$@\""),
                       ("swk-hook", f"SWARM_HOME='{HOME.parent}' exec python3 -I '{HERE / 'hook.py'}' \"$@\"")):
        (BIN / name).write_text(f"#!/bin/sh\n{line}\n")
        (BIN / name).chmod(0o755)
    main, folder = stage.locate()
    carried = carried_over()
    facts = {"worker_command": shutil.which("swk") is not None, "session_gate": shutil.which("swk-hook") is not None, "session_record_found": main.exists(),
             "agent_records_folder_found": folder.exists(), "no_network_cage": subprocess.run(["unshare", "-n", "true"], capture_output=True).returncode == 0,
             "agent_definitions": sorted(p.stem for p in (ROOT / ".claude" / "agents").glob("swarm-*.md")), "cores": os.cpu_count(),
             "counted_before_this_run": carried, "limit": stage.PLAN["caps"]["cumulative_input_tokens"]}
    print(json.dumps(facts, indent=1))
    return 0 if facts["worker_command"] and facts["session_record_found"] else 1


def prep() -> int:
    done = stage.prep(None)
    if done == 0:
        spec = stage.spec_of((HOME / "open").read_text().strip())
        if spec["kind"] == "task":
            run = json.loads((HOME / "runs" / f"{spec['id']}.json").read_text())
            taskqueue.create(HOME / "work" / spec["id"], run["tasks"], spec["batch"])
    return done


def finish(carried: dict) -> int:
    ident = (HOME / "open").read_text().strip()
    spec, run = stage.spec_of(ident), json.loads((HOME / "runs" / f"{ident}.json").read_text())
    read = measure.read

    def tagged(path, *window):
        """The second phase's driver keeps a record when its prompt names one of the stage's tasks. Here the prompt names none, so a record
        of the stage's agent type is given the stage's first task id as its mark. The mark is used for nothing else."""
        row = read(path, *window)
        if spec["kind"] == "task" and not window and stage.extra(path)["agent_type"] == spec["agent_type"]:
            row["task"] = run["tasks"][0]
        return row

    measure.read = tagged
    try:
        done = stage.finish()
    finally:
        measure.read = read
    stages = stage.load()
    last = next(s for s in stages if s["label"] == ident)
    if spec["kind"] == "task":
        state = taskqueue.status(HOME / "work" / ident)
        took = sorted(len(ids) for ids in state["by_worker"].values())
        last["queue"] = {"tasks": state["tasks"], "left_waiting": state["waiting"], "claimed_and_not_handed_in": state["claimed"], "handed_in": state["handed_in"],
                         "given_up": state["failed"], "workers_that_drew_a_task": state["workers"], "most_tasks_one_worker_took": took[-1] if took else 0,
                         "batch_allowed": spec["batch"], "calls_per_message_asked": min(spec["per_message"], spec["agents"])}
    last["counted_before_this_run"] = carried
    stage.save(stages)
    return done


def report() -> int:
    done = stage.report()
    for name in ("RESULTS.md", "state/RESUME.txt"):
        path = stage.OUT / name
        if path.exists():
            path.write_text(path.read_text().replace("Results of the second phase", "Results of the third phase's run").replace("Second phase.", "Third phase's run.")
                            .replace("stage.py report", "stage3.py report").replace("swarm/phase2/stage.py", "swarm/phase3/stage3.py")
                            .replace("swarm/phase2/RUNBOOK.md", "swarm/phase3/RUNBOOK-RUN.md").replace("the first phase's", "everything before this run:"))
    return done


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    carried = configure()
    if command == "setup":
        return setup()
    if command == "plan":
        return stage.plan()
    if command == "prep":
        return prep()
    if command == "finish":
        return finish(carried)
    if command == "report":
        return report()
    print(__doc__.split("\n\n")[1])
    return 2


if __name__ == "__main__":
    sys.exit(main())
