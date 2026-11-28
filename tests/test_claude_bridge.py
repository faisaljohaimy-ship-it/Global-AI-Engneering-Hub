"""Exercise project MCP calls over the real stdio subprocess transport."""

import hashlib
import json
import pathlib
import subprocess
import tempfile
import time
import unittest

from engineering_os.claude_bridge import MAX_MESSAGE
from engineering_os.intelligence import OPERATIONS


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["gaie"]
COMMAND = [CONFIG["command"], *CONFIG["args"]]


def rpc(method, identifier=None, **params):
    message = {"jsonrpc": "2.0", "method": method, "params": params}
    if identifier is not None:
        message["id"] = identifier
    return message


def call(identifier, name, request):
    return rpc("tools/call", identifier, name=name, arguments={"request": request})


def handshake(protocol="2025-06-18"):
    return [rpc("initialize", "start", protocolVersion=protocol, capabilities={},
                clientInfo={"name": "gaie-test-client", "version": "1.0.0"}),
            rpc("notifications/initialized")]


def factory_request():
    return {"schema_version": 1, "project": "gaie", "source_revision": "a" * 40,
            "requirements": [{"id": "read", "summary": "Read approved items",
                              "acceptance": ["authorized"]}], "targets": ["api"]}


def record():
    return {"project": "gaie", "kind": "decision", "title": "Keep project history",
            "summary": "Use local project memory", "tags": ["architecture"],
            "symbols": [], "links": [], "provenance": {"engine": "claude-code", "source_sha256": "a" * 64}}


class ClaudeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)

    def process(self, messages, *options):
        lines = [message if isinstance(message, bytes) else json.dumps(message).encode("utf-8")
                 for message in messages]
        completed = subprocess.run([*COMMAND, *options], cwd=ROOT,
                                   input=b"\n".join(lines) + b"\n", capture_output=True, timeout=20, check=True)
        self.assertEqual(completed.stderr, b"")
        return [json.loads(line) for line in completed.stdout.splitlines()]

    def value(self, response):
        result = response["result"]
        self.assertFalse(result["isError"], result)
        self.assertEqual(result["content"][0]["type"], "text")
        return json.loads(result["content"][0]["text"])

    def test_repository_configuration_launches_and_negotiates(self):
        self.assertEqual(CONFIG["type"], "stdio")
        start, listed, ping = self.process([*handshake(), rpc("tools/list", 1), rpc("ping", 2)])
        self.assertEqual(start["id"], "start")
        self.assertEqual(start["result"]["protocolVersion"], "2025-06-18")
        self.assertFalse(start["result"]["capabilities"]["tools"]["listChanged"])
        tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
        self.assertIn("gaie_reasoning_plan", tools)
        self.assertIn("gaie_economics", tools)
        self.assertIn("gaie_cinematic", tools)
        self.assertNotIn("gaie_memory_search", tools)
        self.assertNotIn("gaie_factory_generate", tools)
        self.assertNotIn("gaie_factory_evaluate", tools)
        self.assertTrue(tools["gaie_reasoning_plan"]["annotations"]["readOnlyHint"])
        self.assertEqual(tools["gaie_reasoning_plan"]["inputSchema"]["required"], ["request"])
        self.assertEqual(ping["result"], {})

    def test_calls_use_real_engines_under_project_binding(self):
        cause = {"observations": [{"id": "storage", "status": "failed", "evidence_sha256": "a" * 64}],
                 "dependencies": {"storage": [], "app": ["storage"]}}
        healing = {"schema_version": 1, "project": "gaie", "source_sha256": "b" * 64,
                   "baseline_sha256": "a" * 64, "baseline_tests": {"smoke": "passed"},
                   "current_tests": {"smoke": "failed"}, "failures": [], "performance": [], "dependencies": [],
                   "evidence": {"project": "gaie", "source_sha256": "b" * 64, "baseline_sha256": "a" * 64,
                                "at": time.time(), "sha256": "c" * 64}}
        ledger = {"schema_version": 1, "project": "gaie",
                  "actors": [{"id": "coordinator", "role": "coordinator", "complete": False}],
                  "tasks": [], "usage": [], "overheads": []}
        inventory = {"schema_version": 1, "required_browsers": ["chromium"],
                     "max_age_seconds": 86400, "max_p95_ms": 25}
        responses = self.process([*handshake(), call(1, "gaie_root_causes", cause),
                                  call(2, "gaie_factory_plan", factory_request()),
                                  call(3, "gaie_healing_analyze", healing),
                                  call(4, "gaie_economics", ledger), call(5, "gaie_cinematic", inventory),
                                  call(6, "gaie_factory_plan", {**factory_request(), "project": "another"})])
        self.assertEqual(self.value(responses[1])["candidate_roots"], ["storage"])
        self.assertEqual(self.value(responses[2])["request"]["project"], "gaie")
        self.assertEqual(self.value(responses[3])["regressions"], ["smoke"])
        self.assertFalse(self.value(responses[4])["accounting_complete"])
        self.assertEqual(self.value(responses[5])["brief_count"], 200)
        self.assertTrue(responses[6]["result"]["isError"])

    def test_operational_tools_verify_real_runtime_over_mcp(self):
        settings = '{"foreign_keys":false,"atomic_batches":true,"deduplicate":false}'
        repair = {"schema_version": 1, "project": "gaie", "settings_json": settings,
                  "settings_sha256": hashlib.sha256(settings.encode()).hexdigest()}
        measure = {"schema_version": 1, "operation": "factory-plan",
                   "request": factory_request(), "repeats": 2}
        generation = {"schema_version": 1, "project": "gaie", "source_revision": "a" * 40,
                      "resources": [{"name": "tasks", "fields": [
                          {"name": "title", "type": "text", "required": True}]}]}
        output = self.root / "factory-output"
        responses = self.process([
            *handshake("2025-11-25"), call(1, "gaie_architecture", {}),
            call(2, "gaie_healing_repair", repair), call(3, "gaie_economics_measure", measure),
            call(4, "gaie_factory_generate", generation),
        ], "--destination", str(output))
        self.assertEqual(len(self.value(responses[1])["layers"]), 20)
        report = self.value(responses[2])
        self.assertTrue(report["rollback_verified"])
        self.assertEqual(report["status"], "repair-verified")
        self.assertEqual(self.value(responses[3])["provider_calls"], 0)
        self.assertEqual(self.value(responses[4])["verification"]["status"], "passed")
        self.assertTrue((output / "manifest.json").is_file())
        _, replay = self.process([*handshake(), call(1, "gaie_healing_replay",
                                                   {"request": repair, "report": report})])
        self.assertEqual(self.value(replay), report)

    def test_memory_is_private_project_scoped_and_exposes_no_path_arguments(self):
        memory = self.root / "memory"
        source = self.root / "source"
        source.mkdir()
        (source / "component.py").write_text("def dispatch_item():\n    return True\n", encoding="utf-8")
        responses = self.process([
            *handshake(), rpc("tools/list", 1), call(2, "gaie_memory_put", record()),
            call(3, "gaie_memory_search", {"project": "gaie", "query": "project history"}),
            call(4, "gaie_memory_search", {"project": "another", "query": "project history"}),
            call(5, "gaie_memory_index", {"project": "gaie", "path": "component.py"}),
            call(6, "gaie_memory_index", {"project": "gaie", "path": "../component.py"}),
            call(7, "gaie_memory_index", {"project": "gaie", "path": ".private/component.py"}),
            call(8, "gaie_memory_put", {**record(), "provenance": {"engine": "codex", "source_sha256": "a" * 64}}),
            rpc("tools/call", 9, name="gaie_memory_search", arguments={
                "request": {"project": "gaie", "query": "project history"}, "state_dir": str(self.root / "elsewhere")}),
        ], "--memory-dir", str(memory), "--artifact-root", str(source))
        tools = {tool["name"]: tool for tool in responses[1]["result"]["tools"]}
        self.assertFalse(tools["gaie_memory_put"]["annotations"]["readOnlyHint"])
        self.assertEqual(self.value(responses[2])["id"], self.value(responses[3])[0]["id"])
        self.assertTrue(responses[4]["result"]["isError"])
        self.assertEqual(len(self.value(responses[5])), 1)
        self.assertTrue(all(row["result"]["isError"] for row in responses[6:]))
        self.assertEqual((memory / "memory.json").stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.root / "elsewhere").exists())

    def test_malformed_frames_and_initialization_fail_closed(self):
        responses = self.process([
            rpc("tools/list", 1), b'{"jsonrpc":"2.0","id":2,"id":3,"method":"ping"}',
            b"x" * (MAX_MESSAGE * 2), *handshake("future-protocol"),
            b'{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}',
            rpc("tools/call", 4, name="gaie_run_command", arguments={"request": {}}),
            rpc("tools/list", 5), rpc("ping"), rpc("ping", 6),
        ])
        self.assertEqual(responses[0]["error"]["code"], -32000)
        self.assertEqual(responses[1]["error"]["code"], -32700)
        self.assertEqual(responses[2]["error"]["code"], -32700)
        self.assertEqual(responses[3]["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(responses[4]["error"]["code"], -32600)
        self.assertEqual(responses[5]["error"]["code"], -32602)
        self.assertGreater(len(responses[6]["result"]["tools"]), 0)
        self.assertEqual(responses[7], {"jsonrpc": "2.0", "id": 6, "result": {}})

    def test_credential_shaped_payload_is_rejected_without_echo(self):
        shaped = "sk-" + "x" * 40
        source = {**record(), "summary": shaped}
        response = self.process([*handshake(), call(1, "gaie_memory_put", source)],
                                "--memory-dir", str(self.root / "memory"))[-1]
        self.assertTrue(response["result"]["isError"])
        self.assertNotIn(shaped, json.dumps(response))
        self.assertFalse((self.root / "memory" / "memory.json").exists())

    def test_git_and_symlink_memory_directories_are_rejected_at_startup(self):
        private = self.root / "private"
        private.mkdir(mode=0o700)
        symlink = self.root / "alias"
        symlink.symlink_to(private, target_is_directory=True)
        for path in [str(ROOT / "memory-fixture-uncreated"), str(symlink)]:
            with self.subTest(path=path):
                completed = subprocess.run([*COMMAND, "--memory-dir", path], cwd=ROOT,
                                           input=b"", capture_output=True, timeout=5)
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stdout, b"")
                self.assertNotIn(path.encode(), completed.stderr)

    def test_integrated_operational_entry_points_are_discoverable(self):
        rows = self.process([*handshake(), rpc("tools/list", 1)], "--destination", str(self.root / "output"))
        names = {tool["name"] for tool in rows[1]["result"]["tools"]}
        for operation in ("architecture", "healing-repair", "healing-replay", "economics-measure", "factory-generate"):
            with self.subTest(operation=operation):
                self.assertEqual("gaie_" + operation.replace("-", "_") in names, operation in OPERATIONS)


if __name__ == "__main__":
    unittest.main()
