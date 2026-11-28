"""recheck-release-2 N2: a URL whose authority Git and libcurl end before the @ never names a registered project.

workspace_policy.REMOTE accepted any user info without / or whitespace, so it also swallowed ? and #. For
libcurl and Git those end the authority: https://evil.example?@github.com/<owner>/<repo> (or #@, or
http://evil.example:80?@...) normalised to the registered owner/name, validate_workspace granted a write scope
to a worktree with that fetch and push origin and upgrade_engine.route_command took it for the registered
project, while Git fetched from and pushed to evil.example. The user info of REMOTE now excludes / ? # @ \\,
whitespace and control characters, and _repo_id refuses any URL authority that holds ?, #, a backslash,
whitespace, a control character or a second @. Each layer alone holds. SYNTHETIC local repositories in a
temporary directory; no network. Which host Git contacts for each spelling was measured offline with a
recording 127.0.0.1 proxy (Git 2.43.0, libcurl 8.5.0); that run is not part of this test.
"""
import importlib.util
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import upgrade_engine, workspace_policy  # noqa: E402
from engineering_os.workspace_policy import WorkspacePolicyError, _repo_id, validate_workspace  # noqa: E402


def _spellings():
    spec = importlib.util.spec_from_file_location("gaie_remote_fixes_spellings", ROOT / "tests/test_recheck_fixes_repo_id.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SLUG, module.SPELLINGS


SLUG, SPELLINGS = _spellings()
AT = chr(64)  # remotes with user info are joined at run time: no e-mail- or credential-shaped literal here
GH = f"{AT}github.com/{SLUG}"
# Git and libcurl end the authority before the @, or the host is ambiguous: refused.
AMBIGUOUS = {
    "? before @ (https)": f"https://evil.example?{GH}.git",
    "# before @ (https)": f"https://evil.example#{GH}.git",
    "? before @ with port (http)": f"http://evil.example:80?{GH}",
    "? before @ (http)": f"http://evil.example?{GH}",
    "# before @ (http)": f"http://evil.example#{GH}",
    "? before @ (ssh)": f"ssh://evil.example?{GH}.git",
    "# before @ (git)": f"git://evil.example#{GH}",
    "? in a password": "https://x-access-token:" + "abc?def" + f"{GH}",
    "backslash before @": f"https://evil.example\\{GH}",
    "two @": f"http://a{AT}evil.example{GH}",
    "two @ (ssh)": f"ssh://git{AT}evil.example{GH}.git",
    "tab before @": f"http://evil.example\t{GH}",
    "space before @ (ssh)": f"ssh://evil example{GH}",
    "control character before @": f"https://evil.example\x01{GH}",
    "? after the host": f"https://github.com?{AT}/{SLUG}",
    "# after the host": f"https://github.com#/{SLUG}",
    "? in the local proxy authority": f"http://local_proxy{AT}127.0.0.1:8080?{AT}x/git/{SLUG}",
}
# Git contacts github.com/<owner>/<repo> for these (measured), so they name the registered project.
SAME_REPOSITORY = {
    "; before @ (libcurl login options)": f"http://evil.example;{GH}",
    "%40 in user info": f"https://evil%40example{GH}.git",
    "%3F in user info": f"https://evil.example%3F{GH}.git",
    "%23 in user info": f"https://evil.example%23{GH}",
    "? in the scp user": f"evil.example?{AT}github.com:{SLUG}.git",
    "# in the scp user": f"evil.example#{AT}github.com:{SLUG}.git",
}
# A ? or # after the first / is not part of the authority.
PATH_QUERY = (f"https://github.com/{SLUG}?x{AT}y", f"https://gitlab.com/{SLUG}?x{AT}github.com/a")
# bfdc87f's user info, the source of N2.
OLD_REMOTE = re.compile(workspace_policy.REMOTE.pattern.replace(r"(?:[^/?#@\\\s\x00-\x1f\x7f]*@)?", r"(?:[^/\s]*@)?"),
                        re.IGNORECASE | re.ASCII)


def outcome(url):
    try:
        return _repo_id(url)
    except WorkspacePolicyError:
        return "refused"


def git(path, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="Fixture",
               GIT_AUTHOR_EMAIL="fixture" + AT + "example.invalid", GIT_COMMITTER_NAME="Fixture",
               GIT_COMMITTER_EMAIL="fixture" + AT + "example.invalid")
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=env).stdout


