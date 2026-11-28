"""recheck-authz F1 (checkout guard part): a submodule that has submodules of its own is refused.

checkout_guard resolved and checked only the superproject's own gitlinks, so a nested submodule
(sub/nested) whose gitfile points outside .git/modules, or whose .git is an embedded directory, passed
the guard with a filter program in its config; a plain `git status` then ran that program. The fail-closed
option chosen: a populated submodule whose index records any gitlink is refused, populated or not, and
nested Git directories are never traversed or trusted. Each planted case first shows that plain Git runs
the program. Synthetic repositories built at run time; no network, no deployment.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import control_plane, release_engine  # noqa: E402
from sdk import engineering_sdk as sdk  # noqa: E402

REPOSITORY, TEAM, PROJECT = "https://github.com/example/release-probe", "team_probe", "prj_probe"
NESTED = "nested submodule"


def git_env():
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="Test",
               GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")
    return env


def run_git(root, *args):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "protocol.file.allow=always", "-C", str(root),
                           *args], capture_output=True, text=True, check=True, env=git_env(), timeout=60).stdout


class NestedSubmoduleGuard(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rf2-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name)
        os.chmod(self.base, 0o700)
        self.marker = self.base / "program-ran"
        self.program = self.base / "planted.sh"
        self.program.write_text(f'#!/bin/sh\ntouch "{self.marker}"\nexec cat\n')
        self.program.chmod(0o700)
        nested, sub = self.base / "nestedsrc", self.base / "subsrc"
        for path in (nested, sub):
            path.mkdir()
            run_git(path, "init", "-q")
        (nested / "a.txt").write_text("hello\n")
        (nested / ".gitattributes").write_text("* filter=probe\n")
        run_git(nested, "add", "-A")
        run_git(nested, "commit", "-qm", "nested")
        (sub / "s.txt").write_text("s\n")
        run_git(sub, "add", "-A")
        run_git(sub, "commit", "-qm", "s")
        run_git(sub, "submodule", "--quiet", "add", str(nested), "nested")
        run_git(sub, "commit", "-qm", "add nested")
        self.root = self.base / "super"
        (self.root / ".engineering").mkdir(parents=True)
        (self.root / ".engineering/project.json").write_text(json.dumps({
            "schema_version": 1, "identity_verified": True, "repository": REPOSITORY,
            "vercel": {"team_id": TEAM, "project_id": PROJECT, "root_directory": "."}, "required_checks": ["test"]}))
        run_git(self.root, "init", "-q")
        run_git(self.root, "add", "-A")
        run_git(self.root, "commit", "-qm", "base")
        run_git(self.root, "submodule", "--quiet", "add", str(sub), "sub")
        run_git(self.root, "submodule", "--quiet", "update", "--init", "--recursive")
        run_git(self.root, "commit", "-qm", "add submodule")
        self.commit = run_git(self.root, "rev-parse", "HEAD").strip()
        self.gitdir = self.root / ".git/modules/sub/modules/nested"

    def plant(self, mode):
        """Move the nested Git directory outside .git/modules (gitfile) or into its folder (embedded)."""
        gitdir = self.gitdir
        if mode == "gitfile":
            gitdir = pathlib.Path(shutil.move(str(gitdir), str(self.base / "elsewhere-gitdir")))
            run_git(self.root, "config", "-f", str(gitdir / "config"), "core.worktree", str(self.root / "sub/nested"))
            (self.root / "sub/nested/.git").write_text(f"gitdir: {gitdir}\n")
        elif mode == "embedded":
            (self.root / "sub/nested/.git").unlink()
            gitdir = pathlib.Path(shutil.move(str(gitdir), str(self.root / "sub/nested/.git")))
            run_git(self.root, "config", "-f", str(gitdir / "config"), "--unset", "core.worktree")
        for key in ("filter.probe.clean", "filter.probe.smudge"):
            run_git(self.root, "config", "-f", str(gitdir / "config"), key, str(self.program))
        os.utime(self.root / "sub/nested/a.txt", (978307200, 978307200))  # stat-dirty: status re-hashes it

    def plain_status(self):
        subprocess.run(["git", "-C", str(self.root), "status", "--porcelain"], stdin=subprocess.DEVNULL,
                       capture_output=True, env=git_env(), timeout=60, check=False)

    def assert_refused(self):
        with self.assertRaisesRegex(ValueError, NESTED):
            sdk.checkout_guard(self.root)
        with self.assertRaisesRegex(ValueError, NESTED):
            sdk.target(self.root, REPOSITORY, TEAM, PROJECT, self.commit)

    def test_a_nested_gitdir_outside_modules_or_embedded_is_refused_and_never_runs(self):
        for mode in ("gitfile", "embedded"):
            with self.subTest(mode=mode):
                if mode != "gitfile":
                    self.setUp()
                self.plant(mode)
                self.plain_status()
                self.assertTrue(self.marker.exists(), "premise: plain git status runs the nested filter")
                self.marker.unlink()
                self.assert_refused()
                self.assertFalse(self.marker.exists(), "the planted filter program ran")

    def test_a_clean_nested_submodule_and_an_unpopulated_one_are_refused_too(self):
        self.assert_refused()  # nested Git directory in .git/modules, no program configured anywhere
        run_git(self.root / "sub", "submodule", "--quiet", "deinit", "-f", "nested")
        self.assertFalse((self.root / "sub/nested/.git").exists())
        self.assert_refused()  # still recorded in sub's index

    def test_an_unpopulated_parent_and_a_submodule_without_children_still_pass(self):
        run_git(self.root, "submodule", "--quiet", "deinit", "-f", "sub")
        self.assertEqual(sdk.target(self.root, REPOSITORY, TEAM, PROJECT, self.commit)["repository"], REPOSITORY)
        plain = self.base / "plainsrc"
        plain.mkdir()
        run_git(plain, "init", "-q")
        (plain / "p.txt").write_text("p\n")
        run_git(plain, "add", "-A")
        run_git(plain, "commit", "-qm", "p")
        other = self.base / "other"
        run_git(self.base, "init", "-q", str(other))
        (other / "r.txt").write_text("r\n")
        run_git(other, "add", "-A")
        run_git(other, "commit", "-qm", "r")
        run_git(other, "submodule", "--quiet", "add", str(plain), "plain")
        run_git(other, "commit", "-qm", "add plain")
        sdk.checkout_guard(other)

    def test_read_only_release_checks_refuse_and_never_run_the_planted_program(self):
        self.plant("gitfile")
        profile = {"schema": release_engine.PROFILE_SCHEMA, "product": "probe", "title": "Probe", "tag_prefix": "v",
                   "changelog": "CHANGELOG.md", "changelog_heading": "Probe", "version_file": None, "components": [],
                   "required_jobs": {".github/workflows/ci.yml": ["test"]}}
        result = release_engine.engine("eligibility", {"root": str(self.root), "profile": profile, "version": "1.0.0",
                                                       "commit": self.commit}, {})
        self.assertEqual([row["code"] for row in result["refusals"]], ["checkout-unsafe"])
        self.assertIn(NESTED, result["refusals"][0]["detail"])
        state = self.base / "state"
        state.mkdir(mode=0o700)
        grant = {"grant_id": "g-rf2-release-read", "role": "release-engineer",
                 "engines": {"master-release": ["eligibility"]}, "paths": [str(self.root)],
                 "max_side_effect": "none", "expires_at": "2099-01-01T00:00:00Z", "approvals": []}
        payload = {"root": str(self.root), "evidence": {}, "repository": REPOSITORY, "team": TEAM,
                   "project": PROJECT, "commit": self.commit}
        with self.assertRaisesRegex(control_plane.ControlPlaneError, NESTED):
            control_plane.invoke("master-release", "eligibility", payload, grant=grant, ctx={"state_dir": str(state)})
        self.assertFalse(self.marker.exists(), "a side_effect none eligibility check ran the program")


if __name__ == "__main__":
    unittest.main()
