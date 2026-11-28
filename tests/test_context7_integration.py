"""Context7 MCP integration: host config, role policy, MASTER sections, probe guards, evidence.

Offline by default. GAIE_LIVE_CONTEXT7=1 also runs the probe against the real endpoint.
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENDPOINT = "https://mcp.context7.com/mcp"
POLICY = json.loads((ROOT / "governance/policies/context7.json").read_text())
ROLES = [role["id"] for role in json.loads((ROOT / "governance/agent-roles.json").read_text())["roles"]]
EVIDENCE_PATH = ROOT / "docs/evidence/gaie-20-layers/context7.json"
PROBE_PATH = ROOT / "integrations/context7/probe.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("context7_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HostConfig(unittest.TestCase):
    def test_mcp_json_names_only_the_remote_endpoint_and_no_key(self):
        config = json.loads((ROOT / ".mcp.json").read_text())
        server = config["mcpServers"]["context7"]
        self.assertEqual(server["type"], "http")
        self.assertEqual(server["url"], ENDPOINT)
        self.assertEqual(set(server), {"type", "url"}, "no headers: a key or placeholder is never committed")
        self.assertNotIn("command", server, "remote only: nothing is installed or started")

    def test_no_key_shaped_value_in_committed_files(self):
        key_shape = re.compile(r"ctx7sk[-_][A-Za-z0-9-]{8,}")
        for path in (ROOT / ".mcp.json", ROOT / "governance/policies/context7.json", EVIDENCE_PATH,
                     PROBE_PATH, ROOT / "integrations/context7/README.md"):
            self.assertIsNone(key_shape.search(path.read_text()), path)


class RolePolicy(unittest.TestCase):
    def test_every_specialist_role_is_covered_exactly_once(self):
        self.assertEqual(len(ROLES), 20)
        self.assertEqual(list(POLICY["roles"]), ROLES)

    def test_each_role_has_a_known_level_and_a_reason(self):
        for role, entry in POLICY["roles"].items():
            self.assertIn(entry["use"], POLICY["usage_levels"], role)
            self.assertGreater(len(entry["when"]), 20, role)

    def test_build_and_upgrade_owners_are_primary(self):
        for role in ("master-build-engine-engineer", "master-upgrade-engine-engineer", "claude-code-integration-engineer"):
            self.assertEqual(POLICY["roles"][role]["use"], "primary", role)

    def test_policy_grants_lookups_only(self):
        self.assertIn("grants no engine action", POLICY["authority"])
        self.assertEqual(POLICY["server"]["endpoint"], ENDPOINT)
        self.assertEqual(POLICY["server"]["tools"], ["resolve-library-id", "query-docs"])
        self.assertTrue(any("never send source code" in rule for rule in POLICY["data_rules"]))


class MasterDocuments(unittest.TestCase):
    def test_both_engines_carry_the_context7_section(self):
        for name in ("MASTER_BUILD", "MASTER_UPGRADE"):
            text = (ROOT / "prompts" / f"{name}.md").read_text()
            self.assertIn("## Library documentation (Context7)", text, name)
            self.assertIn("governance/policies/context7.json", text, name)
            self.assertIn("never code", text, name)
            self.assertIn(name, POLICY["engines"])


class ProbeGuards(unittest.TestCase):
    def test_refuses_any_other_host(self):
        probe = load_probe()
        for endpoint in ("http://mcp.context7.com/mcp", "https://evil.example/mcp", "https://mcp.context7.com.evil.example/mcp"):
            with self.assertRaises(SystemExit, msg=endpoint):
                probe.Client(endpoint)

    def test_refuses_every_redirect(self):
        probe = load_probe()
        request = probe.urllib.request.Request(ENDPOINT)
        with self.assertRaises(probe.urllib.error.HTTPError):
            probe.NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://evil.example/mcp")
        with self.assertRaises(SystemExit):
            probe.check_host("https://evil.example/mcp")

    def test_refuses_code_or_long_text(self):
        probe = load_probe()
        for library, question in (("x", "import os\nos.system('id')"), ("x" * 201, "q"), ("lib", "a;b`c`")):
            with self.assertRaises(SystemExit):
                probe.run(library, question)


class Evidence(unittest.TestCase):
    def test_receipt_passed_with_no_key_cost_or_provider_call(self):
        receipt = json.loads(EVIDENCE_PATH.read_text())
        self.assertEqual(receipt["status"], "passed")
        self.assertTrue(all(receipt["checks"].values()))
        self.assertEqual((receipt["keys_read_into_output"], receipt["paid_services"], receipt["provider_calls"]), (0, 0, 0))
        self.assertEqual(receipt["endpoint"], ENDPOINT)
        self.assertTrue(receipt["calls"]["resolve-library-id"]["library_id"].startswith("/"))
        self.assertGreater(receipt["calls"]["query-docs"]["chars"], 200)

    def test_server_exposes_only_read_only_lookup_tools(self):
        tools = json.loads(EVIDENCE_PATH.read_text())["tools"]
        self.assertEqual(set(tools), {"resolve-library-id", "query-docs"}, "a new tool needs a new review")
        for name, tool in tools.items():
            self.assertTrue(tool["read_only"] and not tool["destructive"], name)

    def test_host_loaded_text_matches_the_reviewed_digest(self):
        receipt = json.loads(EVIDENCE_PATH.read_text())
        loaded = receipt["host_loaded_text"]
        self.assertEqual(loaded["surface_sha256"], POLICY["server"]["reviewed_surface"]["sha256"],
                         "server instructions or tool descriptions changed: review the new text, then re-pin")
        self.assertEqual(loaded["reviewed_surface_sha256"], loaded["surface_sha256"])
        self.assertTrue(receipt["checks"]["host_loaded_text_matches_review"])
        for name, tool in receipt["tools"].items():
            self.assertRegex(tool["description_sha256"], "^[0-9a-f]{64}$", name)

    def test_receipt_was_made_by_the_committed_probe(self):
        receipt = json.loads(EVIDENCE_PATH.read_text())
        self.assertEqual(receipt["generator"]["sha256"], hashlib.sha256(PROBE_PATH.read_bytes()).hexdigest(),
                         "probe changed: regenerate with python3 integrations/context7/probe.py --out " + str(EVIDENCE_PATH.relative_to(ROOT)))

    def test_npm_record_points_to_the_remote_route(self):
        tools = json.loads((ROOT / "activation/tools.json").read_text())["tools"]
        record = next(tool for tool in tools if tool["id"] == "upstash/context7")
        self.assertIsNone(record["lock"], "no ninth npm lock: the dependency scan limit stays")
        self.assertEqual(record["remote"]["endpoint"], ENDPOINT)


@unittest.skipUnless(os.environ.get("GAIE_LIVE_CONTEXT7") == "1", "set GAIE_LIVE_CONTEXT7=1 to call the live endpoint")
class Live(unittest.TestCase):
    def test_resolve_and_query(self):
        result = load_probe().run("fastapi", "dependency injection with Depends")
        self.assertEqual(result["status"], "passed", result["checks"])


if __name__ == "__main__":
    unittest.main()
