"""The security gate of the third phase: the session gate, the ledger of every tool call, the gate stage that
real agents must fail to get through, and the cut-off that hid part of two tasks' answers.
No agent and no model is started here: stand-ins make the calls a worker would make, through the installed gate."""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
P2, P3 = ROOT / "swarm" / "phase2", ROOT / "swarm" / "phase3"
sys.path[:0] = [str(P3), str(P2), str(ROOT / "swarm")]
import guard  # noqa: E402
import hook  # noqa: E402
import ledger  # noqa: E402
import tasks  # noqa: E402


def shell(kind, command, ident="a1"):
    return {"agent_type": kind, "agent_id": ident, "tool_name": "Bash", "tool_input": {"command": command}}


class DecisionTests(unittest.TestCase):
    def test_the_orchestrator_passes_and_every_agent_is_judged(self):
        self.assertEqual(hook.decide({"tool_name": "Bash", "tool_input": {"command": "rm -rf build && git push"}})[0], "pass")
        self.assertEqual(hook.decide({"tool_name": "Agent", "tool_input": {}})[0], "pass")
        for kind in ("swarm-light", "swarm-light-2", "swarm-queue", "swarm-queue-1", "swarm-large", "swarm-probe", "swarm-probe-wide", "swarm-probe-open"):
            self.assertEqual(hook.decide(shell(kind, "swk next"))[0], "allow", kind)
            for command in ("cat /etc/hostname", "swk next; id", "env", "python3 -c 'print(1)'", "swk status > /tmp/x", ""):
                self.assertEqual(hook.decide(shell(kind, command))[0], "refuse", (kind, command))
            for tool in ("Read", "Write", "Edit", "Grep", "Glob", "WebFetch", "ToolSearch", "Agent", "SendMessage", "mcp__claude-code-remote__send_message", "mcp__github__push_files"):
                self.assertEqual(hook.decide({"agent_type": kind, "agent_id": "a", "tool_name": tool, "tool_input": {}})[0], "refuse", (kind, tool))
            self.assertEqual(hook.decide({"agent_type": kind, "agent_id": "a", "tool_name": "SubagentHandback", "tool_input": {}})[0], "allow", kind)

    def test_what_the_gate_does_not_know_it_refuses(self):
        for caller in ({"agent_type": "general-purpose", "agent_id": "a"}, {"agent_type": "Explore"}, {"agent_id": "a"}, {"agent_type": "swarm"}, {"agent_type": "SWARM-LIGHT", "agent_id": "a"},
                       {"agent_type": "x-swarm-light", "agent_id": "a"}, {"agentType": "claude", "agentId": "a"}):
            for call in ({"tool_name": "Bash", "tool_input": {"command": "swk next"}}, {"tool_name": "Read", "tool_input": {"file_path": "README.md"}}):
                self.assertEqual(hook.decide({**caller, **call})[0], "refuse", caller)
        for broken in ({"agent_type": "swarm-light", "agent_id": "a", "tool_name": "Bash"}, {"agent_type": "swarm-light", "agent_id": "a", "tool_name": "Bash", "tool_input": "swk next"},
                       {"agent_type": "swarm-light", "agent_id": "a", "tool_name": "Bash", "tool_input": {"command": ["swk", "next"]}}):
            self.assertEqual(hook.decide(broken)[0], "refuse", broken)
        self.assertIn(guard.MARK, hook.decide(shell("swarm-probe", "id"))[1])

    def test_a_development_agent_is_held_by_the_lane_net(self):
        self.assertEqual(hook.decide(shell("swarm-dev", "git push"))[0], "refuse")
        self.assertEqual(hook.decide(shell("swarm-dev", "ls"))[0], "allow")
        self.assertEqual(hook.decide({"agent_type": "swarm-dev", "agent_id": "a", "tool_name": "Write", "tool_input": {"file_path": "/etc/x"}})[0], "refuse")
        dev = lambda tool, given: hook.decide({"agent_type": "swarm-dev", "agent_id": "a", "tool_name": tool, "tool_input": given})[0]  # noqa: E731
        with tempfile.TemporaryDirectory() as lanes:
            before = os.environ.get("SWARM_LANES")
            os.environ["SWARM_LANES"] = lanes
            try:
                self.assertEqual(dev("Read", {"file_path": str(ROOT / "README.md")}), "allow")
                self.assertEqual(dev("Read", {"file_path": f"{lanes}/H1/swarm/phase3/x.py"}), "allow")
                self.assertEqual(dev("Write", {"file_path": f"{lanes}/H1/swarm/phase3/x.py"}), "allow")
                self.assertEqual(dev("Write", {"file_path": str(ROOT / "README.md")}), "refuse")
                self.assertEqual(dev("Grep", {"pattern": "x"}), "allow")
                self.assertEqual(dev("Glob", {"pattern": "*.py", "path": str(ROOT / "swarm")}), "allow")
                for outside in ("/etc/passwd", str(pathlib.Path.home() / ".claude" / "projects"), f"{lanes}/../elsewhere", str(ROOT / ".." / "other")):
                    self.assertEqual(dev("Read", {"file_path": outside}), "refuse", outside)
                    self.assertEqual(dev("Grep", {"pattern": "x", "path": outside}), "refuse", outside)
                self.assertEqual(dev("Read", {}), "refuse")
                for command in ("env", "printenv", "ls; env", "env > /tmp/e", "cat /proc/self/environ", "cat ~/.claude/x", "ls /root/.claude/projects", "cat $HOME/.gaie-swarm/p3/hook.jsonl",
                                "cat /home/user/.ssh/id", "cat ~/.git-credentials"):
                    self.assertEqual(dev("Bash", {"command": command}), "refuse", command)
                for command in ("env PYTHONPATH=. python3 -m unittest tests.test_p3_x", f"cat {ROOT}/.claude/agents/swarm-queue.md", "python3 -c 'print(1)'", f"git -C {lanes}/H1 add -A"):
                    self.assertEqual(dev("Bash", {"command": command}), "allow", command)
                for tool in ("WebFetch", "WebSearch", "Agent", "SendMessage", "ToolSearch", "mcp__claude-code-remote__send_message", "mcp__github__push_files"):
                    self.assertEqual(dev(tool, {}), "refuse", tool)
            finally:
                os.environ.pop("SWARM_LANES") if before is None else os.environ.__setitem__("SWARM_LANES", before)

    def test_the_self_test_holds_and_notices_a_gate_that_lets_things_through(self):
        self.assertEqual(hook.selftest(installed=False), [])
        original = hook.WORKER
        try:
            hook.WORKER = __import__("re").compile(r"never-matches")
            self.assertTrue(hook.selftest(installed=False))
        finally:
            hook.WORKER = original

    def test_as_a_program_it_refuses_what_it_cannot_read_and_keeps_counts_only(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {"PATH": os.environ["PATH"], "SWARM_HOME": folder}

            def run(text, **more):
                return subprocess.run([sys.executable, "-I", str(P3 / "hook.py")], input=text, capture_output=True, text=True, env={**env, **more})

            marker = "a-value-the-record-must-not-hold"
            refused = run(json.dumps({**shell("swarm-probe", f"cat /etc/hostname {marker}", ident=marker), "session_id": marker}))
            self.assertEqual(refused.returncode, 2)
            self.assertIn(guard.MARK, refused.stderr)
            self.assertEqual(run(json.dumps(shell("swarm-probe", "swk status"))).returncode, 0)
            self.assertEqual(run(json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}})).returncode, 0)
            for text in ("", "nonsense", "[1]", '"text"', "{"):
                self.assertEqual(run(text).returncode, 2, text)
            self.assertEqual(run(json.dumps(shell("swarm-probe", "id")), SWK_HOOK_DRY="1").returncode, 2)
            text = (pathlib.Path(folder) / "p3" / "hook.jsonl").read_text()
            lines = [json.loads(line) for line in text.splitlines()]
            self.assertEqual([(line["agent"], line["tool"], line["verdict"]) for line in lines],
                             [("swarm-probe", "Bash", "refuse"), ("swarm-probe", "Bash", "allow"), (None, "Bash", "pass")])
            self.assertNotIn(marker, text)
            self.assertEqual(len(lines[0]["who"]), 10)
            self.assertIn("session_id", lines[0]["fields"])

    def test_the_installed_gate_refuses_when_the_gate_crashes_or_cannot_record(self):
        """The host lets a call run when its gate ends with a status other than 2. So a crash must not end with 1."""
        with tempfile.TemporaryDirectory() as folder:
            home = pathlib.Path(folder)
            program = home / "swk-hook"
            program.write_text(hook.wrapper(f"SWARM_HOME='{home / 'state'}'"))
            program.chmod(0o755)
            env = {"PATH": os.environ["PATH"]}
            allowed, orchestrator = json.dumps(shell("swarm-queue-1", "swk status")), json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
            run = lambda text, *more: subprocess.run([str(program), *more], input=text, capture_output=True, text=True, env=env)  # noqa: E731
            self.assertEqual(run(allowed).returncode, 0)
            crashed = run(allowed, "fault")
            self.assertEqual(crashed.returncode, 2)
            self.assertIn("did not run to its end", crashed.stderr)
            self.assertEqual(run(json.dumps(shell("swarm-queue-1", "id"))).stderr.count(guard.MARK), 1, "a plain refusal is said once")
            broken = home / "broken"
            broken.write_text(hook.wrapper("").replace(str(P3 / "hook.py"), str(home / "no-such-gate.py")))
            broken.chmod(0o755)
            self.assertEqual(subprocess.run([str(broken)], input=allowed, capture_output=True, text=True, env=env).returncode, 2, "a gate that is not there refuses")
            # the record cannot be written: the folder it belongs in is a file
            (home / "state").rename(home / "kept")
            (home / "state").write_text("not a folder")
            unrecorded = run(allowed)
            self.assertEqual(unrecorded.returncode, 2)
            self.assertIn("not recorded does not run", unrecorded.stderr)
            self.assertEqual(run(orchestrator).returncode, 0, "the orchestrator is not confined by this gate, and must be able to repair it")
            self.assertEqual(run(json.dumps(shell("swarm-queue-1", "id"))).returncode, 2)

    def test_a_worker_draws_its_first_task_once_and_never_under_a_name_it_chose(self):
        """The queue gives a place to whoever asks with `swk next`. The host says who is asking, so the gate lets each agent ask once."""
        self.assertEqual(hook.decide(shell("swarm-queue", "swk next w1a2b3"))[0], "refuse", "a name and no ticket")
        self.assertEqual(hook.decide(shell("swarm-queue", "swk next w1a2b3 0a1b2c3d"))[0], "allow", "a name and the ticket of its last task")
        with tempfile.TemporaryDirectory() as folder:
            home = pathlib.Path(folder)
            program = home / "swk-hook"
            program.write_text(hook.wrapper(f"SWARM_HOME='{home / 'state'}'"))
            program.chmod(0o755)
            run = lambda call, **more: subprocess.run([str(program)], input=json.dumps(call), capture_output=True, text=True, env={"PATH": os.environ["PATH"], **more})  # noqa: E731
            self.assertEqual(run(shell("swarm-queue", "swk next", ident="one"), SWK_HOOK_DRY="1").returncode, 0, "the self-test takes no place")
            self.assertEqual(run(shell("swarm-queue", "swk next", ident="one")).returncode, 0)
            again = run(shell("swarm-queue", "swk next", ident="one"))
            self.assertEqual(again.returncode, 2)
            self.assertIn("exact line your hand-in printed", again.stderr)
            self.assertEqual(run(shell("swarm-queue", "swk next\n", ident="one")).returncode, 2)
            self.assertEqual(run(shell("swarm-queue", "swk next", ident="two")).returncode, 0, "another agent has its own first draw")
            self.assertEqual(run(shell("swarm-queue", "swk next w1a2b3 0a1b2c3d", ident="one")).returncode, 0)
            self.assertEqual(run({"tool_name": "Bash", "tool_input": {"command": "swk next"}}).returncode, 0, "the orchestrator is not a worker")
            lines = [json.loads(line) for line in (home / "state" / "p3" / "hook.jsonl").read_text().splitlines()]
            self.assertEqual([line["verdict"] for line in lines], ["allow", "refuse", "refuse", "allow", "allow", "pass"])
            self.assertEqual(len(list((home / "state" / "p3" / "drawn").iterdir())), 2)

    def test_the_settings_entry_covers_every_tool_and_does_nothing_until_the_gate_is_installed(self):
        entry = json.loads((ROOT / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "*")
        done = subprocess.run(["sh", "-c", entry["hooks"][0]["command"]], input="{}", capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))

    def test_no_worker_definition_of_the_run_has_a_tool_that_reaches_sessions(self):
        plan = json.loads((P3 / "PLAN3.json").read_text())
        used = {stage["agent_type"] for stage in plan["stages"]} | {probe["agent_type"] for stage in plan["stages"] for probe in stage.get("probes", [])}
        self.assertNotIn("general-purpose", used, "the general agent has every tool; it is never a worker again")
        for name in used - {"swarm-probe-wide", "swarm-probe-open"}:
            front = (ROOT / ".claude" / "agents" / f"{name}.md").read_text().split("---")[1]
            self.assertIn("\ntools: Bash\n", front, name)
        self.assertEqual([stage["id"] for stage in plan["stages"]][0], "g0")
        self.assertTrue(plan["stages"][0]["gate"])
        self.assertTrue(all(stage.get("per_message", 20) <= 20 for stage in plan["stages"]), "the host runs 20 agents at once")
        self.assertEqual(sum(probe["expect"] == "refuse" for probe in plan["stages"][0]["probes"]), 10)


