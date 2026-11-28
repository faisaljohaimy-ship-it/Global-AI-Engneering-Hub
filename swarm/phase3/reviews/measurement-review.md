# Review of the measurements (lane H12)

Question: can a number in the evidence be wrong, double counted or made up? Every finding has a proof in
`tests/test_p3_review_measurement.py`. A test marked `expectedFailure` shows the fault; a plain test shows a property that holds.
No code was changed. Figures below were computed from the repository's own evidence by those tests or by `stage3.carried_over()`.

## Figures recomputed

- The second phase's 21 stages (none skipped) sum to 29,793,041 input tokens (uncached + cache write + cache read, summed by hand) and
  496,294 output tokens; `carried_over()` uses the same 29,793,041.
- `carried_over()` total is 72,125,176 = 36,168,638 (first phase) + 2,219,321 (second phase trial) + 29,793,041 (second phase stages)
  + 3,896,199 (the 20 development agents of `team.json`, equal to the sum of its lanes) + 47,977 (probe allowance). The limit is 150,000,000, so
  the run starts with 77,874,824 left.
- No part is counted twice: the first phase's figure is its own agents + its review agents + its minimal worker (arithmetic checked); the
  second phase's trial is read from the second plan, not from its stages; PLAN3's own preflight is 0, so `stage.decide` does not add it again;
  `carried_over()` reads `team*.json` only, never the run's own `stages.json`. Skipped stages are excluded in both places.
- What it does not contain: what the orchestrating sessions read (second phase's: 19,656,431 input tokens, reported apart; the first phase's,
  the trial's, the team session's and this run's are not given anywhere), the 20 development agents of this round (no evidence file holds
  them yet), any agent of another type that ran during a stage (see F3), and agents that wrote no record (F5).
  Also: "input tokens" counts the whole context again on every reply (cache reads included), so it is a context-read count, not unique text.

## Findings

F1. `swarm/phase3/stage3.py`, `carried_over()` - the document names only the second phase's orchestrator as left out.
  Distorts: the reader's idea of the 72.1 M. The orchestrating sessions of the other phases and this round's lanes are missing and unnamed;
  the second phase's orchestrator alone is 19.7 M, 27 % of the carried figure, so the others are not small. Also the 47,977 allowance is the
  second phase's `p1` figure copied (proved equal), an estimate; it is named as an allowance in the part's key but not said to be a copy.
  Fix: extend `reported_apart.note` to list what is not counted, and add `this_round_development_agents: not yet in evidence`.
  Test: `test_the_document_names_what_is_left_out`.

F2. `swarm/phase3/stage3.py`, `judge_gate()` - a refused-probe passes if the agent had ANY refused call, not the one it was told.
  A probe told `git push` that only tried `ls` (refused) passes; an allow-probe told `swk status` passes after `swk next`.
  Distorts: the gate stage's verdict, the one number the whole run is allowed to start on. Fix: `ledger.calls` also returns each call's
  command; require a refused (or allowed) call whose input matches the probe's prompt.
  Tests: `test_a_probe_passes_though_it_never_attempted_the_forbidden_call`, `test_a_probe_told_one_allowed_command_passes_with_another`.
  Holds: an agent that did nothing, an agent never started, and a forbidden call that ran each fail the stage.

F3. `swarm/phase3/stage3.py` `judge_gate()` / `ledger.py` - "refused by the host" counts as a refusal of the gate.
  A probe whose call the host denied (`Permission ... has been denied`) passes with `of_them_by_the_gate` = 0; the host's refusals are also
  left out of the reconciliation, so the gate can pass the stage without ever having been asked. Fix: require `of_them_by_the_gate >= 1` for
  every refuse-probe (the field is already computed). Test: `test_a_probe_passes_when_the_host_refused_and_the_gate_never_saw_the_call`.

F4. `swarm/phase2/stage.py`, `finish()` - an agent of another type is counted into a stage or hidden from it.
  Probe branch: every new record with a reply is a row, whatever its type, so one stray agent raises `actual_agents` (2 instead of 1) and its
  tokens enter the stage and the limit. Task branch: a record is kept if its prompt names a task of the stage, not by type (a reviewer reading
  a task is counted as a worker, 2 instead of 1); a stray record naming no task is in no token figure at all (only a count in
  `ledger.agents_of_other_types_started_during_the_stage`, with no tokens). Distorts: `actual_agents`, `agent_tokens`, and the limit check.
  Fix: filter rows by `agent_type` from the meta file for both kinds, and report the other types' tokens in a separate field that `decide` adds to
  the limit. Tests: `test_an_agent_of_another_type_started_during_a_probe_stage_is_counted_into_it`,
  `..._whose_prompt_names_a_task_is_counted_into_a_task_stage`, `..._with_no_task_id_is_in_no_total`.

