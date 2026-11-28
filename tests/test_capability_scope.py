"""Verify the fixed MCP registry, project boundaries and source-bound calls."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from engineering_os.capability_scope import DESCRIPTORS, CapabilityScope, wire_name
from engineering_os.intelligence import OPERATIONS
from engineering_os.orchestration import _atomic_write


class CapabilityScopeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.scope = CapabilityScope("gaie", memory_dir=self.root / "memory", artifact_root=self.root,
                                     destination=self.root / "new-app", checkpoint_dir=self.root / "snapshots",
                                     receipt_dir=self.root / "receipts")

    def test_every_local_dispatch_has_one_fixed_descriptor(self):
        self.assertEqual(set(DESCRIPTORS), set(OPERATIONS))
        names = {tool["name"] for tool in self.scope.list_tools()}
        self.assertEqual(names, {wire_name(operation) for operation in OPERATIONS})
        self.assertEqual(len(names), len(OPERATIONS))
        self.assertEqual({row["engine"] for row in self.scope.catalog()},
                         {"control", "reasoning", "memory", "factory", "healing", "economics", "cinematic"})
        self.assertNotIn(str(self.root), json.dumps(self.scope.catalog()))
        self.assertFalse(any(name.endswith("run_command") for name in names))

    def test_mcp_enablement_requires_every_startup_scope(self):
        default = CapabilityScope("gaie")
        self.assertEqual(set(default.tools.values()), {op for op, info in DESCRIPTORS.items() if not info.needs})
        memory = CapabilityScope("gaie", memory_dir=self.root / "memory-only")
        self.assertEqual(set(memory.tools.values()) - set(default.tools.values()),
                         {"memory-put", "memory-search", "memory-graph"})
        with self.assertRaises(ValueError):
            memory.invoke("factory-generate", {"project": "gaie"})
        artifacts = CapabilityScope("gaie", memory_dir=self.root / "memory-only", artifact_root=self.root)
        self.assertIn("gaie_memory_index", artifacts.tools)
        self.assertNotIn("gaie_memory_verify", artifacts.tools)
        self.assertNotIn("gaie_memory_restore", artifacts.tools)

    def test_checkpoint_and_receipt_ids_bind_fixed_private_roots(self):
        request = {"project": "gaie", "id": "snapshot-1"}
        backup, roots = self.scope.prepare("memory-checkpoint", request)
        self.assertEqual(backup, {"project": "gaie", "destination": str(self.root / "snapshots" / "snapshot-1.json")})
        self.assertEqual(roots, {"state_dir": self.scope.memory_dir, "artifact_root": self.root})
        restore, _ = self.scope.prepare("memory-restore", request)
        self.assertEqual(restore, {"project": "gaie", "checkpoint": backup["destination"]})
        verify, _ = self.scope.prepare("memory-verify", {"project": "gaie", "id": "a" * 64,
                                                        "receipt_id": "ci-01", "receipt_sha256": "b" * 64})
        self.assertEqual(verify["receipt_path"], str(self.root / "receipts" / "ci-01.json"))
        self.assertNotIn("receipt_id", verify)
        for value in ("../outside", "sub/example", "/tmp/payload", ".hidden", "snap.json", "a\\b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.scope.prepare("memory-restore", {"project": "gaie", "id": value})
        with self.assertRaises(ValueError):
            self.scope.prepare("memory-checkpoint", {**request, "destination": "/tmp/outside"})
        with self.assertRaises(ValueError):
            self.scope.prepare("memory-verify", {"project": "gaie", "id": "a" * 64,
                                                 "receipt_path": "/tmp/outside.json", "receipt_sha256": "b" * 64})

    def test_memory_operations_bind_provenance_and_source_evidence(self):
        source = self.root / "component.py"
        source.write_text("def retry():\n    return 2\n", encoding="utf-8")
        record = {"project": "gaie", "kind": "solution", "title": "Use bounded retries", "summary": "Retry twice",
                  "tags": ["retry"], "symbols": [], "links": [],
                  "provenance": {"engine": "claude-code", "source_sha256": "a" * 64}}
        identifier = self.scope.invoke("memory-put", record)["id"]
        receipt = self.scope.receipt_dir / "check.json"
        _atomic_write(receipt, {"schema_version": 1, "status": "passed", "solution_sha256": identifier,
                                "source_sha256": {source.name: hashlib.sha256(source.read_bytes()).hexdigest()}})
        request = {"project": "gaie", "id": identifier, "receipt_id": "check",
                   "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}
        result = self.scope.invoke("memory-verify", request)
        self.assertEqual(result["verification_status"], "source-matches-recorded-test")
        source.write_text("def retry():\n    return 9\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.scope.invoke("memory-verify", request)
        alias = self.scope.receipt_dir / "alias.json"
        alias.symlink_to(receipt)
        with self.assertRaises(OSError):
            self.scope.invoke("memory-verify", {**request, "receipt_id": "alias"})

    def test_untrusted_project_and_relative_file_inputs_are_refused(self):
        for request in ({"plan": {"request": {"project": "foreign"}}},
                        {"project": "foreign", "plan": {"request": {"project": "gaie"}}}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.scope.prepare("reasoning-review", request)
        for path in ("/tmp/probe.py", "a/../probe.py", ".private/probe.py", "x//probe.py", "module.js", "n\0.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.scope.prepare("memory-index", {"project": "gaie", "path": path})
        request = {"plan": {"request": {"project": "gaie"}}, "receipts": [
            {"artifact": {"path": "artifact.json"}, "checks": [{"evidence": {"path": "../../proof.json"}}]},
        ]}
        with self.assertRaises(ValueError):
            self.scope.prepare("factory-evaluate", request)

    def test_private_directory_links_and_overlapping_roles_are_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.scope.checkpoint_dir, target_is_directory=True)
        with self.assertRaises(ValueError):
            CapabilityScope("gaie", checkpoint_dir=alias)
        with self.assertRaises(ValueError):
            CapabilityScope("gaie", memory_dir=self.scope.memory_dir, receipt_dir=self.scope.memory_dir)

    def test_approved_discovery_records_do_not_enable_execution(self):
        external = self.scope.external_catalog()
        self.assertEqual({entry["id"] for entry in external}, {"microsoft/playwright", "headroomlabs-ai/headroom"})
        self.assertNotIn("gaie_playwright", self.scope.tools)
        self.assertNotIn("gaie_headroom", self.scope.tools)
        self.assertTrue(all(entry["revision"] for entry in external))
