"""Lane S1: attack the worker's gate (guard.py) and the worker's command (kit.py).

Run: python3 -m unittest tests.test_p3_gate_fuzz

What was tried
  Gate: an independent hand-written scanner (no regular expressions) defines the allowed
  language; 6,000 commands from a seeded generator (fragments with `;`, `&&`, `|`, `>`, `<`,
  backquotes, `$(`, `${`, `$'`, `<<<`, `<<-`, unquoted `<<TAG`, backslash at a line end,
  carriage returns, tabs, NUL, `~ * ? {a,b} # !`, padding spaces, an assignment before the
  command, several lines, a here-document closed early or never, look-alikes of the letters
  of `swk` such as Cyrillic and full-width letters, non-ASCII digits) plus hand-made cases
  are checked: the gate must let through exactly what the scanner accepts.
  Command: task ids and paths that try to leave the task folder (`..`, absolute, encoded,
  non-ASCII digits, a trailing newline), a symlink planted inside the project and given to
  `read`, `grep` (with and without a path) and `setline`, a very large standard input to
  `submit`, `setline` and `answer`, and a regular expression that runs for minutes in `grep`.

What held
  The gate: no difference from the scanner in any generated or hand-made command.
  The command: every id and path outside the task was refused; `read`, `setline` and
  `grep PATH` refuse a symlink that leaves the task folder; `swk answer` and `submit`
  refuse over-long input.

What was closed (each has a regression test that failed before the change)
  1. test_grep_without_path_does_not_follow_a_symlink: `swk grep ID REGEX` listed the
     project folders with glob and read every file, following a symlink that points out of
     the task. Now each file is resolved and skipped unless it stays inside the folder.
  2. test_grep_regex_cannot_run_for_minutes: a regular expression with nested quantifiers
     ran without limit. Now the search is stopped after a few seconds and refused.
  3. test_status_takes_no_words: the gate let `swk status WORD...` through as an ordinary
     line (the command refuses it, but the gate's stated shapes do not include it). Closed.
  4. test_large_stdin_is_not_read_whole: `submit`, `setline` and `answer` read all of
     standard input before judging its length, so a huge input used all the memory. Now at
     most one byte more than the limit is read.
"""
from __future__ import annotations

import json
import os
import random
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "swarm" / "phase2"), str(ROOT / "swarm")]
import guard  # noqa: E402
import tasks  # noqa: E402

KIT = ROOT / "swarm" / "phase2" / "kit.py"
WORD_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:=,@%+-")
LINE_VERBS = {"show", "next", "status", "test", "read", "grep", "def", "callers", "select"}
DOC_VERBS = {"submit", "setline", "answer"}
TAG_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")


# ---- my own definition of the allowed language: a scanner, not a pattern -------------------

def scan_args(text: str, at: int, stop_at_redirect: bool) -> int | None:
    """Read ` WORD` (and, on a one-line command only, ` 'quoted'`) items from `at`. Returns where they end, or None."""
    n = len(text)
    while at < n:
        if text[at] != " ":
            return at if stop_at_redirect else None
        nxt = at + 1
        if nxt >= n:
            return None
        if text[nxt] == "'" and not stop_at_redirect:
            close = text.find("'", nxt + 1)
            if close < 0 or "\n" in text[nxt:close]:
                return None
            at = close + 1
        elif text[nxt] in WORD_CHARS:
            at = nxt
            while at < n and text[at] in WORD_CHARS:
                at += 1
        elif stop_at_redirect and text.startswith("<<'", nxt):
            return at
        else:
            return None
    return at


def head(text: str, verbs: set[str]) -> int | None:
    if not text.startswith("swk "):
        return None
    at = 4
    while at < len(text) and text[at] in WORD_CHARS:
        at += 1
    return at if text[4:at] in verbs else None


def my_parser(raw: str) -> bool:
    text = raw
    while text.startswith("\n"):
        text = text[1:]
    while text.endswith("\n"):
        text = text[:-1]
    if "\n" not in text:
        if text == "swk status":
            return True
        end = head(text, LINE_VERBS - {"status"})
        return end is not None and scan_args(text, end, False) == len(text)
    lines = text.split("\n")
    first, body = lines[0], lines[1:]
    end = head(first, DOC_VERBS)
    if end is None:
        return False
    stop = scan_args(first, end, True)
    if stop is None or not first.startswith(" <<'", stop):
        return False
    tag_start = stop + 4
    close = first.find("'", tag_start)
    tag = first[tag_start:close] if close > 0 else ""
    if close != len(first) - 1 or not tag or any(c not in TAG_CHARS for c in tag):
        return False
    return body[-1] == tag and tag not in body[:-1]


