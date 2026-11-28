"""Resume a stage driver from the repository's evidence.

The driver keeps its working results in a private folder that does not travel with the
repository. This script finds where a run stopped from a public evidence document, and
can rebuild the missing results file from it.

Call:  python3 swarm/phase3/resume.py EVIDENCE PLAN [RESULTS]
  Prints which stages are done, which were skipped and which is next. With RESULTS, it
  also writes that file from the evidence when it does not exist (never overwrites it).

Evidence measured under another plan is refused (ValueError): its plan_sha256 must be the
SHA-256 of the plan file's bytes. Functions given only a plan dict cannot see those bytes,
so they take them as plan_bytes; without them the dict is checked against its common
JSON serialisations (indent 1, 2 or compact, with or without a final newline).
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PLAN = HERE.parent / "phase2" / "PLAN.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _candidates(plan: dict):
    for kw in ({"indent": 1}, {"indent": 2}, {"separators": (",", ":")}, {}):
        for utf in (False, True):
            text = json.dumps(plan, ensure_ascii=utf, **kw)
            yield text.encode()
            yield (text + "\n").encode()


def _refuse_unless_same_plan(evidence: dict, plan: dict | None, plan_bytes: bytes | None) -> None:
    claimed = evidence.get("plan_sha256")
    if not isinstance(claimed, str) or not claimed:
        raise ValueError("evidence has no plan_sha256: cannot tell which plan it was measured under")
    if plan_bytes is not None:
        ok = _sha(plan_bytes) == claimed
    else:
        ok = any(_sha(c) == claimed for c in _candidates(plan or {}))
    if not ok:
        raise ValueError("evidence was measured under another plan (plan_sha256 differs)")


def position(evidence: dict, plan: dict, plan_bytes: bytes | None = None) -> dict:
    """Where the run stands: {"done": [...], "skipped": [...], "next": id or None}, in plan order."""
    _refuse_unless_same_plan(evidence, plan, plan_bytes)
    done_ids, skipped_ids = set(), set()
    for row in evidence.get("stages", []):
        label = row.get("label")
        (skipped_ids if row.get("skipped") else done_ids).add(label)
    done, skipped, nxt = [], [], None
    for spec in plan.get("stages", []):
        sid = spec.get("id")
        if sid in skipped_ids:
            skipped.append(sid)
        elif sid in done_ids:
            done.append(sid)
        elif nxt is None:
            nxt = sid
    return {"done": done, "skipped": skipped, "next": nxt}


def rebuild(evidence_file, results_file, plan_file=DEFAULT_PLAN) -> bool:
    """Write {"stages": [...]} to results_file from the evidence if it is missing; True if written."""
    evidence_file, results_file = Path(evidence_file), Path(results_file)
    evidence = json.loads(evidence_file.read_text())
    _refuse_unless_same_plan(evidence, None, Path(plan_file).read_bytes())
    if results_file.exists():
        return False
    results_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(results_file, "x") as fh:  # exclusive: never overwrites
            fh.write(json.dumps({"stages": evidence.get("stages", [])}, indent=1) + "\n")
    except FileExistsError:
        return False
    return True


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (2, 3):
        print(__doc__)
        return 2
    plan_bytes = Path(args[1]).read_bytes()
    try:
        pos = position(json.loads(Path(args[0]).read_text()), json.loads(plan_bytes), plan_bytes)
        wrote = rebuild(args[0], args[2], args[1]) if len(args) == 3 else None
    except ValueError as err:
        print("refused:", err)
        return 1
    print("done:", " ".join(pos["done"]) or "-")
    print("skipped:", " ".join(pos["skipped"]) or "-")
    print("next:", pos["next"] or "none")
    if wrote is not None:
        print("results written" if wrote else "results exist, left as they are")
    return 0


if __name__ == "__main__":
    sys.exit(main())
