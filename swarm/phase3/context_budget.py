"""Static size of what a worker starts with.

For every `.claude/agents/*.md` under a root folder this reports the characters of
the frontmatter and of the instructions, the tools, model and turn limit, whether the
shell is behind the gate (`swk-guard` or `swk-lane-guard` in a hook), and an ESTIMATED
token count (characters divided by four; an estimate, not a tokenizer's count). It also
counts the instruction files a session in the root loads: CLAUDE.md and AGENTS.md,
following one level of `@FILE` lines.

Call:  python3 swarm/phase3/context_budget.py [ROOT]
Prints a table and exits 1 if a limit is exceeded or a worker has a tool it should not.
"""
import re
import sys
from pathlib import Path

LIMITS = {"definition_chars": 1800, "instructions_chars": 8000,
          "tools": ["Bash"], "tools_by_name": {
              "swarm-dev": ["Bash", "Read", "Write", "Edit", "Grep", "Glob"]}}
GATES = ("swk-guard", "swk-lane-guard")
NOTE = "tokens are an estimate (characters / 4), not a tokenizer's count"


def _split(text):
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", text, re.S)
    return (m.group(1), m.group(2)) if m else ("", text)


def _field(front, key):
    m = re.search(rf"^{key}:[ \t]*(.*)$", front, re.M)
    return m.group(1).strip().strip("'\"") if m else None


def _tools(value):
    return [t.strip() for t in value.split(",") if t.strip()] if value else []


def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _instruction_files(root):
    rows = []
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = _read(root / name)
        if text is None:
            continue
        rows.append({"file": name, "chars": len(text)})
        for ref in re.findall(r"^@(\S+)\s*$", text, re.M):
            target = (root / ref)
            if not target.resolve().is_relative_to(root.resolve()):
                continue
            sub = _read(target)
            if sub is not None:
                rows.append({"file": ref, "chars": len(sub), "via": name})
    seen, unique = set(), []
    for r in rows:  # a file counted once even if reached twice
        if r["file"] not in seen:
            seen.add(r["file"])
            unique.append(r)
    return unique


def budget(root):
    root = Path(root)
    agents = []
    for path in sorted((root / ".claude" / "agents").glob("*.md")):
        text = _read(path)
        if text is None:
            continue
        front, body = _split(text)
        name = _field(front, "name") or path.stem
        turns = _field(front, "maxTurns")
        agents.append({
            "name": name,
            "frontmatter_chars": len(front),
            "instructions_chars": len(body),
            "chars": len(text),
            "tools": _tools(_field(front, "tools")),
            "model": _field(front, "model"),
            "maxTurns": int(turns) if turns and turns.isdigit() else None,
            "gated": any(g in front for g in GATES),
            "tokens_estimate": len(text) // 4,
        })
    files = _instruction_files(root)
    total = sum(f["chars"] for f in files)
    return {"agents": agents, "instruction_files": files,
            "instructions_chars": total,
            "instructions_tokens_estimate": total // 4, "note": NOTE}


def check(root, limits=None):
    lim = dict(LIMITS)
    lim.update(limits or {})
    data = budget(root)
    problems = []
    for a in data["agents"]:
        if a["chars"] > lim["definition_chars"]:
            problems.append(f"{a['name']}: definition {a['chars']} chars exceeds "
                            f"{lim['definition_chars']}")
        if a["name"].startswith("swarm-"):
            allowed = lim.get("tools_by_name", {}).get(a["name"], lim["tools"])
            extra = [t for t in a["tools"] if t not in allowed]
            if extra:
                problems.append(f"{a['name']}: tool not allowed: {', '.join(extra)}")
    if data["instructions_chars"] > lim["instructions_chars"]:
        problems.append(f"instruction files {data['instructions_chars']} chars exceed "
                        f"{lim['instructions_chars']}")
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[2]
    data = budget(root)
    print(f"{'agent':24}{'front':>7}{'instr':>7}{'tok~':>6} {'model':8}{'turns':>6} gate  tools")
    for a in data["agents"]:
        print(f"{a['name']:24}{a['frontmatter_chars']:>7}{a['instructions_chars']:>7}"
              f"{a['tokens_estimate']:>6} {str(a['model']):8}{str(a['maxTurns']):>6} "
              f"{'yes' if a['gated'] else 'no':5} {','.join(a['tools'])}")
    for f in data["instruction_files"]:
        print(f"instruction file {f['file']}: {f['chars']} chars")
    print(f"instruction total: {data['instructions_chars']} chars "
          f"(~{data['instructions_tokens_estimate']} tokens); {NOTE}")
    problems = check(root, {})
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
