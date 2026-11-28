#!/usr/bin/env python3
"""Tasks of three sizes for the second phase, each with tests the worker never sees.

    python3 swarm/phase2/tasks.py make OUT SIZE FIRST COUNT [--mode lean|raw] [--seed N]
    python3 swarm/phase2/tasks.py check OUT [--json FILE]

    small   one function: the ten families of the first phase, with a new seed
    medium  one module whose parts work together: four families written here, each with a
            reference solution that obeys the worker's own rules
    large   a generated project with one planted bug and four questions: bench.py of the
            first phase, one project per task

Every task folder holds TASK.md. What the worker's command needs is in OUT/.kit, and the
withheld tests are in OUT/.hidden. The worker's command never opens .hidden.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import random
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import bench  # noqa: E402
import workload  # noqa: E402

SEED = 20261129
RULES = ("Python 3, one file. You may import only: math, re, itertools, collections, functools, statistics, heapq, bisect, string, "
         "typing. No printing, no input, no files, no network. Where the task says ValueError, raise exactly that.")
SIZES = {"S": "small", "M": "medium", "L": "large"}

# Runs a file against a suite. A suite is {"entry": class name or null, "tests": [{"init": [...], "steps": [...]}]};
# a step is {"call", "args", "expect"} or {"call", "args", "raises"}. A test passes when every step does.
RUNNER = r"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("solution", sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
suite = json.load(open(sys.argv[2])); passed = 0; first = None
def same(a, b):
    if type(a) is not type(b): return False
    if isinstance(a, list): return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict): return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return a == b
def run(target, step):
    try:
        got = getattr(target, step["call"])(*step["args"])
    except ValueError:
        return "raises" in step, "raised ValueError"
    except Exception as problem:
        return False, "raised " + type(problem).__name__
    if "raises" in step: return False, "returned " + repr(got)[:80]
    try: ok = same(json.loads(json.dumps(got)), step["expect"])
    except (TypeError, ValueError): ok = False
    return ok, "returned " + repr(got)[:80]
for number, test in enumerate(suite["tests"], 1):
    ok = True
    try:
        target = getattr(module, suite["entry"])(*test.get("init", [])) if suite.get("entry") else module
        for index, step in enumerate(test["steps"], 1):
            ok, what = run(target, step)
            if not ok:
                first = first or {"test": number, "step": index, "call": step["call"], "args": step["args"], "what": what,
                                  "want": "ValueError" if "raises" in step else step["expect"]}
                break
    except Exception as problem:
        ok = False; first = first or {"test": number, "step": 0, "call": suite.get("entry"), "args": [], "what": "raised " + type(problem).__name__, "want": "an object"}
    passed += bool(ok)
print(json.dumps({"passed": passed, "total": len(suite["tests"]), "first_failure": first}))
"""


def run_suite(solution: Path, suite: dict, timeout: int = 20) -> dict:
    """Run code a worker wrote against a suite: no inherited environment, no network, a time limit."""
    with tempfile.TemporaryDirectory(prefix="suite-") as scratch:
        file = Path(scratch) / "suite.json"
        file.write_text(json.dumps(suite))
        try:
            done = workload.isolated([sys.executable, "-I", "-c", RUNNER, str(solution), str(file)], timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"passed": 0, "total": len(suite["tests"]), "error": "timed out"}
    if done.returncode != 0:
        return {"passed": 0, "total": len(suite["tests"]), "error": (done.stderr.strip().splitlines() or ["failed"])[-1][:160]}
    return json.loads(done.stdout)


# ---- medium families: a specification, a reference file, and scripts of calls --------------

