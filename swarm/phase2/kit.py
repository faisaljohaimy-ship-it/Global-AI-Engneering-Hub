#!/usr/bin/env python3
"""swk: the one command a worker of the second phase may run.

    swk show ID                          print the task
    swk submit ID <<'PY' ... PY          hand in solution.py (small and medium tasks); the examples are run
    swk status                           say which stage is open

  large tasks only:
    swk test ID                          run the project's tests
    swk read ID PATH [FIRST:LAST]        print a file, or some of its lines, with line numbers
    swk grep ID 'REGEX' [PATH]           search the project, or one file or folder
    swk def ID NAME                      one function with line numbers          (lean stages)
    swk callers ID NAME                  the functions whose code calls it       (lean stages)
    swk select ID PATH FIELD=VALUE OUT   a field of the matching records of a JSON list   (lean stages)
    swk setline ID PATH N <<'EOF' ... EOF   replace one line of a module of the package
    swk answer ID <<'EOF' ... EOF        hand in the JSON object of facts

A worker gets no other tool. It cannot choose a path outside its task, cannot read the
withheld tests, and code it hands in is screened before it is run, then run with no network
and no inherited environment. In a lean stage long output is shortened: test output goes
through the hub's Headroom front end when that is installed, with a plain summary otherwise.

Everything lives under SWARM_HOME/p2 (default ~/.gaie-swarm/p2), outside any repository.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import signal
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import tasks  # noqa: E402
import workload  # noqa: E402

HOME = Path(os.environ.get("SWARM_HOME", Path.home() / ".gaie-swarm")) / "p2"
ID = re.compile(r"[SMLX]-\d{4}")
ATTEMPTS = 3
RAW_CAP, LEAN_CAP = 400000, 4000  # a plain stage shows whole files: its cap must be above the largest file of a project, or part of an answer is hidden
PROJECT_FILE = re.compile(r"(inv|tests|data|logs)(/[A-Za-z0-9_.-]+)?")
FACTS = ("fixed_function", "direct_callers", "failed_event_ids", "build_error_code")


class Refused(Exception):
    pass


def stage() -> Path:
    try:
        return HOME / "work" / (HOME / "current").read_text().strip()
    except OSError:
        raise Refused("no stage is open") from None


def locate(ident: str) -> tuple[Path, Path]:
    if not ID.fullmatch(ident):
        raise Refused(f"{ident!r} is not a task id")
    folder, state = stage() / ident, stage() / ".kit" / f"{ident}.json"
    if not state.exists():
        raise Refused(f"{ident} is not a task of the open stage")
    return folder, state


def load(state: Path) -> dict:
    return json.loads(state.read_text())


def emit(state: Path, verb: str, text: str, view: bool = False) -> None:
    """Print, and count what was printed: the task's own record of what its worker was shown."""
    kit = load(state)
    kit["calls"][verb] = kit["calls"].get(verb, 0) + 1
    kit["chars_out"] += len(text)
    kit["views"] += int(view)
    state.write_text(json.dumps(kit, ensure_ascii=False))
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def inside(folder: Path, name: str) -> Path:
    if not PROJECT_FILE.fullmatch(name):
        raise Refused(f"{name!r} is not a path of this project")
    path = (folder / name).resolve()
    if folder.resolve() not in path.parents or not path.exists():
        raise Refused(f"no such path: {name}")
    return path


def need_large(state: Path, lean: bool = False) -> dict:
    kit = load(state)
    if kit["size"] != "large":
        raise Refused("this command is for large tasks")
    if lean and kit["mode"] != "lean":
        raise Refused("this command is not part of this task's commands")
    return kit


def read_input(limit: int) -> str:
    """Standard input, but never more than one character past LIMIT: a huge input is refused, not held in memory."""
    return sys.stdin.read(limit + 1)


SEARCH_SECONDS = 5


def stopped(signum, frame):
    raise Refused("that search took too long; use a simpler regular expression")


def capped(text: str, limit: int, hint: str) -> str:
    return text if len(text) <= limit else f"{text[:limit]}\n[{len(text) - limit} more characters not shown: {hint}]"


