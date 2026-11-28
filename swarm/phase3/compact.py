"""Compact task text for a worker's second and later tasks.

A worker that takes several tasks from the queue sees the same rules paragraph
(tasks.RULES) with each one. render(text, first) keeps it on the first task and
replaces it by the line "Rules as before." on later ones. saving(texts) reports
the characters before and after for a batch rendered in order.

Call from Python: compact.render(text, first=False); compact.saving([t1, t2]).
Running the file prints the saving for a batch of generated tasks.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]

import tasks  # noqa: E402

SHORT = "Rules as before."
_BLANKS = re.compile(r"\n(?:[ \t]*\n){2,}")


def render(text: str, first: bool) -> str:
    """First task: collapse blank-line runs. Later tasks: shorten the rules paragraph only."""
    rules = tasks.RULES
    if first or rules not in text:
        return _BLANKS.sub("\n\n", text)
    return text.replace(rules, SHORT, 1)


def saving(texts: list[str]) -> dict:
    """Characters before and after for a batch rendered in order, and the percent saved."""
    before = sum(len(t) for t in texts)
    after = sum(len(render(t, i == 0)) for i, t in enumerate(texts))
    percent = round(100.0 * (before - after) / before, 2) if before else None
    return {"before": before, "after": after, "percent": percent}


def main() -> int:
    batch = [tasks.small(n, tasks.SEED)["text"] for n in range(1, 6)]
    print(saving(batch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
