# Threat model of the experiment

Made by `swarm/phase3/security_doc.py` from its table; do not edit by hand. `python3 swarm/phase3/security_doc.py --write` rewrites it and a test fails when it differs.

## W1: a worker: runs a second shell command (chains, substitutes, redirects, or runs its own program)

Status: held

Control: `swarm/phase3/hook.py` `decide`; `swarm/phase2/guard.py` `allowed`

Tests:
- `tests/test_p3_gate.py::DecisionTests.test_the_orchestrator_passes_and_every_agent_is_judged`
- `tests/test_p3_gate_fuzz.py::GateFuzz.test_generated_commands_match_the_scanner`
- `tests/test_p3_gate_fuzz.py::GateFuzz.test_hand_made_cases`

Left open: The shape is checked by a pattern; the fuzz test compares it with a scanner, which is evidence and not proof.

## W2: a worker: uses a file tool (Read, Write, Edit, Grep, Glob)

Status: held

Control: `swarm/phase3/hook.py` `decide`

Tests:
- `tests/test_p3_gate.py::DecisionTests.test_the_orchestrator_passes_and_every_agent_is_judged`
- `tests/test_p3_gate.py::DecisionTests.test_no_worker_definition_of_the_run_has_a_tool_that_reaches_sessions`

Left open: Nothing known. The gate stage of PLAN3.json (probes of swarm-probe-wide) checks it with real agents when the run starts.

## W3: a worker: uses a tool that reaches another session (send message, a remote-session tool, a repository-push tool)

Status: held

Control: `swarm/phase3/hook.py` `decide`

Tests:
- `tests/test_p3_gate.py::DecisionTests.test_the_orchestrator_passes_and_every_agent_is_judged`
- `tests/test_p3_gate.py::DecisionTests.test_no_worker_definition_of_the_run_has_a_tool_that_reaches_sessions`

Left open: Only agent types named swarm-light, swarm-queue, swarm-large and swarm-probe are workers; every other type falls under U1.

## W4: a worker: starts an agent of its own

Status: held

Control: `swarm/phase3/hook.py` `decide`

Tests:
- `tests/test_p3_gate.py::DecisionTests.test_the_orchestrator_passes_and_every_agent_is_judged`

Left open: Nothing known.

## W5: a worker: reaches a task, a file or a symlink outside its own task through a kit verb

Status: held

Control: `swarm/phase2/kit.py` `inside`; `swarm/phase2/kit.py` `read_input`

Tests:
- `tests/test_p3_gate_fuzz.py::KitAttack.test_ids_and_paths_that_leave_the_folder_are_refused`
- `tests/test_p3_gate_fuzz.py::KitAttack.test_a_task_of_another_size_or_stage_is_not_reachable`
- `tests/test_p3_gate_fuzz.py::KitAttack.test_symlink_is_refused_by_read_setline_and_grep_with_a_path`
- `tests/test_p3_gate_fuzz.py::KitAttack.test_a_symlinked_folder_is_refused`
- `tests/test_p3_gate_fuzz.py::KitAttack.test_over_long_input_is_refused`
- `tests/test_p3_gate_fuzz.py::KitAttack.test_grep_regex_cannot_run_for_minutes`

Left open: A worker can still read everything the kit shows for its own task, including the whole events file of a plain stage (see tests/test_p3_gate.py::RawReachTests).

## W6: a worker: makes a call that is not one of its tools and hopes nobody counts it

Status: held

Control: `swarm/phase3/ledger.py` `build`; `swarm/phase3/hook.py` `record`

Tests:
- `tests/test_p3_gate.py::LedgerTests.test_every_call_is_named_and_put_in_one_class`
- `tests/test_p3_gate.py::LedgerTests.test_a_gate_that_saw_fewer_calls_than_the_records_hold_is_not_reconciled`
- `tests/test_p3_gate.py::RunTests.test_a_workers_foreign_call_that_ran_ends_the_run`
- `tests/test_p3_gate.py::RunTests.test_one_forbidden_thing_that_runs_ends_everything`

Left open: This detects after the fact and ends the run; it does not prevent.

## G1: a worker: makes a call the gate cannot read (not JSON, not an object, a command that is not text)

Status: held

Control: `swarm/phase3/hook.py` `decide`; `swarm/phase3/hook.py` `main`

Tests:
- `tests/test_p3_gate.py::DecisionTests.test_what_the_gate_does_not_know_it_refuses`
- `tests/test_p3_gate.py::DecisionTests.test_as_a_program_it_refuses_what_it_cannot_read_and_keeps_counts_only`
- `tests/test_p3_gate_fuzz.py::GateFuzz.test_main_refuses_anything_that_is_not_a_bash_call`

Left open: Nothing known.

## G2: a worker: makes the gate crash so that the host lets the call run (the host lets a call run on any status but 2)

Status: held

Control: `swarm/phase3/hook.py` `wrapper`

Tests:
- `tests/test_p3_gate.py::DecisionTests.test_the_installed_gate_refuses_when_the_gate_crashes_or_cannot_record`

Left open: Held only for the installed wrapper. Not measured: what the host does when the gate runs out of time.

## G3: a worker: makes a call that cannot be written to the record

Status: held

Control: `swarm/phase3/hook.py` `record`; `swarm/phase3/hook.py` `main`

