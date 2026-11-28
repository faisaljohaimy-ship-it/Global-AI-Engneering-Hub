"""Second-by-second count of agents that were really running at once.

Reads agent record files (JSONL, one line per event, each with an ISO
`timestamp`). For every record it takes the first and last timestamp and the
timestamp of the first reply (first `assistant` line), then reports how many
agents were active in each second, the peak, the delay to the first reply, the
duration of each agent, and plateaus.

A plateau is a span of at least three seconds in which the active count stayed
at its peak while at least one agent had not yet started. It SUGGESTS a limit
on how many agents the host runs at once; it does not prove one.

Call: python3 timeline.py RECORD.jsonl [RECORD.jsonl ...]   (prints JSON)
From code: build(paths, start=None) -> dict
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

MIN_PLATEAU = 3
NOTE = ("A plateau suggests a limit on agents run at once; it does not prove one. "
        "Times are measured from the record timestamps; seconds are whole-second "
        "buckets counted from the earliest start.")


def _ts(text):
    d = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def _read(path):
    first = last = reply = None
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            row = json.loads(line)
            t = _ts(row["timestamp"])
        except (ValueError, KeyError, TypeError):
            continue
        if not isinstance(row, dict):
            continue
        first = t if first is None else min(first, t)
        last = t if last is None else max(last, t)
        if row.get("type") == "assistant" and (reply is None or t < reply):
            reply = t
    if first is None:
        return None
    return {"start": first, "end": last, "reply": reply}


def _pct(values, q):
    if not values:
        return None
    v = sorted(values)
    rank = max(1, -(-len(v) * q // 100))
    return round(v[int(rank) - 1], 3)


def _spread(values):
    return {"median": _pct(values, 50), "p95": _pct(values, 95),
            "max": round(max(values), 3) if values else None, "n": len(values)}


def build(paths, start=None):
    agents = []
    for p in paths:
        a = _read(p)
        if a:
            agents.append(a)
    out = {"note": NOTE, "agents": [], "active": [], "peak": None,
           "peak_seconds": 0, "first_reply_delay": _spread([]),
           "duration": _spread([]), "plateaus": []}
    if not agents:
        return out
    agents.sort(key=lambda a: (a["start"], a["end"]))
    t0 = min(a["start"] for a in agents)
    base = int(t0 // 1)
    ref = t0 if start is None else float(start)
    last = int(max(a["end"] for a in agents) // 1) - base
    diff = [0] * (last + 2)
    first_bucket = []
    for a in agents:
        s = int(a["start"] // 1) - base
        e = int(a["end"] // 1) - base
        diff[s] += 1
        diff[e + 1] -= 1
        first_bucket.append(s)
    counts, cur = [], 0
    for i in range(last + 1):
        cur += diff[i]
        counts.append(cur)
    runs = []
    for c in counts:
        if runs and runs[-1][1] == c:
            runs[-1][0] += 1
        else:
            runs.append([1, c])
    peak = max(counts)
    latest_start = max(first_bucket)
    plateaus, begin = [], None
    for i in range(last + 2):
        on = i <= last and counts[i] == peak and latest_start > i
        if on and begin is None:
            begin = i
        elif not on and begin is not None:
            if i - begin >= MIN_PLATEAU:
                plateaus.append({"from_second": begin, "seconds": i - begin,
                                 "active": peak})
            begin = None
    delays = [a["reply"] - ref for a in agents if a["reply"] is not None]
    out.update({
        "agents": [{"index": i + 1,
                    "start_offset": round(a["start"] - t0, 3),
                    "end_offset": round(a["end"] - t0, 3),
                    "duration": round(a["end"] - a["start"], 3),
                    "first_reply_delay": None if a["reply"] is None
                    else round(a["reply"] - ref, 3)}
                   for i, a in enumerate(agents)],
        "active": runs,
        "peak": peak,
        "peak_seconds": counts.count(peak),
        "first_reply_delay": _spread(delays),
        "duration": _spread([a["end"] - a["start"] for a in agents]),
        "plateaus": plateaus,
    })
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    print(json.dumps(build([Path(a) for a in argv]), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
