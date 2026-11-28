#!/usr/bin/env python3
"""Synthetic work for the swarm experiment: small, independent, equally sized tasks.

    python3 swarm/workload.py make OUT_DIR --first N --count K [--seed S]
    python3 swarm/workload.py check OUT_DIR [--json FILE]

Each task asks for one pure function from a written specification. There are ten
families (durations, ranges, rolling statistics, check digits, ordering, run-length
codes, versions, record splitting, truncation, spirals) and each task draws its own
parameters, so no two tasks have the same answer. Nothing here is real project data.

`make` writes OUT_DIR/T-0001/TASK.md and so on, and keeps the withheld tests beside them
in OUT_DIR/.hidden/, which no worker is told about. `check` reads each solution.py as
text first and refuses imports outside a short list, then runs the withheld tests in a
separate process with a time limit, and prints one line per task and a total.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import random
import re
import statistics
import subprocess
import sys
from pathlib import Path

ALLOWED_IMPORTS = {"math", "re", "itertools", "collections", "functools", "statistics", "heapq", "bisect", "string", "typing"}
FORBIDDEN_CALLS = {"eval", "exec", "open", "__import__", "compile", "input", "print", "globals", "locals"}
RULES = """# Worker task

Rules, the same for every worker:

1. Write exactly one file, `solution.py`, in this folder. Do not read or write anything else.
2. Use only these standard-library modules: math, re, itertools, collections, functools,
   statistics, heapq, bisect, string, typing.
