"""The development team of the third phase: its lanes, the net under each agent, and the joining of the lanes.
No agent and no model is started here."""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
P3 = ROOT / "swarm" / "phase3"
sys.path.insert(0, str(P3))
import lane_guard  # noqa: E402

TEAM = json.loads((P3 / "TEAM.json").read_text())


class LaneTests(unittest.TestCase):
    def test_twenty_lanes_in_the_groups_the_owner_asked_for(self):
        groups = {}
        for lane in TEAM["lanes"]:
            groups[lane["group"]] = groups.get(lane["group"], 0) + 1
        self.assertEqual(groups, {"architecture": 3, "context": 4, "engine": 4, "scale": 3, "security": 2, "quality": 2, "integration": 1, "economics": 1})
        self.assertEqual(len({lane["id"] for lane in TEAM["lanes"]}), 20)
        self.assertTrue(all(re.fullmatch(r"[A-Z]\d", lane["id"]) for lane in TEAM["lanes"]))
        self.assertEqual(set(groups), set(TEAM["groups"]))

    def test_no_path_belongs_to_two_lanes_and_every_lane_brings_tests(self):
        owner = {}
        for lane in TEAM["lanes"]:
            self.assertTrue(any(re.fullmatch(r"tests/test_p3_\w+\.py", path) for path in lane["owns"]), lane["id"])
            self.assertGreater(len(lane["brief"]), 400, lane["id"])
            for path in lane["owns"]:
                self.assertFalse(path.startswith("/") or ".." in path, path)
                self.assertNotIn(path, owner, f"{path} is owned by {owner.get(path)} and {lane['id']}")
                owner[path] = lane["id"]
        self.assertEqual({path: who for path, who in owner.items() if path.startswith("swarm/phase2/")}, {"swarm/phase2/guard.py": "S1", "swarm/phase2/kit.py": "S1"},
                         "the second phase's files are read-only, but for the two the security lane may repair")
        self.assertFalse([path for path in owner if path.startswith("swarm/") and not path.startswith(("swarm/phase2/", "swarm/phase3/"))], "nothing of the first phase")
        self.assertNotIn("swarm/phase3/team.py", owner)
        self.assertNotIn("swarm/phase3/CONTRACT.md", owner)

    def test_the_contract_names_every_module_another_lane_may_rely_on(self):
        contract = (P3 / "CONTRACT.md").read_text()
        for lane in TEAM["lanes"]:
            for path in lane["owns"]:
                if path.startswith("swarm/phase3/") and path.endswith(".py") and lane["id"] not in ("Q2",):
                    self.assertIn(f"`{pathlib.Path(path).name}`", contract, path)
        self.assertIn("standard library only", contract)

    def test_the_queue_gives_each_task_to_one_worker_and_keeps_to_the_batch(self):
        import taskqueue  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as folder:
            stage = pathlib.Path(folder)
            taskqueue.create(stage, [f"S-{n:04d}" for n in range(1, 8)], 3)
            taken = [taskqueue.claim(stage, "w1") for _ in range(4)] + [taskqueue.claim(stage, "w2") for _ in range(4)] + [taskqueue.claim(stage, "w3") for _ in range(2)]
            self.assertEqual(taken, ["S-0001", "S-0002", "S-0003", None, "S-0004", "S-0005", "S-0006", None, "S-0007", None])
            taskqueue.release(stage, "S-0001", "w1", "handed-in")
            taskqueue.release(stage, "S-0001", "w1", "failed")
            taskqueue.release(stage, "S-0004", "w2", "failed")
            now = taskqueue.status(stage)
            self.assertEqual((now["waiting"], now["claimed"], now["handed_in"], now["failed"], now["workers"]), (0, 5, 1, 1, 3))
            self.assertEqual(taskqueue.holder(stage, "S-0002"), "w1")
            with self.assertRaises(ValueError):
                taskqueue.claim(stage, "../w")


class NetTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.lanes = pathlib.Path(self.folder.name) / "lanes"
        (self.lanes / "E2").mkdir(parents=True)
        os.environ["SWARM_LANES"] = str(self.lanes)
        self.addCleanup(os.environ.pop, "SWARM_LANES", None)

    def test_a_development_agent_writes_only_inside_the_lanes(self):
        inside = {"tool_name": "Write", "tool_input": {"file_path": str(self.lanes / "E2" / "swarm" / "phase3" / "adaptive.py")}}
        self.assertTrue(lane_guard.allowed(inside)[0])
        for target in (str(ROOT / "hub.py"), "/etc/passwd", str(self.lanes / "E2" / ".." / ".." / "x.py"), str(self.lanes) + "-other/x.py"):
            self.assertFalse(lane_guard.allowed({"tool_name": "Edit", "tool_input": {"file_path": target}})[0], target)
        self.assertFalse(lane_guard.allowed({"tool_name": "Write", "tool_input": {}})[0])
        self.assertFalse(lane_guard.allowed({"tool_name": "Agent", "tool_input": {}})[0])

    def test_the_shell_may_test_and_commit_and_may_not_push_fetch_switch_or_install(self):
        wt = self.lanes / "E2"
        for command in (f"cd {wt} && python3 -m unittest tests.test_p3_adaptive", f"git -C {wt} add -A && git -C {wt} commit -q -m 'Lane E2: the next wave'",
                        f"git -C {wt} status --short", f"git -C {wt} diff --stat", "swk-brief LANE-E2", f"python3 {wt}/swarm/phase3/adaptive.py --help",
                        f"ls {wt}/swarm/phase3 | head", f"cat > {wt}/x.py <<'PY'\n# pip and curl are only words here; git push too\nPY"):
            self.assertTrue(lane_guard.allowed({"tool_name": "Bash", "tool_input": {"command": command}})[0], command)
        for command in (f"git -C {wt} push origin HEAD", "git push", f"cd {wt} && git checkout main", f"git -C {wt} merge claude/p3-e1", "git fetch origin", "git remote -v",
                        "git worktree add ../x", "curl https://example.org", "true; wget x", "pip install requests", "python3 -m pip install x", "uv pip install x",
                        "npm install", "sudo ls", "echo hi | nc example.org 80", "env A=1 curl x", "git -c user.name=x pull",
                        "bash <<'EOF'\ngit push\nEOF", f"cat > {wt}/x.py <<'PY'\nx = 1\nPY\ngit push"):
            self.assertFalse(lane_guard.allowed({"tool_name": "Bash", "tool_input": {"command": command}})[0], command)

    def test_the_net_refuses_what_it_cannot_read(self):
        def run(text):
            return subprocess.run([sys.executable, "-I", str(P3 / "lane_guard.py")], input=text, capture_output=True, text=True, env={"PATH": os.environ["PATH"], "SWARM_LANES": str(self.lanes)})

        self.assertEqual(run(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})).returncode, 0)
        refused = run(json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}}))
        self.assertEqual(refused.returncode, 2)
        self.assertIn(lane_guard.MARK, refused.stderr)
        for text in ("", "nonsense", json.dumps([1]), json.dumps({"tool_name": "Bash", "tool_input": {"command": 5}})):
            self.assertEqual(run(text).returncode, 2, text)

    def test_the_development_agent_has_six_tools_the_net_and_a_turn_limit(self):
        front = (ROOT / ".claude" / "agents" / "swarm-dev.md").read_text().split("---")[1]
        self.assertIn("\ntools: Read, Write, Edit, Bash, Grep, Glob\n", front)
        self.assertIn('matcher: "Write|Edit|Bash"', front)
        self.assertIn('command: "swk-lane-guard"', front)
        self.assertRegex(front, r"\nmaxTurns: \d+\n")
        self.assertEqual(TEAM["agent_type"], "swarm-dev")


