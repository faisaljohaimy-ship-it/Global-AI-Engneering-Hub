"""Scenario G (release engine, L11) on a SYNTHETIC Git repository built in a temporary directory.

Criteria G1-G9 are stated in docs/specs/gaie-20-layers/RELEASE_ENGINE.md; the fixture and
its cases are tests/fixtures/release/scenario_g.py, which also writes the committed
evidence docs/evidence/gaie-20-layers/scenario-g.json.
"""
import copy
import importlib.util
import inspect
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import contracts  # noqa: E402
from engineering_os import release_engine as engine  # noqa: E402
from scripts import verify_release  # noqa: E402


def fixture():
    name = "gaie_release_scenario_g_fixture"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "tests/fixtures/release/scenario_g.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


F = fixture()
CASES = {case[0]: case for case in F.CASES}


class Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = pathlib.Path(tempfile.mkdtemp(prefix="gaie-g-"))
        cls.addClassCleanup(shutil.rmtree, cls.scratch, ignore_errors=True)
        cls.template = F.build(cls.scratch / "template")
        cls.count = 0

    def fresh(self):
        type(self).count += 1
        directory = self.scratch / f"x{self.count}"
        directory.mkdir()
        return directory

    def copy(self):
        return F.copy_fixture(self.template, self.fresh())

    def payload(self, f, **change):
        return dict({"root": str(f["repo"]), "profile": copy.deepcopy(F.PROFILE), **F.inputs(f)}, **change)

    def assertCase(self, name):
        result, _ = F.run_case(self.template, CASES[name], self.fresh())
        self.assertEqual((result["observed"], result["observed_codes"]), (result["expected"], result["expected_codes"]), name)
        return result


