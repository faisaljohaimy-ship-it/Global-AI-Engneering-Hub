#!/usr/bin/env python3
"""A queue of tasks that many workers draw from at once, without one task ever going to two.

    python3 swarm/phase3/taskqueue.py status STAGE_DIR

The state is one empty-or-tiny file per task under STAGE_DIR/.queue: `waiting/ID`,
`claimed/ID` (holding the worker's name) and `done/ID` (the worker and the outcome). A claim
is a rename from `waiting` to `claimed`, which the file system does for exactly one caller.
Each worker may claim at most `batch` tasks, counted in `workers/NAME`: a line `ID` adds a task
and a line `-ID` takes it off again (written when a claim is reclaimed), so the file is only
ever appended to.

A claim holds the worker's name and the time it was made. `reclaim` moves claims older than the
lease back to `waiting`; a worker that hands in after that no longer holds the task, and its
hand-in is ignored.

    python3 swarm/phase3/taskqueue.py reclaim STAGE_DIR [LEASE_SECONDS]
"""
from __future__ import annotations

import itertools
import json
import os
import re
import sys
import time
from pathlib import Path

WORKER = re.compile(r"[A-Za-z0-9_-]{1,40}")
OUTCOMES = ("handed-in", "failed")


CHUNK = 256  # how many waiting names one claim reads at a time


def create(stage_dir: Path, task_ids: list[str], batch: int) -> None:
    """Start a queue holding these tasks. Each worker may take up to `batch` of them."""
    root = Path(stage_dir) / ".queue"
    for name in ("waiting", "claimed", "done", "workers", "reclaiming"):
        (root / name).mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)  # the queue is its owner's only
    (root / "meta.json").write_text(json.dumps({"batch": int(batch), "tasks": len(task_ids)}))
    for ident in task_ids:
        (root / "waiting" / ident).touch()


def _net(path: Path) -> list[str]:
    """The task ids a worker holds now: its lines, with each `-ID` cancelling the last `ID`."""
    held: list[str] = []
    try:
        lines = path.read_text().split()
    except OSError:
        return held
    for line in lines:
        if line.startswith("-"):
            if line[1:] in held:
                held.remove(line[1:])
        else:
            held.append(line)
    return held


def _lease(path: Path) -> tuple[str | None, float | None]:
    """The worker and claim time written in a claimed file; None where it is not written yet."""
    try:
        parts = path.read_text().split()
    except OSError:
        return None, None
    if len(parts) != 2:
        return None, None
    try:
        return parts[0], float(parts[1])
    except ValueError:
        return None, None


def _made(path: Path) -> tuple[str | None, float | None]:
    """The lease of a claimed file. A claim whose worker was killed between taking the file and writing its lease has no
    lease written: then the time is the file's own, and there is no worker, so that the task is not lost for the stage."""
    worker, made = _lease(path)
    if made is None:
        try:
            if path.stat().st_size == 0:
                return None, path.stat().st_mtime
        except OSError:
            pass
    return worker, made


def claim(stage_dir: Path, worker: str, now: float | None = None) -> str | None:
    """Give the next waiting task to `worker`. None when nothing waits or the worker has had its batch."""
    if not WORKER.fullmatch(worker):
        raise ValueError("not a worker name")
    stamp = time.time() if now is None else float(now)
    root = Path(stage_dir) / ".queue"
    batch = json.loads((root / "meta.json").read_text())["batch"]
    mine = root / "workers" / worker
    if len(_net(mine)) >= batch:
        return None
    # Read the waiting folder a part at a time. Listing and sorting all of it for every claim made 100,000 tasks
    # too slow to hand out (measured: 46 claims a second). A queue of up to CHUNK tasks is still handed out in order.
    with os.scandir(root / "waiting") as entries:
        while True:
            part = sorted(entry.name for entry in itertools.islice(entries, CHUNK))
            if not part:
                return None
            for ident in part:
                try:
                    os.rename(root / "waiting" / ident, root / "claimed" / ident)
                except FileNotFoundError:  # another worker took it first
                    continue
                (root / "claimed" / ident).write_text(f"{worker} {stamp!r}")
                with open(mine, "a", encoding="utf-8") as handle:
                    handle.write(ident + "\n")
                return ident


