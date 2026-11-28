"""Freeze the experiment: record and check the hash of every file in it.

What it does: `write(root)` records in swarm/phase3/FREEZE.json the SHA-256 and
size of every file of the experiment (everything under swarm/, the swarm agent
definitions, .claude/settings.json, the swarm and phase 3 tests and the phase 3
fixtures), plus the closing statement, the file count and one hash over all the
others. `check(root)` returns, in plain words, every file changed, added or
removed since.

How to call it, from the repository root:
    python3 swarm/phase3/freeze.py write   # write FREEZE.json
    python3 swarm/phase3/freeze.py check   # exit 1 if anything changed

In a git checkout only tracked files are frozen (git ls-files); otherwise the
tree is walked. Standard library only.
"""
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

STATEMENT = ("The numerical scale-up phase is closed. "
             "No further scale stage is to be run on this branch.")
FREEZE = "swarm/phase3/FREEZE.json"


def _wanted(rel):
    parts = rel.split("/")
    if "__pycache__" in parts or rel == FREEZE:
        return False
    if parts[0] == "swarm":
        return True
    if rel == ".claude/settings.json":
        return True
    if (len(parts) == 3 and parts[:2] == [".claude", "agents"]
            and fnmatch.fnmatchcase(parts[2], "swarm-*.md")):
        return True
    if parts[0] == "tests":
        if len(parts) == 2 and (fnmatch.fnmatchcase(parts[1], "test_swarm*.py")
                                or fnmatch.fnmatchcase(parts[1], "test_p3_*.py")):
            return True
        if len(parts) >= 3 and parts[1] == "fixtures" and parts[2].startswith("p3-"):
            return True
    return False


def _git_files(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                             capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", "surrogateescape").split("\0")


def _walk_files(root):
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for name in files:
            found.append(os.path.relpath(os.path.join(folder, name), root))
    return [p.replace(os.sep, "/") for p in found]


def files(root):
    """Sorted relative paths of the files that belong to the experiment."""
    root = Path(root)
    names = _git_files(root) if (root / ".git").exists() else None
    if names is None:
        names = _walk_files(root)
    return sorted({n for n in names
                   if n and _wanted(n) and (root / n).is_file()})


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _overall(entries):
    h = hashlib.sha256()
    for path in sorted(entries):
        e = entries[path]
        h.update(f"{path}\0{e['sha256']}\0{e['size']}\n".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


def _entries(root):
    root = Path(root)
    return {p: {"sha256": _digest(root / p), "size": (root / p).stat().st_size}
            for p in files(root)}


def write(root):
    """Write FREEZE.json under root and return the document."""
    root = Path(root)
    entries = _entries(root)
    doc = {"statement": STATEMENT, "file_count": len(entries),
           "overall_sha256": _overall(entries), "files": entries}
    target = root / FREEZE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return doc


def check(root):
    """Return a plain-words line for every file changed, added or removed."""
    root = Path(root)
    try:
        doc = json.loads((root / FREEZE).read_text(encoding="utf-8"))
        recorded = doc["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return [f"{FREEZE} is missing or unreadable"]
    problems = []
    if doc.get("statement") != STATEMENT:
        problems.append(f"{FREEZE}: the closing statement was changed")
    if doc.get("file_count") != len(recorded) or doc.get("overall_sha256") != _overall(recorded):
        problems.append(f"{FREEZE}: its own count or overall hash does not match its file list")
    now = _entries(root)
    for p in sorted(set(recorded) - set(now)):
        problems.append(f"removed: {p}")
    for p in sorted(set(now) - set(recorded)):
        problems.append(f"added: {p}")
    for p in sorted(set(now) & set(recorded)):
        if now[p] != recorded[p]:
            problems.append(f"changed: {p}")
    return problems


def main(argv):
    root = Path(__file__).resolve().parents[2]
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "write":
        doc = write(root)
        print(f"frozen: {doc['file_count']} files written to {FREEZE}")
        return 0
    if cmd == "check":
        problems = check(root)
        if problems:
            print("\n".join(problems))
            return 1
        n = json.loads((root / FREEZE).read_text(encoding="utf-8"))["file_count"]
        print(f"frozen: {n} files unchanged")
        return 0
    print("usage: freeze.py write|check")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
