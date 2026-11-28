#!/usr/bin/env python3
"""Mutation check: do the tests notice when a gate or a command is quietly broken?

`mutants(source, limit, seed)` returns up to `limit` variants of a Python source. Each has one
small change made through the `ast` module: a comparison flipped, `and` swapped with `or`, a
`not` removed, an integer constant moved by one, or a returned boolean inverted. The same
source, limit and seed always give the same list, and every variant parses.

Call it from the root of a checkout:

    python3 swarm/phase3/mutate.py run FILE TEST_MODULE [--limit N] [--seed S] [--timeout SECONDS]

It copies the checkout (without `.git`) to a temporary folder, writes each mutant of FILE over the copy,
runs TEST_MODULE there (several modules may be given as one quoted, space-separated argument) (`python3 -m unittest TEST_MODULE`) and reports how many mutants the
tests noticed (killed). A mutant that makes the tests fail, error or run out of time is killed.
The surviving changes are printed as short diffs. Nothing is written into the repository.
"""
from __future__ import annotations

import argparse
import ast
import copy
import difflib
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPARE = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
           ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}


def sites(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Every place a change can be made, as (kind, node number in walk order, operator index)."""
    found = []
    for number, node in enumerate(ast.walk(tree)):
        if isinstance(node, ast.Compare):
            found += [("compare", number, i) for i, op in enumerate(node.ops) if type(op) in COMPARE]
        elif isinstance(node, ast.BoolOp):
            found.append(("boolop", number, 0))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            found.append(("not", number, 0))
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            found.append(("int", number, 0))
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and type(node.value.value) is bool:
            found.append(("return", number, 0))
    return found


def apply(tree: ast.AST, site: tuple[str, int, int], rng: random.Random) -> ast.AST:
    """A copy of the tree with the change at one site."""
    tree = copy.deepcopy(tree)
    kind, number, index = site
    node = list(ast.walk(tree))[number]
    if kind == "compare":
        node.ops[index] = COMPARE[type(node.ops[index])]()
    elif kind == "boolop":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif kind == "not":
        for parent in ast.walk(tree):
            for field, value in ast.iter_fields(parent):
                if value is node:
                    setattr(parent, field, node.operand)
                elif isinstance(value, list):
                    value[:] = [node.operand if item is node else item for item in value]
    elif kind == "int":
        node.value += rng.choice((1, -1))
    elif kind == "return":
        node.value.value = not node.value.value
    return ast.fix_missing_locations(tree)


def mutants(source: str, limit: int, seed: int) -> list[str]:
    """Up to `limit` variants of `source`, each with one small change; the same inputs give the same list."""
    tree = ast.parse(source)
    rng = random.Random(seed)
    chosen = sites(tree)
    rng.shuffle(chosen)
    base, seen, out = ast.unparse(tree), set(), []
    for site in chosen:
        if len(out) >= max(limit, 0):
            break
        try:
            text = ast.unparse(apply(tree, site, rng))
            ast.parse(text)
        except (ValueError, SyntaxError, RecursionError):
            continue
        if text != base and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def short_diff(before: str, after: str) -> str:
    lines = difflib.unified_diff(before.splitlines(), after.splitlines(), "original", "mutant", n=0, lineterm="")
    return "\n".join(line for line in lines if not line.startswith(("---", "+++")))[:400]


def run(path: str, module: str, limit: int, seed: int, timeout: int) -> dict:
    """Try the mutants of one file of the repository against one test module."""
    source = (ROOT / path).read_text(encoding="utf-8")
    base = ast.unparse(ast.parse(source))
    killed, survivors = 0, []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "copy"
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))  # the tests also read other folders
        env = {"PATH": os.environ.get("PATH", ""), "SWARM_HOME": str(Path(tmp) / "home"), "HOME": str(Path(tmp) / "home"), "PYTHONDONTWRITEBYTECODE": "1"}
        Path(env["HOME"]).mkdir()

        def passes(text: str) -> bool:
            (work / path).write_text(text, encoding="utf-8")
            try:
                done = subprocess.run([sys.executable, "-m", "unittest", *module.split()], cwd=work, env=env, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                return False
            return done.returncode == 0

        if not passes(source):
            raise SystemExit("the tests do not pass on the unchanged file")
        tried = mutants(source, limit, seed)
        for text in tried:
            if passes(text):
                survivors.append(short_diff(base, text))
            else:
                killed += 1
    return {"file": path, "module": module, "tried": len(tried), "killed": killed, "survivors": survivors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("verb", choices=["run"])
    parser.add_argument("file")
    parser.add_argument("module")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    result = run(args.file, args.module, args.limit, args.seed, args.timeout)
    print(f"{result['file']}: {result['killed']} of {result['tried']} mutants noticed by {result['module']}")
    for number, diff in enumerate(result["survivors"], 1):
        print(f"\nsurvivor {number}:\n{diff}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
