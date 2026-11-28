"""Exercise the MASTER approval boundary with a synthetic Git history."""

import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from engineering_os import master_approval


FIXTURE_ROUTER = """
import argparse
import json
import os
import pathlib

assert "GAIE_TEST_CREDENTIAL" not in os.environ
overlay = pathlib.Path(os.environ["GAIE_HOME"]).resolve()
assert not any((parent / ".git").exists() for parent in (overlay, *overlay.parents))
assert not (overlay / "projects.json").exists()
assert pathlib.Path("prompts/MASTER_BUILD.md").is_file()
assert pathlib.Path("prompts/MASTER_UPGRADE.md").is_file()
parser = argparse.ArgumentParser()
parser.add_argument("operation")
parser.add_argument("command")
parser.add_argument("--workspace")
args = parser.parse_intermixed_args()
assert args.operation == "route"
if args.command == "clarify":
    print(json.dumps({"schema_version": 1, "status": "needs-clarification"}))
    raise SystemExit(2)
route = {
    "schema_version": 1, "status": "routed", "engine": "MASTER_BUILD",
    "command": args.command, "workspace_received": args.workspace is not None
}
if args.command.startswith("upgrade"):
    route.update(engine="MASTER_UPGRADE", write_allowed=True, targets=[{
        "id": "sample", "repository": "https://github.com/fixture/sample", "workspace_matches": True
    }])
print(json.dumps(route))
"""


class MasterApprovalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-master-approval-test-")
        self.addCleanup(temporary.cleanup)
        self.home = pathlib.Path(temporary.name)
        self.repo = self.home / "hub"
        self.repo.mkdir()
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.name", "GAIE Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("remote", "add", "origin", master_approval.HUB_URL + ".git")
        for name in master_approval.SOURCE_PATHS:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(FIXTURE_ROUTER if name == master_approval.ROUTER else "Synthetic closure fixture\n")
        self.revision = self.commit()
        self.git("update-ref", master_approval.MAIN_REF, self.revision)
        self.path = self.home / "approval.json"
        self.persist(self.receipt(self.revision))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "Synthetic fixture")
        return self.git("rev-parse", "HEAD")

    def receipt(self, revision):
        return {
            "schema_version": 1,
            "repository": master_approval.HUB_URL,
            "revision": revision,
            "approved_engines": list(master_approval.ENGINES),
            "source_sha256": {name: hashlib.sha256((self.repo / name).read_bytes()).hexdigest()
                              for name in master_approval.SOURCE_PATHS},
        }

    def persist(self, approval):
        raw = json.dumps(approval).encode("utf-8")
        self.path.write_bytes(raw)
        self.path.chmod(0o600)
        self.sha = hashlib.sha256(raw).hexdigest()

    def inputs(self, **override):
        return {**{"approval_file": self.path, "approval_sha256": self.sha,
                   "source_root": self.repo}, **override}

    def test_approved_route_executes_immutable_source_and_scrubs_inherited_environment(self):
        # A mutable checkout must not change what the approved route executes.
        (self.repo / master_approval.ROUTER).write_text("raise SystemExit(99)\n")
        with patch.dict(os.environ, {"GAIE_TEST_CREDENTIAL": "fixture", "GAIE_HOME": "/ignored",
                                     "GIT_DIR": "/ignored"}):
            result = master_approval.approved_route("build synthetic app", **self.inputs(workspace_root=self.repo))
        self.assertEqual(result["engine"], "MASTER_BUILD")
        self.assertTrue(result["workspace_received"])
        self.assertNotIn("command", result)
        proof = result["master_approval"]
        self.assertEqual(proof["revision"], self.revision)
        self.assertEqual(proof["main_revision"], self.revision)
        self.assertEqual(proof["approval_sha256"], self.sha)
        self.assertEqual(set(proof["source_sha256"]), set(master_approval.SOURCE_PATHS))

    def test_unmerged_pin_and_missing_tracking_main_are_blocked(self):
        (self.repo / "prompts/MASTER_BUILD.md").write_text("Unmerged prompt fixture\n")
        draft = self.commit()
        self.persist(self.receipt(draft))
        with self.assertRaises(master_approval.MasterApprovalError):
            master_approval.verify_master_approval(**self.inputs())
        self.git("update-ref", "-d", master_approval.MAIN_REF)
        with self.assertRaises(master_approval.MasterApprovalError):
            master_approval.verify_master_approval(**self.inputs())

    def test_source_digest_mismatch_and_incomplete_closure_fail(self):
        approval = self.receipt(self.revision)
        approval["source_sha256"]["prompts/MASTER_UPGRADE.md"] = "0" * 64
        self.persist(approval)
        with self.assertRaisesRegex(master_approval.MasterApprovalError, "source differs"):
            master_approval.verify_master_approval(**self.inputs())
        approval["source_sha256"].pop(master_approval.ROUTER)
        self.persist(approval)
        with self.assertRaisesRegex(master_approval.MasterApprovalError, "source closure"):
            master_approval.verify_master_approval(**self.inputs())

    def test_receipt_pin_permissions_links_and_foreign_origin_fail(self):
        with self.assertRaisesRegex(master_approval.MasterApprovalError, "approval bytes"):
            master_approval.verify_master_approval(**self.inputs(approval_sha256="0" * 64))
        self.path.chmod(0o644)
        with self.assertRaises(master_approval.MasterApprovalError):
            master_approval.verify_master_approval(**self.inputs())
        self.path.chmod(0o600)
        link = self.home / "link.json"
        link.symlink_to(self.path)
        with self.assertRaises(master_approval.MasterApprovalError):
            master_approval.verify_master_approval(**self.inputs(approval_file=link))
        self.git("remote", "set-url", "origin", "https://github.com/fixture/other")
        with self.assertRaisesRegex(master_approval.MasterApprovalError, "expected GitHub origin"):
            master_approval.verify_master_approval(**self.inputs())

    def test_next_generation_source_does_not_start_if_approval_omits_an_engine(self):
        approval = self.receipt(self.revision)
        approval["approved_engines"].remove("MASTER_UPGRADE")
        self.persist(approval)
        with self.assertRaisesRegex(master_approval.MasterApprovalError, "both MASTER engines"):
            master_approval.approved_route("build synthetic app", **self.inputs())

    def test_pinned_router_can_defer_a_prompt_without_executing(self):
        result = master_approval.approved_route("clarify", **self.inputs())
        self.assertEqual(result["status"], "needs-clarification")
        self.assertEqual(result["master_approval"]["main_revision"], self.revision)

    def test_upgrade_requires_raw_origin_and_exact_worktree_root(self):
        project = self.home / "upgrade"
        project.mkdir()

        def git_project(*args):
            subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True)

        git_project("init", "-q")
        git_project("remote", "add", "origin", "https://github.com/fixture/sample.git")
        inputs = self.inputs(workspace_root=project)
        correct = master_approval.approved_route("upgrade sample", **inputs)
        self.assertTrue(correct["targets"][0]["workspace_matches"])
        self.assertTrue(correct["write_allowed"])

        git_project("remote", "set-url", "origin", "https://example.invalid/acme/sample.git")
        git_project("config", "url.https://github.com/fixture/.insteadOf", "https://example.invalid/acme/")
        rewritten = master_approval.approved_route("upgrade sample", **inputs)
        self.assertFalse(rewritten["targets"][0]["workspace_matches"])
        self.assertFalse(rewritten["write_allowed"])
        git_project("remote", "set-url", "origin", "https://github.com/fixture/sample.git")
        nested = project / "nested"
        nested.mkdir()
        mismatch = master_approval.approved_route("upgrade sample", **self.inputs(workspace_root=nested))
        self.assertFalse(mismatch["write_allowed"])

    def test_git_symlink_cannot_supply_executable_source(self):
        router = self.repo / master_approval.ROUTER
        target = self.repo / "real.py"
        router.rename(target)
        router.symlink_to("../real.py")
        revision = self.commit()
        self.git("update-ref", master_approval.MAIN_REF, revision)
        self.persist(self.receipt(revision))
        with self.assertRaisesRegex(master_approval.MasterApprovalError, "regular pinned Git blob"):
            master_approval.verify_master_approval(**self.inputs())


if __name__ == "__main__":
    unittest.main()
