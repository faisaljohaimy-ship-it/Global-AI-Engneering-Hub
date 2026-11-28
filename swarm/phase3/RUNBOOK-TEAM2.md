# Runbook: the second round of the development team, in a clean session

You start sixteen development agents at once, one per lane, and then join what they made.
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
- From step 2 on a gate judges every tool call of every agent you start, and refuses what
  it does not know. Your own calls pass. If an agent reports that it was refused, that is a
  result: do not do its command for it.

## Steps

1. `swarm-dev` must be among the agent types you can start. If it is not, stop and say so
   in your last message.

2. Set up. Every command of this runbook that names `team.py` needs the team file in
   front of it, exactly as written here:

       SWARM_TEAM_FILE=TEAM2.json python3 swarm/phase3/team.py setup
       python3 swarm/phase3/hook.py selftest

   The first makes one worktree and one local branch per lane beside the repository and
   prints the card. The second must print `"holds": true`. If it does not, stop and report
   what it printed: start no agent.

3. Start the agents of the card: one message holding one Agent call per lane, so that all
   sixteen run at once. For each call: `subagent_type`, `model` and `effort` as on the card
   (the owner asked for them to be set per kind of work, so this is an explicit instruction
   to set them); `description` and `prompt` are the lane id, such as `LANE-H2`, and nothing
   else; `run_in_background` is false.

4. When every agent has returned, whatever it answered:

       SWARM_TEAM_FILE=TEAM2.json python3 swarm/phase3/team.py integrate
       python3 swarm/phase3/hook.py report --save

   The first checks that each lane changed only its own paths, merges the lanes that did,
   runs each lane's tests and then the whole suite, and writes
   `swarm/phase3/evidence/team2.json`. The second writes what the gate saw, as counts.

5. Save and push:

       git add -A swarm/phase3/evidence
       git commit -m "Third phase: the second round's lanes joined"
       git push origin claude/swarm-phase-3

   If the push is refused because the remote has new commits:
   `git fetch origin claude/swarm-phase-3 && git merge --no-edit FETCH_HEAD`, then push
   again.

6. Report to the session that started you, with one `send_message` to
   `session_01CMJzrzrBBEyhkxrVx4Kkyb`: the table `integrate` printed, its last two lines,
   and anything that did not go as this runbook says. Then stop. Do not open a pull
   request: one exists for this branch.
