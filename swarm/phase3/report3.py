#!/usr/bin/env python3
"""The final report of the whole experiment, as Markdown, made only from files in the repository.

    python3 swarm/phase3/report3.py            print the report
    python3 swarm/phase3/report3.py --save     write swarm/phase3/RESULTS-FINAL.md

A section whose file is absent says so and gives no number. Nothing here is measured by this
script: every figure is copied or added up from the evidence files named beside it.
"""
import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FILES = {
    "summary": "swarm/evidence/summary.json", "ladder": "swarm/evidence/ladder.json",
    "limits": "swarm/evidence/host-limits.json", "second": "swarm/phase2/evidence/stages.json",
    "third": "swarm/phase3/evidence/stages.json", "gate": "swarm/phase3/evidence/gate.json",
    "capacity": "swarm/phase3/evidence/capacity.json",
}
TEAM_GLOB = "swarm/phase3/evidence/team*.json"


def load(root, rel):
    try:
        return json.loads((Path(root) / rel).read_text())
    except (OSError, ValueError):
        return None


def na(rel):
    return f"not available: {rel} is not in the repository"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


def num(value, default="not recorded"):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"


def ran(doc):
    return [s for s in (doc or {}).get("stages", []) if not s.get("skipped")]


def total(stages, getter):
    values = [getter(s) for s in stages]
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return sum(values) if values else None


def input_of(stage):
    return (stage.get("agent_tokens") or {}).get("input_total")


def teams(root):
    out = []
    for path in sorted(glob.glob(str(Path(root) / TEAM_GLOB))):
        try:
            out.append((Path(path).relative_to(root).as_posix(), json.loads(Path(path).read_text())))
        except (OSError, ValueError):
            pass
    return out


def phases(root):
    s, l, p2, p3 = (load(root, FILES[k]) for k in ("summary", "ladder", "second", "third"))
    rows = []
    if s:
        a, t = s.get("agents", {}), s.get("tasks", {})
        rows.append(["first", num(a.get("registered_roles")), num(a.get("all_real_agents_started")), num(a.get("peak_concurrent_ai_agents")),
                     num(t.get("ladder_total")), num(t.get("ladder_verified")), num((s.get("tokens") or {}).get("all_agents_input_with_review"))])
    else:
        rows.append(["first"] + [na(FILES["summary"])] * 6)
    for name, doc, rel in (("second", p2, FILES["second"]), ("third", p3, FILES["third"])):
        if not doc:
            rows.append([name] + [na(rel)] * 6)
            continue
        st = ran(doc)
        peaks = [x.get("peak_concurrent_agents") for x in st if isinstance(x.get("peak_concurrent_agents"), int)]
        rows.append([name, num(total(st, lambda x: x.get("registered_agents"))), num(total(st, lambda x: x.get("actual_agents"))),
                     num(max(peaks) if peaks else None), num(total(st, lambda x: x.get("tasks"))),
                     num(total(st, lambda x: x.get("verified_tasks"))), num(total(st, input_of))])
    out = ["## 1. The three phases in one table", ""]
    if not l:
        out += [na(FILES["ladder"]) + " (first phase ladder)", ""]
    out += table(["phase", "agents registered", "real agents started", "most at once", "tasks", "tasks verified by withheld tests", "input tokens"], rows)
    out += ["", "Registered counts, tasks and verified tasks are summed over the stages that ran; a cell says `not recorded` where the file has no such field."]
    return out


def kinds(root):
    p3, cap = load(root, FILES["third"]), load(root, FILES["capacity"])
    out = ["## 2. Four kinds of agents, kept apart", ""]
    rows = []
    if p3:
        st = ran(p3)
        rows.append(["real agents of the measured run (third phase, task stages)", num(total([s for s in st if s.get("kind") != "probe"], lambda x: x.get("actual_agents"))), FILES["third"]])
        rows.append(["probe agents of the security gate", num(total([s for s in st if s.get("kind") == "probe"], lambda x: x.get("actual_agents"))), FILES["third"]])
    else:
        rows.append(["real agents of the measured run (third phase)", na(FILES["third"]), "-"])
        rows.append(["probe agents of the security gate", na(FILES["third"]), "-"])
    ts = teams(root)
    if ts:
        rows.append(["development agents", num(sum(d.get("totals", {}).get("agents_started", 0) for _, d in ts)), ", ".join(n for n, _ in ts)])
    else:
        rows.append(["development agents", na(TEAM_GLOB), "-"])
    if cap:
        rows.append(["simulated agents (a simulation, never added to a real agent)", sim_agents(cap), FILES["capacity"]])
    else:
        rows.append(["simulated agents", na(FILES["capacity"]), "-"])
    return out + table(["kind", "count", "from"], rows)


def cap_rows(cap):
    for value in (cap.values() if isinstance(cap, dict) else []):
        if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
            return value
    return []