class ScenarioG(Synthetic):
    """Acceptance Scenario G: the engine releases nothing and refuses every incomplete release."""

    def criterion(self, label):
        names = [name for name, case in CASES.items() if case[1] == label]
        self.assertTrue(names, label)
        for name in names:
            with self.subTest(case=name):
                self.assertCase(name)

    def test_g1_g8_eligible_with_complete_exact_sha_evidence(self):
        self.assertCase("eligible")
        f = self.copy()
        planned = engine.engine("plan", self.payload(f, now=F.NOW), {})
        self.assertEqual((planned["decision"], planned["refusals"]), ("ELIGIBLE", []))
        body = planned["record"]
        self.assertEqual((body["version"], body["planned_tag"], body["status"]), ("1.1.0", "synthetic-v1.1.0", engine.STATUS))
        self.assertEqual((body["tested_commit"], body["base_commit"]), (self.template["tested"], self.template["base"]))
        self.assertEqual({key: body[key] for key in engine.PERFORMED}, engine.PERFORMED)
        self.assertEqual(sorted((row["workflow"], row["job"]) for row in body["required_jobs"]),
                         sorted((path, name) for path, names in F.REQUIRED.items() for name in names))
        self.assertTrue(all(row["commit"] == self.template["tested"] for row in body["required_jobs"]))
        self.assertEqual(body["previous_version"], {"version": "1.0.0", "sources": ["changelog", "tag"]})
        self.assertEqual(body["rollback"]["previous_commit"], self.template["base"])
        self.assertEqual(body["release_notes"], "- second release")
        for row in body["components"]:
            self.assertEqual(row["sha256"], contracts.sha256((f["repo"] / row["path"]).read_bytes()), row["id"])
        tree = subprocess.run(["git", "-C", str(f["repo"]), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True,
                              check=True).stdout.strip()
        self.assertEqual(body["tree"]["git_tree"], tree)
        self.assertEqual(body["record_sha256"], contracts.sha256({k: v for k, v in body.items() if k != "record_sha256"}))
        publish = body["owner_commands"][1]["argv"]
        self.assertEqual(publish[:4], ["gh", "release", "create", "synthetic-v1.1.0"])
        self.assertEqual(publish[publish.index("--target") + 1], self.template["tested"])

    def test_g1_refused_for_a_dirty_or_unsafe_checkout(self):
        self.criterion("G1")

    def test_g2_refused_unless_the_exact_full_sha_is_head(self):
        self.criterion("G2")

    def test_g3_refused_for_another_sha_a_missing_failed_or_ambiguous_job(self):
        self.criterion("G3")

    def test_g4_refused_without_owner_authorization_for_this_sha_and_version(self):
        self.criterion("G4")

    def test_g5_refused_for_a_version_that_is_invalid_not_greater_or_not_in_the_changelog(self):
        self.criterion("G5")

    def test_g6_refused_unless_an_independent_review_gate_passed_for_this_commit(self):
        self.criterion("G6")

    def test_g7_record_never_written_through_a_link_inside_git_or_over_a_file(self):
        results, _ = F.record_cases(self.template, self.fresh(), {"git": [], "events": []})
        self.assertEqual(len(results), 4)
        for row in results:
            with self.subTest(case=row["id"]):
                self.assertEqual((row["observed"], row["observed_codes"], row["written"]),
                                 ("REFUSED", row["expected_codes"], False))
        f = self.copy()
        (f["repo"] / "README.md").write_text("dirty\n")
        out = self.fresh() / "refused.json"
        result = engine.engine("record", self.payload(f, out=str(out)), {})
        self.assertEqual((result["decision"], result["written"], out.exists()), ("REFUSED", None, False))

    def test_g7_record_is_private_exclusive_and_defaults_to_the_state_directory(self):
        f, state = self.copy(), self.fresh() / "state"
        result = engine.engine("record", self.payload(f, now=F.NOW), {"state_dir": str(state)})
        path = pathlib.Path(result["written"]["path"])
        self.assertEqual(path.parent, state / "releases")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text())["record_sha256"], result["written"]["record_sha256"])
        again = engine.engine("record", self.payload(f, now=F.NOW), {"state_dir": str(state)})
        self.assertEqual([row["code"] for row in again["refusals"]], ["record-exists"])
        with self.assertRaises(engine.ReleaseError):
            engine.engine("record", self.payload(f), {})

    def test_g8_no_push_tag_or_network_command_is_ever_executed(self):
        f, directory = self.copy(), self.fresh()
        with F.recording(directory) as seen:
            F.call(seen, "eligibility", self.payload(f))
            written = F.call(seen, "record", self.payload(f, out=str(directory / "r.json")))
            F.call(seen, "verify-record", {"root": str(f["repo"]), "profile": copy.deepcopy(F.PROFILE),
                                           "record_path": str(directory / "r.json")})
            refused = self.payload(f, version="9.9.9")
            F.call(seen, "plan", refused)
        self.assertIsNotNone(written["written"])
        executed = F.summary(seen)
        self.assertGreater(executed["git_invocations"], 10)
        self.assertEqual(executed["processes_started"], executed["git_invocations"], "every process was the logged git")
        self.assertEqual((executed["git_write_or_network_commands"], executed["non_git_processes"],
                          executed["socket_exec_or_url_events"]), (0, 0, 0))
        self.assertLessEqual(set(executed["git_subcommands"]), F.READ_ONLY)
        self.assertEqual(F.fixture_git(self.template["origin"], "for-each-ref"), "", "nothing reached the remote")
        self.assertEqual(F.fixture_git(f["repo"], "tag", "--list").split(), ["synthetic-v1.0.0"])
        for argv in (("push", "origin", "main"), ("tag", "synthetic-v1.1.0"), ("fetch",), ("remote", "-v"),
                     ("ls-remote", "origin"), ("commit", "-m", "x"), ("config", "user.name", "x")):
            with self.subTest(argv=argv), self.assertRaises(engine.ReleaseError):
                engine._git(f["repo"], *argv)

    def test_g9_verify_record_goes_unverified_after_one_byte_and_back_after_restoring(self):
        _, cycle = F.record_cases(self.template, self.fresh(), {"git": [], "events": []})
        steps = {row["step"]: (row["status"], row["codes"]) for row in cycle["steps"]}
        self.assertEqual(steps, {
            "written": ("ELIGIBLE", []), "verify": ("VERIFIED", []),
            "record-one-byte-changed": ("UNVERIFIED", ["record-digest"]), "record-restored": ("VERIFIED", []),
            "record-truncated": ("UNVERIFIED", ["record-unreadable"]),
            "component-one-byte-changed": ("UNVERIFIED", ["component-changed", "dirty-tree"]),
            "component-restored": ("VERIFIED", []), "other-receipts-supplied": ("UNVERIFIED", ["receipts-changed"]),
            "same-inputs-supplied": ("VERIFIED", []), "record-read-through-symlink": ("UNVERIFIED", ["record-unreadable"])})

    def test_g9_verify_record_after_head_moves_or_the_profile_changes(self):
        f, directory = self.copy(), self.fresh()
        out = directory / "r.json"
        self.assertIsNotNone(engine.engine("record", self.payload(f, out=str(out)), {})["written"])
        verify = {"root": str(f["repo"]), "profile": copy.deepcopy(F.PROFILE), "record_path": str(out)}
        changed = copy.deepcopy(F.PROFILE)
        changed["required_jobs"][".github/workflows/ci.yml"].append("e2e")
        result = engine.engine("verify-record", dict(verify, profile=changed), {})
        self.assertEqual(sorted(row["code"] for row in result["reasons"]), ["profile-changed", "required-jobs-changed"])
        F.fixture_git(f["repo"], "commit", "-q", "--allow-empty", "-m", "later", date="2026-01-03T00:00:00+00:00")
        result = engine.engine("verify-record", verify, {})
        self.assertEqual([row["code"] for row in result["reasons"]], ["commit-not-head"])
        F.fixture_git(f["repo"], "tag", "synthetic-v1.1.0", "HEAD")
        result = engine.engine("verify-record", verify, {})
        self.assertEqual(sorted(row["code"] for row in result["reasons"]), ["commit-not-head", "tag-on-other-commit"])

    def test_receipts_and_authorization_shapes_are_strict(self):
        f = self.copy()
        tested = self.template["tested"]
        bad = [("receipts", dict(F.receipts(tested), schema="other")), ("receipts", dict(F.receipts(tested), extra=1)),
               ("receipts", F.receipts(tested, jobs=[dict(F.receipts(tested)["jobs"][0], run_id="7")])),
               ("authorization", dict(F.authorization(tested), authorized_by="agent")),
               ("authorization", dict(F.authorization(tested), at="yesterday")),
               ("review_gate", {"passed": "yes", "commit": tested}), ("review_gate", ["passed"])]
        for key, value in bad:
            with self.subTest(key=key, value=str(value)[:60]):
                result = engine.engine("eligibility", self.payload(f, **{key: value}), {})
                self.assertEqual(result["decision"], "REFUSED")
                self.assertTrue(all(row["code"].endswith("-invalid") for row in result["refusals"]), result["refusals"])