def headroom():
    """The hub's Headroom front end as a module, or None."""
    path = HERE.parents[1] / "skills" / "ultra-context-optimization" / "scripts" / "hr.py"
    try:
        spec = importlib.util.spec_from_file_location("hr", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module if (module.TOOL_HOME / "venv" / "bin" / "python").exists() and module.hub_tool() else None
    except (OSError, AttributeError, ImportError):
        return None


def summary(text: str) -> str:
    """The failing tests and the closing lines of a unittest run, when Headroom is not there to do it."""
    lines = text.splitlines()
    failures = [line for line in lines if re.match(r"(FAIL|ERROR): ", line)]
    detail = [line for line in lines if re.match(r"(AssertionError|[A-Za-z]+Error)\b", line)][:20]
    return "\n".join([*failures, *detail, *[line for line in lines if line.strip()][-3:]])


# ---- commands ---------------------------------------------------------------------------

def show(ident: str) -> None:
    folder, state = locate(ident)
    emit(state, "show", (folder / "TASK.md").read_text(encoding="utf-8"))


def submit(ident: str) -> None:
    folder, state = locate(ident)
    kit = load(state)
    if kit["size"] == "large":
        raise Refused("a large task is handed in with setline and answer")
    if kit["attempts"] >= ATTEMPTS:
        emit(state, "submit", "No attempts are left. Reply FAILED.")
        return
    source = read_input(40000)
    if len(source) > 40000:
        raise Refused("the file is too long")
    kit["attempts"] += 1
    state.write_text(json.dumps(kit, ensure_ascii=False))
    left = ATTEMPTS - kit["attempts"]
    again = f"Attempt {kit['attempts']} of {ATTEMPTS}: correct it and hand it in again." if left else "No attempts are left. Reply FAILED."
    (folder / "solution.py").write_text(source, encoding="utf-8")
    findings = workload.inspect(source)
    if findings:
        emit(state, "submit", f"Not run: {'; '.join(findings[:3])}. Only Python that keeps the task's rules is run. {again}")
        return
    result = tasks.run_suite(folder / "solution.py", kit["examples"])
    if result.get("error"):
        emit(state, "submit", f"The file failed before the examples could run: {result['error']}. {again}")
    elif result["passed"] == result["total"]:
        emit(state, "submit", f"The {result['total']} examples passed. Reply DONE.")
    else:
        first = result["first_failure"]
        call = f"{first['call']}({', '.join(repr(a) for a in first['args'])})"
        emit(state, "submit", f"{result['passed']} of {result['total']} examples passed. First failure, example {first['test']} step {first['step']}: "
                              f"{call} {first['what']}, expected {first['want']!r}. {again}"[:900])


def test(ident: str) -> None:
    folder, state = locate(ident)
    kit = need_large(state)
    done = workload.isolated([sys.executable, "-B", "-s", "-E", "-m", "unittest", "discover", "-s", "tests"], folder, 120)
    text = done.stdout + done.stderr
    if kit["mode"] != "lean":
        emit(state, "test", capped(text, RAW_CAP, "search it with swk grep"))
        return
    if done.returncode == 0:
        emit(state, "test", [line for line in text.splitlines() if line.strip()][-2] + "\nOK: no failure.")
        return
    hr = headroom()
    if hr is not None:
        os.environ["HR_SESSION"] = f"swarm-{stage().name}-{ident}"
        shown, facts = hr.view(text, "List every failing test.", "python3 -m unittest discover -s tests")
        if facts.get("via", "").startswith("headroom"):
            emit(state, "test", capped(shown, LEAN_CAP * 2, "the failures above are what matters"), view=True)
            return
    emit(state, "test", capped(summary(text), LEAN_CAP * 2, "the failures above are what matters"))


def read(ident: str, name: str, span: str = "") -> None:
    folder, state = locate(ident)
    kit = need_large(state)
    lines = inside(folder, name).read_text(encoding="utf-8", errors="replace").splitlines()
    first, _, last = span.partition(":")
    start, end = max(int(first or 1), 1), min(int(last or len(lines)), len(lines))
    text = "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))
    limit = LEAN_CAP if kit["mode"] == "lean" else RAW_CAP
    emit(state, "read", capped(text, limit, "ask for a range of lines, or use swk grep"))


def grep(ident: str, pattern: str, name: str = "") -> None:
    folder, state = locate(ident)
    kit = need_large(state)
    try:
        wanted = re.compile(pattern)
    except re.error as problem:
        raise Refused(f"not a regular expression: {problem}") from None
    root = inside(folder, name) if name else folder
    whole = folder.resolve()
    files = [root] if root.is_file() else sorted(p for sub in ("inv", "tests", "data", "logs") for p in (folder / sub).glob("*") if p.is_file()
                                                 and (root == folder or root in p.parents) and whole in p.resolve().parents)
    hits = []
    signal.signal(signal.SIGALRM, stopped)
    signal.setitimer(signal.ITIMER_REAL, SEARCH_SECONDS)
    try:
        for path in files:
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if wanted.search(line):
                    hits.append(f"{path.relative_to(folder)}:{number}:{line}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    limit = LEAN_CAP if kit["mode"] == "lean" else RAW_CAP
    emit(state, "grep", capped("\n".join(hits) or "no line matches", limit, f"{len(hits)} lines matched; narrow the search"))


def shared_index(state: Path) -> dict:
    return json.loads(state.with_name(state.name.replace(".json", ".index.json")).read_text())


def define(ident: str, name: str) -> None:
    folder, state = locate(ident)
    need_large(state, lean=True)
    where = shared_index(state)["functions"].get(name)
    if where is None:
        raise Refused(f"no function named {name}")
    lines = (folder / "inv" / f"{where['module']}.py").read_text().splitlines()
    emit(state, "def", f"inv/{where['module']}.py\n" + "\n".join(f"{n}: {lines[n - 1]}" for n in range(where["first"], where["last"] + 1)))


def callers(ident: str, name: str) -> None:
    _, state = locate(ident)
    need_large(state, lean=True)
    found = shared_index(state)["callers"].get(name)
    if found is None:
        raise Refused(f"no function named {name}")
    emit(state, "callers", json.dumps(found))


def select(ident: str, name: str, condition: str, out: str) -> None:
    folder, state = locate(ident)
    need_large(state, lean=True)
    field, _, value = condition.partition("=")
    records = json.loads(inside(folder, name).read_text())
    if not isinstance(records, list):
        raise Refused("that file is not a JSON list of records")
    emit(state, "select", json.dumps([r.get(out) for r in records if isinstance(r, dict) and str(r.get(field)) == value])[:LEAN_CAP])


def setline(ident: str, name: str, number: str) -> None:
    folder, state = locate(ident)
    need_large(state)
    if not re.fullmatch(r"inv/m\d+\.py", name):
        raise Refused("only a module of the package may be changed")
    text = read_input(401).rstrip("\n")
    if "\n" in text or len(text) > 400:
        raise Refused("give exactly one line")
    path = inside(folder, name)
    lines = path.read_text().splitlines()
    if not 1 <= int(number) <= len(lines):
        raise Refused(f"{name} has {len(lines)} lines")
    lines[int(number) - 1] = text
    source = "\n".join(lines) + "\n"
    try:
        ast.parse(source)
    except SyntaxError as problem:
        raise Refused(f"that would not be Python: {problem.msg}") from None
    path.write_text(source)
    emit(state, "setline", f"{name} line {number} is now: {text}")


def answer(ident: str) -> None:
    folder, state = locate(ident)
    need_large(state)
    try:
        given = json.loads(read_input(20000))
    except ValueError:
        raise Refused("that is not JSON") from None
    if not isinstance(given, dict) or sorted(given) != sorted(FACTS):
        raise Refused(f"give one object with exactly these keys: {', '.join(FACTS)}")
    for key in ("direct_callers", "failed_event_ids"):  # the order of a list is not part of the answer
        if isinstance(given[key], list):
            given[key] = sorted(given[key], key=lambda item: (str(type(item)), item))
    (folder / "ANSWER.json").write_text(json.dumps(given))
    emit(state, "answer", "The answer is recorded. If swk test reports no failure, reply DONE.")


VERBS = {"show": (show, 1, 1), "submit": (submit, 1, 1), "test": (test, 1, 1), "read": (read, 2, 3), "grep": (grep, 2, 3), "def": (define, 2, 2),
         "callers": (callers, 2, 2), "select": (select, 4, 4), "setline": (setline, 3, 3), "answer": (answer, 1, 1)}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv == ["status"]:
            print(f"swk is ready: stage {stage().name} is open")
            return 0
        if not argv or argv[0] not in VERBS:
            raise Refused("unknown command; the task lists the commands that run")
        call, least, most = VERBS[argv[0]]
        if not least <= len(argv) - 1 <= most:
            raise Refused(f"swk {argv[0]} takes {least}{'' if least == most else f' to {most}'} arguments")
        call(*argv[1:])
    except Refused as problem:
        print(f"swk: refused: {problem}")
        return 2
    except (OSError, ValueError, KeyError) as problem:
        print(f"swk: refused: {type(problem).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
