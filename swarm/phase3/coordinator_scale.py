#!/usr/bin/env python3
"""Measures whether the coordinator's own parts hold at 100,000 tasks. No agent and no model runs.

    python3 swarm/phase3/coordinator_scale.py [--quick] [--save]

For each size it times `taskqueue.create` (seconds, files and bytes on disk), then lets 20 processes
claim every task at the same moment (claims per second, and whether each id was claimed exactly once),
then times `taskqueue.status`. A size whose claiming runs past the time budget is reported as
not finished, with how many were claimed. Once, it times `hook.decide` in one process, the installed
gate program for 200 calls, the size of one line of the gate's record (with an estimate for 100,000
agents making two calls each), and `ledger.build` over 2,000 generated agent records (seconds and
peak memory, with a linear estimate for 100,000). `--quick` uses sizes 200 and 1000. `--save` writes
swarm/phase3/evidence/coordinator-scale.json. These are the coordinator's parts only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]

import hook  # noqa: E402
import ledger  # noqa: E402
import taskqueue  # noqa: E402

PROCESSES = 20
BUDGET_SECONDS = 300.0
CALLS_THROUGH_GATE = 200
RECORDS = 2000


def _claimer(stage: str, name: str, out: str, deadline: float) -> None:
    got = []
    while time.time() < deadline:
        ident = taskqueue.claim(Path(stage), name)
        if ident is None:
            break
        got.append(ident)
    Path(out).write_text(json.dumps(got))


def _du(root: Path) -> tuple[int, int]:
    files = size = 0
    for base, _, names in os.walk(root):
        for name in names:
            files += 1
            size += os.lstat(os.path.join(base, name)).st_size
    return files, size


def queue_size(count: int, scratch: Path, budget: float) -> dict:
    stage = scratch / f"stage{count}"
    stage.mkdir()
    ids = [f"t{n:06d}" for n in range(count)]
    began = time.perf_counter()
    taskqueue.create(stage, ids, count)
    made = time.perf_counter() - began
    files, size = _du(stage / ".queue")
    outs = [scratch / f"c{count}-{i}.json" for i in range(PROCESSES)]
    deadline = time.time() + budget
    began = time.perf_counter()
    procs = [subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--claimer", str(stage), f"w{i}", str(outs[i]), repr(deadline)])
             for i in range(PROCESSES)]
    for proc in procs:
        proc.wait()
    wall = time.perf_counter() - began
    got: list[str] = []
    for out in outs:
        try:
            got += json.loads(out.read_text())
        except (OSError, ValueError):
            pass
    began = time.perf_counter()
    state = taskqueue.status(stage)
    status_seconds = time.perf_counter() - began
    return {"tasks": count, "create_seconds": round(made, 3), "files_on_disk": files, "bytes_on_disk": size,
            "claim_processes": PROCESSES, "claim_wall_seconds": round(wall, 3), "claimed": len(got),
            "claims_per_second": round(len(got) / wall, 1) if wall > 0 else None,
            "every_id_claimed_exactly_once": len(got) == count and set(got) == set(ids),
            "no_id_claimed_twice": len(got) == len(set(got)), "finished_within_budget": len(got) == count,
            "status_seconds": round(status_seconds, 3), "status_claimed": state["claimed"], "status_waiting": state["waiting"]}


def gate_figures(scratch: Path) -> dict:
    # `swk status` and not `swk next`: the gate lets one agent draw a first task once, so the same call 200 times would be refused 199 times
    call = {"agent_type": "swarm-queue-1", "agent_id": "a1", "tool_name": "Bash", "tool_input": {"command": "swk status"}}
    began = time.perf_counter()
    n = 20000
    for _ in range(n):
        hook.decide(call)
    decide_rate = n / (time.perf_counter() - began)
    home = scratch / "home"
    home.mkdir()
    program = scratch / "gate.sh"
    program.write_text(hook.wrapper(f"SWARM_HOME='{home}'"))
    program.chmod(0o700)
    text, codes = json.dumps(call), set()
    began = time.perf_counter()
    for _ in range(CALLS_THROUGH_GATE):
        codes.add(subprocess.run([str(program)], input=text, capture_output=True, text=True).returncode)
    per_call = (time.perf_counter() - began) / CALLS_THROUGH_GATE
    old = hook.LOG
    hook.LOG = scratch / "one-line.jsonl"
    try:
        hook.record(call, "allow")
        line_bytes = hook.LOG.stat().st_size
    finally:
        hook.LOG = old
    return {"hook_decide_per_second_one_process": round(decide_rate), "installed_gate_calls": CALLS_THROUGH_GATE,
            "installed_gate_seconds_per_call": round(per_call, 4), "installed_gate_exit_codes_seen": sorted(codes),
            "record_line_bytes": line_bytes,
            "_line": line_bytes}


def ledger_figures(scratch: Path) -> dict:
    folder = scratch / "records"
    folder.mkdir()
    paths = []
    for n in range(RECORDS):
        path = folder / f"agent-{n}.jsonl"
        rows = []
        for k in range(2):
            rows.append({"type": "assistant", "message": {"id": f"m{n}-{k}", "model": "m", "usage": {}, "content": [
                {"type": "tool_use", "id": f"u{n}-{k}", "name": "Bash", "input": {"command": "swk next"}}]}})
            rows.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"u{n}-{k}", "content": "ok", "is_error": False}]}})
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        path.with_name(path.stem + ".meta.json").write_text(json.dumps({"agentType": "swarm-queue-1"}))
        paths.append(path)
    tracemalloc.start()
    began = time.perf_counter()
    result = ledger.build(paths)
    seconds = time.perf_counter() - began
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {"records": RECORDS, "tool_calls_counted": result["tool_calls"], "seconds": round(seconds, 3), "peak_memory_bytes_tracemalloc": peak}


def machine() -> dict:
    total = None
    try:
        for row in Path("/proc/meminfo").read_text().splitlines():
            if row.startswith("MemTotal:"):
                total = int(row.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return {"cores": os.cpu_count(), "memory_total_bytes": total}


def measure(sizes: tuple = (1000, 10000, 100000), quick: bool = False) -> dict:
    if quick:
        sizes = (200, 1000)
    budget = 60.0 if quick else BUDGET_SECONDS
    with tempfile.TemporaryDirectory() as raw:
        scratch = Path(raw)
        queue = [queue_size(int(size), scratch, budget) for size in sizes]
        gate = gate_figures(scratch)
        led = ledger_figures(scratch)
    line = gate.pop("_line")
    agents, calls = 100000, 2
    scale = 100000 / led["records"]
    return {
        "about": "The coordinator's own parts only: the queue, the gate and the ledger. No agent and no model ran.",
        "machine": machine(),
        "measured": {"queue_by_size": queue, "gate": gate, "ledger_build": led,
                     "source": "timed on this machine in one run with time.perf_counter; memory from tracemalloc (Python allocations only)"},
        "estimated": {
            "gate_record_bytes_for_100000_agents_two_calls_each": line * agents * calls,
            "gate_record_arithmetic": f"{line} bytes per line x {agents} agents x {calls} calls = {line * agents * calls} bytes",
            "ledger_build_seconds_for_100000_records": round(led["seconds"] * scale, 1),
            "ledger_build_peak_bytes_for_100000_records": round(led["peak_memory_bytes_tracemalloc"] * scale),
            "ledger_arithmetic": f"measured value for {led['records']} records x {scale:g}, assuming cost grows in step with the number of records",
            "label": "estimate, not measured"}}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--claimer"]:
        _claimer(argv[1], argv[2], argv[3], float(argv[4]))
        return 0
    result = measure(quick="--quick" in argv)
    text = json.dumps(result, indent=1)
    if "--save" in argv:
        out = HERE / "evidence" / "coordinator-scale.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
