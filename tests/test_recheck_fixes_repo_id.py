"""recheck-authz F3: every spelling Git accepts for a registered GitHub repository names that project.

workspace_policy._repo_id recognised only three exact GitHub prefixes, so an origin spelled with the host
in capitals, user info, a www. host or ssh:// with :22 gave None and the registered project's own
default-branch checkout was accepted as an unrelated explicit local target. _repo_id now normalises host
case, user info, www./ssh. hosts, a trailing dot, default ports, the scp and ssh:// forms, a .git suffix
and a trailing slash, and refuses a GitHub remote it cannot reduce to exactly one owner/name.
Synthetic local repositories; no network.
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import upgrade_engine, workspace_policy  # noqa: E402
from engineering_os.workspace_policy import WorkspacePolicyError, _repo_id  # noqa: E402

SLUG = "faisaljohaimy-ship-it/biz-pulse-ar"
# Remotes with user info are joined at run time so this file holds no credential-shaped URL.
SPELLINGS = {  # every form names the registered project biz-pulse-ar
    "canonical https": f"https://github.com/{SLUG}",
    "host in capitals": f"https://GitHub.com/{SLUG}.git",
    "user in https URL": f"https://faisal@github.com/{SLUG}.git",
    "user and token in https URL": "https://x-access-token:" + "secret-value" + f"@github.com/{SLUG}",
    "www host": f"https://www.github.com/{SLUG}",
    "ssh with default port": f"ssh://git@github.com:22/{SLUG}.git",
    "ssh without user": f"ssh://github.com/{SLUG}",
    "ssh.github.com on 443": f"ssh://git@ssh.github.com:443/{SLUG}.git",
    "git+ssh scheme": f"git+ssh://git@github.com/{SLUG}",
    "https default port": f"https://github.com:443/{SLUG}",
    "http": f"http://github.com/{SLUG}",
    "git protocol": f"git://github.com/{SLUG}.git",
    "scp form": f"git@github.com:{SLUG}.git",
    "scp form without user, capitals": f"GITHUB.COM:{SLUG}",
    "scheme in capitals": f"HTTPS://github.com/{SLUG}",
    "trailing dot host and slash": f"https://github.com./{SLUG}/",
    ".git suffix in capitals": f"https://github.com/{SLUG}.GIT",
    "owner and name in capitals": "https://github.com/FaisalJohaimy-Ship-It/Biz-Pulse-AR",
    "local Git proxy": f"http://local_proxy@127.0.0.1:8080/git/{SLUG}",
}
UNPARSEABLE_GITHUB = ("https://github.com:8443/" + SLUG, "ssh://git@github.com:2222/" + SLUG, "ftp://github.com/" + SLUG,
                      "https://github.com/faisaljohaimy-ship-it", f"https://github.com/{SLUG}/tree/main",
                      f"https://github.com//{SLUG}", f"https://github.com/{SLUG}?tab=readme",
                      "https://github.com/faisaljohaimy-ship-it/biz-pulse-%61r", f"git@github.com:/{SLUG}",
                      "https://user:" + "secret-value" + "@github.com:9999/" + SLUG)
OTHER_HOSTS = (f"https://gitlab.com/{SLUG}", f"https://github.com.evil.example/{SLUG}", f"https://github.com@evil.example/{SLUG}",
               f"file:///srv/git/{SLUG}.git", f"/srv/git/{SLUG}.git", f"https://evil.example/@github.com/{SLUG}")


def git(path, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="Fixture",
               GIT_AUTHOR_EMAIL="fixture@example.invalid", GIT_COMMITTER_NAME="Fixture",
               GIT_COMMITTER_EMAIL="fixture@example.invalid")
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=env).stdout


class RepoIdSpellings(unittest.TestCase):
    def test_every_spelling_of_the_registered_repository_gives_its_id(self):
        for label, url in SPELLINGS.items():
            with self.subTest(form=label):
                self.assertEqual(_repo_id(url), SLUG)
                self.assertTrue(workspace_policy.REMOTE.fullmatch(url), "a GitHub or proxy remote")

    def test_a_github_remote_that_is_not_one_repository_on_its_default_port_is_refused(self):
        for url in UNPARSEABLE_GITHUB:
            with self.subTest(url=url):
                with self.assertRaises(WorkspacePolicyError) as caught:
                    _repo_id(url)
                self.assertNotIn("secret-value", str(caught.exception), "the remote's user info is never echoed")

    def test_other_hosts_and_local_paths_are_not_github(self):
        for url in OTHER_HOSTS:
            with self.subTest(url=url):
                self.assertIsNone(_repo_id(url))
        self.assertEqual((_repo_id("owner/demo"), _repo_id(None), _repo_id("not a repository")), ("owner/demo", None, None))


class RegisteredCheckoutInEveryForm(unittest.TestCase):
    """The PoC of the re-check: the registered project's own default-branch checkout, origin in each form."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rf3-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.environ = {"GAIE_HOME": str(self.base / "gaie-home")}
        self.count = 0

    def checkout(self, origin):
        self.count += 1
        checkout = self.base / f"co{self.count}"
        checkout.mkdir(mode=0o700)
        git(checkout, "init", "-q", "-b", "main")
        (checkout / "app.py").write_text("def f():\n    return 1\n")
        git(checkout, "add", "-A")
        git(checkout, "commit", "-qm", "base")
        if origin is not None:
            git(checkout, "remote", "add", "origin", origin)
            git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
            git(checkout, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        return checkout

    def route(self, command, workspace):
        return upgrade_engine.route_command(command, environ=self.environ, workspace=str(workspace))

    def test_the_default_branch_checkout_is_refused_in_every_spelling(self):
        for label, url in SPELLINGS.items():
            checkout = self.checkout(url)
            for command in ("upgrade the system", "audit the system"):
                with self.subTest(form=label, command=command), self.assertRaises(upgrade_engine.UpgradeError) as caught:
                    self.route(command, checkout)
                self.assertIn("registered project 'biz-pulse-ar' but not its verified isolated checkout", str(caught.exception))

    def test_an_unparseable_github_origin_is_refused_not_accepted_as_a_local_target(self):
        for url in UNPARSEABLE_GITHUB[:3]:
            checkout = self.checkout(url)
            with self.subTest(url=url), self.assertRaises((upgrade_engine.UpgradeError, WorkspacePolicyError)):
                self.route("upgrade the system", checkout)

    def test_the_verified_linked_worktree_is_accepted_in_another_spelling(self):
        checkout = self.checkout(SPELLINGS["host in capitals"])
        worktree = self.base / "wt"
        git(checkout, "worktree", "add", "-qb", "codex/gaie-upgrade-rf3", str(worktree))
        worktree.chmod(0o700)
        route = self.route("upgrade the system", worktree)
        self.assertEqual((route["project"], route["target_resolution"]), ("biz-pulse-ar", "registered-project-origin"))

    def test_controls_no_remote_and_another_repository_stay_explicit_local_targets(self):
        for origin in (None, "https://GitHub.com/example/another-project.git", "git@gitlab.com:" + SLUG):
            with self.subTest(origin=origin):
                route = self.route("upgrade the system", self.checkout(origin))
                self.assertEqual((route["project"], route["target_resolution"]), (None, "explicit-local-target"))


if __name__ == "__main__":
    unittest.main()
