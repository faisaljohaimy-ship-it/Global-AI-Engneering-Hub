"""Tests of the ledger at its edges: stopped calls, odd records, missing meta, odd gate lines. No agent, no model, no network."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "swarm" / "phase3"), str(ROOT / "swarm" / "phase2"), str(ROOT / "swarm")]
import guard  # noqa: E402
import ledger  # noqa: E402


def record(folder, name, kind, steps, meta=True, tail="", results=True):
    """steps: list of replies, each a list of (id, tool, input, result text or list or None, is_error)."""
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "go"}})]
    for number, reply in enumerate(steps):
        lines.append(json.dumps({"type": "assistant", "message": {"id": f"m{number}", "content": [
            {"type": "tool_use", "id": i, "name": t, "input": g} for i, t, g, _, _ in reply]}}))
        done = [{"type": "tool_result", "tool_use_id": i, "content": r, "is_error": e} for i, _, _, r, e in reply if r is not None]
        if done:
            lines.append(json.dumps({"type": "user", "message": {"role": "user", "content": done}}))
    path = Path(folder) / f"agent-{name}.jsonl"
    path.write_text("\n".join(lines) + tail)
    if meta:
        path.with_name(f"agent-{name}.meta.json").write_text(json.dumps({"agentType": kind}))
    return path


WORKER = ("swk show S-0001")
SUMS = ("by_class", "by_tool")


class EdgeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dir = self.folder.name

    def build(self, paths, gate=None):
        book = ledger.build(paths, gate)
        for key in SUMS:  # every figure adds up, on every document
            self.assertEqual(sum(book[key].values()), book["tool_calls"], key)
        self.assertLessEqual(sum(book["calls_a_gate_must_have_seen_by_agent_type"].values()), book["tool_calls"])
        return book

    def test_stopped_worker_command_is_its_own_class_and_stays_clean(self):
        path = record(self.dir, "a", "swarm-light", [[("1", "Bash", {"command": WORKER}, None, False)]])
        book = self.build([path])
        self.assertEqual(book["by_class"], {"no result recorded": 1})
        self.assertTrue(book["clean"])
        self.assertEqual(book["calls_a_gate_must_have_seen_by_agent_type"], {"swarm-light": 1})

    def test_stopped_hand_back_is_clean(self):
        path = record(self.dir, "a", "swarm-light", [[("1", "SubagentHandback", {"report": "x"}, None, False)]])
        book = self.build([path])
        self.assertEqual(book["by_class"], {"no result recorded": 1})
        self.assertTrue(book["clean"])

    def test_stopped_other_call_may_have_run_so_the_ledger_is_not_clean(self):
        for tool, given in (("Read", {"file_path": "x"}), ("Bash", {"command": "cat /etc/hostname"}), ("mcp__claude-code-remote__send_message", {})):
            path = record(self.dir, "b", "swarm-light", [[("1", tool, given, None, False)]])
            book = self.build([path])
            self.assertFalse(book["clean"], tool)
            self.assertEqual(book["calls_outside_the_contract_that_ran"], {f"no result recorded: {tool}": 1})

    def test_a_result_with_no_call_is_reported_and_not_a_call(self):
        path = record(self.dir, "a", "swarm-light", [[("1", "Bash", {"command": WORKER}, "ok", False)]])
        with path.open("a") as f:
            f.write("\n" + json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "zz", "content": "x"}]}}))
        book = self.build([path])
        self.assertEqual(book["tool_calls"], 1)
        self.assertEqual(book["results_without_a_call"], 1)

    def test_the_same_call_id_twice_counts_once(self):
        path = record(self.dir, "a", "swarm-light", [[("1", "Bash", {"command": WORKER}, "ok", False)], [("1", "Bash", {"command": WORKER}, None, False)]])
        book = self.build([path])
        self.assertEqual(book["tool_calls"], 1)
        self.assertEqual(book["repeated_call_ids"], 1)

    def test_several_calls_in_one_reply_some_refused(self):
        path = record(self.dir, "a", "swarm-light", [[
            ("1", "Bash", {"command": WORKER}, "task", False), ("2", "Bash", {"command": "cat /x"}, f"{guard.MARK}: refused.", True),
            ("3", "Read", {"file_path": "x"}, "text", False), ("4", "Write", {}, "Permission to use Write has been denied.", True)]])
        book = self.build([path])
        self.assertEqual(book["by_class"], {"other tool": 1, "refused by the gate": 1, "refused by the host": 1, "worker command": 1})
        self.assertEqual(book["calls_outside_the_contract_that_ran"], {"other tool: Read": 1})

    def test_a_cut_off_or_non_json_line_is_skipped_and_counted(self):
        path = record(self.dir, "a", "swarm-light", [[("1", "Bash", {"command": WORKER}, "ok", False)]], tail='\nnot json\n[1,2]\n{"type": "assistant", "mess')
        book = self.build([path])
        self.assertEqual(book["tool_calls"], 1)
        self.assertEqual(book["unreadable_lines"], 3)

    def test_no_meta_means_unknown_type_not_a_known_worker(self):
        path = record(self.dir, "a", "swarm-light", [[("1", "Bash", {"command": WORKER}, "ok", False)]], meta=False)
        self.assertIsNone(ledger.agent_type(path))
        book = self.build([path], [{"agent": "swarm-light", "tool": "Bash", "verdict": "allow"}])
        self.assertEqual(book["agents_with_type_not_recorded"], 1)
        self.assertEqual(book["calls_a_gate_must_have_seen_by_agent_type"], {"type not recorded": 1})
        self.assertNotIn("swarm-light", book["calls_a_gate_must_have_seen_by_agent_type"])
        self.assertFalse(book["gate"]["reconciled"])

    def test_a_meta_without_a_type_is_unknown(self):
        path = record(self.dir, "a", "x", [], meta=False)
        path.with_name("agent-a.meta.json").write_text(json.dumps({"agentType": 5}))
        self.assertIsNone(ledger.agent_type(path))

    def test_an_empty_record(self):
        path = Path(self.dir) / "agent-e.jsonl"
        path.write_text("")
        book = self.build([path])
        self.assertEqual((book["tool_calls"], book["empty_records"], book["agents"], book["clean"]), (0, 1, 1, True))
        self.assertEqual(self.build([])["tool_calls"], 0)

    def test_result_content_as_a_list_of_blocks(self):
        path = record(self.dir, "a", "swarm-light", [[
            ("1", "Bash", {"command": "cat /x"}, [{"type": "text", "text": f"{guard.MARK}: refused."}], True),
            ("2", "Bash", {"command": WORKER}, [{"type": "text", "text": "fine"}, "bare", {"type": "image"}], False)]])
        self.assertEqual(self.build([path])["by_class"], {"refused by the gate": 1, "worker command": 1})

    def test_a_refusal_text_in_ordinary_output_is_not_a_refusal(self):
        path = record(self.dir, "a", "swarm-light", [[
            ("1", "Bash", {"command": WORKER}, f"the file says {guard.MARK}: refused. and swk-lane-guard", False),
            ("2", "Read", {"file_path": "x"}, f"{guard.MARK} in a file", False)]])
        book = self.build([path])
        self.assertEqual(book["by_class"], {"other tool": 1, "worker command": 1})
        self.assertEqual(book["gate"] if "gate" in book else {}, {})

    def test_gate_lines_without_time_outside_the_stage_or_not_json(self):
        log = Path(self.dir) / "hook.jsonl"
        log.write_text("\n".join([json.dumps({"t": 5, "agent": "a", "tool": "Bash"}), json.dumps({"agent": "a", "tool": "Bash"}),
                                  json.dumps({"t": 99, "agent": "a", "tool": "Bash"}), json.dumps({"t": "x", "agent": "a"}), "{cut", "[1]", ""]))
        report = ledger.gate_report(log, 0, 10)
        self.assertEqual(len(report["lines"]), 1)
        self.assertEqual((report["not_json"], report["no_time"], report["outside_the_stage"]), (2, 2, 1))
        self.assertEqual(len(ledger.gate_log(log, 0, 10)), 1)
        self.assertEqual(len(ledger.gate_log(log)), 4)  # no window: nothing is outside, lines with no time stay
        self.assertEqual(ledger.gate_log(Path(self.dir) / "missing"), [])

    def test_odd_gate_lines_do_not_break_the_comparison(self):
        path = record(self.dir, "a", "swarm-light", [[("1", "Bash", {"command": WORKER}, "ok", False)]])
        book = self.build([path], ["junk", None, {"agent": ["x"], "tool": "Bash"}, {"agent": "swarm-light", "tool": "Bash", "verdict": "allow"}])
        self.assertTrue(book["gate"]["reconciled"])
        self.assertEqual(book["gate"]["gate_lines_unusable"], 2)

    def test_figures_add_up_on_a_mixed_document(self):
        paths = [record(self.dir, "a", "swarm-light", [[("1", "Bash", {"command": WORKER}, "ok", False), ("2", "Read", {}, None, False)], [("3", "SubagentHandback", {}, "ok", False)]]),
                 record(self.dir, "b", "x", [[("1", "Bash", {"command": WORKER}, None, False)]], meta=False)]
        book = self.build(paths)
        self.assertEqual(book["tool_calls"], 4)


if __name__ == "__main__":
    unittest.main()
