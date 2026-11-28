# L03 — Adaptive Agent Orchestration engine

Status: implemented in `engineering_os/orchestrator.py`, tested by `tests/test_orchestrator.py`
(38 tests). Layer L03 of the twenty-layer architecture; team D role
`adaptive-agent-orchestration-engineer`. Deterministic code only: no model is called, no agent is
started, no command is run. Plans, schedules and simulations are never reported as executions.

## 1. What it is for

The control plane and the build/upgrade engines hand the orchestrator a goal (or a `gaie.spec/1`
requirement specification). It returns a plan that up to twenty specialist agents can run in
parallel without stepping on each other, decides how many agents the next wave may use from what the
previous waves measured, carries each task through a leased, checkpointed, independently reviewed
lifecycle, and prints the git commands that give every agent its own worktree and branch.

## 2. Integration, not duplication

| Concern | Reused engine | How |
|---|---|---|
| Roles, owned paths, layers, default grants | `layers.load_roles`, `layers.instantiate_grant` (`governance/agent-roles.json`) | role assignment, ownership, grant templates |
| Grant validity and enforcement | `contracts.validate_grant`, `governor.check` | every per-task grant validates; tests prove the governor allows exactly the granted actions |
| Hierarchy and dependencies | `reasoning.decompose`, `reasoning.analyze_dependencies` | goal → milestones → tasks, dependency waves, critical path, sealed receipts |
| Wave assignment | `swarm/scheduler.py:plan` | loaded read-only by path (`adapters.load_path_module`); one agent per role instance per wave |
| Next-wave size | `economics.recommend_concurrency` (wraps `swarm/phase3/adaptive.py:next_wave`) | grow/hold/shrink/stop rules plus the host cap |
| Leases, handovers, approvals | `orchestration.TaskStore` | hash-chained private state; three independent approvals before done |
| Checkpoints and resume | `memory.MemoryStore` (`task_progress`, `next_steps`, checkpoint records) | work steps survive a crash; a fresh process resumes |

Nothing in `swarm/**` is modified; both swarm files are only loaded and called.

## 3. Public API

```python
plan(goal_or_spec, *, roles=None, max_agents=20, per_role=1, frozen=(), now=None) -> plan
verify_plan(plan, *, roles=None, frozen=()) -> plan            # digest + invariants, or raise
schedule(plan, history, *, done=(), cpus=None, agents_per_cpu=2, tokens_left=None) -> decision
lifecycle(task, *, state_dir, clock=None, frozen=()) -> Lifecycle
review_assignment(task) -> {"implementer", "reviewer", "panel", "independent": True}
worktree_plan(plan, *, repo, base_dir, base_ref="HEAD") -> argv lists per agent
scenario_h(metrics, *, commits=None, cpus=4) -> measured Scenario H figures
engine(action, payload, ctx) / health()                        # contract entrypoint, all side-effect none
```

Errors: `OrchestratorError` and its subclasses `OwnershipConflict` (carries `.conflicts`),
`GrantEscalation`, `ReviewIndependenceError`, `LifecycleError`.

## 4. Planning

