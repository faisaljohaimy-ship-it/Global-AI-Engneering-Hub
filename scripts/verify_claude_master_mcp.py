"""Exercise native Claude Code stdio MCP against a loopback Messages fixture.

The fixture scripts the assistant's tool choices. Claude Code, MCP, and the
server-side operation are real. This cannot establish autonomous model choice,
repo approval, or a provider's billing. SPDX-License-Identifier: MIT.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


ROOT = pathlib.Path(__file__).resolve().parents[1]
MAX_WIRE_BODY = 2 * 1024 * 1024
MAX_TURNS = 5
MODEL = "claude-sonnet-4-6"
FIXTURE_PLACEHOLDER = "example-token-value"
RESULT_TEXT = "GAIE native MCP fixture completed."
HUB_URL = "https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub"
BUILD_COMMAND = "Build a local task tracker"
UPGRADE_COMMAND = "طور gaie"


class FixtureError(ValueError):
    """The native smoke did not complete the expected local protocol flow."""


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def value_sha256(value):
    return hashlib.sha256(encode(value)).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class Step:
    tool: str
    request: dict
    validate: Callable[[dict], dict]

    @property
    def wire_name(self):
        return "mcp__gaie__" + self.tool


def blocks(messages, role, kind):
    return [
        block for message in messages if message.get("role") == role
        for block in (message["content"] if isinstance(message.get("content"), list) else [])
        if isinstance(block, dict) and block.get("type") == kind
    ]


def mcp_value(result):
    """Parse only the expected successful, single JSON MCP text value."""
    if result.get("is_error") is True:
        raise FixtureError("Claude Code reported an MCP tool failure")
    content = result.get("content")
    if isinstance(content, str):
        raw = content
    elif (isinstance(content, list) and len(content) == 1
          and isinstance(content[0], dict) and content[0].get("type") == "text"):
        raw = content[0].get("text")
    else:
        raise FixtureError("Unexpected MCP result envelope")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_WIRE_BODY:
        raise FixtureError("Missing or oversized MCP result")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise FixtureError("Expected a structured MCP tool result")
    return value


def events(response, index):
    """Emit the streaming Messages API subset Claude Code consumes."""
    tool = response["type"] == "tool_use"
    first = {**response, **({"input": {}} if tool else {"text": ""})}
    delta = ({"type": "input_json_delta", "partial_json": encode(response["input"]).decode()}
             if tool else {"type": "text_delta", "text": response["text"]})
    events_data = (
        {"type": "message_start", "message": {
            "id": f"msg_gaie_fixture_{index}", "type": "message", "role": "assistant",
            "model": MODEL, "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }},
        {"type": "content_block_start", "index": 0, "content_block": first},
        {"type": "content_block_delta", "index": 0, "delta": delta},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta",
         "delta": {"stop_reason": "tool_use" if tool else "end_turn", "stop_sequence": None},
         "usage": {"output_tokens": 0}},
        {"type": "message_stop"},
    )
    return b"".join(b"event: " + event["type"].encode() + b"\ndata: " + encode(event) + b"\n\n"
                    for event in events_data)


class Script:
    """One fresh native session with ordered positive outcome checks."""

    def __init__(self, prompt, steps, *, forbidden_tools=()):
        self.prompt = prompt
        self.steps = tuple(steps)
        self.forbidden_tools = frozenset(forbidden_tools)
        self.observations = []
        self.requests = 0
        self.proxy_rejections = 0
        self.failure = False

    def turn(self, request):
        turn = self.requests
        if turn > len(self.steps) or request.get("stream") is not True or request.get("model") != MODEL:
            raise FixtureError("Unexpected native Messages request")
        messages = request["messages"]
        users = [message for message in messages if message.get("role") == "user"]
        if not users:
            raise FixtureError("Native session did not send the plain-language request")
        first = users[0]["content"]
        first_text = first if isinstance(first, str) else "\n".join(
            part["text"] for part in first if part.get("type") == "text")
        if first_text.strip() != self.prompt:
            raise FixtureError("Native prompt differs from the expected plain-language request")
        advertised = {tool["name"] for tool in request["tools"]}
        if advertised & self.forbidden_tools:
            raise FixtureError("Native host was offered a forbidden MCP tool")

        returned = blocks(messages, "user", "tool_result")
        invoked = blocks(messages, "assistant", "tool_use")
        if len(returned) != turn or len(invoked) != turn:
            raise FixtureError("Native session did not return the expected MCP results in order")
        if turn:
            previous = self.steps[turn - 1]
            expected_id = f"toolu_gaie_fixture_{turn - 1}"
            if (returned[-1].get("tool_use_id") != expected_id
                    or invoked[-1].get("id") != expected_id
                    or invoked[-1].get("name") != previous.wire_name
                    or invoked[-1].get("input") != {"request": previous.request}):
                raise FixtureError("Returned tool result does not match the scripted tool invocation")
            value = mcp_value(returned[-1])
            summary = previous.validate(value)
            self.observations.append({"tool": previous.tool, "result_sha256": value_sha256(value),
                                      "verified": summary})
        if turn == len(self.steps):
            action = {"type": "text", "text": RESULT_TEXT}
        else:
            next_step = self.steps[turn]
            if next_step.wire_name not in advertised:
                raise FixtureError("Native runtime did not discover the required tool")
            action = {"type": "tool_use", "id": f"toolu_gaie_fixture_{turn}",
                      "name": next_step.wire_name, "input": {"request": next_step.request}}
        self.requests += 1
        return events(action, turn)


class FixtureHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def handler(script):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            # Native payloads can include machine metadata. Retain only validated summaries.
            return

        def do_CONNECT(self):
            script.proxy_rejections += 1
            self.send_error(403)

        def do_GET(self):
            self.send_error(404)

        def do_POST(self):
            parts = urllib.parse.urlsplit(self.path)
            if parts.scheme or parts.netloc or parts.path != "/v1/messages":
                script.proxy_rejections += 1
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_WIRE_BODY:
                    raise FixtureError("Invalid native request length")
                if self.headers.get("x-api-key") != FIXTURE_PLACEHOLDER:
                    raise FixtureError("Native client did not use the fixture placeholder")
                self.connection.settimeout(5)
                body = script.turn(json.loads(self.rfile.read(length)))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, KeyError, TypeError, AttributeError, OSError):
                script.failure = True
                self.send_error(422)
    return Handler


def isolated_env(state, endpoint):
    # Supply only a fixed, non-provider placeholder for the native protocol fixture.
    # The local proxy refuses CONNECT and non-Messages destinations.
    paths = {name: state / name for name in ("config", "cache", "home", "temp", "data")}
    for path in paths.values():
        path.mkdir(mode=0o700)
    return {
        "PATH": os.defpath, "LANG": "C.UTF-8", "HOME": str(paths["home"]),
        "CLAUDE_CONFIG_DIR": str(paths["config"]), "XDG_CONFIG_HOME": str(paths["config"]),
        "XDG_CACHE_HOME": str(paths["cache"]), "XDG_DATA_HOME": str(paths["data"]),
        "TMPDIR": str(paths["temp"]), "ANTHROPIC_BASE_URL": endpoint,
        "ANTHROPIC_API_KEY": FIXTURE_PLACEHOLDER, "NO_PROXY": "127.0.0.1",
        "HTTP_PROXY": endpoint, "HTTPS_PROXY": endpoint, "ALL_PROXY": endpoint,
        "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }


def session(binary, repo, state, script, bridge_args=()):
    """Launch the actual host against only the configured local fixture and MCP."""
    with FixtureHTTPServer(("127.0.0.1", 0), handler(script)) as server:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        env = isolated_env(state, endpoint)
        config = state / "mcp.json"
        config.write_bytes(encode({"mcpServers": {"gaie": {
            "type": "stdio", "command": sys.executable, "args": [
                "-m", "engineering_os.claude_bridge", "--project", "gaie", *bridge_args,
            ], "env": {"PYTHONPATH": str(repo), "PYTHONDONTWRITEBYTECODE": "1"},
        }}}))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        tools = ",".join(sorted({step.wire_name for step in script.steps}))
        try:
            completed = subprocess.run([
                str(binary), "--bare", "--print", "--no-session-persistence",
                "--setting-sources", "", "--output-format", "json", "--strict-mcp-config",
                "--mcp-config", str(config), "--tools", "", "--allowedTools", tools,
                "--model", MODEL, "--max-turns", str(MAX_TURNS), "--", script.prompt,
            ], cwd=state, env=env, capture_output=True, timeout=60, check=False)
        finally:
            server.shutdown()
            thread.join(timeout=5)
    if script.failure or completed.returncode or script.proxy_rejections:
        raise FixtureError("Native session failed its isolated MCP exchange")
    decoded = json.loads(completed.stdout)
    if (decoded.get("is_error") is not False or decoded.get("result") != RESULT_TEXT
            or len(script.observations) != len(script.steps)
            or script.requests != len(script.steps) + 1):
        raise FixtureError("Native CLI did not complete all scripted MCP calls")
    return {"plain_prompt_sha256": value_sha256(script.prompt), "fresh_session": True,
            "native_mcp_results": script.observations, "loopback_messages_requests": script.requests}


def count_layers(value):
    identifiers = [layer["id"] for layer in value["layers"]]
    if identifiers != [f"L{index:02d}" for index in range(1, 21)]:
        raise FixtureError("Native MCP did not return the twenty architecture identifiers")
    return {"architecture_layers": len(identifiers)}


def verify_blocked(value):
    if value.get("status") != "approval-required" or value.get("master_tools_enabled") is not False:
        raise FixtureError("Unapproved MASTER operations appeared available in Claude Code")
    return {"status": "approval-required", "master_tools_enabled": False}


def read_version(binary, state):
    # Keep the version probe within the same local-only, fresh home policy.
    env = isolated_env(state, "http://127.0.0.1:9")
    probe = subprocess.run([str(binary), "--version"], cwd=state, env=env, timeout=10,
                           capture_output=True, text=True, check=True)
    result = probe.stdout.strip()
    if not result.endswith("(Claude Code)") or len(result) > 100:
        raise FixtureError("Expected the native Claude Code binary")
    return result


def fixture_git(checkout, *args):
    return subprocess.run(["git", "-C", str(checkout), *args], env={
        "PATH": os.defpath, "LC_ALL": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ALLOW_PROTOCOL": "", "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "GAIE native fixture", "GIT_COMMITTER_NAME": "GAIE native fixture",
        "GIT_AUTHOR_EMAIL": "gaie-fixture@example.invalid", "GIT_COMMITTER_EMAIL": "gaie-fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    }, timeout=10, capture_output=True, text=True, check=True).stdout.strip()


def fixture_routes():
    shared = {"schema_version": 1, "status": "routed", "read_only": False, "write_allowed": True}
    return {
        BUILD_COMMAND: {**shared, "engine": "MASTER_BUILD", "intent": "build", "verb": "build",
                        "scope": "comprehensive", "prompt": "prompts/MASTER_BUILD.md",
                        "skill": "gaie-build", "target_scope": "new-project", "targets": []},
        UPGRADE_COMMAND: {**shared, "engine": "MASTER_UPGRADE", "intent": "upgrade", "verb": "upgrade",
                          "scope": "comprehensive", "prompt": "prompts/MASTER_UPGRADE.md",
                          "skill": "gaie-upgrade", "target_scope": "single-project",
                          "targets": [{"id": "gaie", "repository": HUB_URL, "workspace_matches": True}]},
    }


def create_approval_fixture(root):
    """Use six tiny synthetic Git blobs. These do not approve the real upstream PR."""
    from engineering_os.master_approval import SOURCE_PATHS

    checkout = root / "synthetic-source"
    checkout.mkdir(mode=0o700)
    router = (
        "import json\nimport sys\nfrom pathlib import Path\n"
        "if sys.argv[1] != 'route' or sys.argv[-2] != '--':\n    raise SystemExit(1)\n"
        f"routes = json.loads({encode(fixture_routes()).decode()!r})\n"
        "route = routes.get(sys.argv[-1])\n"
        "if route is None:\n    print(json.dumps({'schema_version': 1, 'status': 'needs-clarification'}))\n"
        "    raise SystemExit(2)\n"
        "if route['targets']:\n"
        "    if sys.argv[2] != '--workspace' or not (Path(sys.argv[3]) / 'fixture-project.txt').is_file():\n"
        "        raise SystemExit(1)\n"
        "print(json.dumps(route))\n"
    )
    for relative in SOURCE_PATHS:
        target = checkout / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (router if relative.endswith("/gaie_router.py") else "{}\n" if relative.endswith(".json")
                else "# Synthetic prompt pin for native MCP fixtures only\n")
        target.write_text(data, encoding="utf-8")
    (checkout / "fixture-project.txt").write_text("Synthetic fixture workspace.\n", encoding="utf-8")
    fixture_git(checkout, "init", "--quiet", "--initial-branch=main")
    fixture_git(checkout, "config", "--local", "core.hooksPath", os.devnull)
    fixture_git(checkout, "remote", "add", "origin", HUB_URL)
    fixture_git(checkout, "add", "--", ".")
    fixture_git(checkout, "commit", "--quiet", "-m", "Synthetic MASTER smoke fixture")
    revision = fixture_git(checkout, "rev-parse", "HEAD")
    fixture_git(checkout, "update-ref", "refs/remotes/origin/main", revision)
    approval = root / "synthetic-approval.json"
    with os.fdopen(os.open(approval, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(encode({"schema_version": 1, "repository": HUB_URL, "revision": revision,
                             "approved_engines": ["MASTER_BUILD", "MASTER_UPGRADE"],
                             "source_sha256": {relative: file_digest(checkout / relative)
                                               for relative in SOURCE_PATHS}}))
    return checkout, approval, revision


def verify_route(engine, revision):
    def validate(value):
        result = value.get("route", value)
        if (result.get("engine") != engine or result.get("status") != "routed"
                or result.get("master_approval", {}).get("revision") != revision):
            raise FixtureError("Native route did not resolve the approved fixture engine")
        return {"engine": engine, "fixture_revision": revision}
    return validate


def verify_execution(engine, revision, operations):
    def validate(value):
        stages = value.get("stages")
        if (value.get("engine") != engine or value.get("status") != "local-verified"
                or value.get("approval_revision") != revision or value.get("local_profile_verified") is not True
                or value.get("production_mutations") != 0 or value.get("provider_calls") != 0
                or not isinstance(stages, list) or [stage["operation"] for stage in stages] != operations
                or any(stage["status"] != "completed" for stage in stages)):
            raise FixtureError("Native execution did not verify the expected local engine stages")
        if engine == "MASTER_BUILD":
            checks = stages[-1]["summary"]["checks"]
            if "restart-persistence" not in checks:
                raise FixtureError("Generated application did not verify persisted behavior")
            return {"engine": engine, "operations": operations, "generated_runtime_verified": True}
        repair, replay = stages[1]["summary"], stages[2]["summary"]
        if (repair.get("status") != "repair-verified" or replay.get("rollback_verified") is not True
                or replay.get("receipt_sha256") != repair.get("receipt_sha256")):
            raise FixtureError("SQLite repair and replay did not verify an identical receipt")
        return {"engine": engine, "operations": operations, "rollback_replayed": True}
    return validate


def master_sessions(binary, repo, root):
    checkout, approval, revision = create_approval_fixture(root)
    shared = ["--master-approval", str(approval), "--master-approval-sha256", file_digest(approval),
              "--master-source-root", str(checkout), "--master-workspace", str(checkout)]
    destination = root / "generated-app"
    settings = '{"foreign_keys":false,"atomic_batches":true,"deduplicate":false}'
    scenarios = (
        ("build", BUILD_COMMAND, "MASTER_BUILD", {"generation": {
            "schema_version": 1, "project": "gaie", "source_revision": revision,
            "resources": [{"name": "tasks", "fields": [
                {"name": "title", "type": "text", "required": True}]}],
        }}, ["architecture", "factory-generate"], ["--destination", str(destination)]),
        ("upgrade", UPGRADE_COMMAND, "MASTER_UPGRADE", {"repair": {
            "schema_version": 1, "project": "gaie", "settings_json": settings,
            "settings_sha256": hashlib.sha256(settings.encode()).hexdigest(),
        }}, ["architecture", "healing-repair", "healing-replay"], []),
    )
    runs = {}
    for name, command, engine, inputs, operations, build_args in scenarios:
        state = root / name
        state.mkdir(mode=0o700)
        request = {"command": command, "workflow": {"schema_version": 1, "project": "gaie",
                    "mode": "execute", "inputs": inputs}}
        steps = [Step("gaie_master_route", {"command": command}, verify_route(engine, revision)),
                 Step("gaie_master_execute", request, verify_execution(engine, revision, operations))]
        runs[name] = session(binary, repo, state, Script(command, steps), [*shared, *build_args])
        runs[name]["approval_scope"] = "synthetic-isolated-git-fixture"
    if not (destination / "manifest.json").is_file() or fixture_git(checkout, "status", "--porcelain"):
        raise FixtureError("Generated local output or original synthetic workspace did not match expectations")
    return runs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", required=True, type=pathlib.Path,
                        help="Existing locally reviewed Claude Code executable")
    parser.add_argument("--architecture-only", action="store_true",
                        help="Verify the host connection without a synthetic Master approval fixture")
    args = parser.parse_args(argv)
    try:
        binary = args.claude.resolve(strict=True)
        binary_digest = file_digest(binary)
        inputs = ["scripts/verify_claude_master_mcp.py", "engineering_os/claude_bridge.py",
                  "engineering_os/intelligence.py", "engineering_os/control.py"]
        if not args.architecture_only:
            inputs.extend(["engineering_os/master_approval.py", "engineering_os/master_workflow.py",
                           "engineering_os/capability_scope.py", "engineering_os/factory_generate.py",
                           "engineering_os/healing_runtime.py"])
        source_digests = {name: file_digest(ROOT / name) for name in inputs}
        with tempfile.TemporaryDirectory(prefix="gaie-native-mcp-", dir="/tmp") as folder:
            root = pathlib.Path(folder)
            version_state = root / "version"
            version_state.mkdir(mode=0o700)
            version = read_version(binary, version_state)
            state = root / "architecture"
            state.mkdir(mode=0o700)
            layers = Script("Inspect the engineering architecture.",
                            [Step("gaie_architecture", {}, count_layers)])
            runs = {"architecture": session(binary, ROOT, state, layers)}
            if not args.architecture_only:
                state = root / "unapproved"
                state.mkdir(mode=0o700)
                blocked = Script(BUILD_COMMAND, [Step("gaie_master_status", {}, verify_blocked)],
                                 forbidden_tools=("mcp__gaie__gaie_master_route", "mcp__gaie__gaie_master_execute"))
                runs["unapproved"] = session(binary, ROOT, state, blocked)
                runs.update(master_sessions(binary, ROOT, root))
        if binary_digest != file_digest(binary) or source_digests != {name: file_digest(ROOT / name) for name in inputs}:
            raise FixtureError("Source or native binary changed while collecting smoke evidence")
        report = {
            "schema_version": 1, "status": "passed", "claude_code_version": version,
            "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "binary_sha256": binary_digest, "source_sha256": source_digests,
            "native_stdio_mcp_exercised": True, "tool_selection": "scripted-loopback-messages-fixture",
            "autonomous_model_selection_verified": False, "hosted_model_calls": 0,
            "real_upstream_master_approval_verified": False, "additional_provider_cost": 0, "sessions": runs,
        }
        print(encode(report).decode())
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        print("Native Claude MCP fixture failed; check local runtime, approval fixture and tool receipts.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
