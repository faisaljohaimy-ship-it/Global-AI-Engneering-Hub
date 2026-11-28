# Attack on the session gate (hook.py), lane H1

Every row was run as a test in `tests/test_p3_hook_attack.py`, against `hook.decide` or against the installed
program (written with `hook.wrapper`, run as a subprocess). "Held" means the call was refused (or, for the
orchestrator, passed by design) before the fix too; "Hole" means a forbidden call got through.

| Attack | Before | Fix |
|---|---|---|
| `agent_type` or `agent_id` as a list, a number, empty, blank, or null, with the other field absent | Hole: a non-string was read as "absent", so a call with a list type and no id passed as the orchestrator | A field that is present but not one clean non-empty string marks the caller as unreadable: refused, hand-back included |
| The two spellings disagreeing (`agent_type` against `agentType` against `subagent_type`, ids likewise) | Hole: the first spelling won, so a worker type beside a foreign type was judged as the worker | All spellings present must be the same string, else refused |
| Type with an id missing | Hole: a worker type with no id was judged as a worker | An agent must carry both type and id, else refused |
| Type that only starts with a worker name (`swarm-lightning`, `swarm-light;id`, trailing space or newline) | Hole: the check was a prefix match | Whole-string match: `swarm-(light/queue/large/probe)` plus up to three `-name` parts of `[a-z0-9]` |
| Case (`Swarm-Light`, `SWARM-DEV`), `swarm-developer`, `swarm-dev ` | Held | Test added |
| Same key twice in the JSON document (top level or inside `tool_input`) | Hole: the last value won, which another reader may not take | Duplicate keys anywhere refuse the call |
| Tool name `bash`, `BASH`, `Bash `, list, number, null, object | Held (exact match) | Test added; the hand-back test now also requires a string |
| Hand-back name carrying a command (`SubagentHandback; rm -rf /`, wrong case, trailing space) | Held (exact match) for the decision. Hole in the record: the name was written to the record as it came | See the record row |
| `tool_input` missing, a list, a string, `command` a list, a number, null, or spelt otherwise | Held | Test added |
| Command of one million characters | Held, but only because the pattern did not match; the cost was not bounded | Refuse above 100,000 characters before any pattern runs |
| NUL in a command | Hole: a quoted here-document body could hold NUL | Refuse |
| Bytes that are not UTF-8, a byte-order mark, NUL on standard input, lone `NaN`, `1e999999`, 100,000 nested brackets | Held (any fault ends in status 2) | Input is now read as bytes and decoded strictly, so the decoding is explicit; tests added |
| Record path is a folder | Held for an agent's allowed call (the write failed, so refused); a refused call was refused anyway | Test added |
| Record path is a symbolic link | Hole: the gate wrote through the link into its target | Open with `O_NOFOLLOW`, and only a regular file is written |
| Record path is a pipe nobody reads | Hole: the gate hung on open, and the host's behaviour on a gate that does not end was not measured | Open with `O_NONBLOCK`: fails at once, so the call is refused |
| 200 processes recording at once | Held: 200 whole lines, 200 distinct agent hashes (40 at a time on this machine) | A short write now counts as a failure to record. Line length is bounded, which keeps one write whole |
| Tool or agent or field names with content, or 100,000 characters long, written to the record | Hole: `str(tool_name)`, the agent type and the field names were recorded as sent, so content could reach the record and a line could grow without bound | Only a name of up to 80 characters of `[A-Za-z0-9_.:-]` is recorded; else `(unreadable)`; at most 60 field names; a type that does not parse is recorded as `(unreadable)` |
| A worker type calling `Agent`, `Task`, `ToolSearch`, `SendMessage`, any `mcp__` tool, `Skill`, `TodoWrite` | Held | Test added |

All decisions in `hook.CASES` and in `tests/test_p3_gate.py` still hold. One test in that file,
`RunTests.test_no_stage_is_opened_when_the_installed_gate_is_gone`, fails on this branch before and after this
change (it fails with the original `hook.py` too); it is outside this lane's files.

## What this gate cannot decide

- The orchestrator passes by design. A call that carries neither field is judged to be the orchestrator. If the host
  ever left both fields out of an agent's call, that call would pass. The test marked as an expected failure shows it.
  The host's own report is the only source, and it is trusted.
- A field the host sends as present but null is refused as unreadable. If the host sent null for the orchestrator,
  the orchestrator would be stopped; the measured behaviour is that it sends neither field.
- What the host does when a gate runs out of time, or is killed, was not measured. Status 2 is the only ending the
  host was measured to treat as a refusal, and the wrapper maps every other ending of the program to 2, but a wrapper
  that is itself killed cannot do that.
- The gate does not look inside a here-document body that `guard.allowed` accepts, other than for length and NUL. What
  `swk` does with that text is the concern of the kit.
- `lane_guard` decides a development agent's calls; this lane tested only that a type that is not exactly `swarm-dev`
  never reaches it.
- Whether a symbolic link or a folder sits in the path above `SWARM_HOME/p3` was not tested; only the record file is
  protected.
- The record is private and not signed: whoever can write to `SWARM_HOME` can alter it.

## What was done about each finding

Added by the session that set the review, after it.

- The test of the run that failed in the lane's session (`test_no_stage_is_opened_when_the_installed_gate_is_gone`) found a gate installed for the whole machine by the team's own setup. The run's tests now leave such folders out of their path.
- A call that carries neither agent field still passes as the orchestrator: the gate cannot tell. What catches it is the ledger: the gate is compared with the host's records agent by agent, and a call in a record that the gate did not judge as that agent's ends the run (`ledger.build`).
- Since this review the gate also lets each agent draw a first task from a queue once, and refuses a draw under a name with no ticket (`hook.first_draw`).
