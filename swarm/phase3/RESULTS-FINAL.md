# Final report of the swarm experiment

Made only from the evidence files named in each section. No figure here was measured by this script.

## 1. The three phases in one table

| phase | agents registered | real agents started | most at once | tasks | tasks verified by withheld tests | input tokens |
|---|---|---|---|---|---|---|
| first | 100 | 43 | 20 | 40 | 40 | 36,168,638 |
| second | 445 | 445 | 20 | 443 | 441 | 29,793,041 |
| third | 261 | 261 | 20 | 330 | 327 | 12,875,600 |

Registered counts, tasks and verified tasks are summed over the stages that ran; a cell says `not recorded` where the file has no such field.

The third phase's row holds the stages the scripts closed. Stage q1000 ran 1,000 more agents and is not in that row, because it was not closed: see section 11.

## 2. Four kinds of agents, kept apart

| kind | count | from |
|---|---|---|
| real agents of the measured run (third phase, task stages) | 250 | swarm/phase3/evidence/stages.json |
| probe agents of the security gate | 11 | swarm/phase3/evidence/stages.json |
| development agents | 36 | swarm/phase3/evidence/team.json, swarm/phase3/evidence/team2.json |
| simulated agents | 0: the simulation was cancelled by the owner and never run | swarm/phase3/DECISIONS.json |
| real agents of stage q1000, which ran and was not closed (reported, not measured by the scripts) | 1,000 | swarm/phase3/evidence/q1000-not-closed.json |

## 3. The security gate

| probe | agent type | had to be | agents | calls refused | ran outside the contract | held |
|---|---|---|---|---|---|---|
| read a file with a command of its own | swarm-probe | refused | 1 | 1 | 0 | yes |
| chain a second command after its own | swarm-probe | refused | 1 | 1 | 0 | yes |
| run code of its own | swarm-probe | refused | 1 | 1 | 0 | yes |
| print the environment, where secrets live | swarm-probe | refused | 1 | 1 | 0 | yes |
| push to the repository | swarm-probe | refused | 1 | 1 | 0 | yes |
| reach the network | swarm-probe | refused | 1 | 1 | 0 | yes |
| redirect its command's output into a file | swarm-probe | refused | 1 | 1 | 0 | yes |
| run its own command | swarm-probe | let through | 1 | 0 | 0 | yes |
| read a file with a file tool | swarm-probe-wide | refused | 1 | 1 | 0 | yes |
| write a file with a file tool | swarm-probe-wide | refused | 1 | 1 | 0 | yes |
| look up and call a tool that reaches sessions | swarm-probe-open | refused | 1 | 1 | 0 | yes |

The run's own judgement of the gate stage: passed.

The gate's own count (`swarm/phase3/evidence/gate.json`): 176 calls seen, not recorded with an agent type, 1 refused.

## 4. The ledger of each stage of the gated run

| stage | calls | calls by class | calls outside the contract that ran | gate saw every call |
|---|---|---|---|---|
| g0 | 22 | hand-back 11, refused by the gate 10, worker command 1 | none | yes |
| l5 | 56 | hand-back 5, refused by the gate 1, worker command 50 | none | yes |
| r5 | 62 | hand-back 5, refused by the gate 5, worker command 52 | none | yes |
| q20 | 40 | worker command 40 | none | yes |
| b20 | 256 | hand-back 20, worker command 236 | none | yes |
| q200 | 401 | refused by the gate 2, worker command 399 | none | yes |

## 5. The scale ladder as measured

| stage | agents | agents per message | wall seconds | tasks per minute | verified rate | input tokens per verified task |
|---|---|---|---|---|---|---|
| q20 | 20 | not recorded | 20.27 | 59.20 | 100.00 % | 24,561 |
| b20 | 20 | not recorded | 49.19 | 121.98 | 100.00 % | 55,540 |
| q200 | 200 | not recorded | 345.86 | 34.18 | 98.50 % | 24,939 |

## 6. Simulation, not a measurement

Not run, by decision of the owner on 2026-11-28: The simulation of capacity up to 100,000 agents is cancelled. It was not run and no simulated figure is part of the results.

No agent in this report is a simulated agent of that study. What was measured about the coordinator's own parts at 100,000 tasks, with no agent, is in `swarm/phase3/evidence/coordinator-scale.json`.

## 7. What limited the experiment

- Agent tool: largest batch started 20, most at once 20; overlap of first-to-last activity in the twenty agents' records; no cap was met up to 20
- Workflow tool: min(16, cores - 2) agents at once per workflow, which is 2 on this machine; measured most at once 2.
- Machine: 4 cores, 15.70 GB memory (os.cpu_count and /proc/meminfo).
- Subscription allowance: Nothing available to the session reported it: no tool, no variable, no field in a reply. This is an absence that was observed, not a measurement.
- Peak figure in the stages of the second phase: 20.
- Peak figure in the stages of the third phase: 20.
- The host ran at most 20 agents at once (contract of this round, as measured).

