#!/usr/bin/env python3
"""One gate for the whole session: it tells a worker from the orchestrator by what the host reports, and refuses by default.

    swk-hook                                  the host calls this before every tool call, with the call as JSON on standard input
    python3 swarm/phase3/hook.py selftest     does the gate decide as it must, and does the installed gate do the same?
    python3 swarm/phase3/hook.py report       what the gate has seen so far, as counts (--save writes evidence/gate.json)

The second phase found that this host does not run a gate written into an agent's own
definition. It does run a gate set for the whole session in .claude/settings.json, and it
tells that gate the type and the id of the agent that is calling. So this gate decides by
who is calling, and what it does not know it refuses:

- the orchestrator (the host reports no agent): let through. It is the party that starts
  the agents and it is not confined by this gate;
- the host's own hand-back of an agent's answer: let through for every agent;
- a worker of the experiment (agent types swarm-light*, swarm-queue*, swarm-large,
  swarm-probe*): a shell call must pass the worker gate (guard.allowed), one swk command
  of a fixed shape; every other tool is refused, whatever the worker's definition lists;
- a development agent (swarm-dev): the lane net (lane_guard.allowed);
- any other agent, of any type this gate does not know: every call refused;
- a call this gate cannot read, a fault in the gate itself, or an agent's call that
  cannot be written to the record: refused.

It records every call it judged: the time, the tool's name, the agent's type, a short
hash of the agent's id, the verdict, and the names (never the values) of the fields the
host sent. No command text and no content. The record is private, under SWARM_HOME/p3.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2")]
import guard  # noqa: E402
import lane_guard  # noqa: E402

LOG = Path(os.environ.get("SWARM_HOME", Path.home() / ".gaie-swarm")) / "p3" / "hook.jsonl"
WORKER = re.compile(r"swarm-(light|queue|large|probe)(-[a-z0-9]{1,24}){0,3}")  # the whole type, never a prefix of it
NAME = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
BAD = "\0unreadable"  # stands for a type or an id that is not one clean, non-empty string
MOST = 100_000  # the longest shell call a worker may make, in characters
TYPE_FIELDS = ("agent_type", "agentType", "subagent_type")
ID_FIELDS = ("agent_id", "agentId")
HAND_BACK = ("SubagentHandback", "StructuredOutput")
REFUSAL = f"{guard.MARK}: refused."


def caller(call: dict) -> tuple[str | None, str | None]:
    """The type and the id of the calling agent, as the host reports them. Both None for the orchestrator.
    A value that is not a clean string is returned as the marker BAD, never as "absent"."""
    def pick(names):
        found = [call[name] for name in names if name in call]
        if not found:
            return None
        first = found[0]
        if not isinstance(first, str) or first != first.strip() or not first or any(value != first for value in found):
            return BAD
        return first
    return pick(TYPE_FIELDS), pick(ID_FIELDS)


def decide(call: dict) -> tuple[str, str]:
    """`pass` for the orchestrator, `allow` or `refuse` for an agent, and what a refused agent is told."""
    kind, ident = caller(call)
    tool = call.get("tool_name")
    if kind is None and ident is None:
        return "pass", ""
    if kind in (None, BAD) or ident in (None, BAD):  # an agent that the host did not describe whole and plainly
        return "refuse", f"{REFUSAL} The gate could not tell who is calling."
    if isinstance(tool, str) and tool in HAND_BACK:
        return "allow", ""
    if WORKER.fullmatch(kind):
        if tool != "Bash":
            return "refuse", f"{REFUSAL} A worker has a shell and nothing else."
        command = call["tool_input"].get("command") if isinstance(call.get("tool_input"), dict) else None
        if isinstance(command, str) and len(command) <= MOST and "\0" not in command and guard.allowed(command):
            return "allow", ""
        return "refuse", f"{REFUSAL} Only the swk commands named in your instructions and your task run here, one per call."
    if kind == "swarm-dev":
        ok, why = lane_guard.allowed(call)
        return ("allow", "") if ok else ("refuse", f"{lane_guard.MARK}: refused: {why}.")
    return "refuse", f"{REFUSAL} In a session of this experiment only its own agent types may use tools."


def _plain(value, fallback="(unreadable)") -> str:
    """A name for the record: only a short plain name goes in, so a tool name or a field name that carries a command
    or content never reaches the record."""
    return value if isinstance(value, str) and NAME.fullmatch(value) else fallback


def record(call: dict, verdict: str) -> bool:
    """One line for one judged call. False when the line could not be written."""
    try:
        kind, ident = caller(call)
        line = {"t": round(time.time(), 2), "tool": _plain(call.get("tool_name"), "(none)" if "tool_name" not in call else "(unreadable)"),
                "agent": None if kind is None else _plain(kind), "verdict": verdict,
                "who": hashlib.sha256(ident.encode("utf-8", "replace")).hexdigest()[:10] if isinstance(ident, str) and ident != BAD else None,
                "fields": sorted({_plain(key) for key in list(call)[:60]})}
        LOG.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)  # never through a link, never waiting on a pipe
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                return False
            data = (json.dumps(line) + "\n").encode()
            return os.write(descriptor, data) == len(data)  # one write: a line is whole or absent
        finally:
            os.close(descriptor)
    except (OSError, TypeError, ValueError, AttributeError):
        return False


def wrapper(settings: str) -> str:
    """The installed program. The host lets a call run when its gate ends with any status but 2, so a gate that
    crashes would open the door. This wrapper turns every ending except "allowed" into a refusal."""
    return ("#!/bin/sh\n"
            f"{settings} python3 -I '{HERE / 'hook.py'}' \"$@\"\n"
            "status=$?\n"
            "[ \"$status\" -eq 0 ] && exit 0\n"
            f"[ \"$status\" -eq 2 ] || echo '{REFUSAL} The gate did not run to its end.' >&2\n"
            "exit 2\n")


CASES = (  # who calls, the call, and what the gate must say
    ("the orchestrator's shell", {"tool_name": "Bash", "tool_input": {"command": "git status"}}, "pass"),
    ("a worker's own command", {"agent_type": "swarm-queue-1", "agent_id": "a1", "tool_name": "Bash", "tool_input": {"command": "swk next"}}, "allow"),
    ("a worker reading a file", {"agent_type": "swarm-queue-1", "agent_id": "a1", "tool_name": "Bash", "tool_input": {"command": "cat /etc/hostname"}}, "refuse"),
    ("a worker chaining a second command", {"agent_type": "swarm-light", "agent_id": "a2", "tool_name": "Bash", "tool_input": {"command": "swk status; id"}}, "refuse"),
    ("a worker using a file tool", {"agent_type": "swarm-large", "agent_id": "a3", "tool_name": "Read", "tool_input": {"file_path": "/etc/hostname"}}, "refuse"),
    ("a worker using a session tool", {"agent_type": "swarm-probe-open", "agent_id": "a4", "tool_name": "mcp__claude-code-remote__send_message", "tool_input": {}}, "refuse"),
    ("a worker's answer being handed back", {"agent_type": "swarm-queue-1", "agent_id": "a1", "tool_name": "SubagentHandback", "tool_input": {}}, "allow"),
    ("an agent of an unknown type", {"agent_type": "general-purpose", "agent_id": "a5", "tool_name": "Bash", "tool_input": {"command": "swk next"}}, "refuse"),
    ("an agent with an id and no type", {"agent_id": "a6", "tool_name": "Bash", "tool_input": {"command": "swk next"}}, "refuse"),
    ("a development agent pushing", {"agent_type": "swarm-dev", "agent_id": "a7", "tool_name": "Bash", "tool_input": {"command": "git push"}}, "refuse"),
)


def selftest(installed: bool = True) -> list[str]:
    """What is wrong with the gate, as a list. Empty when it decides as it must, here and as installed."""
    problems = [f"{who}: decided {decide(call)[0]}, must be {must}" for who, call, must in CASES if decide(call)[0] != must]
    if installed:
        program = shutil.which("swk-hook")
        if program is None:
            return [*problems, "the gate is not installed: swk-hook is not on the path"]
        quiet = {**os.environ, "SWK_HOOK_DRY": "1"}  # the self-test leaves no line in the record
        for who, call, must in CASES:
            code = subprocess.run([program], input=json.dumps(call), capture_output=True, text=True, env=quiet).returncode
            if code != (2 if must == "refuse" else 0):
                problems.append(f"{who}: the installed gate exited {code}")
        for text in ("", "not json", "[1]"):
            if subprocess.run([program], input=text, capture_output=True, text=True, env=quiet).returncode != 2:
                problems.append("the installed gate let a call through that it could not read")
        allowed = json.dumps(CASES[1][1])
        if subprocess.run([program, "fault"], input=allowed, capture_output=True, text=True, env=quiet).returncode != 2:
            problems.append("the installed gate lets a call through when the gate itself crashes")
    return problems


def report() -> dict:
    lines = []
    for text in LOG.read_text().splitlines() if LOG.exists() else []:
        try:
            lines.append(json.loads(text))
        except ValueError:
            continue
    counts: dict[str, int] = {}
    for line in lines:
        key = f"{line.get('agent') or 'the orchestrator'} / {line.get('tool')} / {line.get('verdict')}"
        counts[key] = counts.get(key, 0) + 1
    typed = [line for line in lines if line.get("agent")]
    return {"about": "What the session-wide gate saw. Counts and field names only.", "calls_seen": len(lines), "calls_from_agents": len(typed),
            "host_reports_the_agent_type": bool(typed), "agent_types_seen": sorted({line["agent"] for line in typed}),
            "agents_seen": len({line.get("who") for line in typed if line.get("who")}), "refused": sum(line.get("verdict") == "refuse" for line in lines),
            "by_caller_tool_and_verdict": dict(sorted(counts.items())), "fields_the_host_sends": sorted({field for line in lines for field in line.get("fields", [])})}


def _once(pairs: list) -> dict:
    """A document that names a field twice is refused: two readers could take different values."""
    names = [key for key, _ in pairs]
    if len(set(names)) != len(names):
        raise ValueError("a field twice")
    return dict(pairs)


def main() -> int:
    if sys.argv[1:2] == ["fault"]:  # the self-test's way to see what a crash of the gate leads to
        raise RuntimeError("a fault, asked for by the self-test")
    if sys.argv[1:2] == ["selftest"]:
        problems = selftest("--here" not in sys.argv)
        print(json.dumps({"holds": not problems, "problems": problems}, indent=1))
        return 1 if problems else 0
    if sys.argv[1:2] == ["report"]:
        result = report()
        if "--save" in sys.argv:
            out = HERE / "evidence" / "gate.json"
            out.parent.mkdir(exist_ok=True)
            out.write_text(json.dumps(result, indent=1) + "\n")
        print(json.dumps(result, indent=1))
        return 0
    try:
        call = json.loads(sys.stdin.buffer.read().decode("utf-8"), object_pairs_hook=_once)
        if not isinstance(call, dict):
            raise ValueError("not a call")
        verdict, why = decide(call)
    except Exception:  # noqa: BLE001 - whatever goes wrong inside the gate, the call does not run
        print(f"{REFUSAL} The gate could not read this call.", file=sys.stderr)
        return 2
    if os.environ.get("SWK_HOOK_DRY") != "1" and not record(call, verdict) and verdict == "allow":
        print(f"{REFUSAL} The gate could not record this call, and a call that is not recorded does not run.", file=sys.stderr)
        return 2
    if verdict == "refuse":
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