# ---- the generator -------------------------------------------------------------------------

HOSTILE = [";", "&&", "||", "|", ">", ">>", "<", "`id`", "$(id)", "${HOME}", "$'a'", "<<<", "<<-", "<<EOF", "\\\n", "\r", "\t", "\x00", "~", "*", "?",
           "{a,b}", "#", "!", " ", "  ", "\n", "\n\n", "A=1 ", "&", "(", ")", "'", "''", "\"", "$", "\\", "..", "/etc/passwd", "'a b'", "'a\nb'",
           "'it's'", "ѕwk", "swk", "ѕwк", "ｓｗｋ", "swK", "١٢", " ", " ", "\x0b", "\x0c"]
VERBS = sorted(LINE_VERBS | DOC_VERBS | {"x", "Show", "SHOW", "show2", "sh0w", "status", ""})
WORDS = ["S-0001", "inv/m1.py", "1:20", "a=b", "x,y", "foo.bar", "%d", "a@b", "+1", "-n", "S-١٢٣٤", "L-0001", "tests"]
TAGS = ["EOF", "PY", "A", "a_b", "E0F", "", "EOF ", "E-F"]


def valid_like(rng: random.Random) -> str:
    verb = rng.choice(VERBS)
    parts = ["swk", verb]
    for _ in range(rng.randint(0, 3)):
        parts.append(rng.choice(WORDS) if rng.random() < 0.7 else "'" + rng.choice(["a b", "^x$", "(a|b)", "", "a;b", "$(x)", "`x`", "\\n"]) + "'")
    if verb in DOC_VERBS and rng.random() < 0.8:
        tag = rng.choice(TAGS)
        quote = rng.choice(["'", "'", "'", "", '"', "\\"])
        parts.append(f"<<{quote}{tag}{quote}")
        body = [rng.choice(["x = 1", "EOF", "PY", "A", "", "$(id)", "a_b", "`x`", "E0F "]) for _ in range(rng.randint(0, 3))]
        if rng.random() < 0.8:
            body.append(tag)
        return " ".join(parts) + "\n" + "\n".join(body)
    return " ".join(parts)


