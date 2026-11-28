#!/usr/bin/env python3
"""Drive the second phase one stage at a time: prepare before the agents start, score after.

    python3 swarm/phase2/stage.py setup        install the worker's command and its gate, find the host's records
    python3 swarm/phase2/stage.py plan         the stages in order, and where the experiment stands
    python3 swarm/phase2/stage.py prep [ID]    write the next stage's tasks, claim them, print what to launch
    python3 swarm/phase2/stage.py finish       score the open stage, record it, and name the next stage or the end
    python3 swarm/phase2/stage.py report       rewrite RESULTS.md and the state files from the evidence

The agents themselves are started by the agent host, not by this script: a script cannot
start a real agent. Everything measured comes from the records the host keeps of each
agent, from the withheld tests, and from the worker command's own count of what it printed.

The plan, the limits and the rules for stopping are in PLAN.json, written before the first
agent of this phase ran. The first phase's files are read and never written.

Private working files are under SWARM_HOME/p2 (default ~/.gaie-swarm/p2), outside any
repository. What is written into the repository holds counts, times and tool names only.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import guard  # noqa: E402
import measure  # noqa: E402
import scheduler  # noqa: E402
import tasks  # noqa: E402

HOME = Path(os.environ.get("SWARM_HOME", Path.home() / ".gaie-swarm")) / "p2"
BIN = Path(os.environ.get("SWARM_BIN", "/usr/local/bin"))
PLAN = json.loads((HERE / "PLAN.json").read_text())
RESULTS = HOME / "results.json"
OUT = Path(os.environ.get("SWARM_REPORT_DIR", HERE))  # where the public files go; the tests point it elsewhere
EVIDENCE = OUT / "evidence" / "stages.json"
ALIASES = ("haiku", "sonnet", "opus", "fable")
GUARDED = ("swarm-light", "swarm-light-2", "swarm-light-inline", "swarm-large", "swarm-probe")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def spec_of(ident: str) -> dict:
    return next(stage for stage in PLAN["stages"] if stage["id"] == ident)


def load() -> list[dict]:
    return json.loads(RESULTS.read_text())["stages"] if RESULTS.exists() else []


def locate() -> tuple[Path, Path]:
    """The host's record of this session and the folder of its agents' records."""
    main = os.environ.get("SWARM_MAIN_RECORD")
    if not main:
        session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        # A session that changed its working folder has a record under each; the one being written is the newest.
        newest = lambda paths: sorted(paths, key=lambda p: p.stat().st_mtime)[-1:]  # noqa: E731
        found = newest(Path.home().glob(f".claude/projects/*/{session}.jsonl")) if session else []
        found = found or newest(Path.home().glob(".claude/projects/*/*.jsonl"))
        if not found:
            raise SystemExit("no session record found: set SWARM_MAIN_RECORD and SWARM_RECORDS")
        main = found[-1]
    main = Path(main)
    return main, Path(os.environ.get("SWARM_RECORDS") or main.with_suffix("") / "subagents")


def records(folder: Path) -> list[Path]:
    return sorted(folder.glob("agent-*.jsonl")) or sorted(p for p in folder.glob("*.output") if p.stat().st_size)


def alias(model: str | None) -> str:
    return next((name for name in ALIASES if name in str(model).lower()), "other")


def extra(path: Path) -> dict:
    """What the first phase's reader does not collect: the first request, cache writes by lifetime, and the tool contract."""
    usages: dict[str, dict] = {}
    order, bash, other, results = [], [], {}, {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        if entry.get("type") == "assistant":
            if message.get("usage"):
                key = message.get("id") or entry.get("requestId") or str(len(usages))
                if key not in usages:
                    order.append(key)
                usages[key] = message["usage"]
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    if block.get("name") == "Bash":
                        bash.append((block.get("id"), str((block.get("input") or {}).get("command", ""))))
                    elif block.get("name") not in ("SubagentHandback", "StructuredOutput"):
                        other[block.get("name")] = other.get(block.get("name"), 0) + 1
        elif entry.get("type") == "user":
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    inner = block.get("content")
                    text = inner if isinstance(inner, str) else " ".join(b.get("text", "") for b in inner or [] if isinstance(b, dict))
                    results[block.get("tool_use_id")] = text[:400]
    size = lambda usage: sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))  # noqa: E731
    first = usages[order[0]] if order else {}
    short = long = unknown = 0
    for usage in usages.values():
        split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else None
        if split:
            short += int(split.get("ephemeral_5m_input_tokens") or 0)
            long += int(split.get("ephemeral_1h_input_tokens") or 0)
        else:
            unknown += int(usage.get("cache_creation_input_tokens") or 0)
    kept = refused = foreign = 0
    for call, command in bash:
        if guard.allowed(command):
            kept += 1
        elif guard.MARK in results.get(call, ""):
            refused += 1
        else:
            foreign += 1
    meta = path.with_name(path.stem + ".meta.json")
    try:
        kind = json.loads(meta.read_text()).get("agentType")
    except (OSError, ValueError, AttributeError):
        kind = None
    return {"first_context": size(first) if first else None, "first_cache_read": int(first.get("cache_read_input_tokens") or 0), "write_5m": short,
            "write_1h": long, "write_unknown": unknown, "swk_calls": kept, "refused_calls": refused, "foreign_calls": foreign, "other_tools": other,
            "agent_type": kind}


