#!/usr/bin/env python3
"""Every tool call of every agent, by name and by what became of it, and whether the gate saw them all.

    python3 swarm/phase3/ledger.py RECORD...                   the ledger of these agent records, as JSON
    python3 swarm/phase3/ledger.py --gate-log FILE RECORD...   the same, compared with the gate's own record

The second phase counted a worker's shell calls and lumped everything else together. A
general worker's call to a tool that reaches other sessions was therefore counted as
"another tool" and not named, and one stage's count missed calls the host itself flagged.
This ledger leaves nothing out: each tool call in a record is named and put in exactly
one class.

    worker command          a shell call the worker gate lets through
    refused by the gate     a call the gate refused (its mark is in what came back)
    refused by the host     a call the host itself denied
    foreign shell command   a shell call outside the worker's language that ran
    session tool            a tool that reaches another session or agent, and ran
    other tool              any other tool that ran
    hand-back               the host's own way of returning an agent's answer
    no result recorded      a call with no result line: the agent was stopped mid-call; it counts as outside
                            the contract that may have run unless a worker may make it (a worker command, the hand-back)

A stage is clean when the last three ran-classes above the hand-back are all zero for its
workers. With the gate's record it is also reconciled: the gate must have seen every call
the agents' records hold, no fewer. A gate that misses calls is not a gate.

Counts and tool names only. No command text and no content is kept.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2")]
import guard  # noqa: E402

HAND_BACK = ("SubagentHandback", "StructuredOutput")
SESSION_TOOL = re.compile(r"mcp__claude-code-remote__|^(SendMessage|ListAgents|Agent|Task|Workflow)$")
HOST_DENIAL = re.compile(r"permission to use|permission denied by|has been denied|not allowed to use|hook (blocked|denied)|was blocked|no such tool|is not available|unknown tool", re.I)
GATE_MARKS = ("swk-guard", "swk-lane-guard")
RAN = ("foreign shell command", "session tool", "other tool")
NO_RESULT = "no result recorded"
UNKNOWN = "type not recorded"


def scan(path: Path, with_asked: bool = False) -> tuple[list[dict], dict]:
    """The rows of a record and what was odd about it: lines that are not JSON, results with no call, call ids seen twice."""
    asked, came_back = [], {}
    odd = {"unreadable_lines": 0, "results_without_a_call": 0, "repeated_call_ids": 0, "repeated_result_ids": 0}
    try:
        text_of_record = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text_of_record = ""
    for line in text_of_record.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:  # a cut-off last line, or a line that is not JSON
            odd["unreadable_lines"] += 1
            continue
        if not isinstance(entry, dict):
            odd["unreadable_lines"] += 1
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        for block in message.get("content") if isinstance(message.get("content"), list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                given = block.get("input") if isinstance(block.get("input"), dict) else {}
                if block.get("id") is not None and any(block.get("id") == seen["id"] for seen in asked):  # one reply may be written on several lines
                    odd["repeated_call_ids"] += 1
                else:
                    asked.append({"id": block.get("id"), "name": str(block.get("name")), "command": given.get("command"), "path": given.get("file_path")})
            elif block.get("type") == "tool_result":
                inner = block.get("content")
                if isinstance(inner, str):
                    text = inner
                elif isinstance(inner, list):
                    text = " ".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in inner)
                else:
                    text = "" if inner is None else str(inner)
                key = block.get("tool_use_id")
                if key in came_back:
                    odd["repeated_result_ids"] += 1
                else:
                    came_back[key] = (text[:600], block.get("is_error") is True)
    rows = []
    for call in asked:
        name = call["name"]
        worker_may = name in HAND_BACK or (name == "Bash" and isinstance(call["command"], str) and guard.allowed(call["command"]))
        if call["id"] is None or call["id"] not in came_back:
            # stopped mid-call: nothing says whether it ran. Only what a worker may do leaves the ledger clean.
            rows.append({"tool": name, "class": NO_RESULT, "may_have_run_outside": not worker_may, "hand_back": name in HAND_BACK})
            continue
        text, failed = came_back[call["id"]]
        if name in HAND_BACK:
            kind = "hand-back"
        elif failed and any(mark in text for mark in GATE_MARKS):  # the same words in ordinary output of a command that ran are not a refusal
            kind = "refused by the gate"
        elif failed and HOST_DENIAL.search(text):
            kind = "refused by the host"
        elif name == "Bash":
            kind = "worker command" if worker_may else "foreign shell command"
        elif SESSION_TOOL.search(name):
            kind = "session tool"
        else:
            kind = "other tool"
        rows.append({"tool": name, "class": kind})
    odd["results_without_a_call"] = sum(1 for key in came_back if all(key != call["id"] for call in asked))
    if with_asked:  # one row was made for each call, in order
        for row, call in zip(rows, asked, strict=True):
            row["asked"] = call["command"] if call["name"] == "Bash" else call["path"]
    return rows, odd


def calls(path: Path) -> list[dict]:
    """One row per tool call of a record: the tool's name and its class."""
    return scan(path)[0]


def asked(path: Path) -> list[dict]:
    """The rows of `calls`, each with what it asked for: a shell call's command, a file tool's path. For a judge that must know
    whether an agent tried the one thing it was told to try. It is compared in memory and never written anywhere."""
    return scan(path, with_asked=True)[0]


def who(path: Path) -> str:
    """The short hash the gate writes for the agent this record belongs to: the record's file is named after the agent's id."""
    name = Path(path).stem
    return hashlib.sha256((name[6:] if name.startswith("agent-") else name).encode("utf-8", "replace")).hexdigest()[:10]