LEDGER = '''
class Ledger:
    def __init__(self):
        self.money = {}
        self.log = {}

    def _known(self, account):
        if account not in self.money:
            raise ValueError("unknown account")

    def deposit(self, account, amount):
        if amount <= 0:
            raise ValueError("amount")
        self.money[account] = self.money.get(account, 0) + amount
        self.log.setdefault(account, []).append(["deposit", amount])
        return self.money[account]

    def withdraw(self, account, amount):
        self._known(account)
        if amount <= 0 or self.money[account] - amount < -LIMIT:
            raise ValueError("amount")
        self.money[account] -= amount
        self.log[account].append(["withdraw", amount])
        return self.money[account]

    def transfer(self, source, target, amount):
        self._known(source)
        if source == target or amount <= 0 or self.money[source] - amount - FEE < -LIMIT:
            raise ValueError("transfer")
        self.money[source] -= amount + FEE
        self.log[source].append(["out", amount])
        if FEE:
            self.log[source].append(["fee", FEE])
        self.money[target] = self.money.get(target, 0) + amount
        self.log.setdefault(target, []).append(["in", amount])
        return self.money[source]

    def balance(self, account):
        self._known(account)
        return self.money[account]

    def history(self, account):
        self._known(account)
        return [list(entry) for entry in self.log[account]]

    def richest(self, count):
        return sorted(self.money, key=lambda name: (-self.money[name], name))[:count]
'''


def family_ledger(rng):
    limit, fee = rng.choice([0, 50, 200]), rng.choice([0, 1, 3])
    names = rng.sample(["ada", "bob", "cy", "dee", "eve", "fay"], 4)
    a, b, c, _ = names
    floor = "0" if limit == 0 else f"-{limit}"
    spec = (
        "`Ledger()` keeps whole-number balances for named accounts. An account exists once money has been deposited in it or "
        "transferred to it. Every method raises `ValueError` when its rule is broken, and then changes nothing.\n\n"
        "- `deposit(account, amount)`: `amount` must be above zero. Adds it, creating the account if needed, and returns the new balance.\n"
        f"- `withdraw(account, amount)`: the account must exist, `amount` must be above zero, and the balance may not fall below {floor}. "
        "Returns the new balance.\n"
        "- `transfer(source, target, amount)`: `source` must exist and differ from `target`, and `amount` must be above zero. The source pays "
        f"`amount` plus a fee of {fee} and may not fall below {floor}. The target receives `amount` and is created if needed. Returns the "
        "source's new balance.\n"
        "- `balance(account)`: the balance. The account must exist.\n"
        "- `history(account)`: the account's entries, oldest first, each a list `[kind, amount]`. The kinds are `\"deposit\"`, `\"withdraw\"`, "
        "`\"out\"` (money sent), `\"fee\"` (written right after `\"out\"`, and only when the fee is not zero) and `\"in\"` (money received). "
        "The account must exist.\n"
        "- `richest(count)`: the names of at most `count` accounts, highest balance first, equal balances in alphabetical order.")
    tour = [("deposit", (a, 120)), ("deposit", (b, 40)), ("transfer", (a, b, 30)), ("withdraw", (b, 10)), ("balance", (a,)),
            ("history", (a,)), ("history", (b,)), ("richest", (2,))]
    errors = [("withdraw", (a, 5)), ("deposit", (a, 0)), ("deposit", (a, 100)), ("transfer", (a, a, 10)), ("transfer", (c, a, 10)),
              ("withdraw", (a, 100 + limit)), ("withdraw", (a, 1)), ("balance", (a,))]
    edge = [("deposit", (a, 100)), ("transfer", (a, b, 100 + limit - fee)), ("transfer", (a, b, 1)), ("balance", (a,)), ("balance", (b,)),
            ("history", (a,)), ("richest", (5,))]
    ties = [("deposit", (b, 50)), ("deposit", (a, 50)), ("deposit", (c, 70)), ("richest", (3,)), ("richest", (0,)), ("richest", (1,)),
            ("history", (c,)), ("balance", (names[3],))]

    def more():
        script = []
        for _ in range(rng.randint(8, 11)):
            who, other = rng.sample(names, 2)
            amount = rng.choice([0, -5, 10, 25, 60, 140, 300])
            script.append(rng.choice([("deposit", (who, amount)), ("deposit", (who, amount)), ("withdraw", (who, amount)),
                                      ("transfer", (who, other, amount)), ("transfer", (who, other, amount)), ("balance", (who,)),
                                      ("history", (who,)), ("richest", (rng.randint(0, 4),))]))
        return script

    source = LEDGER.replace("LIMIT", str(limit)).replace("FEE", str(fee))
    return {"entry": "Ledger", "what": "the class `Ledger`", "spec": spec, "source": source, "scripts": [tour, errors, edge, ties, *[more() for _ in range(8)]]}


