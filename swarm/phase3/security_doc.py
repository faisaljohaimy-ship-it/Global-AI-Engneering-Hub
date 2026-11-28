#!/usr/bin/env python3
"""The experiment's threat model as a table in code, and the document made from it.

    python3 swarm/phase3/security_doc.py            check the table against the files and the tests; print the problems
    python3 swarm/phase3/security_doc.py --write    write swarm/phase3/SECURITY.md from the table

Each row says who might try what, which control stops it (a file and a function), which
tests prove it (as tests/FILE.py::Class.test_name), and what is left open. `check()` reads
the test files and the control files with `ast`: a cited test or function that does not
exist is reported, and so is a SECURITY.md that differs from `render()`. A row marked
"open" is a thing that is not controlled; it may claim no test as proof.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DOC = HERE / "SECURITY.md"

G = "tests/test_p3_gate.py::DecisionTests."
F = "tests/test_p3_gate_fuzz.py::"
C = "tests/test_p3_cage.py::CageTest."
T = "tests/test_p3_team.py::NetTests."
HOOK = ("swarm/phase3/hook.py", "decide")
GUARD = ("swarm/phase2/guard.py", "allowed")
LANE = ("swarm/phase3/lane_guard.py", "allowed")
CAGE = ("swarm/phase3/cage.py", "run")

WORKER, CODE, DEV, UNKNOWN, ORCH = ("a worker", "code a worker wrote", "a development agent", "an agent of an unknown type", "the orchestrator")

ROWS = [
    {"id": "W1", "who": WORKER, "tries": "runs a second shell command (chains, substitutes, redirects, or runs its own program)",
     "controls": [HOOK, GUARD], "status": "held",
     "tests": [G + "test_the_orchestrator_passes_and_every_agent_is_judged", F + "GateFuzz.test_generated_commands_match_the_scanner", F + "GateFuzz.test_hand_made_cases"],
     "left_open": "The shape is checked by a pattern; the fuzz test compares it with a scanner, which is evidence and not proof."},
    {"id": "W2", "who": WORKER, "tries": "uses a file tool (Read, Write, Edit, Grep, Glob)",
     "controls": [HOOK], "status": "held",
     "tests": [G + "test_the_orchestrator_passes_and_every_agent_is_judged", G + "test_no_worker_definition_of_the_run_has_a_tool_that_reaches_sessions"],
     "left_open": "Nothing known. The gate stage of PLAN3.json (probes of swarm-probe-wide) checks it with real agents when the run starts."},
    {"id": "W3", "who": WORKER, "tries": "uses a tool that reaches another session (send message, a remote-session tool, a repository-push tool)",
     "controls": [HOOK], "status": "held",
     "tests": [G + "test_the_orchestrator_passes_and_every_agent_is_judged", G + "test_no_worker_definition_of_the_run_has_a_tool_that_reaches_sessions"],
     "left_open": "Only agent types named swarm-light, swarm-queue, swarm-large and swarm-probe are workers; every other type falls under U1."},
    {"id": "W4", "who": WORKER, "tries": "starts an agent of its own",
     "controls": [HOOK], "status": "held",
     "tests": [G + "test_the_orchestrator_passes_and_every_agent_is_judged"],
     "left_open": "Nothing known."},
    {"id": "W5", "who": WORKER, "tries": "reaches a task, a file or a symlink outside its own task through a kit verb",
     "controls": [("swarm/phase2/kit.py", "inside"), ("swarm/phase2/kit.py", "read_input")], "status": "held",
     "tests": [F + "KitAttack.test_ids_and_paths_that_leave_the_folder_are_refused", F + "KitAttack.test_a_task_of_another_size_or_stage_is_not_reachable",
               F + "KitAttack.test_symlink_is_refused_by_read_setline_and_grep_with_a_path", F + "KitAttack.test_a_symlinked_folder_is_refused",
               F + "KitAttack.test_over_long_input_is_refused", F + "KitAttack.test_grep_regex_cannot_run_for_minutes"],
     "left_open": "A worker can still read everything the kit shows for its own task, including the whole events file of a plain stage (see tests/test_p3_gate.py::RawReachTests)."},
    {"id": "W6", "who": WORKER, "tries": "makes a call that is not one of its tools and hopes nobody counts it",
     "controls": [("swarm/phase3/ledger.py", "build"), ("swarm/phase3/hook.py", "record")], "status": "held",
     "tests": ["tests/test_p3_gate.py::LedgerTests.test_every_call_is_named_and_put_in_one_class",
               "tests/test_p3_gate.py::LedgerTests.test_a_gate_that_saw_fewer_calls_than_the_records_hold_is_not_reconciled",
               "tests/test_p3_gate.py::RunTests.test_a_workers_foreign_call_that_ran_ends_the_run",
               "tests/test_p3_gate.py::RunTests.test_one_forbidden_thing_that_runs_ends_everything"],
     "left_open": "This detects after the fact and ends the run; it does not prevent."},
    {"id": "G1", "who": WORKER, "tries": "makes a call the gate cannot read (not JSON, not an object, a command that is not text)",
     "controls": [HOOK, ("swarm/phase3/hook.py", "main")], "status": "held",
     "tests": [G + "test_what_the_gate_does_not_know_it_refuses", G + "test_as_a_program_it_refuses_what_it_cannot_read_and_keeps_counts_only",
               F + "GateFuzz.test_main_refuses_anything_that_is_not_a_bash_call"],
     "left_open": "Nothing known."},
    {"id": "G2", "who": WORKER, "tries": "makes the gate crash so that the host lets the call run (the host lets a call run on any status but 2)",
     "controls": [("swarm/phase3/hook.py", "wrapper")], "status": "held",
     "tests": [G + "test_the_installed_gate_refuses_when_the_gate_crashes_or_cannot_record"],
     "left_open": "Held only for the installed wrapper. Not measured: what the host does when the gate runs out of time."},
    {"id": "G3", "who": WORKER, "tries": "makes a call that cannot be written to the record",
     "controls": [("swarm/phase3/hook.py", "record"), ("swarm/phase3/hook.py", "main")], "status": "held",
     "tests": [G + "test_the_installed_gate_refuses_when_the_gate_crashes_or_cannot_record",
               G + "test_as_a_program_it_refuses_what_it_cannot_read_and_keeps_counts_only"],
     "left_open": "Only a call that would be allowed is stopped for want of a record; a refused call is refused whether or not the line was written."},
    {"id": "G4", "who": WORKER, "tries": "runs while the gate is not installed or the settings entry is absent",
     "controls": [("swarm/phase3/hook.py", "selftest"), ("swarm/phase3/stage3.py", "setup")], "status": "held",
     "tests": [G + "test_the_settings_entry_covers_every_tool_and_does_nothing_until_the_gate_is_installed", G + "test_the_self_test_holds_and_notices_a_gate_that_lets_things_through",
               "tests/test_p3_gate.py::RunTests.test_no_stage_is_opened_when_the_installed_gate_is_gone"],
     "left_open": "A gate that is not installed does nothing, by design, so that ordinary sessions in this repository work. The run refuses to open a stage without it; nothing else does."},
    {"id": "U1", "who": UNKNOWN, "tries": "uses any tool, or has an id and no type",
     "controls": [HOOK], "status": "held",
     "tests": [G + "test_what_the_gate_does_not_know_it_refuses"],
     "left_open": "Refusal is by default: a new agent type is refused until the gate is changed to know it."},
    {"id": "X1", "who": CODE, "tries": "reads secrets (the environment, files of the caller)",
     "controls": [CAGE], "status": "held",
     "tests": [C + "test_stdin_closed_and_env_empty"],
     "left_open": "The code runs with an empty environment, but it can read any file its user can read. As the unprivileged user it cannot read private folders; when the caller is not root nothing is dropped, so it runs as the caller."},
    {"id": "X2", "who": CODE, "tries": "writes outside its scratch folder, or a very large file",
     "controls": [CAGE], "status": "held",
     "tests": [C + "test_cannot_write_outside", C + "test_file_size_limit"],
     "left_open": "Writing outside is stopped by the privilege drop, so it is tested only when the caller is root; otherwise that test is skipped."},
    {"id": "X3", "who": CODE, "tries": "uses the network",
     "controls": [("swarm/phase3/cage.py", "network_wall"), CAGE], "status": "held",
     "tests": [C + "test_no_network"],
     "left_open": "Where a network namespace cannot be built the wall is absent and that test is skipped."},
    {"id": "X4", "who": CODE, "tries": "outlives its time limit, spins, takes memory or forks without end",
     "controls": [CAGE], "status": "held",
     "tests": [C + "test_timeout_kills_group", C + "test_cpu_limit_before_timeout", C + "test_memory_limit", C + "test_fork_loop_contained"],
     "left_open": "The process limit applies only when the caller is root."},
    {"id": "D1", "who": DEV, "tries": "writes outside its lane's worktree",
     "controls": [LANE], "status": "held",
     "tests": [T + "test_a_development_agent_writes_only_inside_the_lanes", G + "test_a_development_agent_is_held_by_the_lane_net"],
     "left_open": "The net does not know which lane calls, so it cannot keep one lane out of another. The control that counts is the join, which rejects a lane that changed a path it does not own (tests/test_p3_team.py::JoinTests)."},
    {"id": "D2", "who": DEV, "tries": "pushes, fetches, switches branch, installs, or uses the network from the shell",
     "controls": [LANE], "status": "held",
     "tests": [T + "test_the_shell_may_test_and_commit_and_may_not_push_fetch_switch_or_install", G + "test_a_development_agent_is_held_by_the_lane_net"],
     "left_open": "The net is a list of refused commands and not a sandbox. A shell can be made to do what a pattern did not foresee."},
    {"id": "D3", "who": DEV, "tries": "reads outside the repository and the lanes, the environment, or the host's private folders",
     "controls": [LANE], "status": "held",
     "tests": [G + "test_a_development_agent_is_held_by_the_lane_net", T + "test_the_net_refuses_what_it_cannot_read"],
     "left_open": "The shell is refused by pattern only; a read through a command the pattern does not name is not stopped."},
    {"id": "O1", "who": ORCH, "tries": "anything: the gate lets the orchestrator through",
     "controls": [HOOK], "status": "open", "tests": [],
     "left_open": "The orchestrator is not confined by the gate. It starts the agents, and the host reports it with no agent type and no agent id."},
    {"id": "O2", "who": "any session", "tries": "what the host does when the gate runs out of time",
     "controls": [], "status": "open", "tests": [],
     "left_open": "Not measured. The wrapper turns every ending of the gate's program into a refusal, but a timeout is the host's ending, not the program's."},
]


def _tests(path: Path) -> set[str]:
    found = set()
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            found.update(f"{node.name}.{item.name}" for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return found


def _has_function(path: Path, name: str) -> bool:
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name for node in ast.walk(ast.parse(path.read_text())))


def render() -> str:
    out = ["# Threat model of the experiment", "",
           "Made by `swarm/phase3/security_doc.py` from its table; do not edit by hand. `python3 swarm/phase3/security_doc.py --write` rewrites it and a test fails when it differs.", ""]
    for row in ROWS:
        out += [f"## {row['id']}: {row['who']}: {row['tries']}", "", f"Status: {row['status']}", ""]
        out.append("Control: " + ("; ".join(f"`{f}` `{n}`" for f, n in row["controls"]) if row["controls"] else "none"))
        out += ["", "Tests:"]
        out += [f"- `{t}`" for t in row["tests"]] if row["tests"] else ["- none: this is not controlled"]
        out += ["", f"Left open: {row['left_open']}", ""]
    out += ["## Not controlled, in plain words", "",
            "- The orchestrator is not confined by the gate.",
            "- A gate that is not installed does nothing, by design, so that ordinary sessions in this repository work.",
            "- The lane net for development agents is a list of refused commands and not a sandbox.",
            "- What the host does when the gate runs out of time was not measured.", ""]
    return "\n".join(out)


def check() -> list[str]:
    problems, cache = [], {}
    seen = set()
    for row in ROWS:
        if row["id"] in seen:
            problems.append(f"{row['id']}: the id is used twice")
        seen.add(row["id"])
        if row["status"] not in ("held", "open"):
            problems.append(f"{row['id']}: status {row['status']!r} is neither held nor open")
        if row["status"] == "open" and row["tests"]:
            problems.append(f"{row['id']}: a row marked open claims tests as proof")
        if row["status"] == "held" and not row["tests"]:
            problems.append(f"{row['id']}: a row marked held names no test")
        for file, function in row["controls"]:
            path = ROOT / file
            if not path.is_file():
                problems.append(f"{row['id']}: control file {file} does not exist")
            elif not _has_function(path, function):
                problems.append(f"{row['id']}: {file} has no function {function}")
        for cited in row["tests"]:
            file, _, name = cited.partition("::")
            path = ROOT / file
            if not path.is_file():
                problems.append(f"{row['id']}: test file {file} does not exist")
                continue
            cache.setdefault(file, _tests(path))
            if name not in cache[file]:
                problems.append(f"{row['id']}: {cited} does not exist")
    if not DOC.is_file() or DOC.read_text() != render():
        problems.append("swarm/phase3/SECURITY.md differs from render()")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--write" in args:
        DOC.write_text(render())
    problems = check()
    print("\n".join(problems) if problems else "the threat model matches the files and the tests")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
