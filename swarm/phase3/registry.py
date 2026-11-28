"""Expand the 100 registered roles of swarm/agents.json into 1,000 places.

Each role gets ten places with ids like T01-A01-03. A place is a row in a
file, not an agent that ran: registering one starts nothing.

Size rule, derived from the team number n (the Tnn part of the role id):
  small  - every team
  medium - teams 4 to 10
  large  - even-numbered teams
So small is takeable by 1,000 places, medium by 700 and large by 500.

Call:
  python3 swarm/phase3/registry.py           write registry.json beside this file
  python3 swarm/phase3/registry.py --check   exit 1 if the file is not what would be written
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENTS = HERE.parent / "agents.json"
OUT = HERE / "registry.json"
PER_ROLE = 10
SIZES = ("small", "medium", "large")
ABOUT = ("A registered place is a row in this file, not an agent that ran. "
         "Registering places starts nothing; an agent exists only while a host runs it.")


def sizes_for(team_number: int) -> list[str]:
    out = ["small"]
    if team_number >= 4:
        out.append("medium")
    if team_number % 2 == 0:
        out.append("large")
    return out


def slots() -> list[dict]:
    roles = json.loads(AGENTS.read_text(encoding="utf-8"))["agents"]
    rows = []
    for role in roles:
        n = int(role["id"].split("-")[0][1:])
        for k in range(1, PER_ROLE + 1):
            rows.append({"id": f"{role['id']}-{k:02d}", "role": role["id"],
                         "team": role["team"], "sizes": sizes_for(n),
                         "status": "registered"})
    return rows


def assign(tasks: list[dict], slots: list[dict]) -> dict:
    """Map task id to place id: rarest size first, least-loaded eligible place, ties by order."""
    by_size = {}
    for s in slots:
        for size in s["sizes"]:
            by_size.setdefault(size, []).append(s["id"])
    for t in tasks:
        if not by_size.get(t["size"]):
            raise ValueError(f"no place takes size {t['size']!r}")
    load = {s["id"]: 0 for s in slots}
    order = sorted(tasks, key=lambda t: (len(by_size[t["size"]]), t["size"], str(t["id"])))
    result = {}
    for t in order:
        best = min(by_size[t["size"]], key=lambda p: load[p])  # min keeps first on ties
        load[best] += 1
        result[t["id"]] = best
    return result


def document() -> str:
    return json.dumps({"about": ABOUT, "per_role": PER_ROLE, "places": slots()},
                      indent=1, sort_keys=True) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = document()
    if "--check" in argv:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("registry.json is current" if ok else "registry.json is out of date")
        return 0 if ok else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {len(slots())} places")
    return 0


if __name__ == "__main__":
    sys.exit(main())
