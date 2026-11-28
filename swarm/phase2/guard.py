#!/usr/bin/env python3
"""The gate in front of a worker's shell: only `swk` commands of a fixed shape get through.

It is run by the agent host before every Bash call of a worker (a PreToolUse hook in the
worker's definition). It reads the call as JSON on standard input, exits 0 to let it run
and 2 to refuse it; what it prints on standard error is shown to the worker.

Two shapes are let through, and nothing else:

    swk VERB WORD... ['QUOTED']...                one line; plain words and single-quoted text only
    swk submit|setline|answer WORD... <<'TAG'     a quoted here-document, closed by TAG on the last line

Plain words cannot hold a shell operator, single quotes stop every expansion, and a quoted
here-document is passed on as it is. So a worker cannot chain a second command, substitute
one, redirect output or reach a file by a path of its own choosing. Anything this script
cannot read is refused.
"""
from __future__ import annotations

import json
import re
import sys

MARK = "swk-guard"
WORD = r"[A-Za-z0-9_./:=,@%+-]+"
LINE = re.compile(rf"swk (?:show|next|test|read|grep|def|callers|select)(?: (?:{WORD}|'[^'\n]*'))*")
OPEN = re.compile(rf"swk (?:submit|setline|answer)(?: {WORD})* <<'([A-Za-z_]+)'")


def allowed(command: str) -> bool:
    command = command.strip("\n")
    if "\n" not in command:
        return command == "swk status" or LINE.fullmatch(command) is not None
    first, *body = command.split("\n")
    opened = OPEN.fullmatch(first)
    return opened is not None and body[-1] == opened.group(1) and opened.group(1) not in body[:-1]


def main() -> int:
    try:
        call = json.loads(sys.stdin.read())
        if call.get("tool_name") != "Bash":
            raise ValueError("not a shell call")
        command = call["tool_input"]["command"]
        if isinstance(command, str) and allowed(command):
            return 0
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    print(f"{MARK}: refused. Only the swk commands named in your instructions and your task run here, one per call.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
