"""Independent assurance (L20): reviewer independence, source-bound review receipts and the approval gate.

Every case runs on a synthetic tree and a private state directory in a temporary directory; no
repository file is edited and nothing is written to the owner's ~/.gaie. The role registry is the
real governance/agent-roles.json. Forged receipts recompute every digest, as an attacker with write
access to the state directory could: the checks that must still refuse them are not digest checks.
"""
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from engineering_os import assurance, contracts, control_plane
from engineering_os.assurance import AssuranceError, IndependenceError
from engineering_os.orchestration import _atomic_write

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRODUCER = "master-build-engine-engineer"
REVIEWER = "independent-assurance-engineer"
FILES = {"pkg/a.py": "def a():\n    return 1\n", "pkg/b.txt": "notes\n",
         "engineering_os/assurance.py": "# synthetic copy of an owned path\n"}


def review(key="lane-a", verdict="approve", findings=(), **extra):
    return {"key": key, "target": f"gaie/r-{key}@0000000", "verdict": verdict, "findings": list(findings), **extra}


def forge(path, **changes):
    """Rewrite a stored receipt with `changes` and every digest recomputed (mode 0600 kept)."""
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt.update(changes)
    source = contracts.sha256({"files": receipt["files"], "deleted": receipt["deleted"]})
    receipt["source_sha256"] = source
    receipt["contract_receipt"].update(
        source_sha256=source,
        request_sha256=assurance._request(receipt["key"], receipt["target"], receipt["producer"],
                                          receipt["reviewer"], receipt["commit"], source),
        result_sha256=contracts.sha256({"verdict": receipt["verdict"], "findings": receipt["findings"]}))
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    receipt["receipt_sha256"] = contracts.sha256(body)
    _atomic_write(path, receipt)
    return receipt


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="asr-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "tree"
        self.state = self.tmp / "state"
        for relative, text in FILES.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def record(self, document=None, *, producer=PRODUCER, reviewer=REVIEWER, paths=("pkg/a.py", "pkg/b.txt"), **kw):
        return assurance.record(document or review(), producer=producer, reviewer=reviewer, paths=list(paths),
                                root=self.root, state_dir=self.state, **kw)

    def verify(self, key="lane-a"):
        return assurance.verify(key, root=self.root, state_dir=self.state)

    def receipt_path(self, key="lane-a"):
        return self.state / f"{key}.json"


class AssignTests(unittest.TestCase):
    def test_default_reviewer_is_independent_for_every_role(self):
        roles = assurance._roles()
        for role in roles["roles"]:
            with self.subTest(role=role["id"]):
                result = assurance.assign(role["id"], roles=roles)
                self.assertNotEqual(result["reviewer"], role["id"])
                self.assertTrue(result["independent"])
                if role["id"] != REVIEWER:  # the role with the reviewer flag reviews everyone else
                    self.assertEqual(result["reviewer"], REVIEWER)
        self.assertEqual(assurance.assign(REVIEWER)["reviewer"], "testing-self-healing-engineer")

    def test_self_review_is_refused(self):
        for role in (PRODUCER, REVIEWER):
            with self.subTest(role=role), self.assertRaises(IndependenceError):
                assurance.assign(role, reviewer=role)

    def test_unknown_roles_are_refused(self):
        with self.assertRaisesRegex(AssuranceError, "unknown producer"):
            assurance.assign("nobody")
        with self.assertRaisesRegex(AssuranceError, "unknown reviewer"):
            assurance.assign(PRODUCER, reviewer="nobody")

    def test_a_reviewer_owning_a_changed_path_is_refused(self):
        with self.assertRaisesRegex(IndependenceError, "owns 1 changed path"):
            assurance.assign(PRODUCER, reviewer=REVIEWER, paths=["engineering_os/assurance.py"])
        with self.assertRaises(IndependenceError):  # ownership by pattern (skills/gaie-cinematic/*)
            assurance.assign(PRODUCER, reviewer="cinematic-production-engineer", paths=["skills/gaie-cinematic/SKILL.md"])
        ok = assurance.assign(PRODUCER, reviewer="cinematic-production-engineer", paths=["engineering_os/factory.py"])
        self.assertEqual(ok["reviewer"], "cinematic-production-engineer")

    def test_the_default_skips_a_candidate_that_owns_a_changed_path(self):
        result = assurance.assign(REVIEWER, paths=["tests/test_healing.py", "engineering_os/assurance.py"])
        self.assertNotIn(result["reviewer"], (REVIEWER, "testing-self-healing-engineer"))
        self.assertEqual(result["skipped"][0]["role"], "testing-self-healing-engineer")

    def test_no_independent_candidate_left_is_refused(self):
        owned = ["engineering_os/assurance.py", "engineering_os/healing.py", "scripts/security_scan.py",
                 "scripts/verify_release.py", "engineering_os/governor.py", "engineering_os/contracts.py"]
        with self.assertRaisesRegex(IndependenceError, "every candidate owns"):
            assurance.assign(PRODUCER, paths=owned)

    def test_unsafe_paths_are_refused(self):
        for path in ("../x", ".git/config", "a/.git/HEAD", "/etc/passwd", "a//b", "a/./b", "a/", "a*", "a\\b", "x\ny", ""):
            with self.subTest(path=path), self.assertRaises(AssuranceError):
                assurance.assign(PRODUCER, paths=[path])
        with self.assertRaisesRegex(AssuranceError, "duplicate"):
            assurance.assign(PRODUCER, paths=["a.py", "a.py"])


