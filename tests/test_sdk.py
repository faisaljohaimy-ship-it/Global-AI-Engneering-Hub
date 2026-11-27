import copy
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

import hublink

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sdk", ROOT / "sdk/engineering_sdk.py")
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


class SDKTests(unittest.TestCase):
    def test_sdk_pack_installs_both_agent_skills_and_verifies_offline(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("hublink.on_main", return_value=True):
            root = pathlib.Path(folder)
            hublink.register(root, hublink.head(), capabilities=["pack:engineering-sdk"], apply=True)
            self.assertTrue(hublink.verify(root, strict=True)["ok"])
            self.assertEqual((root / ".agents/skills/engineering-sdk/SKILL.md").read_bytes(),
                             (root / ".claude/skills/engineering-sdk/SKILL.md").read_bytes())
            result = subprocess.run(["python3", str(root / ".engineering/sdk/engineering_sdk.py"), "verify", "--project", str(root)], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)["status"], "local-integrity-verified")

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        (self.root / ".engineering").mkdir()
        (self.root / "vendored.txt").write_bytes(b"pinned bytes")
        self.manifest = {"schema_version": 1, "hub_revision": "a" * 40,
                         "budget_additional_sar": 0, "production_runtime_dependency": False,
                         "capabilities": [{"id": "pack:sample", "files": [{"path": "vendored.txt", "sha256": hashlib.sha256(b"pinned bytes").hexdigest()}]}]}
        self.save("capabilities.json", self.manifest)
        self.contract = {"schema_version": 1, "identity_verified": True,
                         "repository": "https://github.com/example/one",
                         "vercel": {"team_id": "team_one", "project_id": "prj_one", "root_directory": "."},
                         "required_checks": ["unit", "security", "build"]}
        self.save("project.json", self.contract)
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.evidence = {"schema_version": 1, "commit": self.sha,
                         "repository": self.contract["repository"], "vercel": self.contract["vercel"],
                         "checks": {n: {"commit": self.sha, "conclusion": "success"} for n in self.contract["required_checks"]},
                         "review": {"commit": self.sha, "decision": "approved"},
                         "rollback": {"deployment_id": "dpl_previous", "project_id": "prj_one", "verified": True},
                         "stage": {"deployment_id": "dpl_candidate", "project_id": "prj_one", "target": "production", "commit": self.sha, "smoke": "success", "domains_assigned": False},
                         "configuration_preserved": True, "additional_cost": 0}

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True, stderr=subprocess.DEVNULL)

    def save(self, name, value):
        (self.root / ".engineering" / name).write_text(json.dumps(value))

    def release(self, evidence=None, **values):
        options = dict(repository=self.contract["repository"], team="team_one", project="prj_one", commit=self.sha)
        options.update(values)
        return sdk.release(self.root, self.evidence if evidence is None else evidence, **options)

    def test_offline_integrity_never_uses_subprocess_or_network(self):
        with mock.patch.object(sdk.subprocess, "run", side_effect=AssertionError("must be offline")):
            self.assertEqual(sdk.verify(self.root)["network_requests"], 0)
        (self.root / "vendored.txt").write_text("edited")
        with self.assertRaises(ValueError):
            sdk.verify(self.root)

    def test_traversal_and_symlinks_are_rejected(self):
        for name in ["../private.txt", "/etc/passwd", ".git/config", ""]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                sdk.safe_path(self.root, name)
        (self.root / "link").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            sdk.safe_path(self.root, "link/vendored.txt")

    def test_empty_capabilities_runtime_budget_and_duplicate_json_fail(self):
        for field, value in [("capabilities", []), ("budget_additional_sar", True), ("budget_additional_sar", 1), ("production_runtime_dependency", True), ("hub_revision", "main")]:
            row = copy.deepcopy(self.manifest)
            row[field] = value
            self.save("capabilities.json", row)
            with self.subTest(field=field), self.assertRaises(ValueError):
                sdk.verify(self.root)
        (self.root / ".engineering/capabilities.json").write_text('{"schema_version":1,"schema_version":2}')
        with self.assertRaises(ValueError):
            sdk.verify(self.root)

    def test_valid_exact_sha_receipts_are_eligible_without_deployment(self):
        result = self.release()
        self.assertEqual(result["status"], "eligible-for-promotion")
        self.assertEqual(result["deployment_id"], "dpl_candidate")

    def test_cross_project_wrong_team_and_stale_sha_fail(self):
        for option in [dict(repository="https://github.com/example/two"), dict(team="team_two"), dict(project="prj_two"), dict(commit="b" * 40)]:
            with self.subTest(option=option), self.assertRaises(ValueError):
                self.release(**option)

    def test_dirty_checkout_and_unknown_identity_fail(self):
        (self.root / "new.txt").write_text("unreviewed")
        with self.assertRaises(ValueError):
            self.release()
        (self.root / "new.txt").unlink()
        self.contract["identity_verified"] = False
        self.save("project.json", self.contract)
        with self.assertRaises(ValueError):
            self.release()

    def test_failed_pending_skipped_and_stale_checks_block_release(self):
        for conclusion in ["pending", "failure", "cancelled", "skipped", None]:
            row = copy.deepcopy(self.evidence)
            row["checks"]["unit"]["conclusion"] = conclusion
            with self.subTest(conclusion=conclusion), self.assertRaises(ValueError):
                self.release(row)
        row = copy.deepcopy(self.evidence)
        row["checks"]["build"]["commit"] = "b" * 40
        with self.assertRaises(ValueError):
            self.release(row)

    def test_missing_review_rollback_smoke_or_zero_cost_evidence_blocks(self):
        for field in ["review", "rollback", "stage", "configuration_preserved", "additional_cost"]:
            row = copy.deepcopy(self.evidence)
            del row[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.release(row)
        for field, value in [("project_id", "prj_other"), ("smoke", "failure"), ("target", "preview"), ("domains_assigned", True)]:
            row = copy.deepcopy(self.evidence)
            row["stage"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.release(row)

    def test_private_registry_prevents_shared_deployment_targets(self):
        path = self.root / "registry.json"
        one = {"repository": self.contract["repository"], "visibility": "private", "vercel": self.contract["vercel"]}
        data = {"schema_version": 1, "projects": [one]}
        path.write_text(json.dumps(data))
        self.assertEqual(sdk.registry(path)["projects"], 1)
        two = copy.deepcopy(one)
        two["repository"] = "https://github.com/example/two"
        data["projects"].append(two)
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            sdk.registry(path)
        one["visibility"] = "public"
        path.write_text(json.dumps({"schema_version": 1, "projects": [one]}))
        with self.assertRaises(ValueError):
            sdk.registry(path)

    def test_mcp_is_read_only_and_selective(self):
        request = lambda method, params={}: {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        initialized = sdk.rpc(request("initialize", {"protocolVersion": "2025-03-26"}), self.root)
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-03-26")
        listed = sdk.rpc(request("tools/list"), self.root)["result"]["tools"]
        self.assertEqual(len(listed), 2)
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in listed))
        found = sdk.rpc(request("tools/call", {"name": "engineering_discover", "arguments": {"query": "webgpu"}}), self.root)
        self.assertIn('"candidate"', found["result"]["content"][0]["text"])
        self.assertTrue(any(row["id"] == "github/spec-kit" for row in sdk.catalog("spec-kit")))
        self.assertTrue(any(row["id"] == "provider:GitHub" and row["status"] == "environment-specific" for row in sdk.catalog("provider:GitHub")))
        denied = sdk.rpc(request("tools/call", {"name": "deploy", "arguments": {}}), self.root)
        self.assertTrue(denied["result"]["isError"])
        self.assertIsNone(sdk.rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.root))

    def test_mcp_stdio_accepts_multiple_requests_without_logging_payloads(self):
        messages = ["not json", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}), json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})]
        result = subprocess.run(["python3", str(ROOT / "sdk/engineering_sdk.py"), "mcp", "--project", str(self.root)], input="\n".join(messages)+"\n", capture_output=True, text=True, check=True)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[-1]["id"], 2)
        self.assertEqual(result.stderr, "")
