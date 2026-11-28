"""Tests of kit3, the queue worker's command: scripted workers, no agent, no model."""
import io
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "swarm" / "phase3"), str(ROOT / "swarm" / "phase2"), str(ROOT / "swarm")]
import guard  # noqa: E402
import kit3  # noqa: E402
import taskqueue  # noqa: E402
import tasks  # noqa: E402


def swk(*argv, stdin=""):
    out = io.StringIO()
    with redirect_stdout(out), mock.patch("sys.stdin", io.StringIO(stdin)):
        code = kit3.main(list(argv))
    return code, out.getvalue()


class Kit3Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"SWARM_HOME": self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)
        home = Path(self.tmp.name) / "p3"
        self.stage = home / "work" / "s1"
        self.stage.mkdir(parents=True)
        (home / "current").write_text("s1")
        self.items = tasks.make(self.stage, "medium", 1, 6)
        self.ids = [t["id"] for t in self.items]
        taskqueue.create(self.stage, self.ids, 3)

    def hand_in(self, ident, source):
        return swk("submit", ident, stdin=source)[1]

    def test_two_workers_drain_without_sharing(self):
        reference = {t["id"]: t["reference"] for t in self.items}
        seen = []
        for worker in ("wa", "wb"):
            for _ in range(3):
                _, text = swk("next", worker)
                self.assertTrue(text.startswith(f"worker {worker}\n"))
                ident = re.search(r"[SMLX]-\d{4}", self.stage_task_for(worker)).group(0)
                seen.append(ident)
                reply = self.hand_in(ident, reference[ident])
                self.assertIn(f"Then run: swk next {worker}", reply)
            self.assertIn("No more tasks", swk("next", worker)[1])
        self.assertEqual(sorted(seen), sorted(self.ids))
        self.assertEqual(taskqueue.status(self.stage)["handed_in"], 6)

    def stage_task_for(self, worker):
        return (self.stage / ".queue" / "workers" / worker).read_text().split()[-1]

    def test_unnamed_worker_gets_a_name(self):
        _, text = swk("next")
        self.assertRegex(text.splitlines()[0], r"worker w[0-9a-f]{6}")

    def test_failing_hand_in_keeps_task_until_attempts_run_out(self):
        swk("next", "wa")
        ident = self.stage_task_for("wa")
        for n in (1, 2):
            reply = self.hand_in(ident, "def nothing():\n    return None\n")
            self.assertNotIn("Then run", reply)
            self.assertEqual(taskqueue.holder(self.stage, ident), "wa")
        reply = self.hand_in(ident, "def nothing():\n    return None\n")
        self.assertIn("Then run: swk next wa", reply)
        self.assertIsNone(taskqueue.holder(self.stage, ident))
        self.assertEqual(taskqueue.status(self.stage)["failed"], 1)

    def test_other_verbs_pass_through(self):
        code, text = swk("status")
        self.assertEqual(code, 0)
        self.assertIn("stage s1", text)

    def test_definition_commands_pass_the_guard(self):
        text = (ROOT / ".claude" / "agents" / "swarm-queue.md").read_text()
        self.assertIn("maxTurns: 40", text)
        commands = re.findall(r"`(swk [^`]+)`", text)
        self.assertTrue(commands)
        for command in commands:
            command = command.replace("NAME", "wabc123").replace(" ID", " M-0001")
            self.assertTrue(guard.allowed(command), command)
        block = "swk submit M-0001 <<'PY'\nprint(1)\nPY"
        self.assertTrue(guard.allowed(block))
        self.assertIn("swk submit ID <<'PY'", text)


if __name__ == "__main__":
    unittest.main()
