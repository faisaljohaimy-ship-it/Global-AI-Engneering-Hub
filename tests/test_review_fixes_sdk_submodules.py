"""Review fix pr30-authz F1: the release checkout guard and submodules.

checkout_guard used to skip a symlinked submodule config and never looked at a submodule whose gitfile
points outside .git/modules; the `git status` in target() then recursed into the submodule and ran a
filter program planted there, also through the side_effect "none" master-release.eligibility action.
Each case first shows the premise on plain Git where it can, then proves the program never runs.
Synthetic repositories built at run time; no network, no deployment.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import control_plane  # noqa: E402
from sdk import engineering_sdk as sdk  # noqa: E402

REPOSITORY, TEAM, PROJECT = "https://github.com/example/release-probe", "team_probe", "prj_probe"


def git_env():
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="Test",
               GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")
    return env


def run_git(root, *args):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "protocol.file.allow=always", "-C", str(root),
                           *args], capture_output=True, text=True, check=True, env=git_env(), timeout=60).stdout


class SubmoduleGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-f1-")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name)
        os.chmod(self.base, 0o700)
        self.marker = self.base / "program-ran"
        self.filter = self.base / "filter.sh"
        self.filter.write_text(f'#!/bin/sh\ntouch "{self.marker}"\nexec cat\n')
        self.filter.chmod(0o700)
        source = self.base / "subsrc"
        source.mkdir()
        (source / "a.txt").write_text("hello\n")
        (source / ".gitattributes").write_text("* filter=probe\n")
        run_git(source, "init", "-q")
        run_git(source, "add", "-A")
        run_git(source, "commit", "-qm", "sub")
        self.root = self.base / "super"
        (self.root / ".engineering").mkdir(parents=True)
        (self.root / ".engineering/project.json").write_text(json.dumps({
            "schema_version": 1, "identity_verified": True, "repository": REPOSITORY,
            "vercel": {"team_id": TEAM, "project_id": PROJECT, "root_directory": "."}, "required_checks": ["test"]}))
        run_git(self.root, "init", "-q")
        run_git(self.root, "add", "-A")
        run_git(self.root, "commit", "-qm", "base")
        run_git(self.root, "submodule", "--quiet", "add", str(source), "sub")
        run_git(self.root, "commit", "-qm", "add submodule")
        self.commit = run_git(self.root, "rev-parse", "HEAD").strip()
        self.config = self.root / ".git/modules/sub/config"
        self.evil = f'[filter "probe"]\n\tclean = {self.filter}\n\tsmudge = cat\n'

    def target(self):
        return sdk.target(self.root, REPOSITORY, TEAM, PROJECT, self.commit)

    def stat_dirty(self, when=978307200):
        os.utime(self.root / "sub/a.txt", (when, when))  # same bytes: status re-hashes through the clean filter

    def plain_status(self):
        subprocess.run(["git", "-C", str(self.root), "status", "--porcelain"], capture_output=True,
                       env=git_env(), timeout=60, check=False)

    def symlinked_config(self):
        outside = self.base / "outside-config"
        outside.write_text(self.config.read_text() + self.evil)
        self.config.unlink()
        self.config.symlink_to(outside)

    def gitdir_outside_modules(self):
        elsewhere = self.base / "elsewhere-gitdir"
        (self.root / ".git/modules/sub").rename(elsewhere)
        with (elsewhere / "config").open("a") as handle:
            handle.write(self.evil)
        run_git(self.root, "config", "-f", str(elsewhere / "config"), "core.worktree", str(self.root / "sub"))
        (self.root / "sub/.git").write_text(f"gitdir: {elsewhere}\n")

    def assert_refused_and_never_ran(self, pattern):
        self.stat_dirty(1_000_000)
        with self.assertRaisesRegex(ValueError, pattern):
            sdk.checkout_guard(self.root)
        with self.assertRaisesRegex(ValueError, pattern):
            self.target()
        self.assertFalse(self.marker.exists(), "the planted filter program ran")

    def test_a_clean_checkout_with_a_submodule_still_passes(self):
        self.assertEqual(self.target()["repository"], REPOSITORY)

    def test_a_symlinked_submodule_config_is_refused_and_its_program_never_runs(self):
        self.symlinked_config()
        self.stat_dirty()
        self.plain_status()
        self.assertTrue(self.marker.exists(), "premise: plain git status runs the submodule's clean filter")
        self.marker.unlink()
        self.assert_refused_and_never_ran("symbolic link")

    def test_a_gitfile_pointing_outside_git_modules_is_refused_and_its_program_never_runs(self):
        self.gitdir_outside_modules()
        self.stat_dirty()
        self.plain_status()
        self.assertTrue(self.marker.exists(), "premise: plain git status follows the gitfile and runs the filter")
        self.marker.unlink()
        self.assert_refused_and_never_ran("outside .git/modules")

    def test_a_filter_in_the_regular_submodule_config_is_still_refused(self):
        with self.config.open("a") as handle:
            handle.write(self.evil)
        self.assert_refused_and_never_ran("filter")

    def test_a_filter_included_conditionally_for_the_submodule_is_refused(self):
        extra = self.base / "extra.conf"
        extra.write_text(self.evil)
        with self.config.open("a") as handle:
            handle.write(f'[includeIf "gitdir:{self.config.parent}/"]\n\tpath = {extra}\n')
        self.assert_refused_and_never_ran("conditional include|filter")

    def test_a_fifo_in_place_of_the_submodule_config_is_refused_without_reading_it(self):
        self.config.unlink()
        os.mkfifo(self.config)
        self.assert_refused_and_never_ran("not a regular file")

    def test_an_unreadable_submodule_config_is_refused(self):
        self.config.write_text("[core\n\tbroken")
        self.assert_refused_and_never_ran("cannot be read|cannot resolve")

    def test_a_symlinked_submodule_git_marker_is_refused(self):
        gitfile = self.root / "sub/.git"
        text = gitfile.read_text()
        (self.base / "gitfile").write_text(text.replace("gitdir: ../", f"gitdir: {self.root}/"))
        gitfile.unlink()
        gitfile.symlink_to(self.base / "gitfile")
        self.assert_refused_and_never_ran("link")

    def test_a_submodule_at_another_commit_is_refused_although_status_ignores_submodules(self):
        sub = self.root / "sub"
        (sub / "b.txt").write_text("untested\n")
        run_git(sub, "add", "b.txt")
        run_git(sub, "commit", "-qm", "untested")
        with self.assertRaisesRegex(ValueError, "recorded commit"):
            self.target()

    def test_an_unpopulated_submodule_passes(self):
        run_git(self.root, "submodule", "--quiet", "deinit", "-f", "sub")
        self.assertEqual(self.target()["repository"], REPOSITORY)

    def test_status_never_enters_a_submodule_even_if_the_guard_were_bypassed(self):
        self.symlinked_config()
        self.stat_dirty()
        with mock.patch.object(sdk, "checkout_guard", lambda root: None):
            self.assertEqual(self.target()["repository"], REPOSITORY)
        self.assertFalse(self.marker.exists(), "target() status recursed into the submodule")

    def test_read_only_release_eligibility_never_runs_the_planted_program(self):
        for plant in (self.symlinked_config, self.gitdir_outside_modules):
            with self.subTest(plant=plant.__name__):
                self.setUp()
                plant()
                self.stat_dirty()
                state = self.base / "state"
                state.mkdir(mode=0o700)
                self.assertEqual(control_plane.describe("master-release")["actions"]["eligibility"]["side_effect"],
                                 "none")
                grant = {"grant_id": "g-f1-release-read", "role": "release-engineer",
                         "engines": {"master-release": ["eligibility"]}, "paths": [str(self.root)],
                         "max_side_effect": "none", "expires_at": "2099-01-01T00:00:00Z", "approvals": []}
                payload = {"root": str(self.root), "evidence": {}, "repository": REPOSITORY, "team": TEAM,
                           "project": PROJECT, "commit": self.commit}
                with self.assertRaisesRegex(control_plane.ControlPlaneError, "symbolic link|outside .git/modules"):
                    control_plane.invoke("master-release", "eligibility", payload, grant=grant,
                                         ctx={"state_dir": str(state)})
                self.assertFalse(self.marker.exists(), "a side_effect none eligibility check ran the program")


if __name__ == "__main__":
    unittest.main()
