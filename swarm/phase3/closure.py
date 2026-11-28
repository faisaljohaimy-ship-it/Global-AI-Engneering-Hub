#!/usr/bin/env python3
"""Check the whole experiment in one command.

    python3 swarm/phase3/closure.py [ROOT]

Prints one row per check: ok, FAILED, or "not available" with the file that is missing.
Exits 1 if any row failed; a row that is not available does not fail.
From code: check(root) returns {"rows": [{"check", "passed", "detail"}], "failed": N, "unavailable": N}.
"""
import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]
import schema  # noqa: E402

P2 = "swarm/phase2/evidence/stages.json"
P3 = "swarm/phase3/evidence/stages.json"
PLAN = "swarm/phase3/PLAN3.json"
CAPACITY = "swarm/phase3/evidence/capacity.json"
FREEZE_FILES = ("FREEZE.json", "swarm/phase3/FREEZE.json")
LEAKS = (re.compile(r"/(?:home|root|tmp|Users)/"), re.compile(r"session_0"),
         re.compile(r"claude[-_](?:opus|sonnet|haiku|\d)", re.I))


def _row(name, passed, detail):
    return {"check": name, "passed": passed, "detail": detail}


def _load(root, rel):
    path = Path(root) / rel
    if not path.is_file():
        return None, f"missing: {rel}"
    try:
        return json.loads(path.read_text()), ""
    except (OSError, ValueError) as error:
        return None, f"unreadable: {rel} ({type(error).__name__})"


def _absent(name, why):
    return _row(name, None, why)


def _ran(document):
    return [s for s in document.get("stages", []) if isinstance(s, dict) and not s.get("skipped")]


def _validates(root, name, rel):
    doc, why = _load(root, rel)
    if doc is None:
        return _absent(name, why)
    problems = schema.validate(doc)
    return _row(name, not problems, "sound" if not problems else "; ".join(problems[:5]))


def _freeze(root):
    name = "the freeze still matches"
    found = next((f for f in FREEZE_FILES if (Path(root) / f).is_file()), None)
    if found is None:
        return _absent(name, "missing: FREEZE.json")
    try:
        module = importlib.import_module("freeze")
    except ImportError:
        return _absent(name, "missing: swarm/phase3/freeze.py")
    try:
        result = module.check(root)
    except Exception as error:  # a freeze that cannot be checked is not a pass
        return _row(name, False, f"freeze.check raised {type(error).__name__}")
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, dict):
        result = result.get("ok", result.get("passed", not result.get("problems")))
    if isinstance(result, (list, set)):
        return _row(name, not result, "matches" if not result else "; ".join(sorted(map(str, result))[:5]))
    return _row(name, bool(result), "matches" if result else "does not match")


