"""The second phase of the swarm experiment: tasks of three sizes, the worker's one command,
the gate in front of its shell, and the stage driver. No agent and no model is started here."""
import json
import os
import pathlib
import random
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
P2 = ROOT / "swarm" / "phase2"
sys.path.insert(0, str(P2))
sys.path.insert(0, str(ROOT / "swarm"))
import bench  # noqa: E402
import guard  # noqa: E402
import tasks  # noqa: E402
import workload  # noqa: E402

PLAN = json.loads((P2 / "PLAN.json").read_text())
TOY = tasks.finish("S-9001", "small", "toy", None, "Write the function `double(x: int) -> int`.",
                   [{"steps": [{"call": "double", "args": [n], "expect": 2 * n}]} for n in (0, 3, -4, 10)],
                   [{"steps": [{"call": "double", "args": [3], "expect": 6}]}])


class Stage(unittest.TestCase):
    """A private home with one open stage, and the worker's command run the way a worker runs it."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = pathlib.Path(self.folder.name)
        self.out = self.home / "p2" / "work" / "t1"
        self.out.mkdir(parents=True)
        (self.home / "p2" / "current").write_text("t1")
        self.env = {"PATH": os.environ["PATH"], "SWARM_HOME": str(self.home), "HOME": str(self.home), "HR_TOOL_HOME": str(self.home / "no-tools")}

    def swk(self, *arguments, text=None):
        return subprocess.run([sys.executable, "-I", str(P2 / "kit.py"), *arguments], input=text, capture_output=True, text=True, env=self.env)


class TaskTests(Stage):
    def test_every_medium_reference_keeps_the_workers_rules_and_passes_its_withheld_tests(self):
        made = tasks.make(self.out, "medium", 1, 8)
        self.assertEqual({item["family"] for item in made}, {"ledger", "expr", "rooms", "graph"})
        for item in made:
            self.assertEqual(workload.inspect(item["reference"]), [], item["id"])
            (self.out / item["id"] / "solution.py").write_text(item["reference"])
        result = tasks.check(self.out)
        self.assertEqual((result["verified"], result["tests_passed"]), (8, result["tests_total"]))
        self.assertGreaterEqual(min(row["total"] for row in result["rows"]), 12)

    def test_a_solution_that_is_wrong_in_one_rule_is_not_verified(self):
        made = tasks.make(self.out, "medium", 1, 4)
        wrong = {"ledger": ("(-self.money[name], name)", "(self.money[name], name)"), "expr": ("value * right if False else value", "value"),
                 "rooms": ("start < other_end and other_start < end", "start <= other_end and other_start <= end"), "graph": ("seen.discard(name)", "pass")}
        for item in made:
            old, new = wrong[item["family"]]
            source = item["reference"].replace("value *= right", "value += right") if item["family"] == "expr" else item["reference"].replace(old, new)
            self.assertNotEqual(source, item["reference"], item["family"])
            (self.out / item["id"] / "solution.py").write_text(source)
        result = tasks.check(self.out)
        self.assertEqual(result["verified"], 0)
        self.assertTrue(all(0 < row["passed"] < row["total"] for row in result["rows"]), [(r["family"], r["passed"], r["total"]) for r in result["rows"]])

    def test_the_task_text_shows_examples_and_the_withheld_set_is_larger_and_kept_apart(self):
        made = tasks.make(self.out, "medium", 1, 4) + tasks.make(self.out, "small", 1, 10)
        for item in made:
            self.assertLess(len(item["examples"]["tests"]), len(item["suite"]["tests"]), item["id"])
            kit = json.loads((self.out / ".kit" / f"{item['id']}.json").read_text())
            self.assertEqual(kit["examples"], item["examples"])
            self.assertNotIn("suite", kit)
            self.assertEqual(sorted(p.name for p in (self.out / item["id"]).iterdir()), ["TASK.md"])
        self.assertEqual(len({item["family"] for item in made if item["size"] == "small"}), 10)

    def test_the_same_number_and_seed_give_the_same_task_and_another_seed_another(self):
        self.assertEqual(tasks.medium(7, 1)["fingerprint"], tasks.medium(7, 1)["fingerprint"])
        self.assertNotEqual(tasks.medium(7, 1)["fingerprint"], tasks.medium(7, 2)["fingerprint"])
        self.assertEqual(tasks.small(3, 5)["suite"], tasks.small(3, 5)["suite"])

    def test_the_runner_tells_a_list_from_a_number_and_true_from_one(self):
        (self.out / "s.py").write_text("def f(x):\n    return x\n")
        suite = {"entry": None, "tests": [{"steps": [{"call": "f", "args": [1], "expect": 1}]}, {"steps": [{"call": "f", "args": [True], "expect": 1}]},
                                         {"steps": [{"call": "f", "args": [[1, 2]], "expect": [1, 2]}]}, {"steps": [{"call": "f", "args": [1.0], "expect": 1}]}]}
        self.assertEqual(tasks.run_suite(self.out / "s.py", suite)["passed"], 2)


class WorkerCommandTests(Stage):
    def test_a_worker_reads_its_task_hands_in_and_is_told_the_examples_passed(self):
        made = tasks.make(self.out, "medium", 1, 1, extra=[TOY])
        shown = self.swk("show", "M-0001")
        self.assertEqual(shown.stdout.strip(), next(m["text"] for m in made if m["id"] == "M-0001").strip())
        done = self.swk("submit", "M-0001", text=next(m["reference"] for m in made if m["id"] == "M-0001"))
        self.assertRegex(done.stdout, r"^The 2 examples passed\. Reply DONE\.")
        self.assertIn("examples passed", self.swk("submit", "S-9001", text="def double(x):\n    return x + x\n").stdout)
        result = tasks.check(self.out)
        self.assertEqual((result["verified"], result["attempts"], result["extra_files"]), (2, 2, 0))

    def test_a_failure_is_named_and_three_attempts_are_all_there_are(self):
        tasks.make(self.out, "small", 1, 0, extra=[TOY])
        first = self.swk("submit", "S-9001", text="def double(x):\n    return x * 3\n").stdout
        self.assertIn("0 of 1 examples passed", first)
        self.assertIn("double(3) returned 9, expected 6", first)
        self.assertIn("Attempt 1 of 3", first)
        self.swk("submit", "S-9001", text="def double(x):\n    return 0\n")
        self.assertIn("No attempts are left. Reply FAILED.", self.swk("submit", "S-9001", text="def double(x):\n    return 1\n").stdout)
        fourth = self.swk("submit", "S-9001", text="def double(x):\n    return x * 2\n")
        self.assertEqual(fourth.stdout.strip(), "No attempts are left. Reply FAILED.")
        self.assertIn("return 1", (self.out / "S-9001" / "solution.py").read_text(), "a hand-in after the last attempt changes nothing")

    def test_a_file_that_breaks_the_rules_is_not_run(self):
        tasks.make(self.out, "small", 1, 0, extra=[TOY])
        marker = self.home / "ran"
        reply = self.swk("submit", "S-9001", text=f"import os\nos.system('touch {marker}')\ndef double(x):\n    return x * 2\n").stdout
        self.assertIn("Not run: import of os", reply)
        self.assertFalse(marker.exists())
        self.assertFalse(tasks.check(self.out)["rows"][0]["verified"])

    def test_a_worker_cannot_name_a_task_or_a_path_of_its_own(self):
        tasks.make(self.out, "small", 1, 0, extra=[TOY])
        for arguments in (["show", "S-0001"], ["show", "../t1/S-9001"], ["show", "S-9001/../.hidden"], ["frobnicate", "S-9001"], ["show"], ["test", "S-9001"]):
            done = self.swk(*arguments)
            self.assertEqual(done.returncode, 2, arguments)
            self.assertTrue(done.stdout.startswith("swk: refused"), arguments)
        self.assertNotIn("expect", self.swk("show", "S-9001").stdout)

    def test_a_large_task_is_found_fixed_and_answered_with_the_lean_commands(self):
        made = tasks.make(self.out, "large", 1, 1, mode="lean")[0]
        truth, ident = made["truth"], made["id"]
        module, name = truth["fixed_function"].split(".")
        failing = self.swk("test", ident).stdout
        self.assertIn(f"test_{name}", failing)
        self.assertLess(len(failing), 9000)
        self.assertEqual(json.loads(self.swk("callers", ident, name).stdout), truth["direct_callers"])
        self.assertEqual(json.loads(self.swk("select", ident, "data/events.json", "status=failed", "id").stdout), truth["failed_event_ids"])
        self.assertIn(truth["build_error_code"], self.swk("grep", ident, "^ERROR", "logs/build.log").stdout)
        shown = self.swk("def", ident, name).stdout.splitlines()
        self.assertEqual(shown[0], f"inv/{module}.py")
        number, broken = next((int(line.split(":")[0]), line.split(": ", 1)[1]) for line in shown if "return" in line)
        correct = next(line for line in bench.source(bench.design(tasks.SEED * 1000 + 1), module, False).splitlines()[number - 1:number])
        self.assertNotEqual(correct, broken)
        for arguments, text in ((["setline", ident, "tests/test_inv.py", "1"], "x = 1"), (["setline", ident, f"inv/{module}.py", str(number)], "    return (y +"),
                                (["setline", ident, f"inv/{module}.py", str(number)], "a\nb"), (["read", ident, "../../etc/passwd"], None),
                                (["read", ident, "/etc/passwd"], None), (["answer", ident], '{"fixed_function": "m1.f"}')):
            self.assertEqual(self.swk(*arguments, text=text).returncode, 2, arguments)
        self.assertEqual(self.swk("setline", ident, f"inv/{module}.py", str(number), text=correct + "\n").returncode, 0)
        self.assertIn("OK: no failure.", self.swk("test", ident).stdout)
        answer = dict(truth, direct_callers=list(reversed(truth["direct_callers"])), failed_event_ids=list(reversed(truth["failed_event_ids"])))
        self.assertIn("The answer is recorded", self.swk("answer", ident, text=json.dumps(answer)).stdout)
        row = tasks.check(self.out)["rows"][0]
        self.assertEqual((row["verified"], row["passed"], row["total"]), (True, 5, 5))
        self.assertGreaterEqual(row["kit_calls"], 7)

    def test_a_raw_stage_has_no_index_and_prints_the_whole_test_output(self):
        made = tasks.make(self.out, "large", 2, 1, mode="raw")[0]
        name = made["truth"]["fixed_function"].split(".")[1]
        self.assertEqual(self.swk("def", made["id"], name).returncode, 2)
        self.assertEqual(self.swk("callers", made["id"], name).returncode, 2)
        self.assertIn("Traceback (most recent call last)", self.swk("test", made["id"]).stdout)
        self.assertIn(f"def {name}(", self.swk("read", made["id"], f"inv/{made['truth']['fixed_function'].split('.')[0]}.py").stdout)
        self.assertNotIn("swk def", made["text"])
        row = tasks.check(self.out)["rows"][0]
        self.assertEqual((row["verified"], row["passed"]), (False, 0))

    def test_the_shared_index_is_read_from_the_code_and_agrees_with_the_generator(self):
        made = tasks.make(self.out, "large", 3, 1, mode="lean")[0]
        target = made["truth"]["fixed_function"].split(".")[1]
        self.assertEqual(made["index"]["callers"][target], made["truth"]["direct_callers"])
        self.assertEqual(len(made["index"]["functions"]), bench.MODULES * bench.FUNCTIONS)


class GateTests(unittest.TestCase):
    def test_only_swk_commands_of_the_two_shapes_get_through(self):
        body = "swk submit S-0001 <<'PY'\ndef f(x):\n    return x * 2  # $(id) `id` ; rm -rf / | cat > /tmp/x\nPY"
        for command in ("swk show S-0001", "swk status", "swk grep L-0001 'f3_2\\(' inv", "swk read L-0001 inv/m3.py 10:20", "swk select L-0001 data/events.json status=failed id",
                        body, "swk setline L-0001 inv/m3.py 41 <<'EOF'\n    return y * 3 + 5\nEOF", "swk answer L-0001 <<'EOF'\n{\"a\": 1}\nEOF\n"):
            self.assertTrue(guard.allowed(command), command)
        for command in ("cat /etc/hostname", "swk show S-0001; id", "swk show S-0001 && id", "swk show $(id)", "swk show `id`", "swk show S-0001 > /tmp/x",
                        "swk show S-0001 | head", 'swk grep L-0001 "$(id)"', "swk show S-0001\nid", "swk submit S-0001 <<PY\nx = 1\nPY", "swk submit S-0001 <<'PY'\nx = 1\nPY\nid",
                        "swk submit S-0001 <<'PY'\nx = 1\nPY\nPY", "swk submit S-0001 <<'PY' ; id\nx = 1\nPY", "swk submit S-0001 < /etc/passwd", "sudo swk show S-0001",
                        "env X=1 swk show S-0001", " swk show S-0001", "swkshow S-0001", "python3 -c 'print(1)'", "", "swk show S-0001 &"):
            self.assertFalse(guard.allowed(command), command)

    def test_the_gate_refuses_what_it_cannot_read_and_says_why_to_the_worker(self):
        def run(text):
            return subprocess.run([sys.executable, "-I", str(P2 / "guard.py")], input=text, capture_output=True, text=True)

        self.assertEqual(run(json.dumps({"tool_name": "Bash", "tool_input": {"command": "swk status"}})).returncode, 0)
        refused = run(json.dumps({"tool_name": "Bash", "tool_input": {"command": "id"}}))
        self.assertEqual(refused.returncode, 2)
        self.assertIn(guard.MARK, refused.stderr)
        for text in ("", "not json", json.dumps({"tool_name": "Write", "tool_input": {"command": "swk status"}}), json.dumps({"tool_name": "Bash"}),
                     json.dumps({"tool_name": "Bash", "tool_input": {"command": ["swk", "status"]}}), json.dumps([1])):
            self.assertEqual(run(text).returncode, 2, text)

    def test_every_worker_definition_has_a_shell_only_and_the_gate_in_front_of_it(self):
        names = sorted(path.stem for path in (ROOT / ".claude" / "agents").glob("swarm-*.md"))
        self.assertEqual(names, ["swarm-large", "swarm-light", "swarm-light-2", "swarm-light-inline", "swarm-light-open", "swarm-probe"])
        for name in names:
            text = (ROOT / ".claude" / "agents" / f"{name}.md").read_text()
            front = text.split("---")[1]
            self.assertIn("\ntools: Bash\n", front, name)
            self.assertRegex(front, r"\nmaxTurns: \d+\n", name)
            self.assertEqual('command: "swk-guard"' in front, name != "swarm-light-open", name)
            self.assertIsNone(re.search(r"mcp|send_message|interrupt_session|WebFetch|Agent\b", text), name)
        used = {stage["agent_type"] for stage in PLAN["stages"]} - {"general-purpose"}
        self.assertTrue(used <= set(names) - {"swarm-light-open"}, used)


def fake_stage(label, agents=10, verified=10, per_agent=60000, **more):
    row = {"label": label, "kind": "task", "size": "small", "agent_type": "swarm-light", "model": "haiku", "actual_agents": agents, "registered_agents": agents,
           "tasks": agents, "verified_tasks": verified, "verified_success_rate": round(100 * verified / agents, 1), "security_findings": 0, "wall_seconds": 30.0,
           "peak_concurrent_agents": agents, "agents_with_limit_error": 0, "foreign_calls": 0, "guard_enforced": True,
           "agent_tokens": {"input_total": per_agent * agents, "output": 500 * agents}, "machine": {"least_memory_available_mb": 9000, "peak_host_process_rss_mb": 1200}}
    row.update(more)
    return row


class DriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.home = pathlib.Path(cls.folder.name)
        (cls.home / "records").mkdir()
        (cls.home / "bin").mkdir()
        (cls.home / "main.jsonl").write_text("")
        cls.env = {"PATH": f"{cls.home / 'bin'}:{os.environ['PATH']}", "HOME": str(cls.home), "SWARM_HOME": str(cls.home / "swarm"), "SWARM_BIN": str(cls.home / "bin"),
                   "SWARM_MAIN_RECORD": str(cls.home / "main.jsonl"), "SWARM_RECORDS": str(cls.home / "records"), "SWARM_REPORT_DIR": str(cls.home / "public"),
                   "HR_TOOL_HOME": str(cls.home / "no-tools")}
        saved = {key: os.environ.get(key) for key in cls.env}
        os.environ.update(cls.env)
        import stage  # noqa: PLC0415 - it reads its folders from the environment when loaded

        cls.stage = stage
        for key, value in saved.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)

    def run_stage(self, *arguments):
        return subprocess.run([sys.executable, str(P2 / "stage.py"), *arguments], capture_output=True, text=True, env=self.env)

    def test_the_plan_is_the_ladder_the_owner_asked_for_within_its_own_limits(self):
        stages = PLAN["stages"]
        self.assertEqual(len({s["id"] for s in stages}), len(stages))
        self.assertEqual(stages[0]["kind"], "probe")
        ladder = [s for s in stages if re.fullmatch(r"s\d+", s["id"])]
        self.assertEqual([s["agents"] for s in ladder], [10, 20, 25, 50, 75, 100])
        self.assertEqual({(s["agent_type"], s["model"], s["delivery"], s["tasks"] == s["agents"]) for s in ladder}, {("swarm-light", "haiku", "id", True)})
        self.assertEqual({s["size"] for s in stages if s["kind"] == "task"}, {"small", "medium", "large"})
        taken = {}
        for s in (s for s in stages if s["kind"] == "task"):
            for number in range(s["first"], s["first"] + s["tasks"]):
                self.assertNotIn((s["size"], number), taken, f"{s['id']} repeats a task of {taken.get((s['size'], number))}")
                taken[(s["size"], number)] = s["id"]
        self.assertLessEqual(sum(s["agents"] for s in stages), PLAN["caps"]["phase2_agent_runs"])
        self.assertEqual((PLAN["caps"]["cumulative_input_tokens"], PLAN["caps"]["spent_before_phase2"]), (150_000_000, 36_168_638))
        first = json.loads((ROOT / "swarm" / "evidence" / "summary.json").read_text())
        self.assertIn(str(PLAN["caps"]["spent_before_phase2"]), json.dumps(first), "the first phase's own total is what is carried over")

    def test_what_ends_the_experiment_what_skips_a_stage_and_what_is_only_noted(self):
        decide, spec = self.stage.decide, self.stage.spec_of("s20")
        self.assertEqual(decide([], spec)[:2], ([], []))
        end, skip, notes, figures = decide([fake_stage("s10")], spec)
        self.assertEqual((end, skip, notes), ([], [], []))
        self.assertEqual(figures["projected_for_stage"], 20 * 60000)
        self.assertEqual(figures["input_tokens_counted"], 36_168_638 + PLAN["caps"]["preflight_input_tokens"] + 600_000)
        self.assertTrue(decide([fake_stage("s10", agents_with_limit_error=1)], spec)[0])
        self.assertTrue(decide([fake_stage("s10", security_findings=1)], spec)[0])
        self.assertTrue(decide([fake_stage("s10", foreign_calls=1)], spec)[0])
        self.assertFalse(decide([fake_stage("s10", foreign_calls=1, agent_type="general-purpose")], spec)[0], "the general agent has no gate; its calls are recorded, not a breach")
        self.assertTrue(decide([fake_stage("s10", verified=5)], spec)[0])
        self.assertEqual(decide([fake_stage("s10", verified=8)], spec)[0], [])
        self.assertEqual(len(decide([fake_stage("s10", verified=8)], spec)[2]), 1)
        self.assertTrue(decide([fake_stage("s10", actual_agents=4)], spec)[0])
        self.assertEqual(len(decide([fake_stage("s10", peak_concurrent_agents=6)], spec)[2]), 1)
        self.assertTrue(decide([fake_stage("s10", machine={"least_memory_available_mb": 900, "peak_host_process_rss_mb": 1200})], spec)[0])
        dear = [fake_stage("s10", per_agent=6_000_000)]
        self.assertEqual(decide(dear, spec)[0], [])
        self.assertIn("past the limit of 150,000,000", decide(dear, spec)[1][0])

    def test_a_stage_that_would_pass_the_limit_is_skipped_and_the_next_that_fits_is_taken(self):
        done = [{"label": s["id"], "skipped": "test"} for s in PLAN["stages"][:8]] + [fake_stage("s75", agents=75, verified=75, per_agent=1_200_000)]
        nxt, end = self.stage.following(done)
        self.assertEqual(end, [])
        self.assertEqual(nxt["id"], "g10", "s100 is projected past the limit; the general agents have nothing to project from and fit")
        self.assertIn("s100", [s["label"] for s in done if s.get("skipped")])
        self.assertEqual(self.stage.following([fake_stage("s10", agents_with_limit_error=2)])[0], None)

    def test_a_later_stage_takes_the_lighter_model_only_if_it_verified_enough(self):
        spec = self.stage.spec_of("m25")
        self.assertEqual(self.stage.resolve(spec, [fake_stage("m10h", verified=9)]), "haiku")
        self.assertEqual(self.stage.resolve(spec, [fake_stage("m10h", verified=8)]), "sonnet")
        self.assertEqual(self.stage.resolve(self.stage.spec_of("s10"), []), "haiku")

    def test_cost_units_weigh_the_kinds_of_token_and_say_they_are_an_assumption(self):
        row = {"input_uncached": 100, "write_5m": 1000, "write_1h": 100, "write_unknown": 0, "cache_read": 10000, "output": 10}
        self.assertEqual(self.stage.cost_units(row), 100 + 1250 + 200 + 1000 + 50)
        self.assertIn("assumption", PLAN["cost_weights"]["about"])
        self.assertIn("not a measure of subscription allowance", PLAN["cost_weights"]["about"])

    def record(self, name, prompt, commands, model="claude-haiku-4-5-20251001"):
        """A record the way the host writes one: a prompt, replies with usage, shell calls and what came back."""
        lines = [{"type": "user", "timestamp": "2026-11-28T10:00:00Z", "message": {"role": "user", "content": prompt}}]
        for index, (command, came_back) in enumerate(commands):
            usage = {"input_tokens": 12, "cache_creation_input_tokens": 9000 if index == 0 else 300, "cache_read_input_tokens": 21000 if index else 20000, "output_tokens": 150,
                     "cache_creation": {"ephemeral_5m_input_tokens": 9000 if index == 0 else 300, "ephemeral_1h_input_tokens": 0}}
            lines.append({"type": "assistant", "timestamp": f"2026-11-28T10:00:0{index + 1}Z",
                          "message": {"id": f"m{index}", "model": model, "usage": usage, "content": [{"type": "tool_use", "id": f"t{index}", "name": "Bash", "input": {"command": command}}]}})
            lines.append({"type": "user", "timestamp": f"2026-11-28T10:00:0{index + 1}Z", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{index}", "content": came_back}]}})
        lines.append({"type": "assistant", "timestamp": "2026-11-28T10:00:09Z", "message": {"id": "last", "model": model, "content": [{"type": "text", "text": "DONE"}],
                                                                                              "usage": {"input_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 30000, "output_tokens": 4}}})
        path = self.home / "records" / f"agent-{name}.jsonl"
        path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
        path.with_name(f"agent-{name}.meta.json").write_text(json.dumps({"agentType": "swarm-light"}))
        return path

    def test_a_record_gives_the_first_request_the_cache_writes_and_the_tool_contract(self):
        path = self.record("probe", "S-0001", [("swk show S-0001", "task"), ("cat /etc/hostname", f"{guard.MARK}: refused."), ("ls /", "bin etc")])
        found = self.stage.extra(path)
        self.assertEqual((found["first_context"], found["first_cache_read"]), (12 + 9000 + 20000, 20000))
        self.assertEqual((found["write_5m"], found["write_1h"], found["write_unknown"]), (9600, 0, 0))
        self.assertEqual((found["swk_calls"], found["refused_calls"], found["foreign_calls"]), (1, 1, 1))
        self.assertEqual(found["agent_type"], "swarm-light")
        path.unlink()

    def test_the_session_record_is_the_newest_when_the_session_has_one_under_two_folders(self):
        home = self.home / "twice"
        for folder, age in (("-home-user-zzz", 500), ("-home-user", 0)):
            (home / ".claude" / "projects" / folder / "abc" / "subagents").mkdir(parents=True)
            record = home / ".claude" / "projects" / folder / "abc.jsonl"
            record.write_text("")
            os.utime(record, (record.stat().st_mtime - age,) * 2)
        code = "import stage; main, folder = stage.locate(); print(main.parent.name, folder.name)"
        env = {**self.env, "HOME": str(home), "CLAUDE_CODE_SESSION_ID": "abc", "PYTHONPATH": str(P2)}
        del env["SWARM_MAIN_RECORD"], env["SWARM_RECORDS"]
        found = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        self.assertEqual(found.stdout.split(), ["-home-user", "subagents"], found.stderr)

    def test_a_probe_in_which_the_workers_own_command_did_not_run_ends_the_experiment(self):
        probe = {"label": "p1", "kind": "probe", "actual_agents": 2, "agents_with_limit_error": 0, "foreign_calls": 0, "agent_type": "swarm-probe", "guard_enforced": False,
                 "allowed_command_ran": False, "agent_tokens": {"input_total": 60000, "output": 100}}
        self.assertTrue(self.stage.decide([probe], self.stage.spec_of("c1"))[0])
        self.assertEqual(self.stage.decide([dict(probe, allowed_command_ran=True)], self.stage.spec_of("c1"))[0], [])

    def test_one_stage_end_to_end_with_a_stand_in_for_the_agent(self):
        self.assertEqual(self.run_stage("setup").returncode, 0)
        prepared = self.run_stage("prep", "m1")
        self.addCleanup(lambda: subprocess.run(["pkill", "-f", str(self.home / "swarm")], capture_output=True))
        self.assertIn("STAGE m1: start 1 agents, all in ONE message", prepared.stdout)
        self.assertIn("subagent_type: swarm-light   model: haiku   effort: low", prepared.stdout)
        self.assertIn("M-0001", prepared.stdout)
        self.assertEqual(self.run_stage("prep").returncode, 1, "a second stage cannot be opened while one is open")
        reference = tasks.medium(1, PLAN["seed"])["reference"]
        handed = subprocess.run(["swk", "submit", "M-0001"], input=reference, capture_output=True, text=True, env=self.env)
        self.assertIn("examples passed", handed.stdout)
        self.record("a1", "M-0001", [("swk show M-0001", "the task"), ("swk submit M-0001 <<'PY'\nx\nPY", "The 2 examples passed. Reply DONE.")])
        finished = self.run_stage("finish")
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertIn("NEXT p1", finished.stdout)
        text = (self.home / "public" / "evidence" / "stages.json").read_text()
        result = json.loads(text)["stages"][0]
        self.assertEqual((result["label"], result["actual_agents"], result["verified_tasks"], result["tasks"]), ("m1", 1, 1, 1))
        self.assertEqual(result["agent_tokens"]["input_total"], (12 + 9000 + 20000) + (12 + 300 + 21000) + (5 + 30000))
        self.assertEqual(result["first_request_context"]["median"], 29012)
        self.assertEqual((result["swk_calls"], result["refused_calls"], result["foreign_calls"]), (2, 0, 0))
        self.assertEqual(result["ownership"]["approved"], 1)
        self.assertEqual(result["worker_command"]["hand_ins"], 1)
        self.assertEqual(result["models"], ["haiku"])
        self.assertGreater(result["per_verified_task_cost_units"], 0)
        for private in ("/home/", "/root/", "/tmp/", str(self.home), "claude-haiku-4-5", "session_0"):
            self.assertNotIn(private, text)
        self.assertEqual(self.run_stage("report").returncode, 0)
        self.assertIn("| m1 | medium | swarm-light | haiku | 1 | 1 | 1/1 |", (self.home / "public" / "RESULTS.md").read_text())
        state = self.home / "public" / "state"
        self.assertEqual(sorted(p.name for p in state.iterdir()), ["AGENT_STATUS.json", "BENCHMARK_RESULTS.json", "RESOURCE_METRICS.json", "RESUME.txt", "TASK_STATE.json", "TEST_EVIDENCE.json"])
        self.assertTrue(json.loads((state / "TASK_STATE.json").read_text())["checkpoint"]["restore_matches"])


if __name__ == "__main__":
    unittest.main()
