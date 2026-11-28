"""pr30-isolation F2: Git metadata a strict child plants in its writable root never runs on the host.

The strict governor overlays only an existing <root>/.git pointer read-only. A child can still create
<root>/.git (a build workspace, a registered_path root, any subdirectory) or a bare-repository-shaped
directory whose config names core.fsmonitor, a hook or a filter. The supervisor now re-inspects the
writable root after every run and reports the run as failed without removing anything, and the build
engine's Git helper neither runs such programs nor works in a repository whose config names them.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import build_engine, governor
from engineering_os.workspace_policy import WorkspacePolicyError, WorkspaceSupervisor, WorkspaceTaintedError

ROOT = pathlib.Path(__file__).resolve().parents[1]
FULL = governor.isolation_probe()["tier"] == "full"
CLEAN_ENV = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
                          env={**CLEAN_ENV, "HOME": str(path)}).stdout.strip()


def plain_git(path, *args):
    """The operator's ordinary Git, without any of the hub's hardening."""
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=60,
                          env={**CLEAN_ENV, "HOME": str(path)})


class Base(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-f2-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.marker = self.base / "host-program-ran"

    def private(self, name):
        path = self.base / name
        path.mkdir(mode=0o700)
        return path

    def linked(self):
        source = self.private("source")
        git(source, "init", "--quiet", "--initial-branch=main")
        (source / "src").mkdir(mode=0o700)
        (source / "src" / "demo.txt").write_text("fixture")
        git(source, "add", "src/demo.txt")
        git(source, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "f")
        git(source, "remote", "add", "origin", "https://github.com/owner/demo.git")
        git(source, "update-ref", "refs/remotes/origin/main", git(source, "rev-parse", "HEAD"))
        git(source, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        work = self.base / "work"
        git(source, "worktree", "add", "--quiet", "-b", "codex/review", str(work))
        work.chmod(0o700)
        (work / "src").chmod(0o700)
        return work

    def plant_repository(self, directory):
        """What a child can do with the git binary visible in /usr: init and name a host program."""
        git(directory, "init", "--quiet")
        git(directory, "config", "core.fsmonitor", f"touch {self.marker}; false")


class SupervisorRescanTests(Base):
    def planting(self, plant):
        def launch(cmd, *, cwd, **kwargs):
            plant(pathlib.Path(cwd))
            return {"returncode": 0, "stdout": "planted\n", "stderr": "", "limit": None,
                    "fs_isolated": True, "network_isolated": True}
        return mock.patch.object(governor, "sandbox_run", side_effect=launch)

    def assert_tainted(self, supervisor, agent, plant, left_behind):
        with self.planting(plant), self.assertRaisesRegex(WorkspaceTaintedError, "run is failed") as caught:
            supervisor.run(agent, ["/bin/true"], timeout=5)
        self.assertIsInstance(caught.exception, WorkspacePolicyError)
        self.assertEqual(caught.exception.result["returncode"], 0)
        self.assertTrue(os.path.lexists(left_behind), "nothing is quarantined or removed silently")
        with mock.patch.object(governor, "sandbox_run") as launch, self.assertRaises(WorkspacePolicyError):
            supervisor.run(agent, ["/bin/true"], timeout=5)
        launch.assert_not_called()
        self.assertFalse(self.marker.exists())

    def test_git_planted_at_a_build_root_fails_the_run(self):
        build = self.private("build")
        supervisor = WorkspaceSupervisor({"builder": {"path": build, "intent": "build"}})
        self.assert_tainted(supervisor, "builder", self.plant_repository, build / ".git")

    def test_git_planted_in_a_registered_path_root_fails_the_run(self):
        work = self.linked()
        supervisor = WorkspaceSupervisor({"dev": {"path": work, "intent": "upgrade", "expected_repository": "owner/demo",
                                                  "registered_path": "src"}})
        self.assert_tainted(supervisor, "dev", self.plant_repository, work / "src" / ".git")

    def test_nested_and_bare_shaped_repositories_fail_the_run(self):
        def nested(root):
            (root / "deep" / "er").mkdir(parents=True)
            self.plant_repository(root / "deep" / "er")

        def bare(root):
            (root / "store").mkdir()
            git(root / "store", "init", "--bare", "--quiet")

        def common_dir(root):  # HEAD plus a commondir file pointing at directories elsewhere in the tree
            (root / "alias").mkdir()
            (root / "alias" / "HEAD").write_text("ref: refs/heads/main\n")
            (root / "alias" / "commondir").write_text("../store\n")

        def git_file(root):
            (root / "pkg").mkdir()
            (root / "pkg" / ".GIT").write_text("gitdir: /elsewhere\n")

        for name, plant, left in (("nested", nested, "deep/er/.git"), ("bare", bare, "store/HEAD"),
                                  ("commondir", common_dir, "alias/commondir"), ("gitfile", git_file, "pkg/.GIT")):
            with self.subTest(name):
                build = self.private(f"build-{name}")
                supervisor = WorkspaceSupervisor({"builder": {"path": build, "intent": "build"}})
                self.assert_tainted(supervisor, "builder", plant, build / left)

    def test_an_ordinary_write_still_succeeds(self):
        build = self.private("build")
        supervisor = WorkspaceSupervisor({"builder": {"path": build, "intent": "build"}})
        with self.planting(lambda root: (root / "HEAD.md").write_text("notes")):
            self.assertEqual(supervisor.run("builder", ["/bin/true"], timeout=5)["returncode"], 0)

    @unittest.skipUnless(FULL, "needs the full namespace sandbox to run a real strict child")
    def test_real_strict_child_planting_git_is_reported_and_never_runs(self):
        build = self.private("build")
        supervisor = WorkspaceSupervisor({"builder": {"path": build, "intent": "build"}})
        child = (f"git init -q . && git config core.fsmonitor 'touch {self.marker}; false' && "
                 f"printf '#!/bin/sh\\ntouch {self.marker}\\n' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push")
        with self.assertRaises(WorkspaceTaintedError) as caught:
            supervisor.run("builder", ["/bin/sh", "-c", child], timeout=20)
        self.assertEqual(caught.exception.result["returncode"], 0, caught.exception.result["stderr"])
        self.assertTrue((build / ".git" / "config").is_file())
        self.assertFalse(self.marker.exists())
        self.assertTrue(plain_git(build, "status", "--porcelain").returncode == 0 and self.marker.exists(),
                        "premise: the operator's plain git status would run the planted program")
        self.marker.unlink()
        build_engine._git(build, "status", "--porcelain")
        self.assertFalse(self.marker.exists())

    @unittest.skipUnless(FULL, "needs the full namespace sandbox to run a real strict child")
    def test_hub_workspace_run_reports_failed_status(self):
        build = self.private("build")
        assignments = self.base / "assignments.json"
        assignments.write_text(json.dumps({"builder": {"path": str(build), "intent": "build"}}))
        assignments.chmod(0o600)
        done = subprocess.run([sys.executable, "-B", str(ROOT / "hub.py"), "workspace-run", "--assignments",
                               str(assignments), "--agent", "builder", "--timeout", "20", "--", "/bin/sh", "-c",
                               "mkdir -p x/refs x/objects && echo 'ref: refs/heads/main' > x/HEAD"],
                              capture_output=True, text=True, timeout=120, env={**os.environ, "TMPDIR": "/tmp"})
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual((report["status"], report["result"]["returncode"]), ("failed", 0))
        self.assertIn("shaped like a Git repository", report["reason"])


class BuildEngineGitTests(Base):
    def setUp(self):
        super().setUp()
        self.repo = self.private("app")
        self.plant_repository(self.repo)
        (self.repo / "a.txt").write_text("x")
        git(self.repo, "add", "a.txt")
        git(self.repo, "-c", "user.name=f", "-c", "user.email=f@example.invalid", "commit", "--quiet", "-m", "f")
        self.marker.unlink(missing_ok=True)

    def test_planted_fsmonitor_and_hooks_do_not_run(self):
        self.assertEqual(plain_git(self.repo, "status", "--porcelain").returncode, 0)
        self.assertTrue(self.marker.exists(), "premise: plain git status runs core.fsmonitor here")
        self.marker.unlink()
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text(f"#!/bin/sh\ntouch {self.marker}\n")
        hook.chmod(0o700)
        (self.repo / "b.txt").write_text("y")
        build_engine._git(self.repo, "status", "--porcelain")
        build_engine._git(self.repo, "add", "--all")
        build_engine._git(self.repo, "commit", "--quiet", "-m", "second")
        self.assertFalse(self.marker.exists())

    def test_repository_config_naming_programs_is_refused_before_git_runs(self):
        git(self.repo, "config", "--unset", "core.fsmonitor")
        (self.repo / ".gitattributes").write_text("* filter=probe\n")
        git(self.repo, "add", ".gitattributes")
        git(self.repo, "-c", "user.name=f", "-c", "user.email=f@example.invalid", "commit", "--quiet", "-m", "attr")
        git(self.repo, "config", "filter.probe.clean", f"sh -c 'touch {self.marker}; cat'")
        os.utime(self.repo / "a.txt", (1, 1))
        plain_git(self.repo, "status", "--porcelain")
        self.assertTrue(self.marker.exists(), "premise: plain git status runs a clean filter on a stat-dirty file")
        self.marker.unlink()
        os.utime(self.repo / "a.txt", (2, 2))
        with self.assertRaisesRegex(build_engine.BuildError, "git refused"):
            build_engine._git(self.repo, "status", "--porcelain")
        git(self.repo, "config", "--unset", "filter.probe.clean")
        for key, value in (("remote.lazy.promisor", "true"), ("credential.helper", "!false"),
                           ("http.sslVerify", "false"), (f"remote.{self.base}/remote.git.receivepack", "false"),
                           ("url.ext::.pushInsteadOf", "https://"), ("protocol.file.allow", "always")):
            with self.subTest(key=key):
                git(self.repo, "config", key, value)
                with self.assertRaisesRegex(build_engine.BuildError, "git refused"):
                    build_engine._git(self.repo, "rev-parse", "HEAD")
                git(self.repo, "config", "--unset", key)
        self.assertFalse(self.marker.exists())
        self.assertEqual(build_engine._git(self.repo, "rev-parse", "HEAD").returncode, 0)

    def test_only_a_push_reaches_a_transport_and_only_its_own(self):
        bare = self.base / "remote.git"
        git(self.base, "init", "--bare", "--quiet", str(bare))
        fetched = build_engine._git(self.repo, "fetch", str(bare), check=False)
        self.assertNotEqual(fetched.returncode, 0)
        self.assertIn("not allowed", fetched.stderr)
        pushed = build_engine._git(self.repo, "push", "--porcelain", str(bare), "HEAD:refs/heads/main", check=False)
        self.assertEqual(pushed.returncode, 0, pushed.stderr)
        sneaky = build_engine._git(self.repo, "push", "--porcelain", f"file://{bare}", "HEAD:refs/heads/other",
                                   check=False)
        self.assertNotEqual(sneaky.returncode, 0)


if __name__ == "__main__":
    unittest.main()
