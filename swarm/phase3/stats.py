"""Speed-up, efficiency and the balance point, read from an evidence document.

Reads the evidence of the second phase (the file written by stage.save()) and groups
its task stages by size, worker type and model. For each stage it gives agents, the
peak at once, verified and total tasks, wall seconds, tasks per minute (all tasks of
the stage over its wall time), input tokens and cost units per verified task, the
speed-up against the group's single-agent stage, the parallel efficiency and the gain
in tasks per minute over the stage before. A figure whose input is missing is None.

Call:  python3 swarm/phase3/stats.py EVIDENCE.json     (prints a Markdown table per group)
In code: summary(document) and balance_point(rows).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

GAIN_MIN = 10.0  # percent: a stage counts as worth its size when it gained at least this much


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _div(a, b, digits=2):
    a, b = _num(a), _num(b)
    return round(a / b, digits) if a is not None and b else None


def _row(stage: dict) -> dict:
    agents, total, verified = _num(stage.get("actual_agents")), _num(stage.get("tasks")), _num(stage.get("verified_tasks"))
    wall = _num(stage.get("wall_seconds"))
    tokens = stage.get("agent_tokens") if isinstance(stage.get("agent_tokens"), dict) else {}
    per_task = _div(wall, total, 4) if wall else None
    return {"label": stage.get("label"), "agents": agents, "peak": _num(stage.get("peak_concurrent_agents")), "verified": verified, "tasks": total,
            "wall_seconds": wall, "tasks_per_minute": _div(total * 60, wall) if total is not None and wall else None,
            "input_per_verified": _div(tokens.get("input_total"), verified, 1) if verified else None,
            "cost_per_verified": _div(stage.get("cost_units"), verified, 1) if verified else None,
            "_seconds_per_task": per_task, "speedup": None, "efficiency": None, "gain_percent": None}


def summary(document: dict) -> dict:
    """Groups of rows by size, worker type and model, plus the skipped stages with their reasons."""
    stages = (document or {}).get("stages") or []
    groups: dict[tuple, list[dict]] = {}
    skipped = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        if stage.get("skipped"):
            skipped.append({"label": stage.get("label"), "reason": stage["skipped"]})
        elif stage.get("kind") == "task":
            groups.setdefault((stage.get("size"), stage.get("agent_type"), stage.get("model")), []).append(_row(stage))
    out = []
    for (size, worker, model), rows in groups.items():
        rows.sort(key=lambda r: (r["agents"] is None, r["agents"] or 0))
        single = next((r for r in rows if r["agents"] == 1 and r["_seconds_per_task"]), None)
        previous = None
        for row in rows:
            if single and row["_seconds_per_task"]:
                row["speedup"] = _div(single["_seconds_per_task"], row["_seconds_per_task"])
                row["efficiency"] = _div(row["speedup"], row["agents"], 3)
            if previous and previous["tasks_per_minute"] and row["tasks_per_minute"] is not None:
                row["gain_percent"] = round((row["tasks_per_minute"] / previous["tasks_per_minute"] - 1) * 100, 1)
            previous = row
        for row in rows:
            del row["_seconds_per_task"]
        out.append({"size": size, "worker": worker, "model": model, "rows": rows, "balance": balance_point(rows)})
    return {"groups": out, "skipped": skipped}


def balance_point(rows: list[dict]) -> dict:
    """The largest stage that still gained at least 10 percent, the cheapest per verified task, and one sentence."""
    if len(rows) < 2:
        return {"largest_worthwhile_agents": None, "cheapest_agents": None,
                "sentence": "Fewer than two stages ran in this group, so no balance point is chosen."}
    worthwhile = [r["agents"] for r in rows if _num(r.get("gain_percent")) is not None and r["gain_percent"] >= GAIN_MIN and r.get("agents") is not None]
    big = max(worthwhile) if worthwhile else None
    priced = [r for r in rows if _num(r.get("cost_per_verified")) is not None and r.get("agents") is not None]
    cheap = min(priced, key=lambda r: r["cost_per_verified"])["agents"] if priced else None
    parts = [f"The largest stage that still gained at least {GAIN_MIN:g}% in tasks per minute had {big} agents" if big is not None
             else f"No stage gained at least {GAIN_MIN:g}% in tasks per minute over the one before"]
    parts.append(f"the lowest cost per verified task was at {cheap} agents" if cheap is not None else "the cost per verified task is unknown for every stage")
    return {"largest_worthwhile_agents": big, "cheapest_agents": cheap, "sentence": "; ".join(parts) + "."}


def _cell(value) -> str:
    return "n/a" if value is None else f"{value:g}" if isinstance(value, float) else str(value)


def render(result: dict) -> str:
    head = ["agents", "peak", "verified", "tasks", "wall s", "tasks/min", "input/verified", "cost/verified", "speed-up", "efficiency", "gain %"]
    keys = ["agents", "peak", "verified", "tasks", "wall_seconds", "tasks_per_minute", "input_per_verified", "cost_per_verified", "speedup", "efficiency", "gain_percent"]
    lines = []
    for g in result["groups"]:
        lines += [f"### size {_cell(g['size'])}, worker {_cell(g['worker'])}, model {_cell(g['model'])}", "",
                  "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        lines += ["| " + " | ".join(_cell(r[k]) for k in keys) + " |" for r in g["rows"]]
        lines += ["", g["balance"]["sentence"], ""]
    lines.append("Skipped stages: " + ("; ".join(f"{s['label']} ({s['reason']})" for s in result["skipped"]) or "none") + ".")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    print(render(summary(json.loads(Path(argv[0]).read_text()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
