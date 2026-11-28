"""What a task, a feature and a system change cost, read from an evidence document.

Takes the second phase's evidence file (a JSON document with a list of "stages")
and prints a Markdown report: one row per task stage with its cost per verified
task, a projection for more tasks, the cheapest stage per task size, and the
assumptions behind the cost units.

    python3 swarm/phase3/economics.py EVIDENCE [--tasks N]

A queue stage of the gated run (third phase) is read the same way; the orchestrator's
tokens are shown in their own columns, never added to the agents'. A stage with no
tasks (the gate stage) is left out. `factory` prices a recipe such as
{"small": 40, "medium": 12, "large": 3}; `render_factory` prints three recipes.

Where a stage verified nothing, was skipped, or lacks a field, the figure is
None (shown as "n/a"), never zero. Projections come from one stage only and
say so. Cost units are an assumption, not a bill.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]

PLAN = HERE.parent / "phase2" / "PLAN.json"
SIZES = ("small", "medium", "large")
STAND_IN = {"small": "a function", "medium": "a module-sized feature", "large": "a fix in an existing system"}


def _num(value):
    """A real number or None; booleans and text are not numbers."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _div(top, bottom, digits=2):
    top, bottom = _num(top), _num(bottom)
    if top is None or not bottom:
        return None
    value = round(top / bottom, digits)
    return int(value) if digits == 0 else value


def _stages(document: dict) -> list[dict]:
    stages = document.get("stages") if isinstance(document, dict) else None
    if stages is None and isinstance(document, dict) and isinstance(document.get("stage"), dict):
        stages = [document["stage"]]
    return [s for s in stages or [] if isinstance(s, dict)]


def per_task(document: dict) -> list[dict]:
    """One row per task stage (probes are left out)."""
    rows = []
    for s in _stages(document):
        if s.get("kind") not in (None, "task"):
            continue
        skipped = s.get("skipped")
        tokens = s.get("agent_tokens") if isinstance(s.get("agent_tokens"), dict) else {}
        verified = _num(s.get("verified_tasks"))
        verified = verified if verified else None  # zero verified means no per-task figure
        if skipped:
            verified = None
        input_total = _num(tokens.get("input_total"))
        cache_read = _num(tokens.get("cache_read"))
        share = _div(cache_read, input_total, 4)
        if share is None and not skipped:
            share = _num(s.get("cache_read_share"))
        seconds = _div(s.get("sum_of_agent_seconds"), verified)
        agent_seconds = (s.get("per_verified_task") or {}).get("agent_seconds") if isinstance(s.get("per_verified_task"), dict) else None
        if seconds is None and verified and not skipped:
            seconds = _num(agent_seconds)
        orch = s.get("orchestrator_tokens") if isinstance(s.get("orchestrator_tokens"), dict) else {}
        tasks_n = _num(s.get("tasks"))
        failure = None
        if not skipped and tasks_n and _num(s.get("verified_tasks")) is not None:
            failure = round(max(0.0, 1 - s["verified_tasks"] / tasks_n), 4)
        seconds_total = _num(s.get("sum_of_agent_seconds"))
        rows.append({
            "tasks": None if skipped else tasks_n, "failure_rate": failure,
            "output_tokens_per_task": _div(tokens.get("output"), verified, 0),
            "agent_minutes_per_task": None if seconds is None else round(seconds / 60, 4),
            "orchestrator_input_per_task": _div(orch.get("input_total"), verified, 0) if orch and not skipped else None,
            "orchestrator_output_per_task": _div(orch.get("output"), verified, 0) if orch and not skipped else None,
            "label": s.get("label"), "size": s.get("size"), "worker_type": s.get("agent_type"), "model": s.get("model"),
            "agents": None if skipped else _num(s.get("actual_agents")), "verified_tasks": None if skipped else _num(s.get("verified_tasks")),
            "input_tokens_per_task": _div(input_total, verified, 0), "cost_units_per_task": _div(s.get("cost_units"), verified, 0),
            "worker_seconds_per_task": seconds, "cache_read_share": share,
            "tasks_per_minute": None if skipped or not verified else _num(s.get("tasks_per_minute")),
            "skipped": skipped or None,
        })
    return rows


def project(row: dict, tasks: int) -> dict:
    """Input tokens, cost units and wall time for `tasks` more tasks like this row's."""
    basis = f"projection from one stage ({row.get('label')})"
    count = _num(tasks)

    def figure(per):
        per = _num(per)
        value = None if per is None or count is None else round(per * count)
        return {"value": value, "basis": basis}

    tpm = _num(row.get("tasks_per_minute"))
    minutes = round(count / tpm, 2) if tpm and count is not None else None
    return {"tasks": tasks, "input_tokens": figure(row.get("input_tokens_per_task")), "cost_units": figure(row.get("cost_units_per_task")),
            "wall_minutes": {"value": minutes, "basis": basis + " at its tasks per minute"}}


def _cell(value):
    return "n/a" if value is None else f"{value:,}" if isinstance(value, int) else str(value)


def _cheapest(rows: list[dict]) -> dict:
    best = {}
    for size in SIZES:
        priced = [r for r in rows if r["size"] == size and r["cost_units_per_task"] is not None]
        best[size] = min(priced, key=lambda r: r["cost_units_per_task"]) if priced else None
    return best


def _about() -> str:
    try:
        return json.loads(PLAN.read_text())["cost_weights"]["about"]
    except (OSError, ValueError, KeyError):
        return None


