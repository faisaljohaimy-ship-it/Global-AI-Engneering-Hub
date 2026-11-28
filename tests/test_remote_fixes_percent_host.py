"""recheck-release-2 N3: a percent-encoded remote host is refused, never taken for "not GitHub".

workspace_policy._repo_id returned None for https://github%2ecom/<owner>/<repo> and %67ithub.com, while libcurl
(https, http) and Git's own ssh:// and git:// parser decode the host and contact github.com/<owner>/<repo>.
upgrade_engine.route_command therefore accepted the registered project's own default-branch checkout with such
an origin as an unrelated explicit local target, which the canonical origin refuses. _repo_id now refuses any
remote whose host or port holds a %; a % in the user info keeps its meaning. SYNTHETIC local repositories in a
temporary directory; no network. Which host Git contacts was measured offline with a recording 127.0.0.1 proxy
(Git 2.43.0, libcurl 8.5.0); that run is not part of this test.
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
from engineering_os.workspace_policy import WorkspacePolicyError, _repo_id, validate_workspace  # noqa: E402

SLUG = "faisaljohaimy-ship-it/biz-pulse-ar"
AT = chr(64)  # remotes with user info are joined at run time: no e-mail- or credential-shaped literal here
PERCENT_HOSTS = ("github%2ecom", "%67ithub.com", "github%2Ecom", "www%2egithub.com", "ssh.github%2ecom",
                 "github.com%2e", "%47%49%54%48%55%42.com", "evil.example%40github.com")


def forms(host):
    return {"https": f"https://{host}/{SLUG}.git", "http": f"http://{host}/{SLUG}", "https with user": f"https://git{AT}{host}/{SLUG}",
            "ssh": f"ssh://git{AT}{host}/{SLUG}.git", "git": f"git://{host}/{SLUG}", "scp": f"git{AT}{host}:{SLUG}.git"}


PERCENT_REMOTES = {f"{host} [{form}]": url for host in PERCENT_HOSTS for form, url in forms(host).items()}
PERCENT_REMOTES.update({"percent-encoded port": f"https://github.com:%34%34%33/{SLUG}",
                        "percent in the local proxy host": f"http://local_proxy{AT}127.0.0.%31:8080/git/{SLUG}",
                        "percent host, unrelated path": "https://gitlab%2ecom/example/another-project.git"})
# A % in the user info is the user's; Git contacts github.com (measured), so these keep the registered id.
USER_INFO = (f"https://git%2ehub{AT}github.com/{SLUG}.git", f"https://evil%40example{AT}github.com/{SLUG}",
             f"ssh://git%2e{AT}github.com/{SLUG}.git", f"git%2e{AT}github.com:{SLUG}.git")


def git(path, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="Fixture",
               GIT_AUTHOR_EMAIL="fixture" + AT + "example.invalid", GIT_COMMITTER_NAME="Fixture",
               GIT_COMMITTER_EMAIL="fixture" + AT + "example.invalid")
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=env).stdout


class PercentEncodedHost(unittest.TestCase):
    def test_a_percent_encoded_host_or_port_is_refused(self):
        for label, url in PERCENT_REMOTES.items():
            with self.subTest(form=label):
                with self.assertRaises(WorkspacePolicyError) as caught:
                    _repo_id(url)
                self.assertNotIn("%", str(caught.exception), "the remote is never echoed")

    def test_the_encoded_host_decodes_to_github(self):
        """Premise of the PoC: the decoded host is GitHub, so None ("not GitHub") was wrong."""
        from urllib.parse import unquote
        for host in PERCENT_HOSTS[:6]:
            with self.subTest(host=host):
                self.assertIn(unquote(host).lower().rstrip("."), ("github.com", "www.github.com", "ssh.github.com"))

    def test_a_percent_in_the_user_info_keeps_its_meaning(self):
        for url in USER_INFO:
            with self.subTest(url=url):
                self.assertEqual(_repo_id(url), SLUG)

    def test_a_percent_in_a_local_path_or_plain_name_is_not_a_host(self):
        for value in (f"/srv/git/%67ithub/{SLUG}.git", f"file:///srv/git/%67ithub.com/{SLUG}.git", "owner%2f/demo"):
            with self.subTest(value=value):
                self.assertIsNone(_repo_id(value))


class PercentHostCheckouts(unittest.TestCase):
    """The reviewer's PoC: the registered project's own checkouts with a percent-encoded origin."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rfp-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.environ = {"GAIE_HOME": str(self.base / "gaie-home")}
        self.count = 0

    def checkout(self, origin):
        self.count += 1
        checkout = self.base / f"c{self.count}"
        checkout.mkdir(mode=0o700)
        git(checkout, "init", "-q", "-b", "main")
        (checkout / "app.py").write_text("def f():\n    return 1\n")
        git(checkout, "add", "-A")
        git(checkout, "commit", "-qm", "base")
        git(checkout, "remote", "add", "origin", origin)
        git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(checkout, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        return checkout

    def route(self, workspace):
        return upgrade_engine.route_command("upgrade the system", environ=self.environ, workspace=str(workspace))

    def test_the_default_branch_checkout_is_not_an_explicit_local_target(self):
        for url in (PERCENT_REMOTES["github%2ecom [https]"], PERCENT_REMOTES["%67ithub.com [https]"],
                    PERCENT_REMOTES["github%2Ecom [ssh]"]):
            with self.subTest(url=url), self.assertRaisesRegex(upgrade_engine.UpgradeError, "cannot be ruled out"):
                self.route(self.checkout(url))
        with self.assertRaisesRegex(upgrade_engine.UpgradeError, "but not its verified isolated checkout"):
            self.route(self.checkout(f"https://github.com/{SLUG}.git"))  # control: the canonical origin
        unrelated = self.route(self.checkout("https://GitHub.com/example/another-project.git"))
        self.assertEqual((unrelated["project"], unrelated["target_resolution"]), (None, "explicit-local-target"))

    def test_a_linked_worktree_with_a_percent_host_gets_no_write_scope(self):
        source = self.checkout(PERCENT_REMOTES["github%2ecom [https]"])
        work = self.base / "wt"
        git(source, "worktree", "add", "-qb", "codex/gaie-upgrade-rfp", str(work))
        work.chmod(0o700)
        with self.assertRaisesRegex(WorkspacePolicyError, "single matching registered fetch and push origin"):
            validate_workspace(work, intent="upgrade", expected_repository=f"https://github.com/{SLUG}")
        self.assertIsNone(workspace_policy.REMOTE.fullmatch(PERCENT_REMOTES["github%2ecom [https]"]))


if __name__ == "__main__":
    unittest.main()
