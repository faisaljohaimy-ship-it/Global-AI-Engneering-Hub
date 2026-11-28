# Runbook: the development team of the third phase, in a clean session

You start twenty development agents at once, one per lane, and then join what they made.
You do not write the parts yourself, and you do not repair them.

## Rules

- Work only in this repository, on the branch `claude/swarm-phase-3`. Never merge it
  anywhere, never force-push, never touch another branch of the remote or another
  repository. The lane branches `claude/p3-*` stay local: do not push them.
- Extra budget is zero: no paid service, no API key, no other account. If any agent
  reports a usage limit or a rate limit, start no further agent.
- Start agents only as the card says. No workflow, no helper agent, no second round.
- Do not edit the lanes' work and do not retry a lane. A lane that is rejected or fails is
  a result; the session that started you decides what happens to it.
- Nothing private goes into a commit: no path outside the repository, no record content,
  no model identifier.

## Steps

1. `swarm-dev` must be among the agent types you can start. If it is not, stop and say so
   in your last message.

2. Set up. It makes one worktree and one local branch per lane beside the repository and
   prints the card:

       python3 swarm/phase3/team.py setup

3. Start the agents of the card: one message holding one Agent call per lane, so that all
   twenty run at once. For each call: `subagent_type`, `model` and `effort` as on the card
   (the owner asked for them to be set per kind of work, so this is an explicit instruction
   to set them); `description` and `prompt` are the lane id, such as `LANE-E2`, and nothing
   else; `run_in_background` is false.

4. When every agent has returned, whatever it answered:

       python3 swarm/phase3/team.py integrate

   It checks that each lane changed only its own paths, merges the lanes that did, runs
   each lane's tests and then the whole suite, and writes
   `swarm/phase3/evidence/team.json`.

5. Save and push:

       git add swarm/phase3/evidence
       git commit -m "Third phase: the team's lanes joined"
       git push origin claude/swarm-phase-3

6. End with one message that gives the table `integrate` printed and its two last lines.
   Then stop. Do not open a pull request: one exists for this branch.
