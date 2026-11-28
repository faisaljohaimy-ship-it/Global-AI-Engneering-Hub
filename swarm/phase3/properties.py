"""Properties the medium reference solutions of swarm/phase2/tasks.py must keep.

The references (ledger, expression, rooms, graph) judge every worker. This module
checks them against rules that do not come from the references themselves: totals,
no-change-on-error, ordering, tiling of the open hours, inverse relations and
Python's own eval.  Constants (limit, fee, hours, most, operator) are read from each
task's text.

Call from a script or test:  properties.check_variant(number, seed) -> list of
violations (empty when every property holds).  Run  python3 properties.py [COUNT]
to check COUNT variants of each family and print the violations found.
"""
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]

import tasks  # noqa: E402

FAMILIES = ("ledger", "expr", "rooms", "graph")


def number_of(family: str, index: int) -> int:
    """Task number of the index-th (from 0) variant of a family."""
    return 4 * index + FAMILIES.index(family) + 1


def load(reference: str, entry):
    space: dict = {}
    exec(compile(reference, "<reference>", "exec"), space)  # noqa: S102 - the repository's own reference text
    return space[entry] if entry else space


def call(target, name, *args):
    """Return ("ok", value) or ("error", None) when the call raises ValueError."""
    try:
        return "ok", getattr(target, name)(*args)
    except ValueError:
        return "error", None


# ---- ledger ---------------------------------------------------------------------------------

def ledger_constants(text: str):
    fee = int(re.search(r"a fee of (\d+)", text).group(1))
    floor = re.search(r"may not fall below (-?\d+)", text).group(1)
    return fee, int(floor)


def ledger_snapshot(ledger, names):
    state = {}
    for name in names:
        kind, bal = call(ledger, "balance", name)
        state[name] = (bal, call(ledger, "history", name)[1]) if kind == "ok" else None
    state["#richest"] = ledger.richest(len(names))
    return state


def check_ledger(text: str, reference: str, rng: random.Random, calls: int = 80) -> list:
    fee, floor = ledger_constants(text)
    ledger = load(reference, "Ledger")()
    names = ["ada", "bob", "cy", "dee", "eve"]
    bad, deposits, withdrawals, fees = [], 0, 0, 0
    for _ in range(calls):
        who, other = rng.sample(names, 2)
        amount = rng.choice([-5, 0, 1, 10, 25, 60, 140, 300])
        verb = rng.choice(["deposit", "withdraw", "transfer", "transfer", "richest"])
        before = ledger_snapshot(ledger, names)
        if verb == "deposit":
            kind, _ = call(ledger, "deposit", who, amount)
            deposits += amount if kind == "ok" else 0
            args = (who, amount)
        elif verb == "withdraw":
            kind, _ = call(ledger, "withdraw", who, amount)
            withdrawals += amount if kind == "ok" else 0
            args = (who, amount)
        elif verb == "transfer":
            kind, _ = call(ledger, "transfer", who, other, amount)
            fees += fee if kind == "ok" else 0
            args = (who, other, amount)
        else:
            count = rng.randint(0, 6)
            got = ledger.richest(count)
            state = {n: ledger.balance(n) for n in names if call(ledger, "balance", n)[0] == "ok"}
            want = sorted(state, key=lambda n: (-state[n], n))[:count]
            if got != want:
                bad.append(f"richest({count}) gave {got}, expected {want}")
            continue
        after = ledger_snapshot(ledger, names)
        if kind == "error" and after != before:
            bad.append(f"{verb}{args} raised ValueError but changed the ledger")
        balances = [v[0] for k, v in after.items() if k != "#richest" and v]
        if sum(balances) != deposits - withdrawals - fees:
            bad.append(f"after {verb}{args}: sum {sum(balances)} != deposits {deposits} - withdrawals {withdrawals} - fees {fees}")
            break
        if any(b < floor for b in balances):
            bad.append(f"after {verb}{args}: a balance fell below {floor}")
    return bad


# ---- rooms ----------------------------------------------------------------------------------

def rooms_constants(text: str):
    opens, closes = map(int, re.search(r"open from (\d+) to (\d+)", text).groups())
    most = int(re.search(r"fewer than (\d+) current bookings", text).group(1))
    return opens, closes, most


