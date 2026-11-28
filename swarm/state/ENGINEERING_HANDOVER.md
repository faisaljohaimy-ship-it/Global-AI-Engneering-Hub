# Handover: swarm experiment

Branch `claude/swarm-100x100`, stacked on `claude/ultra-context-optimization`. Nothing here touches a product,
a production deployment or the control plane. All work data was generated; none is from a real project.

## Decisions, and why

1. **Real agents were started by the host's agent tool, in one batch per stage.** A script cannot start an agent, and
   a batch that returns together costs the orchestrator two turns a stage instead of one turn per agent.
2. **Workers ran on the lightest model with low effort; the two benchmark agents on the middle model.** The work was
   routine; `route.py` gives the same answer. The session's own model was used only to orchestrate.
3. **Ownership uses `engineering_os.orchestration.TaskStore`,** not a new store. The experiment acted as orchestrator
   for its own forty tasks in a private state folder. Tasks end in `review`: the store wants three independent
   approvals and only the testing one exists.
4. **Limits were fixed before the first run** (`protect.py`). One was amended after stage one and is marked in the
   code: the orchestrator-share rule now applies from two agents up.
5. **The ladder stopped at twenty agents** because two of those limits said so. Stages 25 to 100 were not run.
6. **Configurations A to D were compared mostly by a scripted trace,** with one real agent for A and one for D,
   because the token limit left room for no more.
7. **No lifecycle hook, proxy or wrapper was installed.** Nothing changed how model requests are sent.

## What a reviewer should look at

- `evidence/ladder.json` against the table in `README.md` (a test checks they agree).
- `protect.py`: the limits and the one amendment.
- `evidence/tool-audit.json`: four workers called session-control tools they were never asked to use. The host
  refused all four. A worker type with only file tools would remove the risk; it needs a session restart to load.
- The hub now has two Headroom integrations: `tools/headroom_context.py` on main and `hr` in the
  context-optimization skill. Both were run here. The first handles JSON with stronger isolation and returns logs
  and search results unchanged; the second also calls Headroom's log, search and diff transforms. They should
  become one.

## To resume

`state/TASK_STATE.json` says what is done and gives the command for the next stage. The task store's checkpoint
restores into an empty store with the same checksum (`state/TEST_EVIDENCE.json`). Codex has not run any of this;
the scripts are plain Python and need only the hub.
