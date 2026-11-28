#!/usr/bin/env python3
"""Load test of the worker command with scripted workers: no agent, no model.

    python3 swarm/phase3/loadtest.py --tasks 1000 --workers 200 --out FILE

Builds medium tasks in a stage called `load` under HOME/p2/work, then starts all the
workers at the same moment. Each scripted worker takes its share of the tasks and, for each,
runs `kit.py show ID` and then `kit.py submit ID` with the task's reference solution on
standard input. It reports wall seconds, hand-ins per second, the median, 95th percentile and
largest time of each command, failed commands, the highest one-minute load average seen, and
whether the withheld tests verify every task. HOME is SWARM_HOME or a temporary folder.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]

import tasks as tasks_mod  # noqa: E402

KIT = HERE.parent / "phase2" / "kit.py"
KIND = "load test with scripted workers: no agent, no model"


def worker(home: Path, ids: list[str], start: Path, out: Path) -> None:
    """One scripted worker: wait for the start file, then show and submit each task."""
    env = {"SWARM_HOME": str(home), "PATH": os.environ.get("PATH", "")}
    while not start.exists():
        time.sleep(0.01)
    show, submit, failed, handed = [], [], 0, 0
    for ident in ids:
        source = (home / "p3" / "load" / "refs" / f"{ident}.py").read_text()
        for verb, stdin, sink in (("show", "", show), ("submit", source, submit)):
            began = time.perf_counter()
            done = subprocess.run([sys.executable, "-I", str(KIT), verb, ident], input=stdin, env=env,
                                  capture_output=True, text=True)
            sink.append(time.perf_counter() - began)
            if done.returncode != 0:
                failed += 1
            elif verb == "submit" and "passed" in done.stdout:
                handed += 1
    out.write_text(json.dumps({"show": show, "submit": submit, "failed": failed, "handed": handed}))


def spread(values: list[float]) -> dict:
    if not values:
        return {"median": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {"median": round(statistics.median(ordered), 4),
            "p95": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 4),
            "max": round(ordered[-1], 4)}


def run(tasks: int, workers: int, home: Path) -> dict:
    """Run the load test under HOME and return the measurements."""
    home = Path(home)
    stage = home / "p2" / "work" / "load"
    made = tasks_mod.make(stage, "medium", 1, tasks)
    (home / "p2" / "current").write_text("load")
    private = home / "p3" / "load"
    (private / "refs").mkdir(parents=True, exist_ok=True)
    (private / "out").mkdir(exist_ok=True)
    for task in made:
        (private / "refs" / f"{task['id']}.py").write_text(task["reference"])
    count = max(1, min(workers, len(made)))
    shares = [[t["id"] for t in made[i::count]] for i in range(count)]
    start = private / "go"
    start.unlink(missing_ok=True)
    procs = [subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--worker", str(home), str(start),
                               str(private / "out" / f"{i}.json"), *share]) for i, share in enumerate(shares)]
    time.sleep(min(2.0, 0.5 + count * 0.01))
    peak = [os.getloadavg()[0]]
    stop = threading.Event()

    def sample() -> None:
        while not stop.wait(0.5):
            peak.append(os.getloadavg()[0])

    watcher = threading.Thread(target=sample, daemon=True)
    watcher.start()
    began = time.perf_counter()
    start.touch()
    for proc in procs:
        proc.wait()
    wall = time.perf_counter() - began
    stop.set()
    watcher.join()
    show, submit, failed, handed = [], [], 0, 0
    for i in range(count):
        path = private / "out" / f"{i}.json"
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            failed += 2 * len(shares[i])
            continue
        show += data["show"]
        submit += data["submit"]
        failed += data["failed"]
        handed += data["handed"]
    verdict = tasks_mod.check(stage)
    return {"kind": KIND, "cores": os.cpu_count(), "tasks": len(made), "workers": count, "wall_seconds": round(wall, 2),
            "hand_ins": handed, "hand_ins_per_second": round(handed / wall, 2) if wall > 0 else None,
            "show_seconds": spread(show), "submit_seconds": spread(submit), "failed_commands": failed,
            "max_load_average_1min": round(max(peak), 2), "verified": verdict.get("verified"),
            "all_verified": verdict.get("verified") == len(made) and failed == 0,
            "source": "measured on this machine from the commands' own wall times"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--worker":
        worker(Path(argv[1]), argv[4:], Path(argv[2]), Path(argv[3]))
        return 0
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=200)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    base = os.environ.get("SWARM_HOME")
    with tempfile.TemporaryDirectory() as scratch:
        result = run(args.tasks, args.workers, Path(base) if base else Path(scratch))
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0 if result["all_verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