def generate(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        command = valid_like(rng)
        for _ in range(rng.choice([0, 0, 1, 1, 2, 3])):
            at = rng.randint(0, len(command))
            piece = rng.choice(HOSTILE)
            command = command[:at] + piece + command[at:] if rng.random() < 0.8 else command[:at] + command[at + len(piece):]
        if rng.random() < 0.1:
            command = rng.choice(["\n", " ", "\t", "  "]) + command
        if rng.random() < 0.1:
            command += rng.choice(["\n", " ", "\t", "\n\n", "\r\n", ";"])
        out.append(command)
    return out


HAND = [
    "swk status", "swk status ", " swk status", "swk status;id", "swk show S-0001", "swk show S-0001 ", "swk show S-0001\n", "\nswk show S-0001",
    "swk show S-0001; id", "swk show S-0001 && id", "swk show S-0001 | cat", "swk show S-0001 > f", "swk show `id`", "swk show $(id)", "swk show ${HOME}",
    "swk show $'a'", "swk grep L-0001 'a b' inv/m1.py", "swk grep L-0001 'a\nb'", "swk grep L-0001 'a'b", "swk grep L-0001 'a''b'", "swk read L-0001 ~",
    "swk read L-0001 *", "swk read L-0001 {a,b}", "swk read L-0001 #x", "swk read L-0001 !x", "A=1 swk status", "swk\tshow S-0001", "swk show\tS-0001",
    "swk show S-0001\r", "swk show S-0001\\\n", "swk show S-0001 \\\n", "ѕwk show S-0001", "swk show S-0001 <<<x", "swk show S-0001 <<EOF\nx\nEOF",
    "swk submit S-0001 <<'EOF'\nx\nEOF", "swk submit S-0001 <<'EOF'\nx\nEOF\nid\nEOF", "swk submit S-0001 <<'EOF'\nx\nEOF\nid", "swk submit S-0001 <<EOF\nx\nEOF",
    "swk submit S-0001 <<-'EOF'\nx\nEOF", "swk submit S-0001 <<<'EOF'\nx\nEOF", "swk submit S-0001 <<'EOF' ; id\nx\nEOF", "swk submit S-0001 <<'EOF'\nEOF",
    "swk submit S-0001 <<'EOF'\n\nEOF", "swk submit S-0001 <<'EOF'\nEOF ", "swk answer L-0001 <<'EOF'\n{}\nEOF\n", "swk setline L-0001 inv/m1.py 3 <<'E'\nx=1\nE",
    "swk setline L-0001 inv/m1.py 3 <<'E1'\nx=1\nE1", "swk submit <<'EOF'\nEOF\n", "swk show", "swk", "", "\n", "swk  show S-0001", "swk show  S-0001",
    "swk show 'unterminated", "swk show S-0001 \x00", "swk show S-0001 '\x00'", "swk show S-0001 '\r'", "swk Show S-0001", "swk next", "swk next S-0001 x",
]


class GateFuzz(unittest.TestCase):
    def test_scanner_agrees_on_the_obvious(self) -> None:
        self.assertTrue(my_parser("swk read L-0001 inv/m1.py 1:5"))
        self.assertTrue(my_parser("swk answer L-0001 <<'EOF'\n{}\nEOF"))
        self.assertFalse(my_parser("swk show S-0001; id"))
        self.assertFalse(my_parser("swk answer L-0001 <<'EOF'\nEOF\nid\nEOF"))

    def test_hand_made_cases(self) -> None:
        for command in HAND:
            with self.subTest(command=command):
                self.assertEqual(guard.allowed(command), my_parser(command))

    def test_generated_commands_match_the_scanner(self) -> None:
        commands = generate(20260101, 6000)
        self.assertGreaterEqual(len(commands), 5000)
        accepted = 0
        for command in commands:
            mine = my_parser(command)
            accepted += mine
            if guard.allowed(command) != mine:
                self.fail(f"gate and scanner differ on {command!r}: gate={guard.allowed(command)} scanner={mine}")
        self.assertGreater(accepted, 100, "the generator must produce commands that are allowed, or the test says nothing")
        self.assertLess(accepted, len(commands) - 1000)

    def test_main_refuses_anything_that_is_not_a_bash_call(self) -> None:
        for call, code in (({"tool_name": "Bash", "tool_input": {"command": "swk status"}}, 0), ({"tool_name": "Write", "tool_input": {"command": "swk status"}}, 2),
                           ({"tool_name": "Bash", "tool_input": {"command": ["swk", "status"]}}, 2), ({"tool_name": "Bash", "tool_input": {}}, 2),
                           ({"tool_name": "Bash", "tool_input": {"command": "swk status; id"}}, 2), ([], 2)):
            done = subprocess.run([sys.executable, "-I", str(ROOT / "swarm" / "phase2" / "guard.py")], input=json.dumps(call), text=True, capture_output=True)
            self.assertEqual(done.returncode, code, call)
        done = subprocess.run([sys.executable, "-I", str(ROOT / "swarm" / "phase2" / "guard.py")], input="not json", text=True, capture_output=True)
        self.assertEqual(done.returncode, 2)


class KitAttack(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.stage = self.home / "p2" / "work" / "st"
        self.stage.mkdir(parents=True)
        (self.home / "p2" / "current").write_text("st")
        self.made = tasks.make(self.stage, "large", 1, 1, mode="lean")
        self.small = tasks.make(self.stage, "small", 1, 1)
        self.ident = self.made[0]["id"]
        self.folder = self.stage / self.ident
        self.secret = Path(self.tmp.name) / "outside.txt"
        self.secret.write_text("TOPSECRET line\n")

    def swk(self, *args: str, stdin: str | None = "", timeout: int = 30, limit_mb: int | None = None) -> subprocess.CompletedProcess:
        env = {"SWARM_HOME": str(self.home), "PATH": os.environ.get("PATH", "")}

        def cap() -> None:
            if limit_mb:
                resource.setrlimit(resource.RLIMIT_AS, (limit_mb << 20, limit_mb << 20))
        return subprocess.run([sys.executable, "-I", str(KIT), *args], input=stdin, capture_output=True, text=True, env=env, timeout=timeout,
                              preexec_fn=cap if limit_mb else None)

    def plant(self, name: str = "inv/link.txt") -> Path:
        link = self.folder / name
        link.parent.mkdir(exist_ok=True)
        link.symlink_to(self.secret)
        return link

    # ---- what held ----
    def test_ids_and_paths_that_leave_the_folder_are_refused(self) -> None:
        for ident in ("../L-0001", "L-0001/../L-0001", "/etc", "L-0001\n", "L-١٢٣٤", "L-00011", "l-0001", ".", "", "L-0001 ", "%2e%2e"):
            for verb in (["show", ident], ["read", ident, "inv/m1.py"], ["grep", ident, "x"]):
                done = self.swk(*verb)
                self.assertEqual(done.returncode, 2, (verb, done.stdout))
                self.assertNotIn("TASK", done.stdout)
        for name in ("../outside.txt", "/etc/passwd", "inv/../../outside.txt", "inv/..", "inv/.", ".kit/L-0001.json", ".hidden/L-0001.json", "TASK.md", "inv//m1.py",
                     "inv/m1.py/", "inv\\m1.py", "inv/m1.py\n", "inv/%2e%2e", "ANSWER.json", "inv/ѕ.py"):
            for verb in ("read", "grep", "setline"):
                if verb == "grep" and name == "inv/.":
                    continue  # a folder of the project itself: searching it is allowed
                args = ([verb, self.ident, "x", name] if verb == "grep" else [verb, self.ident, name] + (["1"] if verb == "setline" else []))
                done = self.swk(*args, stdin="x = 1\n")
                self.assertEqual(done.returncode, 2, (args, done.stdout))
                self.assertNotIn("TOPSECRET", done.stdout)

    def test_a_task_of_another_size_or_stage_is_not_reachable(self) -> None:
        self.assertEqual(self.swk("read", self.small[0]["id"], "inv/m1.py").returncode, 2)
        self.assertEqual(self.swk("show", "S-9999").returncode, 2)

    def test_symlink_is_refused_by_read_setline_and_grep_with_a_path(self) -> None:
        self.plant("inv/m9.py")
        self.plant("inv/link.txt")
        self.assertEqual(self.swk("read", self.ident, "inv/link.txt").returncode, 2)
        self.assertEqual(self.swk("grep", self.ident, "TOPSECRET", "inv/link.txt").returncode, 2)
        done = self.swk("setline", self.ident, "inv/m9.py", "1", stdin="x = 1\n")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(self.secret.read_text(), "TOPSECRET line\n")

    def test_a_symlinked_folder_is_refused(self) -> None:
        outside = Path(self.tmp.name) / "outdir"
        outside.mkdir()
        (outside / "a.txt").write_text("TOPSECRET\n")
        shutil.rmtree(self.folder / "logs")
        (self.folder / "logs").symlink_to(outside)
        self.assertEqual(self.swk("read", self.ident, "logs/a.txt").returncode, 2)
        self.assertNotIn("TOPSECRET", self.swk("grep", self.ident, "TOPSECRET", "logs").stdout)

    def test_over_long_input_is_refused(self) -> None:
        self.assertEqual(self.swk("setline", self.ident, "inv/m1.py", "1", stdin="x" * 500).returncode, 2)
        self.assertEqual(self.swk("answer", self.ident, stdin="{" * 100000).returncode, 2)
        self.assertEqual(self.swk("submit", self.small[0]["id"], stdin="#" * 50000).returncode, 2)

    # ---- the holes, as regression tests ----
    def test_grep_without_path_does_not_follow_a_symlink(self) -> None:
        self.plant("inv/link.txt")
        done = self.swk("grep", self.ident, "TOPSECRET")
        self.assertNotIn("TOPSECRET", done.stdout)

    def test_grep_regex_cannot_run_for_minutes(self) -> None:
        path = self.folder / "logs" / "long.log"
        path.parent.mkdir(exist_ok=True)
        path.write_text("a" * 60 + "!\n")
        started = time.monotonic()
        done = self.swk("grep", self.ident, "(a+)+$", timeout=60)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(done.returncode, 2, done.stdout)

    def test_status_takes_no_words(self) -> None:
        self.assertFalse(guard.allowed("swk status a@b L-0001"))
        self.assertTrue(guard.allowed("swk status"))

    def test_large_stdin_is_not_read_whole(self) -> None:
        big = "x" * (100 << 20)
        for args in (("setline", self.ident, "inv/m1.py", "1"), ("answer", self.ident)):
            done = self.swk(*args, stdin=big, timeout=60, limit_mb=200)
            self.assertEqual(done.returncode, 2, (args, done.stderr[-300:]))
        done = self.swk("submit", self.small[0]["id"], stdin=big, timeout=60, limit_mb=200)
        self.assertEqual(done.returncode, 2, done.stderr[-300:])


if __name__ == "__main__":
    unittest.main()
