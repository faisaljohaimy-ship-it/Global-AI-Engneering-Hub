"""Check an evidence document written by the second phase's stage.py or the third phase's stage3.py.

A document is of the third phase when it has the top-level key counted_before_this_run;
then the ledger, the security gate, the queue and the limit are checked as well.
Call: python3 swarm/phase3/schema.py FILE
Prints each problem found, one per line, and exits 1 if there are any.
From code: validate(document) returns the list of problems (empty when sound).
"""
import json
import re
import sys

TOP = {"about": str, "plan_sha256": str, "caps": dict, "figures": dict, "stages": list}
TOKENS = ("input_uncached", "cache_write", "cache_read", "input_total", "output", "total")
COMMON = {"label": str, "kind": str, "actual_agents": int, "agents_with_limit_error": int, "agent_tokens": dict,
          "wall_seconds": (int, float), "model": str, "cost_units": (int, float), "swk_calls": int,
          "refused_calls": int, "foreign_calls": int}
PROBE = {"guard_enforced": bool, "allowed_command_ran": bool}
TASK = {"tasks": int, "verified_tasks": int, "verified_success_rate": (int, float),
        "security_findings": int, "peak_concurrent_agents": int}
BAD_TEXT = ("/home/", "/root/", "/tmp/", "/Users/", "session_0")
MODEL_ID = re.compile(r"claude[-_]|\d")


def _is(value, kind) -> bool:
    kinds = kind if isinstance(kind, tuple) else (kind,)
    if isinstance(value, bool) and bool not in kinds:
        return False
    return isinstance(value, kinds)


def _keys(where: str, stage: dict, wanted: dict) -> list[str]:
    out = []
    for key, kind in wanted.items():
        if key not in stage:
            out.append(f"{where}: missing key {key}")
        elif not _is(stage[key], kind):
            out.append(f"{where}: {key} has the wrong type")
    return out