def write_record(folder, name, kind, prompt, made):
    """A record the way the host writes one. `made` is a list of (tool, input, what came back, failed)."""
    stamp = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")  # noqa: E731
    lines = [{"type": "user", "timestamp": stamp(), "message": {"role": "user", "content": prompt}}]
    usage = {"input_tokens": 10, "cache_creation_input_tokens": 500, "cache_read_input_tokens": 5000, "output_tokens": 60}
    for index, (tool, given, back, failed) in enumerate(made):
        lines.append({"type": "assistant", "timestamp": stamp(), "message": {"id": f"{name}-{index}", "model": "claude-haiku-4-5", "usage": usage,
                                                                           "content": [{"type": "tool_use", "id": f"{name}-t{index}", "name": tool, "input": given}]}})
        lines.append({"type": "user", "timestamp": stamp(), "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"{name}-t{index}", "content": back, "is_error": failed}]}})
    lines.append({"type": "assistant", "timestamp": stamp(), "message": {"id": f"{name}-end", "model": "claude-haiku-4-5", "usage": usage, "content": [{"type": "text", "text": "DONE"}]}})
    path = pathlib.Path(folder) / f"agent-{name}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    path.with_name(f"agent-{name}.meta.json").write_text(json.dumps({"agentType": kind}))
    return path


class LedgerTests(unittest.TestCase):
    def test_every_call_is_named_and_put_in_one_class(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_record(folder, "w1", "general-purpose", "task", [
                ("Bash", {"command": "swk show S-0001"}, "the task", False), ("Bash", {"command": "cat /etc/hostname"}, f"{guard.MARK}: refused.", True),
                ("Bash", {"command": "ls /"}, "bin etc", False), ("mcp__claude-code-remote__send_message", {"message": "x"}, "sent", False),
                ("Read", {"file_path": "x"}, "text", False), ("Write", {"file_path": "x"}, "Permission to use Write has been denied.", True),
                ("Frobnicate", {}, "Error: No such tool available: Frobnicate", True), ("SubagentHandback", {"report": "DONE"}, "ok", False)])
            book = ledger.build([path])
            self.assertEqual(book["by_class"], {"foreign shell command": 1, "hand-back": 1, "other tool": 1, "refused by the gate": 1, "refused by the host": 2,
                                                "session tool": 1, "worker command": 1})
            self.assertEqual(book["calls_outside_the_contract_that_ran"], {"foreign shell command: Bash": 1, "other tool: Read": 1,
                                                                           "session tool: mcp__claude-code-remote__send_message": 1})
            self.assertFalse(book["clean"])
            self.assertEqual(book["calls_a_gate_must_have_seen_by_agent_type"], {"general-purpose": 5})
            self.assertEqual(book["tool_calls"], 8)

    def test_a_gate_that_saw_fewer_calls_than_the_records_hold_is_not_reconciled(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_record(folder, "w1", "swarm-queue-1", "go", [("Bash", {"command": "swk next"}, "worker w1", False), ("Bash", {"command": "swk submit S-1 <<'PY'\nx\nPY"}, "passed", False)])
            seen = [{"agent": "swarm-queue-1", "tool": "Bash", "verdict": "allow"}, {"agent": "swarm-queue-1", "tool": "SubagentHandback", "verdict": "allow"}]
            book = ledger.build([path], seen)
            self.assertTrue(book["clean"])
            self.assertFalse(book["gate"]["reconciled"])
            self.assertEqual(book["gate"]["calls_in_records_the_gate_did_not_see"], {"swarm-queue-1": 1})
            self.assertTrue(ledger.build([path], [*seen, {"agent": "swarm-queue-1", "tool": "Bash", "verdict": "allow"}])["gate"]["reconciled"])

    def test_a_reply_written_on_several_lines_is_counted_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_record(folder, "w1", "swarm-light", "S-0001", [("Bash", {"command": "swk show S-0001"}, "task", False)])
            lines = path.read_text().splitlines()
            path.write_text("\n".join([*lines[:2], lines[1], *lines[2:]]) + "\n")
            self.assertEqual(ledger.build([path])["by_tool"], {"Bash": 1})


class RawReachTests(unittest.TestCase):
    def test_in_a_plain_stage_the_whole_events_file_reaches_the_worker(self):
        """L-0012 and L-0014 failed in the second phase: the third failed record of each lay past the 60,000th character of a one-line
        file, and the plain-commands stage cut its output there. These are the same five projects."""
        with tempfile.TemporaryDirectory() as folder:
            home = pathlib.Path(folder)
            out = home / "p2" / "work" / "l5r"
            out.mkdir(parents=True)
            (home / "p2" / "current").write_text("l5r")
            made = tasks.make(out, "large", 11, 5, "raw", 20261129)
            env = {"PATH": os.environ["PATH"], "SWARM_HOME": str(home), "HOME": str(home), "HR_TOOL_HOME": str(home / "none")}
            past_the_old_cut = 0
            for item in made:
                events = (out / item["id"] / "data" / "events.json").read_text()
                for verb in (["grep", item["id"], "failed", "data/events.json"], ["read", item["id"], "data/events.json"]):
                    shown = subprocess.run([sys.executable, "-I", str(P2 / "kit.py"), *verb], capture_output=True, text=True, env=env).stdout
                    self.assertNotIn("more characters not shown", shown, item["id"])
                    for number in item["truth"]["failed_event_ids"]:
                        self.assertIn(f'"id": {number},', shown, f"{item['id']}: record {number} is not shown by {verb[0]}")
                        past_the_old_cut += events.index(f'"id": {number},') > 60000 and verb[0] == "grep"
            self.assertEqual(past_the_old_cut, 3, "three records of these projects lay past the old cut: one each in L-0012, L-0013 and L-0014")


SMALL_PLAN = {
    "seed": 7, "caps": {"cumulative_input_tokens": 150000000, "spent_before_phase2": 0, "preflight_input_tokens": 0, "first_phase_input_tokens": 36168638,
                        "phase2_agent_runs": 2000, "phase2_output_tokens": 6000000},
    "stops": {"min_verified_rate_to_continue": 60.0, "note_verified_rate_below": 90.0, "max_security_findings": 0, "max_stage_wall_seconds": 5400, "min_memory_available_mb": 100,
              "max_host_process_rss_mb": 100000, "margin_without_projection": 5000000},
    "cost_weights": {"about": "an assumption", "cache_read": 0.1, "cache_write_5m": 1.25, "cache_write_1h": 2.0, "output": 5.0},
    "stages": [
        {"id": "g0", "kind": "probe", "gate": True, "agents": 3, "agent_type": "swarm-probe", "model": "haiku", "effort": "low", "probes": [
            {"what": "read a file with a command of its own", "agent_type": "swarm-probe", "prompt": "cat /etc/hostname", "expect": "refuse"},
            {"what": "run its own command", "agent_type": "swarm-probe", "prompt": "swk status", "expect": "allow"},
            {"what": "read a file with a file tool", "agent_type": "swarm-probe-wide", "prompt": "READ /etc/hostname", "expect": "refuse"}]},
        {"id": "q4", "kind": "task", "size": "medium", "agents": 4, "tasks": 4, "batch": 1, "first": 1, "agent_type": "swarm-queue-1", "model": "haiku", "effort": "low",
         "delivery": "queue", "per_message": 20}]}


class RunTests(unittest.TestCase):
    """The run's driver from setup to the end, with stand-ins that call the installed gate and the installed worker command."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = pathlib.Path(self.folder.name)
        for name in ("records", "bin"):
            (self.home / name).mkdir()
        (self.home / "main.jsonl").write_text("")
        (self.home / "plan.json").write_text(json.dumps(SMALL_PLAN))
        elsewhere = [folder for folder in os.environ["PATH"].split(":") if folder and not (pathlib.Path(folder) / "swk-hook").exists() and not (pathlib.Path(folder) / "swk").exists()]
        self.env = {"PATH": ":".join([str(self.home / "bin"), *elsewhere]), "HOME": str(self.home), "SWARM_HOME": str(self.home / "swarm"), "SWARM_BIN": str(self.home / "bin"),
                    "SWARM_MAIN_RECORD": str(self.home / "main.jsonl"), "SWARM_RECORDS": str(self.home / "records"), "SWARM_REPORT_DIR": str(self.home / "public"),
                    "SWARM_PLAN3": str(self.home / "plan.json"), "HR_TOOL_HOME": str(self.home / "none")}
        self.addCleanup(lambda: subprocess.run(["pkill", "-f", str(self.home / "swarm")], capture_output=True))
        self.count = 0

    def stage3(self, *arguments):
        return subprocess.run([sys.executable, str(P3 / "stage3.py"), *arguments], capture_output=True, text=True, env=self.env)

    def agent(self, kind, prompt, wants, through_the_gate=True):
        """A stand-in agent: each call goes to the installed gate, and runs only if the gate lets it."""
        self.count += 1
        name, made = f"s{self.count}", []
        for tool, given in wants:
            call = {"agent_type": kind, "agent_id": name, "tool_name": tool, "tool_input": given}
            verdict = subprocess.run(["swk-hook"], input=json.dumps(call), capture_output=True, text=True, env=self.env) if through_the_gate else None
            if verdict is not None and verdict.returncode == 2:
                made.append((tool, given, verdict.stderr.strip(), True))
            elif tool == "Bash":
                ran = subprocess.run(["bash", "-c", given["command"]], capture_output=True, text=True, env=self.env)
                made.append((tool, given, ran.stdout + ran.stderr, False))
            else:
                made.append((tool, given, "contents", False))
        write_record(self.home / "records", name, kind, prompt, made)
        return made

    def pass_the_gate(self):
        self.assertEqual(self.stage3("setup").returncode, 0)
        card = self.stage3("prep").stdout
        self.assertIn("the security gate: start 3 agents, all in ONE message", card)
        self.assertIn("subagent_type: swarm-probe-wide", card)
        self.agent("swarm-probe", "cat /etc/hostname", [("Bash", {"command": "cat /etc/hostname"})])
        self.agent("swarm-probe", "swk status", [("Bash", {"command": "swk status"})])
        self.agent("swarm-probe-wide", "READ /etc/hostname", [("Read", {"file_path": "/etc/hostname"})])
        return self.stage3("finish")

    def work_the_queue(self, extra=None, through_the_gate=True, check_status=False):
        card = self.stage3("prep").stdout
        self.assertIn("prompt of every agent: the single word go", card)
        self.assertIn("Never put more than 20 Agent calls in one message", card)
        for done in range(4):
            if check_status and done in (0, 3):
                said = self.stage3("status").stdout
                self.assertIn(f"STAGE q4 is open: {done} of 4 agents started, {4 - done} left = 1 more message(s) of at most 20 Agent calls. Start {4 - done} now.", said)
                self.assertIn(f"queue: {4 - done} waiting, 0 claimed, {done} handed in, 0 given up, of 4", said)
            first = subprocess.run(["swk", "next"], capture_output=True, text=True, env=self.env).stdout
            worker, ident = first.splitlines()[0].split()[1], first.split("## Task ")[1].split()[0]
            reference = tasks.medium(int(ident.split("-")[1]), SMALL_PLAN["seed"])["reference"]
            ticket = re.search(r"^ticket (\S+)$", first, re.M)  # a queue that gives tickets wants the ticket in the hand-in
            wants = [("Bash", {"command": f"swk submit {ident}{' ' + ticket.group(1) if ticket else ''} <<'PY'\n{reference}\nPY"}), *(extra or [])]
            # the stand-in's first call was made above, outside the gate: tell the gate of it, as the host would have
            subprocess.run(["swk-hook"], input=json.dumps({"agent_type": "swarm-queue-1", "agent_id": f"s{self.count + 1}", "tool_name": "Bash", "tool_input": {"command": "swk next"}}),
                           capture_output=True, text=True, env=self.env)
            made = self.agent("swarm-queue-1", "go", wants, through_the_gate)
            path = self.home / "records" / f"agent-s{self.count}.jsonl"
            write_record(self.home / "records", f"s{self.count}", "swarm-queue-1", "go", [("Bash", {"command": "swk next"}, first, False), *made])
            self.assertTrue(path.exists() and worker)
        if check_status:
            self.assertIn("STAGE q4 is open: 4 of 4 agents started, 0 left. Start no more. Run: python3 swarm/phase3/stage3.py finish", self.stage3("status").stdout)
        return self.stage3("finish")

    def test_the_gate_stage_passes_and_then_the_queue_stage_runs_clean(self):
        gate = self.pass_the_gate()
        self.assertEqual(gate.returncode, 0, gate.stderr)
        self.assertIn("security gate: PASSED", gate.stdout)
        self.assertTrue(gate.stdout.rstrip().splitlines()[-1].startswith("NEXT q4"))
        self.assertIn("No stage is open", self.stage3("status").stdout)
        done = self.work_the_queue(check_status=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("gate saw every call: True", done.stdout)
        self.assertTrue(done.stdout.rstrip().splitlines()[-1].startswith("END - every stage"), done.stdout)
        text = (self.home / "public" / "evidence" / "stages.json").read_text()
        document = json.loads(text)
        gate_stage, work = document["stages"]
        self.assertTrue(document["about"].startswith("Third phase"))
        self.assertEqual(document["plan_sha256"], __import__("hashlib").sha256((self.home / "plan.json").read_bytes()).hexdigest())
        self.assertEqual(document["counted_before_this_run"]["total"], sum(document["counted_before_this_run"]["parts"].values()))
        self.assertGreater(document["counted_before_this_run"]["reported_apart"]["orchestrator_of_the_second_phase_run"], 0)
        self.assertTrue(gate_stage["guard_enforced"] and work["guard_enforced"])
        self.assertTrue(gate_stage["security_gate"]["passed"])
        self.assertEqual([(p["must_be"], p["held"], p["calls_outside_the_contract_that_ran"]) for p in gate_stage["security_gate"]["probes"]],
                         [("refused", True, 0), ("let through", True, 0), ("refused", True, 0)])
        self.assertEqual((work["verified_tasks"], work["tasks"], work["actual_agents"]), (4, 4, 4))
        self.assertTrue(work["ledger"]["clean"] and work["ledger"]["gate"]["reconciled"])
        self.assertEqual(work["ledger"]["by_class"], {"worker command": 8})
        self.assertEqual((work["queue"]["handed_in"], work["queue"]["left_waiting"], work["queue"]["most_tasks_one_worker_took"]), (4, 0, 1))
        self.assertGreater(work["counted_before_this_run"]["total"], 36168638)
        for private in (str(self.home), "/tmp/", "claude-haiku-4-5", "cat /etc/hostname"):
            self.assertNotIn(private, text)

    def test_one_forbidden_thing_that_runs_ends_everything(self):
        self.assertEqual(self.stage3("setup").returncode, 0)
        self.stage3("prep")
        self.agent("swarm-probe", "cat /etc/hostname", [("Bash", {"command": "cat /etc/hostname"})], through_the_gate=False)
        self.agent("swarm-probe", "swk status", [("Bash", {"command": "swk status"})])
        self.agent("swarm-probe-wide", "READ /etc/hostname", [("Read", {"file_path": "/etc/hostname"})])
        gate = self.stage3("finish")
        self.assertIn("security gate: DID NOT HOLD", gate.stdout)
        last = gate.stdout.rstrip().splitlines()[-1]
        self.assertTrue(last.startswith("END - "), last)
        self.assertIn("the security gate did not hold", last)
        self.assertIn("read a file with a command of its own was not refused", last)
        again = self.stage3("prep")
        self.assertEqual(again.returncode, 1)
        self.assertTrue(again.stdout.startswith("END - "), again.stdout)

    def test_a_probe_that_was_never_started_does_not_count_as_refused(self):
        self.assertEqual(self.stage3("setup").returncode, 0)
        self.stage3("prep")
        self.agent("swarm-probe", "cat /etc/hostname", [("Bash", {"command": "cat /etc/hostname"})])
        self.agent("swarm-probe", "swk status", [("Bash", {"command": "swk status"})])
        gate = self.stage3("finish")
        self.assertIn("DID NOT HOLD", gate.stdout)
        self.assertIn("not started or not found", gate.stdout)

    def test_a_workers_foreign_call_that_ran_ends_the_run(self):
        self.assertIn("PASSED", self.pass_the_gate().stdout)
        done = self.work_the_queue(extra=[("Bash", {"command": "echo outside"})], through_the_gate=False)
        last = done.stdout.rstrip().splitlines()[-1]
        self.assertTrue(last.startswith("END - "), done.stdout)
        self.assertIn("calls outside a worker's contract ran in q4", last)
        work = json.loads((self.home / "public" / "evidence" / "stages.json").read_text())["stages"][1]
        self.assertFalse(work["guard_enforced"], "a stage where a foreign call ran is not a stage where the gate held")

    def test_an_agent_of_another_type_is_not_a_worker_of_the_stage_and_its_tokens_still_count(self):
        self.assertIn("PASSED", self.pass_the_gate().stdout)
        self.stage3("prep")
        write_record(self.home / "records", "stray", "general-purpose", "go", [("Read", {"file_path": "README.md"}, "text", False)])
        write_record(self.home / "records", "silent", "swarm-queue-1", "go", [])  # started, and stopped before it did anything
        done = self.stage3("finish")
        work = json.loads((self.home / "public" / "evidence" / "stages.json").read_text())["stages"][1]
        self.assertEqual(work["other_agents_during_the_stage"]["agents"], 1)
        self.assertEqual(work["other_agents_during_the_stage"]["input_tokens"], 2 * 5510)
        self.assertEqual(work["ledger"]["by_tool"], {}, "the other agent's call is not in the stage's ledger")
        self.assertEqual(work["ledger"]["agents_of_other_types_started_during_the_stage"], 1)
        document = json.loads((self.home / "public" / "evidence" / "stages.json").read_text())
        counted = document["counted_before_this_run"]["total"] + sum(s["agent_tokens"]["input_total"] for s in document["stages"]) + 2 * 5510
        self.assertEqual(document["figures"]["input_tokens_counted"], counted)
        self.assertIn("left no record with a reply", done.stdout + done.stderr + json.dumps(document))

    def test_a_worker_given_a_task_by_id_that_acts_on_anothers_task_ends_the_run(self):
        plan = json.loads(json.dumps(SMALL_PLAN))
        plan["stages"][1] = {"id": "t2", "kind": "task", "size": "small", "agents": 2, "tasks": 2, "first": 1, "agent_type": "swarm-light", "model": "haiku", "effort": "low", "delivery": "id"}
        (self.home / "plan.json").write_text(json.dumps(plan))
        self.assertIn("PASSED", self.pass_the_gate().stdout)
        self.stage3("prep")
        self.agent("swarm-light", "S-0001", [("Bash", {"command": "swk show S-0001"}), ("Bash", {"command": "swk show S-0002"})])
        self.agent("swarm-light", "S-0002", [("Bash", {"command": "swk show S-0002"})])
        last = self.stage3("finish").stdout.rstrip().splitlines()[-1]
        self.assertTrue(last.startswith("END - "), last)
        self.assertIn("worker command on another worker's task", last)

    def test_the_projection_carries_a_margin_and_zero_is_not_a_projection(self):
        sys.path.insert(0, str(P3))
        import stage
        import stage3
        plan = json.loads(json.dumps(SMALL_PLAN))
        spec = plan["stages"][1]
        gate = {"label": "g0", "kind": "probe", "agent_tokens": {"input_total": 0, "output": 0}, "actual_agents": 3, "security_gate": {"passed": True, "why": []}}
        alike = {"label": "q0", "kind": "task", "size": "medium", "agent_type": "swarm-queue-1", "model": "haiku", "actual_agents": 4, "registered_agents": 4, "verified_success_rate": 100.0,
                 "security_findings": 0, "wall_seconds": 5, "peak_concurrent_agents": 4, "agent_tokens": {"input_total": 4000, "output": 1}, "tasks": 4, "verified_tasks": 4}
        old = stage.PLAN
        try:
            for spent_left, per_agent, skipped in ((4000, 1000, True), (4999, 1000, True), (5000, 1000, False), (6_249_999, 0, True), (6_250_000, 0, False)):
                plan["caps"]["spent_before_phase2"] = plan["caps"]["cumulative_input_tokens"] - spent_left - 4 * per_agent
                stage.PLAN = plan
                row = {**alike, "agent_tokens": {"input_total": 4 * per_agent, "output": 1}}
                end, skip, _, figures = stage3.decide([gate, row], spec)
                self.assertEqual((bool(skip), end), (skipped, []), (spent_left, per_agent, skip))
            plan["caps"]["spent_before_phase2"] = plan["caps"]["cumulative_input_tokens"] + 1
            self.assertIn("the limit is passed", " ".join(stage3.decide([gate], None)[0]))
        finally:
            stage.PLAN = old

    def test_no_stage_is_opened_when_the_installed_gate_is_gone(self):
        self.assertEqual(self.stage3("setup").returncode, 0)
        (self.home / "bin" / "swk-hook").unlink()
        refused = self.stage3("prep")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("END - the session gate does not pass its self-test", refused.stdout)
        self.assertFalse((self.home / "swarm" / "p3" / "open").exists())


if __name__ == "__main__":
    unittest.main()