EXPR = '''
DIGITS = "0123456789"
LETTERS = "abcdefghijklmnopqrstuvwxyz"


def tokenize(text):
    tokens, at = [], 0
    while at < len(text):
        char = text[at]
        if char == " ":
            at += 1
        elif char in DIGITS or char in LETTERS:
            group = DIGITS if char in DIGITS else LETTERS
            end = at
            while end < len(text) and text[end] in group:
                end += 1
            tokens.append(text[at:end])
            at = end
        elif char in "+-*()EXTRA":
            tokens.append(char)
            at += 1
        else:
            raise ValueError("character")
    return tokens


def evaluate(text, variables):
    tokens = tokenize(text)
    at = 0

    def peek():
        return tokens[at] if at < len(tokens) else None

    def take():
        nonlocal at
        at += 1
        return tokens[at - 1]

    def factor():
        token = peek()
        if token is None:
            raise ValueError("end")
        take()
        if token == "-":
            return -factor()
        if token == "(":
            value = total()
            if peek() != ")":
                raise ValueError("bracket")
            take()
            return value
        if token[0] in DIGITS:
            return int(token)
        if token[0] in LETTERS:
            if token not in variables:
                raise ValueError("name")
            return variables[token]
        raise ValueError("token")

    def product():
        value = factor()
        while peek() in ("*", "EXTRA"):
            sign = take()
            right = factor()
            if sign == "*":
                value *= right
            elif right == 0:
                raise ValueError("zero")
            else:
                value = OPERATION
        return value

    def total():
        value = product()
        while peek() in ("+", "-"):
            sign = take()
            right = product()
            value = value + right if sign == "+" else value - right
        return value

    result = total()
    if at != len(tokens):
        raise ValueError("left over")
    return result
'''


def family_expr(rng):
    extra = rng.choice(["/", "%"])
    meaning, python = ("floor division", "//") if extra == "/" else ("the remainder", "%")
    names = rng.sample(["x", "y", "ab", "n", "rate", "k"], 3)
    env = {name: rng.randint(-9, 12) for name in names}
    spec = (
        "Two functions for a small arithmetic language over whole numbers.\n\n"
        f"Tokens: a number is a run of the digits `0` to `9`; a name is a run of the lowercase letters `a` to `z`; each of `+ - * {extra} ( )` "
        "is a token by itself. Spaces separate tokens and mean nothing else. Any other character is an error.\n\n"
        "- `tokenize(text)` returns the tokens as a list of strings, in order. `tokenize(\"12*(ab-3)\")` is "
        "`[\"12\", \"*\", \"(\", \"ab\", \"-\", \"3\", \")\"]`, and `\"2x\"` is the two tokens `\"2\"` and `\"x\"`.\n"
        "- `evaluate(text, variables)` returns the whole-number value of the expression. `variables` is a dict from names to whole numbers.\n"
        f"  - `*` and `{extra}` are applied before `+` and `-`. Signs of the same strength are applied from left to right. Brackets group.\n"
        f"  - `{extra}` is {meaning}, exactly Python's `{python}` on integers.\n"
        f"  - A `-` standing where a value is expected negates the one number, name, bracket or negation that follows it, before any `*` or "
        f"`{extra}`: `-7 {extra} 2` means `(-7) {extra} 2`, `2*-3` is `-6` and `--3` is `3`.\n"
        "  - Raise `ValueError` for a character that is no token, for an expression that is empty or not well formed (such as `1 +`, `(2`, "
        f"`2 3` or `2x`), for a name that is missing from `variables`, and for a zero on the right of `{extra}`.")

    def build(depth):
        if depth == 0 or rng.random() < 0.3:
            return rng.choice([str(rng.randint(0, 20)), rng.choice(names)])
        kind = rng.random()
        if kind < 0.15:
            return "-" + build(depth - 1)
        if kind < 0.4:
            return "(" + build(depth - 1) + ")"
        return build(depth - 1) + rng.choice([" + ", " - ", "*", " * ", extra]) + build(depth - 1)

    tour = [("tokenize", (f"12*({names[2]}-3)",)), ("evaluate", (f"2 + 3 * {names[0]}", env)), ("evaluate", (f"-7 {extra} 2", env)),
            ("evaluate", (f"({names[0]} + {names[1]}) * 2 - 10 {extra} 4", env)), ("evaluate", ("1 +", env)), ("tokenize", ("3 $ 4",))]
    fixed = ["--3", "2*-3", "2--3", "(1+2)*3", "10-4-3", f"20{extra}3{extra}2", f"{names[0]}*({names[1]}+{names[2]})", "", "(2", "2 3", "2x",
             "zz+1", f"5{extra}0", f"5{extra}(2-2)", "1+)", "()", "3 $ 4", f"-({names[0]}{extra}3)", f"7{extra}-2", "((4))"]
    scripts = [tour, *[[("evaluate", (text, env))] for text in fixed], *[[("evaluate", (build(3), env))] for _ in range(10)],
               [("tokenize", ("A+1",))], [("tokenize", (f"  7{extra}ab )( ",))], [("tokenize", ("",))]]
    source = EXPR.replace("EXTRA", extra).replace("OPERATION", f"value {python} right")
    return {"entry": None, "what": "the functions `tokenize` and `evaluate`", "spec": spec, "source": source, "scripts": scripts, "single": True}