class EngineContract(unittest.TestCase):
    def test_engine_record_satisfies_the_shared_contract_at_or_below_workspace_write(self):
        record = contracts.validate_engine(copy.deepcopy(engine.ENGINE_RECORD), check_imports=True)
        self.assertEqual((record["id"], record["layer"]), ("release-engine", "L11"))
        ceiling = contracts.side_effect_rank("workspace-write")
        for name, spec in record["actions"].items():
            self.assertLessEqual(contracts.side_effect_rank(spec["side_effect"]), ceiling, name)
            self.assertNotIn("ext:github", spec["permissions"], name)
        self.assertEqual(set(record["actions"]), {"eligibility", "plan", "record", "verify-record"})
        self.assertEqual(list(inspect.signature(engine.engine).parameters)[:3], ["action", "payload", "ctx"])

    def test_unknown_actions_keys_and_profiles_are_refused(self):
        for action, payload in (("deploy", {}), ("publish", {}), ("eligibility", []),
                                ("eligibility", {"root": "/x", "profile": "hub", "version": "1.0.0"}),
                                ("plan", {"root": "/x", "profile": "hub", "version": "1.0.0", "commit": "a" * 40,
                                          "shell": "true"})):
            with self.subTest(action=action), self.assertRaises(engine.ReleaseError):
                engine.engine(action, payload, {})
        bad = copy.deepcopy(F.PROFILE)
        for field, value in (("tag_prefix", "release/"), ("changelog", "../CHANGELOG.md"), ("required_jobs", {}),
                             ("components", [{"id": "x", "path": "/etc/passwd", "key": None}]), ("schema", "other")):
            with self.subTest(field=field), self.assertRaises(engine.ReleaseError):
                engine.validate_profile(dict(bad, **{field: value}))

    def test_health_is_side_effect_free(self):
        result = engine.health()
        self.assertTrue(result["ok"], result)
        self.assertIn("never tags, pushes or deploys", result["detail"])