class ReviewDocumentTests(unittest.TestCase):
    def test_duplicate_json_keys_and_nan_are_refused(self):
        with self.assertRaisesRegex(AssuranceError, "Duplicate JSON key"):
            assurance.load_review('{"key": "a", "key": "b", "target": "t", "verdict": "approve", "findings": []}')
        with self.assertRaises(AssuranceError):
            assurance.load_review('{"key": "a", "target": "t", "verdict": "approve", "findings": [{"severity": "low", "x": NaN}]}')
        self.assertEqual(assurance.load_review(json.dumps(review()))["verdict"], "approve")

    def test_schema_is_strict(self):
        bad = [review(verdict="lgtm"), review(findings=[{"severity": "urgent"}]), review(findings=[{"summary": "no severity"}]),
               review(findings=[{"severity": "low", "status": "ignored"}]), review(findings=[{"severity": "low", "Bad-Name": 1}]),
               review(findings=[{"severity": "low", "id": "F"}, {"severity": "low", "id": "F"}]),
               review(findings=[{"severity": "low", "line": 1.5}]), review(key="Not A Slug"), review(extra="field"),
               {"key": "a", "target": "t", "verdict": "approve"}, review(target="two\nlines"), review(tried="not a list")]
        for document in bad:
            with self.subTest(document=document), self.assertRaises(AssuranceError):
                assurance.check_review(document)

    def test_findings_are_normalized(self):
        normal = assurance.check_review(review(verdict="approve-with-fixes", findings=[
            {"severity": "high", "file": "a.py", "line": 3, "summary": "s", "poc": "line one\nline two"}]))
        self.assertEqual(normal["findings"][0]["id"], "F1")
        self.assertEqual(normal["findings"][0]["status"], "open")
        self.assertEqual(assurance.open_findings(normal["findings"]), {"critical": 0, "high": 1, "medium": 0, "low": 0})

    def test_approve_with_an_open_high_finding_contradicts_itself(self):
        with self.assertRaisesRegex(AssuranceError, "approve-with-fixes or block"):
            assurance.check_review(review(findings=[{"severity": "high", "summary": "s"}]))
        assurance.check_review(review(findings=[{"severity": "high", "summary": "s", "status": "fixed"}]))
        assurance.check_review(review(findings=[{"severity": "medium", "summary": "s"}]))

    def test_credential_shaped_text_is_refused(self):
        token = "gh" + "p_" + "Z" * 36  # assembled at run time so the repository scan stays clean
        with self.assertRaisesRegex(AssuranceError, "credential-shaped"):
            assurance.check_review(review(verdict="block", findings=[{"severity": "critical", "poc": f"leaked {token}"}]))