def release(stage_dir: Path, task_id: str, worker: str, outcome: str) -> None:
    """Record that `worker` is finished with a task it claimed.

    Doing it twice changes nothing, and neither does a hand-in by a worker that no longer holds
    the task (its claim ran out and the task went back to the queue or to another worker)."""
    if outcome not in OUTCOMES:
        raise ValueError("unknown outcome")
    if not WORKER.fullmatch(worker):
        raise ValueError("not a worker name")
    root = Path(stage_dir) / ".queue"
    if _lease(root / "claimed" / task_id)[0] != worker:
        return
    try:
        os.rename(root / "claimed" / task_id, root / "done" / task_id)
    except FileNotFoundError:
        return
    owner = _lease(root / "done" / task_id)[0]
    if owner != worker:  # it changed hands between the check and the move: put it back
        try:
            os.rename(root / "done" / task_id, root / "claimed" / task_id)
        except OSError:
            pass
        return
    (root / "done" / task_id).write_text(f"{worker} {outcome}")


def reclaim(stage_dir: Path, now: float | None = None, lease_seconds: float = 900) -> list[str]:
    """Move claims older than the lease back to waiting. Returns their ids, sorted."""
    stamp = time.time() if now is None else float(now)
    root = Path(stage_dir) / ".queue"
    back: list[str] = []
    for ident in sorted(os.listdir(root / "claimed")):
        _, made = _made(root / "claimed" / ident)
        if made is None or stamp - made <= lease_seconds:
            continue
        private = root / "reclaiming" / f"{ident}.{os.getpid()}"
        try:
            os.rename(root / "claimed" / ident, private)  # only one reclaimer gets it
        except FileNotFoundError:
            continue
        worker, made = _made(private)
        if made is None or stamp - made <= lease_seconds:  # it was handed on meanwhile: give it back
            os.rename(private, root / "claimed" / ident)
            continue
        if worker is not None:
            with open(root / "workers" / worker, "a", encoding="utf-8") as handle:
                handle.write("-" + ident + "\n")
        os.rename(private, root / "waiting" / ident)
        (root / "waiting" / ident).write_text("")
        back.append(ident)
    return back


def holder(stage_dir: Path, task_id: str) -> str | None:
    """The worker that holds a claimed task."""
    return _lease(Path(stage_dir) / ".queue" / "claimed" / task_id)[0]


def status(stage_dir: Path, now: float | None = None) -> dict:
    stamp = time.time() if now is None else float(now)
    root = Path(stage_dir) / ".queue"
    done = [(root / "done" / name).read_text().split() for name in os.listdir(root / "done")]
    by_worker = {path.name: _net(path) for path in sorted((root / "workers").iterdir())}
    made = [t for t in (_lease(root / "claimed" / name)[1] for name in os.listdir(root / "claimed")) if t is not None]
    return {"tasks": json.loads((root / "meta.json").read_text())["tasks"], "waiting": len(os.listdir(root / "waiting")),
            "claimed": len(os.listdir(root / "claimed")), "handed_in": sum(1 for d in done if d[-1:] == ["handed-in"]),
            "failed": sum(1 for d in done if d[-1:] == ["failed"]), "workers": len(by_worker), "by_worker": by_worker,
            "oldest_claim_age": max(0.0, stamp - min(made)) if made else None}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "status":
        print(json.dumps(status(Path(sys.argv[2])), indent=1))
        sys.exit(0)
    if len(sys.argv) in (3, 4) and sys.argv[1] == "reclaim":
        print(json.dumps(reclaim(Path(sys.argv[2]), None, float(sys.argv[3]) if len(sys.argv) == 4 else 900)))
        sys.exit(0)
    print(__doc__.split("\n\n")[1])
    sys.exit(2)
