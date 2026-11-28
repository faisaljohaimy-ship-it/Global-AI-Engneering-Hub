"""recheck-release-2 N1: a promisor remote with no name or an empty name is a partial clone too.

sdk.engineering_sdk.PARTIAL_CLONE_SETTING needed a non-empty remote name (remote\\..+\\.promisor), but Git 2.43
also makes a promisor remote of `[remote] promisor = true` (key remote.promisor) and of `[remote ""]` (key
remote..promisor). checkout_guard passed such a checkout, and the release engine said ELIGIBLE and wrote a
record that verify-record called VERIFIED; the planted program did not run only because GIT_NO_LAZY_FETCH=1
and GIT_ALLOW_PROTOCOL="" held. The pattern now takes an empty or absent name, so checkout_guard and all four
release actions refuse first. Each planted case first shows that plain Git runs the program, so a pass is not
an inert fixture. SYNTHETIC repositories in a temporary directory; no network.
"""
import copy
import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import release_engine as engine  # noqa: E402
from sdk import engineering_sdk as sdk  # noqa: E402

PARTIAL = "partial clone"
HEADERS = {"no remote name": "[remote]", "empty remote name": '[remote ""]', "no remote name, upper case": "[REMOTE]"}
# The parent's pattern: a remote name of at least one character.
NAMED_ONLY = re.compile(r"extensions\.partialclone|remote\..+\.(?:promisor|partialclonefilter)", re.I | re.A | re.S)


def fixture():
    name = "gaie_release_scenario_g_fixture"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "tests/fixtures/release/scenario_g.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


F = fixture()


class NamelessPromisorRemote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = pathlib.Path(tempfile.mkdtemp(prefix="rfs-", dir="/tmp" if os.path.isdir("/tmp") else None))
        cls.addClassCleanup(shutil.rmtree, cls.scratch, ignore_errors=True)
        cls.template = F.build(cls.scratch / "t")
        cls.count = 0

    def checkout(self):
        type(self).count += 1
        here = self.scratch / f"c{self.count}"
        here.mkdir()
        f = F.copy_fixture(self.template, here)
        F.fixture_git(f["repo"], "update-index", "-q", "--refresh")
        f["log"] = here / "ran.log"
        f["program"] = here / "planted.sh"
        f["program"].write_text(f"#!/bin/sh\necho \"$0 $*\" >> '{f['log']}'\nexit 1\n")
        f["program"].chmod(0o755)
        f["here"] = here
        return f

    def plant(self, f, header):
        """The reviewer's PoC nosub_promisor_engine.py: a nameless promisor remote whose URL insteadOf
        rewrites to ext::<program>, the ext transport allowed, and the base commit's object missing."""
        repo = f["repo"]
        base = F.fixture_git(repo, "rev-parse", "HEAD~1").strip()
        with open(repo / ".git/config", "a") as config:
            config.write(f'{header}\n\tpromisor = true\n[url "ext::{f["program"]}"]\n\tinsteadOf = ""\n'
                         '[protocol "ext"]\n\tallow = always\n')
        (repo / ".git/objects" / base[:2] / base[2:]).unlink()
        return base

    def payload(self, f, **change):
        return dict({"root": str(f["repo"]), "profile": copy.deepcopy(F.PROFILE), **F.inputs(f, commit=f["tested"])},
                    **change)

    def plain_merge_base(self, f, base):
        env = {"PATH": os.defpath, "HOME": str(f["here"]), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "LC_ALL": "C"}
        subprocess.run(["git", "-C", str(f["repo"]), "merge-base", "--is-ancestor", base, "HEAD"], capture_output=True,
                       env=env, stdin=subprocess.DEVNULL, timeout=60)

    def test_every_release_action_refuses_a_nameless_promisor_and_nothing_runs(self):
        for label, header in HEADERS.items():
            with self.subTest(form=label):
                f = self.checkout()
                first = f["here"] / "first.json"
                written = engine.engine("record", self.payload(f, now=F.NOW, out=str(first)), {})
                self.assertEqual((written["decision"], written["refusals"]), ("ELIGIBLE", []))
                base = self.plant(f, header)
                keys = sdk._keys(sdk.git(f["repo"], "config", "--list", "--show-scope", "-z"), {"local"})
                self.assertTrue(any(key.lower() in ("remote.promisor", "remote..promisor") for key in keys), keys)
                with self.assertRaisesRegex(ValueError, PARTIAL):
                    sdk.checkout_guard(f["repo"])
                later = f["here"] / "later.json"
                results = {"eligibility": engine.engine("eligibility", self.payload(f), {}),
                           "eligibility with the missing base": engine.engine("eligibility", self.payload(f, base=base), {}),
                           "plan": engine.engine("plan", self.payload(f, now=F.NOW), {}),
                           "record": engine.engine("record", self.payload(f, now=F.NOW, out=str(later)), {}),
                           "verify-record": engine.engine("verify-record", {"root": str(f["repo"]),
                                                                            "profile": copy.deepcopy(F.PROFILE),
                                                                            "record_path": str(first)}, {})}
                for action, result in results.items():
                    rows = result["refusals"] if "refusals" in result else result["reasons"]
                    self.assertEqual([row["code"] for row in rows], ["checkout-unsafe"], (label, action))
                    self.assertIn(PARTIAL, rows[0]["detail"], (label, action))
                self.assertIsNone(results["record"]["written"])
                self.assertFalse(later.exists())
                self.assertEqual(results["verify-record"]["status"], "UNVERIFIED")
                self.assertFalse(f["log"].exists(), f["log"].read_text() if f["log"].exists() else "")
                self.plain_merge_base(f, base)
                self.assertTrue(f["log"].exists(), "control: plain `git merge-base` lazy-fetches and runs the program")

    def test_the_parent_pattern_let_the_nameless_promisor_through(self):
        """Premise: with the named-only pattern checkout_guard passes and eligibility says ELIGIBLE; the
        offline Git (GIT_NO_LAZY_FETCH, GIT_ALLOW_PROTOCOL) is then the only layer, and it holds."""
        for label, header in HEADERS.items():
            with self.subTest(form=label):
                f = self.checkout()
                self.plant(f, header)
                with mock.patch.object(sdk, "PARTIAL_CLONE_SETTING", NAMED_ONLY):
                    self.assertIsNone(sdk.checkout_guard(f["repo"]))
                    result = engine.engine("eligibility", self.payload(f), {})
                self.assertEqual((result["decision"], result["refusals"]), ("ELIGIBLE", []))
                self.assertFalse(f["log"].exists())

    def test_the_pattern_matches_nameless_keys_and_not_look_alikes(self):
        for key in ("remote.promisor", "remote..promisor", "Remote.Promisor", "remote.partialclonefilter",
                    "remote..partialCloneFilter", "remote.origin.promisor", "remote.a.b.promisor", "extensions.partialClone"):
            with self.subTest(key=key):
                self.assertTrue(sdk.PARTIAL_CLONE_SETTING.fullmatch(key))
        for key in ("remote.promisor.url", "remote.partialclonefilter.fetch", "branch.partialclone.remote",
                    "remote.pushdefault", "remotes.promisor", "xremote.promisor", "remote.promisorx"):
            with self.subTest(key=key):
                self.assertIsNone(sdk.PARTIAL_CLONE_SETTING.fullmatch(key))


if __name__ == "__main__":
    unittest.main()
