"""The priority-tool activation record must agree with its locks and its receipt.

These tests need none of the tools. They stop the record from claiming more than the
recorded run shows.
"""
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RECORD = json.loads((ROOT / "activation" / "tools.json").read_text())
RECEIPT = json.loads((ROOT / RECORD["receipt"]).read_text())
TOOLS = {tool["id"]: tool for tool in RECORD["tools"]}
ORDER = RECORD["labels"]


class ActivationTests(unittest.TestCase):
    def test_the_record_covers_exactly_the_priority_tools(self):
        packs = json.loads((ROOT / "catalog" / "priority-capability-packs.json").read_text())
        self.assertEqual(sorted(TOOLS), sorted(packs["priority_tools"]))
        self.assertEqual(sorted(RECEIPT["results"]), sorted(TOOLS))
        known = {pack["id"] for pack in packs["packs"]}
        for tool in TOOLS.values():
            self.assertLessEqual(set(tool.get("pack_evidence", {})), known, tool["id"])

    def test_registry_is_untouched_so_nothing_here_reads_as_approval(self):
        registry = {entry["id"]: entry for entry in json.loads((ROOT / "catalog" / "registry.json").read_text())}
        for name in TOOLS:
            self.assertEqual(registry[name]["status"], "discovered", name)

    def test_every_installed_tool_is_pinned_in_a_lock_that_matches_the_record(self):
        for tool in TOOLS.values():
            if "INSTALLED" not in tool["labels"]:
                self.assertIsNone(tool["lock"], tool["id"])
                continue
            self.assertLess(tool["published"], "2026-11-14", tool["id"])
            lock = ROOT / tool["lock"]
            if tool["ecosystem"] == "pypi":
                self.assertEqual((lock.parent / "requirements.in").read_text().strip(), f"{tool['package']}=={tool['version']}")
                text = lock.read_text()
                entries = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text)[1:]
                self.assertTrue(all("--hash=sha256:" in entry for entry in entries), tool["id"])
                block = next(entry for entry in entries if entry.startswith(f"{tool['package']}=={tool['version']}"))
                self.assertEqual(sorted(re.findall(r"sha256:([0-9a-f]{64})", block)), tool["artifact_sha256"])
            else:
                wanted = json.loads((lock.parent / "package.json").read_text())["dependencies"]
                self.assertEqual(wanted, {tool["package"]: tool["version"]})
                packages = json.loads(lock.read_text())["packages"]
                entry = packages[f"node_modules/{tool['package']}"]
                self.assertEqual((entry["version"], entry["integrity"]), (tool["version"], tool["artifact_integrity"]))
                for path, package in packages.items():
                    if path:
                        self.assertTrue(package["integrity"].startswith("sha512-"), path)
                        self.assertTrue(package["resolved"].startswith("https://registry.npmjs.org/"), path)

    def test_labels_claim_no_more_than_the_receipt_shows(self):
        for name, tool in TOOLS.items():
            labels, result = tool["labels"], RECEIPT["results"][name]
            self.assertEqual(labels, sorted(labels, key=ORDER.index), name)
            self.assertEqual("TESTED" in labels, result["status"] == "passed", name)
            self.assertEqual("BLOCKED" in labels, result["status"] == "blocked", name)
            self.assertFalse("ACTUALLY USED" in labels, name)
            if "BLOCKED" in labels:
                self.assertTrue(tool["blocked_by"] and result["reason"] and result["needs"], name)
            if tool["test"]:
                self.assertTrue((ROOT / tool["test"]).is_file(), tool["test"])
            self.assertTrue(tool["not_proven"], name)
        for server in ("microsoft/playwright-mcp", "ChromeDevTools/chrome-devtools-mcp"):
            self.assertFalse("HOST VERIFIED" in TOOLS[server]["labels"], "a probe is not an agent host")

    def test_every_passed_result_passed_in_every_case(self):
        results = RECEIPT["results"]
        agent = results["pydantic/pydantic-ai"]
        self.assertIs(agent["provider_requests_allowed"], False)
        self.assertEqual(len(agent["cases"]), 6)
        self.assertTrue(all(case["passed"] for case in agent["cases"].values()))
        self.assertEqual(agent["cases"]["unauthorised_call_is_refused"]["raised"], "Refused")
        self.assertLess(agent["cases"]["slow_tool_is_stopped"]["seconds"], 1.0)
        for server in ("microsoft/playwright-mcp", "ChromeDevTools/chrome-devtools-mcp"):
            checks = results[server]["checks"]
            self.assertEqual(set(checks), {"navigation", "snapshot", "script_and_console_write", "console_diagnostics", "screenshot", "wrong_arguments_rejected"})
            self.assertTrue(all(check["passed"] for check in checks.values()), server)
            self.assertTrue(checks["wrong_arguments_rejected"]["rejected"])
            self.assertTrue(checks["screenshot"]["png_signature"])
        self.assertEqual(results["promptfoo/promptfoo"]["stats"], {"successes": 1, "failures": 1, "errors": 0})
        self.assertEqual(results["promptfoo/promptfoo"]["npm_audit"]["high"] + results["promptfoo/promptfoo"]["npm_audit"]["critical"], 0)

    def test_tests_call_no_provider_and_the_installer_fetches_nothing_unpinned(self):
        self.assertIn("models.ALLOW_MODEL_REQUESTS = False", (ROOT / "activation/tests/pydantic_ai_typed_tool.py").read_text())
        self.assertIn('"mockllm/model"', (ROOT / "activation/tests/inspect_ai_mock_eval.py").read_text())
        self.assertIn("- echo", (ROOT / "activation/tests/promptfoo/promptfooconfig.yaml").read_text())
        script = (ROOT / "activation/activate.sh").read_text()
        self.assertIn("--require-hashes", script)
        self.assertIn("npm ci --ignore-scripts", script)
        self.assertIn("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1", script)
        self.assertFalse("@latest" in script or "npx " in script)
        self.assertIsNone(re.search(r"(API_KEY|TOKEN)=", script))

    def test_public_files_name_no_private_path(self):
        for path in (ROOT / "activation" / "tools.json", ROOT / RECORD["receipt"], ROOT / "activation" / "README.md"):
            text = path.read_text()
            for private in ("/home/", "/root/", "/Users/", "/tmp/", "@gmail", "session_0"):
                self.assertFalse(private in text, f"{path.name} contains {private}")


if __name__ == "__main__":
    unittest.main()