3. No printing, no input, no code that runs on import.
4. You may run one quick check of your own with `python3`. Do not write test files.
5. When `solution.py` is written, reply with the single word DONE. If you cannot do it, reply FAILED.
"""
UNITS = [("w", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]


def _spiral_walk(grid):
    out, grid = [], [list(row) for row in grid]
    while grid:
        out += grid.pop(0)
        grid = [list(row) for row in zip(*grid)][::-1]
    return out


SPIRALS = {  # start corner, direction, first move, and how to turn the grid into the plain top-left clockwise walk
    ("top-left", "clockwise"): ("right", lambda g: g),
    ("top-left", "counter-clockwise"): ("down", lambda g: [list(r) for r in zip(*g)]),
    ("top-right", "clockwise"): ("down", lambda g: [list(r) for r in zip(*g)][::-1]),
    ("top-right", "counter-clockwise"): ("left", lambda g: [r[::-1] for r in g]),
    ("bottom-right", "clockwise"): ("left", lambda g: [r[::-1] for r in g[::-1]]),
    ("bottom-right", "counter-clockwise"): ("up", lambda g: [list(r) for r in zip(*[r[::-1] for r in g[::-1]])]),
    ("bottom-left", "clockwise"): ("up", lambda g: [list(r)[::-1] for r in zip(*g)]),
    ("bottom-left", "counter-clockwise"): ("right", lambda g: g[::-1]),
}


def family_duration(rng):
    units = dict(sorted(rng.sample(UNITS, rng.choice([3, 4])), key=lambda u: -u[1]))

    def ref(text):
        if not isinstance(text, str) or not re.fullmatch(r"(?:\d+[a-z])+", text):
            raise ValueError
        seen, total = set(), 0
        for number, unit in re.findall(r"(\d+)([a-z])", text):
            if unit not in units or unit in seen:
                raise ValueError
            seen.add(unit)
            total += int(number) * units[unit]
        return total

    names = list(units)
    cases = [("".join(f"{rng.randint(0, 90)}{u}" for u in rng.sample(names, rng.randint(1, len(names)))),) for _ in range(8)]
    cases += [("",), ("5x",), (f"3{names[0]}3{names[0]}",), (f"{names[0]}5",), ("12",), (f"1{names[0]} 2{names[-1]}",)]
    table = ", ".join(f"`{u}` = {v}" for u, v in units.items())
    spec = (f"`{{fn}}(text: str) -> int`\n\n`text` is a run of `<number><unit>` pairs with no spaces, for example "
            f"`{cases[0][0]}`. Units: {table} seconds. A unit may appear at most once, in any order. Return the total "
            "number of seconds. Raise `ValueError` if `text` is empty, uses another unit, repeats a unit, or contains anything else.")
    return ref, cases, spec


def family_ranges(rng):
    gap = rng.randint(0, 3)

    def ref(ranges):
        rows = sorted(list(r) for r in ranges)
        if any(len(r) != 2 or r[0] > r[1] for r in rows):
            raise ValueError
        out = []
        for start, end in rows:
            if out and start <= out[-1][1] + gap:
                out[-1][1] = max(out[-1][1], end)
            else:
                out.append([start, end])
        return out

    def one():
        rows = []
        for _ in range(rng.randint(1, 7)):
            start = rng.randint(0, 40)
            rows.append([start, start + rng.randint(0, 6)])
        return rows

    cases = [(one(),) for _ in range(10)] + [([],), ([[5, 2]],), ([[1, 1], [1 + gap, 9]],), ([[1, 1], [2 + gap, 9]],)]
    spec = (f"`{{fn}}(ranges: list[list[int]]) -> list[list[int]]`\n\nEach item is `[start, end]` with both ends included. "
            f"Sort the ranges and merge two neighbours whenever the next start is at most the current end plus {gap}. "
            "Return the merged ranges as lists, sorted by start. Raise `ValueError` if any item has start greater than end. "
            "An empty list gives an empty list.")
    return ref, cases, spec


def family_rolling(rng):
    stat, window, digits = rng.choice(["mean", "median", "max", "min", "sum"]), rng.randint(2, 5), rng.randint(1, 3)
    func = {"mean": statistics.fmean, "median": statistics.median, "max": max, "min": min, "sum": sum}[stat]

    def ref(values):
        if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
            raise ValueError
        return [round(float(func(values[i:i + window])), digits) for i in range(len(values) - window + 1)]

    cases = [([rng.randint(-50, 50) for _ in range(rng.randint(0, 12))],) for _ in range(11)] + [([1, 2.5, 3, 4, 5, 6],), ([],)]
    spec = (f"`{{fn}}(values: list[int]) -> list[float]`\n\nSlide a window of {window} values over the list, one step at a time, "
            f"and for every full window return its {stat} as a float rounded with `round(x, {digits})`. A list shorter than the "
            "window gives an empty list. Raise `ValueError` if any value is not an `int` (a float or a bool is not allowed).")
    return ref, cases, spec


def family_check_digit(rng):
    weights, modulus = rng.sample([1, 2, 3, 5, 7], rng.choice([2, 3])), rng.choice([7, 9, 10, 11, 13])

    def ref(digits):
        if not isinstance(digits, str) or not re.fullmatch(r"[0-9]+", digits):
            raise ValueError
        total = sum(int(c) * weights[i % len(weights)] for i, c in enumerate(digits))
        return (modulus - total % modulus) % modulus

    cases = [("".join(rng.choice("0123456789") for _ in range(rng.randint(1, 14))),) for _ in range(10)] + [("",), ("12a4",), (" 123",), ("0",)]
    spec = (f"`{{fn}}(digits: str) -> int`\n\nMultiply each digit, from the left, by the weights {weights} repeated in that order, "
            f"and add the products. Return `({modulus} - total % {modulus}) % {modulus}`. Raise `ValueError` if `digits` is empty "
            "or has any character other than the ASCII digits 0 to 9.")
    return ref, cases, spec


def family_order(rng):
    latest = rng.choice([False, True])

    def ref(edges):
        nodes = sorted({n for edge in edges for n in edge})
        after = {n: set() for n in nodes}
        waiting = {n: 0 for n in nodes}
        for a, b in edges:
            if b not in after[a]:
                after[a].add(b)
                waiting[b] += 1
        out, ready = [], [n for n in nodes if not waiting[n]]
        while ready:
            node = max(ready) if latest else min(ready)
            ready.remove(node)
            out.append(node)
            for nxt in after[node]:
                waiting[nxt] -= 1
                if not waiting[nxt]:
                    ready.append(nxt)
        if len(out) != len(nodes):
            raise ValueError
        return out

    def one():
        names = rng.sample("abcdefghij", rng.randint(3, 7))
        return [list(sorted(rng.sample(names, 2))) for _ in range(rng.randint(2, 8))]

    cases = [(one(),) for _ in range(10)] + [([],), ([["a", "b"], ["b", "a"]],), ([["a", "b"], ["b", "c"], ["c", "a"], ["d", "a"]],), ([["x", "y"], ["x", "y"]],)]
    pick = "last" if latest else "first"
    spec = (f"`{{fn}}(edges: list[list[str]]) -> list[str]`\n\nEach edge `[a, b]` means `a` must come before `b`. Return every name "
            f"that appears, in an order that respects all edges. Whenever several names are ready, take the one that sorts {pick} "
            "alphabetically. A repeated edge counts once. Raise `ValueError` if the edges contain a cycle. No edges gives an empty list.")
    return ref, cases, spec


def family_run_length(rng):
    count_first, sep = rng.choice([False, True]), rng.choice(["", "-", ":", "."])

    def ref(text):
        if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z]*", text):
            raise ValueError
        groups = [(m.group(0)[0], len(m.group(0))) for m in re.finditer(r"(.)\1*", text)]
        return sep.join(f"{n}{c}" if count_first else f"{c}{n}" for c, n in groups)

    cases = [("".join(rng.choice("abAB") * rng.randint(1, 4) for _ in range(rng.randint(1, 6))),) for _ in range(10)] + [("",), ("a1",), ("a b",), ("zzzzzzzzzzzz",)]
    shape = "`<count><letter>`" if count_first else "`<letter><count>`"
    joined = f"joined by `{sep}`" if sep else "with nothing between them"
    spec = (f"`{{fn}}(text: str) -> str`\n\nReplace every run of the same letter by {shape}, in order, {joined}. Upper and lower "
            "case are different letters. An empty string gives an empty string. Raise `ValueError` if `text` has any character "
            "other than the letters A to Z and a to z.")
    return ref, cases, spec


def family_versions(rng):
    tag = rng.choice(["rc", "beta", "pre", "dev"])

    def key(text):
        match = re.fullmatch(rf"(\d+(?:\.\d+)*)(?:-{tag}(\d+))?", text) if isinstance(text, str) else None
        if not match:
            raise ValueError
        parts = [int(p) for p in match.group(1).split(".")]
        while parts and parts[-1] == 0:
            parts.pop()
        return parts, (0, int(match.group(2))) if match.group(2) else (1, 0)

    def ref(a, b):
        left, right = key(a), key(b)
        return (left > right) - (left < right)

    def one():
        base = ".".join(str(rng.randint(0, 3)) for _ in range(rng.randint(1, 4)))
        return base + (f"-{tag}{rng.randint(1, 3)}" if rng.random() < 0.4 else "")

    cases = [(one(), one()) for _ in range(9)] + [("1.0", "1"), (f"2.1-{tag}2", "2.1"), (f"2.1-{tag}2", f"2.1-{tag}10"), ("1..2", "1"), ("1.2", "v1.2"), ("1.10", "1.9")]
    spec = (f"`{{fn}}(a: str, b: str) -> int`\n\nA version is numbers joined by dots, optionally followed by `-{tag}N`, for example "
            f"`2.1` or `2.1-{tag}3`. Compare the numbers from the left as integers; missing trailing numbers count as zero, so `1.0` "
            f"equals `1`. With equal numbers, a version with `-{tag}N` is lower than one without, and two such versions compare by N "
            "as an integer. Return -1, 0 or 1. Raise `ValueError` if either string is not a version of this form.")
    return ref, cases, spec


def family_records(rng):
    delim, quote = rng.choice([";", "|", ","]), rng.choice(['"', "'"])

    def ref(line):
        fields, current, quoted, i = [], "", False, 0
        while i < len(line):
            char = line[i]
            if quoted:
                if char == quote and line[i + 1:i + 2] == quote:
                    current, i = current + quote, i + 1
                elif char == quote:
                    quoted = False
                else:
                    current += char
            elif char == quote:
                quoted = True
            elif char == delim:
                fields.append(current)
                current = ""
            else:
                current += char
            i += 1
        if quoted:
            raise ValueError
        return fields + [current]

    def one():
        cells = []
        for _ in range(rng.randint(1, 5)):
            word = "".join(rng.choice("abc xyz") for _ in range(rng.randint(0, 5)))
            style = rng.random()
            cells.append(f"{quote}{word}{delim}{word}{quote}" if style < 0.3 else f"{quote}{word}{quote}{quote}s{quote}" if style < 0.5 else word)
        return delim.join(cells)

    cases = [(one(),) for _ in range(10)] + [("",), (f"a{delim}{quote}b",), (f"{delim}{delim}",), (f"{quote}{quote}",)]
    spec = (f"`{{fn}}(line: str) -> list[str]`\n\nSplit one record into fields at `{delim}`. A part wrapped in `{quote}` may contain "
            f"the separator; inside such a part, two `{quote}` in a row stand for one. The wrapping characters are not part of the "
            "field. Text outside the wrapping is kept as it is. An empty line gives one empty field. Raise `ValueError` if a wrapped part is never closed.")
    return ref, cases, spec


def family_truncate(rng):
    mark = rng.choice(["…", "...", "~", " >"])

    def ref(text, width):
        if width < len(mark):
            raise ValueError
        if len(text) <= width:
            return text
        cut = text[:width - len(mark)]
        if " " in cut:
            cut = cut[:cut.rfind(" ")]
        return cut.rstrip() + mark

    words = ["motion", "engine", "verify", "a", "of", "registry", "hub", "frame", "export", "quality"]
    cases = [(" ".join(rng.choice(words) for _ in range(rng.randint(1, 8))), rng.randint(len(mark), 30)) for _ in range(11)]
    cases += [("abc", len(mark) - 1), ("", 5), ("abcdefghij", len(mark)), ("ab  cd  ef", 6 + len(mark))]
    spec = (f"`{{fn}}(text: str, width: int) -> str`\n\nIf `text` has at most `width` characters, return it unchanged. Otherwise take "
            f"the first `width - {len(mark)}` characters; if that piece contains a space, drop everything from its last space on; "
            f"strip trailing spaces; then append `{mark}` ({len(mark)} characters). Raise `ValueError` if `width` is less than {len(mark)}.")
    return ref, cases, spec


def family_spiral(rng):
    corner, turn = rng.choice(sorted(SPIRALS))
    first, to_plain = SPIRALS[(corner, turn)]

    def ref(grid):
        if not grid:
            return []
        if any(len(row) != len(grid[0]) for row in grid) or not grid[0]:
            raise ValueError
        return _spiral_walk(to_plain([list(row) for row in grid]))

    def one():
        rows, cols = rng.randint(1, 4), rng.randint(1, 5)
        numbers = iter(rng.sample(range(100), rows * cols))
        return [[next(numbers) for _ in range(cols)] for _ in range(rows)]

    cases = [(one(),) for _ in range(11)] + [([],), ([[1, 2], [3]],), ([[7]],)]
    spec = (f"`{{fn}}(grid: list[list[int]]) -> list[int]`\n\nWalk the rectangular grid in a spiral and return the values in the order "
            f"visited. Start at the {corner} cell, move {first} first, and keep turning {turn} inward until every cell is visited "
            "once. An empty grid gives an empty list. Raise `ValueError` if the rows have different lengths or a row is empty.")
    return ref, cases, spec


FAMILIES = [("parse_duration", family_duration), ("merge_ranges", family_ranges), ("rolling_stat", family_rolling),
            ("check_digit", family_check_digit), ("order_names", family_order), ("run_length", family_run_length),
            ("compare_versions", family_versions), ("split_record", family_records), ("truncate_text", family_truncate),
            ("spiral_walk", family_spiral)]


def task(number: int, seed: int) -> dict:
    name, build = FAMILIES[(number - 1) % len(FAMILIES)]
    rng = random.Random(f"{seed}:{number}")
    ref, cases, spec = build(rng)
    function = f"{name}_{number:04d}"
    tests = []
    for args in cases:
        try:
            tests.append({"args": list(args), "expect": ref(*json.loads(json.dumps(list(args))))})
        except ValueError:
            tests.append({"args": list(args), "raises": "ValueError"})
    shown = [t for t in tests if "expect" in t][:2] + [t for t in tests if "raises" in t][:1]
    examples = "\n".join(f"- `{function}({', '.join(json.dumps(a, ensure_ascii=False) for a in t['args'])})` "
                         + (f"returns `{json.dumps(t['expect'], ensure_ascii=False)}`" if "expect" in t else "raises `ValueError`") for t in shown)
    text = f"{RULES}\n## Task T-{number:04d}\n\nWrite the function {spec.format(fn=function)}\n\nExamples:\n\n{examples}\n"
    return {"id": f"T-{number:04d}", "family": name, "function": function, "text": text, "tests": tests,
            "fingerprint": hashlib.sha256(text.encode()).hexdigest()}


def make(out: Path, first: int, count: int, seed: int) -> list[dict]:
    hidden = out / ".hidden"
    hidden.mkdir(parents=True, exist_ok=True)
    made = []
    for number in range(first, first + count):
        item = task(number, seed)
        folder = out / item["id"]
        folder.mkdir(exist_ok=True)
        (folder / "TASK.md").write_text(item["text"], encoding="utf-8")
        (hidden / f"{item['id']}.json").write_text(json.dumps({k: item[k] for k in ("id", "family", "function", "tests", "fingerprint")}, ensure_ascii=False), encoding="utf-8")
        made.append(item)
    return made


RUNNER = r"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("solution", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
hidden = json.load(open(sys.argv[2])); function = getattr(module, hidden["function"]); passed = 0
for test in hidden["tests"]:
    try:
        got = function(*test["args"]); ok = "expect" in test and got == test["expect"] and type(got) is type(test["expect"])
    except ValueError:
        ok = "raises" in test
    except Exception:
        ok = False
    passed += bool(ok)
print(json.dumps({"passed": passed, "total": len(hidden["tests"])}))
"""