def cost_units(row_or_sum: dict) -> int:
    """One number for cost, in units of one uncached input token, from the weights in PLAN.json. An assumption, stated there."""
    weight = PLAN["cost_weights"]
    return round(row_or_sum["input_uncached"] + weight["cache_write_5m"] * (row_or_sum["write_5m"] + row_or_sum["write_unknown"])
                 + weight["cache_write_1h"] * row_or_sum["write_1h"] + weight["cache_read"] * row_or_sum["cache_read"] + weight["output"] * row_or_sum["output"])


def decide(stages: list[dict], spec: dict | None) -> tuple[list[str], list[str], list[str], dict]:
    """Reasons to end everything, reasons to skip the stage asked about, things to note, and the figures used."""
    caps, stops = PLAN["caps"], PLAN["stops"]
    ran = [s for s in stages if not s.get("skipped")]
    spent_in = caps["spent_before_phase2"] + caps["preflight_input_tokens"] + sum(s["agent_tokens"]["input_total"] for s in ran)
    spent_out = sum(s["agent_tokens"]["output"] for s in ran)
    runs = sum(s["actual_agents"] for s in ran)
    end, skip, notes = [], [], []
    last = ran[-1] if ran else None
    if last:
        if last.get("agents_with_limit_error"):
            end.append(f"{last['agents_with_limit_error']} agents of {last['label']} met a usage or rate limit")
        if last.get("foreign_calls") and last.get("agent_type") in GUARDED and last.get("guard_enforced") is not False:
            end.append(f"a worker of {last['label']} ran {last['foreign_calls']} commands outside its contract")
        if last.get("kind") == "probe" and not last.get("allowed_command_ran"):
            end.append("the worker's own command did not run in the probe, so no worker could work")
        if last.get("kind") == "task":
            if last["actual_agents"] * 2 < last["registered_agents"]:
                end.append(f"the host started only {last['actual_agents']} of {last['registered_agents']} agents of {last['label']}")
            if last["verified_success_rate"] < stops["min_verified_rate_to_continue"]:
                end.append(f"only {last['verified_success_rate']}% of the tasks of {last['label']} verified")
            elif last["verified_success_rate"] < stops["note_verified_rate_below"]:
                notes.append(f"{last['verified_success_rate']}% of the tasks of {last['label']} verified")
            if last["security_findings"] > stops["max_security_findings"]:
                end.append(f"{last['security_findings']} security findings in the output of {last['label']}")
            if last["wall_seconds"] > stops["max_stage_wall_seconds"]:
                end.append(f"{last['label']} took {last['wall_seconds']} s")
            machine = last.get("machine") or {}
            if machine and machine["least_memory_available_mb"] < stops["min_memory_available_mb"]:
                end.append(f"memory fell to {machine['least_memory_available_mb']} MB during {last['label']}")
            if machine and machine["peak_host_process_rss_mb"] > stops["max_host_process_rss_mb"]:
                end.append(f"the host process reached {machine['peak_host_process_rss_mb']} MB during {last['label']}")
            if last["peak_concurrent_agents"] < last["actual_agents"]:
                notes.append(f"{last['label']}: {last['peak_concurrent_agents']} agents ran at once out of {last['actual_agents']}")
    if spent_out > caps["phase2_output_tokens"]:
        end.append(f"{spent_out:,} output tokens spent, past {caps['phase2_output_tokens']:,}")
    figures = {"input_tokens_counted": spent_in, "cap": caps["cumulative_input_tokens"], "agents_started_in_phase_2": runs, "projected_for_stage": None}
    if spec:
        model = resolve(spec, stages)
        alike = [s for s in ran if s.get("size") == spec.get("size") and s.get("agent_type") == spec["agent_type"] and s.get("model") == model and s["actual_agents"]]
        if alike:
            figures["projected_for_stage"] = round(alike[-1]["agent_tokens"]["input_total"] / alike[-1]["actual_agents"] * spec["agents"])
            if spent_in + figures["projected_for_stage"] > caps["cumulative_input_tokens"]:
                skip.append(f"{spent_in:,} input tokens counted; {spec['id']} is projected at {figures['projected_for_stage']:,}, past the limit of {caps['cumulative_input_tokens']:,}")
        elif spent_in + stops["margin_without_projection"] > caps["cumulative_input_tokens"]:
            skip.append(f"{spent_in:,} input tokens counted and nothing to project {spec['id']} from")
        if runs + spec["agents"] > caps["phase2_agent_runs"]:
            skip.append(f"{runs} agents started; {spec['agents']} more would pass {caps['phase2_agent_runs']}")
    return end, skip, notes, figures


