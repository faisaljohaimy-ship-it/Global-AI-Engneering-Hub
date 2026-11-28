#!/usr/bin/env python3
"""swk of the third phase: the worker's command when tasks come from a queue.

    swk next [WORKER [TICKET]]   take the next task (a worker with no name gets one); a further
                                 task needs the ticket of the one handed in last
    swk submit ID [TICKET] <<'PY' ... PY
                                 hand in a solution; in a queue the ticket `next` printed is needed
    swk show|status|...          every other verb is the second phase's own

`next` prints `worker NAME` and the task text, or says there are no more tasks. `submit` runs
the examples as the second phase does; when they passed, or no attempts are left, the task is
released from its holder and the reply ends with the command that asks for the next one.
Everything lives under SWARM_HOME/p3 (default ~/.gaie-swarm/p3), outside any repository.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import io
import os
import re
import secrets
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]
import kit  # noqa: E402
import taskqueue  # noqa: E402

try:
    import compact
except ImportError:  # another lane's module; the full text is the fallback
    compact = None

TICKET = re.compile(r"[0-9a-f]{8}")
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


def _digest(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


def _tickets(stage: Path) -> Path:
    return stage / ".queue" / "tickets"


def _keep(path: Path, text: str) -> None:
    """Write a file only its owner can read, in one step."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    scratch = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    descriptor = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)
    os.replace(scratch, path)


def _matches(path: Path, ticket: str) -> bool:
    try:
        kept = path.read_text().strip()
    except OSError:
        return False
    return bool(TICKET.fullmatch(ticket)) and hmac.compare_digest(kept, _digest(ticket))


def _refuse(stage: Path, ident: str) -> None:
    """Note one refused hand-in: the time and the task id, never the ticket."""
    ident = ident if kit.ID.fullmatch(ident) else "-"
    try:
        with open(stage / ".queue" / "refused", "a", encoding="utf-8") as handle:
            handle.write(f"{time.time():.3f} {ident}\n")
    except OSError:
        pass
    raise kit.Refused("the ticket for that task is missing, wrong or used")


def next_task(args: list[str]) -> None:
    if len(args) > 2:
        raise kit.Refused("swk next takes at most two arguments")
    worker = args[0] if args else "w" + secrets.token_hex(3)
    if not taskqueue.WORKER.fullmatch(worker):
        raise kit.Refused("not a worker name")
    stage = kit.stage()
    mine = stage / ".queue" / "workers" / worker
    held = taskqueue._net(mine)
    if held:  # a worker that has drawn before proves it with the ticket of its last task
        ticket = args[1] if len(args) == 2 else ""
        if not (_matches(_tickets(stage) / held[-1], ticket) or _matches(_tickets(stage) / (held[-1] + ".spent"), ticket)):
            raise kit.Refused(f"give the ticket of your last task: swk next {worker} TICKET")
    elif len(args) == 2:
        raise kit.Refused("a worker's first draw takes no ticket")
    ident = taskqueue.claim(stage, worker)
    if ident is None:
        print(NONE_LEFT)
        return
    ticket = secrets.token_hex(4)
    _keep(_tickets(stage) / ident, _digest(ticket) + "\n")
    (_tickets(stage) / (ident + ".spent")).unlink(missing_ok=True)
    first = len(mine.read_text().split()) == 1
    _, state = kit.locate(ident)
    text = render((stage / ident / "TASK.md").read_text(encoding="utf-8"), first)
    line = f"swk submit {ident} {ticket} <<'PY'"
    text, count = re.subn(r"swk submit (?:ID|" + re.escape(ident) + r") <<'PY'", line, text)
    if not count:
        text += f"\nHand in the whole file with: {line} (the file, then PY on a line of its own)"
    kit.emit(state, "next", f"worker {worker}\nticket {ticket}\n{text}")


def submit(args: list[str]) -> None:
    stage = kit.stage()
    queued = (stage / ".queue").is_dir()
    if len(args) != (2 if queued else 1):
        if queued and args:
            _refuse(stage, args[0])
        raise kit.Refused(f"swk submit takes {2 if queued else 1} arguments")
    ident = args[0]
    if queued and not (kit.ID.fullmatch(ident) and _matches(_tickets(stage) / ident, args[1]) and taskqueue.holder(stage, ident) is not None):
        _refuse(stage, ident)
    kit.locate(ident)
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
            if taskqueue.holder(stage, ident) is None:  # the ticket ends with the task
                with contextlib.suppress(OSError):
                    os.replace(_tickets(stage) / ident, _tickets(stage) / (ident + ".spent"))
            reply += f"\nThen run: swk next {worker} {args[1]}" if queued else f"\nThen run: swk next {worker}"
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