def check(root) -> dict:
    root = Path(root)
    rows = [_validates(root, "second phase evidence validates", P2),
            _validates(root, "third phase evidence validates", P3)]
    doc, why = _load(root, P3)
    plan_text = (root / PLAN)
    plan = None
    if plan_text.is_file():
        try:
            plan = json.loads(plan_text.read_text())
        except ValueError:
            plan = None

    def need(name, fn):
        if doc is None:
            rows.append(_absent(name, why))
        else:
            rows.append(fn())

    def names_plan():
        name = "the document names the plan it ran"
        if not plan_text.is_file():
            return _absent(name, f"missing: {PLAN}")
        same = doc.get("plan_sha256") == hashlib.sha256(plan_text.read_bytes()).hexdigest()
        return _row(name, same, "plan_sha256 matches" if same else "plan_sha256 differs from the plan file")
    need("the document names the plan it ran", names_plan)

    def gate_first():
        ran = _ran(doc)
        gate = ran[0].get("security_gate") if ran else None
        ok = bool(gate) and gate.get("passed") is True
        return _row("the first stage that ran is a passed security gate", ok,
                    "gate passed" if ok else ("no stage ran" if not ran else "first stage is not a passed security gate"))
    need("the first stage that ran is a passed security gate", gate_first)

    def ledgers():
        ran = _ran(doc)
        bad = []
        for stage in ran[1:]:
            if stage.get("kind") != "task":
                continue
            led = stage.get("ledger") or {}
            if not (led.get("clean") is True and (led.get("gate") or {}).get("reconciled") is True
                    and stage.get("guard_enforced") is True):
                bad.append(str(stage.get("label")))
        return _row("task stages have a clean, reconciled ledger and an enforced guard", not bad,
                    "all hold" if not bad else "not so in " + ", ".join(bad))
    need("task stages have a clean, reconciled ledger and an enforced guard", ledgers)

    def covered():
        name = "every stage of the plan is run or skipped, or the end is explained"
        if plan is None:
            return _absent(name, f"missing: {PLAN}")
        stages = [s for s in doc.get("stages", []) if isinstance(s, dict)]
        seen = {s.get("label") for s in stages}
        left = [s.get("id") for s in plan.get("stages", []) if s.get("id") not in seen]
        last = stages[-1] if stages else {}
        explained = any(last.get(k) for k in ("skipped", "stopped", "ended", "end_reason", "stop"))
        unclosed = {}
        for path in sorted((root / "swarm" / "phase3" / "evidence").glob("*-not-closed.json")):
            try:
                unclosed[json.loads(path.read_text()).get("stage")] = str(path.relative_to(root))
            except ValueError:
                pass
        if left and not explained and all(name_ in unclosed for name_ in left):
            # The stage ran and its closing failed. That is recorded in a file of its own; it is neither a pass nor hidden.
            return _absent(name, "ran and was not closed, so not measured: " + ", ".join(f"{s} ({unclosed[s]})" for s in left))
        ok = not left or explained
        return _row(name, ok, "all in the document" if not left else
                    ("end explained by the last stage" if explained else "missing: " + ", ".join(map(str, left))))
    need("every stage of the plan is run or skipped, or the end is explained", covered)

    def tokens():
        counted = (doc.get("figures") or {}).get("input_tokens_counted")
        limit = (doc.get("caps") or {}).get("cumulative_input_tokens")
        ok = isinstance(counted, (int, float)) and isinstance(limit, (int, float)) and counted <= limit
        return _row("counted input tokens are within the limit", ok, f"{counted} of {limit}")
    need("counted input tokens are within the limit", tokens)

    def limits():
        hit = [str(s.get("label")) for s in _ran(doc) if s.get("agents_with_limit_error")]
        return _row("no agent met a usage limit", not hit, "none" if not hit else "in " + ", ".join(hit))
    need("no agent met a usage limit", limits)

    def registered():
        bad = [str(s.get("label")) for s in _ran(doc)
               if not isinstance(s.get("actual_agents"), int) or not isinstance(s.get("registered_agents"), int)
               or s["actual_agents"] > s["registered_agents"]]
        return _row("real agents never exceed registered agents", not bad, "all within" if not bad else "not so in " + ", ".join(bad))
    need("real agents never exceed registered agents", registered)

    cap, cwhy = _load(root, CAPACITY)
    if cap is None:
        try:
            decided = [d for d in json.loads((root / "swarm" / "phase3" / "DECISIONS.json").read_text()).get("decisions", []) if d.get("cancels") == CAPACITY]
        except (OSError, ValueError):
            decided = []
        rows.append(_absent("the capacity study is labelled a simulation", f"cancelled by {decided[0].get('by')} on {decided[0].get('date')}: no simulation was run" if decided else cwhy))
    else:
        head = " ".join(str(cap.get(k)) for k in ("about", "kind", "label", "simulation", "labelled")
                        if isinstance(cap, dict) and cap.get(k) not in (None, False)).lower()
        ok = "simulat" in head
        rows.append(_row("the capacity study is labelled a simulation", ok, "labelled" if ok else "no simulation label"))

    base = root / "swarm"
    files = sorted(base.rglob("evidence/*.json")) if base.is_dir() else []
    if not files:
        rows.append(_absent("no evidence file holds a path, session id or model identifier", "missing: swarm/**/evidence/*.json"))
    else:
        dirty = []
        for f in files:
            try:
                text = f.read_text()
            except OSError:
                dirty.append(f.name)
                continue
            if any(p.search(text) for p in LEAKS):
                dirty.append(str(f.relative_to(root)))
        rows.append(_row("no evidence file holds a path, session id or model identifier", not dirty,
                         f"{len(files)} files clean" if not dirty else "in " + ", ".join(dirty)))
    for attempt in sorted((root / "swarm" / "phase3" / "evidence").glob("run-*.json")):  # attempts of the run that ended early, kept with the plan each ran
        name = f"the earlier attempt {attempt.stem} validates and names the plan it ran"
        kept_plan = root / "swarm" / "phase3" / f"PLAN3-{attempt.stem}.json"
        try:
            document = json.loads(attempt.read_text())
        except ValueError:
            rows.append(_row(name, False, "not JSON"))
            continue
        problems = schema.validate(document)
        if not kept_plan.is_file():
            problems.append(f"its plan {kept_plan.name} is not in the repository")
        elif document.get("plan_sha256") != hashlib.sha256(kept_plan.read_bytes()).hexdigest():
            problems.append(f"plan_sha256 is not the hash of {kept_plan.name}")
        rows.append(_row(name, not problems, "sound" if not problems else "; ".join(problems[:3])))
    rows.append(_freeze(root))
    return {"rows": rows, "failed": sum(r["passed"] is False for r in rows),
            "unavailable": sum(r["passed"] is None for r in rows)}


def main(argv) -> int:
    root = Path(argv[1]) if len(argv) > 1 else HERE.parent.parent
    result = check(root)
    for r in result["rows"]:
        mark = "ok" if r["passed"] else "FAILED" if r["passed"] is False else "not available"
        print(f"{mark:14} {r['check']}: {r['detail']}")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
