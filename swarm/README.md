# Swarm experiment: 100 capabilities, 100 roles, real agents up to the point where it stopped paying

Everything here was run on 2026-11-28 in one Claude Code cloud session (4 cores, 15.7 GB). The numbers are in
`evidence/` and `state/`; this page only quotes them.

## What exists

- `capabilities.json`: the hundred optimisation capabilities, each with what it really is and how far it got.
  66 were used for real work, 18 ran in a test only, 2 exist but were not exercised, 2 are done by the host,
  3 are working rules, 2 are blocked and 7 are not implemented. 14 of the hundred are outside tools that ran here.
- `agents.json`: a hundred roles in ten teams, each with its scope, capabilities, limits and stop conditions.
  A role in a file is not an agent. Real agents ran two of the hundred roles.
- `route.py` picks a few capabilities for a task (2 of 100 for routine work, 10 for an investigation).
- `scheduler.py` plans waves and keeps ownership in the hub's own task store. Its simulation schedules a hundred
  agents with dependencies and duplicates and passes its checks at limits of 100, 16 and 2.
- `workload.py`, `bench.py`: generated tasks and a generated project, with withheld tests. No real project data.
- `measure.py`, `protect.py`, `ladder.py`: measurement from the host's agent records, the limits, and the stage driver.

## The ladder

Each agent wrote one small function from a written specification; withheld tests decided whether it counted.
Stage one is one agent doing five tasks, so stage two (five agents, one task each) is the same amount of work.

| Agents | Peak at once | Tasks | Verified | Seconds | Tasks a minute | Speedup | Efficiency | Input tokens | Output tokens | Input per task | Verified tasks per million tokens |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 5 | 5 | 23.23 | 12.91 | 1.0 (baseline) | 1.0 | 703,616 | 5,389 | 140,723 | 1.76 |
| 5 | 5 | 5 | 5 | 21.81 | 13.75 | 1.07 | 0.213 | 4,186,207 | 10,012 | 837,241 | 0.89 |
| 10 | 10 | 10 | 10 | 20.37 | 29.46 | 2.28 | 0.228 | 8,128,633 | 18,001 | 812,863 | 1.04 |
| 20 | 20 | 20 | 20 | 40.49 | 29.64 | 2.29 | 0.115 | 16,031,441 | 37,602 | 801,572 | 1.14 |

Stage s25 was not started. After s20 two limits written before the first run said stop: throughput was 29.64 tasks a minute against 29.46 at ten agents, under the required 10% gain; and the next stage was projected to pass the limit of 40,000,000 input tokens. Stages of 25, 50, 75 and 100 agents were therefore not run, and nothing is reported for them.

What the ladder shows:

- All 40 tasks passed all 564 withheld tests, at every size. Quality did not drop.
- Five agents were not faster than one agent doing the same five tasks (21.81 s against 23.23 s) and cost 5.9 times the input tokens.
- Throughput doubled from five to ten agents and then stopped: twenty agents took twice as long each.
- An agent's first request carried a median of 222,067 tokens of context (221,822 to 222,192) before it had read its task, and a median
  of 182,023 tokens was written to the cache per agent. The ladder's agents made 125 model replies and used 29,049,897
  input tokens, about 232,399 a reply: nearly all of it is that starting context sent again each time, not the task.
  The session has six repositories' instruction files and many connectors attached, which is the likely reason; the split was not measured.
- Speedup is measured against stage one's 23.23 seconds for five tasks, unrounded. Efficiency is speedup divided by agents.

## Configurations A to D

Scripted, with no agent: the text each way of working puts into context for the same five questions about the
generated project (`evidence/configurations-trace.json`; tokens from a proxy tokenizer).

| Configuration | Tokens of tool output | Saved against A | Questions answered by the output alone |
|---|---:|---:|---:|
| A. the host's own tools | 33,437 | | 4 of 5 |
| B. A with Headroom on long output | 16,393 | 51.0% | 4 of 5 |
| C. B with the language server for code | 16,739 | 49.9% | 5 of 5 |
| D. C with a shared index and one-line scripts | 2,210 | 93.4% | 5 of 5 |

With one real agent each (`evidence/configurations-agents.json`, one sample, so an observation and not a rate):

| | A | D |
|---|---:|---:|
| Score | 5 of 5 | 5 of 5 |
| Model replies | 8 | 7 |
| Tool calls | 8 | 7 |
| Characters of tool output read | 7,021 | 6,046 |
| Input tokens | 1,885,739 | 1,645,148 |
| Output tokens | 1,276 | 1,197 |
| Seconds | 20.37 | 17.36 |

Configurations B and C were not run with real agents: the token limit left no room.

## Independent review

Four reviewers, started by the host's workflow tool and told to refute this report, returned 12 findings
(8 low, 4 medium). All were valid and are addressed; `evidence/review.json` lists each with what was done.
They also measured that tool's limit: 2 of the 4 ran at once, as its documentation says for a four-core machine.
`evidence/host-limits.json` records every limit named in `state/BLOCKERS.md` and how it was observed.

## Safety

- 4 tool calls by 4 agents went outside their task (calls to session-control tools); the host refused 4 of them. See `evidence/tool-audit.json`.
- No solution imported anything outside the allowed list, and no agent wrote a file outside its folder.
- A minimal worker agent type could not be used: the host loads agent definitions only when a session starts.

## Run it again

```bash
python3 swarm/build_registries.py --check
python3 swarm/scheduler.py simulate --limit 16
SWARM_RECORDS=DIR SWARM_MAIN_RECORD=FILE python3 swarm/ladder.py prep s05 5 6      # then start the agents, then: finish s05 10
python3 swarm/bench.py build DIR && python3 swarm/bench.py trace DIR OUT.json
```

`ladder.py` starts no agent. A real agent is started by the agent host; the script prepares the work and scores it.
