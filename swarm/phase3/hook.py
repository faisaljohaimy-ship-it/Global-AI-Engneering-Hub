#!/usr/bin/env python3
"""One gate for the whole session, which tells a worker from the orchestrator by the agent type the host reports.

    swk-hook                                  the host calls this before a Bash, Write or Edit call, with the call as JSON on standard input
    python3 swarm/phase3/hook.py report       what the gate has seen so far, as counts
    python3 swarm/phase3/hook.py report --save    the same, written to swarm/phase3/evidence/gate.json

The second phase found that this host does not run a gate written into an agent's own
definition: a worker told to run a forbidden command ran it. This gate is set for the whole
session in .claude/settings.json instead, and decides by who is calling:

- a worker of the experiment (agent types swarm-light*, swarm-queue*, swarm-large,
  swarm-probe): a shell call must pass the worker gate (guard.allowed); any other tool is refused;
- a development agent (swarm-dev): the lane net (lane_guard.allowed);
- anyone else, including the orchestrator and a call for which the host reports no agent
  type: let through.

So if the host does not say which agent is calling, this gate holds nobody back, and the
record it keeps shows that. It records counts only: the tool, the agent type, the verdict,
and the names (never the values) of the fields the host sent. The record is private, under
SWARM_HOME/p3.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2")]
import guard  # noqa: E402
import lane_guard  # noqa: E402

LOG = Path(os.environ.get("SWARM_HOME", Path.home() / ".gaie-swarm")) / "p3" / "hook.jsonl"
WORKER = re.compile(r"swarm-(light|queue|large|probe)")
TYPE_FIELDS = ("agent_type", "agentType", "subagent_type")


def decide(call: dict) -> tuple[str, str]:
    """`pass` for a caller this gate does not judge, `allow` or `refuse` for one it does, and why."""
    kind = next((call[name] for name in TYPE_FIELDS if isinstance(call.get(name), str)), None)
    if kind and WORKER.match(kind):
        if call.get("tool_name") != "Bash":
            return "refuse", f"{guard.MARK}: refused. A worker has a shell and nothing else."
        command = (call.get("tool_input") or {}).get("command")
        ok = isinstance(command, str) and guard.allowed(command)
        return ("allow", "") if ok else ("refuse", f"{guard.MARK}: refused. Only the swk commands named in your instructions and your task run here, one per call.")
    if kind == "swarm-dev":
        ok, why = lane_guard.allowed(call)
        return ("allow", "") if ok else ("refuse", f"{lane_guard.MARK}: refused: {why}.")
    return "pass", ""


def record(call: dict, verdict: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        kind = next((call[name] for name in TYPE_FIELDS if isinstance(call.get(name), str)), None)
        line = {"t": round(time.time(), 1), "tool": call.get("tool_name"), "agent": kind, "verdict": verdict, "fields": sorted(str(key) for key in call)}
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
    except OSError:
        pass


def report() -> dict:
    lines = [json.loads(line) for line in LOG.read_text().splitlines()] if LOG.exists() else []
    counts: dict[str, int] = {}
    for line in lines:
        key = f"{line['agent'] or 'no agent type reported'} / {line['tool']} / {line['verdict']}"
        counts[key] = counts.get(key, 0) + 1
    typed = [line for line in lines if line["agent"]]
    return {"about": "What the session-wide gate saw. Counts and field names only.", "calls_seen": len(lines), "calls_with_an_agent_type": len(typed),
            "host_reports_the_agent_type": bool(typed), "agent_types_seen": sorted({line["agent"] for line in typed}),
            "refused": sum(line["verdict"] == "refuse" for line in lines), "by_caller_tool_and_verdict": dict(sorted(counts.items())),
            "fields_the_host_sends": sorted({field for line in lines for field in line["fields"]})}


def main() -> int:
    if sys.argv[1:2] == ["report"]:
        result = report()
        if "--save" in sys.argv:
            out = HERE / "evidence" / "gate.json"
            out.parent.mkdir(exist_ok=True)
            out.write_text(json.dumps(result, indent=1) + "\n")
        print(json.dumps(result, indent=1))
        return 0
    try:
        call = json.loads(sys.stdin.read())
        if not isinstance(call, dict):
            raise ValueError("not a call")
    except (ValueError, OSError):
        return 0  # not a call this gate can read: the host decides, as it would without this gate
    verdict, why = decide(call)
    record(call, verdict)
    if verdict == "refuse":
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