class RecordVerifyTests(Base):
    def test_record_writes_a_private_source_bound_receipt(self):
        result = self.record()
        path = self.receipt_path()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        receipt = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(receipt), assurance.RECEIPT_FIELDS)
        contracts.validate_receipt(receipt["contract_receipt"])
        body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        self.assertEqual(receipt["receipt_sha256"], contracts.sha256(body))
        self.assertEqual(result["receipt_sha256"], receipt["receipt_sha256"])
        self.assertEqual(receipt["files"]["pkg/a.py"], hashlib.sha256(FILES["pkg/a.py"].encode()).hexdigest())
        self.assertEqual((receipt["producer"], receipt["reviewer"], receipt["authenticated"]), (PRODUCER, REVIEWER, False))
        self.assertEqual(receipt["review_sha256"], contracts.sha256(review()))
        row = self.verify()
        self.assertEqual((row["status"], row["verdict"], row["files"]), ("VERIFIED", "approve", 2))

    def test_record_refuses_self_review_and_a_reviewer_owning_a_bound_path(self):
        with self.assertRaises(IndependenceError):
            self.record(reviewer=PRODUCER, producer=PRODUCER)
        with self.assertRaises(IndependenceError):
            self.record(paths=["engineering_os/assurance.py"])
        with self.assertRaises(IndependenceError):
            self.record(paths=["pkg/a.py"], deleted=["engineering_os/assurance.py"])
        self.assertFalse(self.state.exists())

    def test_record_refuses_missing_symlinked_or_still_present_paths(self):
        os.symlink(self.root / "pkg/a.py", self.root / "pkg/link.py")
        os.symlink(self.root / "pkg", self.root / "alias")
        for paths, deleted in ((["pkg/none.py"], ()), (["pkg/link.py"], ()), (["alias/a.py"], ()), (["pkg"], ()),
                               (["pkg/a.py"], ["pkg/b.txt"]), (["pkg/a.py"], ["pkg/a.py"]), ([], [])):
            with self.subTest(paths=paths, deleted=deleted), self.assertRaises(AssuranceError):
                self.record(paths=paths, deleted=list(deleted))
        with self.assertRaisesRegex(AssuranceError, "commit"):
            self.record(commit="HEAD")

    def test_a_one_byte_edit_is_stale_and_restoring_the_bytes_restores_verified(self):
        self.record()
        path = self.root / "pkg/a.py"
        original = path.read_bytes()
        path.write_bytes(original.replace(b"1", b"2"))
        row = self.verify()
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertIn("stale receipt: 1 bound path(s) changed", row["reason"])
        self.assertEqual(row["changed"], ["pkg/a.py"])
        path.write_bytes(original)
        self.assertEqual(self.verify()["status"], "VERIFIED")

    def test_a_missing_or_symlinked_bound_file_is_unverified(self):
        self.record()
        path = self.root / "pkg/a.py"
        original = path.read_bytes()
        path.unlink()
        row = self.verify()
        self.assertIn("missing file", row["reason"])
        self.assertEqual(row["missing"], ["pkg/a.py"])
        (self.tmp / "same.py").write_bytes(original)  # same bytes, but reached through a symlink
        os.symlink(self.tmp / "same.py", path)
        self.assertEqual(self.verify()["missing"], ["pkg/a.py"])
        path.unlink()
        path.write_bytes(original)
        self.assertEqual(self.verify()["status"], "VERIFIED")

    def test_a_deleted_path_that_reappears_is_stale(self):
        self.record(paths=["pkg/a.py"], deleted=["pkg/gone.py"])
        self.assertEqual(self.verify()["status"], "VERIFIED")
        (self.root / "pkg/gone.py").write_text("back\n", encoding="utf-8")
        self.assertEqual(self.verify()["changed"], ["pkg/gone.py"])

    def test_a_tampered_receipt_is_unverified(self):
        self.record()
        path = self.receipt_path()
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["verdict"] = "block"
        _atomic_write(path, receipt)
        self.assertIn("digest mismatch", self.verify()["reason"])
        receipt = forge(path, verdict="approve")  # consistent again
        self.assertEqual(self.verify()["status"], "VERIFIED")
        receipt["contract_receipt"]["result_sha256"] = "0" * 64  # body digest recomputed, contract left stale
        receipt["receipt_sha256"] = contracts.sha256({k: v for k, v in receipt.items() if k != "receipt_sha256"})
        _atomic_write(path, receipt)
        self.assertIn("inconsistent", self.verify()["reason"])
        receipt.pop("summary")
        _atomic_write(path, receipt)
        self.assertIn("schema", self.verify()["reason"])

    def test_a_forged_self_review_is_unverified_even_with_valid_digests(self):
        self.record()
        forge(self.receipt_path(), reviewer=PRODUCER)
        row = self.verify()
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertIn("self-review", row["reason"])

    def test_a_forged_reviewer_that_owns_a_bound_path_is_unverified(self):
        self.record(paths=["engineering_os/assurance.py"], reviewer="testing-self-healing-engineer")
        self.assertEqual(self.verify()["status"], "VERIFIED")
        forge(self.receipt_path(), reviewer=REVIEWER)
        row = self.verify()
        self.assertIn("not independent", row["reason"])
        self.assertEqual(row["changed"], ["engineering_os/assurance.py"])
        forge(self.receipt_path(), reviewer="nobody-role")
        self.assertIn("current registry", self.verify()["reason"])

    def test_a_forged_contradictory_verdict_is_unverified(self):
        self.record(review(verdict="approve-with-fixes", findings=[{"severity": "high", "summary": "s"}]))
        forge(self.receipt_path(), verdict="approve")
        self.assertIn("receipt body invalid", self.verify()["reason"])

    def test_a_receipt_through_a_symlink_or_with_unsafe_mode_is_refused(self):
        self.record()
        path = self.receipt_path()
        moved = self.state / "elsewhere.data"
        path.rename(moved)
        os.symlink(moved, path)
        row = self.verify()
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertIn("unreadable receipt", row["reason"])
        with self.assertRaises(AssuranceError):  # a new record does not write through the link either
            self.record()
        path.unlink()
        moved.rename(path)
        self.assertEqual(self.verify()["status"], "VERIFIED")
        path.chmod(0o640)
        self.assertIn("unreadable receipt", self.verify()["reason"])
        path.chmod(0o600)
        os.link(path, self.state / "second-link")
        self.assertIn("unreadable receipt", self.verify()["reason"])
        (self.state / "second-link").unlink()
        self.assertEqual(self.verify()["status"], "VERIFIED")

    def test_duplicate_json_keys_in_a_receipt_are_refused(self):
        self.record()
        path = self.receipt_path()
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace('"verdict":"approve"', '"verdict":"block","verdict":"approve"', 1), encoding="utf-8")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertIn("Duplicate JSON key", self.verify()["reason"])

    def test_a_state_directory_inside_git_or_unsafe_is_refused(self):
        repo = self.tmp / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git/HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        inside = repo / "private/assurance"
        with self.assertRaisesRegex(AssuranceError, "outside Git"):
            assurance.record(review(), producer=PRODUCER, reviewer=REVIEWER, paths=["pkg/a.py"], root=self.root, state_dir=inside)
        self.assertFalse(inside.exists())
        inside.mkdir(parents=True, mode=0o700)
        with self.assertRaisesRegex(AssuranceError, "outside Git"):
            assurance.verify("lane-a", root=self.root, state_dir=inside)
        loose = self.tmp / "loose"
        loose.mkdir(mode=0o750)
        loose.chmod(0o750)
        with self.assertRaisesRegex(AssuranceError, "0700"):
            assurance.record(review(), producer=PRODUCER, reviewer=REVIEWER, paths=["pkg/a.py"], root=self.root, state_dir=loose)
        real = self.tmp / "real"
        real.mkdir(mode=0o700)
        os.symlink(real, self.tmp / "linked")
        for state in (self.tmp / "linked", self.tmp / "linked/sub"):
            with self.subTest(state=state), self.assertRaisesRegex(AssuranceError, "Symlink"):
                assurance.record(review(), producer=PRODUCER, reviewer=REVIEWER, paths=["pkg/a.py"], root=self.root, state_dir=state)

    def test_no_receipt_and_replacement(self):
        self.assertEqual(self.verify()["reason"], "no receipt")
        self.assertEqual(assurance.status(root=self.root, state_dir=self.state), [])
        self.assertFalse(self.state.exists())  # reading never creates state
        self.record(review(verdict="block", findings=[{"severity": "high", "summary": "s"}]))
        self.record(review(findings=[{"severity": "high", "summary": "s", "status": "fixed"}]))
        self.assertEqual(self.verify()["verdict"], "approve")
        self.record(review(key="lane-b"), paths=["pkg/b.txt"])
        (self.root / "pkg/b.txt").write_text("changed\n", encoding="utf-8")
        rows = {row["key"]: row["status"] for row in assurance.status(root=self.root, state_dir=self.state)}
        self.assertEqual(rows, {"lane-a": "UNVERIFIED", "lane-b": "UNVERIFIED"})


