"""Capacity study by simulation: what would 1,000 to 100,000 agents need?

It takes the rates measured on one real stage (seconds per agent, agents per message,
seconds per message beyond the agents' own time, share of tasks not verified, input
tokens per agent) and runs simulate.run for every size at every concurrency. No agent
runs; every output says so. Concurrency 20 is the measured limit of one host session;
larger values stand for several sessions side by side, which was not tested.
The same seed gives the same document, byte for byte.

Call:
    python3 swarm/phase3/capacity.py --from EVIDENCE.json --stage LABEL [--limit TOKENS] [--save]
--save writes swarm/phase3/evidence/capacity.json.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]
import simulate  # noqa: E402

KIND = "simulation"
ABOUT = ("Simulation, not a measurement: no agent ran. Rates come from one real stage; "
         "every size and every concurrency above 20 is extrapolation. One host session "
         "runs at most 20 agents (measured); larger concurrencies stand for several "
         "sessions side by side, which was not tested.")
SIZES = (1000, 2000, 5000, 10000, 20000, 50000, 100000)
CONCURRENCIES = (20, 100, 500, 1000)
SESSION = 20
SEED = 20261130
SD_FRACTION = 0.25  # assumption: spread of one agent's time, not measured
OUT = HERE / "evidence" / "capacity.json"


class Refused(ValueError):
    pass


def parameters_from(document, label):
    stage = next((s for s in document.get("stages", []) if s.get("label") == label), None)
    if stage is None:
        raise Refused(f"no stage labelled {label!r} in the document")
    agents = stage.get("actual_agents") or 0
    if agents <= 0:
        raise Refused(f"stage {label!r} has no agents: nothing to derive rates from")
    if not stage.get("verified_tasks"):
        raise Refused(f"stage {label!r} has no verified task: its rates cannot be trusted")
    tasks = stage.get("tasks") or 0
    if tasks <= 0:
        raise Refused(f"stage {label!r} records no tasks")
    total = stage.get("sum_of_agent_seconds") or 0
    if total <= 0:
        raise Refused(f"stage {label!r} has no agent seconds: the time per agent is unknown")
    per_msg = (stage.get("queue") or {}).get("agent_calls_per_message")
    if not per_msg or per_msg <= 0:
        raise Refused(f"stage {label!r} has no agents per message")
    wall = stage.get("wall_seconds")
    if wall is None:
        raise Refused(f"stage {label!r} has no wall time")
    tokens = (stage.get("agent_tokens") or {}).get("input_total")
    if tokens is None:
        raise Refused(f"stage {label!r} has no input token count")
    parallel = max(1, stage.get("peak_concurrent_agents") or 1)
    messages = math.ceil(agents / per_msg)
    beyond = max(0.0, wall - total / parallel) / messages
    unverified = max(0.0, 1.0 - stage["verified_tasks"] / tasks)
    return {
        "seconds_per_agent": {"value": total / agents,
                              "from": ["sum_of_agent_seconds", "actual_agents"]},
        "agents_per_message": {"value": per_msg, "from": ["queue.agent_calls_per_message"]},
        "seconds_per_message_beyond_agents": {
            "value": beyond,
            "from": ["wall_seconds", "sum_of_agent_seconds", "peak_concurrent_agents",
                     "actual_agents", "queue.agent_calls_per_message"],
            "how": "(wall - agent seconds / peak concurrent agents) / messages, never below 0"},
        "share_not_verified": {"value": unverified, "from": ["verified_tasks", "tasks"]},
        "input_tokens_per_agent": {"value": tokens / agents,
                                   "from": ["agent_tokens.input_total", "actual_agents"]},
        "assumed": {"sd_fraction_of_seconds_per_agent": SD_FRACTION,
                    "tasks_per_agent": 1,
                    "overhead_per_agent": "seconds per message / agents per message"},
        "stage": label,
    }


def _v(parameters, key):
    return parameters[key]["value"]


def ladder(parameters, sizes=SIZES, concurrencies=CONCURRENCIES, seed=SEED, limit=None):
    mean = _v(parameters, "seconds_per_agent")
    service = {"mean": mean, "sd": mean * SD_FRACTION, "least": mean * 0.1}
    overhead = (_v(parameters, "seconds_per_message_beyond_agents")
                / _v(parameters, "agents_per_message"))
    failure = _v(parameters, "share_not_verified")
    tokens_each = _v(parameters, "input_tokens_per_agent")
    rows = []
    for n in sizes:
        for c in concurrencies:
            r = simulate.run(n, n, 1, c, service, seed, overhead, failure)
            tokens = tokens_each * n
            rows.append({
                "kind": KIND,
                "agents": n,
                "concurrency": c,
                "sessions_of_20": math.ceil(c / SESSION),
                "wall_seconds": r["wall_seconds"],
                "tasks_per_minute": r["tasks_per_minute"],
                "tasks_done": r["tasks_done"],
                "tasks_failed": r["tasks_failed"],
                "input_tokens": tokens,
                "fits_limit": None if limit is None else tokens <= limit,
            })
    return {"kind": KIND, "about": ABOUT, "seed": seed, "limit_tokens": limit,
            "parameters": parameters, "rows": rows}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="source", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--save", action="store_true")
    a = p.parse_args(argv)
    try:
        params = parameters_from(json.loads(Path(a.source).read_text()), a.stage)
    except (Refused, OSError, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    doc = ladder(params, limit=a.limit)
    took = time.perf_counter() - t0
    top = max(doc["rows"], key=lambda r: r["agents"])["agents"]
    print(f"{KIND}: no agent ran. Whole ladder up to {top} agents took {took:.2f} s "
          f"as measured here.")
    print(f"{'agents':>7} {'conc':>5} {'sess':>5} {'wall_s':>11} {'per_min':>9} {'tokens':>13} fits")
    for r in doc["rows"]:
        tpm = r["tasks_per_minute"]
        print(f"{r['agents']:>7} {r['concurrency']:>5} {r['sessions_of_20']:>5} "
              f"{r['wall_seconds']:>11.1f} {'-' if tpm is None else format(tpm, '.1f'):>9} "
              f"{r['input_tokens']:>13.0f} {r['fits_limit']}")
    if a.save:
        doc["timing"] = {"measured_here_seconds": round(took, 2),
                         "note": "wall clock of this run on this machine; not part of the simulation"}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        print(f"saved {OUT.relative_to(HERE.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
