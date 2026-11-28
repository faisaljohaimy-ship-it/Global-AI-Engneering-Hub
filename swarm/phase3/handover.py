#!/usr/bin/env python3
"""Write the handover page that lets the other engine take over the swarm work, with receipts.

    python3 swarm/phase3/handover.py            write swarm/phase3/HANDOVER.md
    python3 swarm/phase3/handover.py --check    exit 1 when that file is not current

`receipts(root)` lists every source, plan, test and agent definition of the swarm work with
its sha256 and line count. `write(root)` returns the text of the page. The page is
regenerated whenever lanes are joined; it goes stale in between, and --check says so.
"""
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = "swarm/phase3/HANDOVER.md"
PATTERNS = ["swarm/**/*.py", "swarm/**/PLAN*.json", "tests/test_swarm*.py",
            "tests/test_p3_*.py", ".claude/agents/swarm-*.md"]


def receipts(root: Path) -> list[dict]:
    root = Path(root)
    found = {}
    for pattern in PATTERNS:
        for p in root.glob(pattern):
            rel = p.relative_to(root).as_posix()
            if p.is_file() and rel != PAGE and "__pycache__" not in rel:
                found[rel] = p
    rows = []
    for rel in sorted(found):
        data = found[rel].read_bytes()
        rows.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(),
                     "lines": data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)})
    return rows


def _sentence(text: str) -> str:
    text = " ".join(text.strip().split("\n\n")[0].split())
    m = re.search(r"[.!?](\s|$)", text)
    return text[:m.end()].strip() if m else text


def _doc(path: Path) -> str:
    try:
        return _sentence(ast.get_docstring(ast.parse(path.read_text())) or "") or "(no docstring)"
    except (OSError, SyntaxError):
        return "(not readable)"


def _third(path: Path) -> str:
    try:
        text = path.read_text()
    except OSError:
        return "(not readable)"
    sections = re.split(r"^## ", text, flags=re.M)
    body = " ".join(sections[1].split("\n", 1)[1].split()) if len(sections) > 1 else ""
    for s in re.split(r"(?<=[.!?])\s+", body):
        if s.startswith("The third phase"):
            return s
    return _sentence(body) or "(no section)"


EVIDENCE = "swarm/phase3/evidence/stages.json"
NO_RUN = "The gated run has not been recorded on this branch."


def _stages(root: Path):
    try:
        data = json.loads((Path(root) / EVIDENCE).read_text())
        return data if isinstance(data.get("stages"), list) else None
    except (OSError, ValueError, AttributeError):
        return None


def _ended(data: dict, root: Path) -> str:
    for key in ("ended", "end", "ended_because"):
        if data.get(key):
            v = data[key]
            return "; ".join(v) if isinstance(v, list) else str(v)
    try:
        sys.path[:0] = [str(Path(root) / "swarm/phase3"), str(Path(root) / "swarm/phase2"), str(Path(root) / "swarm")]
        import stage3
        stops = stage3.decide(data["stages"], None)[0]
        return "; ".join(stops) if stops else "no stop rule fired in the recorded stages"
    except Exception:  # the reason is derived only when the run's own code can be loaded
        return "the file does not record why the run ended"


def _gate_section(root: Path, data) -> list[str]:
    out = ["## The security gate", ""]
    if data is None:
        return out + [NO_RUN, ""]
    gates = [(s["label"], s["security_gate"]) for s in data["stages"] if s.get("security_gate")]
    if not gates:
        return out + [NO_RUN, ""]
    for label, gate in gates:
        out.append(f"Gate stage `{label}`: " + ("passed." if gate.get("passed") else "did not pass."))
        for why in gate.get("why") or []:
            out.append(f"- Reason: {why}")
        out += ["", "| probe | agent type | must be | agents | held |", "|---|---|---|---|---|"]
        out += [f"| {r.get('what')} | {r.get('agent_type')} | {r.get('must_be')} | {r.get('agents')} | "
                f"{'yes' if r.get('held') else 'no'} |" for r in gate.get("probes", [])]
        out.append("")
    return out


def _run_section(root: Path, data) -> list[str]:
    out = ["## The run", ""]
    if data is None:
        return out + [NO_RUN, ""]
    ran = [s for s in data["stages"] if not s.get("skipped")]
    skipped = [s for s in data["stages"] if s.get("skipped")]
    agents = sum(s.get("actual_agents") or 0 for s in ran)
    verified = sum(s.get("verified_tasks") or 0 for s in ran)
    tasks = sum(s.get("tasks") or 0 for s in ran)
    out += [f"- Stages run: {len(ran)}" + (" (" + ", ".join(s["label"] for s in ran) + ")" if ran else "") + ".",
            f"- Stages skipped: {len(skipped)}" + (" (" + "; ".join(f"{s['label']}: {s['skipped']}" for s in skipped) + ")" if skipped else "") + ".",
            f"- Real agents started: {agents}.",
            f"- Tasks verified: {verified} of {tasks}.",
            f"- Why the run ended: {_ended(data, root)}.", ""]
    return out