class GateTests(Base):
    def gate(self, items):
        return assurance.gate(items, root=self.root, state_dir=self.state)

    def test_an_approval_passes_and_block_fails(self):
        self.record()
        result = self.gate(["lane-a"])
        self.assertTrue(result["passed"])
        self.assertEqual((result["schema"], result["approved"], result["authenticated"]),
                         (assurance.GATE_SCHEMA, ["lane-a"], False))
        self.record(review(verdict="block"))
        result = self.gate(["lane-a"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["items"][0]["reasons"], ["verdict is block"])

    def test_an_open_critical_or_high_finding_fails_until_fixed(self):
        for severity in ("critical", "high"):
            with self.subTest(severity=severity):
                self.record(review(verdict="approve-with-fixes", findings=[{"id": "H1", "severity": severity, "summary": "s"}]))
                result = self.gate(["lane-a"])
                self.assertFalse(result["passed"])
                self.assertIn("open critical/high finding(s): H1", result["items"][0]["reasons"][0])
        self.record(review(verdict="approve-with-fixes", findings=[{"id": "H1", "severity": "high", "status": "fixed"},
                                                                    {"id": "M1", "severity": "medium"}]))
        result = self.gate(["lane-a"])
        self.assertTrue(result["passed"])
        self.assertEqual(result["items"][0]["open_findings"]["medium"], 1)

    def test_missing_stale_or_mismatched_items_fail(self):
        self.record()
        (self.root / "pkg/c.txt").write_text("c\n", encoding="utf-8")
        self.record(review(key="lane-b"), paths=["pkg/c.txt"])
        self.assertFalse(self.gate(["lane-a", "lane-c"])["passed"])
        (self.root / "pkg/c.txt").write_text("edited\n", encoding="utf-8")
        result = self.gate(["lane-a", "lane-b"])
        self.assertEqual((result["approved"], result["not_approved"]), (["lane-a"], ["lane-b"]))
        cases = [({"key": "lane-a", "producer": "motion-sdk-animation-engineer"}, "producer"),
                 ({"key": "lane-a", "paths": ["pkg/a.py", "pkg/other.py"]}, "does not bind 1 path"),
                 ({"key": "lane-a", "commit": "a" * 40}, "another commit")]
        for item, reason in cases:
            with self.subTest(item=item):
                result = self.gate([item])
                self.assertFalse(result["passed"])
                self.assertIn(reason, result["items"][0]["reasons"][0])
        self.assertTrue(self.gate([{"key": "lane-a", "producer": PRODUCER, "paths": ["pkg/a.py", "pkg/b.txt"]}])["passed"])

    def test_bad_gate_requests_are_refused(self):
        for items in ([], ["lane-a", "lane-a"], [{"key": "lane-a", "extra": 1}], [{"producer": PRODUCER}], "lane-a", [7]):
            with self.subTest(items=items), self.assertRaises(AssuranceError):
                self.gate(items)


class EngineTests(Base):
    def test_engine_record_follows_the_contract(self):
        contracts.validate_engine(assurance.ENGINE_RECORD, check_imports=True)
        self.assertEqual(assurance.ENGINE_RECORD["layer"], "L20")
        self.assertEqual(sorted(assurance.ENGINE_ACTIONS), ["assign", "gate", "record", "status", "verify"])
        for name, spec in assurance.ENGINE_ACTIONS.items():
            with self.subTest(action=name):
                if name == "record":
                    self.assertEqual(spec["side_effect"], "state-write")
                else:
                    self.assertEqual(spec["side_effect"], "none")
                    self.assertLessEqual(set(spec["permissions"]), control_plane.READ_PERMISSIONS)
        self.assertEqual(assurance.health()["ok"], True)

    def test_engine_actions_use_the_private_state_directory(self):
        ctx = {"state_dir": str(self.tmp / "cp"), "root": self.root}
        assigned = assurance.engine("assign", {"producer": PRODUCER, "paths": ["pkg/a.py"]}, ctx)["result"]
        payload = {"review": review(), "producer": PRODUCER, "reviewer": assigned["reviewer"], "paths": ["pkg/a.py"]}
        out = assurance.engine("record", payload, ctx)
        self.assertEqual((out["engine"], out["mode"]), ("independent-assurance", "deterministic"))
        self.assertTrue((self.tmp / "cp/assurance/lane-a.json").is_file())
        self.assertEqual(assurance.engine("verify", {"key": "lane-a"}, ctx)["result"]["status"], "VERIFIED")
        self.assertTrue(assurance.engine("gate", {"items": ["lane-a"]}, ctx)["result"]["passed"])
        self.assertEqual(assurance.engine("status", {}, ctx)["result"]["count"], 1)

    def test_engine_refuses_unknown_actions_and_bad_payloads(self):
        ctx = {"state_dir": str(self.tmp / "cp"), "root": self.root}
        for action, payload in (("delete", {}), ("verify", {}), ("verify", {"key": "a", "path": "/etc"}),
                                ("record", {"review": review(), "producer": PRODUCER, "paths": ["pkg/a.py"]}),
                                ("assign", [PRODUCER]), (None, {})):
            with self.subTest(action=action, payload=payload), self.assertRaises(AssuranceError):
                assurance.engine(action, payload, ctx)


def _git(cwd, *args):
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(cwd), "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                    *args], cwd=cwd, env=env, check=True, capture_output=True, timeout=60)


@unittest.skipUnless(shutil.which("git"), "git is required for the --base flow")
class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="asc-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.state = self.tmp / "repo", self.tmp / "state"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a.py").write_text("A = 1\n", encoding="utf-8")
        (self.repo / "b.txt").write_text("b\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "base")
        _git(self.repo, "checkout", "-q", "-b", "feature")
        (self.repo / "a.py").write_text("A = 2\n", encoding="utf-8")
        (self.repo / "c.py").write_text("C = 3\n", encoding="utf-8")
        (self.repo / "b.txt").unlink()
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "change")
        self.findings = self.tmp / "findings.json"
        self.findings.write_text(json.dumps(review(key="feature", verdict="approve-with-fixes",
                                                   findings=[{"id": "L1", "severity": "low", "summary": "s"}])), encoding="utf-8")

    def cli(self, *args):
        env = {**os.environ, "GAIE_HOME": str(self.tmp / "home")}
        return subprocess.run([sys.executable, "-m", "engineering_os.assurance", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_record_from_a_branch_diff_then_verify_and_gate(self):
        common = ["--root", str(self.repo), "--state", str(self.state)]
        out = self.cli("record", "--review", str(self.findings), "--producer", PRODUCER, "--reviewer", REVIEWER,
                       "--base", "main", *common, "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        receipt = json.loads((self.state / "feature.json").read_text(encoding="utf-8"))
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        self.assertEqual((receipt["commit"], sorted(receipt["files"]), receipt["deleted"]), (head, ["a.py", "c.py"], ["b.txt"]))
        self.assertEqual(self.cli("verify", "feature", *common).returncode, 0)
        gate = self.cli("gate", "feature", *common, "--json")
        self.assertEqual(gate.returncode, 0, gate.stdout)
        self.assertTrue(json.loads(gate.stdout)["passed"])
        (self.repo / "a.py").write_text("A = 9\n", encoding="utf-8")  # uncommitted edit
        self.assertEqual(self.cli("verify", "feature", *common).returncode, 1)
        self.assertEqual(self.cli("gate", "feature", *common).returncode, 1)
        dirty = self.cli("record", "--review", str(self.findings), "--producer", PRODUCER, "--reviewer", REVIEWER,
                         "--base", "main", *common)
        self.assertEqual(dirty.returncode, 2)
        self.assertIn("commit them first", dirty.stderr)
        injected = self.cli("record", "--review", str(self.findings), "--producer", PRODUCER, "--reviewer", REVIEWER,
                            "--base=--output=/tmp/x", *common)
        self.assertEqual(injected.returncode, 2)
        self.assertIn("plain Git revision", injected.stderr)
        with self.assertRaisesRegex(AssuranceError, "plain Git revision"):
            assurance.changed_since(self.repo, "-x")
        with self.assertRaisesRegex(AssuranceError, "git could not resolve"):
            assurance.changed_since(self.repo, "no-such-branch")

    def test_cli_refuses_self_review_and_duplicate_keys(self):
        assigned = self.cli("assign", "--producer", PRODUCER, "--json")
        self.assertEqual(json.loads(assigned.stdout)["reviewer"], REVIEWER)
        self.assertEqual(self.cli("assign", "--producer", PRODUCER, "--reviewer", PRODUCER).returncode, 2)
        self.findings.write_text('{"key": "feature", "key": "other", "target": "t", "verdict": "approve", "findings": []}',
                                 encoding="utf-8")
        out = self.cli("record", "--review", str(self.findings), "--producer", PRODUCER, "--reviewer", REVIEWER,
                       "--paths", "a.py", "--root", str(self.repo), "--state", str(self.state))
        self.assertEqual(out.returncode, 2)
        self.assertIn("Duplicate JSON key", out.stderr)
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
