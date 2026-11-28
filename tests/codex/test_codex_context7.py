"""Check the disabled profile and native Codex transport to a loopback fixture."""

import http.server
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "integrations/context7-codex/config.toml"
POLICY = ROOT / "governance/policies/context7.json"
ENDPOINT = "https://mcp.context7.com/mcp"
TOKEN_NAME = "GAIE_CODEX_CONTEXT7_TOKEN"
TOOLS = ["resolve-library-id", "query-docs"]
FIXTURE_TOKEN = "synthetic-context7-loopback-fixture"


def native_environment(home, config_dir):
    return {
        "PATH": os.defpath,
        "HOME": str(home),
        "CODEX_HOME": str(config_dir),
        "XDG_CONFIG_HOME": str(home),
        "TMPDIR": str(home),
        "LANG": "C.UTF-8",
    }


class DocumentationFixture(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(405)
        self.end_headers()

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = request["method"]
        args = request.get("params", {})
        authorized = self.headers.get("Authorization") == f"Bearer {FIXTURE_TOKEN}"
        self.server.requests_on_wire.append((self.path, method, args, authorized))
        if self.path != "/mcp" or not authorized:
            self.send_response(403)
            self.end_headers()
            return
        if "id" not in request:
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            result = {
                "protocolVersion": args["protocolVersion"],
                "serverInfo": {"name": "synthetic-documentation", "version": "1"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": [
                {"name": name, "inputSchema": {"type": "object"}}
                for name in (*TOOLS, "outside-profile")
            ]}
        elif method == "tools/call":
            response = "/fixture/docs" if args["name"] == TOOLS[0] else "synthetic docs proof"
            result = {"content": [{"type": "text", "text": response}]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Context7CodexProfileTests(unittest.TestCase):
    def test_profile_defines_one_disabled_server_with_two_tools(self):
        profile = tomllib.loads(PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(profile, {"mcp_servers": {"context7": {
            "enabled": False,
            "required": False,
            "url": ENDPOINT,
            "bearer_token_env_var": TOKEN_NAME,
            "enabled_tools": TOOLS,
            "default_tools_approval_mode": "prompt",
            "startup_timeout_sec": 10,
            "tool_timeout_sec": 20,
        }}})

    def test_profile_matches_the_shared_context7_policy_when_integrated(self):
        if not POLICY.is_file():
            self.skipTest("the shared Context7 policy must land in PR #31")
        shared = json.loads(POLICY.read_text(encoding="utf-8"))["server"]
        profile = tomllib.loads(PROFILE.read_text(encoding="utf-8"))["mcp_servers"][shared["name"]]
        self.assertEqual((shared["transport"], profile["url"]), ("http", shared["endpoint"]))
        self.assertEqual(profile["enabled_tools"], shared["tools"])

    @unittest.skipUnless(os.environ.get("GAIE_CHECK_CODEX_CONTEXT7") == "1",
                         "set GAIE_CHECK_CODEX_CONTEXT7=1 to verify the native Codex CLI")
    def test_native_codex_reads_the_disabled_profile_in_a_fresh_home(self):
        codex = shutil.which("codex")
        self.assertIsNotNone(codex, "native verification requires Codex on PATH")
        with tempfile.TemporaryDirectory(prefix="gaie-codex-context7-") as temp:
            home = Path(temp)
            config_dir = home / ".codex"
            config_dir.mkdir(mode=0o700)
            config = config_dir / "config.toml"
            config.write_bytes(PROFILE.read_bytes())
            config.chmod(0o600)
            result = subprocess.run(
                [codex, "mcp", "get", "context7", "--json"], cwd=home,
                env=native_environment(home, config_dir),
                capture_output=True, text=True, check=True, timeout=20,
            )
            native = json.loads(result.stdout)
            self.assertFalse(native["enabled"])
            self.assertEqual(native["enabled_tools"], TOOLS)
            self.assertEqual(native["transport"]["type"], "streamable_http")
            self.assertEqual(native["transport"]["url"], ENDPOINT)
            self.assertEqual(native["transport"]["bearer_token_env_var"], TOKEN_NAME)
            self.assertIsNone(native["transport"]["http_headers"])
            self.assertIsNone(native["transport"]["env_http_headers"])
            self.assertEqual(config.read_bytes(), PROFILE.read_bytes())

    @unittest.skipUnless(os.environ.get("GAIE_CHECK_CODEX_CONTEXT7") == "1",
                         "set GAIE_CHECK_CODEX_CONTEXT7=1 to verify native loopback transport")
    def test_native_codex_dispatches_only_documentation_tools_to_loopback(self):
        codex = shutil.which("codex")
        self.assertIsNotNone(codex, "native verification requires Codex on PATH")
        with tempfile.TemporaryDirectory(prefix="gaie-c7-") as temp, \
                http.server.ThreadingHTTPServer(("127.0.0.1", 0), DocumentationFixture) as server:
            home = Path(temp)
            config_dir = home / ".codex"
            config_dir.mkdir(mode=0o700)
            server.requests_on_wire = []
            port = server.server_port
            fixture_profile = PROFILE.read_text(encoding="utf-8").replace(
                ENDPOINT, f"http://127.0.0.1:{port}/mcp"
            ).replace("enabled = false", "enabled = true")
            fixture_provider = (
                'model = "unused-fixture"\nmodel_provider = "fixture"\n'
                "check_for_update_on_startup = false\n[analytics]\nenabled = false\n"
                '[model_providers.fixture]\nname = "Loopback fixture"\n'
                f'base_url = "http://127.0.0.1:{port}/model"\nwire_api = "responses"\n'
            )
            config = config_dir / "config.toml"
            config.write_text(fixture_provider + "\n" + fixture_profile, encoding="utf-8")
            config.chmod(0o600)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with (home / "codex.stderr").open("wb") as stderr, subprocess.Popen(
                    [codex, "app-server", "--stdio"], cwd=home,
                    env={**native_environment(home, config_dir), TOKEN_NAME: FIXTURE_TOKEN},
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                ) as process:
                    try:
                        self.check_documentation_transport(process)
                    finally:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
            finally:
                server.shutdown()
                worker.join(timeout=5)
            observed = server.requests_on_wire
            self.assertTrue(all(path == "/mcp" and authorized
                                for path, _, _, authorized in observed))
            calls = [(args["name"], args["arguments"]) for _, method, args, _ in observed
                     if method == "tools/call"]
            self.assertEqual(calls, [
                (TOOLS[0], {"libraryName": "Synthetic", "query": "public documentation topic"}),
                (TOOLS[1], {"libraryId": "/fixture/docs", "query": "public documentation topic"}),
            ])

    def check_documentation_transport(self, process):
        buffered = b""

        def request(method, params=None, request_id=None):
            nonlocal buffered
            message = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                message["params"] = params
            if request_id is not None:
                message["id"] = request_id
            process.stdin.write(json.dumps(message).encode() + b"\n")
            process.stdin.flush()
            if request_id is None:
                return None
            deadline = time.monotonic() + 15
            while (remaining := deadline - time.monotonic()) > 0:
                while b"\n" in buffered:
                    line, buffered = buffered.split(b"\n", 1)
                    output = json.loads(line)
                    if output.get("id") == request_id:
                        return output
                if select.select([process.stdout], [], [], remaining)[0]:
                    data = os.read(process.stdout.fileno(), 65536)
                    self.assertTrue(data, f"Codex app-server stopped before {method}")
                    buffered += data
            self.fail(f"Codex app-server timed out during {method}")

        self.assertIn("result", request("initialize", {
            "clientInfo": {"name": "gaie-context7-test", "version": "1"},
            "capabilities": {"experimentalApi": True},
        }, 1))
        request("initialized")
        thread = request("thread/start", {
            "ephemeral": True, "sandbox": "read-only", "approvalPolicy": "never",
        }, 2)["result"]["thread"]["id"]
        status = request("mcpServerStatus/list", {
            "threadId": thread, "serverName": "context7", "detail": "toolsAndAuthOnly",
        }, 3)["result"]["data"]
        self.assertEqual(len(status), 1)
        self.assertEqual(status[0]["name"], "context7")
        self.assertEqual(set(status[0]["tools"]), set(TOOLS))

        resolve = request("mcpServer/tool/call", {
            "threadId": thread, "server": "context7", "tool": TOOLS[0],
            "arguments": {"libraryName": "Synthetic", "query": "public documentation topic"},
        }, 4)["result"]["content"][0]["text"]
        self.assertEqual(resolve, "/fixture/docs")
        result = request("mcpServer/tool/call", {
            "threadId": thread, "server": "context7", "tool": TOOLS[1],
            "arguments": {"libraryId": resolve, "query": "public documentation topic"},
        }, 5)["result"]["content"][0]["text"]
        self.assertEqual(result, "synthetic docs proof")
        denied = request("mcpServer/tool/call", {
            "threadId": thread, "server": "context7", "tool": "outside-profile", "arguments": {},
        }, 6)
        self.assertIn("disabled", denied["error"]["message"])


if __name__ == "__main__":
    unittest.main()