def render(document: dict, tasks: int = 100) -> str:
    rows = per_task(document)
    out = ["# What a task, a feature and a system change cost", "",
           "Figures are measured per verified task from the evidence file; cost units are an assumption (see the end). n/a means the stage verified nothing, was skipped, or the field is missing.", "",
           "| Stage | Size | Worker | Model | Agents | Verified | Input tokens / task | Cost units / task | Worker s / task | Cache-read share |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        label = f"{r['label']} (skipped)" if r["skipped"] else r["label"]
        out.append("| " + " | ".join(_cell(x) for x in (label, r["size"], r["worker_type"], r["model"], r["agents"], r["verified_tasks"],
                                                           r["input_tokens_per_task"], r["cost_units_per_task"], r["worker_seconds_per_task"], r["cache_read_share"])) + " |")
    out += ["", "## What the three sizes stand in for", "",
            "- small: a function.", "- medium: a module-sized feature.", "- large: a fix in an existing system.", "",
            "These are stand-ins. The tasks are generated, not real customer work.", "", "## Cheapest stage per size", ""]
    for size, r in _cheapest(rows).items():
        if r is None:
            out.append(f"- {size}: n/a (no stage with a verified task)")
        else:
            line = f"- {size}: {r['label']} at {r['cost_units_per_task']:,} cost units per verified task"
            p = project(r, tasks)
            out.append(f"{line}; for {tasks} more tasks: {_cell(p['input_tokens']['value'])} input tokens, {_cell(p['cost_units']['value'])} cost units, "
                       f"{_cell(p['wall_minutes']['value'])} minutes ({p['cost_units']['basis']}).")
    out += ["", "## Assumptions", "", _about() or "n/a (the plan's cost weights are not readable)", ""]
    return "\n".join(out)


RECIPES = {"one task": {"small": 1}, "one feature": {"small": 3, "medium": 1}, "one system": {"small": 40, "medium": 12, "large": 3}}
QUALIFY = 0.9


def factory(rows: list[dict], recipe: dict) -> dict:
    """Cost of a recipe from the cheapest measured configuration per size that verified >= 90%.

    A size with no qualifying row has figure None and a note; it adds nothing to the totals,
    and the totals say which sizes they leave out."""
    sizes, totals = {}, {"input_tokens": 0, "output_tokens": 0, "cost_units": 0, "agent_minutes": 0.0}
    missing, weighted, counted = [], 0.0, 0
    for size, count in recipe.items():
        count = _num(count) or 0
        good = [r for r in rows if r.get("size") == size and r.get("cost_units_per_task") is not None and _num(r.get("tasks"))
                and r.get("failure_rate") is not None and 1 - r["failure_rate"] >= QUALIFY]
        if not good:
            sizes[size] = {"tasks": count, "configuration": None, "figure": None,
                           "note": f"no measured configuration verified at least {int(QUALIFY * 100)}% of its {size} tasks"}
            missing.append(size)
            continue
        best = min(good, key=lambda r: r["cost_units_per_task"])
        figure = {"input_tokens": None if best.get("input_tokens_per_task") is None else round(best["input_tokens_per_task"] * count),
                  "output_tokens": None if best.get("output_tokens_per_task") is None else round(best["output_tokens_per_task"] * count),
                  "cost_units": round(best["cost_units_per_task"] * count),
                  "agent_minutes": None if best.get("agent_minutes_per_task") is None else round(best["agent_minutes_per_task"] * count, 2)}
        for key, value in figure.items():
            totals[key] = None if totals[key] is None or value is None else totals[key] + value
        sizes[size] = {"tasks": count, "configuration": {k: best.get(k) for k in ("label", "worker_type", "model")},
                       "failure_rate": best["failure_rate"], "figure": figure}
        weighted += count * best["failure_rate"]
        counted += count
    return {"recipe": dict(recipe), "sizes": sizes, "totals": totals, "sizes_without_a_figure": missing,
            "share_needing_second_attempt": round(weighted / counted, 4) if counted else None,
            "basis": "measured rows; second attempts from each configuration's measured failure rate"}


def render_factory(document: dict, recipes: dict = None) -> str:
    rows = per_task(document)
    out = ["# What a task, a feature and a system cost", "",
           "Cost units are an assumption for comparing configurations, not a price or a subscription allowance.",
           "Units of different models are not comparable.", "",
           "| Recipe | Contents | Input tokens | Output tokens | Cost units | Agent minutes | Second attempts | Left out |",
           "|---|---|---|---|---|---|---|---|"]
    detail = []
    for name, recipe in (recipes or RECIPES).items():
        f = factory(rows, recipe)
        t = f["totals"]
        share = f["share_needing_second_attempt"]
        out.append("| " + " | ".join([name, ", ".join(f"{n} {k}" for k, n in recipe.items()),
                                      _cell(t["input_tokens"]), _cell(t["output_tokens"]), _cell(t["cost_units"]),
                                      _cell(t["agent_minutes"]), "n/a" if share is None else f"{share:.1%}",
                                      ", ".join(f["sizes_without_a_figure"]) or "none"]) + " |")
        for size, z in f["sizes"].items():
            c = z["configuration"]
            detail.append(f"- {name}, {size}: " + (f"{c['label']} ({c['worker_type']}, {c['model']})" if c else z["note"]))
    out += ["", "## Configuration used per size", ""] + detail + ["", "A total leaves out any size listed under Left out.", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Cost per verified task, from an evidence file.")
    parser.add_argument("evidence")
    parser.add_argument("--tasks", type=int, default=100)
    args = parser.parse_args(argv)
    print(render_factory(json.loads(Path(args.evidence).read_text())))
    print(render(json.loads(Path(args.evidence).read_text()), args.tasks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