def check_rooms(text: str, reference: str, rng: random.Random, calls: int = 80) -> list:
    opens, closes, most = rooms_constants(text)
    rooms = load(reference, "Rooms")()
    people = ["kim", "lee", "max"]
    bad, issued = [], 0
    for _ in range(calls):
        before = rooms.agenda()
        verb = rng.choice(["book", "book", "book", "cancel", "free"])
        if verb == "book":
            start = opens + 15 * rng.randint(-1, (closes - opens) // 15 + 1)
            args = (start, start + 15 * rng.randint(0, 6), rng.choice(people))
            kind, number = call(rooms, "book", *args)
            if kind == "ok":
                issued += 1
                if number != issued:
                    bad.append(f"book{args} returned {number}, expected {issued}")
                    issued = number
            elif rooms.agenda() != before:
                bad.append(f"book{args} raised ValueError but changed the agenda")
        elif verb == "cancel":
            kind, _ = call(rooms, "cancel", rng.randint(1, issued + 1))
            if kind == "error" and rooms.agenda() != before:
                bad.append("a failed cancel changed the agenda")
        agenda = rooms.agenda()
        for (s, e, _), (s2, e2, _) in zip(agenda, agenda[1:]):
            if s2 < e:
                bad.append(f"bookings overlap: {[s, e]} and {[s2, e2]}")
        if any(not opens <= s < e <= closes for s, e, _ in agenda):
            bad.append("a booking lies outside the opening hours")
        if any(sum(1 for _, _, w in agenda if w == p) > most for p in people):
            bad.append(f"somebody holds more than {most} bookings")
        pieces = sorted([[s, e] for s, e, _ in agenda] + rooms.free(1))
        at = opens
        for s, e in pieces:
            if s != at or e <= s:
                bad.append(f"free(1) and agenda do not tile {opens}-{closes} once: {pieces}")
                break
            at = e
        else:
            if at != closes:
                bad.append(f"free(1) and agenda stop at {at}, not {closes}")
        if bad:
            break
    return bad


# ---- graph ----------------------------------------------------------------------------------

def check_graph(text: str, reference: str, rng: random.Random, calls: int = 60) -> list:
    graph = load(reference, "Graph")()
    pool = ["api", "cli", "core", "db", "log", "net"]
    direct: dict = {}
    bad = []
    for _ in range(calls):
        name = rng.choice(pool)
        verb = rng.choice(["add", "add", "add", "remove", "order"])
        if verb == "add":
            needs = rng.sample(pool, rng.randint(0, 2))
            kind, _ = call(graph, "add", name, needs)
            if kind == "ok":
                for other in needs:
                    direct.setdefault(other, set())
                direct[name] = set(needs)
        elif verb == "remove":
            kind, _ = call(graph, "remove", name)
            if kind == "ok":
                direct.pop(name, None)
        kind, got = call(graph, "order")
        if kind == "ok":
            if sorted(got) != sorted(direct) or len(set(got)) != len(got):
                bad.append(f"order() {got} is not every known package once ({sorted(direct)})")
            place = {n: i for i, n in enumerate(got)}
            for n, needs in direct.items():
                if any(place.get(x, -1) >= place.get(n, -1) for x in needs):
                    bad.append(f"order() {got} puts {n} before something it needs")
        req = {n: graph.requires(n) for n in direct}
        dep = {n: graph.dependents(n) for n in direct}
        for a in direct:
            for b in direct:
                if a != b and (b in req[a]) != (a in dep[b]):
                    bad.append(f"requires({a}) and dependents({b}) are not inverse")
        if bad:
            break
    return bad


# ---- expression -----------------------------------------------------------------------------

def expr_operator(text: str) -> str:
    return re.search(r"each of `\+ - \* (.) \( \)`", text).group(1)


def expression(rng, depth, names, op):
    if depth == 0 or rng.random() < 0.3:
        return rng.choice([str(rng.randint(0, 20)), rng.choice(names)])
    kind = rng.random()
    if kind < 0.15:
        return "-" + expression(rng, depth - 1, names, op)
    if kind < 0.4:
        return "(" + expression(rng, depth - 1, names, op) + ")"
    sign = rng.choice([" + ", " - ", "*", " * ", op, " " + op + " "])
    return expression(rng, depth - 1, names, op) + sign + expression(rng, depth - 1, names, op)


def check_expr(text: str, reference: str, rng: random.Random, calls: int = 150) -> list:
    op = expr_operator(text)
    space = load(reference, None)
    names = ["x", "y", "ab"]
    bad = []
    for _ in range(calls):
        env = {n: rng.randint(-9, 12) for n in names}
        source = expression(rng, rng.randint(1, 4), names, op)
        python = source.replace("/", "//")
        try:
            want = ("ok", eval(python, {"__builtins__": {}}, dict(env)))  # noqa: S307 - generated arithmetic only
        except ZeroDivisionError:
            want = ("error", None)
        got = call(types_ns(space), "evaluate", source, env)
        if got != want:
            bad.append(f"evaluate({source!r}) gave {got}, Python gives {want}")
        if "".join(space["tokenize"](source)) != source.replace(" ", ""):
            bad.append(f"tokenize({source!r}) joined back differs from the text")
        if len(bad) > 3:
            break
    return bad


def types_ns(space):
    import types
    return types.SimpleNamespace(**space)


CHECKS = {"ledger": check_ledger, "expr": check_expr, "rooms": check_rooms, "graph": check_graph}


def check_variant(number: int, seed: int = tasks.SEED, scripts: int = 6) -> list:
    """Check one medium task with `scripts` random scripts; return the violations."""
    item = tasks.medium(number, seed)
    check = CHECKS[item["family"]]
    bad = []
    for n in range(scripts):
        bad += check(item["text"], item["reference"], random.Random(f"{seed}:{number}:{n}"))
    return bad


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    found = 0
    for family in FAMILIES:
        for index in range(count):
            for line in check_variant(number_of(family, index)):
                found += 1
                print(f"{family} #{index}: {line}")
    print(f"{found} violation(s)")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
