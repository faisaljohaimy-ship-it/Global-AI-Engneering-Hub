"""recheck-release item 2: a look-alike or non-ASCII host never normalises to a registered repository.

workspace_policy.REMOTE was compiled with re.IGNORECASE but not re.ASCII, so Unicode case folding let the i of
github match U+0131 (dotless i) and U+0130 (dotted capital I), and the s of ssh. match U+017F (long s):
_repo_id('https://g\\u0131thub.com/<owner>/<repo>') gave the registered id and _linked_workspace granted a
write scope to a worktree whose fetch and push origin was that look-alike host. _repo_id also folded the
path with str.casefold, so an owner spelled with U+017F folded into the registered owner. REMOTE now folds
ASCII only, _repo_id refuses any remote whose host is not plain ASCII (Python's IDNA codec, like Git's, maps
some of these spellings to github.com, so "not GitHub" would be wrong as well) and folds only ASCII letters
of the path. SYNTHETIC local repositories in a temporary directory; no network.
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
    spec = importlib.util.spec_from_file_location("gaie_recheck_repo_id_spellings", ROOT / "tests/test_recheck_fixes_repo_id.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SLUG, module.SPELLINGS


SLUG, SPELLINGS = _spellings()
OWNER, NAME = SLUG.split("/")
LOOK_ALIKE_HOSTS = {
    "dotless i U+0131": "gıthub.com",
    "dotted capital I U+0130": "gİthub.com",
    "Cyrillic i U+0456": "gіthub.com",
    "Greek iota U+03B9": "gιthub.com",
    "Greek upsilon U+03C5": "gυthub.com",
    "full-width letters": "ｇｉｔｈｕｂ.com",
    "full-width capitals": "ＧＩＴＨＵＢ.COM",
    "full-width dot": "github．com",
    "long s in ssh.": "ſsh.github.com",
    "combining dot on i": "gi̇thub.com",
    "soft hyphen": "git­hub.com",
}
PROXY_LOOK_ALIKE = f"http://local_proxy@localhoſt:8080/git/{SLUG}"
# The parent's pattern: Unicode case folding.
UNICODE_REMOTE = re.compile(workspace_policy.REMOTE.pattern, re.IGNORECASE)


def forms(host):
    return {"https": f"https://{host}/{SLUG}.git", "https with user": f"https://git@{host}/{SLUG}",
            "ssh": f"ssh://git@{host}/{SLUG}.git", "scp": f"git@{host}:{SLUG}.git", "scp without user": f"{host}:{SLUG}"}


def git(path, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="Fixture",
               GIT_AUTHOR_EMAIL="fixture@example.invalid", GIT_COMMITTER_NAME="Fixture",
               GIT_COMMITTER_EMAIL="fixture@example.invalid")
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=env).stdout


class LookAlikeHosts(unittest.TestCase):
    def test_look_alike_and_non_ascii_hosts_never_match(self):
        for label, host in LOOK_ALIKE_HOSTS.items():
            for form, url in forms(host).items():
                with self.subTest(host=label, form=form):
                    self.assertIsNone(workspace_policy.REMOTE.fullmatch(url))
                    with self.assertRaisesRegex(WorkspacePolicyError, "not plain ASCII"):
                        _repo_id(url)
        with self.assertRaisesRegex(WorkspacePolicyError, "not plain ASCII"):
            _repo_id(PROXY_LOOK_ALIKE)
        self.assertIsNone(workspace_policy.REMOTE.fullmatch(PROXY_LOOK_ALIKE))

    def test_the_parent_pattern_matched_the_homoglyphs(self):
        """Premise: Unicode case folding is what matched (re.IGNORECASE without re.ASCII)."""
        for host in ("gıthub.com", "gİthub.com", "ſsh.github.com"):
            with self.subTest(host=host):
                self.assertTrue(UNICODE_REMOTE.fullmatch(f"https://{host}/{SLUG}"))
        self.assertTrue(UNICODE_REMOTE.fullmatch(PROXY_LOOK_ALIKE))

    def test_idna_and_punycode_forms(self):
        """The IDNA (punycode) form of a look-alike is an ASCII host that is not GitHub: no match, None. Some
        non-ASCII spellings encode to github.com itself, which is why a non-ASCII host is refused, not None."""
        to_github = set()
        for label, host in LOOK_ALIKE_HOSTS.items():
            try:
                encoded = host.encode("idna").decode("ascii")
            except UnicodeError:
                continue  # Python's IDNA 2003 codec refuses it; Git would not reach GitHub with it either
            if encoded.casefold() in ("github.com", "ssh.github.com"):
                to_github.add(label)
                continue
            for form, url in forms(encoded).items():
                with self.subTest(host=label, idna=encoded, form=form):
                    self.assertTrue(encoded.startswith("xn--"))
                    self.assertIsNone(workspace_policy.REMOTE.fullmatch(url))
                    self.assertIsNone(_repo_id(url))
        self.assertTrue({"full-width letters", "full-width dot", "long s in ssh."} <= to_github, to_github)
        for url in (f"https://xn--github-qyd.com/{SLUG}", *forms("XN--GTHUB-N4A.COM").values()):
            with self.subTest(url=url):
                self.assertIsNone(_repo_id(url))

    def test_a_non_ascii_owner_or_name_never_folds_into_a_registered_one(self):
        """str.casefold turned U+017F into s and U+212A (Kelvin sign) into k; only ASCII letters fold now."""
        long_s = OWNER.replace("s", "ſ", 1)
        self.assertEqual(long_s.casefold(), OWNER, "premise: casefold folds the look-alike into the owner")
        for url in (f"https://github.com/{long_s}/{NAME}", f"git@github.com:{long_s}/{NAME}.git",
                    f"https://github.com/{OWNER}/{NAME.replace('i', chr(0x130), 1)}", "https://github.com/owner/Key"):
            with self.subTest(url=url):
                with self.assertRaises(WorkspacePolicyError):
                    _repo_id(url)
        self.assertEqual(_repo_id("https://github.com/OWNER/KEY.GIT"), "owner/key")

    def test_the_19_registered_spellings_still_match(self):
        self.assertEqual(len(SPELLINGS), 19)
        for label, url in SPELLINGS.items():
            with self.subTest(form=label):
                self.assertTrue(workspace_policy.REMOTE.fullmatch(url))
                self.assertEqual(_repo_id(url), SLUG)

    def test_non_ascii_user_info_and_local_paths_keep_their_meaning(self):
        self.assertEqual(_repo_id(f"https://fäisal@github.com/{SLUG}.git"), SLUG)
        self.assertEqual(_repo_id(f"fäisal@github.com:{SLUG}"), SLUG)
        for value in ("../مشروع/repo.git", "/srv/مشروع.git",
                      "file:///srv/م.git", "öwner/demo"):
            with self.subTest(value=value):
                self.assertIsNone(_repo_id(value))

    def test_each_layer_alone_refuses_a_look_alike(self):
        url = f"https://gıthub.com/{SLUG}"
        with mock.patch.object(workspace_policy, "REMOTE", UNICODE_REMOTE):  # the explicit host check alone
            with self.assertRaisesRegex(WorkspacePolicyError, "not plain ASCII"):
                _repo_id(url)
        with mock.patch.object(workspace_policy, "AUTHORITY", re.compile(r"(?!)")):  # re.ASCII alone
            self.assertIsNone(_repo_id(url))
        with mock.patch.object(workspace_policy, "REMOTE", UNICODE_REMOTE), \
                mock.patch.object(workspace_policy, "AUTHORITY", re.compile(r"(?!)")):
            self.assertEqual(_repo_id(url), SLUG, "control: with both layers removed the homoglyph matches")


class LookAlikeOriginGetsNoWriteScope(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ra-", dir="/tmp" if os.path.isdir("/tmp") else None)
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
        git(source, "worktree", "add", "-qb", f"codex/gaie-upgrade-ra{self.count}", str(work))
        work.chmod(0o700)
        return work

    def test_a_look_alike_fetch_or_push_origin_is_refused_a_write_scope(self):
        look_alike = f"https://gıthub.com/{SLUG}.git"
        for fetch, push in ((look_alike, None), (f"https://github.com/{SLUG}.git", look_alike),
                            (f"git@gİthub.com:{SLUG}.git", None), (f"https://ｇｉｔｈｕｂ.com/{SLUG}", None)):
            with self.subTest(fetch=fetch, push=push):
                work = self.worktree(fetch, push)
                with self.assertRaisesRegex(WorkspacePolicyError, "single matching registered fetch and push origin"):
                    validate_workspace(work, intent="upgrade", expected_repository=f"https://github.com/{SLUG}")
        control = self.worktree(f"https://GitHub.com/{SLUG}.git")
        scope = validate_workspace(control, intent="upgrade", expected_repository=f"https://github.com/{SLUG}")
        self.assertEqual(scope.checkout, control)

    def test_the_upgrade_route_never_takes_a_look_alike_worktree_for_the_registered_project(self):
        work = self.worktree(f"https://gıthub.com/{SLUG}.git")
        with self.assertRaises((upgrade_engine.UpgradeError, WorkspacePolicyError)):
            upgrade_engine.route_command("upgrade the system", environ=self.environ, workspace=str(work))
        control = upgrade_engine.route_command("upgrade the system", environ=self.environ,
                                               workspace=str(self.worktree(f"https://github.com/{SLUG}.git")))
        self.assertEqual((control["project"], control["target_resolution"]), ("biz-pulse-ar", "registered-project-origin"))


if __name__ == "__main__":
    unittest.main()
