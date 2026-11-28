"""Report on prompt-cache sharing between workers.

Reads agent records (JSONL files) and reports, per whole set of agents, how
much of each agent's first request was written to the cache, read from it, or
not cached, and how much a warm shared prefix might have saved.

Call from Python:   report(paths, weights) -> dict
Call from a shell:  python3 cache_report.py [--weights JSON] RECORD [RECORD ...]
where JSON is like '{"cache_write_5m": 1.25, "cache_read": 0.1}' (cost units
per token; an assumption supplied by the caller, never filled in here). The
result is printed as JSON.

Rules: only lines of type "assistant" with a usage block count. A reply that
appears on several lines with the same message.id is counted once (the last
line wins). The first reply of a record is the first distinct reply in file
order. A record with no reply is not an agent; it is counted in
empty_records. Tokens are measured from the records.

warm_prefix_estimate is an ESTIMATE, not a measurement. It assumes that all
agents share one common prefix, so that a single warm copy, written once by
the largest first-request writer, could have been read by every other agent
instead of each writing its own. Tokens: sum of first-request cache writes
minus the largest single one. Cost units: those tokens times
(cache_write_5m - cache_read) weight; None when a weight is missing. It
ignores cache lifetime (5 minutes), ordering, and prefixes that differ.
"""
import json
import sys
from pathlib import Path

_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _usage(raw):
    """Normalise a usage dict to uncached, written, read, output."""
    written = raw.get("cache_creation_input_tokens")
    if written is None:
        split = raw.get("cache_creation")
        written = (_num(split.get("ephemeral_5m_input_tokens"))
                   + _num(split.get("ephemeral_1h_input_tokens"))) if isinstance(split, dict) else 0
    return {"uncached": _num(raw.get("input_tokens")), "written": _num(written),
            "read": _num(raw.get("cache_read_input_tokens"))}


def replies(path):
    """Distinct replies of one record, in order of first appearance."""
    order, seen = [], {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for n, line in enumerate(text.splitlines()):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("type") != "assistant":
            continue
        msg = row.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
            continue
        key = msg.get("id") or ("line", n)
        if key not in seen:
            order.append(key)
        seen[key] = _usage(msg["usage"])
    return [seen[k] for k in order]


def report(paths, weights):
    weights = weights or {}
    firsts, empty = [], 0
    all_written = all_read = 0
    for path in paths:
        rs = replies(path)
        if not rs:
            empty += 1
            continue
        firsts.append(rs[0])
        all_written += sum(r["written"] for r in rs)
        all_read += sum(r["read"] for r in rs)
    uncached = sum(f["uncached"] for f in firsts)
    written = sum(f["written"] for f in firsts)
    read = sum(f["read"] for f in firsts)
    warm = 0
    counted = 0
    for f in firsts:
        total = f["uncached"] + f["written"] + f["read"]
        if total > 0:
            counted += 1
            if f["read"] * 2 >= total:
                warm += 1
    saved = written - max((f["written"] for f in firsts), default=0)
    w, r = weights.get("cache_write_5m"), weights.get("cache_read")
    cost = saved * (w - r) if isinstance(w, (int, float)) and isinstance(r, (int, float)) else None
    return {
        "agents": len(firsts),
        "empty_records": empty,
        "first_request": {"uncached_tokens": uncached, "cache_written_tokens": written,
                          "cache_read_tokens": read},
        "share_first_request_half_cached": (warm / counted) if counted else None,
        "whole_records": {"cache_written_tokens": all_written, "cache_read_tokens": all_read},
        "warm_prefix_estimate": {
            "kind": "estimate: assumes all agents share one common prefix",
            "tokens": saved if firsts else None,
            "cost_units": cost if firsts else None,
            "weights_used": {"cache_write_5m": w, "cache_read": r},
        },
    }


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    weights = {}
    if args[:1] == ["--weights"] and len(args) >= 2:
        weights = json.loads(args[1])
        args = args[2:]
    print(json.dumps(report([Path(a) for a in args], weights), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
