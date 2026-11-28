#!/usr/bin/env python3
"""Pick the few capabilities, the model tier and the effort a task needs, and nothing more.

    python3 swarm/route.py CLASS            routine | investigate | design | security | review
    python3 swarm/route.py --classify "TEXT OF A TASK"

A hundred capabilities are registered. No task gets a hundred: a worker is told only about
the ones whose task classes match its work and that have actually run here.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# class: model tier, effort, and the capabilities a worker of that class is told about
CLASSES = {
    "routine": {"model": "light", "effort": "low", "capabilities": ["C052", "C060"]},
    "investigate": {"model": "middle", "effort": "medium",
                    "capabilities": ["C057", "C060", "C005", "C006", "C021", "C028", "C029", "C025", "C027", "C056"]},
    "review": {"model": "middle", "effort": "medium", "capabilities": ["C060", "C034", "C028", "C027", "C025", "C006"]},
    "design": {"model": "top", "effort": "high", "capabilities": ["C093", "C034", "C028", "C038"]},
    "security": {"model": "top", "effort": "high", "capabilities": ["C087", "C089", "C045", "C027", "C025"]},
}
SIGNS = [("security", r"\b(secret|credential|injection|permission|vulnerab|threat|isolation)"),
         ("design", r"\b(architecture|design|boundar|interface between|trade-?off)"),
         ("review", r"\b(review|audit|findings)"),
         ("investigate", r"\b(failing|fails|bug|root cause|why|trace|log|who calls|references)"),
         ("routine", r"\b(implement|write the function|rename|format|convert|generate)")]


def classify(text: str) -> str:
    lowered = text.lower()
    for name, pattern in SIGNS:
        if re.search(pattern, lowered):
            return name
    return "investigate"


def select(name: str) -> dict:
    rule = CLASSES[name]
    registry = {row["id"]: row for row in json.loads((HERE / "capabilities.json").read_text(encoding="utf-8"))["capabilities"]}
    chosen = [registry[cid] for cid in rule["capabilities"] if registry[cid]["status"] in ("USED", "TESTED") and registry[cid]["invoke"]]
    return {"class": name, "model_tier": rule["model"], "effort": rule["effort"],
            "capabilities": [{"id": row["id"], "name": row["name"], "invoke": row["invoke"]} for row in chosen],
            "registered": len(registry), "selected": len(chosen)}


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--classify":
        print(json.dumps(select(classify(sys.argv[2])), indent=1))
        return 0
    if len(sys.argv) != 2 or sys.argv[1] not in CLASSES:
        print(__doc__.split("\n\n")[1])
        return 2
    print(json.dumps(select(sys.argv[1]), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
