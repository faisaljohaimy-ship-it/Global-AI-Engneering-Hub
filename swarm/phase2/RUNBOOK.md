# Runbook: the second phase, in a clean session

You are the orchestrator of a measured experiment. The plan is fixed in `PLAN.json`. You run
it. You do not redesign it, improve it or skip parts of it.

Why a clean session: a worker starts with every instruction file of its session in its
context. In the authoring session that was about 128,000 tokens for each worker. A session
that holds only this repository starts each worker far lower, and the worker definitions in
`.claude/agents/` are loaded only when a session starts.

## Rules

- Work only in this repository, on the branch `claude/swarm-phase-2`. Never merge, never
  force-push, never touch another branch or another repository.
- Extra budget is zero: no paid service, no API key, no other account. Stop at the first
  message about a usage limit or a rate limit and report it.
- Start agents only as a stage card tells you: that agent type, that model, that effort,
  that prompt, that many. Nothing else may start an agent: no workflow, no helper agent.
- Do not help a worker, repeat a stage, or repair a worker's output. A failed task is a
  result.
- Do not open task folders, withheld tests or agents' records yourself. The scripts read
  them.
- Do not edit anything under `swarm/` except what the scripts write in
  `swarm/phase2/evidence/`, `swarm/phase2/state/` and `swarm/phase2/RESULTS.md`. If a script
  fails, do not patch the experiment: stop and report (step 6).
- Nothing private goes into a commit: no path outside the repository, no record content,
  no model identifier.

## Steps

1. Check your agent types. `swarm-light`, `swarm-light-2`, `swarm-light-inline`,
   `swarm-large` and `swarm-probe` must be among the agent types you can start. If they are
   not, stop: go to step 6 and say so.

2. Install the two reviewed tools the large tasks use. Each is optional for the experiment:
   if one fails, go on and say so at the end.

       bash skills/ultra-context-optimization/scripts/bootstrap.sh headroom
       bash skills/ultra-context-optimization/scripts/bootstrap.sh serena

3. Set up, and read what it prints:

       python3 swarm/phase2/stage.py setup

   `worker_command`, `gate` and `session_record_found` must be true. If one is false, stop
   and report.

4. Run the stages. Repeat until the last line of `finish` begins with `END`:

   a. `python3 swarm/phase2/stage.py prep` prints the card of the next stage. If it prints
      `END`, go to step 5.

   b. Start the agents of the card. Write one message that holds one Agent call for every
      agent of the stage, so that they all run at once. For each call:
      `subagent_type`, `model` and `effort` as on the card; `description` is the task id;
      `prompt` is exactly what the card says, and for most stages that is the task id and
      nothing else; `run_in_background` is false. If the host does not accept that many
      calls in one message, put as many as it accepts in the first message and the rest in
      the next, and report that at the end.

   c. When every agent has returned, whatever it answered:
      `python3 swarm/phase2/stage.py finish`

   d. Save the stage:

          git add swarm/phase2/evidence swarm/phase2/state
          git commit -m "Second phase: stage <id>"
          git push origin claude/swarm-phase-2

      Its last line is `NEXT <id>` or `END - <why>`. Do what it says. Do not start a stage
      it did not name.

5. At the end:

       python3 swarm/phase2/stage.py report
       git add swarm/phase2 && git commit -m "Second phase: results" && git push origin claude/swarm-phase-2

6. Report to the session that started you, with one `send_message` to
   `session_01CMJzrzrBBEyhkxrVx4Kkyb`: the stages that ran, the largest number of agents
   that ran at once, the last line of the last `finish`, and anything that did not go as
   this runbook says. Then stop. Do not open a pull request: one exists for this branch.

## What the scripts decide, so that you do not

- which stage is next, and whether its projected cost fits under the limit of 150,000,000
  input tokens that counts the first phase as well;
- whether the experiment ends: a usage or rate limit, a security finding in a worker's
  output, a worker that got a command past its gate, a machine limit, or a stage where
  fewer than 60% of the tasks pass their withheld tests;
- what counts as passed: the withheld tests, run with no network and no inherited
  environment.
