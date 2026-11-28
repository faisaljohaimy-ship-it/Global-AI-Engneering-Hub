"""recheck-release item 1: a partial clone never fetches during checkout_guard or a release check.

checkout_guard's `git ls-files -v --stage` on a sparse-index checkout whose tree object is missing started a
lazy fetch from the promisor remote and ran the program named in remote.origin.uploadpack, during the
read-only eligibility, plan, record and verify-record actions: the release engine's own Git runner was
offline, sdk.engineering_sdk.git was not. sdk.engineering_sdk.git now runs with GIT_NO_LAZY_FETCH=1,
GIT_ALLOW_PROTOCOL="" (which overrides protocol.<name>.allow in the checkout), -c protocol.allow=never,
fsmonitor, hooks and the untracked cache off, no system or global config, GIT_* scrubbed and stdin closed;
and checkout_guard refuses a partial clone from its config before any command that reads the index.
Each planted case first shows that plain Git runs the program, so a pass is not an inert fixture.
SYNTHETIC repositories in a temporary directory; no network.
"""
import copy
import importlib.util
import os
import pathlib
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
ACTIONS = ("eligibility", "plan", "record", "verify-record")


def fixture():
    name = "gaie_release_scenario_g_fixture"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "tests/fixtures/release/scenario_g.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


F = fixture()


