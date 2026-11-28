"""recheck-authz F1 (release engine part): no program planted in a checkout runs during a release check.

A plain `git status` recursed into a nested submodule (sub/nested) whose Git directory sits outside
.git/modules, or is embedded in its folder, and ran the filter program configured there, although
`eligibility` is read-only. Every Git call of the release engine now carries the flags of
`sdk.engineering_sdk.target` (status never enters a submodule; hooks, fsmonitor and the untracked
cache off; no system or global config; no transport) and re-checks that the checkout's own config
names no filter program. Each case first shows that the planted program does run under a plain
`git status`, so a pass is not an inert fixture. SYNTHETIC repositories in a temporary directory.
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


def fixture():
    name = "gaie_release_scenario_g_fixture"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "tests/fixtures/release/scenario_g.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


F = fixture()
SUBMODULE = ("-c", "protocol.file.allow=always", "submodule", "--quiet")


def plain_status(repo, home):
    """What the engine used to run: `git status` with the checkout's own settings and a user HOME."""
    env = {"PATH": os.defpath, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
    subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=normal"],
                   capture_output=True, env=env, timeout=60)


class PlantedProgramsNeverRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = pathlib.Path(tempfile.mkdtemp(prefix="rf1-", dir="/tmp" if os.path.isdir("/tmp") else None))
        cls.addClassCleanup(shutil.rmtree, cls.scratch, ignore_errors=True)
        cls.template = F.build(cls.scratch / "t")
        cls.count = 0

    def checkout(self, nested=True):
        """A copy of the Scenario G repository with a submodule `sub` that has its own submodule `nested`."""
        type(self).count += 1
        here = self.scratch / f"c{self.count}"
        here.mkdir()
        f = F.copy_fixture(self.template, here)
        nested_src, sub_src = here / "nestedsrc", here / "subsrc"
        for path in (nested_src, sub_src):
            path.mkdir()
            F.fixture_git(path, "init", "-q", "-b", "main")
        (nested_src / "a.txt").write_text("hello\n")
        (nested_src / ".gitattributes").write_text("* filter=evil\n")
        F.fixture_git(nested_src, "add", "-A")
        F.fixture_git(nested_src, "commit", "-qm", "nested")
        (sub_src / "s.txt").write_text("s\n")
        F.fixture_git(sub_src, "add", "-A")
        F.fixture_git(sub_src, "commit", "-qm", "s")
        if nested:
            F.fixture_git(sub_src, *SUBMODULE, "add", str(nested_src), "nested")
            F.fixture_git(sub_src, "commit", "-qm", "add nested")
        F.fixture_git(f["repo"], *SUBMODULE, "add", str(sub_src), "sub")
        F.fixture_git(f["repo"], *SUBMODULE, "update", "--init", "--recursive")
        F.fixture_git(f["repo"], "commit", "-qm", "add submodule", date="2026-01-02T01:00:00+00:00")
        f["tested"] = F.fixture_git(f["repo"], "rev-parse", "HEAD").strip()
        f["log"] = here / "ran.log"
        f["program"] = here / "planted.sh"
        f["program"].write_text(f"#!/bin/sh\necho \"$0 $*\" >> '{f['log']}'\nexec cat\n")
        f["program"].chmod(0o755)
        f["here"] = here
        return f

    def payload(self, f, **change):
        return dict({"root": str(f["repo"]), "profile": copy.deepcopy(F.PROFILE), **F.inputs(f, commit=f["tested"])},
                    **change)

    def plant_nested(self, f, mode):
        repo, here = f["repo"], f["here"]
        gitdir = repo / ".git/modules/sub/modules/nested"
        if mode == "gitfile":  # the nested Git directory moved outside .git/modules, reached through its gitfile
            gitdir = shutil.move(str(gitdir), str(here / "elsewhere-gitdir"))
            F.fixture_git(repo, "config", "-f", f"{gitdir}/config", "core.worktree", str(repo / "sub/nested"))
            (repo / "sub/nested/.git").write_text(f"gitdir: {gitdir}\n")
        else:  # embedded: sub/nested/.git is a real directory
            (repo / "sub/nested/.git").unlink()
            gitdir = shutil.move(str(gitdir), str(repo / "sub/nested/.git"))
            F.fixture_git(repo, "config", "-f", f"{gitdir}/config", "--unset", "core.worktree")
        for key in ("filter.evil.clean", "filter.evil.smudge", "core.fsmonitor"):
            F.fixture_git(repo, "config", "-f", f"{gitdir}/config", key, str(f["program"]))
        os.utime(repo / "sub/nested/a.txt", (978307200, 978307200))  # stat-dirty: status would clean it

    def run_all(self, f, record_path):
        """eligibility, plan, record and verify-record of an earlier record; the planted log must stay absent."""
        results = {"eligibility": engine.engine("eligibility", self.payload(f), {}),
                   "plan": engine.engine("plan", self.payload(f, now=F.NOW), {}),
                   "record": engine.engine("record", self.payload(f, now=F.NOW, out=str(f["here"] / "later.json")), {}),
                   "verify-record": engine.engine("verify-record", {"root": str(f["repo"]), "profile": copy.deepcopy(F.PROFILE),
                                                                    "record_path": str(record_path)}, {})}
        self.assertFalse(f["log"].exists(), f"a planted program ran: {f['log'].read_text() if f['log'].exists() else ''}")
        return results

    def first_record(self, f):
        out = f["here"] / "first.json"
        written = engine.engine("record", self.payload(f, now=F.NOW, out=str(out)), {})
        self.assertEqual((written["decision"], written["refusals"]), ("ELIGIBLE", []))
        return out

    def test_nested_submodule_filter_and_fsmonitor_never_run(self):
        for mode in ("gitfile", "embedded"):
            with self.subTest(mode=mode):
                f = self.checkout()
                record_path = self.first_record(f)
                self.plant_nested(f, mode)
                results = self.run_all(f, record_path)
                for action, result in results.items():
                    codes = {row["code"] for row in result.get("refusals", result.get("reasons", []))}
                    self.assertLessEqual(codes, {"checkout-unsafe"}, (mode, action))
                plain_status(f["repo"], f["here"])
                self.assertTrue(f["log"].exists(), "control: plain `git status` runs the nested filter")

    def test_superproject_fsmonitor_hooks_and_a_global_filter_never_run(self):
        f = self.checkout(nested=False)
        record_path = self.first_record(f)
        repo, program = f["repo"], str(f["program"])
        F.fixture_git(repo, "config", "core.fsmonitor", program)
        F.fixture_git(repo, "config", "-f", str(repo / ".git/modules/sub/config"), "core.fsmonitor", program)
        for hook in ("post-index-change", "reference-transaction", "post-checkout"):
            shutil.copyfile(f["program"], repo / ".git/hooks" / hook)
            (repo / ".git/hooks" / hook).chmod(0o755)
        home = f["here"] / "home"
        home.mkdir()
        (home / ".gitconfig").write_text(f"[filter \"evil\"]\n\tclean = {program}\n\tsmudge = {program}\n")
        (repo / ".git/info/attributes").write_text("* filter=evil\n")
        os.utime(repo / "README.md", (978307200, 978307200))
        clean = {key: value for key, value in os.environ.items() if key not in ("GIT_CONFIG_GLOBAL", "XDG_CONFIG_HOME")}
        with mock.patch.dict(os.environ, dict(clean, HOME=str(home)), clear=True):
            results = self.run_all(f, record_path)
        self.assertEqual([(results[name]["decision"], results[name]["refusals"]) for name in ("eligibility", "plan")],
                         [("ELIGIBLE", [])] * 2)
        self.assertIsNotNone(results["record"]["written"])
        self.assertEqual((results["verify-record"]["status"], results["verify-record"]["reasons"]), ("VERIFIED", []))
        plain_status(repo, home)
        self.assertTrue(f["log"].exists(), "control: plain `git status` runs the fsmonitor and the global filter")

    def test_a_filter_program_in_the_checkout_config_refuses_every_git_call(self):
        f = self.checkout(nested=False)
        included = f["here"] / "included.cfg"
        included.write_text(f"[filter \"evil\"]\n\tclean = {f['program']}\n")
        F.fixture_git(f["repo"], "config", "include.path", str(included))
        (f["repo"] / ".git/info/attributes").write_text("* filter=evil\n")
        os.utime(f["repo"] / "README.md", (978307200, 978307200))
        for args in (("rev-parse", "HEAD"), engine.CLEAN_STATUS, ("tag", "--list")):
            with self.subTest(args=args), self.assertRaisesRegex(engine.ReleaseError, "filter programs"):
                engine._git(f["repo"], *args)
        result = engine.engine("eligibility", self.payload(f), {})
        self.assertEqual([row["code"] for row in result["refusals"]], ["checkout-unsafe"])
        self.assertFalse(f["log"].exists())

    def test_only_the_exact_hardened_status_is_allowed(self):
        f = self.checkout(nested=False)
        for args in (("status",), ("status", "--porcelain", "--untracked-files=normal"),
                     ("status", "--porcelain=v1", "--untracked-files=normal", "--ignore-submodules=none")):
            with self.subTest(args=args), self.assertRaises(engine.ReleaseError):
                engine._git(f["repo"], *args)
        self.assertEqual(engine._git(f["repo"], *engine.CLEAN_STATUS), "")
        self.assertEqual((engine.GIT_ENV["GIT_ALLOW_PROTOCOL"], engine.GIT_ENV["GIT_NO_LAZY_FETCH"],
                          engine.GIT_ENV["GIT_CONFIG_GLOBAL"]), ("", "1", os.devnull))
        self.assertIn("protocol.allow=never", engine.GIT_FLAGS)


if __name__ == "__main__":
    unittest.main()