class JoinTests(unittest.TestCase):
    def test_lanes_are_joined_one_by_one_and_a_lane_outside_its_paths_is_rejected_whole(self):
        with tempfile.TemporaryDirectory() as folder:
            home = pathlib.Path(folder)
            repo, records = home / "repo", home / "records"
            (repo / "swarm" / "phase3").mkdir(parents=True)
            (repo / "tests").mkdir()
            records.mkdir()
            (home / "bin").mkdir()
            (home / "main.jsonl").write_text("")
            lanes = [{"id": "X1", "group": "engine", "title": "a good lane", "owns": ["swarm/phase3/a.py", "tests/test_p3_a.py"], "brief": "write a"},
                     {"id": "X2", "group": "engine", "title": "a lane that strays", "owns": ["swarm/phase3/b.py", "tests/test_p3_b.py"], "brief": "write b"},
                     {"id": "X3", "group": "scale", "title": "a lane whose tests fail", "owns": ["swarm/phase3/c.py", "tests/test_p3_c.py"], "brief": "write c"},
                     {"id": "X4", "group": "scale", "title": "a lane that did nothing", "owns": ["swarm/phase3/d.py", "tests/test_p3_d.py"], "brief": "write d"}]
            (repo / "swarm" / "phase3" / "TEAM.json").write_text(json.dumps({"agent_type": "swarm-dev", "model": "sonnet", "effort": "medium", "lanes": lanes}))
            (repo / "swarm" / "phase3" / "CONTRACT.md").write_text("# Contract\n")
            (repo / "README.md").write_text("base\n")
            env = {"PATH": f"{home / 'bin'}:{os.environ['PATH']}", "HOME": str(home), "SWARM_TEAM_ROOT": str(repo), "SWARM_LANES": str(home / "lanes"), "SWARM_BIN": str(home / "bin"),
                   "SWARM_MAIN_RECORD": str(home / "main.jsonl"), "SWARM_RECORDS": str(records), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": "/dev/null"}

            def git(*arguments, cwd=repo):
                return subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True, env=env, check=True).stdout

            def team(*arguments):
                return subprocess.run([sys.executable, str(P3 / "team.py"), *arguments], capture_output=True, text=True, env=env)

            git("init", "-q", "-b", "claude/swarm-phase-3")
            git("add", "-A")
            git("commit", "-q", "-m", "base")
            started = team("setup")
            self.assertEqual(started.returncode, 0, started.stderr)
            self.assertIn("start 4 agents, all in ONE message", started.stdout)
            self.assertIn("LANE-X1 LANE-X2 LANE-X3 LANE-X4", started.stdout)
            told = subprocess.run(["swk-brief", "LANE-X2"], capture_output=True, text=True, env=env).stdout
            self.assertIn(f"Your worktree: {(home / 'lanes' / 'X2').resolve()}", told)
            self.assertIn("swarm/phase3/b.py, tests/test_p3_b.py", told)
            self.assertIn("# Contract", told)
            self.assertTrue(told.rstrip().endswith("write b"))
            work = {"X1": {"swarm/phase3/a.py": "A = 1\n", "tests/test_p3_a.py": "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n"},
                    "X2": {"swarm/phase3/b.py": "B = 1\n", "tests/test_p3_b.py": "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_b(self):\n        pass\n", "README.md": "changed\n"},
                    "X3": {"swarm/phase3/c.py": "C = 1\n", "tests/test_p3_c.py": "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_c(self):\n        self.fail('no')\n"}}
            for lane, files in work.items():
                tree = home / "lanes" / lane
                for name, text in files.items():
                    (tree / name).parent.mkdir(parents=True, exist_ok=True)
                    (tree / name).write_text(text)
                git("add", "-A", cwd=tree)
                git("commit", "-q", "-m", f"Lane {lane}", cwd=tree)
            usage = {"input_tokens": 10, "cache_creation_input_tokens": 4000, "cache_read_input_tokens": 16000, "output_tokens": 300}
            (records / "agent-x1.jsonl").write_text("\n".join(json.dumps(line) for line in (
                {"type": "user", "timestamp": "2026-11-28T10:00:00Z", "message": {"role": "user", "content": "LANE-X1"}},
                {"type": "assistant", "timestamp": "2026-11-28T10:00:05Z", "message": {"id": "m1", "model": "claude-sonnet-4-5", "usage": usage, "content": [{"type": "text", "text": "DONE a"}]}})) + "\n")
            joined = team("integrate")
            self.assertEqual(joined.returncode, 0, joined.stderr)
            text = (repo / "swarm" / "phase3" / "evidence" / "team.json").read_text()
            evidence = json.loads(text)
            states = {row["lane"]: row["state"] for row in evidence["lanes"]}
            self.assertEqual(states["X1"], "joined")
            self.assertTrue(states["X2"].startswith("rejected"))
            self.assertEqual(states["X3"], "not joined: its own tests fail here")
            self.assertEqual(states["X4"], "nothing committed")
            self.assertEqual(next(row for row in evidence["lanes"] if row["lane"] == "X2")["outside"], ["README.md"])
            self.assertTrue((repo / "swarm" / "phase3" / "a.py").exists())
            self.assertFalse((repo / "swarm" / "phase3" / "b.py").exists())
            self.assertFalse((repo / "swarm" / "phase3" / "c.py").exists(), "a lane whose tests fail is taken out again")
            self.assertEqual((repo / "README.md").read_text(), "base\n")
            self.assertIn("Join lane X1: a good lane", git("log", "--oneline"))
            totals = evidence["totals"]
            self.assertEqual((totals["joined"], totals["agents_started"], totals["input_tokens"], totals["tests_added_joined"]), (1, 1, 20010, 1))
            self.assertEqual(next(row for row in evidence["lanes"] if row["lane"] == "X1")["agent"]["model"], "sonnet")
            self.assertEqual(evidence["suite_after_joining"], {"tests": 1, "passed": True})
            for private in (str(home), "/tmp/", "claude-sonnet-4-5"):
                self.assertNotIn(private, text)


if __name__ == "__main__":
    unittest.main()
