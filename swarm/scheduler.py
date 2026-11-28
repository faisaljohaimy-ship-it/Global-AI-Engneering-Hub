#!/usr/bin/env python3
"""Plan which agent does which task and when, and keep ownership in the hub's task store.

    python3 swarm/scheduler.py simulate [--limit N] [--agents 100]
    python3 swarm/scheduler.py own STATE_DIR STAGE TASK_ID...       create and claim, print leases
    python3 swarm/scheduler.py submit STATE_DIR STAGE CHECK.json    submit and review from a checker result
    python3 swarm/scheduler.py checkpoint STATE_DIR FILE            then prove it restores

`simulate` starts no agent and calls no model. It builds a hundred tasks, one for each
registered role, with dependencies and a few duplicates, and checks the plan: every
distinct task once, nothing before what it depends on, no agent twice in a wave, no two
tasks writing the same path, no wave above the limit.

Ownership is not a second system: it uses engineering_os.orchestration.TaskStore, whose
state lives in a private folder outside Git. One active task per branch is the store's own
rule; here every task has its own branch name and its own folder, so tasks cannot collide.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from engineering_os.orchestration import TaskStore  # noqa: E402

ORCHESTRATOR = {"id": "swarm-orchestrator", "engine": "claude-code", "role": "orchestrator"}
CHECKER = {"id": "swarm-checker", "engine": "claude-code", "role": "testing"}
WORKER_ROLE = "development"


def plan(tasks: list[dict], agents: list[dict], limit: int) -> dict:
    """Waves of (task, agent) pairs. A wave is what may run at the same time."""
    seen, unique, dropped = {}, [], []
    for item in tasks:
        if item["fingerprint"] in seen:
            dropped.append({"task": item["id"], "same_as": seen[item["fingerprint"]]})
        else:
            seen[item["fingerprint"]] = item["id"]
            unique.append(item)
    alias = {d["task"]: d["same_as"] for d in dropped}
    needs = {t["id"]: {alias.get(n, n) for n in t.get("needs", [])} for t in unique}
    by_team: dict[str, list[dict]] = {}
    for agent in agents:
        by_team.setdefault(agent["team"], []).append(agent)
    done, waves, left = set(), [], {t["id"]: t for t in unique}
    while left:
        ready = sorted((t for t in left.values() if needs[t["id"]] <= done), key=lambda t: (t.get("priority", 2), t["id"]))
        if not ready:
            raise ValueError("the task graph has a cycle")
        wave, busy, paths = [], set(), set()
        for item in ready:
            if len(wave) == limit:
                break
            pool = [a for a in by_team.get(item["team"], []) if a["id"] not in busy]
            exact = [a for a in pool if a["role"] == item.get("role")]
            if not (exact or pool) or item["write"] in paths:
                continue
            agent = (exact or pool)[0]
            busy.add(agent["id"])
            paths.add(item["write"])
            wave.append({"task": item["id"], "agent": agent["id"], "write": item["write"]})
        if not wave:
            raise ValueError("no agent can take any ready task")
        waves.append(wave)
        for pair in wave:
            done.add(pair["task"])
            del left[pair["task"]]
    return {"waves": waves, "dropped_duplicates": dropped, "scheduled": len(done), "limit": limit,
            "largest_wave": max(len(w) for w in waves), "agents_used": len({p["agent"] for w in waves for p in w})}


def simulate(limit: int, count: int, seed: int = 7) -> dict:
    agents = json.loads((HERE / "agents.json").read_text(encoding="utf-8"))["agents"][:count]
    rng = random.Random(seed)
    tasks = []
    for index, agent in enumerate(agents):
        text = f"{agent['role']}: {agent['task_scope']}"
        tasks.append({"id": f"sim-{index + 1:03d}", "team": agent["team"], "role": agent["role"], "write": f"work/sim-{index + 1:03d}",
                      "fingerprint": hashlib.sha256(text.encode()).hexdigest(), "needs": []})
    for item in rng.sample(tasks[10:], min(15, max(0, len(tasks) - 10))):       # some work waits for earlier work
        item["needs"] = [rng.choice(tasks[: int(item["id"][-3:]) - 1])["id"]]
    for source in rng.sample(tasks, min(5, len(tasks))):                         # the same task asked for twice
        tasks.append({**source, "id": source["id"] + "-again", "write": source["write"] + "-again"})
    result = plan(tasks, agents, limit)
    order = {pair["task"]: number for number, wave in enumerate(result["waves"]) for pair in wave}
    alias = {d["task"]: d["same_as"] for d in result["dropped_duplicates"]}
    checks = {
        "every_distinct_task_once": sorted(order) == sorted(t["id"] for t in tasks if t["id"] not in alias),
        "dependencies_first": all(order[alias.get(n, n)] < order[t["id"]] for t in tasks if t["id"] in order for n in t["needs"]),
        "no_agent_twice_in_a_wave": all(len({p["agent"] for p in w}) == len(w) for w in result["waves"]),
        "no_shared_write_path_in_a_wave": all(len({p["write"] for p in w}) == len(w) for w in result["waves"]),
        "no_wave_above_limit": result["largest_wave"] <= limit,
        "duplicates_dropped": len(result["dropped_duplicates"]) == min(5, len(agents)),
    }
    return {"kind": "simulation: no agent was started and no model was called", "registered_agents": len(agents), "tasks_submitted": len(tasks),
            "tasks_scheduled": result["scheduled"], "duplicates_dropped": len(result["dropped_duplicates"]), "waves": len(result["waves"]),
            "largest_wave": result["largest_wave"], "limit": limit, "agents_used": result["agents_used"], "checks": checks, "passed": all(checks.values())}


def own(state: Path, stage: str, task_ids: list[str]) -> list[dict]:
    """Create each task as the orchestrator, then claim it for its own worker."""
    store, leases = TaskStore(state), []
    for task_id in task_ids:
        slug = f"{stage}-{task_id}".lower()
        worker = {"id": f"worker-{slug}", "engine": "claude-code", "role": WORKER_ROLE}
        store.create_task({"id": slug, "project": "swarm-experiment", "branch": f"claude/swarm-{slug}", "paths": [f"work/{stage}/{task_id}/solution.py"],
                           "title": f"Write solution.py for {task_id}", "priority": 2, "role": WORKER_ROLE, "engine": "claude-code"},
                          ORCHESTRATOR, store.snapshot()["revision"])
        task = store.claim(slug, worker, 1, ttl=1800)
        leases.append({"task": slug, "owner": worker["id"], "lease": task["lease"]["id"], "version": task["version"]})
    return leases


def submit(state: Path, stage: str, check: dict) -> dict:
    """Each worker hands in the checksum of its file; the checker records its verdict."""
    store, counts = TaskStore(state), {"submitted": 0, "approved": 0, "rejected": 0, "failed": 0}
    tasks = {t["id"]: t for t in store.tasks()}
    for row in check["rows"]:
        slug = f"{stage}-{row['id']}".lower()
        task = tasks.get(slug)
        if not task or task["status"] != "active":
            continue
        verdict = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        if not row["written"]:
            store.fail(slug, task["owner"], task["version"], task["lease"]["id"], [{"kind": "checker-result", "sha256": verdict}])
            counts["failed"] += 1
            continue
        task = store.submit(slug, task["owner"], task["version"], task["lease"]["id"], [{"kind": "solution", "sha256": row["sha256"]}])
        counts["submitted"] += 1
        decision = "approved" if row["verified"] else "rejected"
        store.review(slug, CHECKER, task["version"], decision, [{"kind": "hidden-tests", "sha256": verdict}])
        counts[decision] += 1
    states: dict[str, int] = {}
    for task in store.tasks():
        states[task["status"]] = states.get(task["status"], 0) + 1
    return {**counts, "task_states": states, "revision": store.snapshot()["revision"]}


def checkpoint(state: Path, target: Path) -> dict:
    """Write a checkpoint, restore it into an empty store and compare."""
    saved = TaskStore(state).checkpoint(target)
    fresh = target.parent / (target.stem + "-restored")
    restored = TaskStore(fresh).restore(target)
    same = TaskStore(fresh).snapshot() == TaskStore(state).snapshot()
    return {"revision": saved["revision"], "state_sha256": saved["state_sha256"], "restored_sha256": restored["state_sha256"], "restore_matches": same}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    sim = commands.add_parser("simulate")
    sim.add_argument("--limit", type=int, default=100)
    sim.add_argument("--agents", type=int, default=100)
    owner = commands.add_parser("own")
    owner.add_argument("state", type=Path)
    owner.add_argument("stage")
    owner.add_argument("tasks", nargs="+")
    hand = commands.add_parser("submit")
    hand.add_argument("state", type=Path)
    hand.add_argument("stage")
    hand.add_argument("check", type=Path)
    save = commands.add_parser("checkpoint")
    save.add_argument("state", type=Path)
    save.add_argument("file", type=Path)
    args = parser.parse_args()
    if args.command == "simulate":
        result = simulate(args.limit, args.agents)
    elif args.command == "own":
        leases = own(args.state, args.stage, args.tasks)
        result = {"claimed": len(leases), "first": leases[0]["task"], "last": leases[-1]["task"]}
    elif args.command == "submit":
        result = submit(args.state, args.stage, json.loads(args.check.read_text()))
    else:
        result = checkpoint(args.state, args.file)
    print(json.dumps(result))
    return 0 if result.get("passed", True) and result.get("restore_matches", True) else 1


if __name__ == "__main__":
    sys.exit(main())
