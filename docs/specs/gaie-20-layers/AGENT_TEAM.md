# L03 — Agent-team policy

Status: policy `governance/policies/agent-team.json` (version 1.0.0), loader
`engineering_os/agent_team.py`, tests `tests/test_agent_team.py`. Read today by
`engineering_os/orchestrator.py`. Team D role `adaptive-agent-orchestration-engineer`.
A team in this policy is a staffing plan. Nothing here starts an agent, calls a model or
runs a command.

## 1. The rule

Every build and every upgrade is staffed by the standing team: the twenty specialist roles
of `governance/agent-roles.json`, working in parallel within the security and resource
policy. The policy says three things:

* **Who.** The roster of the intents `build` and `upgrade` is all twenty roles, in registry
  order. A role with no work in a given plan is listed as omitted with a reason. It is never
  dropped silently. A team never has more than 20 roles.
* **How many at once.** The roster is not the number of agents running at the same moment.
  Live concurrency is bounded by the host (section 2).
* **Who checks.** The reviewer of a work item is never its producer. The registry's reviewer
  role (`independent-assurance-engineer`) is mandatory in every roster.

The intents `audit`, `accelerate`, `repair`, `cinematic` and `release` have no standing
roster. Audit is a read-only review by the `gaie-verifier` agent and release is gated by a
separate owner approval. The three scoped passes keep the router's workstream sizing (at most
20) until the owner adds a roster for them.

## 2. Roster versus concurrency

On a host with `cpus` CPUs:

* `effective = min(session_limit, cpus × agents_per_cpu)`.
* Inside the workflow runner, `effective` is also capped at `min(16, cpus − 2)`.
* The first wave uses `min(start, effective)` agents.

| Number | Value | Kind | Evidence |
|---|---|---|---|
| session_limit | 20 | measured | `swarm/evidence/host-limits.json` agent_tool peak 20; `swarm/phase2/README.md` finding 2 (the host refused calls past the twentieth); `swarm/phase3/evidence/team.json` 20 lanes at once; `swarm/phase3/capacity.py` SESSION |
| agents_per_cpu | 2 | policy | `docs/evidence/gaie-20-layers/scenario-h.json` host_cap_policy (cap 8 on 4 CPUs). At 11 agents with full local suites, fork EAGAIN, BlockingIOError and timeouts were recorded (host_pressure). `swarm/phase3/evidence/team2.json`: 16 at once, suite not passing. ECONOMICS.md: shrink to 8 |
| start | 4 | policy | scenario-h.json next_wave limits and the simulated first wave |
| workflow runner | min(16, cpus − 2) | documented | `swarm/evidence/host-limits.json` workflow_tool: documented cap, peak 2 on 4 cores |

On this 4-CPU host the figures are: session limit 20, effective 8, start 4, workflow
runner 2. Two agents per CPU is a policy figure, not a measured optimum. No 20-agent
concurrent run has happened in the GAIE effort. The measured peak is 11 (Scenario H).

## 3. Waves

`orchestrator.plan` orders the work in dependency waves: team A first, teams B to F in
parallel, then G, then H. For the twenty-role goal the waves are [3, 13, 2, 2]. A wave
holds at most `effective` agents, one task per agent. A ready set larger than that runs as
successive waves and is never started all at once. For example, 13 ready tasks on 4 CPUs
run as 4+4+4+1 at the start size, or 8+5 at the cap. `orchestrator.schedule` sizes the next
wave with `economics.recommend_concurrency`:

* stop on a limit error;
* halve on any conflict;
* grow only when verified tasks per million tokens improved;
* never go above `effective`.

## 4. Omitted with a reason

`check_staffing(plan, intent)` accounts for every one of the twenty roles as staffed or
omitted. A planner can give its own reason with
`"omitted": [{"role", "reason"}]`. Otherwise the reason is one of these:

* the role reviews work items as an independent reviewer or approval-panel member;
* no work item in this plan is assigned to it;
* it is not in the intent's roster.

The check refuses all of the following:

* more agents than the session limit;
* an unknown role;
* a role outside the roster;
* a reviewer that produced its own item;
* a mandatory role that neither works nor reviews;
* a policy whose role list differs from the registry.

For example, the spec build of `tests/fixtures/upgrade/taskapp/gaie-spec.json` has 5 roles
staffed and 15 omitted, each with a reason.

## 5. How the owner changes it

