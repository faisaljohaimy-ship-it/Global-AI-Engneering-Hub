#!/usr/bin/env python3
"""A queue of tasks that many workers draw from at once, without one task ever going to two.

    python3 swarm/phase3/taskqueue.py status STAGE_DIR

The state is one empty-or-tiny file per task under STAGE_DIR/.queue: `waiting/ID`,
`claimed/ID` (holding the worker's name) and `done/ID` (the worker and the outcome). A claim
is a rename from `waiting` to `claimed`, which the file system does for exactly one caller.
Each worker may claim at most `batch` tasks, counted in `workers/NAME`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

WORKER = re.compile(r"[A-Za-z0-9_-]{1,40}")
OUTCOMES = ("handed-in", "failed")


def create(stage_dir: Path, task_ids: list[str], batch: int) -> None:
    """Start a queue holding these tasks. Each worker may take up to `batch` of them."""
    root = Path(stage_dir) / ".queue"
    for name in ("waiting", "claimed", "done", "workers"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "meta.json").write_text(json.dumps({"batch": int(batch), "tasks": len(task_ids)}))
    for ident in task_ids:
        (root / "waiting" / ident).touch()


def claim(stage_dir: Path, worker: str) -> str | None:
    """Give the next waiting task to `worker`. None when nothing waits or the worker has had its batch."""
    if not WORKER.fullmatch(worker):
        raise ValueError("not a worker name")
    root = Path(stage_dir) / ".queue"
    batch = json.loads((root / "meta.json").read_text())["batch"]
    mine = root / "workers" / worker
    if mine.exists() and len(mine.read_text().split()) >= batch:
        return None
    for ident in sorted(os.listdir(root / "waiting")):
        try:
            os.rename(root / "waiting" / ident, root / "claimed" / ident)
        except FileNotFoundError:  # another worker took it first
            continue
        (root / "claimed" / ident).write_text(worker)
        with open(mine, "a", encoding="utf-8") as handle:
            handle.write(ident + "\n")
        return ident
    return None


def release(stage_dir: Path, task_id: str, worker: str, outcome: str) -> None:
    """Record that `worker` is finished with a task it claimed. Doing it twice changes nothing."""
    if outcome not in OUTCOMES:
        raise ValueError("unknown outcome")
    root = Path(stage_dir) / ".queue"
    try:
        os.rename(root / "claimed" / task_id, root / "done" / task_id)
    except FileNotFoundError:
        return
    (root / "done" / task_id).write_text(f"{worker} {outcome}")


def holder(stage_dir: Path, task_id: str) -> str | None:
    """The worker that holds a claimed task."""
    try:
        return (Path(stage_dir) / ".queue" / "claimed" / task_id).read_text().strip() or None
    except OSError:
        return None


def status(stage_dir: Path) -> dict:
    root = Path(stage_dir) / ".queue"
    done = [(root / "done" / name).read_text().split() for name in os.listdir(root / "done")]
    by_worker = {path.name: path.read_text().split() for path in sorted((root / "workers").iterdir())}
    return {"tasks": json.loads((root / "meta.json").read_text())["tasks"], "waiting": len(os.listdir(root / "waiting")),
            "claimed": len(os.listdir(root / "claimed")), "handed_in": sum(1 for d in done if d[-1:] == ["handed-in"]),
            "failed": sum(1 for d in done if d[-1:] == ["failed"]), "workers": len(by_worker), "by_worker": by_worker}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "status":
        print(json.dumps(status(Path(sys.argv[2])), indent=1))
        sys.exit(0)
    print(__doc__.split("\n\n")[1])
    sys.exit(2)