class HubRelease(Synthetic):
    """The hub's own release: the version source, its profile and a record on a hub-shaped repository."""

    def test_os_version_source_matches_the_changelog_and_the_tag_shape(self):
        status = engine.hub_version_status(engine.ROOT)
        self.assertTrue(status["consistent"], status)
        self.assertEqual((ROOT / engine.VERSION_FILE).read_text(encoding="utf-8"), status["version"] + "\n")
        self.assertRegex(status["planned_tag"], engine.HUB_TAG)

    def test_hub_profile_binds_the_jobs_release_yml_verifies_and_every_declared_version(self):
        profile = engine.hub_profile(engine.ROOT)
        self.assertEqual(profile["required_jobs"], {path: sorted(names) for path, names in verify_release.WORKFLOWS.items()})
        refusals, facts = engine.file_facts(engine.ROOT, profile)
        self.assertEqual(refusals, [])
        ids = {row["id"]: row for row in facts["components"]}
        self.assertEqual(ids["engineering-os"]["version"], facts["changelog"]["version"])
        self.assertEqual(ids["engineering-sdk"]["version"], (ROOT / "sdk/VERSION").read_text().strip())
        for row in facts["components"]:
            self.assertEqual(row["sha256"], contracts.sha256((ROOT / row["path"]).read_bytes()), row["id"])

    def hub_repository(self):
        directory = self.fresh()
        repo = directory / "hub"
        names = {"CHANGELOG.md", "catalog/packs.json", *(path for _, path, _ in engine.HUB_FILES)}
        for name in names:
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, repo / name)
        F.fixture_git(repo, "init", "-q", "-b", "main")
        F.fixture_git(repo, "add", "-A")
        F.fixture_git(repo, "commit", "-q", "-m", "hub-shaped synthetic merge commit")
        commit = F.fixture_git(repo, "rev-parse", "HEAD").strip()
        version = (repo / engine.VERSION_FILE).read_text().strip()
        jobs = [{"workflow": path, "job": name, "commit": commit, "status": "completed", "conclusion": "success",
                 "run_id": 7, "job_id": 70 + index} for index, (path, name) in
                enumerate((p, n) for p, names in sorted(verify_release.WORKFLOWS.items()) for n in sorted(names))]
        evidence = {"receipts": {"schema": engine.RECEIPTS_SCHEMA, "commit": commit, "jobs": jobs},
                    "authorization": {"schema": engine.AUTHORIZATION_SCHEMA, "commit": commit, "version": version,
                                      "tag": f"engineering-os-v{version}", "authorized_by": "owner",
                                      "reference": "SYNTHETIC test authorization", "at": "2026-11-28T00:00:00Z"},
                    "review_gate": {"passed": True, "commit": commit, "reviewer": "independent-assurance-engineer"}}
        return directory, repo, commit, version, evidence

    def test_hub_record_is_recorded_with_the_tag_pending(self):
        directory, repo, commit, version, evidence = self.hub_repository()
        out = directory / "state" / "engineering-os-release.json"
        result = engine.hub_record(version, commit, evidence["receipts"], out=str(out), root=repo,
                                   authorization=evidence["authorization"], review_gate=evidence["review_gate"])
        self.assertEqual(result["decision"], "ELIGIBLE", result["refusals"])
        body = json.loads(out.read_text())
        self.assertEqual((body["status"], body["tag_created"], body["planned_tag"]),
                         ("recorded, tag pending", False, f"engineering-os-v{version}"))
        self.assertEqual(body["base_commit"], None)
        self.assertEqual(body["version_source"]["version"], version)
        self.assertEqual(body["owner_commands"][1]["argv"][:4], ["gh", "release", "create", f"engineering-os-v{version}"])
        self.assertEqual(engine.verify_record(repo, "hub", out)["status"], "VERIFIED")
        missing = engine.hub_record(version, commit, evidence["receipts"], out=str(directory / "no.json"), root=repo)
        self.assertEqual(sorted(row["code"] for row in missing["refusals"]), ["authorization-missing", "review-gate-missing"])
        other = engine.hub_record("9.0.0", commit, evidence["receipts"], out=str(directory / "no.json"), root=repo,
                                  authorization=dict(evidence["authorization"], version="9.0.0", tag="engineering-os-v9.0.0"),
                                  review_gate=evidence["review_gate"])
        self.assertEqual(sorted(row["code"] for row in other["refusals"]),
                         ["version-changelog-mismatch", "version-source-mismatch"])
        self.assertFalse((directory / "no.json").exists())

    def test_command_line_hub_record_and_strict_json_inputs(self):
        directory, repo, commit, version, evidence = self.hub_repository()
        files = {}
        for key, value in evidence.items():
            files[key] = directory / f"{key}.json"
            files[key].write_text(json.dumps(value))
        argv = [sys.executable, "-m", "engineering_os.release_engine", "hub-record", "--root", str(repo),
                "--version", version, "--commit", commit, "--receipts", str(files["receipts"]),
                "--authorization", str(files["authorization"]), "--review-gate", str(files["review_gate"])]
        done = subprocess.run(argv + ["--out", str(directory / "cli.json")], cwd=ROOT, capture_output=True, text=True,
                              timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("recorded, tag pending", json.loads(done.stdout)["summary"])
        files["receipts"].write_text('{"schema": "gaie.ci-receipts/1", "jobs": [], "jobs": []}')
        done = subprocess.run(argv + ["--out", str(directory / "dup.json")], cwd=ROOT, capture_output=True, text=True,
                              timeout=120)
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertIn("duplicate", done.stdout)
        self.assertFalse((directory / "dup.json").exists())


class ScenarioGEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = F.EVIDENCE.read_text(encoding="utf-8")
        cls.document = json.loads(cls.text)

    def test_the_committed_evidence_is_reproduced_by_its_command(self):
        self.assertEqual(F.evidence(), self.document, f"regenerate with: {F.COMMAND}")

    def test_bound_to_its_sources_labelled_synthetic_and_public_safe(self):
        doc = self.document
        for name, value in doc["sources"].items():
            self.assertEqual(value, contracts.sha256((ROOT / name).read_bytes()), name)
        self.assertEqual((doc["synthetic"], doc["scenario"], doc["layer"], doc["network"], doc["model_calls"]),
                         (True, "G", "L11", False, 0))
        self.assertTrue(doc["label"].startswith("SYNTHETIC"))
        self.assertEqual(doc["command"], F.COMMAND)
        for row in doc["cases"]:
            self.assertEqual((row["observed"], row["observed_codes"]), (row["expected"], row["expected_codes"]), row["id"])
        executed = doc["commands_executed"]
        self.assertEqual((executed["git_write_or_network_commands"], executed["non_git_processes"],
                          executed["socket_exec_or_url_events"], executed["origin_refs_after"]), (0, 0, 0, 0))
        self.assertEqual(executed["processes_started"], executed["git_invocations"])
        self.assertFalse(doc["record_cycle"]["record"]["tag_created"])
        for needle in ("/tmp/", "/home/", "/root/", "/Users/", str(ROOT)):
            self.assertNotIn(needle, self.text)


if __name__ == "__main__":
    unittest.main()