def plain_ls_files(repo, home):
    """What checkout_guard used to run, with the checkout's own settings and nothing hardened."""
    env = {"PATH": os.defpath, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
    subprocess.run(["git", "-C", str(repo), "ls-files", "-v", "--stage", "-z"], stdin=subprocess.DEVNULL,
                   capture_output=True, env=env, timeout=60)


class PartialCloneNeverFetches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = pathlib.Path(tempfile.mkdtemp(prefix="rp-", dir="/tmp" if os.path.isdir("/tmp") else None))
        cls.addClassCleanup(shutil.rmtree, cls.scratch, ignore_errors=True)
        cls.template = F.build(cls.scratch / "t")
        cls.count = 0

    def checkout(self):
        type(self).count += 1
        here = self.scratch / f"c{self.count}"
        here.mkdir()
        f = F.copy_fixture(self.template, here)
        F.fixture_git(f["repo"], "update-index", "-q", "--refresh")  # the copy changed every file's stat data
        f["log"] = here / "ran.log"
        f["program"] = here / "planted.sh"
        f["program"].write_text(f"#!/bin/sh\necho \"$0 $*\" >> '{f['log']}'\nexit 1\n")
        f["program"].chmod(0o755)
        f["here"] = here
        return f

    def plant(self, f, route="uploadpack"):
        """The reviewer's PoC: a sparse index, a promisor remote and a missing tree object.
        route 'uploadpack': remote.origin.uploadpack names the program (file transport);
        route 'ext': the remote URL is ext::<program> and the checkout allows the ext and every protocol."""
        repo, G = f["repo"], F.fixture_git
        G(repo, "sparse-checkout", "init", "--cone", "--sparse-index")
        G(repo, "config", "index.sparse", "true")
        G(repo, "sparse-checkout", "reapply")
        tree = G(repo, "rev-parse", "HEAD:pkg").strip()
        G(repo, "config", "core.repositoryformatversion", "1")
        G(repo, "config", "extensions.partialClone", "origin")
        G(repo, "config", "remote.origin.promisor", "true")
        if route == "uploadpack":
            G(repo, "config", "remote.origin.uploadpack", str(f["program"]))
        else:
            G(repo, "config", "remote.origin.url", f"ext::{f['program']}")
            G(repo, "config", "protocol.ext.allow", "always")
            G(repo, "config", "protocol.allow", "always")
        (repo / ".git/objects" / tree[:2] / tree[2:]).unlink()
        self.assertIn("040000", G(repo, "ls-files", "--sparse", "--stage", "pkg"), "pkg is a sparse directory entry")

    def payload(self, f, **change):
        return dict({"root": str(f["repo"]), "profile": copy.deepcopy(F.PROFILE), **F.inputs(f, commit=f["tested"])},
                    **change)

    def run_all(self, f, record_path):
        type(self).count += 1
        later = f["here"] / f"later{self.count}.json"
        results = {"eligibility": engine.engine("eligibility", self.payload(f), {}),
                   "plan": engine.engine("plan", self.payload(f, now=F.NOW), {}),
                   "record": engine.engine("record", self.payload(f, now=F.NOW, out=str(later)), {}),
                   "verify-record": engine.engine("verify-record", {"root": str(f["repo"]),
                                                                    "profile": copy.deepcopy(F.PROFILE),
                                                                    "record_path": str(record_path)}, {})}
        self.assertFalse(f["log"].exists(), f"a planted program ran: {f['log'].read_text() if f['log'].exists() else ''}")
        return results

    def test_reviewer_poc_is_refused_by_every_release_action_and_the_program_never_runs(self):
        for route in ("uploadpack", "ext"):
            with self.subTest(route=route):
                f = self.checkout()
                first = f["here"] / "first.json"
                written = engine.engine("record", self.payload(f, now=F.NOW, out=str(first)), {})
                self.assertEqual((written["decision"], written["refusals"]), ("ELIGIBLE", []))
                self.plant(f, route)
                with self.assertRaisesRegex(ValueError, PARTIAL):
                    sdk.checkout_guard(f["repo"])
                self.assertFalse(f["log"].exists())
                results = self.run_all(f, first)
                self.assertEqual([results[name]["decision"] for name in ACTIONS[:3]], ["REFUSED"] * 3)
                self.assertIsNone(results["record"]["written"])
                self.assertEqual(results["verify-record"]["status"], "UNVERIFIED")
                for action, result in results.items():
                    rows = result["refusals"] if "refusals" in result else result["reasons"]
                    self.assertEqual([row["code"] for row in rows], ["checkout-unsafe"], (route, action))
                    self.assertIn(PARTIAL, rows[0]["detail"], (route, action))
                plain_ls_files(f["repo"], f["here"])
                self.assertTrue(f["log"].exists(), "control: plain `git ls-files --stage` runs the program")

    def test_the_hardened_git_alone_never_fetches(self):
        """With the config refusal bypassed, sdk.git still starts no transport: checkout_guard gets past
        `ls-files` (and refuses the sparse checkout's skip-worktree entries) without running the program."""
        for route in ("uploadpack", "ext"):
            with self.subTest(route=route):
                f = self.checkout()
                self.plant(f, route)
                with mock.patch.object(sdk, "_refuse_partial_clone", lambda keys: None):
                    sdk.git(f["repo"], "ls-files", "-v", "--stage", "-z")
                    with self.assertRaisesRegex(ValueError, "skip-worktree"):
                        sdk.checkout_guard(f["repo"])
                    result = engine.engine("eligibility", self.payload(f), {})
                self.assertEqual([row["code"] for row in result["refusals"]], ["checkout-unsafe"])
                self.assertFalse(f["log"].exists(), f["log"].read_text() if f["log"].exists() else "")
                plain_ls_files(f["repo"], f["here"])
                self.assertTrue(f["log"].exists(), "control: plain `git ls-files --stage` runs the program")

    def test_allow_protocol_overrides_the_checkouts_protocol_settings(self):
        """protocol.allow=never on the command line loses to the checkout's protocol.ext.allow=always;
        GIT_ALLOW_PROTOCOL="" does not, even when lazy fetching is allowed."""
        f = self.checkout()
        self.plant(f, "ext")
        without_lazy_flag = {key: value for key, value in sdk.GIT_ENV.items() if key != "GIT_NO_LAZY_FETCH"}
        with mock.patch.object(sdk, "GIT_ENV", without_lazy_flag):
            sdk.git(f["repo"], "ls-files", "-v", "--stage", "-z")
        self.assertFalse(f["log"].exists(), "GIT_ALLOW_PROTOCOL='' blocks the ext transport")
        neither = {key: value for key, value in without_lazy_flag.items() if key != "GIT_ALLOW_PROTOCOL"}
        with mock.patch.object(sdk, "GIT_ENV", neither):
            sdk.git(f["repo"], "ls-files", "-v", "--stage", "-z")
        self.assertTrue(f["log"].exists(), "control: the -c protocol.allow=never flag alone does not stop it")

    def test_each_partial_clone_setting_is_refused_before_the_index_is_read(self):
        def configure(f, change):
            repo = f["repo"]
            if change == "extension":
                F.fixture_git(repo, "config", "core.repositoryformatversion", "1")
                F.fixture_git(repo, "config", "extensions.partialClone", "origin")
            elif change == "promisor":
                F.fixture_git(repo, "config", "remote.origin.promisor", "true")
            elif change == "filter":
                F.fixture_git(repo, "config", "remote.origin.partialCloneFilter", "blob:none")
            elif change == "mixed-case remote":
                F.fixture_git(repo, "config", "remote.UpStream.url", str(f["origin"]))
                F.fixture_git(repo, "config", "remote.UpStream.Promisor", "false")
            elif change == "include":
                included = f["here"] / "included.cfg"
                included.write_text("[remote \"origin\"]\n\tpromisor = true\n")
                F.fixture_git(repo, "config", "include.path", str(included))
            elif change == "worktree config":
                F.fixture_git(repo, "config", "extensions.worktreeConfig", "true")
                (repo / ".git/config.worktree").write_text("[remote \"origin\"]\n\tpartialclonefilter = blob:none\n")
            elif change == "submodule config":
                module = repo / ".git/modules/sub"
                module.mkdir(parents=True)
                (module / "HEAD").write_text("ref: refs/heads/main\n")
                (module / "config").write_text("[extensions]\n\tpartialClone = origin\n")
        for change in ("extension", "promisor", "filter", "mixed-case remote", "include", "worktree config",
                       "submodule config"):
            with self.subTest(change=change):
                f = self.checkout()
                configure(f, change)
                calls = []
                real = sdk.git

                def recording(root, *args):
                    calls.append(args[0])
                    return real(root, *args)
                with mock.patch.object(sdk, "git", recording), self.assertRaisesRegex(ValueError, PARTIAL):
                    sdk.checkout_guard(f["repo"])
                self.assertNotIn("ls-files", calls, change)
                self.assertEqual(calls[0], "config", "the config is the first thing read")
                if change != "submodule config":
                    self.assertEqual(calls, ["config"], "refused before any other Git command")
                result = engine.engine("eligibility", self.payload(f), {})
                self.assertEqual([row["code"] for row in result["refusals"]], ["checkout-unsafe"], change)

    def test_a_full_clone_and_look_alike_keys_still_pass(self):
        f = self.checkout()
        repo = f["repo"]
        F.fixture_git(repo, "config", "remote.promisor.url", str(f["origin"]))  # a remote named "promisor"
        F.fixture_git(repo, "config", "branch.partialclone.remote", "origin")
        F.fixture_git(repo, "config", "extensions.worktreeConfig", "true")
        self.assertIsNone(sdk.checkout_guard(repo))
        result = engine.engine("eligibility", self.payload(f), {})
        self.assertEqual((result["decision"], result["refusals"]), ("ELIGIBLE", []))

    def test_git_runs_offline_without_inherited_settings_global_config_or_stdin(self):
        f = self.checkout()
        repo, home = f["repo"], f["here"] / "home"
        home.mkdir()
        (home / ".gitconfig").write_text("[protocol \"ext\"]\n\tallow = always\n")
        hostile = {"HOME": str(home), "GIT_ALLOW_PROTOCOL": "ext:file", "GIT_NO_LAZY_FETCH": "0",
                   "GIT_CONFIG_PARAMETERS": "'protocol.allow'='always'", "GIT_DIR": str(f["here"]),
                   "GIT_CONFIG_GLOBAL": str(home / ".gitconfig")}
        with mock.patch.dict(os.environ, hostile):
            listing = sdk.git(repo, "config", "--list", "--show-scope", "-z")
            seen = {}

            def capture(argv, **kwargs):
                seen.update(argv=argv, **kwargs)
                return subprocess.CompletedProcess(argv, 0, b"", b"")
            with mock.patch.object(sdk.subprocess, "run", capture):
                sdk.git(repo, "rev-parse", "HEAD")
        scopes = set(listing.split("\0")[::2]) - {""}
        self.assertEqual(scopes, {"command", "local"}, "no global or system config, no inherited -c settings")
        self.assertNotIn("protocol.ext.allow", listing)
        env = seen["env"]
        self.assertEqual((env["GIT_ALLOW_PROTOCOL"], env["GIT_NO_LAZY_FETCH"], env["GIT_CONFIG_GLOBAL"],
                          env["GIT_CONFIG_NOSYSTEM"], env["GIT_OPTIONAL_LOCKS"], env["GIT_TERMINAL_PROMPT"]),
                         ("", "1", os.devnull, "1", "0", "0"))
        self.assertNotIn("GIT_DIR", env)
        self.assertNotIn("GIT_CONFIG_PARAMETERS", env)
        self.assertIs(seen["stdin"], subprocess.DEVNULL)
        for flag in ("protocol.allow=never", "core.fsmonitor=false", "core.hooksPath=/dev/null",
                     "core.untrackedCache=false", "--no-pager"):
            self.assertIn(flag, seen["argv"])


if __name__ == "__main__":
    unittest.main()
