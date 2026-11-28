"""Attacks on the session gate: odd callers, odd documents, odd bytes, odd record paths, many callers at once.
No agent and no model is started; the installed program is the real one, run as a subprocess."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[1]
P3 = ROOT / "swarm" / "phase3"
sys.path[:0] = [str(P3), str(ROOT / "swarm" / "phase2")]
import hook  # noqa: E402


def shell(kind, command, ident="a1"):
    return {"agent_type": kind, "agent_id": ident, "tool_name": "Bash", "tool_input": {"command": command}}


class Program:
    """The installed program as the wrapper writes it, in a temporary folder."""

    def __init__(self, folder):
        self.home = pathlib.Path(folder) / "home"
        self.path = pathlib.Path(folder) / "swk-hook"
        self.path.write_text(hook.wrapper(f"SWARM_HOME='{self.home}'"))
        self.path.chmod(0o755)

    def run(self, data):
        data = data if isinstance(data, bytes) else data.encode()
        return subprocess.run([str(self.path)], input=data, capture_output=True, timeout=20)

    def code(self, call):
        return self.run(json.dumps(call)).returncode

    @property
    def log(self):
        return self.home / "p3" / "hook.jsonl"


class OddCallers(unittest.TestCase):
    def test_a_caller_that_is_not_plainly_described_is_refused(self):
        base = {"tool_name": "Bash", "tool_input": {"command": "swk next"}}
        odd = [{"agent_type": ["swarm-light"]}, {"agent_type": 7}, {"agent_type": ""}, {"agent_type": "  "}, {"agent_type": None},
               {"agent_id": ["a"]}, {"agent_id": 5}, {"agent_id": ""}, {"agent_id": " "}, {"agent_type": "swarm-light"},  # no id
               {"agent_type": "swarm-light", "agent_id": ""}, {"agent_type": "swarm-light", "agent_id": None},
               {"agent_type": "swarm-light", "agentType": "general-purpose", "agent_id": "a"},
               {"agent_type": "general-purpose", "agentType": "swarm-light", "agent_id": "a"},
               {"agent_type": "swarm-light", "agent_id": "a", "agentId": "b"},
               {"agent_type": "swarm-light", "subagent_type": "swarm-light ", "agent_id": "a"}]
        for who in odd:
            self.assertEqual(hook.decide({**who, **base})[0], "refuse", who)
            self.assertEqual(hook.decide({**who, "tool_name": "SubagentHandback"})[0], "refuse", who)

    def test_the_type_must_be_a_whole_worker_type(self):
        for kind in ("swarm-lightning", "swarm-light;id", "swarm-light ", " swarm-light", "swarm-light\n", "Swarm-Light", "swarm-queuex", "swarm-light/../x",
                     "swarm-large-", "swarm-probe-é", "swarm-light-a-b-c-d", "swarm-developer", "swarm-dev ", "SWARM-DEV", "xswarm-dev"):
            self.assertEqual(hook.decide(shell(kind, "swk next"))[0], "refuse", repr(kind))
        for kind in ("swarm-light", "swarm-light-2", "swarm-queue-1", "swarm-probe-wide", "swarm-probe-open", "swarm-large"):
            self.assertEqual(hook.decide(shell(kind, "swk next"))[0], "allow", kind)

    def test_tool_names_and_inputs_of_the_wrong_shape(self):
        for tool in ("bash", "BASH", "Bash ", " Bash", "Bash\n", "Bash\0", "Bash;id", ["Bash"], 1, None, {"a": 1}, "subagenthandback", "SubagentHandback ", "SubagentHandback; rm -rf /",
                     "StructuredOutput x"):
            call = {"agent_type": "swarm-queue-1", "agent_id": "a", "tool_name": tool, "tool_input": {"command": "swk next"}}
            self.assertEqual(hook.decide(call)[0], "refuse", repr(tool))
        self.assertEqual(hook.decide({"agent_type": "swarm-queue-1", "agent_id": "a"})[0], "refuse")
        for given in (None, [], "swk next", 5, [{"command": "swk next"}], {"command": None}, {"command": 5}, {"command": ["swk", "next"]}, {"Command": "swk next"}, {"command ": "swk next"}):
            self.assertEqual(hook.decide({"agent_type": "swarm-queue-1", "agent_id": "a", "tool_name": "Bash", "tool_input": given})[0], "refuse", repr(given))

    def test_workers_have_no_other_tool(self):
        for kind in ("swarm-light", "swarm-queue-2", "swarm-large", "swarm-probe-wide"):
            for tool in ("Agent", "Task", "ToolSearch", "SendMessage", "mcp__x__y", "mcp__claude-code-remote__send_message", "mcp__", "NotebookEdit", "TodoWrite", "Skill"):
                self.assertEqual(hook.decide({"agent_type": kind, "agent_id": "a", "tool_name": tool, "tool_input": {}})[0], "refuse", (kind, tool))

    def test_a_huge_or_nul_command_is_refused_quickly(self):
        import time
        started = time.time()
        for command in ("swk next " + "a" * 1_000_000, "swk next\0", "swk answer 1 " + "9" * 200_000, "swk submit 1 <<'PY'\n" + "x = 1\n" * 40_000 + "PY"):
            self.assertEqual(hook.decide(shell("swarm-queue-1", command))[0], "refuse", len(command))
        self.assertLess(time.time() - started, 5)


class AsAProgram(unittest.TestCase):
    def test_what_cannot_be_read_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Program(folder)
            good = json.dumps(shell("swarm-queue-1", "swk next"))
            self.assertEqual(program.run(good).returncode, 0)
            twice = '{"agent_type": "swarm-queue-1", "agent_type": "x", "agent_id": "a", "tool_name": "Bash", "tool_input": {"command": "swk next"}}'
            twice_other_way = '{"agent_type": "x", "agent_type": "swarm-queue-1", "agent_id": "a", "tool_name": "Bash", "tool_input": {"command": "swk next"}}'
            nested = '{"agent_type": "swarm-queue-1", "agent_id": "a", "tool_name": "Bash", "tool_input": {"command": "id", "command": "swk next"}}'
            orchestrator_twice = '{"tool_name": "Bash", "tool_name": "Bash", "tool_input": {}}'
            for text in (twice, twice_other_way, nested, orchestrator_twice):
                self.assertEqual(program.run(text).returncode, 2, text)
            for data in (b"\xff\xfe{}", b'{"tool_name": "Bash\xff"}', b"\0", b"{\0}", good.encode() + b"\0", b"\xef\xbb\xbf" + good.encode(), b"[" * 100000, b'{"a":' * 50000,
                         b"NaN", b'{"agent_type": NaN}', b"null", b"true", b"1e999999", b""):
                self.assertEqual(program.run(data).returncode, 2, data[:30])

    def test_a_command_of_a_million_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Program(folder)
            self.assertEqual(program.code(shell("swarm-queue-1", "swk next " + "a" * 1_000_000)), 2)
            self.assertEqual(program.code(shell("swarm-dev", "ls " + "a" * 1_000_000)) in (0, 2), True)

    def test_the_record_holds_no_command_and_no_content(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Program(folder)
            marker = "rm-rf-marker-content"
            program.code({"agent_type": "swarm-probe", "agent_id": "ident-" + marker, "tool_name": f"SubagentHandback; {marker}", "tool_input": {"command": marker}})
            program.code({"agent_type": f"x {marker}", "agent_id": "a", "tool_name": "Bash", "tool_input": {}, f"field {marker}": 1})
            program.code({"agent_type": "swarm-probe", "agent_id": "a", "tool_name": "SubagentHandback", "tool_input": {"command": marker}, "t" * 5000: 1})
            program.code({"tool_name": "A" * 100_000, "tool_input": {}})
            text = program.log.read_text()
            self.assertNotIn(marker, text)
            self.assertLess(len(text), 3000)
            for line in text.splitlines():
                json.loads(line)
            self.assertEqual([json.loads(line)["verdict"] for line in text.splitlines()], ["refuse", "refuse", "allow", "pass"])

    def test_a_record_that_cannot_be_written_stops_an_agent_but_not_the_orchestrator(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Program(folder)
            (program.home / "p3").mkdir(parents=True)
            program.log.mkdir()  # the record is a folder
            self.assertEqual(program.code(shell("swarm-queue-1", "swk next")), 2)
            self.assertEqual(program.code(shell("swarm-queue-1", "id")), 2)
            program.log.rmdir()
            target = pathlib.Path(folder) / "elsewhere"
            target.write_text("keep\n")
            program.log.symlink_to(target)  # the record is a link: the gate must not write through it
            self.assertEqual(program.code(shell("swarm-queue-1", "swk next")), 2)
            self.assertEqual(target.read_text(), "keep\n")
            program.log.unlink()
            os.mkfifo(program.log)  # the record is a pipe nobody reads: the gate must not hang
            self.assertEqual(program.code(shell("swarm-queue-1", "swk next")), 2)
            self.assertEqual(target.read_text(), "keep\n")

    def test_two_hundred_processes_record_at_once(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Program(folder)
            calls = [shell("swarm-queue-1", "swk next" if n % 2 else "id", ident=f"agent-{n}") for n in range(200)]
            with ThreadPoolExecutor(40) as pool:
                codes = list(pool.map(program.code, calls))
            self.assertEqual(codes, [0 if n % 2 else 2 for n in range(200)])
            lines = program.log.read_text().splitlines()
            self.assertEqual(len(lines), 200)
            self.assertEqual(len({json.loads(line)["who"] for line in lines}), 200)


@unittest.expectedFailure
class NotDecidable(unittest.TestCase):
    def test_the_orchestrator_cannot_be_told_from_an_agent_the_host_did_not_describe(self):
        # hook.decide passes any call that carries neither field; a host that left them out for an agent would pass it
        self.assertEqual(hook.decide({"tool_name": "Bash", "tool_input": {"command": "git push"}})[0], "refuse")


if __name__ == "__main__":
    unittest.main()
