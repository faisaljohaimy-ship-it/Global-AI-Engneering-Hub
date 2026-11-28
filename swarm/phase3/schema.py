"""Check an evidence document written by the second phase's stage.py.

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
        if abs(stage["verified_success_rate"] - share) > 0.01:
            out.append(f"{where}: verified_success_rate is not the share of verified tasks")
    return out


def validate(document: dict) -> list[str]:
    if not isinstance(document, dict):
        return ["document is not an object"]
    out = _keys("document", document, TOP)
    if isinstance(document.get("stages"), list):
        for i, stage in enumerate(document["stages"]):
            out += _stage(i, stage)
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
