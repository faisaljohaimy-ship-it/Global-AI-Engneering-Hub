# Swarm experiment: closing state and resume points

Closed by the owner on 2026-11-28. The numerical scale-up is over: no further agent, batch
or scale stage is to be started, the simulation to 100,000 agents is cancelled, and no
completed stage is to be run again (`DECISIONS.json`). This page says where everything
stands, in real counts, and how to pick the work up. Figures come from the evidence files
named beside them; where a figure was reported and not measured, it says so.

## Where it is

- Branch `claude/swarm-phase-3`, pull request #24, stacked on #23 (`claude/swarm-phase-2`),
  stacked on #22 (`claude/swarm-100x100`). Merge in that order. The author does not merge.
- `FREEZE.json` holds the hash of every file of the experiment. `python3
  swarm/phase3/freeze.py check` says whether anything changed since.
- The report is `RESULTS-FINAL.md`; the threat model `SECURITY.md`; the page for the
  reviewer `HANDOVER.md`; the account of use `evidence/accounting.json`.

## Real agents, counted once each

Every agent below was a real agent started by the host. No agent is counted in two rows.

| Where | Real agents | Of them |
|---|---|---|
| First phase (`swarm/evidence/summary.json`) | 43 | 38 workers, 4 reviewers, 1 minimal worker |
| Second phase, trial (`phase2/evidence/preflight.json`) | 4 | workers |
| Second phase, 21 stages (`phase2/evidence/stages.json`) | 445 | workers, 2 of them gate probes |
| Third phase, development round 1 (`evidence/team.json`, `gate.json`) | 22 | 20 development agents, 2 gate probes |
| Third phase, development round 2 (`evidence/team2.json`) | 16 | development and review agents |
| Third phase, first attempt of the run (`evidence/run-1.json`) | 14 | 11 gate probes, 3 workers |
| Third phase, the run, closed stages (`evidence/stages.json`) | 261 | 11 gate probes, 250 workers |
| Third phase, the run, stage q1000 (`evidence/q1000-not-closed.json`) | 1,000 | workers; reported, not measured by the scripts |
| **All** | **1,805** | |

Simulated agents: none. The most agents the host ran at once, in every phase: 20. A stage
of more than 20 agents is that many real agents in groups of 20, one group after another.

## Tasks, and what the withheld tests said

| Where | Tasks | Verified by withheld tests |
|---|---|---|
| First phase | 40 | 40 |
| Second phase, trial | 4 | 4 |
| Second phase, stages | 443 | 441 |
| Third phase, first attempt | 3 | 1 |
| Third phase, the run: l5, r5, q20, b20, q200 | 330 | 327 |
| Third phase, the run: q1000 | 1,000 drawn | not measured: the stage was not closed. 874 were handed in with their examples passing, which is a lower bound on correct hand-ins and not a verified count |

The second phase's two failed large tasks, L-0012 and L-0014, were run again on the same
projects: 5 of 5 with the adopted worker and 5 of 5 with plain commands.

The repository's own tests: 637, of which 3 are skipped and 15 are kept as expected
failures, each one a proof of a limit that is still open and named below.

## The security gate

Run live twice, in two sessions, and passed both times: eleven agents were each told to do
one forbidden thing or one allowed thing. Ten forbidden calls were refused by the gate
itself, the allowed call ran, nothing outside a worker's contract ran, and the gate's own
record held every call the host's records held, compared agent by agent. In every closed
stage after it the ledger is clean and the gate saw every call.

## Use

Input tokens; a token is counted each time it is read, cache reads included.

- Counted against the limit of 150,000,000 as the limit has been defined since the first
  phase (workers, probes, reviewers, development agents): 93,239,544 recorded by the
  scripts. The 1,000 agents of q1000 are not in it; the scripts projected 24,565,350 for
  them before the stage. With that estimate: about 117,800,000.
- Orchestrators, as far as the scripts measured them inside stage windows: 32,329,820.
  That leaves out what an orchestrating session read between stages, the two development
  sessions' orchestrators, all of q1000, and the session that wrote the experiment.
- So everything the scripts measured is 125,569,364, and what was really used is higher
  than that and higher than 150,000,000 once q1000 and the unmeasured orchestrators are
  added. The orchestrator of the last run was the largest single user: its context grew
  with every message until each message of twenty agents read about 750,000 tokens.

## What is open

1. **Stage q1000 is not closed.** Its agents ran; the evidence of it is in the folders of
   the session that ran it, not in the repository. That session will close it with the
   corrected script when the owner says so there. It needs no agent: it runs the withheld
   tests and writes the evidence. Then `evidence/stages.json` gains q1000,
   `evidence/q1000-not-closed.json` is removed, and the report, the handover and the freeze
   are written again (commands below). If that session's folders are gone, q1000 stays as
   reported and not measured.
2. The cage fix (each running cage a user of its own) was measured with no agent, not with
   real agents: `evidence/cage-concurrency.json`.
3. Security limits that stand, each with its proof in the tests: five ways through the
   development agents' net, which is a list of refused commands and not a sandbox; a stage
   whose tasks are given by id has no tickets, so a worker acting on another's task is found
   afterwards and not stopped; the gate does not confine the orchestrator; what the host
   does when the gate runs out of time was not measured; a gate that is not installed does
   nothing, by design. `SECURITY.md` has the full table.
4. On this branch two worker model identifiers in six first-phase files are replaced by
   family names. #22 and #23 still hold the old text; merging in order corrects it.

## To pick it up

    python3 -m unittest discover -s tests            # the whole suite
    python3 swarm/phase3/hook.py selftest --here     # the gate decides as it must
    python3 swarm/phase3/closure.py                  # every check of the experiment
    python3 swarm/phase3/freeze.py check             # nothing changed since the freeze

After any change to a frozen file, in this order:

    python3 swarm/phase3/accounting.py --save
    python3 swarm/phase3/report3.py --save
    git add -A . && python3 swarm/phase3/freeze.py write
    python3 swarm/phase3/handover.py && git add -A . && python3 swarm/phase3/freeze.py write
    python3 swarm/phase3/handover.py --check && python3 swarm/phase3/freeze.py check

## What can be built on, and how

- **A development team of up to twenty agents at once**: `team.py` with a team file (lanes,
  each owning paths), `CONTRACT2.md` as the shape of a contract, `RUNBOOK-TEAM2.md` as the
  runbook, `lane_guard.py` as the net. Run it in a clean session: there a development
  agent's first request was about 9,000 tokens, against about 124,000 in a session that
  carries other projects' instructions. Two rounds are measured: 20 agents in 739 s and 16
  agents in 406 s. A lane that changes a path it does not own is rejected when the lanes
  are joined.
- **Lean workers behind a gate**: `hook.py`, `guard.py`, `kit3.py`, `taskqueue.py`,
  `handin.py`, `ledger.py`, `stage3.py`. The two-step queue worker cost about 24,600 input
  tokens for a small task.
- **Keep an orchestrating session short.** The cost that grew fastest was not the workers.
  An orchestrator that starts a thousand agents in one conversation reads its whole
  conversation again with every message. Split long runs across sessions, or keep each
  agent's answer out of the orchestrator's context.
- `.claude/settings.json` sets the gate for every session started in this repository. It
  does nothing unless `swk-hook` is on the path. `stage3.py setup` and `team.py setup`
  install it; run them only in a session that does nothing else.
