# Contract for the second round of the third phase

Everyone building a part in this round reads this once. It is all the shared context
there is: do not explore the repository beyond this page, your own brief and the files your
brief names.

## What this round is for

The second phase ran real workers and found five faults: the gate in front of a worker's
shell was not enforced by the host, workers made calls outside their contract, one agent
used a tool that reaches another session, the evidence did not name every tool call, and
two large tasks failed because their data was cut off. Those are repaired on this branch:
a gate for the whole session that refuses by default (`hook.py`), a ledger of every call
(`ledger.py`), and a run that opens with a security gate stage (`stage3.py`).

This round attacks and closes what is left before 1,000 real workers run, and builds what
the end of the experiment needs: the capacity study, the checks, the report and the freeze.
The owner's order is security first, fail closed, least privilege. A control that cannot be
enforced is reported, never worked around.

## Rules for every lane

- Work only inside your own worktree, and change only the paths your brief says you own.
- New code goes in `swarm/phase3/`, its tests in `tests/test_p3_*.py`.
- Python 3.11 or later, standard library only. No new dependency, no network, no download.
- A script starts with a docstring that says what it does and how to call it, in plain
  words.
- Tests use `unittest`, start no agent and no model, need no network, write only under a
  temporary folder, and finish in under 30 seconds for your file.
- Private working files go under `SWARM_HOME/p3`, never in the repository. Nothing you
  commit may hold a path outside the repository, a session id, a model identifier, record
  content or an environment value.
- A number is either measured, and then says from what, or it is labelled a simulation or
  an estimate. Never write a number you did not compute.
- If you find a fault in a file you do not own, do not change that file. Prove it with a
  test in your own test file marked `@unittest.expectedFailure`, with one comment line that
  says what is wrong and where, and list it in your findings file if you have one.
- Do not use `git push`, `git checkout`, `git merge`, the network or a package manager.
- Stay small: about thirty tool calls. If you are blocked, say so; do not guess.
- Your final answer is one line: `DONE` and what was added, or `BLOCKED` and why.

## What already exists, and how to reach it

From a script in `swarm/phase3/`:

```python
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]
```

- `hook` (the session gate): `decide(call: dict) -> (verdict, why)` with verdict `pass`
  (the orchestrator), `allow` or `refuse`; `wrapper(settings: str) -> str`, the installed
  program, which turns every ending except "allowed" into a refusal; `selftest(installed)
  -> list[str]`; `CASES`; `record(call, verdict) -> bool`; its record is
  `SWARM_HOME/p3/hook.jsonl`, one JSON line per judged call with `t`, `tool`, `agent`,
  `verdict`, `who`, `fields`.
- `guard.allowed(command) -> bool` (second phase): the shape a worker's shell call must have.
- `lane_guard.allowed(call) -> (bool, why)`: what a development agent may do.
- `ledger`: `calls(path) -> list[dict]` reads one agent record; `agent_type(path)`;
  `build(paths, gate_lines=None) -> dict` with `by_class`, `by_tool`,
  `calls_outside_the_contract_that_ran`, `clean`, and `gate.reconciled`;
  `gate_log(path, start=None, end=None)`.
- `stage3` (the run): `setup`, `prep`, `finish`, `status`, `report`; `decide`, `card`,
  `carried_over`, `judge_gate`. It drives the second phase's `stage` module with this
  phase's plan `PLAN3.json`. Evidence: `swarm/phase3/evidence/stages.json`.
- `tests/fixtures/p3-stand-in-stages.json`: a document of exactly the shape the run
  writes, with a gate stage `g0` and a queue stage `q4`. It was made by stand-ins in a
  test. It holds no measurement and must never be quoted as a result.
- `taskqueue`: `create(stage_dir, task_ids, batch)`, `claim(stage_dir, worker, now=None) ->
  id | None`, `release(stage_dir, id, worker, outcome)`, `reclaim`, `holder(stage_dir, id)`,
  `status(stage_dir)`. Its files are under `stage_dir/.queue/`.
- `kit3` (the queue worker's command `swk`): `next [WORKER]` and `submit ID`; every other
  verb goes to the second phase's `kit` (`show`, `status`, `test`, `read`, `grep`, `def`,
  `callers`, `select`, `setline`, `answer`). As a subprocess:
  `[sys.executable, "-I", "swarm/phase3/kit3.py", VERB, ...]` with `SWARM_HOME` in the
  environment. The open stage is named in `SWARM_HOME/p3/current`; its tasks are in
  `SWARM_HOME/p3/work/STAGE/ID/`, the withheld tests in `work/STAGE/.hidden/ID.json`, the
  worker kit in `work/STAGE/.kit/ID.json`.
- `tasks` (second phase): `tasks.make(out, size, first, count, mode="lean", seed=tasks.SEED)`
  writes tasks (`"small"`, `"medium"`, `"large"`) into `out` and returns their dicts (`id`,
  `text`, `suite`, `examples`, and for medium `reference`, a solution that passes);
  `tasks.medium(number, seed)` gives one; `tasks.run_suite(solution_path, suite)`;
  `tasks.check(out)`.
- `workload` (first phase, `swarm/workload.py`): `isolated(command, cwd=None, timeout=20)`
  runs worker-written code with no network and no inherited environment, as the same
  user; `inspect(source)` screens it.
- `cage`: `run(command, cwd=None, timeout=20, memory_mb=512, cpu_seconds=10, ...)` with
  limits, no network, and another user when the caller is root; `workspace(files)`,
  `remove(folder)`.
- `schema.validate(document) -> list[str]`, `stats.summary(document)`,
  `economics.per_task(document)`, `simulate.run(agents, tasks, batch, host_concurrency,
  service, seed, overhead=0.0, failure=0.0)`, `loadtest.run(tasks, workers, home)`,
  `handover.write(root)`.
- Evidence already in the repository: `swarm/evidence/summary.json` and `ladder.json`
  (first phase), `swarm/phase2/evidence/stages.json` (second phase, 21 stages),
  `swarm/phase3/evidence/team.json` and `gate.json`.

Another lane is adding hand-in tickets in this round: `swk next` will print a line
`ticket TICKET` after `worker NAME`, and in a stage that has a queue the hand-in becomes
`swk submit ID TICKET <<'PY'`. A test of yours that hands in a task from a queue must read
the ticket from the output of `swk next` when the line is there and use it, as
`work_the_queue` in `tests/test_p3_gate.py` does, so that it passes before and after.

An agent record is a JSONL file. Lines of type `assistant` carry `message.id`,
`message.model`, `message.usage` and `message.content` blocks (`text`, or `tool_use` with
`id`, `name` and `input`). Lines of type `user` carry the prompt or `tool_result` blocks
(`tool_use_id`, `content`, `is_error`). One reply may be written on several lines with the
same `message.id`. Beside it lies `agent-ID.meta.json` with `agentType`.

## What the host does, as measured

- It runs at most 20 agents at once.
- It does not run a gate written in an agent's own definition. It runs the gate set in
  `.claude/settings.json` before every tool call of every agent and tells it `agent_type`
  and `agent_id`; the orchestrator's calls carry neither.
- It lets a call run when the gate ends with any status other than 2.
