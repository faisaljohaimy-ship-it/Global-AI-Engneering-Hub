"""Review fix pr30-authz F3: the registered-project rule of the upgrade engine no longer depends on wording.

route_command accepted a command that did not name a registered project exactly (a near miss the router
itself flags with suggestions, or no project name at all) as an explicit local target, even on that
project's own default-branch checkout. Now a plan with suggestions is refused, and a target whose Git
remotes belong to a registered project is accepted only as that project's verified linked worktree.
Synthetic local repositories; no network.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import upgrade_engine as engine  # noqa: E402
from engineering_os.upgrade_engine import UpgradeError  # noqa: E402

SADEED = "https://github.com/faisaljohaimy-ship-it/biz-pulse-ar.git"
FIXTURE = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
NEAR_MISSES = ("upgrade Sadeedd", "upgrade Sаdeed", "upgrade Sade​ed", "upgrade biz-pulse", "طور سديدد",
               "audit Sadeedd", "افحص سديدد", "upgrade Wow-buss")
UNNAMED = (("upgrade the system", "upgrade"), ("fix the app", "upgrade"), ("طور النظام", "upgrade"),
           ("طور سدید", "upgrade"), ("audit the system", "audit"))


class RegisteredTargetIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-f3-")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.environ = {"GAIE_HOME": str(self.base / "gaie-home")}

    def git(self, path, *args):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)

    def checkout(self, name, origin, remote="origin"):
        checkout = self.base / f"{name}-canonical"
        checkout.mkdir(mode=0o700)
        self.git(checkout, "init", "-q", "-b", "main")
        (checkout / "app.py").write_text("def f():\n    return 1\n")
        self.git(checkout, "add", "-A")
        self.git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "base")
        self.git(checkout, "remote", "add", remote, origin)
        self.git(checkout, "update-ref", f"refs/remotes/{remote}/main", "HEAD")
        self.git(checkout, "symbolic-ref", f"refs/remotes/{remote}/HEAD", f"refs/remotes/{remote}/main")
        return checkout

    def worktree(self, checkout, name):
        worktree = self.base / f"{name}-worktree"
        self.git(checkout, "worktree", "add", "-qb", f"codex/gaie-upgrade-{name}", str(worktree))
        worktree.chmod(0o700)
        return worktree

    def route(self, command, workspace):
        return engine.route_command(command, environ=self.environ, workspace=workspace)

    def refused(self, command, workspace, message):
        with self.assertRaises(UpgradeError) as caught:
            self.route(command, workspace)
        self.assertIn(message, str(caught.exception))

    def test_near_miss_names_are_refused_on_every_target(self):
        checkout = self.checkout("sadeed", SADEED)
        worktree = self.worktree(checkout, "sadeed")
        plain = self.base / "plain"
        shutil.copytree(FIXTURE, plain)
        for command in NEAR_MISSES:
            for target in (checkout, worktree, plain, None):
                with self.subTest(command=command, target=getattr(target, "name", None)):
                    self.refused(command, target, "resembles the registered project")

    def test_an_unnamed_command_on_a_registered_projects_own_checkout_is_refused(self):
        checkout = self.checkout("sadeed", SADEED)
        for command, _ in UNNAMED:
            with self.subTest(command=command):
                self.refused(command, checkout, "checkout of the registered project 'biz-pulse-ar'")
        (checkout / "src").mkdir()
        (checkout / "src" / "main.py").write_text("print(1)\n")
        self.refused("upgrade the system", checkout / "src", "checkout of the registered project")  # a folder inside it

    def test_another_remote_name_or_url_form_does_not_hide_the_registered_repository(self):
        for name, origin, remote in (("ssh", "git@github.com:faisaljohaimy-ship-it/biz-pulse-ar.git", "origin"),
                                     ("upstream", SADEED, "upstream"),
                                     ("cased", "https://github.com/FaisalJohaimy-Ship-It/Biz-Pulse-AR", "origin")):
            with self.subTest(remote=name):
                self.refused("upgrade the system", self.checkout(name, origin, remote), "registered project 'biz-pulse-ar'")

    def test_the_verified_worktree_is_accepted_as_that_project(self):
        worktree = self.worktree(self.checkout("sadeed", SADEED), "sadeed")
        for command, mode in UNNAMED:
            with self.subTest(command=command):
                route = self.route(command, worktree)
                self.assertEqual((route["mode"], route["project"], route["target_resolution"]),
                                 (mode, "biz-pulse-ar", "registered-project-origin"))
        (worktree / "untracked.txt").write_text("local edit\n")
        self.refused("upgrade the system", worktree, "not its verified isolated checkout")
        self.assertEqual(self.route("audit the system", worktree)["project"], "biz-pulse-ar")

    def test_unregistered_targets_keep_the_explicit_local_target(self):
        foreign = self.checkout("other", "https://github.com/example/another-project.git")
        plain = self.base / "plain"
        shutil.copytree(FIXTURE, plain)
        for target in (foreign, plain, FIXTURE, None):
            for command, mode in UNNAMED:
                with self.subTest(target=getattr(target, "name", None), command=command):
                    route = self.route(command, target)
                    self.assertEqual((route["mode"], route["project"], route["target_resolution"]),
                                     (mode, None, "explicit-local-target"))

    def test_a_focus_word_close_to_a_project_alias_is_not_a_near_miss(self):
        plain = self.base / "plain"
        shutil.copytree(FIXTURE, plain)
        checkout = self.checkout("sadeed", SADEED)
        for command in ("upgrade the security of the task system", "upgrade security", "طور أمان نظام إدارة المهام"):
            with self.subTest(command=command):
                route = self.route(command, plain)  # "security" is close to the "security lab" alias
                self.assertEqual((route["scope"], route["focus"], route["project"]), ("focused", ["security"], None))
                self.refused(command, checkout, "checkout of the registered project 'biz-pulse-ar'")

    def test_the_exactly_named_project_still_follows_the_worktree_rule(self):
        checkout = self.checkout("sadeed", SADEED)
        worktree = self.worktree(checkout, "sadeed")
        self.assertEqual(self.route("upgrade Sadeed", worktree)["target_resolution"], "registered-project")
        self.refused("upgrade Sadeed", checkout, "not its verified isolated checkout")


if __name__ == "__main__":
    unittest.main()
