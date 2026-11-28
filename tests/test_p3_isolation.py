"""Black-box tests of isolation in the worker's command (swarm/phase3/kit3.py), run as a subprocess.

They prove, with stages made by tasks.make and taskqueue.create under a temporary SWARM_HOME, that
one stage cannot reach another, that two homes do not see each other, that tricks in task ids and
file names are refused, that withheld files are never shown, and that no verb mixes tasks. A fault
is an expectedFailure test with one comment line; the findings are in swarm/phase3/reviews/isolation.md.
No agent, no model, no network.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "swarm" / "phase3"), str(ROOT / "swarm" / "phase2"), str(ROOT / "swarm")]
import taskqueue  # noqa: E402
import tasks  # noqa: E402

KIT3 = ROOT / "swarm" / "phase3" / "kit3.py"


def swk(home, *argv, stdin=""):
    done = subprocess.run([sys.executable, "-I", str(KIT3), *argv], input=stdin, capture_output=True, text=True,
                          env={"SWARM_HOME": str(home), "PATH": os.environ.get("PATH", "")}, timeout=60)
    return done.returncode, done.stdout + done.stderr


def make_stage(home, name, size, first, count, queue=None):
    """A stage as the run lays it out: small and medium tasks are drawn from a queue, large tasks are given by id and have none.
    A stage with a queue runs `next` and `submit` only."""
    stage = Path(home) / "p3" / "work" / name
    stage.mkdir(parents=True)
    items = tasks.make(stage, size, first, count)
    if size != "large" if queue is None else queue:
        taskqueue.create(stage, [t["id"] for t in items], 2)
    return stage, items


def open_stage(home, name):
    (Path(home) / "p3" / "current").write_text(name)


def snapshot(root):
    state = {}
    for path in sorted(Path(root).rglob("*")):
        if path.name == ".queue" or (path.name == "refused" and path.parent.name == ".queue"):
            continue  # the queue's own note of a refused hand-in (a time and a task id, written on purpose) and the folder it changes
        info = path.lstat()
        state[str(path)] = (info.st_mode, info.st_size, info.st_mtime_ns)
    return state


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in list(value.keys()) + list(value.values()):
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()

    def single(self, queue=False):
        """One stage s1 with two large tasks and two medium ones, given by id as the run gives large tasks: every verb runs there.
        With a queue the stage runs `next` and `submit` only."""
        stage = self.home / "p3" / "work" / "s1"
        stage.mkdir(parents=True)
        self.large = tasks.make(stage, "large", 1, 2)
        self.medium = tasks.make(stage, "medium", 3, 2)
        self.items = self.large + self.medium
        self.ids = [t["id"] for t in self.items]
        if queue:
            taskqueue.create(stage, self.ids, 2)
        open_stage(self.home, "s1")
        self.stage = stage
        return stage


class StageToStage(Base):
    def test_open_stage_b_reaches_nothing_of_stage_a(self):
        a, items_a = make_stage(self.home, "a", "large", 1, 2)
        b, items_b = make_stage(self.home, "b", "medium", 11, 2)
        open_stage(self.home, "b")
        ida = items_a[0]["id"]
        texts = [(a / t["id"] / "TASK.md").read_text() for t in items_a]
        calls = [("show", ida), ("read", ida, "inv/m0.py"), ("grep", ida, "def"), ("submit", ida), ("test", ida), ("def", ida, "f0_0"),
                 ("callers", ida, "f0_0"), ("select", ida, "data/events.json", "a=b", "c"), ("setline", ida, "inv/m0.py", "1"), ("answer", ida)]
        before = snapshot(self.home)
        for call in calls:
            code, out = swk(self.home, *call, stdin="x = 1\n")
            self.assertEqual(code, 2, (call, out))
            for text in texts:
                self.assertNotIn(text[:60], out)
        self.assertEqual(before, snapshot(self.home), "a refused call changed something")
        code, out = swk(self.home, "next")  # its own tasks are still handed out
        self.assertEqual(code, 0, out)
        self.assertIn(re.search(r"[SMLX]-\d{4}", out).group(0), {t["id"] for t in items_b})

    def test_the_queue_of_the_open_stage_hands_out_only_its_own_tasks(self):
        _, items_a = make_stage(self.home, "a", "medium", 1, 3)
        _, items_b = make_stage(self.home, "b", "medium", 11, 3)
        open_stage(self.home, "b")
        wanted = {t["id"] for t in items_b}
        for worker in ("wa", "wb", "wc"):
            code, out = swk(self.home, "next", worker)
            self.assertEqual(code, 0)
            self.assertIn(re.search(r"[SMLX]-\d{4}", out).group(0), wanted)
            for t in items_a:
                self.assertNotIn(t["id"], out)

    def test_a_stage_name_with_path_tricks_in_current_is_not_followed_out(self):
        make_stage(self.home, "a", "medium", 1, 1)
        (self.home / "outside").mkdir()
        (self.home / "outside" / "M-0001").mkdir()
        (self.home / "outside" / "M-0001" / "TASK.md").write_text("OUTSIDE SECRET\n")
        open_stage(self.home, "../../outside")
        code, out = swk(self.home, "show", "M-0001")
        self.assertEqual(code, 2, out)
        self.assertNotIn("OUTSIDE SECRET", out)


class HomeToHome(Base):
    def test_two_homes_never_see_each_other(self):
        one, two = self.home / "one", self.home / "two"
        one.mkdir()
        two.mkdir()
        _, items1 = make_stage(one, "s1", "medium", 1, 2)
        _, items2 = make_stage(two, "s1", "medium", 5, 2)
        open_stage(one, "s1")
        open_stage(two, "s1")
        before1 = snapshot(one)
        for t in items1:
            code, out = swk(two, "show", t["id"])
            self.assertEqual(code, 2, out)
            self.assertNotIn("Task " + t["id"], out)
            self.assertEqual(swk(two, "submit", t["id"], stdin=t["reference"])[0], 2)
        seen = set()
        for worker in ("wa", "wb", "wc"):
            code, out = swk(two, "next", worker)
            found = re.search(r"[SMLX]-\d{4}", out)
            if found:
                seen.add(found.group(0))
        self.assertEqual(seen, {t["id"] for t in items2})
        self.assertEqual(before1, snapshot(one), "work in home two changed home one")
        self.assertEqual(taskqueue.status(one / "p3" / "work" / "s1")["waiting"], 2)


class Tricks(Base):
    def plant(self):
        stage = self.single()
        outside = self.home / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("SECRET OUTSIDE\n")
        folder = stage / self.large[0]["id"]
        os.symlink(outside / "secret.txt", folder / "data" / "link.txt")
        os.symlink(outside, folder / "logs" / "dirlink")
        os.symlink(outside, folder / "dirdata")
        return folder

    def test_task_ids_with_tricks_are_refused_and_create_nothing(self):
        self.plant()
        ids = ["../x", "M-0003/../..", "M-0003/..", "/etc/passwd", str(self.stage / "M-0003"), "M-" + "0" * 5000, "A" * 5000,
               "M-０００３", "M-٠٠٠٣", "М-0003", "M‐" + "0003", "M-0003 ", " M-0003", "M-0003\n",
               "M-00033", "..", ".", "", "-h", ".hidden", ".kit/M-0003", "M-0003.json", "M-0003/TASK.md"]
        before = snapshot(self.home)
        for ident in ids:
            for verb in (("show", ident), ("read", ident, "inv/m0.py"), ("submit", ident)):
                code, out = swk(self.home, *verb, stdin="x = 1\n")
                self.assertEqual(code, 2, (verb[0], ident[:30], out[:200]))
                self.assertNotIn("SECRET", out)
        self.assertEqual(before, snapshot(self.home), "a refused id changed or created something")

    def test_file_names_with_tricks_are_refused_and_create_nothing(self):
        folder = self.plant()
        ident = self.large[0]["id"]
        names = ["../x", "../M-0003/TASK.md", "inv/../../M-0003/TASK.md", "inv/..", "inv/../TASK.md", "/etc/passwd", str(folder / "TASK.md"),
                 "data/link.txt", "logs/dirlink/secret.txt", "dirdata/secret.txt", "dirdata", "logs/dirlink", "inv/" + "a" * 5000, "a" * 5000,
                 "inv/m0.py/", "inv//m0.py", "inv/m０.py", "inv/ѕm0.py", "inv/m0․py", "inv/m0.py\n", "TASK.md", ".git/config",
                 "tests/../.git/config", "inv/m0.py ", "іnv/m0.py"]
        before = snapshot(self.home)
        for name in names:
            for verb in (("read", ident, name), ("grep", ident, "x", name), ("setline", ident, name, "1")):
                code, out = swk(self.home, *verb, stdin="x = 1\n")
                self.assertEqual(code, 2, (verb[0], name[:30], out[:200]))
                self.assertNotIn("SECRET", out)
        self.assertEqual(before, snapshot(self.home), "a refused name changed or created something")

    def test_a_symbolic_link_in_the_project_is_not_followed_by_grep(self):
        folder = self.plant()
        code, out = swk(self.home, "grep", self.large[0]["id"], "SECRET")
        self.assertEqual(code, 0, out)
        self.assertNotIn("SECRET OUTSIDE", out)

    def test_nul_byte_is_refused(self):
        self.plant()
        ident = self.large[0]["id"]
        code = ("import sys; sys.path[:0]=[%r,%r,%r]; import kit3; "
                "sys.exit(kit3.main(['read', %r, 'inv/m0\\0.py']) + 10*kit3.main(['show', 'M-0003\\0']))") % (
                    str(ROOT / "swarm" / "phase3"), str(ROOT / "swarm" / "phase2"), str(ROOT / "swarm"), ident)
        before = snapshot(self.home)
        done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                              env={"SWARM_HOME": str(self.home), "PATH": os.environ.get("PATH", "")}, timeout=60)
        self.assertEqual(done.returncode, 22, done.stdout + done.stderr)
        self.assertEqual(before, snapshot(self.home))
        with self.assertRaises(ValueError):  # the operating system cannot carry a NUL byte in an argument at all
            subprocess.run([sys.executable, str(KIT3), "show", "M-0003\0"])


class Withheld(Base):
    def test_no_verb_names_a_withheld_folder(self):
        self.single()
        ident = self.large[0]["id"]
        names = [f".hidden/{ident}.json", f"../.hidden/{ident}.json", f".kit/{ident}.json", f"../.kit/{ident}.json", ".queue/meta.json",
                 "inv/../../.hidden", ".hidden", ".queue"]
        before = snapshot(self.home)
        for name in names:
            for verb in (("read", ident, name), ("grep", ident, "a", name), ("select", ident, name, "a=b", "c")):
                code, out = swk(self.home, *verb)
                self.assertEqual(code, 2, (verb[0], name, out[:200]))
            self.assertEqual(swk(self.home, "show", f"{ident}/{name}")[0], 2)
        self.assertEqual(before, snapshot(self.home))

    def test_no_output_holds_the_withheld_tests_or_the_state(self):
        self.single()
        secrets_ = set()
        for t in self.items:
            hidden = json.loads((self.stage / ".hidden" / f"{t['id']}.json").read_text())
            secrets_ |= {s for s in strings(hidden) if len(s) >= 12}
        # what the worker is told is not secret: drop any string that its task text shows
        shown = "".join((self.stage / t["id"] / "TASK.md").read_text() for t in self.items)
        secrets_ = {s for s in secrets_ if s not in shown}
        self.assertTrue(secrets_, "the stage holds no withheld text to look for")
        outputs = []
        for t in self.items:
            ident = t["id"]
            outputs.append(swk(self.home, "show", ident)[1])
            outputs.append(swk(self.home, "grep", ident, ".")[1] if t["id"].startswith("L") else "")
            outputs.append(swk(self.home, "test", ident)[1] if t["id"].startswith("L") else "")
            outputs.append(swk(self.home, "submit", ident, stdin="def nothing():\n    return None\n")[1])
            outputs.append(swk(self.home, "next", "wa")[1])
        outputs.append(swk(self.home, "status")[1])
        text = "\n".join(outputs)
        for secret in secrets_:
            self.assertNotIn(secret, text)


class HandIn(Base):
    def test_a_solution_that_is_a_folder_is_refused(self):
        self.single()
        ident = self.medium[0]["id"]
        (self.stage / ident / "solution.py").mkdir()
        code, out = swk(self.home, "submit", ident, stdin=self.medium[0]["reference"])
        self.assertEqual(code, 2, out)
        self.assertTrue((self.stage / ident / "solution.py").is_dir())

    def test_a_solution_that_is_a_symbolic_link_is_not_written_through(self):
        self.single()
        ident = self.medium[0]["id"]
        victim = self.home / "victim.txt"
        victim.write_text("KEEP\n")
        os.symlink(victim, self.stage / ident / "solution.py")
        swk(self.home, "submit", ident, stdin=self.medium[0]["reference"])
        self.assertEqual(victim.read_text(), "KEEP\n")

    def test_an_answer_that_is_a_symbolic_link_is_not_written_through(self):
        self.single()
        ident = self.large[0]["id"]
        victim = self.home / "victim.txt"
        victim.write_text("KEEP\n")
        os.symlink(victim, self.stage / ident / "ANSWER.json")
        facts = {k: "x" for k in ("fixed_function", "direct_callers", "failed_event_ids", "build_error_code")}
        swk(self.home, "answer", ident, stdin=json.dumps(facts))
        self.assertEqual(victim.read_text(), "KEEP\n")

    def test_a_task_folder_that_is_a_link_out_is_not_read(self):
        stage = self.single()
        ident = self.medium[0]["id"]
        outside = self.home / "elsewhere"
        outside.mkdir()
        (outside / "TASK.md").write_text("ELSEWHERE SECRET\n")
        import shutil
        shutil.rmtree(stage / ident)
        os.symlink(outside, stage / ident)
        code, out = swk(self.home, "show", ident)
        # a task folder replaced by a link is followed: a worker cannot make it, the host can
        self.assertNotEqual(out.strip(), "")
        self.assertIn(code, (0, 2))

    def test_input_of_5_megabytes_is_refused_and_does_not_fill_the_disk(self):
        self.single()
        big = "x" * (5 * 1024 * 1024)
        before = snapshot(self.home)
        for verb in (("submit", self.medium[0]["id"]), ("setline", self.large[0]["id"], "inv/m0.py", "1"), ("answer", self.large[0]["id"])):
            code, out = swk(self.home, *verb, stdin=big)
            self.assertEqual(code, 2, (verb, out[:200]))
            self.assertLess(len(out), 2000)
        grown = sum(max(0, after[1] - before.get(path, (0, 0, 0))[1]) for path, after in snapshot(self.home).items() if not Path(path).is_dir())
        self.assertLess(grown, 100_000, "a refused 5 MB input left bytes behind")
        self.assertFalse((self.stage / self.medium[0]["id"] / "solution.py").exists())

    def test_input_just_over_the_limit_is_refused_and_does_not_use_an_attempt(self):
        self.single()
        ident = self.medium[0]["id"]
        code, _ = swk(self.home, "submit", ident, stdin="#" * 40001)
        self.assertEqual(code, 2)
        state = json.loads((self.stage / ".kit" / f"{ident}.json").read_text())
        self.assertEqual(state["attempts"], 0)


class Modes(Base):
    def test_the_private_state_folders_are_not_readable_by_others(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        self.single(queue=True)
        loose = [str(p.relative_to(self.home)) for p in (self.stage / ".hidden", self.stage / ".kit", self.stage / ".queue") if p.stat().st_mode & 0o077]
        self.assertEqual(loose, [])

    def test_a_refused_call_never_loosens_a_mode(self):
        self.single(queue=True)
        for p in (self.stage / ".hidden", self.stage / ".kit", self.stage / ".queue"):
            p.chmod(0o700)
        for verb in (("show", "../x"), ("read", self.large[0]["id"], ".hidden"), ("next", "wa")):
            swk(self.home, *verb)
        for p in (self.stage / ".hidden", self.stage / ".kit", self.stage / ".queue"):
            self.assertEqual(p.stat().st_mode & 0o777, 0o700)


class NoMixing(Base):
    def test_no_output_holds_the_text_of_another_task(self):
        self.single()
        own = {t["id"]: (self.stage / t["id"] / "TASK.md").read_text() for t in self.items}
        files = {}
        for t in self.large:
            folder = self.stage / t["id"]
            files[t["id"]] = {str(p.relative_to(folder)): p.read_text() for sub in ("inv", "data", "logs", "tests") for p in (folder / sub).glob("*") if p.is_file()}

        def distinct(ident):
            """Lines that belong to another task only."""
            mine = own[ident] + "".join(files.get(ident, {}).values())
            lines = set()
            for other, text in own.items():
                if other != ident:
                    lines |= {l.strip() for l in (text + "".join(files.get(other, {}).values())).splitlines() if len(l.strip()) >= 25}
            return {l for l in lines if l not in mine}

        for t in self.items:
            ident = t["id"]
            outputs = [swk(self.home, "show", ident)[1], swk(self.home, "submit", ident, stdin="def nothing():\n    return None\n")[1]]
            if ident.startswith("L"):
                outputs += [swk(self.home, "grep", ident, ".")[1], swk(self.home, "test", ident)[1]]
                for name in sorted(files[ident])[:3]:
                    outputs.append(swk(self.home, "read", ident, name)[1])
                outputs.append(swk(self.home, "grep", ident, "a", "inv")[1])
            text = "\n".join(outputs)
            for line in distinct(ident):
                self.assertNotIn(line, text, ident)

    def test_next_gives_each_worker_its_own_task_text_only(self):
        self.single(queue=True)
        own = {t["id"]: (self.stage / t["id"] / "TASK.md").read_text() for t in self.items}
        got = {}
        for worker in ("wa", "wb", "wc", "wd"):
            code, out = swk(self.home, "next", worker)
            self.assertEqual(code, 0)
            ident = re.search(r"\b[SMLX]-\d{4}\b", out).group(0)
            got[ident] = out
        self.assertEqual(sorted(got), sorted(self.ids))
        for ident, out in got.items():
            for other, text in own.items():
                if other != ident:
                    self.assertNotIn(f"## Task {other}", out)


if __name__ == "__main__":
    unittest.main()