def resolve(spec: dict, stages: list[dict]) -> str:
    """A stage may leave its model to a rule written in the plan: the lighter model if it verified enough of the trial stage."""
    rule = spec["model"]
    if isinstance(rule, str):
        return rule
    trial = next((s for s in stages if s["label"] == rule["after"] and not s.get("skipped")), None)
    return rule["light"] if trial is None or trial["verified_success_rate"] >= rule["at_least"] else rule["otherwise"]


def following(stages: list[dict]) -> tuple[dict | None, list[str]]:
    """The next stage of the plan that may start, recording the ones skipped on the way; or None and why it all ends."""
    done = {s["label"] for s in stages}
    for spec in PLAN["stages"]:
        if spec["id"] in done:
            continue
        end, skip, _, _ = decide(stages, spec)
        if end:
            return None, end
        if skip:
            stages.append({"label": spec["id"], "skipped": "; ".join(skip)})
            done.add(spec["id"])
            continue
        return spec, []
    return None, ["every stage of the plan has been run or skipped"]


def save(stages: list[dict]) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps({"stages": stages}, indent=1) + "\n")
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    _, _, _, figures = decide(stages, None)
    public = {"about": "Second phase of the swarm experiment. Counts, times and tool names from the host's records of real agents; no record content.",
              "plan_sha256": __import__("hashlib").sha256((HERE / "PLAN.json").read_bytes()).hexdigest(), "caps": PLAN["caps"], "figures": figures, "stages": stages}
    EVIDENCE.write_text(json.dumps(public, indent=1) + "\n")


def cross_check(folder: Path, name: str, expected: list[str]) -> dict:
    """Ask the language server, through the skill's `sym`, who calls one function, and compare with the shared index."""
    sym = shutil.which("sym") or str(Path.home() / ".gaie-tools" / "bin" / "sym")
    if not Path(sym).exists():
        return {"tool": None, "why": "the symbol tool is not installed"}
    module = tasks.index(folder)["functions"][name]["module"]
    started = time.monotonic()
    try:
        done = subprocess.run([sym, "refs", name, f"inv/{module}.py"], cwd=folder, capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired):
        return {"tool": "serena", "answered": False}
    wanted = [caller.split(".")[1] for caller in expected]
    return {"tool": "serena", "answered": done.returncode == 0, "callers_in_the_index": len(wanted), "of_them_named_by_the_language_server": sum(w in done.stdout for w in wanted),
            "seconds": round(time.monotonic() - started, 1)}


