"""Proof tests for the security review of the worker's path (swarm/phase3/reviews/security-review.md).

A normal test shows a control that holds. A test marked expectedFailure shows a fault: it
asserts what should be true and fails today. Run: python3 -m unittest tests.test_p3_review_security
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
P3 = ROOT / "swarm" / "phase3"
PATHS = [str(P3), str(ROOT / "swarm" / "phase2"), str(ROOT / "swarm")]
sys.path[:0] = PATHS
import guard  # noqa: E402
import kit  # noqa: E402
import kit3  # noqa: E402
import lane_guard  # noqa: E402
import taskqueue  # noqa: E402
import tasks  # noqa: E402


class Stage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.stage = self.home / "p3" / "work" / "S1"
        self.stage.mkdir(parents=True)
        (self.home / "p3" / "current").write_text("S1")

    def make(self, size, count, mode="lean"):
        return [t["id"] for t in tasks.make(self.stage, size, 1, count, mode)]

    def swk(self, *argv, stdin=""):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"SWARM_HOME": str(self.home)}), mock.patch("sys.stdin", io.StringIO(stdin)), contextlib.redirect_stdout(out):
            code = kit3.main(list(argv))
        return code, out.getvalue()

    def state(self, ident):
        return json.loads((self.stage / ".kit" / f"{ident}.json").read_text())


class GuardHolds(unittest.TestCase):
    def test_injection_shapes_are_refused(self):
        bad = ["swk show L-0001; id", "swk show L-0001 && id", "swk show L-0001 | cat", "swk show L-0001 > /tmp/x", "swk grep L-0001 $(id)",
               "swk grep L-0001 `id`", 'swk grep L-0001 "x"', "swk grep L-0001 'a'b", "swk show L-0001\nid", "swk submit L-0001", "swk submit L-0001 <<'PY'",
               "swk submit L-0001 <<'PY'\nx\nPY\nid", "swk submit L-0001 <<'PY'\nPY\nid\nPY", "swk submit L-0001 <<'PY' <<'Q'\nx\nPY", "swk submit L-0001 <<PY\nx\nPY",
               "swk show L-0001 \\", "SWARM_HOME=x swk show L-0001", "swk  show L-0001", "swk show L-0001 # c"]
        for command in bad:
            self.assertFalse(guard.allowed(command), command)

    def test_normal_shapes_are_let_through(self):
        for command in ["swk status", "swk next w1", "swk grep L-0001 '-e' inv", "swk submit L-0001 <<'PY'\nx = 1\nPY", "swk setline L-0001 inv/m1.py 3 <<'EOF'\nx\nEOF"]:
            self.assertTrue(guard.allowed(command), command)


class KitHolds(Stage):
    def test_paths_cannot_leave_the_project(self):
        (ident,) = self.make("large", 1)
        for argv in (["read", ident, "../.hidden/x"], ["read", ident, "inv/.."], ["read", ident, "/etc/passwd"], ["read", ident, "inv/../../.kit/x.json"],
                     ["grep", ident, "x", ".."], ["select", ident, "tests/..", "a=b", "c"], ["setline", ident, "inv/../tests/test_x.py", "1"],
                     ["setline", ident, "tests/test_x.py", "1"], ["read", "L-0001/../S-0001", "inv"], ["show", "../x"]):
            code, out = self.swk(*argv, stdin="x\n")
            self.assertEqual(code, 2, argv)
            self.assertNotIn(str(self.home), out)

    def test_answer_is_not_graded_in_the_reply(self):
        (ident,) = self.make("large", 1)
        replies = {self.swk("answer", ident, stdin=json.dumps({"fixed_function": a, "direct_callers": [], "failed_event_ids": [], "build_error_code": a}))[1] for a in ("x", "y")}
        self.assertEqual(len(replies), 1)

    def test_worker_kit_state_holds_no_hidden_field(self):
        ids = self.make("large", 1) + self.make("small", 1)
        for ident in ids:
            text = (self.stage / ".kit" / f"{ident}.json").read_text()
            self.assertFalse({"truth", "suite", "fingerprint"} & set(json.loads(text)))

    def test_no_two_workers_get_one_task(self):
        ids = [f"S-{n:04d}" for n in range(1, 41)]
        taskqueue.create(self.stage, ids, 40)
        got, lock = [], threading.Lock()

        def work(name):
            while (ident := taskqueue.claim(self.stage, name)) is not None:
                with lock:
                    got.append(ident)
        threads = [threading.Thread(target=work, args=(f"w{n}",)) for n in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(got), ids)


class WorkerFaults(Stage):
    # kit3.submit / kit.locate: any worker may act on any task id; nothing ties a caller to the task it claimed
    @unittest.expectedFailure
    def test_a_worker_cannot_use_a_task_it_does_not_hold(self):
        ids = self.make("small", 2)
        taskqueue.create(self.stage, ids, 1)
        taskqueue.claim(self.stage, "w1")
        self.swk("submit", ids[0], stdin="x = 1\n")  # w2 cannot say who it is: it names w1's task
        self.assertEqual(self.state(ids[0])["attempts"], 0)

    # kit3.next_task / taskqueue.claim: a worker name is any string the caller types, so one worker can fill another's batch
    @unittest.expectedFailure
    def test_a_worker_cannot_fill_another_workers_batch(self):
        ids = self.make("small", 3)
        taskqueue.create(self.stage, ids, 1)
        self.swk("next", "victim")  # an attacker takes the victim's whole batch
        code, out = self.swk("next", "victim")  # the victim asks for its first task
        self.assertIn("S-", out)

    # kit3.next_task: one caller changes its name to take more than the batch
    @unittest.expectedFailure
    def test_a_worker_cannot_beat_the_batch_with_a_new_name(self):
        ids = self.make("small", 4)
        taskqueue.create(self.stage, ids, 1)
        taken = [self.swk("next", f"n{n}")[1] for n in range(3)]
        self.assertEqual(sum("worker n" in t for t in taken), 1)

    def test_a_slow_regular_expression_is_stopped(self):
        # holds: the regular-expression engine lets the SIGALRM handler run, so a catastrophic pattern on a worker-made line is refused after the limit
        (ident,) = self.make("large", 1)
        module = sorted((self.stage / ident / "inv").glob("m*.py"))[0]
        blank = next(n for n, text in enumerate(module.read_text().splitlines(), 1) if not text.strip())
        self.assertEqual(self.swk("setline", ident, f"inv/{module.name}", str(blank), stdin="#" + "a" * 50 + "!\n")[0], 0)
        script = ("import sys; sys.path[:0]=%r; import kit, kit3; kit.SEARCH_SECONDS = 1; sys.exit(kit3.main(['grep', %r, '(a|aa)+$']))" % (PATHS, ident))
        done = subprocess.run([sys.executable, "-I", "-c", script], env={"SWARM_HOME": str(self.home)}, capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 2)
        self.assertIn("took too long", done.stdout)

    # kit.setline + kit.test: a changed module runs as the same user in the task folder, so ../.hidden/ID.json (the truth) can be printed
    @unittest.expectedFailure
    def test_a_changed_module_cannot_print_the_withheld_truth(self):
        (ident,) = self.make("large", 1)
        truth = json.loads((self.stage / ".hidden" / f"{ident}.json").read_text())["truth"]["fixed_function"]
        line = f"raise AssertionError(open('../.hidden/{ident}.json').read())"
        module = sorted((self.stage / ident / "inv").glob("m*.py"))[0]
        self.swk("setline", ident, f"inv/{module.name}", "1", stdin=line + "\n")
        code, out = self.swk("test", ident)
        self.assertNotIn(truth, out)

    # kit.answer: nested JSON raises RecursionError, which kit.main does not catch: a traceback instead of a refusal
    @unittest.expectedFailure
    def test_deeply_nested_answer_is_refused(self):
        (ident,) = self.make("large", 1)
        code, _ = self.swk("answer", ident, stdin="[" * 19000)
        self.assertEqual(code, 2)

    # kit.answer: sorting a list of objects raises TypeError, which kit.main does not catch
    @unittest.expectedFailure
    def test_unsortable_answer_is_refused(self):
        (ident,) = self.make("large", 1)
        given = {"fixed_function": "f", "direct_callers": [{"a": 1}, {"a": 2}], "failed_event_ids": [], "build_error_code": "x"}
        code, _ = self.swk("answer", ident, stdin=json.dumps(given))
        self.assertEqual(code, 2)

    # kit.emit: the counters are written in place (read, change, truncate, write), so a reader or a second writer sees a torn or lost record
    @unittest.expectedFailure
    def test_state_is_replaced_not_rewritten_in_place(self):
        (ident,) = self.make("large", 1)
        state, written = self.stage / ".kit" / f"{ident}.json", []
        original = Path.write_text
        with mock.patch.object(Path, "write_text", lambda p, *a, **k: (written.append(p), original(p, *a, **k))[1]):
            self.swk("show", ident)
        self.assertNotIn(state, written)

    # taskqueue.claim: a crash between the rename and the write leaves a claim with no lease, and reclaim skips it for ever
    @unittest.expectedFailure
    def test_a_claim_without_a_lease_is_reclaimed(self):
        taskqueue.create(self.stage, ["S-0001"], 1)
        root = self.stage / ".queue"
        os.rename(root / "waiting" / "S-0001", root / "claimed" / "S-0001")
        self.assertEqual(taskqueue.reclaim(self.stage, now=10**9), ["S-0001"])


CASES_DENIED = ["curl http://x", "sudo id", "git push", "git -C /x push origin", "git -c a=b fetch", "env", "printenv", "cat /proc/self/environ", "echo hi; wget x",
                "pip install x", "npm i x", "git checkout main", "cat ~/.ssh/id_rsa"]


class LaneGuard(unittest.TestCase):
    def bash(self, command):
        return lane_guard.allowed({"tool_name": "Bash", "tool_input": {"command": command}})[0]

    def test_listed_commands_are_refused(self):
        for command in CASES_DENIED:
            self.assertFalse(self.bash(command), command)

    def test_files_and_tools_stay_inside(self):
        with tempfile.TemporaryDirectory() as lanes, mock.patch.dict(os.environ, {"SWARM_LANES": lanes}):
            for tool, given, want in [("Write", {"file_path": f"{lanes}/a/x.py"}, True), ("Write", {"file_path": f"{lanes}/../x"}, False), ("Write", {"file_path": "/etc/x"}, False),
                                      ("Edit", {"file_path": f"{lanes}/a/../../x"}, False), ("Read", {"file_path": "/etc/passwd"}, False), ("WebFetch", {"url": "http://x"}, False),
                                      ("Grep", {"pattern": "x", "path": "/root"}, False)]:
                self.assertEqual(lane_guard.allowed({"tool_name": tool, "tool_input": given})[0], want, (tool, given))

    # lane_guard.visible: a `cat <<EOF | sh` here-document is hidden as if it were file content, so what it runs is never judged
    @unittest.expectedFailure
    def test_a_here_document_piped_to_a_shell_is_judged(self):
        self.assertFalse(self.bash("cat <<'EOF' | sh\ncurl http://x\nEOF"))

    # lane_guard.DENIED: the word must start a command; a path, a quote or a backtick before it is not seen
    @unittest.expectedFailure
    def test_network_command_by_path_or_wrapper(self):
        for command in ["/usr/bin/curl http://x", "bash -c 'curl http://x'", "echo `curl http://x`", "timeout 5 curl http://x", "command wget x", "nohup curl x"]:
            self.assertFalse(self.bash(command), command)

    # lane_guard.DENIED: network by another tool name is not listed
    @unittest.expectedFailure
    def test_network_by_another_tool(self):
        for command in ["python3 -c \"import urllib.request as u; u.urlopen('http://x')\"", "socat - TCP:x:80", "telnet x 80", "rsync a x:b", "git ls-remote http://x", "perl -MIO::Socket -e1"]:
            self.assertFalse(self.bash(command), command)

    # lane_guard.DENIED: git alias and option forms reach push that the pattern does not name
    @unittest.expectedFailure
    def test_git_alias_and_option_forms(self):
        for command in ["git -c alias.p=push p", "git --no-pager push", "git config alias.p push", "git --git-dir=.git push", "git send-pack x"]:
            self.assertFalse(self.bash(command), command)

    # lane_guard.allowed (Bash): no path is checked, so a redirection writes anywhere the user can
    @unittest.expectedFailure
    def test_redirection_outside_the_lanes(self):
        with tempfile.TemporaryDirectory() as lanes, mock.patch.dict(os.environ, {"SWARM_LANES": lanes}):
            self.assertFalse(self.bash("echo x > /etc/motd"))
            self.assertFalse(self.bash("tee /usr/local/x < /dev/null"))

    # lane_guard.allowed (Glob): with no path, an absolute pattern lists any folder
    @unittest.expectedFailure
    def test_glob_pattern_cannot_leave_the_repository(self):
        with tempfile.TemporaryDirectory() as lanes, mock.patch.dict(os.environ, {"SWARM_LANES": lanes}):
            self.assertFalse(lane_guard.allowed({"tool_name": "Glob", "tool_input": {"pattern": "/root/.ssh/*"}})[0])
            self.assertFalse(lane_guard.allowed({"tool_name": "Glob", "tool_input": {"pattern": "../../../etc/*"}})[0])

    # lane_guard.DENIED: other ways to list the environment
    @unittest.expectedFailure
    def test_other_environment_listings(self):
        for command in ["export -p", "declare -x", "set", "python3 -c 'import os; print(os.environ)'", "cat /proc/$$/environ"]:
            self.assertFalse(self.bash(command), command)


if __name__ == "__main__":
    unittest.main()