def agent_type(path: Path) -> str | None:
    try:
        kind = json.loads(Path(path).with_name(Path(path).stem + ".meta.json").read_text()).get("agentType")
    except (OSError, ValueError, AttributeError):
        return None
    return kind if isinstance(kind, str) and kind else None


def build(paths: list[Path], gate_lines: list[dict] | None = None) -> dict:
    by_class: dict[str, int] = {}
    by_tool: dict[str, int] = {}
    by_type: dict[str, int] = {}
    ran: dict[str, int] = {}
    odd_total = {"unreadable_lines": 0, "results_without_a_call": 0, "repeated_call_ids": 0, "repeated_result_ids": 0}
    empty = unknown = 0
    by_agent: dict[str, int] = {}
    for path in paths:
        recorded = agent_type(path)
        kind = recorded or UNKNOWN
        unknown += recorded is None
        rows, odd = scan(path)
        empty += not rows
        for name, count in odd.items():
            odd_total[name] += count
        by_agent.setdefault(who(path), 0)
        for row in rows:
            by_class[row["class"]] = by_class.get(row["class"], 0) + 1
            by_tool[row["tool"]] = by_tool.get(row["tool"], 0) + 1
            if row["class"] != "hand-back" and not row.get("hand_back") and row["class"] != "refused by the host":  # the host answers these itself, before any gate is asked
                by_type[kind] = by_type.get(kind, 0) + 1
                by_agent[who(path)] += 1
            if row["class"] in RAN or row.get("may_have_run_outside"):
                key = f"{row['class']}: {row['tool']}"
                ran[key] = ran.get(key, 0) + 1
    result = {"agents": len(paths), "tool_calls": sum(by_class.values()), "by_class": dict(sorted(by_class.items())), "by_tool": dict(sorted(by_tool.items())),
              "calls_a_gate_must_have_seen_by_agent_type": dict(sorted(by_type.items())), "calls_outside_the_contract_that_ran": dict(sorted(ran.items())),
              "clean": not ran, "agents_with_type_not_recorded": unknown, "empty_records": empty, **odd_total}
    if gate_lines is not None:
        seen: dict[str, int] = {}
        seen_by_agent: dict[str, int] = {}
        unusable = 0
        for line in gate_lines:
            if not isinstance(line, dict):
                unusable += 1
                continue
            if not isinstance(line.get("agent"), str) or not line["agent"]:  # the orchestrator's own calls carry no agent
                continue
            if line.get("tool") not in HAND_BACK:
                seen[line["agent"]] = seen.get(line["agent"], 0) + 1
                if isinstance(line.get("who"), str):
                    seen_by_agent[line["who"]] = seen_by_agent.get(line["who"], 0) + 1
        # Agent by agent: the gate's hash of an agent's id against the hash of the record's name. Then a line of one agent cannot stand in
        # for a call of another. Lines that name no agent at all (a record made by another gate) can only be compared by totals per agent type.
        per_agent = bool(seen_by_agent)  # this gate writes a hash for every agent; only a record made by another gate has none
        if per_agent:
            short = {name: count - seen_by_agent.get(name, 0) for name, count in by_agent.items() if count > seen_by_agent.get(name, 0)}
            missed = {"agents": len(short), "calls": sum(short.values())} if short else {}
        else:
            missed = {kind: count - seen.get(kind, 0) for kind, count in by_type.items() if count > seen.get(kind, 0)}
        strangers = {name: count for name, count in seen_by_agent.items() if name not in by_agent} if per_agent else {}
        result["gate"] = {"calls_the_gate_saw_by_agent_type": dict(sorted(seen.items())), "calls_in_records_the_gate_did_not_see": missed,
                          "compared_by": "agent" if per_agent else "agent type" if by_type or seen else "nothing to compare",
                          "agents_the_gate_saw_that_have_no_record_here": len(strangers), "their_calls": sum(strangers.values()),
                          "refused_by_the_gate_in_its_own_record": sum(isinstance(line, dict) and line.get("verdict") == "refuse" for line in gate_lines),
                          "gate_lines_unusable": unusable, "reconciled": not missed}
    return result


def _time(line: dict) -> float | None:
    value = line.get("t")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value else None


def gate_report(path: Path, start: float | None = None, end: float | None = None) -> dict:
    """The gate's lines inside a stage, and how many were left out and why. With a window, a line with no time cannot be placed and is left out."""
    kept, counts = [], {"not_json": 0, "no_time": 0, "outside_the_stage": 0}
    try:
        text_of_log = Path(path).read_text(errors="replace") if Path(path).exists() else ""
    except OSError:
        text_of_log = ""
    for text in text_of_log.splitlines():
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except ValueError:
            counts["not_json"] += 1
            continue
        if not isinstance(line, dict):
            counts["not_json"] += 1
            continue
        when = _time(line)
        if when is None:
            counts["no_time"] += 1
            if start is not None or end is not None:
                continue
        elif (start is not None and when < start) or (end is not None and when > end):
            counts["outside_the_stage"] += 1
            continue
        kept.append(line)
    return {"lines": kept, **counts}


def gate_log(path: Path, start: float | None = None, end: float | None = None) -> list[dict]:
    return gate_report(path, start, end)["lines"]


def main() -> int:
    arguments = sys.argv[1:]
    log = None
    if arguments[:1] == ["--gate-log"]:
        log, arguments = gate_log(Path(arguments[1])), arguments[2:]
    if not arguments:
        print(__doc__.split("\n\n")[1])
        return 2
    print(json.dumps(build([Path(a) for a in arguments], log), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
