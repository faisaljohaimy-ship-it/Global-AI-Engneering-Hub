"""Check that Codex adapts branch ownership without changing canonical routing gates."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import gaie_router
from scripts import gaie_codex_route


ROOT = pathlib.Path(__file__).resolve().parents[2]


class CodexRouteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.lab = pathlib.Path(temporary.name).resolve()
        self.env = {"GAIE_HOME": str(self.lab / "gaie")}

    def canonical(self, text, **kwargs):
        return gaie_router.route(text, environ=self.env, **kwargs)

    def codex(self, text, **kwargs):
        return gaie_codex_route.route(text, environ=self.env, **kwargs)

    def test_upgrade_performance_repair_media_and_multiple_targets_only_change_suggested_branches(self):
        commands = ("طور سديد بالكامل", "سرّع سديد", "أصلح أخطاء سديد", "طور فيديوهات سديد", "طور جميع مشاريعي")
        for text in commands:
            with self.subTest(text=text):
                expected = self.canonical(text)
                actual = self.codex(text)
                self.assertFalse(actual["write_allowed"])
                self.assertTrue(actual["blockers"])
                self.assertGreater(len(actual["targets"]), 0)
                for target in expected["targets"]:
                    scope = target["execution_scope"]
                    suffix = f"gaie-{expected['intent']}-{target['id']}"
                    self.assertEqual(scope["branch"], f"claude/{suffix}")
                    scope["branch"] = f"codex/{suffix}"
                self.assertEqual(actual, expected)

    def test_build_audit_release_and_clarification_are_unchanged(self):
        for text in ("ابنِ نظامًا جديدًا", "افحص سديد", "انشر سديد", "طور بلتكس"):
            with self.subTest(text=text):
                self.assertEqual(self.codex(text), self.canonical(text))

    def test_unrecognized_canonical_branch_suggestion_fails_closed(self):
        text = "طور سديد بالكامل"
        plan = self.canonical(text)
        plan["targets"][0]["execution_scope"]["branch"] = "claude/another-lane"
        with mock.patch.object(gaie_router, "route", return_value=plan):
            with self.assertRaisesRegex(gaie_router.RouteError, "Unexpected canonical branch"):
                self.codex(text)

    def test_cli_keeps_the_canonical_project_and_blockers(self):
        text = "طور سديد بالكامل"
        result = subprocess.run(
            [sys.executable, "-B", "-m", "scripts.gaie_codex_route", text],
            cwd=ROOT, env={**os.environ, **self.env}, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(json.loads(result.stdout), self.codex(text))

    def test_verified_workspace_requires_codex_branch_only_for_write_plan(self):
        source = self.lab / "source"
        worktree = self.lab / "worktree"
        source.mkdir(mode=0o700)

        def git(path, *argv):
            subprocess.run(["git", "-C", str(path), *argv], check=True, capture_output=True, timeout=10)

        git(source, "init", "-q", "-b", "main")
        git(source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit",
            "--allow-empty", "-qm", "base")
        git(source, "remote", "add", "origin", "https://github.com/faisaljohaimy-ship-it/biz-pulse-ar.git")
        git(source, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(source, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        git(source, "worktree", "add", "-qb", "codex/fixture-review", str(worktree))
        worktree.chmod(0o700)

        text = "طور سديد بالكامل"
        codex_plan = self.codex(text, workspace_path=worktree)
        self.assertTrue(codex_plan["targets"][0]["workspace_matches"])
        self.assertEqual(codex_plan["execution_scope"]["branch"], "codex/fixture-review")
        self.assertEqual(codex_plan, self.canonical(text, workspace_path=worktree))
        self.assertFalse(codex_plan["write_allowed"])

        git(worktree, "branch", "-m", "claude/fixture-review")
        self.assertTrue(self.canonical(text, workspace_path=worktree)["targets"][0]["workspace_matches"])
        with self.assertRaisesRegex(gaie_router.RouteError, "dedicated codex/ worktree"):
            self.codex(text, workspace_path=worktree)
        audit = "افحص سديد"
        self.assertEqual(self.codex(audit, workspace_path=worktree), self.canonical(audit, workspace_path=worktree))
