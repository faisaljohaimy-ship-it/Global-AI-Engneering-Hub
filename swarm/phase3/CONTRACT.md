# Contract for the third phase

Everyone building a part of the third phase reads this once. It is all the shared context
there is: do not explore the repository beyond this page, your own brief and the files your
brief names.

## What is being built

The second phase ran lean workers, one task each, up to 100 at once. The third phase scales
that to 1,000 workers with three additions: a **queue** that workers draw tasks from, so
every worker gets the same prompt and may do a batch of tasks; **adaptive waves**, where the
size of the next wave follows what the last one measured; and **hardening**, so a thousand
pieces of worker-written code can be run safely. Each lane builds one part. The parts are
joined afterwards by the orchestrator, not by you.

## Rules for every lane

- Work only inside your own worktree, and change only the paths your brief says you own.
  A lane that changes any other path is rejected whole when the lanes are joined.
- New code goes in `swarm/phase3/`, its tests in `tests/test_p3_*.py`. Files of the first
  and second phase are read-only, unless your brief names one as yours.
- Python 3.11 or later, standard library only. No new dependency, no network, no download.
- A script starts with a docstring that says what it does and how to call it, in plain
  words, and has a `main()` behind `if __name__ == "__main__"`.
- Tests use `unittest`, start no agent and no model, need no network, write only under a
  temporary folder, and finish in under 60 seconds. Run yours before you commit:
  `python3 -m unittest tests.test_p3_NAME` from the root of your worktree.
- Private working files go under `SWARM_HOME/p3` (default `~/.gaie-swarm/p3`), never in the
  repository. Nothing that is written into the repository may hold an absolute path, a
  session id, a record's content or a model identifier.
- A number is either measured, and then says from what, or it is labelled as a simulation
  or an assumption. Never fill a gap with a guess: use `None` when an input is missing.
- Do not use `git push`, `git checkout`, `git merge`, the network or a package manager.
  Commit in your worktree only: `git -C WORKTREE add -A` then
  `git -C WORKTREE commit -q -m "Lane ID: what it adds"`.
- Stay small: one module, its tests, at most about thirty tool calls. If you are blocked,
  say so and stop; do not widen your lane.
- Your final answer is one line: `DONE` and what was added, or `BLOCKED` and why.

## What already exists, and how to reach it

From a script in `swarm/phase3/`:

```python
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "phase2"), str(HERE.parent)]
```

- `tasks` (second phase): `tasks.make(out, size, first, count, mode="lean", seed=tasks.SEED)`
  writes tasks of size `"small"`, `"medium"` or `"large"` into `out` and returns their
  dicts (`id`, `size`, `family`, `text`, `suite`, `examples`, and for medium `reference`,
  a solution that passes). `tasks.check(out)` runs the withheld tests and returns counts
  and `rows`. `tasks.run_suite(solution_path, suite)` runs one file against one suite.
  `tasks.RULES` is the rules paragraph every task text carries.
- `kit` (second phase): the worker's command `swk`. As a subprocess:
  `[sys.executable, "-I", "swarm/phase2/kit.py", VERB, ...]` with `SWARM_HOME` in the
  environment; it looks for the open stage in `SWARM_HOME/p2/current` and its tasks in
  `SWARM_HOME/p2/work/STAGE/`.
- `guard` (second phase): `guard.allowed(command) -> bool`, the gate in front of a
  worker's shell.
- `stage` (second phase): `stage.locate()` gives the session's record and the folder of
  agents' records; `stage.records(folder)`; `stage.extra(path)` reads one record;
  `stage.cost_units(row)`; `stage.decide(stages, spec)`. Evidence is written by
  `stage.save()` and each stage's fields by `stage.finish()`.
- `measure` (first phase): `measure.read(path)` sums one agent record;
  `measure.peak(rows)` is the largest number of agents active at once.
- `workload` (first phase): `workload.inspect(source)` screens worker-written code;
  `workload.isolated(command, cwd, timeout)` runs it with no network and no inherited
  environment.
- `taskqueue` (third phase, already here): `create(stage_dir, task_ids, batch)`,
  `claim(stage_dir, worker) -> id | None`, `release(stage_dir, id, worker, outcome)` with
  outcome `"handed-in"` or `"failed"`, `holder(stage_dir, id)`, `status(stage_dir)`.
  These signatures are fixed. Only lane E1 changes this file.

An agent record is a JSONL file. Lines of type `assistant` carry `message.id`,
`message.model`, `message.usage` (`input_tokens`, `cache_creation_input_tokens`,
`cache_read_input_tokens`, `output_tokens`, and sometimes `cache_creation` split into
`ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`) and `message.content` blocks
(`text`, or `tool_use` with `name` and `input`). Lines of type `user` carry the prompt or
`tool_result` blocks. Every line has a `timestamp` in ISO form. One reply may be written on
several lines with the same `message.id`: count its usage once.

## Signatures other lanes rely on

Keep these exactly, so the parts fit when they are joined:

| Lane | Module | Must offer |
|---|---|---|
| A1 | `schema.py` | `validate(document: dict) -> list[str]` |
| A2 | `registry.py` | `slots() -> list[dict]`, `assign(tasks: list[dict], slots: list[dict]) -> dict` |
| A3 | `resume.py` | `position(evidence: dict, plan: dict) -> dict`, `rebuild(evidence_file, results_file) -> bool` |
| C1 | `cache_report.py` | `report(paths: list[Path], weights: dict) -> dict` |
| C2 | `context_budget.py` | `budget(root: Path) -> dict`, `check(root: Path, limits: dict) -> list[str]` |
| C3 | `trace.py` | `run(out: Path, count: int) -> dict` |
| C4 | `compact.py` | `render(text: str, first: bool) -> str`, `saving(texts: list[str]) -> dict` |
| E1 | `taskqueue.py` | the five functions above, plus `reclaim(stage_dir, now: float) -> list[str]` |
| E2 | `adaptive.py` | `next_wave(history: list[dict], limits: dict) -> dict` |
| E3 | `simulate.py` | `run(agents, tasks, batch, host_concurrency, service, seed, overhead=0.0, failure=0.0) -> dict` |
| E4 | `kit3.py` | `main(argv) -> int` handling `next` and `submit`, passing other verbs to `kit.main` |
| P1 | `loadtest.py` | `run(tasks: int, workers: int, home: Path) -> dict` |
| P2 | `timeline.py` | `build(paths: list[Path], start: float | None = None) -> dict` |
| P3 | `stats.py` | `summary(document: dict) -> dict`, `balance_point(rows: list[dict]) -> dict` |
| S2 | `cage.py` | `run(command: list[str], cwd=None, timeout=20, memory_mb=512, cpu_seconds=10) -> subprocess.CompletedProcess` |
| Q1 | `mutate.py` | `mutants(source: str, limit: int, seed: int) -> list[str]` |
| G1 | `handover.py` | `receipts(root: Path) -> list[dict]`, `write(root: Path) -> str` |
| D1 | `economics.py` | `per_task(document: dict) -> list[dict]`, `project(row: dict, tasks: int) -> dict`, `render(document: dict) -> str` |
