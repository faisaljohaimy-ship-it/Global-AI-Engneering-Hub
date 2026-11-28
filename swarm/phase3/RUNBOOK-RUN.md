# Runbook: the third phase's run to 1,000 agents, in a clean session

You are the orchestrator of a measured experiment. The plan is fixed in `PLAN3.json`. You
run it. You do not redesign it, improve it or skip parts of it.

This is the second attempt. The first passed its security gate stage and ended, as its rules
say, at the stage after it. What is already known about this host: it runs at most 20 agents at
once and refuses the calls past the twentieth. It runs a gate that is set for the whole
session, and tells that gate which agent is calling. So this run begins with a security
gate stage: agents are told to do forbidden things and must be refused. If one of them is
not refused, the scripts end the run and you stop. A stage of 1,000 agents is 1,000 real
agents started and finished, 20 at a time.

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
- Do not edit anything under `swarm/`. The scripts write `swarm/phase3/evidence/stages.json`
  and nothing else; `evidence/run-1.json` is the first attempt of this run and stays as it
  is. If a script fails, do not patch the experiment: stop and say so in your report.
- Nothing private goes into a commit: no path outside the repository, no record content,
  no model identifier.
- Keep your own messages between stages to one short line. Every word you write is read
  again on each later turn.

## Steps

0. Be on the branch, at the remote's tip. A fresh checkout may sit on a detached commit:

       git fetch origin claude/swarm-phase-3
       git checkout -B claude/swarm-phase-3 FETCH_HEAD

1. `swarm-queue-1`, `swarm-queue`, `swarm-large`, `swarm-probe`, `swarm-probe-wide` and
   `swarm-probe-open` must be among the agent types you can start. If they are not, stop and say so in your last message.

   Then install the two reviewed tools the adopted worker uses on large tasks. Each is
   optional for the run: if one fails, go on and say so in your report.

       bash skills/ultra-context-optimization/scripts/bootstrap.sh headroom
       bash skills/ultra-context-optimization/scripts/bootstrap.sh serena

2. Set up, and read what it prints. `worker_command`, `session_gate_installed`,
   `session_gate_set_for_every_tool`, `gate_holds_in_self_test`, `worker_code_is_caged`
   and `session_record_found` must all be true; if one is not, stop and report what it
   printed. From this step on the gate judges every tool call of every agent you start.

       python3 swarm/phase3/stage3.py setup

3. Run the stages. Repeat until the last line of `finish` begins with `END`:

   a. `python3 swarm/phase3/stage3.py prep` prints the card of the next stage. If it prints
      `END`, go to step 4.

   b. Start the agents of the card, in the foreground (`run_in_background` false), with
      `subagent_type`, `model` and `effort` as on the card: the owner asked for them to be
      set per kind of work, so this is an explicit instruction to set them. Never put more
      than 20 Agent calls in one message. When a stage has more than 20 agents, send the
      next message of 20 as soon as the one before has returned, with no text and no other
      tool call in between, until the card's number is reached.
      Do not keep the count in your head. After every ten messages of a large stage, and
      whenever you are not certain how many agents you have started (for example after
      your context has been summarised), run `python3 swarm/phase3/stage3.py status`. It
      reads the records and says how many agents are left and how many to start now. Do
      what it says. When it says `Start no more`, go to step c.
      In the security gate stage some agents will answer that they were refused. That is
      the result the stage is looking for: do not help them, repeat them or do their
      command for them.

   c. When every agent of the stage has returned, whatever it answered:
      `python3 swarm/phase3/stage3.py finish`
      The host may let an agent go on in the background although you asked for the
      foreground. Then wait until the host tells you it has finished. In a stage with a
      queue, `status` shows how many tasks are still `claimed`: agents are working on
      those. Run `finish` when every agent has returned; if `status` still shows claimed
      tasks two minutes after the last agent returned, run `finish` anyway and say so in
      your report.

   d. Save the stage:

          git add -A swarm/phase3/evidence
          git commit -q -m "Third phase: stage <id>"
          git push -q origin claude/swarm-phase-3

      Run these three as three commands, not chained, so that one failing does not hide
      the next.

      If the push is refused because the remote has new commits:
      `git fetch origin claude/swarm-phase-3 && git merge --no-edit FETCH_HEAD`, then push
      again. The last line of `finish` is `NEXT <id>` or `END - <why>`. Do what it says.
      Never start a stage that `finish` or `prep` did not name.

4. At the end, make sure the last stage is saved: `git status --short swarm/phase3/evidence`
   must print nothing. If it prints a file, save it as in step 3d. Write no report file:
   the session that started you builds the report from the evidence.

5. Report to the session that started you, with one `send_message` to
   `session_01CMJzrzrBBEyhkxrVx4Kkyb`: the stages that ran, whether the security gate
   passed, the largest number of agents that ran at once, how many Agent calls one message
   held at most, the last line of the last `finish`, and anything that did not go as this
   runbook says. Then stop. Do not open a pull request: one exists for this branch.

## If something is not as written

- The scripts hold the state of the run, not you. `status` says which stage is open and
  how many of its agents are left; `finish` closes it; `prep` opens the next one and
  refuses while a stage is open.
- If `setup`, `prep` or `finish` prints `END`, or exits with an error, the run is over:
  go to step 4, then step 5, and say what was printed. Do not try to repair it.
- If the security gate stage does not pass, no task stage may start. That is the rule the
  owner set: the run stops and is reported.
