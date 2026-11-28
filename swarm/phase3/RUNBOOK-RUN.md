# Runbook: the third phase's run to 1,000 agents, in a clean session

You are the orchestrator of a measured experiment. The plan is fixed in `PLAN3.json`. You
run it. You do not redesign it, improve it or skip parts of it.

What is already known about this host, from the second phase: it runs at most 20 agents at
once and makes the rest wait their turn. A stage of 1,000 agents is 1,000 real agents
started and finished, not 1,000 at the same moment. Start them as the card says and let
the host pace them.

## Rules

- Work only in this repository, on the branch `claude/swarm-phase-3`. Never merge it
  anywhere else, never force-push, never touch another branch or another repository.
- Extra budget is zero: no paid service, no API key, no other account. Stop at the first
  message about a usage limit or a rate limit and report it.
- Start agents only as a stage card tells you: that agent type, that model, that effort,
  that prompt, that many. Nothing else may start an agent: no workflow, no helper agent.
- Do not help a worker, repeat a stage, or repair a worker's output. A failed task is a
  result.
- Do not open task folders, withheld tests or agents' records yourself. The scripts read
  them.
- Do not edit anything under `swarm/` except what the scripts write in
  `swarm/phase3/evidence/`, `swarm/phase3/state/` and `swarm/phase3/RESULTS.md`. If a script
  fails, do not patch the experiment: stop and say so in your last message.
- Nothing private goes into a commit: no path outside the repository, no record content,
  no model identifier.
- Keep your own messages between stages to one short line. Every word you write is read
  again on each later turn.

## Steps

1. `swarm-queue-1`, `swarm-queue` and `swarm-probe` must be among the agent types you can
   start. If they are not, stop and say so in your last message.

2. Set up, and read what it prints. `worker_command` and `session_record_found` must be
   true; if not, stop.

       python3 swarm/phase3/stage3.py setup

3. Run the stages. Repeat until the last line of `finish` begins with `END`:

   a. `python3 swarm/phase3/stage3.py prep` prints the card of the next stage. If it prints
      `END`, go to step 4.

   b. Start the agents of the card, in the foreground (`run_in_background` false), with
      `subagent_type`, `model` and `effort` as on the card: the owner asked for them to be
      set per kind of work, so this is an explicit instruction to set them. Put as many
      Agent calls in one message as the card says, and send the next message of the stage
      as soon as the one before has returned, with nothing in between.

   c. When every agent of the stage has returned, whatever it answered:
      `python3 swarm/phase3/stage3.py finish`

   d. Save the stage:

          git add swarm/phase3/evidence swarm/phase3/state
          git commit -q -m "Third phase: stage <id>"
          git push -q origin claude/swarm-phase-3

      The last line of `finish` is `NEXT <id>` or `END - <why>`. Do what it says.

4. At the end:

       python3 swarm/phase3/stage3.py report
       git add swarm/phase3 && git commit -q -m "Third phase: results of the run" && git push -q origin claude/swarm-phase-3

5. End with one message: the stages that ran, the largest number of agents that ran at
   once, how many Agent calls one message held at most, the last line of the last
   `finish`, and anything that did not go as this runbook says. Then stop. Do not open a
   pull request: one exists for this branch.
