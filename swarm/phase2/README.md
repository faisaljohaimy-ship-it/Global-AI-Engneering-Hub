# The second phase: lean workers in a clean session

The first phase stopped at 20 agents. This phase asked why a worker cost so much, removed
most of the cost, and ran the ladder the owner asked for: 10, 20, 25, 50, 75 and 100
agents on small tasks, then medium and large tasks. All 21 stages of `PLAN.json` ran, none
was skipped, and the run stayed far under its limit.

`RESULTS.md` is the full table, generated from `evidence/stages.json`. This page says what
the table means, and what it does not.

## What was measured

| | First phase | Second phase |
|---|---:|---:|
| Context a worker starts with | 222,067 tokens (general worker) | 5,486 tokens (lean worker) |
| Input tokens per verified small task, 20 agents | 801,572 | 50,307 |
| Tasks per minute, 20 agents | 29.64 | 76.57 |
| Largest number of agents that ran at once | 20 | 20 |
| Agents started | 43 | 445 |

- **441 of 443 tasks passed every withheld test** (6,149 of 6,151 tests). The two that did
  not are large tasks of the stage that had plain commands only.
- **Input tokens counted against the limit: 68,181,000 of 150,000,000**, the first
  phase and the trial run included. This phase's own agents used 29,793,041 input and
  496,294 output tokens.
- No agent met a usage limit or a rate limit.

## The five findings

**1. The cost of a worker was its session, not its task.** A general worker in the first
phase began with 222,067 tokens. The same worker type in a clean session that holds only
this repository began with 123,865 (stage `g10`): the host's own tools and connectors.
A worker defined with a shell and nothing else began with 5,486. For the same small task
in the same clean session, the general worker used 470,079 input tokens and the lean
worker 50,292.

**2. The host runs at most 20 agents at once.** In stage `s25` it refused the calls past
the twentieth and said so, naming its own setting for the limit. That setting was not
changed. So the stages of 25, 50, 75 and 100 agents ran as groups of 20, one after
another. All their tasks passed, but they did not run 25, 50, 75 or 100 agents at the same
moment, and their throughput is that of groups of 20 with the orchestrator's own turn
between groups: 36.49 to 44.94 tasks per minute against 76.57 for a single group of 20.
**One hundred agents at the same moment was not reached and cannot be reached on this host.**

**3. More than half of what a lean worker reads is not about its task.** A lean worker's
first request is about 5,500 tokens. Its later requests are about 19,000 to 22,000 each:
the two-step worker of stage `c2` used 24,425 tokens for two requests. A worker's record
in the authoring session shows why: after a worker's first tool call the host attaches the
instructions of every connector the account has (about 38,000 characters there) to the
conversation, although the worker has no connector tool. That was read in the authoring
session's record; for the clean session it is inferred from the sizes of the requests,
which fit it. The practical result is the two-step worker: it is stopped by its turn limit
after handing in, spends no third request on the word DONE, and cost
24,425 tokens per task against 50,292, with all five of its tasks passing.

**4. On large tasks, shortened output and a shared index paid, and plain commands failed.**
Five agents with plain commands only (`l5r`: whole test output, whole files, text search)
verified 3 of 5 tasks, were shown 693,403 characters by the worker command, and left
it 23 times for commands of their own. Five agents with the lean commands (`l5l`: test
failures through the hub's Headroom front end, an index read once from the code, a record
filter) verified 5 of 5 and were shown 19,139 characters. Per verified task that is
209,750 input tokens against 115,349. It held at 10 and 25 agents (10 of 10, 25
of 25). Five tasks a side is a small sample. In each lean stage the index agreed with what
the language server (Serena) said about one project's callers.

**5. The gate in a worker's definition is not run by this host.** The probe worker was told
to run a command the gate must refuse, and ran it. So in this phase the boundary of a
worker was its tool list (a shell only) and its instructions. The workers of the small and
medium stages kept to their one command in every call. Workers of the large stages did
not always: l5r 23, l5l 3, l10 3, l25 6 calls outside the allowed shape, and the general
workers of `g10` made 5 calls to other tools. Nothing was damaged: the tasks are generated,
and worker-written code is screened and run with no network. But the boundary was not
enforced, and the third phase replaces this gate by one set for the whole session.

## What a task cost

| Size | Stands in for | Worker | Agents | Input tokens per verified task |
|---|---|---|---:|---:|
| small | one function | lean, three steps | 20 | 50,307 |
| small | one function | lean, two steps | 5 | 24,425 |
| small | one function | general | 10 | 470,079 |
| medium | a module of parts that work together | lean, light model | 10 | 48,518 |
| medium | the same | lean, middle model | 10 | 45,382 |
| large | a fix in an existing project, with four questions | lean commands, middle model | 10 | 113,423 |

The sizes are generated stand-ins, not customer work. The light and the middle model both
passed all ten medium tasks, so the later medium stages used the light one, as the plan's
rule says. Token counts of two different models are not costs of the same kind: the cost
units in the evidence weigh kinds of token, not models, and must not be used to compare a
stage on one model with a stage on another.

## What the orchestrator cost

The session that started the agents read 19,656,431 input tokens of its own during the
stages, against 29,793,041 for all the agents. It is not counted against the limit,
which counts agents, and it is not small: for the stage of 100 agents it was
2,232,880 against 5,086,005. Every agent started and every answer returned stays in the
orchestrator's context and is read again on each of its later turns.

## What this does not show

- Not 100 agents at once. See finding 2.
- Not what the work cost in subscription allowance. The host does not show that. Token
  counts are from its records of each agent; cost units are an assumption stated in
  `PLAN.json`.
- Not real engineering work. The tasks are generated, with one right answer each.
- Not a second run. Every stage ran once, and the variants (`c2`, `c3`, `l5r`, `l5l`) have
  five agents each.
- Stages from `g10` on overlapped, in time, with twenty development agents working in
  another session on the same account. No limit message appeared, but their throughput
  figures were not measured on a quiet account.
- Nothing was run from Codex.

## Where things are

| Path | What it is |
|---|---|
| `PLAN.json` | the stages, limits and stopping rules, written before the run |
| `RUNBOOK.md` | what the clean session was told to do |
| `evidence/stages.json` | every stage: counts, times, tool names; no record content |
| `evidence/preflight.json` | the four-agent trial in the authoring session |
| `RESULTS.md`, `state/` | generated from the evidence by `stage.py report` |
| `tasks.py`, `kit.py`, `guard.py`, `stage.py` | tasks and withheld tests, the worker's command, the gate, the stage driver |

To run the tests: `python3 -m unittest tests.test_swarm_phase2`. They start no agent.
