"""Simulate workers drawing tasks from a common queue. This is a simulation, not a measurement.

Workers are asked for at time 0. At most `host_concurrency` run at once; the rest wait for
a running worker to end. A running worker takes tasks one at a time from the common queue,
up to `batch`; each task takes a normal-distributed time (never below service["least"]).
Each worker pays `overhead` seconds once at start. A task fails with probability `failure`
and is not retried. Workers that would start after the queue is empty are never started.

Call:
    python3 swarm/phase3/simulate.py sweep [--tasks N] [--batch N] [--host N]
        [--mean S] [--sd S] [--least S] [--overhead S] [--failure P] [--seed N]
    python3 swarm/phase3/simulate.py run AGENTS [same options]
All default numbers in the command line are assumptions, not measurements.
"""
import argparse
import heapq
import json
import random

KIND = "simulation: no agent ran"
SWEEP_AGENTS = (100, 200, 300, 500, 750, 1000)


def run(agents, tasks, batch, host_concurrency, service, seed, overhead=0.0, failure=0.0):
    rng = random.Random(seed)
    mean, sd, least = service["mean"], service["sd"], service.get("least", 0.0)
    remaining = tasks
    waiting = agents
    heap = []  # (time, seq, worker, taken_in_batch)
    seq = 0
    done = failed = 0
    task_time = 0.0
    life = 0.0
    running = peak = 0
    last_start = 0.0
    wall = 0.0
    starts = {}

    def start(t):
        nonlocal waiting, seq, running, peak, last_start
        waiting -= 1
        running += 1
        peak = max(peak, running)
        last_start = t
        starts[seq] = t
        heapq.heappush(heap, (t + overhead, seq, seq, 0))
        seq += 1

    while waiting > 0 and running < host_concurrency and remaining > 0:
        start(0.0)
    while heap:
        t, _, w, n = heapq.heappop(heap)
        if remaining > 0 and n < batch:
            remaining -= 1
            d = max(least, rng.gauss(mean, sd))
            task_time += d
            if rng.random() < failure:
                failed += 1
            else:
                done += 1
            heapq.heappush(heap, (t + d, seq, w, n + 1))
            seq += 1
        else:
            running -= 1
            life += t - starts[w]
            wall = max(wall, t)
            if waiting > 0 and remaining > 0:
                start(t)
    return {
        "kind": KIND,
        "inputs": {"agents": agents, "tasks": tasks, "batch": batch,
                   "host_concurrency": host_concurrency, "service": dict(service),
                   "seed": seed, "overhead": overhead, "failure": failure},
        "wall_seconds": wall,
        "tasks_done": done,
        "tasks_failed": failed,
        "tasks_per_minute": (done / wall * 60.0) if wall > 0 else None,
        "peak_running": peak,
        "task_share": (task_time / life) if life > 0 else None,
        "last_start_wait_seconds": last_start,
    }


def _options(p):
    p.add_argument("--tasks", type=int, default=1000)
    p.add_argument("--batch", type=int, default=10)
    p.add_argument("--host", type=int, default=100)
    p.add_argument("--mean", type=float, default=60.0)
    p.add_argument("--sd", type=float, default=15.0)
    p.add_argument("--least", type=float, default=5.0)
    p.add_argument("--overhead", type=float, default=20.0)
    p.add_argument("--failure", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=1)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    _options(sub.add_parser("sweep"))
    r = sub.add_parser("run")
    r.add_argument("agents", type=int)
    _options(r)
    a = p.parse_args(argv)
    svc = {"mean": a.mean, "sd": a.sd, "least": a.least}
    if a.cmd == "run":
        print(json.dumps(run(a.agents, a.tasks, a.batch, a.host, svc, a.seed,
                             a.overhead, a.failure), indent=2))
        return 0
    print(KIND + " (all inputs are assumptions)")
    print(f"{'agents':>7} {'wall_s':>9} {'done':>6} {'failed':>6} {'per_min':>8} "
          f"{'peak':>5} {'task_share':>10} {'last_wait_s':>11}")
    for n in SWEEP_AGENTS:
        o = run(n, a.tasks, a.batch, a.host, svc, a.seed, a.overhead, a.failure)
        tpm = o["tasks_per_minute"]
        ts = o["task_share"]
        print(f"{n:>7} {o['wall_seconds']:>9.1f} {o['tasks_done']:>6} {o['tasks_failed']:>6} "
              f"{'-' if tpm is None else format(tpm, '.1f'):>8} {o['peak_running']:>5} "
              f"{'-' if ts is None else format(ts, '.3f'):>10} {o['last_start_wait_seconds']:>11.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
