import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
import context_budget as cb  # noqa: E402


def agent(root, name, tools="Bash", body="Do it.", hook="swk-guard"):
    d = Path(root) / ".claude" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    hooks = (f"hooks:\n  PreToolUse:\n    - hooks:\n        - type: command\n"
             f"          command: \"{hook}\"\n") if hook else ""
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ntools: {tools}\nmodel: haiku\nmaxTurns: 3\n{hooks}---\n\n{body}\n")


class Budget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fields(self):
        agent(self.root, "swarm-x")
        a = cb.budget(self.root)["agents"][0]
        self.assertEqual((a["name"], a["tools"], a["model"], a["maxTurns"], a["gated"]),
                         ("swarm-x", ["Bash"], "haiku", 3, True))
        self.assertEqual(a["tokens_estimate"], a["chars"] // 4)
        self.assertIn("estimate", cb.budget(self.root)["note"])

    def test_ungated(self):
        agent(self.root, "swarm-x", hook=None)
        self.assertFalse(cb.budget(self.root)["agents"][0]["gated"])

    def test_definition_limit(self):
        agent(self.root, "swarm-x", body="x" * 2000)
        self.assertTrue(any("definition" in p for p in cb.check(self.root, {})))
        self.assertFalse(cb.check(self.root, {"definition_chars": 5000}))

    def test_tool_rule(self):
        agent(self.root, "swarm-x", tools="Bash, Read")
        self.assertTrue(any("Read" in p for p in cb.check(self.root, {})))
        agent(self.root, "swarm-dev", tools="Bash, Read, Write, Edit, Grep, Glob")
        self.assertFalse([p for p in cb.check(self.root, {}) if "swarm-dev" in p])
        agent(self.root, "other", tools="Read")
        self.assertFalse([p for p in cb.check(self.root, {}) if "other" in p])

    def test_instruction_files(self):
        (self.root / "CLAUDE.md").write_text("@AGENTS.md\n@docs.md\n")
        (self.root / "AGENTS.md").write_text("a" * 100)
        (self.root / "docs.md").write_text("b" * 50)
        b = cb.budget(self.root)
        self.assertEqual(b["instructions_chars"], len("@AGENTS.md\n@docs.md\n") + 150)
        self.assertTrue(cb.check(self.root, {"instructions_chars": 100}))
        self.assertFalse(cb.check(self.root, {}))

    def test_real_repository(self):
        self.assertEqual(cb.check(ROOT, {}), [])


if __name__ == "__main__":
    unittest.main()