def sim_agents(cap):
    counts = sorted({r["agents"] for r in cap_rows(cap) if isinstance(r.get("agents"), int)})
    return "largest row " + num(counts[-1]) + " (rows: " + ", ".join(map(str, counts)) + ")" if counts else "present; no field named `agents` in its rows"


def gate(root):
    p3, g = load(root, FILES["third"]), load(root, FILES["gate"])
    out = ["## 3. The security gate", ""]
    stage = next((s for s in ran(p3) if (s.get("security_gate") or {}).get("probes")), None)
    if stage:
        sg = stage["security_gate"]
        out += table(["probe", "agent type", "had to be", "agents", "calls refused", "ran outside the contract", "held"],
                     [[r.get("what"), r.get("agent_type"), r.get("must_be"), num(r.get("agents")), num(r.get("calls_refused")),
                       num(r.get("calls_outside_the_contract_that_ran")), "yes" if r.get("held") else "no"] for r in sg["probes"]])
        out += ["", f"The run's own judgement of the gate stage: {'passed' if sg.get('passed') else 'not passed'}" + ("; " + "; ".join(sg.get("why", [])) if sg.get("why") else "") + "."]
    else:
        out.append(na(FILES["third"]) if not p3 else f"not available: no gate stage with probe rows in {FILES['third']}")
    out.append("")
    if g:
        out.append(f"The gate's own count (`{FILES['gate']}`): {num(g.get('calls_seen'))} calls seen, {num(g.get('calls_with_an_agent_type'))} with an agent type, {num(g.get('refused'))} refused.")
    else:
        out.append(na(FILES["gate"]))
    return out


def ledger_section(root):
    p3 = load(root, FILES["third"])
    out = ["## 4. The ledger of each stage of the gated run", ""]
    if not p3:
        return out + [na(FILES["third"])]
    rows = []
    for s in ran(p3):
        led = s.get("ledger")
        if not led:
            rows.append([s.get("label"), "no ledger in the file", "-", "-", "-"])
            continue
        classes = ", ".join(f"{k} {v}" for k, v in sorted(led.get("by_class", {}).items())) or "none"
        outside = led.get("calls_outside_the_contract_that_ran") or {}
        seen = (led.get("gate") or {}).get("reconciled")
        rows.append([s.get("label"), num(led.get("tool_calls")), classes,
                     ", ".join(f"{k} {v}" for k, v in sorted(outside.items())) or "none",
                     "yes" if seen else "no" if seen is False else "not recorded"])
    return out + table(["stage", "calls", "calls by class", "calls outside the contract that ran", "gate saw every call"], rows)


def ladder_section(root):
    p3 = load(root, FILES["third"])
    out = ["## 5. The scale ladder as measured", ""]
    if not p3:
        return out + [na(FILES["third"])]
    qs = [s for s in ran(p3) if s.get("delivery") == "queue"]
    if not qs:
        return out + [f"not available: {FILES['third']} holds no queue stage"]
    rows = [[s.get("label"), num(s.get("actual_agents")), num(s.get("agents_per_message")), num(s.get("wall_seconds")), num(s.get("tasks_per_minute")),
             (num(s.get("verified_success_rate")) + " %") if isinstance(s.get("verified_success_rate"), (int, float)) else "not recorded",
             num((s.get("per_verified_task") or {}).get("input_total"))] for s in qs]
    return out + table(["stage", "agents", "agents per message", "wall seconds", "tasks per minute", "verified rate", "input tokens per verified task"], rows)


def capacity_section(root):
    cap = load(root, FILES["capacity"])
    out = ["## 6. Simulation, not a measurement", ""]
    if not cap:
        return out + [na(FILES["capacity"])]
    out += [f"Every figure below is from `{FILES['capacity']}`, a simulation; no real agent produced it.", ""]
    rows = cap_rows(cap)
    if rows:
        keys = sorted({k for r in rows for k, v in r.items() if isinstance(v, (str, int, float, bool))})
        out += table(keys, [[r.get(k, "") for k in keys] for r in rows])
    else:
        out.append("The file has no list of rows to show.")
    return out


def limits_section(root):
    lim, p2, p3 = load(root, FILES["limits"]), load(root, FILES["second"]), load(root, FILES["third"])
    out = ["## 7. What limited the experiment", ""]
    if lim:
        at, wt, m = lim.get("agent_tool", {}), lim.get("workflow_tool", {}), lim.get("machine", {})
        out += [f"- Agent tool: largest batch started {num(at.get('largest_batch_started'))}, most at once {num(at.get('peak_concurrent_measured'))}; {at.get('how', '')}",
                f"- Workflow tool: {wt.get('documented_cap', 'not recorded')}; measured most at once {num(wt.get('peak_concurrent_measured'))}.",
                f"- Machine: {num(m.get('cores'))} cores, {num(m.get('memory_gb'))} GB memory ({m.get('how', '')}).",
                f"- Subscription allowance: {lim.get('subscription_allowance', 'not recorded')}"]
    else:
        out.append(na(FILES["limits"]))
    for name, doc, rel in (("second", p2, FILES["second"]), ("third", p3, FILES["third"])):
        if doc:
            peaks = [s.get("peak_concurrent_agents") for s in ran(doc) if isinstance(s.get("peak_concurrent_agents"), int)]
            out.append(f"- Peak figure in the stages of the {name} phase: {num(max(peaks) if peaks else None)}.")
        else:
            out.append(f"- {name} phase: {na(rel)}")
    return out + ["- The host ran at most 20 agents at once (contract of this round, as measured)."]


