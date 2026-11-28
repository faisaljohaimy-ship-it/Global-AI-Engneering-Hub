"""The swarm experiment: registries, routing, scheduling, workload, limits, measurement, evidence."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SWARM = ROOT / "swarm"
sys.path.insert(0, str(SWARM))
import bench  # noqa: E402
import measure  # noqa: E402
import protect  # noqa: E402
import route  # noqa: E402
import scheduler  # noqa: E402
import workload  # noqa: E402

STATUSES = {"USED", "TESTED", "AVAILABLE", "HOST", "RULE", "BLOCKED", "NOT IMPLEMENTED"}
AGENT_FIELDS = {"id", "team", "role", "hub_role", "task_scope", "required_capabilities", "required_skills", "minimum_context", "resource_budget",
                "permission_boundaries", "output_contract", "acceptance_criteria", "checkpoint_policy", "stop_conditions"}


def stage(agents, per_minute, tokens=800_000, **extra):
    row = {"label": f"s{agents:02d}", "actual_agents": agents, "agents_with_limit_error": 0, "verified_success_rate": 100.0, "security_findings": 0,
           "wall_seconds": 20.0, "effective_concurrency": agents * 0.7, "tasks_per_minute": per_minute,
           "agent_tokens": {"input_total": tokens * agents, "output": 2000 * agents}}
    return {**row, **extra}


class RegistryTests(unittest.TestCase):
    def test_registries_are_current_complete_and_consistent(self):
        self.assertEqual(subprocess.run([sys.executable, str(SWARM / "build_registries.py"), "--check"], capture_output=True).returncode, 0)
        capabilities = json.loads((SWARM / "capabilities.json").read_text())["capabilities"]
        agents = json.loads((SWARM / "agents.json").read_text())["agents"]
        self.assertEqual([c["id"] for c in capabilities], [f"C{n:03d}" for n in range(1, 101)])
        self.assertEqual(len({c["name"] for c in capabilities}), 100)
        self.assertTrue(all(sum(c["group"] == g for c in capabilities) == 10 for g in "ABCDEFGHIJ"))
        self.assertLessEqual({c["status"] for c in capabilities}, STATUSES)
        self.assertTrue(all(c["invoke"] is None for c in capabilities if c["status"] == "NOT IMPLEMENTED"))
        self.assertEqual((len(agents), len({a["id"] for a in agents}), len({a["role"] for a in agents})), (100, 100, 100))
        self.assertTrue(all(sum(a["id"].startswith(f"T{t:02d}-") for a in agents) == 10 for t in range(1, 11)))
        known = {c["id"] for c in capabilities}
        for agent in agents:
            self.assertEqual(set(agent), AGENT_FIELDS, agent["id"])
            self.assertLessEqual(set(agent["required_capabilities"]), known, agent["id"])
            for skill in agent["required_skills"]:
                self.assertTrue((ROOT / "skills" / skill / "SKILL.md").is_file(), skill)

    def test_a_task_is_told_about_a_few_capabilities_that_really_ran(self):
        capabilities = {c["id"]: c for c in json.loads((SWARM / "capabilities.json").read_text())["capabilities"]}
        for name in route.CLASSES:
            chosen = route.select(name)
            self.assertLessEqual(chosen["selected"], 10)
            self.assertTrue(all(capabilities[c["id"]]["status"] in ("USED", "TESTED") for c in chosen["capabilities"]), name)
        self.assertEqual(route.select("routine")["selected"], 2)
        self.assertEqual(route.classify("Find why the test is failing"), "investigate")
        self.assertEqual(route.classify("Implement the function below"), "routine")
        self.assertEqual(route.classify("Check for a leaked credential"), "security")


class SchedulerTests(unittest.TestCase):
    def test_a_hundred_agents_are_scheduled_at_any_limit(self):
        for limit, waves in ((100, None), (16, None), (2, 50)):
            result = scheduler.simulate(limit, 100)
            self.assertTrue(result["passed"], result["checks"])
            self.assertEqual((result["tasks_scheduled"], result["duplicates_dropped"], result["agents_used"]), (100, 5, 100))
            self.assertLessEqual(result["largest_wave"], limit)
            if waves:
                self.assertEqual(result["waves"], waves)

    def test_a_cycle_is_refused(self):
        tasks = [{"id": "a", "team": "t", "write": "w/a", "fingerprint": "1", "needs": ["b"]}, {"id": "b", "team": "t", "write": "w/b", "fingerprint": "2", "needs": ["a"]}]
        with self.assertRaises(ValueError):
            scheduler.plan(tasks, [{"id": "x", "team": "t", "role": "r"}], 4)

    def test_ownership_goes_through_the_hub_task_store_and_survives_a_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            state = pathlib.Path(folder) / "state"
            state.mkdir(mode=0o700)
            self.assertEqual(len(scheduler.own(state, "s99", ["T-0001", "T-0002"])), 2)
            with self.assertRaises(Exception):
                scheduler.own(state, "s99", ["T-0001"])  # the same task cannot be created twice
            rows = [{"id": "T-0001", "written": True, "verified": True, "sha256": "a" * 64}, {"id": "T-0002", "written": False, "verified": False}]
            result = scheduler.submit(state, "s99", {"rows": rows})
            self.assertEqual((result["approved"], result["failed"]), (1, 1))
            saves = pathlib.Path(folder) / "saves"
            saves.mkdir(mode=0o700)
            self.assertTrue(scheduler.checkpoint(state, saves / "one.json")["restore_matches"])


class WorkloadTests(unittest.TestCase):
    def test_tasks_are_reproducible_distinct_and_tested(self):
        self.assertEqual(workload.task(7, 1)["fingerprint"], workload.task(7, 1)["fingerprint"])
        made = [workload.task(n, 1) for n in range(1, 41)]
        self.assertEqual(len({m["fingerprint"] for m in made}), 40)
        self.assertEqual(len({m["family"] for m in made}), 10)
        self.assertTrue(all(len(m["tests"]) >= 12 and any("raises" in t for t in m["tests"]) for m in made))

    def test_the_checker_passes_right_code_and_rejects_missing_wrong_and_unsafe_code(self):
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder)
            made = workload.make(out, 1, 4, 5)
            for index, body in enumerate(["right", "unsafe", "wrong"]):
                item = made[index]
                table = {repr(t["args"]): t for t in item["tests"]}
                source = f"TABLE = {table!r}\n\n\ndef {item['function']}(*args):\n    row = TABLE[repr(list(args))]\n    if 'raises' in row:\n        raise ValueError\n    return row['expect']\n"
                if body == "unsafe":
                    source = "import os\n" + source
                if body == "wrong":
                    source = f"def {item['function']}(*args):\n    return None\n"
                (out / item["id"] / "solution.py").write_text(source)
            result = workload.check(out)
            self.assertEqual((result["tasks"], result["written"], result["verified"], result["security_findings"]), (4, 3, 1, 1))
            self.assertEqual([row["verified"] for row in result["rows"]], [True, False, False, False])


class ProtectTests(unittest.TestCase):
    def test_the_ladder_climbs_only_while_every_limit_holds(self):
        self.assertTrue(protect.decide([stage(1, 12), stage(5, 14)], 10)[0])
        self.assertTrue(protect.decide([stage(1, 12, orchestrator_share_of_all_tokens=0.75)], 5)[0])
        cases = {
            "limit": [stage(1, 12), stage(5, 14, agents_with_limit_error=1)],
            "verified": [stage(1, 12), stage(5, 14, verified_success_rate=80.0)],
            "security": [stage(1, 12), stage(5, 14, security_findings=1)],
            "throughput": [stage(1, 12), stage(10, 29.46), stage(20, 29.64)],
            "under half": [stage(1, 12), stage(10, 14, effective_concurrency=4.0)],
            "orchestrator": [stage(1, 12), stage(5, 14, orchestrator_share_of_all_tokens=0.6)],
            "memory": [stage(1, 12), stage(5, 14, machine={"least_memory_available_mb": 900, "peak_host_process_rss_mb": 500})],
        }
        for word, stages in cases.items():
            go, reasons = protect.decide(stages, 25)
            self.assertFalse(go, word)
            self.assertIn(word, " ".join(reasons))
        go, reasons = protect.decide([stage(1, 12), stage(10, 14), stage(20, 30)], 25)
        self.assertFalse(go)
        self.assertIn("past 40,000,000", " ".join(reasons))


class MeasureTests(unittest.TestCase):
    def test_usage_is_summed_once_per_reply_and_helpers_are_recognised(self):
        usage = {"input_tokens": 3, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 50}
        lines = [
            {"type": "user", "timestamp": "2026-11-28T02:00:00.000Z", "message": {"content": "Read /x/T-0042/TASK.md and do it."}},
            {"type": "assistant", "timestamp": "2026-11-28T02:00:02.000Z", "message": {"id": "m1", "model": "light", "usage": usage, "content": [{"type": "text", "text": "ok"}]}},
            {"type": "assistant", "timestamp": "2026-11-28T02:00:02.500Z", "message": {"id": "m1", "model": "light", "usage": usage,
             "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "hr run -- python3 -m unittest"}}]}},
            {"type": "user", "timestamp": "2026-11-28T02:00:04.000Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x" * 120}]}},
            {"type": "assistant", "timestamp": "2026-11-28T02:00:06.000Z", "message": {"id": "m2", "model": "light", "usage": usage,
             "content": [{"type": "tool_use", "id": "t2", "name": "SubagentHandback", "input": {"report": "DONE"}}]}},
        ]
        with tempfile.TemporaryDirectory() as folder:
            record = pathlib.Path(folder) / "a.output"
            record.write_text("\n".join(json.dumps(line) for line in lines))
            row = measure.read(record)
        self.assertEqual((row["task"], row["roundtrips"], row["input_total"], row["output"], row["seconds"]), ("T-0042", 2, 2006, 100, 6.0))
        self.assertEqual((row["helpers"], row["tool_output_chars"], row["final_reply"], row["cache_read_share"]), ({"hr": 1}, 120, "DONE", round(1800 / 2006, 4)))
        self.assertEqual(measure.peak([{"start": 0, "end": 5}, {"start": 1, "end": 3}, {"start": 4, "end": 9}]), 2)


class BenchTests(unittest.TestCase):
    def test_the_planted_bug_fails_tests_until_the_one_function_is_fixed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder) / "proj"
            made = bench.build(root, 3)
            run = lambda: subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=root, capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}).returncode  # noqa: E731
            self.assertNotEqual(run(), 0)
            self.assertFalse(bench.check(root, root, made["truth"])["tests_pass"])
            module = made["truth"]["fixed_function"].split(".")[0]
            (root / "inv" / f"{module}.py").write_text(bench.source(bench.design(3), module, False))
            (root / "ANSWER.json").write_text(json.dumps(made["truth"]))
            scored = bench.check(root, root, made["truth"])
            self.assertEqual((run(), scored["score"], scored["only_the_broken_module_changed"]), (0, scored["out_of"], True))
            self.assertGreaterEqual(len(made["truth"]["direct_callers"]), 2)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.ladder = json.loads((SWARM / "evidence" / "ladder.json").read_text())["ladder"]
        self.summary = json.loads((SWARM / "evidence" / "summary.json").read_text())

    def test_only_the_stages_that_ran_are_reported(self):
        self.assertEqual([s["label"] for s in self.ladder], self.summary["agents"]["stages_run"])
        self.assertEqual(self.summary["agents"]["stages_not_run"], ["s25", "s50", "s75", "s100"])
        self.assertTrue(all(s["verified_tasks"] == s["tasks"] and s["peak_concurrent_agents"] == s["actual_agents"] for s in self.ladder))
        started = sum(s["actual_agents"] for s in self.ladder) + 2
        self.assertEqual((self.summary["agents"]["actual_ai_agents_started"], self.summary["agents"]["peak_concurrent_ai_agents"]), (started, self.ladder[-1]["actual_agents"]))
        self.assertLessEqual(self.summary["tokens"]["all_experiment_agents_input"], protect.LIMITS["max_input_tokens"])
        self.assertFalse(protect.decide(self.ladder, 25)[0])

    def test_readme_and_state_quote_the_evidence_and_name_no_private_path(self):
        readme = (SWARM / "README.md").read_text()
        for row in self.ladder:
            self.assertIn(f"| {row['actual_agents']} | {row['peak_concurrent_agents']} | {row['tasks']} | {row['verified_tasks']} | {row['wall_seconds']} | {row['tasks_per_minute']} |", readme)
            self.assertIn(f"{row['agent_tokens']['input_total']:,}", readme)
        for name in ("TASK_STATE.json", "ENGINEERING_HANDOVER.md", "RESUME.txt", "AGENT_STATUS.json", "TEST_EVIDENCE.json", "BENCHMARK_RESULTS.json", "RESOURCE_METRICS.json", "BLOCKERS.md"):
            self.assertTrue((SWARM / "state" / name).is_file(), name)
        for path in [*(SWARM / "evidence").iterdir(), *(SWARM / "state").iterdir(), SWARM / "README.md"]:
            text = path.read_text()
            for private in ("/root/", "/home/", "/Users/", "/tmp/", "@gmail", "session_0"):
                self.assertFalse(private in text, f"{path.name} contains {private}")

    def test_the_audit_counts_calls_outside_the_contract(self):
        audit = json.loads((SWARM / "evidence" / "tool-audit.json").read_text())
        self.assertEqual(audit["calls_outside_the_task_contract"], len(audit["detail"]))
        self.assertEqual(audit["of_which_refused_by_the_host"], sum(row["refused"] for row in audit["detail"]))
        self.assertEqual(audit["agents"], self.summary["agents"]["actual_ai_agents_started"])


if __name__ == "__main__":
    unittest.main()


class ReviewFixTests(unittest.TestCase):
    """Each of these fails on the code the independent review criticised."""

    def test_every_script_a_capability_names_exists_or_names_its_pull_request(self):
        import re
        for row in json.loads((SWARM / "capabilities.json").read_text())["capabilities"]:
            for path in re.findall(r"(?:skills|scripts|swarm|packages|tools)/[\w./-]+\.(?:py|sh|mjs)", row["invoke"] or ""):
                self.assertTrue((ROOT / path).exists() or "PR #16" in row["implementation"], f"{row['id']} names {path}")

    def test_the_screen_refuses_the_classic_escape_and_allows_plain_code(self):
        self.assertEqual(workload.inspect("def f(x):\n    return sorted(x)\n"), [])
        self.assertIn("use of __class__", workload.inspect("def f(x):\n    return ().__class__.__mro__\n"))
        self.assertIn("import of inv.m1", workload.inspect("from inv.m1 import f\n"))
        self.assertEqual(workload.inspect("from inv.m1 import f\n", workload.ALLOWED_IMPORTS | {"inv"}), [])

    def test_a_worktree_with_edited_tests_or_unsafe_code_is_never_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder) / "proj"
            made = bench.build(root, 4)
            (root / "tests" / "test_inv.py").write_text("import os\nos.system('touch ran')\n")
            refused = bench.check(root, root, made["truth"])
            self.assertEqual((refused["tests_pass"], refused["score"]), (False, 0))
            self.assertIn("tests/test_inv.py", refused["refused_to_run"])
            self.assertFalse((root / "ran").exists())
            subprocess.run(["git", "-C", str(root), "checkout", "-q", "--", "tests"], check=True)
            module = made["truth"]["fixed_function"].split(".")[0]
            (root / "inv" / f"{module}.py").write_text("import socket\n" + bench.source(bench.design(4), module, False))
            self.assertIn(f"inv/{module}.py: import of socket", bench.check(root, root, made["truth"])["refused_to_run"])

    def test_limits_and_review_are_recorded_with_how_they_were_observed(self):
        limits = json.loads((SWARM / "evidence" / "host-limits.json").read_text())
        review = json.loads((SWARM / "evidence" / "review.json").read_text())
        self.assertTrue(all("how" in limits[key] for key in ("machine", "agent_tool", "workflow_tool", "agent_definitions", "network")))
        self.assertLessEqual(limits["workflow_tool"]["peak_concurrent_measured"], limits["workflow_tool"]["agents_in_this_run"])
        self.assertEqual(review["findings"], len(review["detail"]))
        self.assertTrue(all(row["action"] != "reviewed" for row in review["detail"]))
        both = json.loads((SWARM / "evidence" / "headroom-two-integrations.json").read_text())["samples"]
        self.assertEqual(len(both), 3)
