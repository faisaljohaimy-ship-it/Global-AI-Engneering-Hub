#!/usr/bin/env python3
"""Scripted trace of the worker command on large tasks: no agent, no model.

It builds the same large tasks twice, once as a raw stage and once as a lean stage, and
runs the worker's command (swarm/phase2/kit.py) for the same five needs in each: the
failing tests, the callers of the wrong function, its code, the failed events and the
build error. It records how many characters each command printed, whether the true
answer is in the output, the totals and the percent saved by the lean stage.

    python3 swarm/phase3/trace.py OUTFOLDER [COUNT] [--json FILE]

Everything is written under OUTFOLDER/home (a private SWARM_HOME); COUNT defaults to 2.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]
import tasks  # noqa: E402

KIT = HERE.parent / "phase2" / "kit.py"
NEEDS = ("failing_tests", "callers", "code", "failed_events", "build_error")
KIND = "scripted trace: no agent, no model"


def swk(home: Path, *argv: str) -> str:
    env = {"PATH": os.environ.get("PATH", ""), "SWARM_HOME": str(home)}
    done = subprocess.run([sys.executable, "-I", str(KIT), *argv], capture_output=True, text=True, env=env, timeout=300)
    return done.stdout


def expected_failures(folder: Path) -> list[str]:
    done = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], cwd=folder, capture_output=True, text=True, timeout=300)
    return re.findall(r"^(?:FAIL|ERROR): (.+)$", done.stdout + done.stderr, re.M)


def present(need: str, mode: str, text: str, folder: Path, truth: dict, index: dict, failing: list[str]) -> bool:
    name = truth["fixed_function"].split(".")[-1]
    where = index["functions"][name]
    if need == "failing_tests":
        return bool(failing) and all(item in text for item in failing) if mode == "raw" else bool(failing) and all(item.split()[0] in text for item in failing)
    if need == "callers":
        if mode == "lean":
            try:
                return sorted(json.loads(text)) == sorted(truth["direct_callers"])
            except ValueError:
                return False
        hits = {}
        for line in text.splitlines():
            m = re.match(r"inv/(m\d+)\.py:(\d+):", line)
            if m:
                hits.setdefault(m.group(1), []).append(int(m.group(2)))
        for caller in truth["direct_callers"]:
            module, func = caller.split(".")
            first, last = index["functions"][func]["first"], index["functions"][func]["last"]
            if not any(first <= n <= last for n in hits.get(module, [])):
                return False
        return True
    if need == "code":
        lines = (folder / "inv" / f"{where['module']}.py").read_text().splitlines()
        return all(f"{n}: {lines[n - 1]}" in text for n in range(where["first"], where["last"] + 1))
    if need == "failed_events":
        if mode == "lean":
            try:
                return sorted(json.loads(text)) == sorted(truth["failed_event_ids"])
            except ValueError:
                return False
        seen = {int(i) for i in re.findall(r'"id": (\d+), "service": "[^"]*", "status": "failed"', text)}
        return seen == set(truth["failed_event_ids"])
    return truth["build_error_code"] in text


def commands(mode: str, ident: str, truth: dict) -> dict:
    name = truth["fixed_function"].split(".")[-1]
    module = truth["fixed_function"].split(".")[0]
    if mode == "raw":
        return {"failing_tests": ["test", ident], "callers": ["grep", ident, rf"{name}\(", "inv"], "code": ["read", ident, f"inv/{module}.py"],
                "failed_events": ["grep", ident, "failed", "data/events.json"], "build_error": ["grep", ident, "^ERROR", "logs/build.log"]}
    return {"failing_tests": ["test", ident], "callers": ["callers", ident, name], "code": ["def", ident, name],
            "failed_events": ["select", ident, "data/events.json", "status=failed", "id"], "build_error": ["grep", ident, "^ERROR", "logs/build.log"]}


def run(out: Path, count: int) -> dict:
    out = Path(out)
    home = out / "home"
    rows = []
    for mode in ("lean", "raw"):
        folder = home / "p2" / "work" / mode
        folder.mkdir(parents=True, exist_ok=True)
        made = tasks.make(folder, "large", 1, count, mode)
        (home / "p2" / "current").write_text(mode)
        for item in made:
            ident = item["id"]
            truth = json.loads((folder / ".hidden" / f"{ident}.json").read_text())["truth"]
            index = json.loads((home / "p2" / "work" / "lean" / ".kit" / f"{ident}.index.json").read_text())
            failing = expected_failures(folder / ident)
            for need, argv in commands(mode, ident, truth).items():
                text = swk(home, *argv)
                rows.append({"task": ident, "mode": mode, "need": need, "chars": len(text),
                             "answer_present": present(need, mode, text, folder / ident, truth, index, failing)})
    totals = {mode: sum(r["chars"] for r in rows if r["mode"] == mode) for mode in ("raw", "lean")}
    saved = round(100.0 * (totals["raw"] - totals["lean"]) / totals["raw"], 1) if totals["raw"] else None
    per_need = {need: {mode: sum(r["chars"] for r in rows if r["need"] == need and r["mode"] == mode) for mode in ("raw", "lean")} for need in NEEDS}
    return {"kind": KIND, "tasks": count, "needs": list(NEEDS), "rows": rows, "per_need": per_need, "total_chars": totals, "percent_saved": saved,
            "all_answers_present": {mode: all(r["answer_present"] for r in rows if r["mode"] == mode) for mode in ("raw", "lean")},
            "unit": "characters printed by swk, measured from its standard output"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", type=Path)
    parser.add_argument("count", nargs="?", type=int, default=2)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if args.out is None:
        args.out = Path(tempfile.mkdtemp(prefix="trace-"))
    result = run(args.out, args.count)
    text = json.dumps(result, indent=1) + "\n"
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
