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

A stage is clean when the last three ran-classes above the hand-back are all zero for its
workers. With the gate's record it is also reconciled: the gate must have seen every call
the agents' records hold, no fewer. A gate that misses calls is not a gate.

Counts and tool names only. No command text and no content is kept.
"""
from __future__ import annotations

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


def calls(path: Path) -> list[dict]:
    """One row per tool call of a record: the tool's name and its class."""
    asked, came_back = [], {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        for block in message.get("content") if isinstance(message.get("content"), list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                if all(block.get("id") != seen["id"] for seen in asked):  # one reply may be written on several lines
                    asked.append({"id": block.get("id"), "name": str(block.get("name")), "command": (block.get("input") or {}).get("command")})
            elif block.get("type") == "tool_result":
                inner = block.get("content")
                text = inner if isinstance(inner, str) else " ".join(b.get("text", "") for b in inner or [] if isinstance(b, dict))
                came_back[block.get("tool_use_id")] = (text[:600], bool(block.get("is_error")))
    rows = []
    for call in asked:
        text, failed = came_back.get(call["id"], ("", False))
        name = call["name"]
        if name in HAND_BACK:
            kind = "hand-back"
        elif any(mark in text for mark in GATE_MARKS):
            kind = "refused by the gate"
        elif failed and HOST_DENIAL.search(text):
            kind = "refused by the host"
        elif name == "Bash":
            kind = "worker command" if isinstance(call["command"], str) and guard.allowed(call["command"]) else "foreign shell command"
        elif SESSION_TOOL.search(name):
            kind = "session tool"
        else:
            kind = "other tool"
        rows.append({"tool": name, "class": kind})
    return rows


def agent_type(path: Path) -> str | None:
    try:
        return json.loads(Path(path).with_name(Path(path).stem + ".meta.json").read_text()).get("agentType")
    except (OSError, ValueError, AttributeError):
        return None


def build(paths: list[Path], gate_lines: list[dict] | None = None) -> dict:
    by_class: dict[str, int] = {}
    by_tool: dict[str, int] = {}
    by_type: dict[str, int] = {}
    ran: dict[str, int] = {}
    for path in paths:
        kind = agent_type(path) or "type not recorded"
        for row in calls(path):
            by_class[row["class"]] = by_class.get(row["class"], 0) + 1
            by_tool[row["tool"]] = by_tool.get(row["tool"], 0) + 1
            if row["class"] not in ("hand-back", "refused by the host"):  # the host answers these itself, before any gate is asked
                by_type[kind] = by_type.get(kind, 0) + 1
            if row["class"] in RAN:
                key = f"{row['class']}: {row['tool']}"
                ran[key] = ran.get(key, 0) + 1
    result = {"agents": len(paths), "tool_calls": sum(by_class.values()), "by_class": dict(sorted(by_class.items())), "by_tool": dict(sorted(by_tool.items())),
              "calls_a_gate_must_have_seen_by_agent_type": dict(sorted(by_type.items())), "calls_outside_the_contract_that_ran": dict(sorted(ran.items())),
              "clean": not ran}
    if gate_lines is not None:
        seen: dict[str, int] = {}
        for line in gate_lines:
            if line.get("agent") and line.get("tool") not in HAND_BACK:
                seen[line["agent"]] = seen.get(line["agent"], 0) + 1
        missed = {kind: count - seen.get(kind, 0) for kind, count in by_type.items() if count > seen.get(kind, 0)}
        result["gate"] = {"calls_the_gate_saw_by_agent_type": dict(sorted(seen.items())), "calls_in_records_the_gate_did_not_see": missed,
                          "refused_by_the_gate_in_its_own_record": sum(line.get("verdict") == "refuse" for line in gate_lines), "reconciled": not missed}
    return result


def gate_log(path: Path, start: float | None = None, end: float | None = None) -> list[dict]:
    lines = []
    for text in Path(path).read_text().splitlines() if Path(path).exists() else []:
        try:
            line = json.loads(text)
        except ValueError:
            continue
        if (start is None or line.get("t", 0) >= start) and (end is None or line.get("t", 0) <= end):
            lines.append(line)
    return lines


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