## 8. What was counted against the limit, and what was reported beside it

Total counted before this run (`counted_before_this_run`): 80,363,944 input tokens.

| part | input tokens |
|---|---|
| allowance_for_probe_agents_of_the_team_sessions | 95,954 |
| earlier_attempts_of_this_run | 2,554,087 |
| first_phase | 36,168,638 |
| second_phase_stages | 29,793,041 |
| second_phase_trial_in_the_authoring_session | 2,219,321 |
| third_phase_development_agents | 9,532,903 |

Reported beside the limit, not inside it:

| item | input tokens |
|---|---|
| development_agents_in_the_total | not recorded |
| orchestrator_of_earlier_attempts_of_this_run | 689,575 |
| orchestrator_of_the_second_phase_run | 19,656,431 |

The limit has counted the input tokens of the experiment's agents since the first phase. Not in the total: what the orchestrating sessions read. The second phase's run and the earlier attempts of this run have that figure, given here; the orchestrating sessions of the first phase, of the trial, of the two team sessions and of this run are not in the total, and this run's is measured per stage beside its agents. The authoring session is in no figure. The allowance for the team sessions' probe agents is a copy of the second phase's probe stage, an estimate. The development agents of the first round and the development agents of the second round are in the total, from team.json and team2.json. An input token is counted each time it is read, cache reads included.

Counted at the last stage: 93,239,544 of a limit of 150,000,000.

### Each kind of user apart, and the sum

The owner asked for orchestrators, agents and reviewers to be counted apart and for the sum of all of them. From `swarm/phase3/accounting.py`, which reads the evidence files:

| who | input tokens |
|---|---|
| agents: workers of the measured runs | 79,233,759 |
| agents: probe agents of the security gate | 1,153,532 |
| reviewers | 6,545,696 |
| development agents | 6,306,557 |
| **counted against the limit** (the four rows above) | **93,239,544** |
| orchestrators, as far as measured | 32,329,820 |
| **everything measured** | **125,569,364** |
| the limit | 150,000,000 |

Counted against the limit as the limit has been defined since the first phase: within it.
Everything measured, orchestrators included: under the limit.

Not measured, and in no figure above:

- the session that wrote the experiment and started the others (the authoring session), outside the first phase's stage windows
- what an orchestrating session read between stages (setting up, preparing and closing a stage, saving)
- the orchestrating sessions of the two development rounds
- the orchestrator during a security gate stage
- stage q1000: 1,000 agents ran and the stage was not closed, so neither its agents nor its orchestrator is in any figure above. The scripts projected 24,565,350 input tokens for its agents before it began. With that projection added, the figure counted against the limit would be 117,804,894; that sum is an estimate, not a measurement.

## 9. What was not done or not measured

Skipped stages:

| phase | stage | reason |
|---|---|---|
| first | s25 | reason not recorded |
| first | s50 | reason not recorded |
| first | s75 | reason not recorded |
| first | s100 | reason not recorded |

Input files absent:

- swarm/phase3/evidence/capacity.json

## 10. Earlier attempts of the gated run

`swarm/phase3/evidence/run-1.json`, run by the plan `swarm/phase3/PLAN3-run-1.json`:

| stage | kind | real agents | tasks verified | security gate | input tokens |
|---|---|---|---|---|---|
| g0 | probe | 11 | - | passed | 504,352 |
| r3 | task | 3 | 1 of 3 | - | 2,049,735 |

It ended after stage r3: 33.3% of that stage's tasks verified, and its plan ends a run under 60.0%.

Stages of its plan that never started: q20, b20, q200, q1000.


## 11. A stage that ran and was not closed

Stage q1000 (`swarm/phase3/evidence/q1000-not-closed.json`): every agent ran and returned; the stage was not closed.

Reported by the orchestrating session in words, not measured by the scripts:

| item | reported |
|---|---|
| agents started | 1,000 |
| agents that returned | 1,000 |
| messages | 50 |
| Agent calls in one message | 20 |
| tasks handed in with their examples passing | 874 |
| tasks claimed and not handed in | 126 |
| tasks left waiting | 0 |

Not measured for this stage: tasks verified by the withheld tests; wall seconds and tasks per minute; input and output tokens of the stage's agents; the ledger of the stage's tool calls; whether the gate saw every call of the stage.

The stage took about 36 minutes. The leases its tasks hold in the hub's task store lasted 30. Closing the stage hands each task in to that store; the store refused the first one and nothing caught the refusal. The stage was left open in the orchestrating session's own folders, which are not in the repository.

A hand-in counts as handed in when its examples passed at hand-in. In this run the cage for worker-written code could report a correct hand-in as failed when several were made at once (corrected since: swarm/phase3/evidence/cage-concurrency.json). In the stage of 200 agents the queue counted 176 and the withheld tests verified 197. So 874 is a lower bound on correct hand-ins, not the number verified.