def _reviews_section(root: Path) -> list[str]:
    out = ["## The reviews", ""]
    files = sorted(p for p in (Path(root) / "swarm/phase3/reviews").glob("*") if p.is_file()) \
        if (Path(root) / "swarm/phase3/reviews").is_dir() else []
    if not files:
        return out + ["No review file is present under `swarm/phase3/reviews/`.", ""]
    for p in files:
        try:
            head = next((ln.lstrip("#").strip() for ln in p.read_text().splitlines() if ln.startswith("#")), "(no heading)")
        except (OSError, UnicodeDecodeError):
            head = "(not readable)"
        out.append(f"- `swarm/phase3/reviews/{p.name}`: {head}")
    return out + [""]


def _freeze_section(root: Path) -> list[str]:
    out = ["## The freeze", ""]
    p = Path(root) / "swarm/phase3/FREEZE.json"
    if not p.is_file():
        return out + ["`swarm/phase3/FREEZE.json` does not exist: nothing is frozen.", ""]
    try:
        d = json.loads(p.read_text())
        files = d.get("files", d) if isinstance(d, dict) else d
        n = len(files)
    except (OSError, ValueError):
        return out + ["`swarm/phase3/FREEZE.json` exists but cannot be read.", ""]
    return out + [f"`swarm/phase3/FREEZE.json` exists and holds {n} files.", ""]


def _decisions(root: Path) -> list[str]:
    try:
        hooks = json.loads((Path(root) / ".claude/settings.json").read_text())["hooks"]["PreToolUse"]
        cmds = [h["command"] for g in hooks for h in g["hooks"]]
        cmd = cmds[0]
        fallback = "exit 0" in cmd and "command -v" in cmd
        gate = ("`.claude/settings.json` sets a PreToolUse gate (matcher `" + hooks[0].get("matcher", "") + "`) for every session "
                "started in this repository. Its command is `" + cmd + "`. " +
                ("When the gate program is not installed that command exits 0, so every call is allowed: the session runs ungated. "
                 "Install the gate before any worker starts." if fallback else "Read the command to see what it does without the program."))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        gate = "`.claude/settings.json` could not be read as a gate setting; check it before any session starts."
    return ["## What the reviewer must decide", "",
            "1. The order in which the three branches stack: `claude/swarm-100x100`, then `claude/swarm-phase-2`, then `claude/swarm-phase-3`.",
            "2. The author never merges. The merge and the release belong to the reviewer.",
            "3. " + gate,
            "4. The worker definitions under `.claude/agents/` are for the experiment only, not for general use of the repository.", ""]


def write(root: Path) -> str:
    root = Path(root)
    one = _doc(root / "swarm/ladder.py")
    two = _doc(root / "swarm/phase2/stage.py")
    three = _third(root / "swarm/phase3/CONTRACT.md")
    out = [
        "# Handover of the swarm work to the other engine", "",
        "Generated by `python3 swarm/phase3/handover.py`. Do not edit by hand; "
        "`--check` fails when it is out of date.", "",
        "## The three phases", "",
        f"- First phase (`swarm/ladder.py`): {one}",
        f"- Second phase (`swarm/phase2/stage.py`): {two}",
        f"- Third phase (`swarm/phase3/CONTRACT.md`): {three}", "",
        "## Running the tests", "",
        "From the root of the repository, with the standard library only:", "",
        "    python3 -m unittest tests.test_swarm",
        "    python3 -m unittest discover -s tests -p 'test_p3_*.py' -t .", "",
        "Each test file can also be run alone, for example `python3 -m unittest tests.test_p3_handover`.", "",
        "## Where each phase keeps its evidence", "",
        "- First phase: `swarm/evidence/` and `swarm/state/` (benchmark results, resource metrics, task state).",
        "- Second phase: `swarm/phase2/evidence/` (`stages.json`) and `swarm/phase2/RESULTS.md`, "
        "written by `stage.py report`.",
        "- Third phase: private working files under `SWARM_HOME/p3` (default `~/.gaie-swarm/p3`), "
        "never in the repository. No evidence folder for it is defined here.", "",
        "## The task store",
        "",
        "Task coordination is private and file-backed, in a state directory outside Git. "
        "The protocol does not run agents. Its subcommands, as listed by "
        "`python3 -m engineering_os.orchestration --help`, are: "
        "`status`, `create`, `route`, `claim`, `renew`, `handover`, `submit`, `review`, "
        "`fail`, `recover`, `checkpoint`, `restore`. Every call takes `--state-dir DIR` first, "
        "for example `python3 -m engineering_os.orchestration --state-dir DIR status`. "
        "Leases fence coordinator writes only; actors are caller-supplied assertions.", "",
        "## What has not been done from the other engine", "",
        "Nothing in these phases was run from Codex. No stage, test run or task-store call "
        "listed here has been performed by Codex, and Codex availability has not been tested.", "",
        "@@SECTIONS@@",
        "## Receipts", "",
        "| path | sha256 | lines |", "|---|---|---|",
    ]
    i = out.index("@@SECTIONS@@")
    data = _stages(root)
    out[i:i + 1] = (_gate_section(root, data) + _run_section(root, data) + _reviews_section(root)
                    + _freeze_section(root) + _decisions(root))
    out += [f"| {r['path']} | {r['sha256']} | {r['lines']} |" for r in receipts(root)]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    page = ROOT / PAGE
    text = write(ROOT)
    if "--check" in argv:
        current = page.read_text() if page.exists() else None
        if current != text:
            print("HANDOVER.md is not current")
            return 1
        print("HANDOVER.md is current")
        return 0
    page.write_text(text)
    print("wrote", PAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