class AuthorityDelimiters(unittest.TestCase):
    def test_an_authority_git_ends_before_the_at_sign_is_refused(self):
        for label, url in AMBIGUOUS.items():
            with self.subTest(form=label):
                self.assertIsNone(workspace_policy.REMOTE.fullmatch(url))
                with self.assertRaisesRegex(WorkspacePolicyError, "authority") as caught:
                    _repo_id(url)
                self.assertNotIn("abc?def", str(caught.exception), "the remote's user info is never echoed")
                self.assertNotIn("evil", str(caught.exception))

    def test_the_parent_pattern_matched_the_delimited_forms(self):
        """Premise: bfdc87f's user info [^/\\s]*@ swallowed ? and # (the reviewer's three PoC forms)."""
        for label in ("? before @ (https)", "# before @ (https)", "? before @ with port (http)"):
            with self.subTest(form=label):
                self.assertTrue(OLD_REMOTE.fullmatch(AMBIGUOUS[label]))
        self.assertNotEqual(OLD_REMOTE.pattern, workspace_policy.REMOTE.pattern)

    def test_each_layer_alone_refuses_a_delimited_authority(self):
        never = re.compile(r"(?!)")
        for label, url in AMBIGUOUS.items():
            with self.subTest(form=label):
                with mock.patch.object(workspace_policy, "REMOTE", OLD_REMOTE):  # the authority check alone
                    with self.assertRaisesRegex(WorkspacePolicyError, "authority"):
                        _repo_id(url)
                with mock.patch.object(workspace_policy, "URL_AUTHORITY_DELIMITERS", never):  # REMOTE alone
                    self.assertNotEqual(outcome(url), SLUG)
        with mock.patch.object(workspace_policy, "REMOTE", OLD_REMOTE), \
                mock.patch.object(workspace_policy, "URL_AUTHORITY_DELIMITERS", never):
            self.assertEqual(_repo_id(AMBIGUOUS["? before @ (https)"]), SLUG, "control: with both layers removed it matches")

    def test_user_info_git_strips_still_names_the_repository(self):
        for label, url in SAME_REPOSITORY.items():
            with self.subTest(form=label):
                self.assertTrue(workspace_policy.REMOTE.fullmatch(url))
                self.assertEqual(_repo_id(url), SLUG)

    def test_a_query_or_fragment_in_the_path_is_not_the_authority(self):
        with self.assertRaisesRegex(WorkspacePolicyError, "not exactly one owner/name"):
            _repo_id(PATH_QUERY[0])  # unchanged: a GitHub URL with a query is not one repository
        self.assertIsNone(_repo_id(PATH_QUERY[1]))

    def test_the_19_registered_spellings_still_match(self):
        self.assertEqual(len(SPELLINGS), 19)
        for label, url in SPELLINGS.items():
            with self.subTest(form=label):
                self.assertTrue(workspace_policy.REMOTE.fullmatch(url))
                self.assertEqual(_repo_id(url), SLUG)


class DelimitedOriginGetsNoWriteScope(unittest.TestCase):
    """The reviewer's PoC: a linked worktree whose fetch or push origin is a delimited look-alike."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rfa-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.environ = {"GAIE_HOME": str(self.base / "gaie-home")}
        self.count = 0

    def worktree(self, fetch, push=None):
        self.count += 1
        source = self.base / f"s{self.count}"
        source.mkdir(mode=0o700)
        git(source, "init", "-q", "-b", "main")
        (source / "app.py").write_text("def f():\n    return 1\n")
        git(source, "add", "-A")
        git(source, "commit", "-qm", "base")
        git(source, "remote", "add", "origin", fetch)
        if push:
            git(source, "remote", "set-url", "--push", "origin", push)
        git(source, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(source, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        work = self.base / f"w{self.count}"
        git(source, "worktree", "add", "-qb", f"codex/gaie-upgrade-rfa{self.count}", str(work))
        work.chmod(0o700)
        return work

    def test_a_delimited_fetch_or_push_origin_is_refused_a_write_scope(self):
        canonical = f"https://github.com/{SLUG}.git"
        poc = [AMBIGUOUS[label] for label in ("? before @ (https)", "# before @ (https)", "? before @ with port (http)")]
        for fetch, push in [*((url, None) for url in poc), (canonical, poc[0]), (AMBIGUOUS["two @"], None)]:
            with self.subTest(fetch=fetch, push=push):
                work = self.worktree(fetch, push)
                with self.assertRaisesRegex(WorkspacePolicyError, "single matching registered fetch and push origin"):
                    validate_workspace(work, intent="upgrade", expected_repository=f"https://github.com/{SLUG}")
        control = self.worktree(canonical)
        scope = validate_workspace(control, intent="upgrade", expected_repository=f"https://github.com/{SLUG}")
        self.assertEqual(scope.checkout, control)

    def test_the_upgrade_route_never_takes_a_delimited_worktree_for_the_registered_project(self):
        for label in ("? before @ (https)", "# before @ (https)", "? before @ with port (http)"):
            work = self.worktree(AMBIGUOUS[label])
            with self.subTest(form=label), self.assertRaisesRegex(upgrade_engine.UpgradeError, "cannot be ruled out"):
                upgrade_engine.route_command("upgrade the system", environ=self.environ, workspace=str(work))
        control = upgrade_engine.route_command("upgrade the system", environ=self.environ,
                                               workspace=str(self.worktree(f"https://github.com/{SLUG}.git")))
        self.assertEqual((control["project"], control["target_resolution"]), ("biz-pulse-ar", "registered-project-origin"))


if __name__ == "__main__":
    unittest.main()