**Input.** A goal id (one task per role, the role's owned paths, milestones per team A → B…F → G → H);
a goal object `{"goal", "title"?, "project"?, "tasks" | "milestones"}` whose tasks carry `id`, `paths`
and optionally `title`, `layers`, `role`, `reviewer`, `depends_on`, `minutes`, `risk`, `novelty`,
`confidence`, `engines`; or a `gaie.spec/1` document (validated by `requirements.validate_spec`), which
becomes architecture → data model → one build task per feature → tests and security review → release,
all inside `workspace/<slug>/`. `minutes` are the caller's planning estimates (default 30), never
measurements.

**Role assignment.** A declared role must be one of the plan's roles. Otherwise the role that owns
every path of the task wins (`owned-paths`); two such roles are an `ambiguous-owner` conflict. Failing
that, the role sharing the most layers with the task wins (`layers`, registry order breaks ties).
A task with neither is refused.

**Ownership without overlap.** Paths are canonical relative POSIX paths or patterns (`dir/*`); `..`,
absolute paths, `.git` and bare `*` are refused. Two scopes overlap when they can name the same file:
a plain path also stands for the directory of that name, and patterns are compared conservatively by
their literal prefix (false positives possible, false negatives not). The plan is refused with an
`OwnershipConflict` listing every conflict when

* two tasks overlap (`task-overlap`), whichever roles they have;
* a task writes a path another role owns in `agent-roles.json` (`foreign-owner`);
* a task touches a `frozen` area another session owns, e.g. `frozen=["swarm", ".claude/settings.json"]`
  while the swarm run executes (`frozen`).

`registry_conflicts(document)` checks the role registry itself; it is empty for the current registry.

**Waves.** `reasoning.decompose` flattens milestone dependencies onto task dependencies;
`reasoning.analyze_dependencies` gives dependency waves and the critical path (critical tasks get
priority 0); `swarm/scheduler.plan` assigns tasks to agents in waves of at most `max_agents` (1–20, the
measured limit of one host session), one task per agent per wave. Each role has `per_role` agent
instances (only as many as it has tasks); the roster never exceeds 20.

**Grants (least privilege).** Each task gets `instantiate_grant(role)` narrowed to what the task needs:
the requested `engines` (default: the role's), only the task paths inside the role's default grant
paths, and the lowest side-effect class covering the kept actions. A write action with no writable
task path is dropped (and noted) when it came from the default, and refused (`GrantEscalation`) when
the task asked for it. `grant_within_default` proves every grant is a subset of the role default
(engines, actions, side-effect class, paths, no approvals). Grants expire four hours after `now`.

**Review.** `review_assignment` returns a lead reviewer (the first role with the registry's
`reviewer` flag, else the testing capacity) and a panel for the task store's three approval
capacities: testing (`independent-assurance-engineer`, else `testing-self-healing-engineer`), security
(`enterprise-security-privacy-engineer`, else `agent-isolation-security-engineer`) and release
(`github-integration-release-engineer`, else `chief-engineering-architect`). The implementer's role is
never the reviewer or on the panel; a task that names its own role as reviewer is refused.

**Output.** `gaie.orchestration-plan/1`: hierarchy, tasks (role, team, layers, paths, store scope,
dependencies, agent, branch `claude/<goal>-<agent>`, wave, grant, grant notes, review), dependency
waves, critical path, waves, agents, path ownership map, self-checks, the reasoning receipts, the
SHA-256 of the role and engine registries, and `plan_sha256` over everything else. `verify_plan`
refuses a plan whose digest, ownership, review assignment, grants or wave invariants no longer hold,
or that was made with a different role registry. `plan_sha256` is a plain SHA-256 that anyone can
recompute, so ownership is rechecked against `agent-roles.json`, not trusted from the plan. For the
same reason a re-sealed plan can empty its own `frozen` list: the verifier passes the frozen areas it
requires (`verify_plan(plan, frozen=[…])`); a plan that does not cover each of them is refused with
an `OwnershipConflict` of kind `frozen-dropped`, and its tasks are checked against both lists. A plan
whose `frozen` list is not canonical is refused. Without `frozen=` only the plan's own list applies;
`schedule`, `worktree_plan` and the `engine` actions `schedule` and `worktree-plan` (payload key
`frozen`) pass the caller's list through to `verify_plan`.

## 5. Scheduling the next wave

`schedule(plan, history, done=…)` passes the measured waves (economics wave records: agents,
duration_seconds, tasks_verified, tokens, conflicts, failures, optional limit_errors,
peak_concurrent_agents) to `economics.recommend_concurrency` with
`max_agents = min(plan max_agents, host cap)` and `tasks_left = remaining tasks`:

* no history → start with min(4, cap);
* any limit error → stop (0);
* any conflict → halve;
* growth only when verified tasks per million tokens improved on the previous wave (and the inherited
  next_wave throughput rules allow it); otherwise hold;
* host cap = min(20, CPUs × 2). Two agents per CPU is a **policy**, chosen from the host-pressure
  observations in Scenario H (fork EAGAIN, BlockingIOError and timeouts in load-sensitive tests at 11
  agents on 4 shared CPUs); the 20-agent session limit is measured (swarm/phase3/capacity.py).

The wave is then filled with ready tasks (all dependencies in `done`, one per agent, schedule order).

## 6. Lifecycle

`lifecycle(task, state_dir=…)` binds a plan task to a private state directory (outside Git, mode
0700): `tasks/` holds the TaskStore, `memory/<project>/` the engineering memory.

| State | Store status | Entered by |
|---|---|---|
| queued | pending | `enqueue()` (orchestrator creates the task) |
| leased | active, last event claim | `lease(ttl)` → lease id, the task grant, branch and memory progress |
| running | active, last event renew | `start(lease)`, `checkpoint(lease, done, remaining)` |
| submitted | review | `submit(lease, receipts)`; partial approvals stay here |
| reviewed | done | the third panel approval via `review(role, decision, receipts)` |
| merged | done + memory merge note | `merge(receipts)` with the integrator's merge digest |
| failed | failed or blocked | `fail(lease, receipts)` or a rejected review |
| resumed | pending after recover, or handover | `resume()` (failed, rejected or lease-expired) or `handover()` |

Every transition writes a memory checkpoint bound to the task store's audit event. `checkpoint()`
stores the work steps done and remaining (`MemoryStore.task_progress`); after a crash a fresh process
sees the expired lease, calls `resume()`, leases again and reads `progress()` to continue at the next
step without redoing the finished ones (tested across two subprocesses). Illegal transitions raise
`LifecycleError`; a review by the implementer or by a role off the panel raises
`ReviewIndependenceError`; a task whose review panel or grant was altered is refused on construction.
A task can reach `lifecycle()` without `verify_plan`, so construction also rechecks its scope as
`plan()` does: `paths` must be the planned canonical list, `store_paths` must equal the store scope
derived from them, no path may be owned by another role in `agent-roles.json` (`OwnershipConflict`,
`foreign-owner`) and none may lie inside a frozen area the caller names (`frozen=`). A refused task
creates nothing in the state directory.

### Task stores written before the producer rule (owner decision)

Since review fix M3 (`orchestration.producers`), nobody who claimed, renewed, handed over, submitted
or failed a task may approve it, and `orchestration.verify_state` checks this every time a store is
opened. A store written by earlier code that already holds such an approval (the producer approved
its own work after a handover or a fail-and-recover) therefore **cannot be opened at all**:
`TaskStore(state_dir)` raises `CoordinationError: A reviewer of this task also held or worked it`,
and `lifecycle()` raises `LifecycleError: task store: …`. This blocks every task in that store, not
only the affected one. It fails closed: nothing is read, rewritten or dropped automatically. The
store is hash-chained, so removing the approval from `state.json` by hand is refused as well
(`Task data differs from audit receipt`), and relaxing `verify_state` would reopen M3.

There is no migration tool. What to do with such a store is the owner's choice:

1. **Archive and restart** (needs no code): move the old state directory aside, keep it private and
   outside Git as evidence, and start a new state directory. Enqueue the open tasks again from their
   verified plan; the affected task goes through an independent review panel again.
2. **A reviewed one-time migration**: new code in `engineering_os/orchestration.py` (another role's
   file) that rebuilds the store without the producer's approval, puts the task back to `review` and
   records the migration in the new audit chain. It rewrites an audit trail, so it needs the owner's
   explicit approval before anyone writes it. Not implemented.

## 7. Worktrees

`worktree_plan(plan, repo=…, base_dir=…)` returns, per agent, `git worktree add -b <branch> <dir>
<base_ref>` and the removal commands (`git worktree remove`, `git branch -d`). It only returns argv
lists. Hooks and fsmonitor are disabled in the commands, `base_dir` must be outside the repository,
removal refuses dirty worktrees and unmerged branches. The test creates and removes 20 worktrees on a
temporary repository.

## 8. Scenario H — measured, not simulated

`docs/evidence/gaie-20-layers/scenario-h.json` is produced by

```
python3 -m engineering_os.orchestrator scenario-h --metrics /home/user/gaie-state/wave-metrics.json \
  --git-range 002a612..41af803 --checkpoints /home/user/gaie-state/checkpoints --evidence
```

It embeds the metrics snapshot (with the file's SHA-256), the first-parent integration commits, every
result with its definition, the host-pressure notes it relied on, a schedule labelled `simulated`
(the twenty-role plan; no agent ran for it), and the 1,000-agent swarm run as `pending` (owned by the
swarm session; no result file of it is in this tree). Headline figures from the snapshot (8 measured
agents, 7 merged, 3 still running when it was taken): peak concurrency 11 (mean 9.01), 9.84 merged
tasks per wall-clock hour, 416,108 tokens per merged task, conflict entries in 6 of 8 agents (0.75),
integrator rework rate 0.43 (3 of 7 merged agents), gate re-run rate 0.625. The git history adds 10
agent merges by 55.4 minutes after the start (10.83 per hour) and 3 integrator rework commits.
`recommend_concurrency` on that cohort, with the 4-CPU host cap of 8, gives **4 agents** for the next
wave (conflict-shrink: 7 conflicts in a wave of 8). No 20-agent concurrent run happened.

## 9. Honest limits

* Overlap detection is conservative for patterns; it may refuse two patterns that never share a file.
* Ownership protects coordinated writes. It does not stop an agent editing outside its paths in its
  own worktree; the governor and the integrator's review do that.
* Actors in the task store are caller assertions, not authenticated identities (see orchestration.py).
* `AGENTS_PER_CPU = 2` is a policy derived from observations, not a measured optimum.
* The metrics snapshot predates three merges visible in git; both sources are reported, not mixed.

## 10. Requests to other owners

* `governance/layers.json` (L03): add interfaces `engineering_os.orchestrator:plan`, `:schedule`,
  `:lifecycle`, `:review_assignment`, `:worktree_plan`, test `tests/test_orchestrator.py`, scenario `H`.
* `governance/agent-roles.json`: add `engineering_os/orchestrator.py`, `tests/test_orchestrator.py`,
  `docs/specs/gaie-20-layers/ORCHESTRATION.md` and `docs/evidence/gaie-20-layers/scenario-h.json` to
  the `adaptive-agent-orchestration-engineer` owned paths.
* `governance/engines.json` + `engineering_os/adapters.py`: register an `orchestrator` engine (L03,
  entrypoint `engineering_os.orchestrator:engine`, health `:health`, actions `plan`, `schedule`,
  `review-assignment`, `worktree-plan`, `scenario-h`, all side effect `none`).

## 11. Agent-team policy

The standing team of every build and upgrade comes from `governance/policies/agent-team.json`.
That team is the twenty registry roles, each either staffed or omitted with a reason. The same
file holds the three numbers this engine uses: `MAX_AGENTS` (session limit 20, measured),
`AGENTS_PER_CPU` (2, policy) and `START_AGENTS` (4). Each number is bound to the evidence file it
comes from. The values and the twenty-role plan digest did not change when the numbers moved there.
The loader is `engineering_os/agent_team.py` (`show`, `check`, `role`, `evidence`). The rules, how
to edit them, and the parts that are declared but not enforced are in
[AGENT_TEAM.md](AGENT_TEAM.md).