def isolated(command: list[str], cwd: Path | None = None, timeout: int = 20) -> subprocess.CompletedProcess:
    """Run code an agent wrote: no inherited environment, and no network where the kernel allows."""
    cage = ["unshare", "-n"] if subprocess.run(["unshare", "-n", "true"], capture_output=True).returncode == 0 else []
    return subprocess.run([*cage, *command], cwd=cwd, capture_output=True, text=True, timeout=timeout, env={"PATH": os.environ.get("PATH", "")})


def inspect(source: str, allowed: set[str] = ALLOWED_IMPORTS) -> list[str]:
    """What a reader would object to before running the file at all.

    This is a screen, not a sandbox: it refuses the obvious, and the run that follows is
    still done by `isolated`, with a time limit."""
    try:
        tree = ast.parse(source)
    except SyntaxError as problem:
        return [f"does not parse: {problem.msg}"]
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            findings += [f"import of {name}" for name in names if name.split(".")[0] not in allowed]
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            findings.append(f"use of {node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            findings.append(f"call of {node.func.id}")
    return findings


def check_one(folder: Path, hidden: Path) -> dict:
    solution = folder / "solution.py"
    row = {"id": folder.name, "written": solution.exists(), "passed": 0, "total": len(json.loads(hidden.read_text())["tests"]),
           "findings": [], "lines": 0, "extra_files": sorted(p.name for p in folder.iterdir() if p.name not in ("TASK.md", "solution.py", "__pycache__"))}
    if not row["written"]:
        return {**row, "verified": False}
    source = solution.read_text(encoding="utf-8", errors="replace")
    row["lines"] = len(source.splitlines())
    row["sha256"] = hashlib.sha256(source.encode()).hexdigest()
    row["findings"] = inspect(source)
    if not row["findings"]:
        try:
            done = isolated([sys.executable, "-I", "-c", RUNNER, str(solution), str(hidden)])
            row.update(json.loads(done.stdout) if done.returncode == 0 else {"error": (done.stderr.strip().splitlines() or ["failed"])[-1][:120]})
        except subprocess.TimeoutExpired:
            row["error"] = "timed out"
    row["verified"] = row["passed"] == row["total"] and not row["findings"]
    return row


def check(out: Path) -> dict:
    rows = [check_one(out / hidden.stem, hidden) for hidden in sorted((out / ".hidden").glob("T-*.json"))]
    return {"tasks": len(rows), "written": sum(r["written"] for r in rows), "verified": sum(r["verified"] for r in rows),
            "tests_passed": sum(r["passed"] for r in rows), "tests_total": sum(r["total"] for r in rows),
            "security_findings": sum(len(r["findings"]) for r in rows), "extra_files": sum(len(r["extra_files"]) for r in rows),
            "mean_lines": round(sum(r["lines"] for r in rows) / max(1, sum(r["written"] for r in rows)), 1), "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    maker = commands.add_parser("make")
    maker.add_argument("out", type=Path)
    maker.add_argument("--first", type=int, required=True)
    maker.add_argument("--count", type=int, required=True)
    maker.add_argument("--seed", type=int, default=20261128)
    checker = commands.add_parser("check")
    checker.add_argument("out", type=Path)
    checker.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.command == "make":
        made = make(args.out, args.first, args.count, args.seed)
        print(f"{len(made)} tasks {made[0]['id']}..{made[-1]['id']} in {len({m['family'] for m in made})} families")
        return 0
    result = check(args.out)
    if args.json:
        args.json.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    failed = [f"{r['id']}:{r['passed']}/{r['total']}" + (":" + ";".join(r["findings"]) if r["findings"] else "") for r in result["rows"] if not r["verified"]]
    print({k: v for k, v in result.items() if k != "rows"})
    if failed:
        print("not verified:", " ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