ROOMS = '''
class Rooms:
    def __init__(self):
        self.items = {}
        self.count = 0

    def book(self, start, end, who):
        if not OPEN <= start < end <= CLOSE:
            raise ValueError("hours")
        current = list(self.items.values())
        if any(start < other_end and other_start < end for other_start, other_end, _ in current):
            raise ValueError("overlap")
        if sum(1 for _, _, name in current if name == who) >= MOST:
            raise ValueError("too many")
        self.count += 1
        self.items[self.count] = (start, end, who)
        return self.count

    def cancel(self, number):
        if number not in self.items:
            raise ValueError("number")
        del self.items[number]

    def agenda(self):
        return [list(item) for item in sorted(self.items.values())]

    def free(self, least):
        spans, at = [], OPEN
        for start, end, _ in sorted(self.items.values()):
            if start - at >= least and start > at:
                spans.append([at, start])
            at = end
        if CLOSE - at >= least and CLOSE > at:
            spans.append([at, CLOSE])
        return spans

    def busiest(self):
        if not self.items:
            raise ValueError("empty")
        minutes = {}
        for start, end, who in self.items.values():
            minutes[who] = minutes.get(who, 0) + end - start
        return min(minutes, key=lambda who: (-minutes[who], who))
'''


def family_rooms(rng):
    opens, closes, most = rng.choice([480, 540, 600]), rng.choice([1020, 1080]), rng.choice([2, 3])
    people = rng.sample(["kim", "lee", "max", "noa", "oz"], 3)
    k, l, m = people
    spec = (
        f"`Rooms()` books one meeting room for one day. Times are whole minutes of the day. The room is open from {opens} to {closes}. "
        "Every method raises `ValueError` when its rule is broken, and then changes nothing.\n\n"
        f"- `book(start, end, who)`: needs `{opens} <= start < end <= {closes}`, no overlap with a current booking, and `who` holding fewer "
        f"than {most} current bookings. Two bookings may touch: one may start at the minute another ends. Returns the booking's number: 1 for "
        "the first successful booking, then 2, 3 and so on. A number is never used twice.\n"
        "- `cancel(number)`: removes that current booking and returns `None`. The number must belong to a current booking.\n"
        "- `agenda()`: the current bookings as lists `[start, end, who]`, earliest first.\n"
        "- `free(least)`: the stretches of the open hours that hold no booking, earliest first, as lists `[start, end]`. Each stretch runs "
        "from the opening time or the end of a booking to the start of the next booking or the closing time. Stretches shorter than `least` "
        "minutes are left out.\n"
        "- `busiest()`: the person with the most booked minutes in current bookings; on a tie, the alphabetically first. Needs at least one "
        "current booking.")
    tour = [("book", (opens + 30, opens + 90, k)), ("book", (opens + 90, opens + 120, l)), ("book", (opens + 60, opens + 100, m)), ("agenda", ()),
            ("free", (30,)), ("busiest", ()), ("cancel", (1,)), ("cancel", (1,)), ("free", (1,)), ("book", (opens, opens + 10, l))]
    errors = [("busiest", ()), ("book", (opens - 15, opens + 30, k)), ("book", (closes - 30, closes + 15, k)), ("book", (opens + 60, opens + 60, k)),
              *[("book", (opens + 60 * i, opens + 60 * i + 30, k)) for i in range(most + 1)], ("cancel", (1,)),
              ("book", (opens + 60 * most, opens + 60 * most + 30, k)), ("agenda", ()), ("free", (31,))]
    tie = [("book", (opens, opens + 45, m)), ("book", (opens + 45, opens + 90, k)), ("busiest", ()), ("book", (closes - 15, closes, k)), ("busiest", ()),
           ("free", (1,)), ("cancel", (2,)), ("busiest", ()), ("cancel", (7,))]

    def more():
        script = []
        for _ in range(rng.randint(8, 11)):
            start = opens + 15 * rng.randint(-1, (closes - opens) // 15)
            script.append(rng.choice([("book", (start, start + 15 * rng.randint(0, 6), rng.choice(people))),
                                      ("book", (start, start + 15 * rng.randint(1, 4), rng.choice(people))), ("cancel", (rng.randint(1, 5),)),
                                      ("agenda", ()), ("free", (rng.choice([1, 30, 60, 120]),)), ("busiest", ())]))
        return script

    source = ROOMS.replace("OPEN", str(opens)).replace("CLOSE", str(closes)).replace("MOST", str(most))
    return {"entry": "Rooms", "what": "the class `Rooms`", "spec": spec, "source": source, "scripts": [tour, errors, tie, *[more() for _ in range(9)]]}


GRAPH = '''
class Graph:
    def __init__(self):
        self.needs = {}

    def _known(self, name):
        if name not in self.needs:
            raise ValueError("unknown")

    def _reach(self, name):
        seen, stack = set(), list(self.needs[name])
        while stack:
            other = stack.pop()
            if other not in seen:
                seen.add(other)
                stack.extend(self.needs[other])
        seen.discard(name)
        return seen

    def add(self, name, needs):
        if name in needs:
            raise ValueError("itself")
        for other in needs:
            self.needs.setdefault(other, set())
        self.needs[name] = set(needs)

    def order(self):
        left = {name: set(needs) for name, needs in self.needs.items()}
        result = []
        while left:
            ready = [name for name, needs in left.items() if not needs]
            if not ready:
                raise ValueError("cycle")
            pick = PICK(ready)
            result.append(pick)
            del left[pick]
            for needs in left.values():
                needs.discard(pick)
        return result

    def requires(self, name):
        self._known(name)
        return sorted(self._reach(name))

    def dependents(self, name):
        self._known(name)
        return sorted(other for other in self.needs if other != name and name in self._reach(other))

    def remove(self, name):
        self._known(name)
        if any(name in needs for other, needs in self.needs.items() if other != name):
            raise ValueError("needed")
        del self.needs[name]
'''


def family_graph(rng):
    pick, which = rng.choice([("min", "first"), ("max", "last")])
    pool = rng.sample(["api", "cli", "core", "db", "log", "net", "ui", "web"], 6)
    app, lib, log, core = pool[:4]
    spec = (
        "`Graph()` records which package needs which. A package is known once it has been added or named in another package's needs. "
        "Every method raises `ValueError` when its rule is broken, and then changes nothing.\n\n"
        "- `add(name, needs)`: `needs` is a list of package names and must not contain `name`. Records that `name` needs exactly these "
        "packages, replacing what was recorded for `name` before. Names in `needs` that were not known become known, needing nothing. "
        "Returns `None`.\n"
        "- `order()`: every known package, each one after all the packages it needs. Build the list one package at a time: of the packages "
        f"not yet in the list whose needs are all in it, take the alphabetically {which}. If packages are left and none can be taken, raise "
        "`ValueError`.\n"
        "- `requires(name)`: every package that `name` needs, directly or through others, in alphabetical order, without `name` itself. "
        "`name` must be known.\n"
        "- `dependents(name)`: every other package that needs `name`, directly or through others, in alphabetical order. `name` must be known.\n"
        "- `remove(name)`: forgets a known package and its own needs. Not allowed while another package directly needs it. Returns `None`.")
    tour = [("add", (app, [lib, log])), ("add", (lib, [core])), ("add", (log, [core])), ("order", ()), ("requires", (app,)), ("dependents", (core,)),
            ("remove", (core,)), ("remove", (app,)), ("order", ())]
    errors = [("add", (app, [app])), ("requires", (app,)), ("order", ()), ("add", (app, [lib])), ("add", (lib, [app])), ("order", ()),
              ("requires", (app,)), ("dependents", (app,)), ("add", (lib, [])), ("order", ()), ("remove", (lib,)), ("remove", (app,)), ("order", ())]

    def more():
        script = []
        for _ in range(rng.randint(8, 11)):
            name = rng.choice(pool)
            script.append(rng.choice([("add", (name, rng.sample(pool, rng.randint(0, 2)))), ("add", (name, rng.sample(pool, rng.randint(0, 2)))),
                                      ("add", (name, rng.sample(pool, rng.randint(1, 3)))), ("order", ()), ("requires", (name,)),
                                      ("dependents", (name,)), ("remove", (name,))]))
        return script

    return {"entry": "Graph", "what": "the class `Graph`", "spec": spec, "source": GRAPH.replace("PICK", pick), "scripts": [tour, errors, *[more() for _ in range(10)]]}


MEDIUM = [("ledger", family_ledger), ("expr", family_expr), ("rooms", family_rooms), ("graph", family_graph)]


def play(source: str, entry: str | None, script: list) -> dict:
    """Run a script of calls against a fresh copy of the reference and record what each call does."""
    space: dict = {}
    exec(compile(source, "<reference>", "exec"), space)  # noqa: S102 - the reference is this file's own text
    target = space[entry]() if entry else types.SimpleNamespace(**space)
    steps = []
    for call, args in script:
        args = json.loads(json.dumps(list(args)))
        try:
            steps.append({"call": call, "args": args, "expect": json.loads(json.dumps(getattr(target, call)(*json.loads(json.dumps(args)))))})
        except ValueError:
            steps.append({"call": call, "args": args, "raises": "ValueError"})
    return {"steps": steps}


def shown(step: dict) -> str:
    call = f"{step['call']}({', '.join(repr(a) for a in step['args'])})"
    return f"- `{call}` " + ("raises `ValueError`" if "raises" in step else f"returns `{step['expect']!r}`")


def finish(ident: str, size: str, family: str, entry: str | None, body: str, tests: list, examples: list, source: str | None = None) -> dict:
    text = f"## Task {ident}\n\n{RULES}\n\n{body.strip()}\n"
    return {"id": ident, "size": size, "family": family, "text": text, "suite": {"entry": entry, "tests": tests},
            "examples": {"entry": entry, "tests": examples}, "reference": source, "fingerprint": hashlib.sha256(text.encode()).hexdigest()}


def small(number: int, seed: int) -> dict:
    item = workload.task(number, seed)
    body = item["text"].split("\n## Task ", 1)[1].split("\n", 1)[1]

    def as_test(test):
        step = {"call": item["function"], "args": test["args"]}
        step.update({"expect": test["expect"]} if "expect" in test else {"raises": "ValueError"})
        return {"steps": [step]}

    picked = [t for t in item["tests"] if "expect" in t][:2] + [t for t in item["tests"] if "raises" in t][:1]
    return finish(f"S-{number:04d}", "small", item["family"], None, body, [as_test(t) for t in item["tests"]], [as_test(t) for t in picked])


def medium(number: int, seed: int) -> dict:
    name, build = MEDIUM[(number - 1) % len(MEDIUM)]
    made = build(random.Random(f"{seed}:M:{number}"))
    tests = [play(made["source"], made["entry"], script) for script in made["scripts"]]
    examples = tests[:2]
    if made.get("single"):
        title = "Examples, each a separate call:"
    else:
        title = f"Example, as calls in order on one new `{made['entry']}()`:"
    lines = [f"Write a module with {made['what']}.", "", made["spec"], "", title, "", *[shown(step) for step in tests[0]["steps"]]]
    if not made.get("single"):
        lines += ["", f"And on another new `{made['entry']}()`:", "", *[shown(step) for step in tests[1]["steps"]]]
    return finish(f"M-{number:04d}", "medium", name, made["entry"], "\n".join(lines), tests, examples, made["source"])


COMMANDS = {
    "raw": ("- `swk test ID` runs the tests\n"
            "- `swk read ID PATH` prints a file with line numbers; `swk read ID PATH FIRST:LAST` prints those lines only\n"
            "- `swk grep ID 'REGEX'` searches the project; `swk grep ID 'REGEX' PATH` searches one file or folder\n"),
    "lean": ("- `swk test ID` runs the tests and shows the failures only\n"
             "- `swk def ID NAME` prints one function with line numbers\n"
             "- `swk callers ID NAME` lists the functions whose code calls it\n"
             "- `swk select ID PATH FIELD=VALUE OUT` reads a JSON list of records and prints the OUT field of those whose FIELD is VALUE\n"
             "- `swk grep ID 'REGEX' PATH` searches one file or folder\n"
             "- `swk read ID PATH FIRST:LAST` prints some lines of a file\n"),
}
HAND_IN = ("- `swk setline ID PATH N <<'EOF'`, then the new text of line N, then `EOF` on a line of its own\n"
           "- `swk answer ID <<'EOF'`, then the JSON object, then `EOF` on a line of its own\n")


def index(folder: Path) -> dict:
    """Where every function is and who calls it, read from the code itself. Built once per project and shared by every command."""
    functions, calls = {}, {}
    for path in sorted((folder / "inv").glob("m*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = {"module": path.stem, "first": node.lineno, "last": node.end_lineno}
                calls[node.name] = sorted({n.func.id for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)})
    callers = {name: sorted(f"{functions[other]['module']}.{other}" for other, called in calls.items() if name in called) for name in functions}
    return {"functions": functions, "callers": callers}


def large(number: int, seed: int, out: Path, mode: str) -> dict:
    ident = f"L-{number:04d}"
    folder = out / ident
    made = bench.build(folder, seed * 1000 + number)
    text = (f"## Task {ident}\n\nThe Python package `inv` in this project has 8 modules, `inv/m0.py` to `inv/m7.py`, of small functions that "
            "call one another. Exactly one function is wrong: one arithmetic sign in its `return` line was flipped. Its test fails, and so do "
            "the tests of every function that calls it, directly or through others.\n\nDo two things.\n\n"
            f"1. Correct that one line. Change nothing else. `swk test {ident}` must then report no failure.\n"
            "2. Hand in four facts as one JSON object:\n"
            "   - `\"fixed_function\"`: the wrong function as `\"module.name\"`, for example `\"m3.f3_2\"`\n"
            "   - `\"direct_callers\"`: the functions whose own code calls it, as `\"module.name\"` strings, in any order\n"
            "   - `\"failed_event_ids\"`: the `id` of every record in `data/events.json` whose `status` is `\"failed\"`\n"
            "   - `\"build_error_code\"`: the code on the one `ERROR` line of `logs/build.log`, for example `\"E1234\"`\n\n"
            "Then answer DONE.\n\nThese are the only commands that run. Replace ID by the task id.\n\n"
            f"{COMMANDS[mode]}{HAND_IN}")
    (folder / "TASK.md").write_text(text, encoding="utf-8")
    return {"id": ident, "size": "large", "family": "planted-bug", "text": text, "truth": made["truth"], "mode": mode,
            "index": index(folder) if mode == "lean" else None, "fingerprint": hashlib.sha256(text.encode()).hexdigest()}


def make(out: Path, size: str, first: int, count: int, mode: str = "lean", seed: int = SEED, extra: list | None = None) -> list[dict]:
    """Write COUNT tasks of one size. `extra` adds ready-made tasks, which the tests use."""
    for name in (".hidden", ".kit"):
        (out / name).mkdir(parents=True, exist_ok=True)
    made = list(extra or [])
    for number in range(first, first + count):
        made.append(small(number, seed) if size == "small" else medium(number, seed) if size == "medium" else large(number, seed, out, mode))
    for item in made:
        folder = out / item["id"]
        folder.mkdir(exist_ok=True)
        if item["size"] != "large":
            (folder / "TASK.md").write_text(item["text"], encoding="utf-8")
        kit = {"size": item["size"], "mode": item.get("mode"), "examples": item.get("examples"), "attempts": 0, "calls": {}, "chars_out": 0, "views": 0}
        (out / ".kit" / f"{item['id']}.json").write_text(json.dumps(kit, ensure_ascii=False), encoding="utf-8")
        if item.get("index"):
            (out / ".kit" / f"{item['id']}.index.json").write_text(json.dumps(item["index"]), encoding="utf-8")
        hidden = {key: item.get(key) for key in ("id", "size", "family", "suite", "truth", "fingerprint")}
        (out / ".hidden" / f"{item['id']}.json").write_text(json.dumps(hidden, ensure_ascii=False), encoding="utf-8")
    return made


def check_one(out: Path, hidden: dict) -> dict:
    folder = out / hidden["id"]
    kit = json.loads((out / ".kit" / f"{hidden['id']}.json").read_text())
    row = {"id": hidden["id"], "size": hidden["size"], "family": hidden["family"], "attempts": kit["attempts"], "kit_calls": sum(kit["calls"].values()),
           "kit_chars_out": kit["chars_out"], "kit_views": kit["views"], "findings": [], "lines": 0, "passed": 0}
    if hidden["size"] == "large":
        result = bench.check(folder, folder, hidden["truth"])
        diff = subprocess.run(["git", "-C", str(folder), "diff"], capture_output=True, text=True).stdout
        answer = (folder / "ANSWER.json").read_text() if (folder / "ANSWER.json").exists() else ""
        row.update(written=bool(diff or answer), passed=result["score"], total=result["out_of"], findings=result.get("refused_to_run", []),
                   lines=result.get("lines_added", 0) + result.get("lines_removed", 0), sha256=hashlib.sha256((diff + answer).encode()).hexdigest(),
                   extra_files=[], tests_pass=result["tests_pass"], answer_fields=result.get("answer_fields_correct"))
        row["verified"] = result["score"] == result["out_of"] and bool(result.get("only_the_broken_module_changed"))
        return row
    solution = folder / "solution.py"
    row.update(written=solution.exists(), total=len(hidden["suite"]["tests"]),
               extra_files=sorted(p.name for p in folder.iterdir() if p.name not in ("TASK.md", "solution.py", "__pycache__")))
    if row["written"]:
        source = solution.read_text(encoding="utf-8", errors="replace")
        row.update(lines=len(source.splitlines()), sha256=hashlib.sha256(source.encode()).hexdigest(), findings=workload.inspect(source))
        if not row["findings"]:
            result = run_suite(solution, hidden["suite"])
            row["passed"] = result["passed"]
            if result.get("error"):
                row["error"] = result["error"]
    row["verified"] = row["written"] and row["passed"] == row["total"] and not row["findings"]
    return row


def check(out: Path) -> dict:
    rows = [check_one(out, json.loads(path.read_text())) for path in sorted((out / ".hidden").glob("*.json"))]
    written = sum(r["written"] for r in rows)
    return {"tasks": len(rows), "written": written, "verified": sum(r["verified"] for r in rows), "tests_passed": sum(r["passed"] for r in rows),
            "tests_total": sum(r["total"] for r in rows), "security_findings": sum(len(r["findings"]) for r in rows),
            "extra_files": sum(len(r["extra_files"]) for r in rows), "mean_lines": round(sum(r["lines"] for r in rows) / max(1, written), 1),
            "attempts": sum(r["attempts"] for r in rows), "kit_calls": sum(r["kit_calls"] for r in rows),
            "kit_chars_out": sum(r["kit_chars_out"] for r in rows), "kit_views": sum(r["kit_views"] for r in rows), "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    maker = commands.add_parser("make")
    maker.add_argument("out", type=Path)
    maker.add_argument("size", choices=sorted(SIZES.values()))
    maker.add_argument("first", type=int)
    maker.add_argument("count", type=int)
    maker.add_argument("--mode", choices=("lean", "raw"), default="lean")
    maker.add_argument("--seed", type=int, default=SEED)
    checker = commands.add_parser("check")
    checker.add_argument("out", type=Path)
    checker.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.command == "make":
        made = make(args.out, args.size, args.first, args.count, args.mode, args.seed)
        print(f"{len(made)} {args.size} tasks {made[0]['id']}..{made[-1]['id']} in {len({m['family'] for m in made})} families")
        return 0
    result = check(args.out)
    if args.json:
        args.json.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print({key: value for key, value in result.items() if key != "rows"})
    failed = [f"{r['id']}:{r['passed']}/{r['total']}" for r in result["rows"] if not r["verified"]]
    if failed:
        print("not verified:", " ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
