"""recheck-release-2 N2 in gaie_router.remote_slug: user info that Git ends before the @ is not GitHub.

remote_slug's user info [^/@\\s]+@ accepted ? # and \\, so https://evil.example?@github.com/<owner>/<repo> and
http://evil.example?@127.0.0.1:<port>/git/<owner>/<repo> gave the registered owner/name although Git and libcurl
end the authority at ? and # and contact evil.example. The user info now excludes / ? # @ \\, whitespace and
control characters. Pure string checks; no network.
"""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import gaie_router as router  # noqa: E402

SLUG = "faisaljohaimy-ship-it/biz-pulse-ar"
AT = chr(64)  # joined at run time: no e-mail- or credential-shaped literal in this file
DELIMITED = [f"https://evil.example{mark}{AT}github.com/{SLUG}" for mark in ("?", "#", "\\", "\t", "\x01", "x?y")] + [
    f"http://evil.example{mark}{AT}{host}/git/{SLUG}" for mark in ("?", "#", "\\")
    for host in ("127.0.0.1:9", "localhost", "localhost:8080")] + [
    f"https://evil.example:443?{AT}github.com/{SLUG}.git", f"https://a{AT}evil.example{AT}github.com/{SLUG}"]
KEPT = [f"https://github.com/{SLUG}.git", "git" + f"{AT}github.com:{SLUG}.git", f"http://local_proxy{AT}127.0.0.1:9/git/{SLUG}",
        "https://x-access-token" + f"{AT}github.com/{SLUG}", f"https://evil.example%3F{AT}github.com/{SLUG}",
        f"https://evil.example;{AT}github.com/{SLUG}"]
OLD_USER_INFO = r"(?:[^/@\s]+@)?"


class RemoteSlugUserInfo(unittest.TestCase):
    def test_user_info_git_ends_before_the_at_sign_is_not_github(self):
        for url in DELIMITED:
            with self.subTest(url=url):
                self.assertIsNone(router.remote_slug(url))

    def test_the_parent_pattern_matched_the_delimited_forms(self):
        """Premise: with the old user info, ? # and \\ before the @ gave the registered slug."""
        old = [re.compile(pattern.pattern.replace(router._USER_INFO, OLD_USER_INFO, 1)) for pattern in router.REMOTES]
        self.assertTrue(all(o.pattern != p.pattern for o, p in zip(old, router.REMOTES)))
        for url in (DELIMITED[0], DELIMITED[1], DELIMITED[2], DELIMITED[6]):
            with self.subTest(url=url):
                self.assertTrue(any(pattern.fullmatch(url) for pattern in old))

    def test_github_and_proxy_remotes_still_give_their_slug(self):
        for url in KEPT:
            with self.subTest(url=url):
                self.assertEqual(router.remote_slug(url), SLUG)
        for url in (f"https://gitlab.com/{SLUG}.git", f"https://evil.example/@github.com/{SLUG}",
                    f"https://github.com.evil.example/{SLUG}"):
            with self.subTest(url=url):
                self.assertIsNone(router.remote_slug(url))


if __name__ == "__main__":
    unittest.main()
