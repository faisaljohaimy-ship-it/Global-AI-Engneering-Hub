#!/usr/bin/env python3
"""swk of the third phase: the worker's command when tasks come from a queue.

    swk next [WORKER]            take the next task of the queue (a worker with no name gets one)
    swk submit ID <<'PY' ... PY  hand in a solution; when the task is settled, the queue is told
    swk show|status|...          every other verb is the second phase's own

`next` prints `worker NAME` and the task text, or says there are no more tasks. `submit` runs
the examples as the second phase does; when they passed, or no attempts are left, the task is
released from its holder and the reply ends with the command that asks for the next one.
Everything lives under SWARM_HOME/p3 (default ~/.gaie-swarm/p3), outside any repository.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]
import kit  # noqa: E402
import taskqueue  # noqa: E402

try:
    import compact
except ImportError:  # another lane's module; the full text is the fallback
    compact = None

NONE_LEFT = "No more tasks for you. Reply DONE."


def home() -> Path:
    return Path(os.environ.get("SWARM_HOME", Path.home() / ".gaie-swarm")) / "p3"


def render(text: str, first: bool) -> str:
    if compact is not None:
        try:
            return compact.render(text, first)
        except Exception:  # noqa: BLE001 - never lose a task to a renderer fault
            pass
    return text


def next_task(args: list[str]) -> None:
    if len(args) > 1:
        raise kit.Refused("swk next takes at most one argument")
    worker = args[0] if args else "w" + secrets.token_hex(3)
    if not taskqueue.WORKER.fullmatch(worker):
        raise kit.Refused("not a worker name")
    stage = kit.stage()
    ident = taskqueue.claim(stage, worker)
    if ident is None:
        print(NONE_LEFT)
        return
    first = len((stage / ".queue" / "workers" / worker).read_text().split()) == 1
    _, state = kit.locate(ident)
    text = (stage / ident / "TASK.md").read_text(encoding="utf-8")
    kit.emit(state, "next", f"worker {worker}\n{render(text, first)}")


def submit(args: list[str]) -> None:
    if len(args) != 1:
        raise kit.Refused("swk submit takes 1 arguments")
    ident = args[0]
    kit.locate(ident)
    stage = kit.stage()
    worker = taskqueue.holder(stage, ident)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        kit.submit(ident)
    reply = buffer.getvalue().rstrip("\n")
    if worker is not None:
        _, state = kit.locate(ident)
        passed = "examples passed. Reply DONE" in reply and not re.search(r"\d+ of \d+ examples passed", reply)
        if passed or kit.load(state)["attempts"] >= kit.ATTEMPTS:
            taskqueue.release(stage, ident, worker, "handed-in" if passed else "failed")
            reply += f"\nThen run: swk next {worker}"
    print(reply)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    kit.HOME = home()
    if argv and argv[0] in ("next", "submit"):
        try:
            (next_task if argv[0] == "next" else submit)(argv[1:])
        except kit.Refused as problem:
            print(f"swk: refused: {problem}")
            return 2
        except (OSError, ValueError, KeyError) as problem:
            print(f"swk: refused: {type(problem).__name__}")
            return 2
        return 0
    return kit.main(argv)


if __name__ == "__main__":
    sys.exit(main())
