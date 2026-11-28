#!/usr/bin/env python3
"""Drive one stage of the ladder: prepare its tasks before the agents start, score it after.

    SWARM_RECORDS=DIR SWARM_MAIN_RECORD=FILE python3 swarm/ladder.py prep STAGE AGENTS FIRST_TASK [--tasks N]
    SWARM_RECORDS=DIR SWARM_MAIN_RECORD=FILE python3 swarm/ladder.py finish STAGE NEXT_AGENTS

The agents themselves are started by the agent host, not by this script: a script cannot
start a real agent. `prep` writes the task folders, claims every task in the hub's task
store, starts the machine sampler and prints the one-line prompt for each agent.
`finish` finds the records the host wrote for those agents, sums their real usage, runs
the withheld tests, records ownership, appends the stage to BENCHMARK_RESULTS.json and
asks protect.py whether the next stage may start.

Everything is kept under SWARM_HOME (default ~/.gaie-swarm), outside any repository.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import measure  # noqa: E402
import protect  # noqa: E402
import scheduler  # noqa: E402
import workload  # noqa: E402

HOME = Path(os.environ.get("SWARM_HOME", Path.home() / ".gaie-swarm"))
RESULTS = HOME / "results" / "BENCHMARK_RESULTS.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def records() -> list[Path]:
    return sorted(Path(os.environ["SWARM_RECORDS"]).glob("*.output"))


def prep(stage: str, agents: int, first: int, tasks: int) -> None:
    for folder in ("work", "state", "samples", "runs", "results"):
        (HOME / folder).mkdir(parents=True, exist_ok=True)
    os.chmod(HOME / "state", 0o700)
    out = HOME / "work" / stage
    made = workload.make(out, first, tasks, 20261128)
    ids = [item["id"] for item in made]
    scheduler.own(HOME / "state", stage, ids)
    sampler = subprocess.Popen([sys.executable, str(HERE / "measure.py"), "sample", str(HOME / "samples" / f"{stage}.jsonl"), "--seconds", "1200"],
                               start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (HOME / "runs" / f"{stage}.json").write_text(json.dumps({"stage": stage, "agents": agents, "tasks": ids, "start": now(), "sampler": sampler.pid,
                                                              "before": [p.name for p in records()]}))
    share = [ids[i::agents] for i in range(agents)]
    print(f"{stage}: {tasks} tasks {ids[0]}..{ids[-1]} claimed for {agents} agents; work in {out}")
    for mine in share[:2]:
        print("  prompt:", " ".join(f"{out}/{t}/TASK.md" for t in mine))


def finish(stage: str, next_agents: int) -> int:
    run = json.loads((HOME / "runs" / f"{stage}.json").read_text())
    end = now()
    try:  # the process id comes from a file, so make sure it still is the sampler before stopping it
        command = Path(f"/proc/{run['sampler']}/cmdline").read_bytes()
        if b"measure.py" in command and b"sample" in command:
            os.killpg(run["sampler"], signal.SIGTERM)
    except (OSError, ProcessLookupError, PermissionError):
        pass
    rows = [measure.read(path) for path in records() if path.name not in run["before"]]
    rows = [row for row in rows if row["task"] in run["tasks"]]
    check = workload.check(HOME / "work" / stage)
    ladder = json.loads(RESULTS.read_text())["ladder"] if RESULTS.exists() else []
    baseline = ladder[0]["wall_seconds"] / ladder[0]["tasks"] if ladder else None
    main_row = measure.read(Path(os.environ["SWARM_MAIN_RECORD"]), measure.moment(run["start"]), measure.moment(end))
    sample_file = HOME / "samples" / f"{stage}.jsonl"
    samples = [json.loads(line) for line in sample_file.read_text().splitlines() if line.strip()] if sample_file.exists() else []
    result = measure.stage(stage, rows, check, main_row, samples, baseline)
    result.update(registered_agents=run["agents"], started=run["start"], finished=end, ownership=scheduler.submit(HOME / "state", stage, check))
    ladder = [s for s in ladder if s["label"] != stage] + [result]
    RESULTS.write_text(json.dumps({"ladder": ladder}, indent=1) + "\n")
    go, reasons = protect.decide(ladder, next_agents)
    show = {k: result[k] for k in ("actual_agents", "peak_concurrent_agents", "verified_tasks", "tasks", "wall_seconds", "effective_concurrency",
                                    "tasks_per_minute", "model_roundtrips", "tool_calls", "cache_read_share", "agents_replying_done", "agents_with_limit_error")}
    print(stage, json.dumps(show))
    print("  tokens", result["agent_tokens"], "| per task", result["per_verified_task"])
    print("  speedup", result.get("speedup_against_one_agent"), "efficiency", result.get("parallel_efficiency"), "| orchestrator", result.get("orchestrator_tokens"),
          "| machine", result.get("machine"))
    failed = [f"{r['id']}:{r['passed']}/{r['total']}" for r in check["rows"] if not r["verified"]]
    print("  not verified:", " ".join(failed) or "none", "| ownership", result["ownership"])
    print("  next", next_agents, "->", "GO" if go else "STOP", "-", "; ".join(reasons))
    return 0


def main() -> int:
    if sys.argv[1] == "prep":
        stage, agents, first = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
        prep(stage, agents, first, int(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[5] == "--tasks" else agents)
        return 0
    return finish(sys.argv[2], int(sys.argv[3]))


if __name__ == "__main__":
    sys.exit(main())