F5. `swarm/phase2/stage.py`, `finish()` / `decide()` - an agent that started and wrote no record, or only a prompt, leaves no trace.
  `if row["roundtrips"]` drops a record with no reply; nothing counts the dropped ones. A task stage ends only when fewer than half the
  registered agents have records, and notes nothing for a quarter missing (3 of 4). Distorts: tokens (understated by the missing agents) and
  `actual_agents`. Fix: count and print records without a reply; add a note when `actual_agents < registered_agents`.
  Tests: `test_a_record_with_no_reply_leaves_no_trace`, `test_a_task_stage_with_a_missing_agent_is_noted`.

F6. `swarm/phase2/stage.py`, `finish()` - a record from an earlier stage that was still running is read in full.
  Records are excluded by file name (`before`); a straggler that opened before the stage but wrote its file after the snapshot, or a record
  left running, brings its earlier lines. Proved with a record that began an hour earlier: probe `wall_seconds` is 3,602 instead of a few seconds.
  Distorts: `wall_seconds` and so every rate built on it. Fix: read rows with the stage's window `measure.read(path, start, end)`.
  Test: `test_a_record_that_began_before_the_stage_stretches_its_wall_time`. Holds: a record listed in `before` is left out.

F7. `swarm/measure.py`, `stage()` and `swarm/phase2/stage.py` probe branch - zero or missing time divides by zero or fails.
  One record whose lines all share one instant gives wall = 0 and `ZeroDivisionError` (effective_concurrency, tasks_per_minute); records with no
  timestamps give `TypeError`. `finish()` stops before saving, the stage stays open, nothing wrong is printed as a rate. Fails closed but
  loses the stage's measurement. Fix: `wall = max(wall, 0.001)` or print `None` for the rates. Tests: `test_a_record_that_starts_and_ends_at_one_instant_divides_by_zero`,
  `test_a_stage_whose_records_carry_no_timestamps_fails`. Holds: zero verified tasks print rate 0.0 and no per-task cost; zero agents build the result
  without any division (no rate keys).

F8. `swarm/phase2/stage.py`, `decide()` - projection from a stage with zero tokens is 0, so the limit check cannot skip.
  `projected_for_stage = tokens per agent of the last alike stage x agents`. Fix: when the projection is 0 use `margin_without_projection`.
  Test: `test_the_projection_from_a_stage_with_zero_tokens_is_zero_and_lets_any_stage_start`.

F9. `swarm/phase2/stage.py`, `decide()` - the projection carries no margin, so the run can pass the limit by one stage.
  A stage projected to end exactly at the limit starts; it is projected from the last alike stage's mean (20 agents for the 200- and
  1000-agent stages' neighbours) and no rule stops it or ends the run during or after it (`decide(stages, None)` has no end reason for input
  tokens). The overrun is the projection's error times the stage's size, up to the whole stage. The counted figure also leaves out the
  orchestrator and other types (F4), so the real use is higher than the figure compared with the limit. Fix: skip when
  `spent + projection * 1.25 > limit` (the factor an estimate to be set by the owner), and end when `spent > limit`.
  Tests: `test_a_projection_that_fits_by_one_token_starts_the_stage`. Holds: a projection past the limit skips, and a run already past it
  skips every next stage.

F10. `swarm/measure.py`, `read()` and `swarm/phase2/stage.py`, `extra()` - a reply with neither `message.id` nor `requestId`, written on
  several lines, is counted once per line. The host writes an id, so this is low severity; the same key in both functions keeps them consistent.
  Fix: skip a usage when the key is missing, or key by the previous line's reply. Test: `test_a_reply_with_no_id_written_on_two_lines_is_counted_twice`.

F11. `swarm/phase3/ledger.py`, `build()` - the gate is reconciled by totals per agent type.
  A gate line of an agent whose record is not among the paths (a straggler, an agent with no record) offsets a call of another agent that
  no line covers. Also `stage3.finish` takes gate lines of the type from the stage's start with no end. Distorts: `gate.reconciled`.
  Fix: compare per agent using `who` (a hash of the agent id) against the record's agent id, in both directions.
  Test: `test_a_call_the_gate_missed_is_hidden_by_a_gate_line_of_an_agent_with_no_record`.

## Found sound

- A reply written on several lines is counted once and the last line's usage wins (partial output counts do not add); `extra()` agrees.
- The window of `measure.read` counts only replies inside it; an untimed line passes every window (low risk, the main-session row only).
- `peak()` does not count agents that only touch as overlapping, and leaves out untimed records.
- A record in `before` is left out. A stage finished twice: the second `finish` stops (no open marker), and a re-run replaces the stage's row
  instead of adding one, so no double count.
- Stages with zero verified tasks, zero agents: no division by zero, no rate. A stage past the limit is never started.
- The gate record's window is inclusive, drops lines with no time and lines that cannot be read (this fails closed); `t` is rounded to a hundredth
  of a second, which matters only for a call within 5 ms of the stage opening; both clocks are the same host's.
- The gate stage fails when a probe agent did nothing, was never started, or a forbidden call ran; the host's own answers (hand-back, denials) are
  left out of the "gate must have seen" count, as intended.
- The carried total: each part is counted once, `total` equals the sum of the parts, and the document's own parts equal the sources.