def setup() -> int:
    for folder in ("work", "state", "samples", "runs"):
        (HOME / folder).mkdir(parents=True, exist_ok=True)
    os.chmod(HOME / "state", 0o700)
    for name, script in (("swk", "kit.py"), ("swk-guard", "guard.py")):
        target = BIN / name
        target.write_text(f"#!/bin/sh\nSWARM_HOME='{HOME.parent}' exec python3 -I '{HERE / script}' \"$@\"\n")
        target.chmod(0o755)
    main, folder = locate()
    import kit  # noqa: PLC0415

    hr = kit.headroom()
    facts = {"worker_command": shutil.which("swk") is not None, "gate": shutil.which("swk-guard") is not None,
             "session_record_found": main.exists(), "agent_records_folder_found": folder.exists(), "agent_records_now": len(records(folder)) if folder.exists() else 0,
             "no_network_cage": subprocess.run(["unshare", "-n", "true"], capture_output=True).returncode == 0,
             "headroom": f"SDK {hr.hub_module().VERSION} behind {hr.BOUNDARY}" if hr else "not installed: lean test output falls back to a plain summary",
             "serena": bool(shutil.which("sym") or (Path.home() / ".gaie-tools" / "bin" / "sym").exists()),
             "agent_definitions": sorted(p.stem for p in (HERE.parents[1] / ".claude" / "agents").glob("swarm-*.md")),
             "cores": os.cpu_count(), "host_process_known": bool(os.environ.get("CLAUDE_PID"))}
    (HOME / "env.json").write_text(json.dumps(facts, indent=1))
    print(json.dumps(facts, indent=1))
    return 0 if facts["worker_command"] and facts["gate"] and facts["session_record_found"] else 1


def card(spec: dict, model: str, ids: list[str], out: Path) -> str:
    """What the orchestrator must launch, word for word."""
    lines = [f"STAGE {spec['id']}: start {spec['agents']} agents, all in ONE message, in the foreground.",
             f"  subagent_type: {spec['agent_type']}   model: {model}   effort: {spec['effort']}"]
    if spec["kind"] == "probe":
        lines += ["  prompts, one agent each, exactly:", *[f"    {prompt}" for prompt in spec["prompts"]]]
    elif spec["delivery"] == "id":
        lines += ["  prompt of each agent: its task id and nothing else. One agent per id:", "    " + " ".join(ids)]
    elif spec["delivery"] == "general":
        lines += ["  prompt of each agent, with its own id in place of ID. One agent per id:", "    " + " ".join(ids), "",
                  "    Task ID. Run `swk show ID` to read it. Hand in the whole Python file with one command: `swk submit ID <<'PY'`, the file, then `PY` on a line "
                  "of its own. If the reply names a failure, correct the file and hand it in again. Use no other tool and no other command. "
                  "Final answer: the single word DONE, or FAILED if no attempts are left."]
    else:
        lines.append("  prompt of each agent: the whole text between its two rules below, unchanged.")
        for ident in ids:
            lines += [f"  ----- prompt for {ident} -----", (out / ident / "TASK.md").read_text().rstrip(), "  ----- end -----"]
    lines.append("When every agent has returned, run: python3 swarm/phase2/stage.py finish")
    return "\n".join(lines)


