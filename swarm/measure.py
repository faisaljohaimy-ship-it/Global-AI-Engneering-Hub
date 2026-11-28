#!/usr/bin/env python3
"""Measure what agents actually consumed, from the records the host keeps of each one.

    python3 swarm/measure.py agents OUT.json RECORD...          one row per agent record
    python3 swarm/measure.py stage OUT.json --agents A.json --check C.json --label L
                             [--main RECORD --from ISO --to ISO] [--samples S.jsonl] [--baseline SECONDS]
    python3 swarm/measure.py sample OUT.jsonl --seconds N       record load and memory once a second

Token figures are the usage numbers the API returned with every model reply, summed once
per reply. They are real counts for the agents measured. They say nothing about how much
of a subscription allowance was used, which the host does not show.

A record is the JSONL file the host writes for an agent. Nothing from a record is copied
into the output except counts, times, tool names and the task id found in the prompt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HELPERS = {"hr": r"(^|[\s;&|(])hr\s+(run|put|get|verify)\b", "sym": r"(^|[\s;&|(])sym\s+(overview|def|refs|check)\b",
           "ast-grep": r"\bast-grep\s+run\b", "ripgrep": r"(^|[\s;&|(])rg\s", "repomix": r"\brepomix\b",
           "script": r"\bpython3?\s+(-I\s+)?(-c\b|-\s|<<)"}
TASK = re.compile(r"\b([A-Z]-\d{4}|[A-D]-v\d)\b")
LIMIT_WORDS = re.compile(r"usage limit|rate limit|overloaded|quota|credit balance", re.I)


def moment(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def read(path: Path, start: float | None = None, end: float | None = None) -> dict:
    """Sum one record. With start and end, only replies inside that window are counted."""
    replies: dict[str, dict] = {}
    tools: dict[str, int] = {}
    helpers = {name: 0 for name in HELPERS}
    reads: dict[str, int] = {}
    first = last = None
    task = model = None
    tool_output_chars = 0
    final_text = ""
    limit_hit = False
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            stamp = entry.get("timestamp")
            when = moment(stamp) if isinstance(stamp, str) else None
            if when is not None and ((start is not None and when < start) or (end is not None and when > end)):
                continue
            if when is not None:
                first = when if first is None else min(first, when)
                last = when if last is None else max(last, when)
            message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
            content = message.get("content")
            blocks = content if isinstance(content, list) else []
            if entry.get("type") == "user":
                if task is None:
                    text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in blocks if isinstance(b, dict))
                    found = TASK.search(text or "")
                    task = found.group(1) if found else None
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        inner = block.get("content")
                        tool_output_chars += len(inner) if isinstance(inner, str) else sum(len(b.get("text", "")) for b in inner or [] if isinstance(b, dict))
            elif entry.get("type") == "assistant":
                if message.get("usage"):
                    replies[message.get("id") or entry.get("requestId") or str(len(replies))] = message["usage"]
                    model = message.get("model") or model
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        final_text = block.get("text", "")
                        limit_hit = limit_hit or bool(entry.get("isApiErrorMessage") and LIMIT_WORDS.search(final_text))
                    elif block.get("type") == "tool_use":
                        tools[block.get("name")] = tools.get(block.get("name"), 0) + 1
                        given = block.get("input") or {}
                        if block.get("name") == "Bash":
                            for name, pattern in HELPERS.items():
                                helpers[name] += bool(re.search(pattern, given.get("command", "")))
                        elif block.get("name") == "Read":
                            reads[given.get("file_path", "")] = reads.get(given.get("file_path", ""), 0) + 1
    total = {key: sum(int(u.get(key) or 0) for u in replies.values())
             for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")}
    all_input = total["input_tokens"] + total["cache_creation_input_tokens"] + total["cache_read_input_tokens"]
    return {"record": path.stem, "task": task, "model": model, "start": first, "end": last,
            "seconds": round(last - first, 2) if first is not None and last is not None else None,
            "roundtrips": len(replies), "input_uncached": total["input_tokens"], "cache_write": total["cache_creation_input_tokens"],
            "cache_read": total["cache_read_input_tokens"], "input_total": all_input, "output": total["output_tokens"],
            "cache_read_share": round(total["cache_read_input_tokens"] / all_input, 4) if all_input else None,
            "tool_calls": sum(tools.values()), "tools": tools, "helpers": {k: v for k, v in helpers.items() if v},
            "repeated_reads": sum(count - 1 for count in reads.values() if count > 1), "tool_output_chars": tool_output_chars,
            "final_reply": final_text.strip()[:24], "limit_error": limit_hit}


def peak(rows: list[dict]) -> int:
    """The largest number of agents whose first-to-last activity overlapped."""
    edges = sorted([(r["start"], 1) for r in rows if r["start"]] + [(r["end"], -1) for r in rows if r["end"]])
    best = now = 0
    for _, step in edges:
        now += step
        best = max(best, now)
    return best


def stage(label: str, rows: list[dict], check: dict, main: dict | None, samples: list[dict], baseline: float | None) -> dict:
    wall = max(r["end"] for r in rows) - min(r["start"] for r in rows)
    own = sum(r["seconds"] for r in rows)
    add = lambda key: sum(r[key] for r in rows)  # noqa: E731
    verified, tasks = check["verified"], check["tasks"]
    out = {
        "label": label, "actual_agents": len(rows), "peak_concurrent_agents": peak(rows), "tasks": tasks, "verified_tasks": verified,
        "verified_success_rate": round(100 * verified / tasks, 1), "hidden_tests_passed": check["tests_passed"], "hidden_tests_total": check["tests_total"],
        "security_findings": check["security_findings"], "files_outside_contract": check["extra_files"], "mean_solution_lines": check["mean_lines"],
        "agents_replying_done": sum(r["final_reply"].upper().startswith("DONE") for r in rows), "agents_with_limit_error": sum(r["limit_error"] for r in rows),
        "wall_seconds": round(wall, 2), "sum_of_agent_seconds": round(own, 2), "effective_concurrency": round(own / wall, 2),
        "tasks_per_minute": round(60 * verified / wall, 2),
        "models": sorted({r["model"] for r in rows if r["model"]}),
        "agent_tokens": {"input_uncached": add("input_uncached"), "cache_write": add("cache_write"), "cache_read": add("cache_read"),
                         "input_total": add("input_total"), "output": add("output"), "total": add("input_total") + add("output")},
        "cache_read_share": round(add("cache_read") / add("input_total"), 4) if add("input_total") else None,
        "model_roundtrips": add("roundtrips"), "tool_calls": add("tool_calls"), "repeated_file_reads": add("repeated_reads"),
        "tool_output_chars": add("tool_output_chars"),
        "per_verified_task": {"input_total": round(add("input_total") / verified) if verified else None, "output": round(add("output") / verified) if verified else None,
                              "roundtrips": round(add("roundtrips") / verified, 2) if verified else None, "agent_seconds": round(own / verified, 2) if verified else None},
        "helper_calls": {name: sum(r["helpers"].get(name, 0) for r in rows) for name in HELPERS if any(r["helpers"].get(name) for r in rows)},
    }
    if baseline:
        speedup = baseline * tasks / wall
        out["speedup_against_one_agent"] = round(speedup, 2)
        out["parallel_efficiency"] = round(speedup / len(rows), 3)
    if main:
        out["orchestrator_tokens"] = {k: main[k] for k in ("input_uncached", "cache_write", "cache_read", "input_total", "output", "roundtrips")}
        out["orchestrator_share_of_all_tokens"] = round((main["input_total"] + main["output"]) / (main["input_total"] + main["output"] + out["agent_tokens"]["total"]), 3)
    if samples:
        out["machine"] = {"samples": len(samples), "peak_load_1m": max(s["load1"] for s in samples), "least_memory_available_mb": min(s["mem_available_mb"] for s in samples),
                          "peak_host_process_rss_mb": max(s["host_rss_mb"] for s in samples),
                          "host_process_cpu_seconds": round(samples[-1]["host_cpu_seconds"] - samples[0]["host_cpu_seconds"], 1)}
    return out


def sample(out: Path, seconds: int) -> None:
    pid = int(os.environ.get("CLAUDE_PID", "0") or 0)
    ticks = os.sysconf("SC_CLK_TCK")
    with out.open("w", encoding="utf-8") as handle:
        for _ in range(seconds):
            memory = dict(line.split(":")[0:2] for line in Path("/proc/meminfo").read_text().splitlines()[:5])
            row = {"t": round(time.time(), 1), "load1": float(Path("/proc/loadavg").read_text().split()[0]),
                   "mem_available_mb": int(memory["MemAvailable"].split()[0]) // 1024, "host_rss_mb": 0, "host_cpu_seconds": 0.0}
            try:
                stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                row["host_cpu_seconds"] = (int(stat[11]) + int(stat[12])) / ticks
                row["host_rss_mb"] = int(stat[21]) * os.sysconf("SC_PAGE_SIZE") // 2**20
            except (OSError, IndexError, ValueError):
                pass
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("agents")
    one.add_argument("out", type=Path)
    one.add_argument("records", nargs="+", type=Path)
    many = commands.add_parser("stage")
    many.add_argument("out", type=Path)
    many.add_argument("--agents", type=Path, required=True)
    many.add_argument("--check", type=Path, required=True)
    many.add_argument("--label", required=True)
    many.add_argument("--main", type=Path)
    many.add_argument("--from", dest="start")
    many.add_argument("--to", dest="end")
    many.add_argument("--samples", type=Path)
    many.add_argument("--baseline", type=float)
    sampler = commands.add_parser("sample")
    sampler.add_argument("out", type=Path)
    sampler.add_argument("--seconds", type=int, default=600)
    args = parser.parse_args()
    if args.command == "sample":
        sample(args.out, args.seconds)
        return 0
    if args.command == "agents":
        rows = [read(path) for path in args.records]
        args.out.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
        print(len(rows), "records;", sum(r["input_total"] for r in rows), "input tokens,", sum(r["output"] for r in rows), "output tokens")
        return 0
    rows = json.loads(args.agents.read_text())
    main_row = read(args.main, moment(args.start), moment(args.end)) if args.main and args.start and args.end else None
    samples = [json.loads(line) for line in args.samples.read_text().splitlines()] if args.samples and args.samples.exists() else []
    result = stage(args.label, rows, json.loads(args.check.read_text()), main_row, samples, args.baseline)
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("label", "actual_agents", "peak_concurrent_agents", "verified_tasks", "wall_seconds", "effective_concurrency", "tasks_per_minute")}))
    print("tokens", result["agent_tokens"], "| per task", result["per_verified_task"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