Tests:
- `tests/test_p3_gate.py::DecisionTests.test_the_installed_gate_refuses_when_the_gate_crashes_or_cannot_record`
- `tests/test_p3_gate.py::DecisionTests.test_as_a_program_it_refuses_what_it_cannot_read_and_keeps_counts_only`

Left open: Only a call that would be allowed is stopped for want of a record; a refused call is refused whether or not the line was written.

## G4: a worker: runs while the gate is not installed or the settings entry is absent

Status: held

Control: `swarm/phase3/hook.py` `selftest`; `swarm/phase3/stage3.py` `setup`

Tests:
- `tests/test_p3_gate.py::DecisionTests.test_the_settings_entry_covers_every_tool_and_does_nothing_until_the_gate_is_installed`
- `tests/test_p3_gate.py::DecisionTests.test_the_self_test_holds_and_notices_a_gate_that_lets_things_through`
- `tests/test_p3_gate.py::RunTests.test_no_stage_is_opened_when_the_installed_gate_is_gone`

Left open: A gate that is not installed does nothing, by design, so that ordinary sessions in this repository work. The run refuses to open a stage without it; nothing else does.

## U1: an agent of an unknown type: uses any tool, or has an id and no type

Status: held

Control: `swarm/phase3/hook.py` `decide`

Tests:
- `tests/test_p3_gate.py::DecisionTests.test_what_the_gate_does_not_know_it_refuses`

Left open: Refusal is by default: a new agent type is refused until the gate is changed to know it.

## X1: code a worker wrote: reads secrets (the environment, files of the caller)

Status: held

Control: `swarm/phase3/cage.py` `run`

Tests:
- `tests/test_p3_cage.py::CageTest.test_stdin_closed_and_env_empty`

Left open: The code runs with an empty environment, but it can read any file its user can read. As the unprivileged user it cannot read private folders; when the caller is not root nothing is dropped, so it runs as the caller.

## X2: code a worker wrote: writes outside its scratch folder, or a very large file

Status: held

Control: `swarm/phase3/cage.py` `run`

Tests:
- `tests/test_p3_cage.py::CageTest.test_cannot_write_outside`
- `tests/test_p3_cage.py::CageTest.test_file_size_limit`

Left open: Writing outside is stopped by the privilege drop, so it is tested only when the caller is root; otherwise that test is skipped.

## X3: code a worker wrote: uses the network

Status: held

Control: `swarm/phase3/cage.py` `network_wall`; `swarm/phase3/cage.py` `run`

Tests:
- `tests/test_p3_cage.py::CageTest.test_no_network`

Left open: Where a network namespace cannot be built the wall is absent and that test is skipped.

## X4: code a worker wrote: outlives its time limit, spins, takes memory or forks without end

Status: held

Control: `swarm/phase3/cage.py` `run`

Tests:
- `tests/test_p3_cage.py::CageTest.test_timeout_kills_group`
- `tests/test_p3_cage.py::CageTest.test_cpu_limit_before_timeout`
- `tests/test_p3_cage.py::CageTest.test_memory_limit`
- `tests/test_p3_cage.py::CageTest.test_fork_loop_contained`

Left open: The process limit applies only when the caller is root.

## D1: a development agent: writes outside its lane's worktree

Status: held

Control: `swarm/phase3/lane_guard.py` `allowed`

Tests:
- `tests/test_p3_team.py::NetTests.test_a_development_agent_writes_only_inside_the_lanes`
- `tests/test_p3_gate.py::DecisionTests.test_a_development_agent_is_held_by_the_lane_net`

Left open: The net does not know which lane calls, so it cannot keep one lane out of another. The control that counts is the join, which rejects a lane that changed a path it does not own (tests/test_p3_team.py::JoinTests).

## D2: a development agent: pushes, fetches, switches branch, installs, or uses the network from the shell

Status: held

Control: `swarm/phase3/lane_guard.py` `allowed`

Tests:
- `tests/test_p3_team.py::NetTests.test_the_shell_may_test_and_commit_and_may_not_push_fetch_switch_or_install`
- `tests/test_p3_gate.py::DecisionTests.test_a_development_agent_is_held_by_the_lane_net`

Left open: The net is a list of refused commands and not a sandbox. A shell can be made to do what a pattern did not foresee.

## D3: a development agent: reads outside the repository and the lanes, the environment, or the host's private folders

Status: held

Control: `swarm/phase3/lane_guard.py` `allowed`

Tests:
- `tests/test_p3_gate.py::DecisionTests.test_a_development_agent_is_held_by_the_lane_net`
- `tests/test_p3_team.py::NetTests.test_the_net_refuses_what_it_cannot_read`

Left open: The shell is refused by pattern only; a read through a command the pattern does not name is not stopped.

## O1: the orchestrator: anything: the gate lets the orchestrator through

Status: open

Control: `swarm/phase3/hook.py` `decide`

Tests:
- none: this is not controlled

Left open: The orchestrator is not confined by the gate. It starts the agents, and the host reports it with no agent type and no agent id.

## O2: any session: what the host does when the gate runs out of time

Status: open

Control: none

Tests:
- none: this is not controlled

Left open: Not measured. The wrapper turns every ending of the gate's program into a refusal, but a timeout is the host's ending, not the program's.

## Not controlled, in plain words

- The orchestrator is not confined by the gate.
- A gate that is not installed does nothing, by design, so that ordinary sessions in this repository work.
- The lane net for development agents is a list of refused commands and not a sandbox.
- What the host does when the gate runs out of time was not measured.