def prep(ident: str | None) -> int:
    stages = load()
    if (HOME / "open").exists():
        raise SystemExit(f"stage {(HOME / 'open').read_text()} is open: finish it first")
    if ident:
        spec, end = spec_of(ident), decide(stages, spec_of(ident))[0]
    else:
        spec, end = following(stages)
        save(stages)
    if spec is None or end:
        print("END -", "; ".join(end))
        return 1
    model, out, ids = resolve(spec, stages), HOME / "work" / spec["id"], []
    out.mkdir(parents=True, exist_ok=True)
    if spec["kind"] == "task":
        ids = [item["id"] for item in tasks.make(out, spec["size"], spec["first"], spec["tasks"], spec.get("mode", "lean"), PLAN["seed"])]
        scheduler.own(HOME / "state", spec["id"], ids)
    (HOME / "current").write_text(spec["id"])
    checked = None
    if spec.get("size") == "large" and spec.get("mode") == "lean":  # one project per lean stage: does the index agree with the language server?
        truth = json.loads((out / ".hidden" / f"{ids[0]}.json").read_text())["truth"]
        checked = cross_check(out / ids[0], truth["fixed_function"].split(".")[1], json.loads((out / ".kit" / f"{ids[0]}.index.json").read_text())["callers"][truth["fixed_function"].split(".")[1]])
    main, folder = locate()
    sampler = subprocess.Popen([sys.executable, str(HERE.parent / "measure.py"), "sample", str(HOME / "samples" / f"{spec['id']}.jsonl"), "--seconds", "1500"],
                               start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (HOME / "runs" / f"{spec['id']}.json").write_text(json.dumps({"stage": spec["id"], "model": model, "tasks": ids, "start": now(), "sampler": sampler.pid, "index_cross_check": checked,
                                                                  "before": [p.name for p in records(folder)] if folder.exists() else []}))
    (HOME / "open").write_text(spec["id"])
    print(card(spec, model, ids, out))
    return 0


def total(rows: list[dict], key: str) -> int:
    return sum(row[key] or 0 for row in rows)


def finish() -> int:
    ident = (HOME / "open").read_text().strip()
    spec, run, end_time = spec_of(ident), json.loads((HOME / "runs" / f"{ident}.json").read_text()), now()
    try:  # the process id comes from a file, so make sure it still is the sampler before stopping it
        command = Path(f"/proc/{run['sampler']}/cmdline").read_bytes()
        if b"measure.py" in command and b"sample" in command:
            os.killpg(run["sampler"], signal.SIGTERM)
    except (OSError, ProcessLookupError, PermissionError):
        pass
    main, folder = locate()
    rows = []
    for path in records(folder):
        if path.name not in run["before"]:
            row = {**measure.read(path), **extra(path)}
            if row["roundtrips"] and (spec["kind"] == "probe" or row["task"] in run["tasks"]):
                rows.append(row)
    stages = load()
    out = HOME / "work" / ident
    main_row = measure.read(main, measure.moment(run["start"]), measure.moment(end_time))
    sample_file = HOME / "samples" / f"{ident}.jsonl"
    samples = [json.loads(line) for line in sample_file.read_text().splitlines() if line.strip()] if sample_file.exists() else []
    sums = {key: total(rows, key) for key in ("input_uncached", "cache_read", "output", "write_5m", "write_1h", "write_unknown")}
    contexts = sorted(row["first_context"] for row in rows if row["first_context"])
    common = {"kind": spec["kind"], "size": spec.get("size"), "agent_type": spec["agent_type"], "model": run["model"], "effort": spec["effort"],
              "mode": spec.get("mode"), "delivery": spec.get("delivery"), "registered_agents": spec["agents"], "started": run["start"], "finished": end_time,
              "first_request_context": {"median": round(statistics.median(contexts)), "least": contexts[0], "most": contexts[-1]} if contexts else None,
              "first_request_read_from_cache": round(total(rows, "first_cache_read") / max(1, sum(contexts)), 4),
              "cache_written": {"five_minutes": sums["write_5m"], "one_hour": sums["write_1h"], "lifetime_not_reported": sums["write_unknown"]},
              "cost_units": cost_units(sums) if rows else 0, "swk_calls": total(rows, "swk_calls"), "refused_calls": total(rows, "refused_calls"),
              "foreign_calls": total(rows, "foreign_calls"), "other_tool_calls": sum(sum(row["other_tools"].values()) for row in rows),
              "agent_types_in_records": sorted({str(row["agent_type"]) for row in rows}),
              "replies_per_agent": {"median": statistics.median(r["roundtrips"] for r in rows), "most": max(r["roundtrips"] for r in rows)} if rows else None}
    if spec["kind"] == "probe" or not rows:
        result = {"label": ident, "actual_agents": len(rows), "agents_with_limit_error": sum(r["limit_error"] for r in rows),
                  "agent_tokens": {"input_uncached": sums["input_uncached"], "cache_write": total(rows, "cache_write"), "cache_read": sums["cache_read"],
                                   "input_total": total(rows, "input_total"), "output": sums["output"], "total": total(rows, "input_total") + sums["output"]},
                  "wall_seconds": round(max(r["end"] for r in rows if r["end"] is not None) - min(r["start"] for r in rows if r["start"] is not None), 2)
                  if any(r["start"] is not None and r["end"] is not None for r in rows) else 0, **common}
        if spec["kind"] == "probe":
            result["guard_enforced"] = bool(rows) and result["refused_calls"] >= 1 and result["foreign_calls"] == 0
            result["allowed_command_ran"] = result["swk_calls"] >= 1
        else:
            result.update(kind="task", verified_success_rate=0.0, security_findings=0, peak_concurrent_agents=0, tasks=spec["tasks"], verified_tasks=0)
    else:
        check = tasks.check(out)
        single = next((s for s in stages if s.get("kind") == "task" and s.get("size") == spec["size"] and s["actual_agents"] == 1 and s.get("tasks")), None)
        result = measure.stage(ident, rows, check, main_row, samples, single["wall_seconds"] / single["tasks"] if single else None)
        result["models"] = sorted({alias(model) for model in result["models"]})
        result.update(common)
        result.update(ownership=scheduler.submit(HOME / "state", ident, check), not_verified=[r["id"] for r in check["rows"] if not r["verified"]],
                      worker_command={"hand_ins": check["attempts"], "calls": check["kit_calls"], "characters_printed": check["kit_chars_out"],
                                      "headroom_views": check["kit_views"]},
                      per_verified_task_cost_units=round(result["cost_units"] / check["verified"]) if check["verified"] else None,
                      guard_enforced=next((s["guard_enforced"] for s in stages if s.get("kind") == "probe"), None), index_cross_check=run.get("index_cross_check"))
    stages = [s for s in stages if s["label"] != ident] + [result]
    (HOME / "open").unlink()
    nxt, end = following(stages)
    save(stages)
    _, _, notes, figures = decide(stages, nxt)
    show = {k: result.get(k) for k in ("actual_agents", "peak_concurrent_agents", "verified_tasks", "tasks", "wall_seconds", "tasks_per_minute", "model_roundtrips",
                                       "first_request_context", "first_request_read_from_cache", "refused_calls", "foreign_calls", "guard_enforced")}
    print(ident, json.dumps(show))
    print("  tokens", result["agent_tokens"], "| cost units", result["cost_units"], "| per verified task", result.get("per_verified_task"))
    print("  not verified:", " ".join(result.get("not_verified", [])) or "none", "| notes:", "; ".join(notes) or "none")
    print("  counted so far:", f"{figures['input_tokens_counted']:,}", "of", f"{figures['cap']:,}", "input tokens;", figures["agents_started_in_phase_2"], "agents in this phase")
    skipped = [s["label"] for s in stages if s.get("skipped")]
    if skipped:
        print("  skipped:", " ".join(skipped))
    print(f"NEXT {nxt['id']} (projected {figures['projected_for_stage']})" if nxt else "END - " + "; ".join(end))
    return 0


def plan() -> int:
    stages = {s["label"]: s for s in load()}
    for spec in PLAN["stages"]:
        state = stages.get(spec["id"])
        mark = "to do" if state is None else "skipped: " + state["skipped"] if state.get("skipped") else \
            f"ran: {state['actual_agents']} agents, {state['agent_tokens']['input_total']:,} input tokens"
        print(f"{spec['id']:6} {spec['kind']:5} {str(spec.get('size')):7} {spec['agents']:>3} x {spec['agent_type']:19} {mark}")
    _, _, _, figures = decide(list(stages.values()), None)
    print(figures)
    return 0


def report() -> int:
    data = json.loads(EVIDENCE.read_text())
    ran = [s for s in data["stages"] if not s.get("skipped")]
    work = [s for s in ran if s.get("kind") == "task"]
    cell = lambda value: "" if value is None else f"{value:,}" if isinstance(value, int) else str(value)  # noqa: E731
    lines = ["# Results of the second phase", "", "Generated by `stage.py report` from `evidence/stages.json`. Do not edit by hand.", "",
             "| Stage | Size | Worker | Model | Agents | At once | Verified | Seconds | Tasks/min | First request | Replies | Input tokens | Per verified task | Cost units per task |",
             "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in work:
        lines.append(f"| {s['label']} | {s['size']} | {s['agent_type']} | {s['model']} | {s['actual_agents']} | {s['peak_concurrent_agents']} | "
                     f"{s['verified_tasks']}/{s['tasks']} | {s['wall_seconds']} | {s['tasks_per_minute']} | {cell((s['first_request_context'] or {}).get('median'))} | "
                     f"{cell((s['replies_per_agent'] or {}).get('median'))} | {s['agent_tokens']['input_total']:,} | {cell(s['per_verified_task']['input_total'])} | "
                     f"{cell(s.get('per_verified_task_cost_units'))} |")
    lines += ["", "Skipped stages: " + ("; ".join(f"{s['label']} ({s['skipped']})" for s in data["stages"] if s.get("skipped")) or "none") + ".", "",
              f"Input tokens counted against the limit: {data['figures']['input_tokens_counted']:,} of {data['figures']['cap']:,} "
              f"(the first phase's {data['caps']['spent_before_phase2']:,} included). Agents started in this phase: {data['figures']['agents_started_in_phase_2']}.", ""]
    (OUT / "RESULTS.md").write_text("\n".join(lines))
    state = OUT / "state"
    state.mkdir(exist_ok=True)
    (state / "BENCHMARK_RESULTS.json").write_text(json.dumps({"stages": data["stages"]}, indent=1) + "\n")
    (state / "RESOURCE_METRICS.json").write_text(json.dumps({"caps": data["caps"], "figures": data["figures"], "stages": [
        {"stage": s["label"], "agent_tokens": s["agent_tokens"], "orchestrator_tokens": s.get("orchestrator_tokens"), "cost_units": s["cost_units"],
         "cache_written": s["cache_written"], "machine": s.get("machine"), "wall_seconds": s["wall_seconds"]} for s in ran]}, indent=1) + "\n")
    (state / "AGENT_STATUS.json").write_text(json.dumps({"stages": [
        {"stage": s["label"], "registered": s["registered_agents"], "started": s["actual_agents"], "ran_at_once": s.get("peak_concurrent_agents"),
         "replied_done": s.get("agents_replying_done"), "met_a_limit": s["agents_with_limit_error"], "refused_calls": s["refused_calls"],
         "foreign_calls": s["foreign_calls"]} for s in ran]}, indent=1) + "\n")
    (state / "TEST_EVIDENCE.json").write_text(json.dumps({"stages": [
        {"stage": s["label"], "tasks": s["tasks"], "verified": s["verified_tasks"], "withheld_tests_passed": s["hidden_tests_passed"],
         "withheld_tests": s["hidden_tests_total"], "security_findings": s["security_findings"], "not_verified": s.get("not_verified")} for s in work]}, indent=1) + "\n")
    task_state = {"store": "engineering_os.orchestration.TaskStore, in a private folder outside Git"}
    if (HOME / "state").exists() and work:
        (HOME / "checkpoints").mkdir(mode=0o700, exist_ok=True)
        task_state.update(work[-1]["ownership"], checkpoint=scheduler.checkpoint(HOME / "state", HOME / "checkpoints" / f"p2-{len(work)}.json"))
    (state / "TASK_STATE.json").write_text(json.dumps(task_state, indent=1) + "\n")
    done = [s["label"] for s in data["stages"]]
    left = [spec["id"] for spec in PLAN["stages"] if spec["id"] not in done]
    (state / "RESUME.txt").write_text(f"Second phase. Stages recorded: {' '.join(done) or 'none'}.\nStages left in the plan: {' '.join(left) or 'none'}.\n"
                                      "To go on, in a session that has the swarm-* agent types: python3 swarm/phase2/stage.py setup, then prep, launch the card, finish.\n"
                                      "Read swarm/phase2/RUNBOOK.md first. The private task store does not travel with the repository; a new session starts a new one.\n")
    print("\n".join(lines[:6 + len(work)]))
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "setup":
        return setup()
    if command == "plan":
        return plan()
    if command == "prep":
        return prep(sys.argv[2] if len(sys.argv) > 2 else None)
    if command == "finish":
        return finish()
    if command == "report":
        return report()
    print(__doc__.split("\n\n")[1])
    return 2


if __name__ == "__main__":
    sys.exit(main())
