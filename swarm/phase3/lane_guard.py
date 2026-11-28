#!/usr/bin/env python3
"""A net under a development agent: where it may write, and what its shell may not do.

The agent host runs this before every Write, Edit and Bash call of a development agent
(a PreToolUse hook in the agent's definition). It reads the call as JSON on standard
input, exits 0 to let it run and 2 to refuse it.

- Write and Edit may touch only files inside the folder of lane worktrees (SWARM_LANES).
- Read, Grep and Glob may look only inside the repository and the folder of lanes.
- The shell may not push, fetch, pull, clone, switch branch, rebase, merge or change
  remotes or worktrees, may not use the network or a package manager, may not use sudo,
  may not list the environment and may not name the host's private folders.
- Every other tool is refused.

This is a net, not a wall. A shell can be made to do what a pattern did not foresee, and
this script does not know which lane is calling, so it cannot keep one lane out of another.
The control that counts is applied when the lanes are joined: a lane that changed a path
it does not own is rejected whole.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

MARK = "swk-lane-guard"
START = r"(?:^|[;&|\n(]\s*|\bxargs\s+|\bexec\s+|\benv\s+(?:\w+=\S*\s+)*)"
DENIED = re.compile(
    START + r"(?:sudo\b|curl\b|wget\b|nc\b|ssh\b|scp\b|apt(?:-get)?\b|pip3?\b|uv\b|npm\b|npx\b|pnpm\b|yarn\b)"
    r"|" + START + r"git\b(?:\s+-[cC]\s+\S+)*\s+(?:push|remote|fetch|pull|clone|worktree|checkout|switch|rebase|merge)\b"
    r"|\bpython3?\s+-m\s+pip\b"
    # the environment and the host's private folders: they may hold credentials and other sessions' records
    r"|" + START + r"(?:env|printenv)\s*(?:$|[;&|\n>])"
    r"|/proc/\S*environ\b"
    r"|(?:~|\$HOME|\$\{HOME\}|/root|/home/\w+)/\.(?:claude|gaie-swarm|ssh|config|netrc|git-credentials)\b")


WRITES_A_FILE = re.compile(r"^\s*cat\b[^\n]*<<-?\s*(['\"]?)([A-Za-z_]+)\1[^\n]*$")


def visible(command: str) -> str:
    """The command without the text of files it writes with `cat > FILE <<TAG`. That text is content, not commands.
    A here-document given to anything else, such as a shell, stays in view."""
    kept, closing = [], None
    for line in command.split("\n"):
        if closing is not None:
            closing = None if line.strip() == closing else closing
            continue
        kept.append(line)
        opened = WRITES_A_FILE.match(line)
        if opened:
            closing = opened.group(2)
    return "\n".join(kept)


def allowed(call: dict) -> tuple[bool, str]:
    tool, given = call.get("tool_name"), call.get("tool_input") or {}
    if tool in ("Write", "Edit", "NotebookEdit"):
        lanes = os.environ.get("SWARM_LANES")
        target = given.get("file_path") or given.get("notebook_path")
        if not lanes or not isinstance(target, str):
            return False, "no lane folder is set"
        root, path = Path(lanes).resolve(), Path(target).resolve()
        return (root in path.parents, "a development agent writes only inside its lane's worktree")
    if tool in ("Read", "Grep", "Glob"):
        lanes = os.environ.get("SWARM_LANES")
        target = given.get("file_path") if tool == "Read" else given.get("path")
        if target is None and tool != "Read":
            return True, ""  # a search with no folder named starts in the repository
        if not lanes or not isinstance(target, str):
            return False, "no lane folder is set"
        path, roots = Path(target).resolve(), (Path(lanes).resolve(), Path(__file__).resolve().parents[2])
        return (any(root == path or root in path.parents for root in roots), "a development agent reads only inside the repository and the lanes")
    if tool == "Bash":
        command = given.get("command")
        if not isinstance(command, str):
            return False, "unreadable command"
        return (DENIED.search(visible(command)) is None, "no push, fetch, branch switch, merge, network, package manager or sudo in a lane")
    return False, "this tool is not one a development agent has"


def main() -> int:
    try:
        ok, why = allowed(json.loads(sys.stdin.read()))
    except (ValueError, TypeError, AttributeError, OSError):
        ok, why = False, "unreadable call"
    if ok:
        return 0
    print(f"{MARK}: refused: {why}.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