def _strings(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key, f"{path}/<key>")
            yield from _strings(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _strings(value, f"{path}[{i}]")


def _stage(i: int, stage) -> list[str]:
    where = f"stage {i}"
    if not isinstance(stage, dict):
        return [f"{where}: not an object"]
    if isinstance(stage.get("label"), str):
        where = f"stage {stage['label']}"
    if "skipped" in stage:
        extra = sorted(set(stage) - {"label", "skipped"})
        out = _keys(where, stage, {"label": str})
        return out + ([f"{where}: a skipped stage has other keys: {', '.join(extra)}"] if extra else [])
    out = _keys(where, stage, COMMON)
    kind = stage.get("kind")
    if kind not in ("probe", "task"):
        return out + [f"{where}: kind must be probe or task"]
    out += _keys(where, stage, PROBE if kind == "probe" else TASK)
    tokens = stage.get("agent_tokens")
    if isinstance(tokens, dict):
        out += _keys(f"{where} agent_tokens", tokens, {k: int for k in TOKENS})
        if all(_is(tokens.get(k), int) for k in TOKENS):
            if tokens["input_total"] != tokens["input_uncached"] + tokens["cache_write"] + tokens["cache_read"]:
                out.append(f"{where}: input_total is not input_uncached + cache_write + cache_read")
            if tokens["total"] != tokens["input_total"] + tokens["output"]:
                out.append(f"{where}: total is not input_total + output")
    if kind == "task" and all(_is(stage.get(k), t) for k, t in TASK.items()):
        if stage["verified_tasks"] > stage["tasks"]:
            out.append(f"{where}: verified_tasks exceeds tasks")
        if _is(stage.get("actual_agents"), int) and stage["peak_concurrent_agents"] > stage["actual_agents"]:
            out.append(f"{where}: peak_concurrent_agents exceeds actual_agents")
        share = round(100 * stage["verified_tasks"] / stage["tasks"], 2) if stage["tasks"] else 0.0
        if abs(stage["verified_success_rate"] - share) > 0.051:  # the rate is written to one decimal place: 1 of 3 is 33.3
            out.append(f"{where}: verified_success_rate is not the share of verified tasks")
    return out


def _name(i: int, stage: dict) -> str:
    return f"stage {stage['label']}" if isinstance(stage.get("label"), str) else f"stage {i}"


def _num(value) -> bool:
    return _is(value, (int, float))


def _third(i: int, stage: dict) -> list[str]:
    """What the gated run adds to a stage: ledger, security gate, queue, guard_enforced."""
    where, out = _name(i, stage), []
    book, gate, queue = stage.get("ledger"), stage.get("security_gate"), stage.get("queue")
    ledger_ok = isinstance(book, dict)
    if ledger_ok:
        classes = book.get("by_class")
        if isinstance(classes, dict) and all(_is(v, int) for v in classes.values()) and _is(book.get("tool_calls"), int):
            if sum(classes.values()) != book.get("tool_calls"):
                out.append(f"{where}: ledger classes do not sum to tool_calls")
        elif "by_class" in book or "tool_calls" in book:
            out.append(f"{where}: ledger by_class or tool_calls has the wrong type")
        outside = book.get("calls_outside_the_contract_that_ran")
        if isinstance(outside, dict) and outside and book.get("clean") is not False:
            out.append(f"{where}: ledger is clean although calls outside the contract ran")
    if isinstance(gate, dict):
        probes = gate.get("probes") if isinstance(gate.get("probes"), list) else []
        rows = [p for p in probes if isinstance(p, dict)]
        if gate.get("passed") is True and not all(p.get("held") is True for p in rows):
            out.append(f"{where}: security gate passed although a probe did not hold")
        for p in rows:
            if p.get("must_be") == "refused" and _num(p.get("calls_outside_the_contract_that_ran")) and p["calls_outside_the_contract_that_ran"] > 0:
                out.append(f"{where}: a probe that must be refused ran a call outside the contract")
    if stage.get("guard_enforced") is True and ledger_ok:
        gate_book = book.get("gate")
        if book.get("clean") is not True or not (isinstance(gate_book, dict) and gate_book.get("reconciled") is True):
            out.append(f"{where}: guard_enforced although the ledger is not clean or not reconciled")
    if isinstance(queue, dict):
        keys = ("handed_in", "given_up", "left_waiting", "claimed_and_not_handed_in", "tasks")
        if all(_is(queue.get(k), int) for k in keys):
            if sum(queue[k] for k in keys[:4]) != queue["tasks"]:
                out.append(f"{where}: queue handed_in + given_up + left_waiting + claimed_and_not_handed_in is not tasks")
        else:
            out.append(f"{where}: queue is missing a count or it has the wrong type")
        if _num(queue.get("agent_calls_per_message")) and queue["agent_calls_per_message"] > 20:
            out.append(f"{where}: agent_calls_per_message exceeds 20")
    return out


def _third_document(document: dict) -> list[str]:
    out = []
    carried = document["counted_before_this_run"]
    if not isinstance(carried, dict) or not _is(carried.get("total"), int) or not isinstance(carried.get("parts"), dict) \
            or not all(_is(v, int) for v in carried["parts"].values()):
        out.append("document: counted_before_this_run needs an integer total and integer parts")
    elif carried["total"] != sum(carried["parts"].values()):
        out.append("document: counted_before_this_run total is not the sum of its parts")
    caps, figures = document.get("caps"), document.get("figures")
    if isinstance(caps, dict) and isinstance(figures, dict):
        limit, counted = caps.get("cumulative_input_tokens"), figures.get("input_tokens_counted")
        if _num(limit) and _num(counted) and counted > limit:
            out.append("document: the cumulative figure passes the limit in caps")
    stages = document.get("stages")
    if isinstance(stages, list):
        passed = False
        for i, stage in enumerate(stages):
            if not isinstance(stage, dict) or "skipped" in stage:
                continue
            if stage.get("kind") == "task" and not passed:
                out.append(f"{_name(i, stage)}: a task stage comes before a security gate that passed")
            out += _third(i, stage)
            if isinstance(stage.get("security_gate"), dict) and stage["security_gate"].get("passed") is True:
                passed = True
    return out


def validate(document: dict) -> list[str]:
    if not isinstance(document, dict):
        return ["document is not an object"]
    out = _keys("document", document, TOP)
    if isinstance(document.get("stages"), list):
        for i, stage in enumerate(document["stages"]):
            out += _stage(i, stage)
    if "counted_before_this_run" in document:
        out += _third_document(document)
    for path, text in _strings(document):
        for bad in BAD_TEXT:
            if bad in text:
                out.append(f"{path}: holds {bad!r}")
        if re.search(r"/models?(\[\d+\])?$", path) and MODEL_ID.search(text):
            out.append(f"{path}: model identifier longer than a family name")
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip())
        return 2
    with open(sys.argv[1]) as handle:
        problems = validate(json.load(handle))
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