The policy lives in one file, `governance/policies/agent-team.json`. To change it:

1. Edit the file. For example, trim a roster, lower `session_limit`, change `agents_per_cpu`
   or `start`, or add a roster for another intent.
2. Raise `policy_version`. Use a minor step for a number and a major step for a roster or
   rule change.
3. Run `python3 -m unittest tests.test_agent_team`. It must pass.

The test pins these points:

* The role list equals the registry.
* Every number equals the evidence file it cites. A new number needs a new evidence entry
  (`file`, JSON `pointer`, `value`, or `contains` for text).
* The orchestrator's constants and the router's `max_agents` agree with the policy.
* The full build and upgrade rosters are an owner decision of 2026-11-28. A later decision
  that trims a roster changes the policy and the one assertion in
  `PolicyTests.test_build_and_upgrade_staff_all_twenty` in the same commit.

The loader refuses:

* duplicate JSON keys;
* unknown fields;
* a `session_limit` above 20 (the measured host limit; the policy can lower it, never raise
  it);
* a roster above `session_limit`;
* a roster without the reviewer role.

## 6. Commands

```
python3 -m engineering_os.agent_team show [--intent build|upgrade] [--cpus N] [--runner agent|workflow] [--json]
python3 -m engineering_os.agent_team check PLAN.json --intent build [--json]
python3 -m engineering_os.agent_team role ROLE_ID [--json]
python3 -m engineering_os.agent_team evidence
```

`agents/gaie-specialist.md` (mirrored in `.claude/agents/`) is the definition for one team
member. It works like this:

* It takes a role id and one work item.
* It loads the role's owned paths, default grant and reviewer with `agent_team role`.
* It writes only inside the work item's paths.
* It cannot start agents.
* It hands its result to the reviewer.

Agent definitions load at session start, so a new definition is available only in a new
session (`swarm/evidence/host-limits.json` agent_definitions).

## 7. Declared versus enforced

The policy's `declared_vs_enforced` section lists both halves, and the test checks that every
named test exists.

These rules are enforced in CI:

* the schema and its bounds;
* the role list equals the registry;
* the numbers equal the evidence;
* the orchestrator and router limits come from the policy;
* staffing refuses an oversized team or an unknown role and lists omitted roles with reasons;
* waves stay within the host cap;
* the reviewer is never the producer;
* the specialist definition and its mirror are identical and have no Agent tool.

These claims are declared only:

* **The team really starts.** A live session decides which agents it starts. No code in this
  repository starts an agent.
* **Role identity.** An agent is the role it claims only by assertion. No identity provider
  authenticates roles.
* **Live concurrency.** A session-level count guard needs a PreToolUse hook in
  `.claude/settings.json`. That file is frozen (`swarm/phase3/FREEZE.json`), so no guard is
  installed. The host itself refuses agent calls past the twentieth.
* **Writes stay in scope.** The specialist is instructed to write only inside its paths. No
  hook confines it (ORCHESTRATION.md section 9).
* **Other projects.** Sessions in other projects follow the policy only once the bootstrap
  and the pack ship it with the router.

## 8. Cost

Scenario H measured 2,912,758 tokens for 8 agents, which is 416,108 tokens per merged task
(`docs/evidence/gaie-20-layers/scenario-h.json` results.tokens). Twenty work items at that
rate would be about 8.3 million tokens. That figure is arithmetic, not a measurement.

The swarm measured where a worker's cost comes from (`swarm/phase2/README.md` finding 1):

| Worker | First request (tokens) | Input tokens for the same small task |
|---|---|---|
| General worker | 123,865 | 470,079 |
| Lean definition | 5,486 | 50,292 |

This is why the specialist definition is kept short and why omitted roles start no agent. No
tool reported the subscription allowance, and no money figure is derived here.

## 9. Wiring status

These parts read the policy today:

* `engineering_os/orchestrator.py` (`consumers` in the policy).

These parts are not wired yet. Their owners still have to apply the change:

* the router plan's team block and its refusal of an oversized or unknown team;
* the AGENTS.md rule and the gaie-master-router, gaie-build and gaie-upgrade skills;
* the master prompts;
* shipping the policy, the loader and the specialist through the bootstrap, the pack and the
  plugin;
* the L03 layer record and the role's owned paths;
* the staffing record in the build and upgrade engines.

When one of these is wired, it is added to `consumers` in the policy, and the test checks
that the file uses the loader.
