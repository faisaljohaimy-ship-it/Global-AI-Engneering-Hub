"""Tests of the hand-in tickets of kit3: a worker can hand in only the task it drew."""
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "swarm" / "phase3"), str(ROOT / "swarm" / "phase2"), str(ROOT / "swarm")]
import guard  # noqa: E402
import taskqueue  # noqa: E402
import tasks  # noqa: E402

KIT = str(ROOT / "swarm" / "phase3" / "kit3.py")


class TicketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.stage = self.home / "p3" / "work" / "s1"
        self.stage.mkdir(parents=True)
        (self.home / "p3" / "current").write_text("s1")

    def swk(self, *argv, stdin=""):
        env = {"SWARM_HOME": str(self.home), "PATH": os.environ.get("PATH", "")}
        done = subprocess.run([sys.executable, "-I", KIT, *argv], input=stdin, capture_output=True, text=True, env=env, timeout=60)
        return done.returncode, done.stdout

    def queue(self, count=4, batch=3):
        items = tasks.make(self.stage, "medium", 1, count)
        taskqueue.create(self.stage, [t["id"] for t in items], batch)
        return {t["id"]: t["reference"] for t in items}

    def draw(self, *argv):
        code, text = self.swk("next", *argv)
        self.assertEqual(code, 0, text)
        lines = text.splitlines()
        worker = re.fullmatch(r"worker (\S+)", lines[0]).group(1)
        ticket = re.fullmatch(r"ticket ([0-9a-f]{8})", lines[1]).group(1)
        ident = re.search(r"[SMLX]-\d{4}", text).group(0)
        return worker, ticket, ident, text

    def snapshot(self, ident):
        folder = self.stage / ident
        return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts}, (self.stage / ".kit" / f"{ident}.json").read_bytes()

    def test_right_ticket_hands_in_and_reply_names_next_line(self):
        refs = self.queue()
        worker, ticket, ident, text = self.draw("wa")
        self.assertIn(f"swk submit {ident} {ticket} <<'PY'", text)
        self.assertTrue(guard.allowed(f"swk submit {ident} {ticket} <<'PY'\nprint(1)\nPY"))
        code, reply = self.swk("submit", ident, ticket, stdin=refs[ident])
        self.assertEqual(code, 0)
        self.assertIn(f"Then run: swk next wa {ticket}", reply)
        self.assertTrue(guard.allowed(f"swk next wa {ticket}"))
        self.assertEqual(taskqueue.status(self.stage)["handed_in"], 1)

    def test_bad_tickets_are_refused_and_leave_no_trace(self):
        refs = self.queue()
        _, ticket, ident, _ = self.draw("wa")
        _, other, other_id, _ = self.draw("wb")
        before = self.snapshot(ident)
        for argv in ((ident,), (ident, "00000000"), (ident, other), (ident, "not-a-ticket"), (ident, ticket, "x")):
            code, text = self.swk("submit", *argv, stdin=refs[ident])
            self.assertEqual(code, 2, argv)
            self.assertIn("refused", text)
            self.assertEqual(self.snapshot(ident), before)
        lines = (self.stage / ".queue" / "refused").read_text().splitlines()
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(line.split()[1] == ident for line in lines))
        self.assertNotIn(ticket, "".join(lines))
        self.assertNotIn(other, "".join(lines))
        self.assertEqual(taskqueue.holder(self.stage, ident), "wa")
        self.assertEqual(self.swk("submit", ident, ticket, stdin=refs[ident])[0], 0)
        self.assertNotEqual(other_id, ident)

    def test_used_ticket_cannot_be_replayed(self):
        refs = self.queue()
        _, ticket, ident, _ = self.draw("wa")
        self.assertEqual(self.swk("submit", ident, ticket, stdin=refs[ident])[0], 0)
        before = self.snapshot(ident)
        code, _ = self.swk("submit", ident, ticket, stdin=refs[ident])
        self.assertEqual(code, 2)
        self.assertEqual(self.snapshot(ident), before)

    def test_next_needs_the_ticket_of_the_last_task(self):
        refs = self.queue()
        _, ticket, ident, _ = self.draw("wa")
        self.swk("submit", ident, ticket, stdin=refs[ident])
        self.assertEqual(self.swk("next", "wa")[0], 2)
        self.assertEqual(self.swk("next", "wa", "00000000")[0], 2)
        _, stolen, _, _ = self.draw("wb")
        self.assertEqual(self.swk("next", "wa", stolen)[0], 2)
        _, again, second, _ = self.draw("wa", ticket)
        self.assertNotEqual(second, ident)
        self.assertNotEqual(again, ticket)

    def test_ticket_file_holds_no_ticket_in_clear(self):
        self.queue()
        _, ticket, ident, _ = self.draw("wa")
        path = self.stage / ".queue" / "tickets" / ident
        self.assertEqual(path.stat().st_mode & 0o077, 0)
        self.assertNotIn(ticket, path.read_text())
        self.assertEqual(path.read_text().strip(), hashlib.sha256(ticket.encode()).hexdigest())
        for found in self.stage.rglob("*"):
            if found.is_file() and found.parent.name != "tickets":
                self.assertNotIn(ticket, found.read_text(errors="ignore"), str(found))

    def test_fifty_processes_get_fifty_tasks_and_tickets(self):
        self.queue(50, 1)
        with ThreadPoolExecutor(50) as pool:
            results = list(pool.map(lambda _: self.draw(), range(50)))
        self.assertEqual(len({r[2] for r in results}), 50)
        self.assertEqual(len({r[1] for r in results}), 50)
        self.assertEqual(len({r[0] for r in results}), 50)

    def test_stage_without_a_queue_is_unchanged(self):
        items = tasks.make(self.stage, "medium", 1, 1)
        ident = items[0]["id"]
        code, reply = self.swk("submit", ident, stdin=items[0]["reference"])
        self.assertEqual(code, 0)
        self.assertIn("examples passed", reply)
        self.assertNotIn("Then run", reply)
        self.assertFalse((self.stage / ".queue").exists())


if __name__ == "__main__":
    unittest.main()