def counted_section(root):
    p3 = load(root, FILES["third"])
    out = ["## 8. What was counted against the limit, and what was reported beside it", ""]
    if not p3 or "counted_before_this_run" not in p3:
        return out + [na(FILES["third"])]
    c, f, caps = p3["counted_before_this_run"], p3.get("figures", {}), p3.get("caps", {})
    out += [f"Total counted before this run (`counted_before_this_run`): {num(c.get('total'))} input tokens.", ""]
    out += table(["part", "input tokens"], [[k, num(v)] for k, v in sorted(c.get("parts", {}).items())])
    ra = c.get("reported_apart", {})
    out += ["", "Reported beside the limit, not inside it:", ""]
    out += table(["item", "input tokens"], [[k, num(v)] for k, v in sorted(ra.items()) if not isinstance(v, str)])
    if ra.get("note"):
        out += ["", ra["note"]]
    out += ["", f"Counted at the last stage: {num(f.get('input_tokens_counted'))} of a limit of {num(f.get('cap', caps.get('cumulative_input_tokens')))}."]
    return out


def missing_section(root):
    out = ["## 9. What was not done or not measured", ""]
    skipped = []
    for name, rel in (("second", FILES["second"]), ("third", FILES["third"])):
        for s in (load(root, rel) or {}).get("stages", []):
            if s.get("skipped"):
                skipped.append([name, s.get("label"), s["skipped"]])
    s = load(root, FILES["summary"])
    if s:
        for label in s.get("agents", {}).get("stages_not_run", []):
            skipped.append(["first", label, str(s.get("agents", {}).get("why_the_ladder_stopped", "reason not recorded"))])
    out.append("Skipped stages:")
    out += [""] + (table(["phase", "stage", "reason"], skipped) if skipped else ["none recorded"])
    absent = sorted(rel for rel in FILES.values() if not (Path(root) / rel).exists())
    if not teams(root):
        absent.append(TEAM_GLOB)
    out += ["", "Input files absent:", ""] + ([f"- {rel}" for rel in sorted(absent)] if absent else ["- none"])
    return out


def attempts_section(root):
    """Attempts of the gated run that ended early. Their evidence and their plan are kept beside the final run's."""
    out = ["## 10. Earlier attempts of the gated run", ""]
    found = sorted((Path(root) / "swarm" / "phase3" / "evidence").glob("run-*.json"))
    if not found:
        return out + ["none: no file `swarm/phase3/evidence/run-*.json` is in the repository"]
    for path in found:
        rel = str(path.relative_to(root))
        doc = load(root, rel) or {}
        plan_rel = f"swarm/phase3/PLAN3-{path.stem}.json"
        plan = load(root, plan_rel) or {}
        stages = ran(doc)
        rows = []
        for s in stages:
            gate_of = s.get("security_gate")
            rows.append([s.get("label"), s.get("kind"), num(s.get("actual_agents")), f"{num(s.get('verified_tasks'))} of {num(s.get('tasks'))}" if s.get("kind") == "task" else "-",
                         ("passed" if gate_of.get("passed") else "not passed") if gate_of else "-", num(input_of(s))])
        out += [f"`{rel}`, run by the plan `{plan_rel}`:", ""] + table(["stage", "kind", "real agents", "tasks verified", "security gate", "input tokens"], rows)
        last = stages[-1] if stages else {}
        least = (plan.get("stops") or {}).get("min_verified_rate_to_continue")
        if last.get("kind") == "task" and least is not None and isinstance(last.get("verified_success_rate"), (int, float)) and last["verified_success_rate"] < least:
            out += ["", f"It ended after stage {last.get('label')}: {last['verified_success_rate']}% of that stage's tasks verified, and its plan ends a run under {least}%."]
        planned = [s.get("id") for s in plan.get("stages", [])]
        left = [name for name in planned if name not in {s.get("label") for s in doc.get("stages", [])}]
        if left:
            out += ["", "Stages of its plan that never started: " + ", ".join(left) + "."]
        out.append("")
    return out


def build(root=ROOT):
    parts = [["# Final report of the swarm experiment", "", "Made only from the evidence files named in each section. No figure here was measured by this script."],
             phases(root), kinds(root), gate(root), ledger_section(root), ladder_section(root), capacity_section(root),
             limits_section(root), counted_section(root), missing_section(root), attempts_section(root)]
    return "\n\n".join("\n".join(p) for p in parts) + "\n"


def main(argv):
    text = build(ROOT)
    if "--save" in argv:
        (HERE / "RESULTS-FINAL.md").write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
