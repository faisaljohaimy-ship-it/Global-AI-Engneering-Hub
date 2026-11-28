#!/usr/bin/env python3
"""Run a team of development agents, one lane each, in separate worktrees, and join what they made.

    python3 swarm/phase3/team.py setup          a worktree and a branch per lane, the lane gate, and what to launch
    python3 swarm/phase3/team.py brief LANE     what one development agent reads: its worktree, the contract, its brief
    python3 swarm/phase3/team.py integrate      join the lanes: ownership, merge, each lane's tests, the whole suite, the cost

The agents are started by the agent host, not by this script. Each works alone in its own
worktree on its own branch, so twenty can write at once without touching one another. A
lane owns the paths TEAM.json lists for it. When the lanes are joined, a lane that changed
any other path is rejected whole, a lane that conflicts or whose tests fail is left out,
and the rest are merged one by one. What each agent used is read from the host's record of
it and written, with counts only, to swarm/phase3/evidence/team.json.

Development agents build parts of the system. They are not the agents of the measured
experiment, and the evidence keeps the two apart.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]
import hook  # noqa: E402
import measure  # noqa: E402
import stage  # noqa: E402

ROOT = Path(os.environ.get("SWARM_TEAM_ROOT", HERE.parents[1])).resolve()
TEAM_FILE = ROOT / "swarm" / "phase3" / os.environ.get("SWARM_TEAM_FILE", "TEAM.json")  # TEAM.json was the first round; TEAM2.json the second
TEAM = json.loads(TEAM_FILE.read_text())
LANES = Path(os.environ.get("SWARM_LANES", ROOT.parent / "p3-lanes")).resolve()
BIN = Path(os.environ.get("SWARM_BIN", "/usr/local/bin"))
EVIDENCE = ROOT / "swarm" / "phase3" / "evidence" / TEAM_FILE.name.lower()  # team.json, team2.json
LANE = re.compile(r"LANE-([A-Z]\d)")


def git(*arguments: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True, check=check)


def lane_of(name: str) -> dict:
    ident = name.upper().replace("LANE-", "")
    found = [lane for lane in TEAM["lanes"] if lane["id"] == ident]
    if not found:
        raise SystemExit(f"no lane named {name}")
    return found[0]


def owned(path: str, owns: list[str]) -> bool:
    return any(path == own or (own.endswith("/") and path.startswith(own)) for own in owns)


def card() -> str:
    ids = " ".join(f"LANE-{lane['id']}" for lane in TEAM["lanes"])
    return (f"TEAM: start {len(TEAM['lanes'])} agents, all in ONE message, in the foreground.\n"
            f"  subagent_type: {TEAM['agent_type']}   model: {TEAM['model']}   effort: {TEAM['effort']}\n"
            f"  prompt of each agent: its lane id and nothing else. One agent per id:\n    {ids}\n"
            f"When every agent has returned, run: {'' if TEAM_FILE.name == 'TEAM.json' else f'SWARM_TEAM_FILE={TEAM_FILE.name} '}python3 swarm/phase3/team.py integrate")


def setup() -> int:
    LANES.mkdir(parents=True, exist_ok=True)
    home = Path(os.environ.get("SWARM_HOME", Path.home() / ".gaie-swarm"))
    for name, line in (("swk", f"SWARM_HOME='{home}' exec python3 -I '{HERE.parent / 'phase2' / 'kit.py'}' \"$@\""),
                       ("swk-guard", f"exec python3 -I '{HERE.parent / 'phase2' / 'guard.py'}' \"$@\""),
                       ("swk-lane-guard", f"SWARM_LANES='{LANES}' exec python3 -I '{HERE / 'lane_guard.py'}' \"$@\""),
                       ("swk-brief", f"SWARM_TEAM_ROOT='{ROOT}' SWARM_LANES='{LANES}' SWARM_TEAM_FILE='{TEAM_FILE.name}' exec python3 '{HERE / 'team.py'}' brief \"$@\"")):
        (BIN / name).write_text(f"#!/bin/sh\n{line}\n")
        (BIN / name).chmod(0o755)
    (BIN / "swk-hook").write_text(hook.wrapper(f"SWARM_HOME='{home}' SWARM_LANES='{LANES}'"))
    (BIN / "swk-hook").chmod(0o755)
    base = git("rev-parse", "HEAD").stdout.strip()
    for lane in TEAM["lanes"]:
        if not (LANES / lane["id"]).exists():
            git("worktree", "add", "-q", "-b", f"claude/p3-{lane['id'].lower()}", str(LANES / lane["id"]), base)
    _, folder = stage.locate()
    (LANES / "team.json").write_text(json.dumps({"base": base, "start": datetime.now(timezone.utc).isoformat(),
                                                 "before": [p.name for p in stage.records(folder)] if folder.exists() else []}))
    print(card())
    return 0


def brief(name: str) -> int:
    lane = lane_of(name)
    print(f"Lane {lane['id']}: {lane['title']}\nYour worktree: {LANES / lane['id']}\nThe only paths you may change, relative to your worktree: {', '.join(lane['owns'])}\n")
    print((ROOT / "swarm" / "phase3" / TEAM.get("contract", "CONTRACT.md")).read_text())
    print(f"## Your work, lane {lane['id']}\n\n{lane['brief']}")
    return 0


def usage(info: dict) -> dict:
    """What each lane's agent used, from the host's records of the agents started since setup."""
    _, folder = stage.locate()
    found = {}
    for path in stage.records(folder) if folder.exists() else []:
        if path.name in info["before"]:
            continue
        prompt = ""
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") == "user":
                content = (entry.get("message") or {}).get("content")
                prompt = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content or [] if isinstance(b, dict))
                break
        match = LANE.search(prompt[:200])
        if match:
            found[match.group(1)] = {**measure.read(path), **stage.extra(path)}
    return found


def integrate() -> int:
    info = json.loads((LANES / "team.json").read_text())
    base, used, rows = info["base"], usage(info), []
    for lane in TEAM["lanes"]:
        branch, path = f"claude/p3-{lane['id'].lower()}", LANES / lane["id"]
        changed = git("diff", "--name-only", f"{base}..{branch}").stdout.split()
        numbers = [line.split("\t") for line in git("diff", "--numstat", f"{base}..{branch}").stdout.splitlines()]
        row = {"lane": lane["id"], "group": lane["group"], "title": lane["title"], "files_changed": changed,
               "lines_added": sum(int(n[0]) for n in numbers if n[0].isdigit()), "lines_removed": sum(int(n[1]) for n in numbers if n[1].isdigit()),
               "left_uncommitted": len(git("status", "--porcelain", cwd=path).stdout.splitlines()), "tests_of_its_own": 0}
        outside = [name for name in changed if not owned(name, lane["owns"])]
        tests = sorted(name[:-3].replace("/", ".") for name in changed if re.fullmatch(r"tests/test_\w+\.py", name))
        if not changed:
            row["state"] = "nothing committed"
        elif outside:
            row.update(state="rejected: it changed paths outside its lane", outside=outside)
        elif not tests:
            row["state"] = "not joined: it brought no tests"
        else:
            before = git("rev-parse", "HEAD").stdout.strip()
            if git("merge", "--no-ff", "-q", "-m", f"Join lane {lane['id']}: {lane['title']}", branch, check=False).returncode != 0:
                git("merge", "--abort", check=False)
                row["state"] = "not joined: it conflicts with a lane joined before it"
            else:
                try:
                    ran = subprocess.run([sys.executable, "-m", "unittest", *tests], cwd=ROOT, capture_output=True, text=True, timeout=900)
                    count = re.search(r"Ran (\d+) tests?", ran.stderr)
                    row["tests_of_its_own"] = int(count.group(1)) if count else 0
                    passed = ran.returncode == 0 and row["tests_of_its_own"] > 0
                except subprocess.TimeoutExpired:
                    passed = False
                if passed:
                    row["state"] = "joined"
                else:
                    git("reset", "-q", "--hard", before)
                    row["state"] = "not joined: its own tests fail here"
        record = used.get(lane["id"])
        if record:
            row.update(agent={"replies": record["roundtrips"], "tool_calls": record["tool_calls"], "seconds": record["seconds"], "model": stage.alias(record["model"]),
                              "first_request_context": record["first_context"], "input_tokens": record["input_total"], "output_tokens": record["output"],
                              "cost_units": stage.cost_units(record), "refused_calls": sum(1 for _ in range(record["refused_calls"])),
                              "final_reply": record["final_reply"].split()[0] if record["final_reply"] else "", "met_a_limit": record["limit_error"]})
        rows.append(row)
    suite = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT, capture_output=True, text=True, timeout=1800)
    count = re.search(r"Ran (\d+) tests?", suite.stderr)
    agents = [row["agent"] for row in rows if row.get("agent")]
    timed = [record for record in used.values() if record["start"] is not None and record["end"] is not None]
    evidence = {"about": "Development agents of the third phase: each built one part of the system in its own worktree. They are not agents of the measured experiment. "
                         "Counts, times and tool names from the host's records; no record content.",
                "kind": "development agents", "lanes": rows,
                "totals": {"lanes": len(rows), "agents_started": len(agents), "ran_at_once": measure.peak(timed) if timed else 0,
                           "wall_seconds": round(max(r["end"] for r in timed) - min(r["start"] for r in timed), 1) if timed else None,
                           "joined": sum(row["state"] == "joined" for row in rows), "input_tokens": sum(a["input_tokens"] for a in agents),
                           "output_tokens": sum(a["output_tokens"] for a in agents), "cost_units": sum(a["cost_units"] for a in agents),
                           "agents_that_met_a_limit": sum(bool(a["met_a_limit"]) for a in agents), "lines_added_joined": sum(r["lines_added"] for r in rows if r["state"] == "joined"),
                           "tests_added_joined": sum(r["tests_of_its_own"] for r in rows if r["state"] == "joined")},
                "suite_after_joining": {"tests": int(count.group(1)) if count else 0, "passed": suite.returncode == 0}}
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=1) + "\n")
    for row in rows:
        agent = row.get("agent") or {}
        print(f"{row['lane']:3} {row['group']:12} {row['state'][:46]:46} +{row['lines_added']:<5} tests {row['tests_of_its_own']:<3} "
              f"replies {agent.get('replies', '-')!s:<3} input {agent.get('input_tokens', 0):>10,} {agent.get('final_reply', '')}")
    print("totals", json.dumps(evidence["totals"]))
    print("suite after joining:", evidence["suite_after_joining"])
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "setup":
        return setup()
    if command == "brief" and len(sys.argv) == 3:
        return brief(sys.argv[2])
    if command == "integrate":
        return integrate()
    if command == "card":
        print(card())
        return 0
    print(__doc__.split("\n\n")[1])
    return 2


if __name__ == "__main__":
    sys.exit(main())
