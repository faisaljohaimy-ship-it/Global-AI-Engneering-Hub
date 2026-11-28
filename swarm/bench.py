#!/usr/bin/env python3
"""A synthetic project with one planted bug, for comparing ways of working on the same job.

    python3 swarm/bench.py build DIR [--seed N]     write the project as a Git repository
    python3 swarm/bench.py trace DIR OUT.json       size of what each configuration puts in context
    python3 swarm/bench.py check DIR WORKTREE       score one agent's worktree

The project is generated: a package of small functions that call one another, a test for
each, a large single-line JSON file with three failed records and a long build log with
one error. One function is wrong, so its test and the tests of everything that calls it
fail. The job is to find and fix that one function and to answer four questions.

`build` writes the answers to DIR.truth.json beside DIR, on purpose: an agent working inside
DIR must not be able to read them. Give it a DIR outside any repository.

`trace` starts no agent. For the same five information needs it runs the commands each
configuration would use and records how much text comes back:

    A  the host's own tools only: plain commands, search, whole-file reads
    B  A, with long command output passed through hr (Headroom)
    C  B, with definitions and references asked from the language server (sym)
    D  C, with the shared call index and one-line scripts that print only the answer
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workload  # noqa: E402

HERE = Path(__file__).resolve().parent
MODULES, FUNCTIONS, INPUTS = 8, 12, (0, 1, 5, 12)
SHAPES = ["y * {a} + {b}", "y * {a} - {b}", "(y + {a}) * {b}", "abs(y - {a}) + {b}", "y * y + {a}"]


def design(seed: int) -> dict:
    rng = random.Random(seed)
    functions = {}
    for m in range(MODULES):
        for k in range(FUNCTIONS):
            earlier = [n for n in functions if int(n[1]) < m]
            callee = rng.choice(earlier) if earlier and rng.random() < 0.7 else None
            functions[f"f{m}_{k}"] = {"module": f"m{m}", "callee": callee, "body": rng.choice(SHAPES).format(a=rng.randint(2, 9), b=rng.randint(1, 9))}
    callers = {n: sorted(f"{v['module']}.{c}" for c, v in functions.items() if v["callee"] == n) for n in functions}
    target = rng.choice(sorted(n for n, c in callers.items() if len(c) >= 2))
    return {"functions": functions, "callers": callers, "target": target, "seed": seed}


def source(plan: dict, module: str, broken: bool) -> str:
    mine = {n: v for n, v in plan["functions"].items() if v["module"] == module}
    imports = sorted({(plan["functions"][v["callee"]]["module"], v["callee"]) for v in mine.values() if v["callee"]})
    lines = [f'"""Generated module {module}. Synthetic: it models nothing real."""', *[f"from inv.{m} import {n}" for m, n in imports], ""]
    for name, spec in mine.items():
        body = spec["body"]
        if broken and name == plan["target"]:
            body = body.replace("+", "-", 1) if "+" in body else body.replace("-", "+", 1)
        lines += ["", f"def {name}(x: int) -> int:", f'    """Step {name} of the synthetic pipeline."""',
                  f"    y = {spec['callee']}(x)" if spec["callee"] else "    y = x", f"    return {body}", ""]
    return "\n".join(lines)


def build(root: Path, seed: int) -> dict:
    plan = design(seed)
    rng = random.Random(seed + 1)
    for folder in ("inv", "tests", "data", "logs"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "inv" / "__init__.py").write_text("")
    for m in range(MODULES):
        (root / "inv" / f"m{m}.py").write_text(source(plan, f"m{m}", False))
    expected = {}
    sys.path.insert(0, str(root))
    for name, spec in plan["functions"].items():
        spec_ = importlib.util.spec_from_file_location(f"inv.{spec['module']}", root / "inv" / f"{spec['module']}.py")
        module = importlib.util.module_from_spec(spec_)
        sys.modules[spec_.name] = module
        spec_.loader.exec_module(module)
        expected[name] = [getattr(module, name)(v) for v in INPUTS]
    sys.path.pop(0)
    for key in [k for k in sys.modules if k.startswith("inv")]:
        del sys.modules[key]
    # The broken file has the same size and second as the correct one, so a cached
    # compilation of the correct code would be reused and the bug would never run.
    for cache in root.rglob("__pycache__"):
        for item in cache.iterdir():
            item.unlink()
        cache.rmdir()
    tests = ["import unittest", *[f"from inv.{v['module']} import {n}" for n, v in plan["functions"].items()], "", "", "class PipelineTests(unittest.TestCase):"]
    for name in plan["functions"]:
        tests += [f"    def test_{name}(self):", f"        self.assertEqual([{name}(v) for v in {INPUTS}], {expected[name]})", ""]
    (root / "tests" / "test_inv.py").write_text("\n".join(tests) + "\n\nif __name__ == '__main__':\n    unittest.main()\n")
    module = plan["functions"][plan["target"]]["module"]
    (root / "inv" / f"{module}.py").write_text(source(plan, module, True))
    failed = sorted(rng.sample(range(1, 801), 3))
    events = [{"id": i, "service": f"svc-{i % 7}", "status": "failed" if i in failed else "ok", "latency_ms": 20 + (i * 13) % 37, "region": "eu-west-1"} for i in range(1, 801)]
    (root / "data" / "events.json").write_text(json.dumps(events))
    code = f"E{rng.randint(1000, 9999)}"
    log = [f"[{i // 60:02d}:{i % 60:02d}] compile unit {i:04d} ok" for i in range(3000)]
    log[rng.randint(500, 2500)] = f"ERROR {code}: unit could not be linked"
    (root / "logs" / "build.log").write_text("\n".join(log) + "\n")
    truth = {"fixed_function": f"{module}.{plan['target']}", "direct_callers": plan["callers"][plan["target"]], "failed_event_ids": failed, "build_error_code": code}
    index = {f"{v['module']}.{n}": {"calls": [f"{plan['functions'][v['callee']]['module']}.{v['callee']}"] if v["callee"] else [], "callers": plan["callers"][n]}
             for n, v in plan["functions"].items()}
    (root / ".gitignore").write_text("__pycache__/\nANSWER.json\nTASK.md\nINDEX.json\n.serena/\n")
    git = ["git", "-C", str(root), "-c", "user.name=bench", "-c", "user.email=bench@example.invalid"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "synthetic project with one planted bug"], check=True)
    return {"truth": truth, "index": index}


def run(command: list[str], cwd: Path) -> str:
    env = {**os.environ, "PATH": f"{Path.home()}/.gaie-tools/bin:{os.environ['PATH']}", "HR_SESSION": "bench-trace"}
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=env, timeout=300)
    return done.stdout + done.stderr


def trace(root: Path, truth: dict, index: dict) -> dict:
    module, name = truth["fixed_function"].split(".")
    tests = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    ids = "import json;print([e['id'] for e in json.load(open('data/events.json')) if e['status']=='failed'])"
    (root / "INDEX.json").write_text(json.dumps(index))
    needs = {
        "which tests fail": {"A": tests, "B": ["hr", "run", "--", *tests], "C": ["hr", "run", "--", *tests], "D": ["hr", "run", "--", *tests]},
        "who calls the broken function": {"A": ["rg", "-n", rf"\b{name}\(", "inv"], "B": ["rg", "-n", rf"\b{name}\(", "inv"], "C": ["sym", "refs", name, f"inv/{module}.py"],
                                          "D": [sys.executable, "-c", f"import json;print(json.load(open('INDEX.json'))['{module}.{name}']['callers'])"]},
        "the broken function's code": {"A": ["cat", f"inv/{module}.py"], "B": ["cat", f"inv/{module}.py"], "C": ["sym", "def", name, f"inv/{module}.py"], "D": ["sym", "def", name, f"inv/{module}.py"]},
        "which events failed": {"A": ["rg", "-n", "failed", "data/events.json"], "B": ["hr", "put", "--kind", "json", "data/events.json"], "C": ["hr", "put", "--kind", "json", "data/events.json"],
                                "D": [sys.executable, "-c", ids]},
        "the build error": {c: ["rg", "-n", "^ERROR", "logs/build.log"] for c in "ABCD"},
    }
    outputs = {need: {c: run(cmd, root) for c, cmd in by.items()} for need, by in needs.items()}
    answers = {"which tests fail": f"test_{name} ", "who calls the broken function": truth["direct_callers"][0].split(".")[1], "the broken function's code": f"def {name}(",
               "which events failed": str(truth["failed_event_ids"][0]), "the build error": truth["build_error_code"]}
    spec = importlib.util.spec_from_file_location("hr", HERE.parent / "skills" / "ultra-context-optimization" / "scripts" / "hr.py")
    hr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hr)
    flat = [outputs[need][c] for need in needs for c in "ABCD"]
    counts = hr.count_tokens(flat) or [None] * len(flat)
    table, position = {}, 0
    for need in needs:
        table[need] = {}
        for c in "ABCD":
            text = outputs[need][c]
            table[need][c] = {"chars": len(text), "tokens": counts[position], "answer_present": answers[need] in text}
            position += 1
    totals = {c: {"chars": sum(table[n][c]["chars"] for n in needs), "tokens": sum(table[n][c]["tokens"] or 0 for n in needs),
                  "answers_present": sum(table[n][c]["answer_present"] for n in needs)} for c in "ABCD"}
    for c in "BCD":
        totals[c]["tokens_saved_against_A_percent"] = round(100 * (1 - totals[c]["tokens"] / totals["A"]["tokens"]), 1)
    return {"kind": "scripted trace: no agent and no model; tokens from the legacy Claude tokenizer bundled with litellm, a proxy", "needs": table, "totals": totals}


def check(root: Path, worktree: Path, truth: dict) -> dict:
    # The worktree holds code an agent wrote. Before running any of it: only the package may have
    # changed, never the tests, and every changed file must pass the same screen as the small tasks.
    status = subprocess.run(["git", "-C", str(worktree), "status", "--porcelain"], capture_output=True, text=True).stdout.splitlines()
    touched = [line[3:] for line in status]
    refused = [name for name in touched if not re.fullmatch(r"inv/m\d+\.py", name)]
    for name in touched:
        if name not in refused:
            refused += [f"{name}: {finding}" for finding in workload.inspect((worktree / name).read_text(), workload.ALLOWED_IMPORTS | {"inv"})]
    if refused:
        return {"tests_pass": False, "refused_to_run": refused, "score": 0, "out_of": len(truth) + 1}
    # -B: leave no compiled files behind, so a later fix of the same size in the same second is not masked by them
    # -s -E: no user packages and no Python variables; the environment is empty and there is no network.
    # Not -I: that would also drop the project folder from the import path, and the tests import the package.
    tests = workload.isolated([sys.executable, "-B", "-s", "-E", "-m", "unittest", "discover", "-s", "tests"], worktree, 120)
    diff = subprocess.run(["git", "-C", str(worktree), "diff", "--numstat"], capture_output=True, text=True).stdout.split()
    changed = subprocess.run(["git", "-C", str(worktree), "diff", "--name-only"], capture_output=True, text=True).stdout.split()
    try:
        answer = json.loads((worktree / "ANSWER.json").read_text())
    except (OSError, ValueError):
        answer = {}
    fields = {key: answer.get(key) == value for key, value in truth.items()}
    return {"tests_pass": tests.returncode == 0, "files_changed": changed, "lines_added": int(diff[0]) if diff else 0, "lines_removed": int(diff[1]) if diff else 0,
            "only_the_broken_module_changed": changed == [f"inv/{truth['fixed_function'].split('.')[0]}.py"], "answer_fields_correct": fields,
            "score": sum(fields.values()) + (tests.returncode == 0), "out_of": len(truth) + 1}


def main() -> int:
    command, root = sys.argv[1], Path(sys.argv[2]).resolve()
    secret = root.parent / (root.name + ".truth.json")
    if command == "build":
        seed = int(sys.argv[4]) if len(sys.argv) > 4 else 11
        made = build(root, seed)
        secret.write_text(json.dumps(made))
        print("built", root.name, "| functions", MODULES * FUNCTIONS, "| direct callers of the broken one", len(made["truth"]["direct_callers"]))
        return 0
    made = json.loads(secret.read_text())
    if command == "trace":
        result = trace(root, made["truth"], made["index"])
        Path(sys.argv[3]).write_text(json.dumps(result, indent=1) + "\n")
        for need, by in result["needs"].items():
            print(f"{need:32}", " ".join(f"{c}:{by[c]['tokens']}{'' if by[c]['answer_present'] else '!'}" for c in "ABCD"))
        print("totals", result["totals"])
        return 0
    print(json.dumps(check(root, Path(sys.argv[3]).resolve(), made["truth"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
