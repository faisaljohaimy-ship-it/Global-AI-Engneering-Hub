"""Independent review of the measurements: can a number in the evidence be wrong, double counted or made up?

Each test is a proof. A normal test shows a property that holds. A test marked expectedFailure shows a fault
in a file this lane does not own; swarm/phase3/reviews/measurement-review.md says what each one distorts.
No agent and no model is started; stand-in records are written in the form the host writes them."""
import copy
import datetime
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
P2, P3 = ROOT / "swarm" / "phase2", ROOT / "swarm" / "phase3"
sys.path[:0] = [str(P3), str(P2), str(ROOT / "swarm")]
import ledger  # noqa: E402
import measure  # noqa: E402
import stage  # noqa: E402
import stage3  # noqa: E402
import tasks  # noqa: E402

PLAN3 = json.loads((P3 / "PLAN3.json").read_text())
SECOND = json.loads((P2 / "evidence" / "stages.json").read_text())
START = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc).timestamp()


def iso(seconds):
    return datetime.datetime.fromtimestamp(START + seconds, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def usage(context=1000, output=50, fresh=10):
    return {"input_tokens": fresh, "cache_creation_input_tokens": 0, "cache_read_input_tokens": context - fresh, "output_tokens": output}


def record(folder, name, kind, prompt, begin=0.0, replies=2, calls=(), stamped=True, reply_usage=None):
    """A record the way the host writes one: a prompt, then `replies` replies of one text block each, with the calls in the first."""
    when = (lambda s: {"timestamp": iso(s)}) if stamped else (lambda s: {})  # noqa: E731
    lines = [{"type": "user", **when(begin), "message": {"role": "user", "content": prompt}}]
    for index in range(replies):
        content = [{"type": "text", "text": "DONE" if index == replies - 1 else "working"}]
        if index == 0:
            content += [{"type": "tool_use", "id": f"{name}-t{n}", "name": tool, "input": given} for n, (tool, given, _, _) in enumerate(calls)]
        lines.append({"type": "assistant", **when(begin + 1 + index), "message": {"id": f"{name}-{index}", "model": "claude-haiku-4-5",
                                                                                   "usage": reply_usage or usage(), "content": content}})
        if index == 0 and calls:
            lines.append({"type": "user", **when(begin + 1.5), "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"{name}-t{n}", "content": back, "is_error": failed} for n, (_, _, back, failed) in enumerate(calls)]}})
    path = pathlib.Path(folder) / f"agent-{name}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    path.with_name(f"agent-{name}.meta.json").write_text(json.dumps({"agentType": kind}))
    return path


class TheCarriedOverTotal(unittest.TestCase):
    def test_the_second_phase_stages_sum_to_the_figure_the_run_carries(self):
        ran = [s for s in SECOND["stages"] if not s.get("skipped")]
        by_hand = sum(s["agent_tokens"]["input_uncached"] + s["agent_tokens"]["cache_write"] + s["agent_tokens"]["cache_read"] for s in ran)
        self.assertEqual(by_hand, sum(s["agent_tokens"]["input_total"] for s in ran))
        self.assertEqual(by_hand, stage3.carried_over()["parts"]["second_phase_stages"])
        self.assertEqual(SECOND["figures"]["input_tokens_counted"], PLAN3["caps"]["first_phase_input_tokens"] + json.loads((P2 / "PLAN.json").read_text())["caps"]["preflight_input_tokens"] + by_hand)
        self.assertEqual(len(SECOND["stages"]), len({s["label"] for s in SECOND["stages"]}), "a stage label appears twice in the second phase's evidence")

    def test_every_part_is_counted_once_and_none_is_left_out(self):
        carried = stage3.carried_over()
        summary = json.loads((ROOT / "swarm" / "evidence" / "summary.json").read_text())["tokens"]
        teams = sorted((P3 / "evidence").glob("team*.json"))
        lanes = sum(lane["agent"]["input_tokens"] for path in teams for lane in json.loads(path.read_text())["lanes"])
        self.assertEqual(carried["parts"]["first_phase"], summary["all_agents_input_with_review"])
        self.assertEqual(carried["parts"]["second_phase_trial_in_the_authoring_session"], json.loads((P2 / "PLAN.json").read_text())["caps"]["preflight_input_tokens"])
        self.assertEqual(carried["parts"]["third_phase_development_agents"], lanes)
        self.assertEqual(carried["parts"]["allowance_for_probe_agents_of_the_team_sessions"], stage3.PROBE_ALLOWANCE * len(teams))
        self.assertEqual(set(carried["parts"]), {"first_phase", "second_phase_trial_in_the_authoring_session", "second_phase_stages", "third_phase_development_agents",
                                                 "allowance_for_probe_agents_of_the_team_sessions"})
        self.assertEqual(carried["total"], sum(carried["parts"].values()))
        # the first phase's figure already holds its own review agents, and the second phase's stages do not hold the first phase's
        full = json.loads((ROOT / "swarm" / "evidence" / "summary.json").read_text())
        self.assertEqual(summary["all_agents_input_with_review"], summary["all_experiment_agents_input"] + summary["review_agents_input"] + full["minimal_worker"]["input_total"])

    def test_a_stage_of_this_run_is_added_once_and_the_carried_figure_does_not_read_the_runs_own_evidence(self):
        self.assertEqual(PLAN3["caps"]["preflight_input_tokens"], 0, "a non-zero preflight in PLAN3 would be added a second time by stage.decide")
        self.assertFalse(list((P3 / "evidence").glob("team*.json")) and any(p.name == "stages.json" for p in (P3 / "evidence").glob("team*.json")))
        plan = copy.deepcopy(PLAN3)
        plan["caps"]["spent_before_phase2"] = 1000
        old, stage.PLAN = stage.PLAN, plan
        try:
            made = {"label": "g0", "kind": "probe", "actual_agents": 1, "agent_tokens": {"input_total": 500, "output": 5}}
            self.assertEqual(stage3.decide([made], None)[3]["input_tokens_counted"], 1500)
            self.assertEqual(stage3.decide([made, {"label": "x", "skipped": "no"}], None)[3]["input_tokens_counted"], 1500)
        finally:
            stage.PLAN = old

    def test_the_allowance_for_the_team_probe_is_a_copy_of_one_second_phase_stage(self):
        p1 = next(s for s in SECOND["stages"] if s["label"] == "p1")
        self.assertEqual(stage3.PROBE_ALLOWANCE, p1["agent_tokens"]["input_total"])
        document = stage3.carried_over()
        self.assertIn("allowance", " ".join(document["parts"]), "the part is named as an allowance, so it is labelled an estimate")

    def test_what_the_total_does_not_contain_and_what_the_document_says(self):
        """Not in the total: what the orchestrating sessions read (first phase, trial, the team session, this run), and this round's own
        development agents (no evidence file holds them yet). The document says so for the second phase's orchestrator only."""
        note = stage3.carried_over()["reported_apart"]["note"]
        self.assertIn("orchestrating sessions", note)
        self.assertEqual(stage3.carried_over()["reported_apart"]["orchestrator_of_the_second_phase_run"],
                         sum((s.get("orchestrator_tokens") or {}).get("input_total", 0) for s in SECOND["stages"]))

    def test_the_document_names_what_is_left_out(self):
        # closed since the review. It was: carried_over() in stage3.py: only the second phase's orchestrator is reported apart; the other orchestrating sessions and this round's development agents are not named
        document = stage3.carried_over()
        text = json.dumps(document["reported_apart"]).lower()
        self.assertTrue("development agents of the second round" in text or "this round" in text)
        self.assertTrue("first phase" in text and "team" in text)

    def test_the_teams_lane_figures_add_up(self):
        team = json.loads((P3 / "evidence" / "team.json").read_text())
        self.assertEqual(sum(lane["agent"]["input_tokens"] for lane in team["lanes"]), team["totals"]["input_tokens"])
        self.assertEqual(sum(lane["agent"]["output_tokens"] for lane in team["lanes"]), team["totals"]["output_tokens"])


class OneRecord(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dir = pathlib.Path(self.folder.name)

    def test_a_reply_written_on_several_lines_is_counted_once_and_the_last_line_wins(self):
        path = record(self.dir, "a", "swarm-light", "S-0001", replies=2)
        lines = path.read_text().splitlines()
        partial = json.loads(lines[1])
        partial["message"]["usage"] = usage(context=1000, output=3)  # the first line of a streamed reply carries a partial output count
        path.write_text("\n".join([json.dumps(partial), *lines]) + "\n")
        row = measure.read(path)
        self.assertEqual((row["roundtrips"], row["output"], row["input_total"]), (2, 100, 2000))
        self.assertEqual(stage.extra(path)["first_context"], 1000)

    @unittest.expectedFailure
    def test_a_reply_with_no_id_written_on_two_lines_is_counted_twice(self):
        # measure.read and stage.extra key a reply by message.id, then requestId, then the line count: with neither id a split reply is counted per line
        path = record(self.dir, "b", "swarm-light", "S-0001", replies=1)
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        reply = lines[1]
        del reply["message"]["id"]
        path.write_text("\n".join(json.dumps(line) for line in [lines[0], reply, reply]) + "\n")
        self.assertEqual(measure.read(path)["roundtrips"], 1)

    def test_a_record_with_no_timestamps_has_no_times_and_a_window_does_not_drop_it(self):
        path = record(self.dir, "c", "swarm-light", "S-0001", stamped=False)
        row = measure.read(path)
        self.assertEqual((row["start"], row["end"], row["seconds"]), (None, None, None))
        self.assertEqual(measure.read(path, START, START + 1)["roundtrips"], 2)  # untimed lines pass every window: counted into any stage's orchestrator row

    def test_a_window_counts_only_the_replies_inside_it(self):
        path = record(self.dir, "d", "swarm-light", "S-0001", replies=4)
        self.assertEqual(measure.read(path, START + 2, START + 3)["roundtrips"], 2)
        self.assertEqual(measure.read(path)["roundtrips"], 4)

    def test_the_peak_counts_touching_agents_as_not_overlapping(self):
        rows = [{"start": 0.0, "end": 5.0}, {"start": 5.0, "end": 9.0}, {"start": None, "end": None}]
        self.assertEqual(measure.peak(rows), 1)  # at a shared instant the closing edge sorts first; an untimed record is left out
        self.assertEqual(measure.peak([{"start": 0.0, "end": 5.1}, {"start": 5.0, "end": 9.0}]), 2)


def check_of(verified, total=2):
    return {"verified": verified, "tasks": total, "tests_passed": 0, "tests_total": 0, "security_findings": 0, "extra_files": 0, "mean_lines": 0,
            "attempts": 0, "kit_calls": 0, "kit_chars_out": 0, "kit_views": 0, "rows": []}


class Divisions(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dir = pathlib.Path(self.folder.name)

    def rows(self, **more):
        path = record(self.dir, "z", "swarm-light", "S-0001", **more)
        return [{**measure.read(path), **stage.extra(path)}]

    def test_zero_verified_tasks_print_a_rate_of_zero_and_no_per_task_cost(self):
        out = measure.stage("t", self.rows(), check_of(0), None, [], None)
        self.assertEqual((out["verified_success_rate"], out["tasks_per_minute"]), (0.0, 0.0))
        self.assertEqual(out["per_verified_task"], {"input_total": None, "output": None, "roundtrips": None, "agent_seconds": None})

    def test_a_record_that_starts_and_ends_at_one_instant_divides_by_zero(self):
        # closed since the review. It was: measure.stage divides by wall (effective_concurrency, tasks_per_minute); one agent whose record spans zero seconds ends stage.finish with ZeroDivisionError
        path = record(self.dir, "y", "swarm-light", "S-0001", replies=1)
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        for line in lines:
            line["timestamp"] = iso(0)
        path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
        row = {**measure.read(path), **stage.extra(path)}
        measure.stage("t", [row], check_of(1, 1), None, [], None)

    def test_a_stage_whose_records_carry_no_timestamps_fails(self):
        # closed since the review. It was: measure.stage and stage.finish (probe branch) take max/min of start and end: None when a record has no timestamps
        measure.stage("t", self.rows(stamped=False), check_of(1, 1), None, [], None)

    def test_a_stage_with_no_agents_has_no_rate(self):
        # stage.finish builds the result without measure.stage when no record was found: no division, no rate, no cost per task
        self.assertEqual(stage.total([], "input_total"), 0)

    @unittest.expectedFailure
    def test_the_projection_from_a_stage_with_zero_tokens_is_zero_and_lets_any_stage_start(self):
        # stage.decide: projected_for_stage = tokens per agent of the last alike stage x agents; zero tokens give zero and the limit check can never skip
        plan = copy.deepcopy(PLAN3)
        plan["caps"]["spent_before_phase2"] = plan["caps"]["cumulative_input_tokens"] - 1
        spec = next(s for s in plan["stages"] if s["id"] == "q200")
        empty = {"label": "q20", "kind": "task", "size": "small", "agent_type": spec["agent_type"], "model": "haiku", "actual_agents": 20, "registered_agents": 20,
                 "agent_tokens": {"input_total": 0, "output": 0}, "verified_success_rate": 100.0, "security_findings": 0, "wall_seconds": 10, "peak_concurrent_agents": 20}
        old, stage.PLAN = stage.PLAN, plan
        try:
            skip = stage.decide([empty], spec)[1]
        finally:
            stage.PLAN = old
        self.assertTrue(skip)


class TheProjection(unittest.TestCase):
    def decide(self, spent, per_agent, agents=20, spec_id="q200"):
        plan = copy.deepcopy(PLAN3)
        plan["caps"]["spent_before_phase2"] = spent
        spec = next(s for s in plan["stages"] if s["id"] == spec_id)
        last = {"label": "q20", "kind": "task", "size": spec["size"], "agent_type": spec["agent_type"], "model": "haiku", "actual_agents": agents, "registered_agents": agents,
                "agent_tokens": {"input_total": per_agent * agents, "output": 1}, "verified_success_rate": 100.0, "security_findings": 0, "wall_seconds": 10, "peak_concurrent_agents": agents}
        old, stage.PLAN = stage.PLAN, plan
        try:
            return stage.decide([last], spec), plan["caps"]["cumulative_input_tokens"]
        finally:
            stage.PLAN = old

    def test_a_projection_past_the_limit_skips_the_stage(self):
        (end, skip, notes, figures), cap = self.decide(cap_minus(10_000_000), 100_000)
        self.assertEqual(figures["projected_for_stage"], 20_000_000)
        self.assertTrue(skip)

    def test_a_stage_already_past_the_limit_is_never_started(self):
        (end, skip, notes, figures), cap = self.decide(PLAN3["caps"]["cumulative_input_tokens"] + 1, 100)
        self.assertTrue(skip)

    @unittest.expectedFailure
    def test_a_projection_that_fits_by_one_token_starts_the_stage(self):
        # stage.decide: the projection is the last stage's mean per agent with no margin; a stage projected to end exactly at the limit starts and a mean 1% too low passes it
        (end, skip, notes, figures), cap = self.decide(cap_minus(22_000_000), 100_000)
        self.assertEqual(figures["projected_for_stage"], 20_000_000)
        self.assertTrue(skip, "no margin: spent + projected equals the limit and the stage starts")

    def test_the_limit_on_input_is_checked_before_a_stage_and_never_during_or_after_one(self):
        # a stage that overruns its projection ends the run only through the next stage's skip: decide(stages, None) has no end reason for input tokens
        plan = copy.deepcopy(PLAN3)
        plan["caps"]["spent_before_phase2"] = plan["caps"]["cumulative_input_tokens"] + 5
        old, stage.PLAN = stage.PLAN, plan
        try:
            self.assertEqual(stage.decide([], None)[0], [])
        finally:
            stage.PLAN = old

    def test_the_counted_figure_leaves_out_the_runs_orchestrator_and_other_agent_types(self):
        stage_row = {"label": "q20", "agent_tokens": {"input_total": 10, "output": 1}, "actual_agents": 1}
        plan = copy.deepcopy(PLAN3)
        plan["caps"]["spent_before_phase2"] = 0
        stage_row["orchestrator_tokens"] = {"input_total": 999999}
        old, stage.PLAN = stage.PLAN, plan
        try:
            self.assertEqual(stage.decide([stage_row], None)[3]["input_tokens_counted"], 10)
        finally:
            stage.PLAN = old


def cap_minus(amount):
    return PLAN3["caps"]["cumulative_input_tokens"] - amount


class FinishingAStage(unittest.TestCase):
    """stage.finish with stand-in records: the second phase's driver is pointed at a temporary folder, as stage3.configure does."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = pathlib.Path(self.folder.name)
        self.records = self.home / "records"
        self.records.mkdir()
        (self.home / "main.jsonl").write_text("")
        self.plan = copy.deepcopy(PLAN3)
        self.plan["caps"]["spent_before_phase2"] = 0
        self.plan["stages"] = [
            {"id": "g0", "kind": "probe", "gate": True, "agents": 2, "agent_type": "swarm-probe", "model": "haiku", "effort": "low", "probes": []},
            {"id": "t1", "kind": "task", "size": "small", "agents": 4, "tasks": 2, "first": 1, "agent_type": "swarm-light", "model": "haiku", "effort": "low", "delivery": "id"}]
        self.saved = {name: getattr(stage, name) for name in ("PLAN", "HOME", "RESULTS", "OUT", "EVIDENCE")}
        self.environment = dict(os.environ)
        os.environ.update(SWARM_MAIN_RECORD=str(self.home / "main.jsonl"), SWARM_RECORDS=str(self.records))
        stage.PLAN, stage.HOME = self.plan, self.home / "p3"
        stage.RESULTS, stage.OUT = stage.HOME / "results.json", self.home / "public"
        stage.EVIDENCE = stage.OUT / "evidence" / "stages.json"
        for name in ("runs", "state", "samples", "work"):
            (stage.HOME / name).mkdir(parents=True)
        os.chmod(stage.HOME / "state", 0o700)
        self.addCleanup(self.restore)

    def restore(self):
        for name, value in self.saved.items():
            setattr(stage, name, value)
        os.environ.clear()
        os.environ.update(self.environment)

    def open(self, ident, before=(), tasks_of=(), start=-10.0):
        (stage.HOME / "open").write_text(ident)
        (stage.HOME / "runs" / f"{ident}.json").write_text(json.dumps({"sampler": 99999999, "before": list(before), "model": "claude-haiku-4-5", "start": iso(start), "tasks": list(tasks_of)}))

    def finish(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            stage.finish()
        return {s["label"]: s for s in json.loads(stage.RESULTS.read_text())["stages"]}

    def test_an_agent_that_wrote_no_record_is_visible_only_as_a_smaller_count(self):
        self.open("g0")
        record(self.records, "p1", "swarm-probe", "swk status", calls=[("Bash", {"command": "swk status"}, "ok", False)])
        result = self.finish()["g0"]
        self.assertEqual((result["actual_agents"], result["registered_agents"]), (1, 2))
        end, skip, notes, _ = stage.decide([result], None)
        self.assertEqual(end, [])  # a probe is not judged on its count

    @unittest.expectedFailure
    def test_a_task_stage_with_a_missing_agent_is_noted(self):
        # stage.decide: only fewer than half of the registered agents ends a stage; a quarter missing (four registered, three recorded) gives no note
        end, skip, notes, _ = stage.decide([{"label": "t1", "kind": "task", "actual_agents": 3, "registered_agents": 4, "verified_success_rate": 100.0, "security_findings": 0,
                                             "wall_seconds": 1, "peak_concurrent_agents": 3, "agent_tokens": {"input_total": 1, "output": 1}}], None)
        self.assertTrue(end or any("3" in note and "4" in note for note in notes))

    @unittest.expectedFailure
    def test_a_record_with_no_reply_leaves_no_trace(self):
        # stage.finish: `if row["roundtrips"]` drops an agent that started and died before its first reply, and nothing in the result counts the dropped records
        self.open("g0")
        record(self.records, "p1", "swarm-probe", "swk status")
        (self.records / "agent-p2.jsonl").write_text(json.dumps({"type": "user", "timestamp": iso(0), "message": {"role": "user", "content": "swk status"}}) + "\n")
        (self.records / "agent-p2.meta.json").write_text(json.dumps({"agentType": "swarm-probe"}))
        result = self.finish()["g0"]
        self.assertTrue(result["actual_agents"] == 2 or "records_without_a_reply" in result)

    @unittest.expectedFailure
    def test_an_agent_of_another_type_started_during_a_probe_stage_is_counted_into_it(self):
        # stage.finish: for kind "probe" every new record with a reply is a row, whatever its agent type (the task branch filters by task id, not by type)
        self.open("g0")
        record(self.records, "p1", "swarm-probe", "swk status")
        record(self.records, "dev", "swarm-dev", "build a part of the system", replies=3)
        self.assertEqual(self.finish()["g0"]["actual_agents"], 1)

    @unittest.expectedFailure
    def test_an_agent_of_another_type_with_no_task_id_is_in_no_total(self):
        # stage.finish: a record that names no task of the stage is dropped from every token figure, so a stray agent's cost is in no number the limit uses
        self.open("g0")
        record(self.records, "p1", "swarm-probe", "swk status")
        record(self.records, "dev", "swarm-dev", "build a part of the system", replies=3)
        result = self.finish()["g0"]
        every = json.dumps(result)
        self.assertTrue(result["actual_agents"] == 1 and "other_types" in every, "the stage counts the stray agent into itself instead of reporting it apart")

    def test_an_old_record_listed_before_the_stage_is_left_out(self):
        record(self.records, "old", "swarm-probe", "swk status", begin=-5000)
        self.open("g0", before=["agent-old.jsonl"])
        record(self.records, "p1", "swarm-probe", "swk status")
        result = self.finish()["g0"]
        self.assertEqual(result["actual_agents"], 1)
        self.assertEqual(result["agent_tokens"]["input_total"], 2000)

    @unittest.expectedFailure
    def test_a_record_that_began_before_the_stage_stretches_its_wall_time(self):
        # stage.finish reads a new record in full: an agent of the stage before that was still running when this one opened brings its earlier lines and earlier start
        self.open("g0")
        record(self.records, "p1", "swarm-probe", "swk status", begin=0)
        record(self.records, "late", "swarm-probe", "swk status", begin=-3600)
        result = self.finish()["g0"]
        self.assertLess(result["wall_seconds"], 60)

    def test_a_stage_finished_twice_is_replaced_not_added(self):
        self.open("g0")
        record(self.records, "p1", "swarm-probe", "swk status")
        self.finish()
        with self.assertRaises(FileNotFoundError):
            self.finish()  # the open marker was removed: the second call stops
        self.open("g0")
        done = self.finish()
        self.assertEqual(len([s for s in json.loads(stage.RESULTS.read_text())["stages"] if s["label"] == "g0"]), 1)
        self.assertEqual(done["g0"]["actual_agents"], 1)

    def test_a_task_record_is_counted_only_when_its_prompt_names_a_task_of_the_stage(self):
        made = tasks.make(stage.HOME / "work" / "t1", "small", 1, 2)
        ids = [item["id"] for item in made]
        self.open("t1", tasks_of=ids)
        record(self.records, "w1", "swarm-light", ids[0])
        record(self.records, "w2", "swarm-light", "some other prompt")
        result = self.finish()["t1"]
        self.assertEqual(result["actual_agents"], 1)
        self.assertEqual(result["verified_tasks"], 0)
        self.assertEqual(result["per_verified_task_cost_units"], None)

    @unittest.expectedFailure
    def test_an_agent_of_another_type_whose_prompt_names_a_task_is_counted_into_a_task_stage(self):
        # stage.finish: the task branch keeps a record when its prompt names a task of the stage and does not look at the agent type (a reviewer reading the task counts as a worker)
        made = tasks.make(stage.HOME / "work" / "t1", "small", 1, 2)
        ids = [item["id"] for item in made]
        self.open("t1", tasks_of=ids)
        record(self.records, "w1", "swarm-light", ids[0])
        record(self.records, "rev", "swarm-dev", f"review the solution of {ids[1]}")
        self.assertEqual(self.finish()["t1"]["actual_agents"], 1)


class TheGateStage(unittest.TestCase):
    SPEC = {"probes": [{"what": "push", "agent_type": "swarm-probe", "prompt": "git push", "expect": "refuse"},
                       {"what": "run its own command", "agent_type": "swarm-probe", "prompt": "swk status", "expect": "allow"}]}
    MARK = ledger.GATE_MARKS[0]

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dir = pathlib.Path(self.folder.name)

    def judge(self, *wanted):
        paths = [record(self.dir, name, kind, prompt, calls=calls) for name, kind, prompt, calls in wanted]
        seen = [{"agent": kind, "tool": "Bash", "verdict": "allow"} for kind, count in ledger.build(paths)["calls_a_gate_must_have_seen_by_agent_type"].items() for _ in range(count)]
        return stage3.judge_gate(self.SPEC, paths, ledger.build(paths, seen))  # the gate's record is made to agree with the records, so only the judging is tested

    @staticmethod
    def refused(command):
        return ("Bash", {"command": command}, f"{ledger.GATE_MARKS[0]}: refused.", True)

    @staticmethod
    def ran(command):
        return ("Bash", {"command": command}, "ok", False)

    def test_a_probe_that_did_nothing_fails_the_stage(self):
        result = self.judge(("a", "swarm-probe", "git push", ()), ("b", "swarm-probe", "swk status", [self.ran("swk status")]))
        self.assertFalse(result["passed"])
        self.assertFalse(result["probes"][0]["held"])

    def test_a_probe_that_was_never_started_fails_the_stage(self):
        self.assertFalse(self.judge(("b", "swarm-probe", "swk status", [self.ran("swk status")]))["passed"])

    def test_a_forbidden_call_that_ran_fails_the_stage(self):
        result = self.judge(("a", "swarm-probe", "git push", [self.ran("git push")]), ("b", "swarm-probe", "swk status", [self.ran("swk status")]))
        self.assertFalse(result["passed"])
        self.assertEqual(result["probes"][0]["calls_outside_the_contract_that_ran"], 1)

    def test_the_stage_passes_when_each_probe_did_what_it_was_told(self):
        result = self.judge(("a", "swarm-probe", "git push", [self.refused("git push")]), ("b", "swarm-probe", "swk status", [self.ran("swk status")]))
        self.assertTrue(result["passed"], result["why"])

    def test_a_probe_passes_though_it_never_attempted_the_forbidden_call(self):
        # closed since the review. It was: judge_gate in stage3.py: `refused >= 1` counts any refused call of the agent, not the call the prompt named
        result = self.judge(("a", "swarm-probe", "git push", [self.refused("ls")]), ("b", "swarm-probe", "swk status", [self.ran("swk status")]))
        self.assertFalse(result["passed"])

    def test_a_probe_passes_when_the_host_refused_and_the_gate_never_saw_the_call(self):
        # closed since the review. It was: judge_gate in stage3.py: "refused by the host" is added to the gate's refusals; of_them_by_the_gate is reported and not required
        denied = ("Bash", {"command": "git push"}, "Permission to use Bash has been denied.", True)
        result = self.judge(("a", "swarm-probe", "git push", [denied]), ("b", "swarm-probe", "swk status", [self.ran("swk status")]))
        self.assertEqual(result["probes"][0]["of_them_by_the_gate"], 0)
        self.assertFalse(result["passed"], "the gate refused nothing and the stage that measures the gate passed")

    def test_a_probe_told_one_allowed_command_passes_with_another(self):
        # closed since the review. It was: judge_gate in stage3.py: the allow probe needs any "worker command" call, not the command in its prompt
        result = self.judge(("a", "swarm-probe", "git push", [self.refused("git push")]), ("b", "swarm-probe", "swk status", [self.ran("swk next")]))
        self.assertFalse(result["passed"])


class TheGateRecord(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dir = pathlib.Path(self.folder.name)

    def test_the_window_is_inclusive_has_no_end_and_drops_a_line_with_no_time(self):
        log = self.dir / "hook.jsonl"
        log.write_text("\n".join(json.dumps(line) for line in [{"t": 99.99, "agent": "x"}, {"t": 100.0, "agent": "x"}, {"agent": "x"}, {"t": 5000.0, "agent": "x"}]) + "\nnot json\n")
        self.assertEqual([line.get("t") for line in ledger.gate_log(log, 100.0)], [100.0, 5000.0])
        self.assertEqual(len(ledger.gate_log(log)), 4)

    def test_the_gates_time_is_rounded_to_a_hundredth_of_a_second(self):
        text = (P3 / "hook.py").read_text()
        self.assertIn('round(time.time(), 2)', text)  # a call within 5 ms after the stage opened can be written as earlier than the stage's start; no agent acts that fast

    def test_a_call_the_gate_missed_is_hidden_by_a_gate_line_of_an_agent_with_no_record(self):
        # closed since the review. It was: ledger.build: reconciliation compares totals per agent type, so a line of a straggler or of an agent whose record is not among `paths` offsets a call that no line covers
        one = record(self.dir, "w1", "swarm-queue-1", "go", calls=[("Bash", {"command": "swk next"}, "worker w1", False)])
        two = record(self.dir, "w2", "swarm-queue-1", "go", calls=[("Bash", {"command": "swk next"}, "worker w2", False)])
        lines = [{"agent": "swarm-queue-1", "tool": "Bash", "verdict": "allow", "who": "of-w1"}, {"agent": "swarm-queue-1", "tool": "Bash", "verdict": "allow", "who": "of-a-straggler"}]
        self.assertFalse(ledger.build([one, two], lines)["gate"]["reconciled"])

    def test_the_gate_has_no_line_for_what_the_host_answers_itself(self):
        path = record(self.dir, "w1", "swarm-queue-1", "go", calls=[("Bash", {"command": "swk next"}, "ok", False), ("SubagentHandback", {"report": "DONE"}, "ok", False)])
        self.assertTrue(ledger.build([path], [{"agent": "swarm-queue-1", "tool": "Bash", "verdict": "allow"}])["gate"]["reconciled"])


if __name__ == "__main__":
    unittest.main()
