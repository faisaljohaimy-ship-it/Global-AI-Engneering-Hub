"""Exercise actual local engine composition with fixture-only approval metadata."""

import hashlib
import json
import pathlib
import tempfile
import time
import unittest

from engineering_os.intelligence import dispatch
from engineering_os.master_workflow import MasterWorkflowError, run_master
from engineering_os.orchestration import sha


REVISION = "a" * 40
PROJECT = "gaie-fixture"


def fixture_route(engine="MASTER_BUILD", **changes):
    """Test the executor independently of the source approval gate."""
    build = engine == "MASTER_BUILD"
    route = {
        "schema_version": 1, "status": "routed", "engine": engine,
        "intent": "build" if build else "upgrade", "prompt": f"prompts/{engine}.md",
        "read_only": False, "scope": "comprehensive", "target_scope": "new-project" if build else "single-project",
        "targets": [] if build else [{"id": PROJECT, "repository": "https://github.com/example/workflow-fixture",
                                      "workspace_matches": True}],
        "write_allowed": True, "gates": ["independent-review"],
        "master_approval": {"revision": REVISION},
    }
    return {**route, **changes}


def fixture_generation():
    return {"schema_version": 1, "project": PROJECT, "source_revision": REVISION,
            "resources": [{"name": "tasks", "fields": [
                {"name": "title", "type": "text", "required": True}]}]}


def fixture_repair():
    settings = '{"foreign_keys":false,"atomic_batches":true,"deduplicate":false}'
    return {"schema_version": 1, "project": PROJECT, "settings_json": settings,
            "settings_sha256": hashlib.sha256(settings.encode()).hexdigest()}


def fixture_request(mode="execute", **inputs):
    return {"schema_version": 1, "project": PROJECT, "mode": mode, "inputs": inputs}


def fixture_reasoning():
    source = sha({"fixture": "typed local SQLite application"})
    return {"schema_version": 1, "project": PROJECT, "task": "build",
            "source_sha256": source, "scheduling": "critical-path",
            "nodes": [{"id": "verify", "parent": None, "depends_on": [], "minutes": 1,
                       "risk": 0.1, "novelty": 0.1, "confidence": 0.9}],
            "constraints": {"max_minutes": 10, "max_parallel": 1, "max_depth": 5,
                            "max_cost_units": 0, "max_latency_ms": 1000, "min_quality": 0.1,
                            "required_checks": ["runtime"]},
            "alternatives": [{"id": "local-crud", "cost_units": 0, "latency_ms": 1,
                              "quality": 1, "evidence_ids": ["fixture-check"]}],
            "evidence": [{"id": "fixture-check", "project": PROJECT, "source_sha256": source,
                          "at": time.time(), "kind": "fixture", "sha256": source, "confidence": 0.9}]}


class MasterWorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)
        self.destination = self.root / "new-app"
        self.calls = []
        self.enabled = {"architecture", "factory-generate", "reasoning-plan", "memory-search",
                        "healing-repair", "healing-replay", "cinematic", "economics", "factory-plan"}

    def invoke(self, operation, payload):
        self.calls.append(operation)
        return dispatch(operation, payload, state_dir=self.root / "memory", artifact_root=self.destination)

    def run_workflow(self, route, request, *, invoke=None):
        return run_master(route, request, approval_revision=REVISION,
                          invoke=self.invoke if invoke is None else invoke, available=self.enabled)

    def test_build_executes_generation_and_binds_real_verification_manifest(self):
        result = self.run_workflow(fixture_route(), fixture_request(generation=fixture_generation()))
        self.assertEqual(result["status"], "local-verified")
        self.assertTrue(result["local_profile_verified"])
        self.assertFalse(result["deployment_authorized"])
        self.assertEqual(self.calls, ["architecture", "factory-generate"])
        manifest = json.loads((self.destination / "manifest.json").read_text(encoding="utf-8"))
        stage = result["stages"][-1]
        self.assertEqual(stage["summary"]["manifest_sha256"], manifest["manifest_sha256"])
        self.assertEqual(stage["result_sha256"], sha(manifest))
        self.assertIn("restart-persistence", stage["summary"]["checks"])
        self.assertEqual(result["workflow_sha256"], sha({key: value for key, value in result.items()
                                                        if key != "workflow_sha256"}))

    def test_upgrade_executes_real_sqlite_repair_and_replays_exact_receipt(self):
        result = self.run_workflow(fixture_route("MASTER_UPGRADE"), fixture_request(repair=fixture_repair()))
        self.assertEqual(result["status"], "local-verified")
        self.assertEqual(self.calls, ["architecture", "healing-repair", "healing-replay"])
        repaired, replayed = result["stages"][1:]
        self.assertEqual(repaired["summary"]["status"], "repair-verified")
        self.assertEqual(repaired["summary"]["receipt_sha256"], replayed["summary"]["receipt_sha256"])
        self.assertTrue(replayed["summary"]["rollback_verified"])
        self.assertEqual(json.loads(repaired["summary"]["candidate_json"]),
                         {"foreign_keys": True, "atomic_batches": True, "deduplicate": True})
        self.assertFalse(self.destination.exists())
        self.assertEqual(result["production_mutations"], 0)

    def test_preview_is_pure_and_exposes_missing_inputs_and_tools(self):
        self.enabled.remove("factory-generate")
        request = fixture_request(mode="preview")
        result = self.run_workflow(fixture_route(), request)
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["missing_inputs"], ["generation"])
        self.assertEqual(result["unavailable_operations"], ["factory-generate"])
        self.assertEqual(self.calls, [])
        self.assertFalse(self.destination.exists())
        blocked = self.run_workflow(fixture_route(), fixture_request(generation=fixture_generation()))
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["blockers"], ["operation-not-authorized"])
        self.assertEqual(self.calls, [])

    def test_approval_metadata_has_no_caller_supplied_replacement(self):
        request = fixture_request(generation=fixture_generation())
        route = fixture_route()
        for rejected in ({}, {**route, "master_approval": {"revision": "b" * 40}}):
            with self.subTest(rejected=rejected), self.assertRaises(MasterWorkflowError):
                self.run_workflow(rejected, request)
        with self.assertRaises(MasterWorkflowError):
            self.run_workflow(route, {**request, "approval_revision": REVISION})
        self.assertEqual(self.calls, [])

    def test_foreign_target_and_unverified_workspace_block_upgrade(self):
        route = fixture_route("MASTER_UPGRADE")
        target = route["targets"][0]
        variants = [{**route, "targets": [{**target, "id": "foreign"}]},
                    {**route, "targets": [{**target, "workspace_matches": False}]},
                    {**route, "write_allowed": False},
                    {**route, "target_scope": "all-registered-projects"},
                    {**route, "scope": "focused", "focus": ["interface"]}]
        for rejected in variants:
            with self.subTest(rejected=rejected):
                result = self.run_workflow(rejected, fixture_request(repair=fixture_repair()))
                self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.calls, [])

    def test_all_stage_inputs_checked_for_project_before_execution(self):
        with self.assertRaises(MasterWorkflowError):
            self.run_workflow(fixture_route(), fixture_request(generation={**fixture_generation(), "project": "foreign"}))
        with self.assertRaises(MasterWorkflowError):
            self.run_workflow(fixture_route("MASTER_UPGRADE"), fixture_request(generation=fixture_generation()))
        self.assertEqual(self.calls, [])

    def test_owner_prohibition_prevents_local_repair_but_no_release_is_compatible(self):
        result = self.run_workflow(fixture_route("MASTER_UPGRADE", prohibited=["repair"]),
                                   fixture_request(repair=fixture_repair()))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blockers"], ["upstream-prohibits-local-profile"])
        self.assertEqual(self.calls, [])
        allowed = self.run_workflow(fixture_route("MASTER_UPGRADE", prohibited=["release"]),
                                    fixture_request(repair=fixture_repair()))
        self.assertEqual(allowed["status"], "local-verified")
        self.assertFalse(allowed["deployment_authorized"])

    def test_provisional_reasoning_keeps_review_pending_after_verified_generation(self):
        request = fixture_request(generation=fixture_generation(), reasoning=fixture_reasoning())
        result = self.run_workflow(fixture_route(), request)
        self.assertEqual(result["status"], "review-pending")
        self.assertEqual(result["pending_review_operations"], ["reasoning-plan"])
        self.assertTrue(result["local_profile_verified"])
        self.assertEqual(result["stages"][1]["status"], "provisional")
        self.assertEqual(result["stages"][2]["status"], "completed")

    def test_failed_reasoning_prevents_publication(self):
        reasoning = fixture_reasoning()
        reasoning["alternatives"][0]["cost_units"] = 1
        result = self.run_workflow(fixture_route(), fixture_request(generation=fixture_generation(), reasoning=reasoning))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stages"][-1]["status"], "failed")
        self.assertEqual(self.calls, ["architecture", "reasoning-plan"])
        self.assertFalse(self.destination.exists())

    def test_manifest_from_different_resources_cannot_prove_the_current_request(self):
        old = fixture_generation()
        old["resources"][0]["name"] = "other_tasks"
        receipt = dispatch("factory-generate", old, artifact_root=self.root / "other-app")

        def stale_dispatch(operation, payload):
            return receipt if operation == "factory-generate" else self.invoke(operation, payload)

        result = self.run_workflow(fixture_route(), fixture_request(generation=fixture_generation()),
                                   invoke=stale_dispatch)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stages"][-1]["status"], "failed")
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
