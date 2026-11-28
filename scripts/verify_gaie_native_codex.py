"""Verify GAIE discovery in a fresh local Codex CLI without a model turn."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import time


PACKS = Path("catalog/packs.json")
ROLES = {
    "gaie_specialist": Path(".codex/agents/gaie-specialist.toml"),
    "gaie_verifier": Path(".codex/agents/gaie-verifier.toml"),
}
TIMEOUT = 30
MAX_RPC_LINE = 512 * 1024
MAX_SOURCE_BYTES = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_bytes(checkout, path):
    source = checkout / path
    require(source.resolve(strict=True) == source, f"GAIE source traverses a symlink: {path}")
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), f"GAIE source is not a regular file: {path}")
        data = stream.read(MAX_SOURCE_BYTES + 1)
    require(len(data) <= MAX_SOURCE_BYTES, f"GAIE source is too large: {path}")
    return data


def run_json(command, cwd, env, operation):
    result = subprocess.run(command, cwd=cwd, env=env, check=False, text=True,
                            encoding="utf-8", capture_output=True, timeout=TIMEOUT)
    require(result.returncode == 0, f"{operation} failed with exit {result.returncode}")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise ValueError(f"{operation} returned invalid JSON") from None


def request(request_id, method, params):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def collect(process, pending):
    replies = {}
    buffer = b""
    deadline = time.monotonic() + TIMEOUT
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while pending:
            remaining = deadline - time.monotonic()
            require(remaining > 0 and selector.select(remaining), "Codex app-server discovery timed out")
            data = os.read(process.stdout.fileno(), 65536)
            require(data, "Codex app-server closed before discovery completed")
            buffer += data
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                require(len(line) <= MAX_RPC_LINE, "Codex app-server response is too large")
                reply = json.loads(line)
                request_id = reply.get("id")
                if request_id in pending:
                    method = pending.pop(request_id)
                    require("error" not in reply and "result" in reply, f"Codex app-server {method} failed")
                    replies[method] = reply["result"]
            require(len(buffer) <= MAX_RPC_LINE, "Codex app-server response is too large")
    return replies


def app_server(command, checkout, env):
    messages = [
        request(1, "initialize", {"clientInfo": {"name": "gaie-native-acceptance", "version": "1"}}),
        {"jsonrpc": "2.0", "method": "initialized"},
        request(2, "skills/list", {"cwds": [str(checkout)], "forceReload": True}),
        request(3, "thread/start", {"cwd": str(checkout), "ephemeral": True,
                                    "sandbox": "read-only", "approvalPolicy": "never"}),
    ]
    pending = {item["id"]: item["method"] for item in messages if "id" in item}
    with subprocess.Popen(
        [*command, "app-server", "--listen", "stdio://"], cwd=checkout, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as process:
        try:
            process.stdin.write(b"".join(json.dumps(item).encode() + b"\n" for item in messages))
            process.stdin.flush()
            return collect(process, pending)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()


def verify(codex, checkout, lab):
    pack_bytes = source_bytes(checkout, PACKS)
    packs = json.loads(pack_bytes)
    names = packs["packs"]["gaie-factory"]["skills"]
    require(names and all(isinstance(name, str) and re.fullmatch(r"[a-z0-9-]+", name) for name in names)
            and len(set(names)) == len(names), "invalid GAIE factory skill list")
    skills = {Path(".agents/skills") / name / "SKILL.md": name for name in names}
    instructions = Path("AGENTS.md")
    digests = {str(PACKS): hashlib.sha256(pack_bytes).hexdigest()}
    for path in (instructions, *skills, *ROLES.values()):
        digests[str(path)] = hashlib.sha256(source_bytes(checkout, path)).hexdigest()

    native_state = lab / "codex"
    native_state.mkdir(mode=0o700)
    isolated_home = lab / "home"
    isolated_home.mkdir(mode=0o700)
    (native_state / "config.toml").write_text(
        f'[projects.{json.dumps(str(checkout), ensure_ascii=False)}]\ntrust_level = "trusted"\n', encoding="utf-8")
    env = {"HOME": str(isolated_home), "CODEX_HOME": str(native_state), "PATH": os.defpath,
           "LANG": "C.UTF-8", "CODEX_NO_UPDATE": "1"}
    command = [str(codex), "--disable", "hooks", "--disable", "remote_plugin", "--disable", "enable_mcp_apps",
               "-c", 'sandbox_mode="read-only"', "-c", 'approval_policy="never"', "-c", "analytics.enabled=false"]
    # Listing reads configuration only. Each effective server is disabled before opening a native session.
    configured = run_json([*command, "mcp", "list", "--json"], checkout, env, "Codex MCP configuration listing")
    for server in configured:
        server_name = server["name"]
        require(re.fullmatch(r"[A-Za-z0-9_-]+", server_name), "Codex MCP server name cannot be overridden safely")
        command.extend(("-c", f"mcp_servers.{server_name}.enabled=false"))
    effective = run_json([*command, "mcp", "list", "--json"], checkout, env, "Codex MCP disable verification")
    require(all(server["enabled"] is False for server in effective), "Codex MCP server remains enabled")

    reports = app_server(command, checkout, env)
    entry, = reports["skills/list"]["data"]
    require(Path(entry["cwd"]) == checkout and not entry["errors"], "Codex skill discovery reported errors")
    native_skills = {Path(skill["path"]): skill for skill in entry["skills"]
                     if skill["scope"] == "repo" and skill["enabled"] is True}
    found = []
    for path, name in skills.items():
        item = native_skills.get(checkout / path, {})
        require(item.get("name", "").split(":")[-1] == name, f"Codex did not discover {name} from the checkout")
        found.append(item["name"])

    thread = reports["thread/start"]
    sandbox = thread["sandbox"]
    require(thread["thread"]["ephemeral"] is True and Path(thread["cwd"]) == checkout
            and sandbox["type"] == "readOnly" and sandbox["networkAccess"] is False
            and thread["approvalPolicy"] == "never", "Codex thread has unexpected execution permissions")
    require(str(checkout / instructions) in thread["instructionSources"], "Codex did not load the checkout AGENTS.md")

    prompt = run_json([*command, "debug", "prompt-input", "Local GAIE discovery check."],
                      checkout, env, "Codex native prompt rendering")
    tools = [tool for message in prompt if message.get("role") == "developer" for tool in message.get("tools", [])]
    spawn_tools = [tool for group in tools for tool in (group, *group.get("tools", []))
                   if tool.get("name") == "spawn_agent"]
    require(len(spawn_tools) == 1, "Codex did not expose its native spawn tool schema")
    agent_type = spawn_tools[0]["parameters"]["properties"]["agent_type"]
    _, marker, roster = agent_type["description"].partition("Available roles:\n")
    require(marker and all(re.search(rf"(?m)^{role}: \{{$", roster) for role in ROLES),
            "Codex did not expose the GAIE roles in its spawn tool roster")
    for path, expected in digests.items():
        require(hashlib.sha256(source_bytes(checkout, path)).hexdigest() == expected,
                f"GAIE source changed during discovery: {path}")
    version = reports["initialize"]["userAgent"].split(" ", 1)[0]
    return {"status": "passed", "native_cli": version, "repository_skills": sorted(found),
            "native_roles": sorted(ROLES), "instruction_source": str(instructions), "ephemeral": True,
            "sandbox": "readOnly", "network_access": False, "approval_policy": "never", "mcp_enabled": 0,
            "model_turns": 0, "source_sha256": digests}


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Run only where the host blocks outbound network for the CLI process. "
        "The native thread sandbox does not constrain the launcher."))
    parser.add_argument("--reviewed-checkout", type=Path, required=True,
                        help="exact operator-reviewed GAIE checkout to trust for this run")
    parser.add_argument("--codex", default="codex", help="path or command name of the local Codex CLI")
    args = parser.parse_args()
    try:
        binary = shutil.which(args.codex)
        require(binary, "Codex CLI is not installed or executable")
        with TemporaryDirectory(prefix="gaie-native-codex-") as directory:
            result = verify(Path(binary).resolve(), args.reviewed_checkout.resolve(strict=True), Path(directory).resolve())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error)[:300]}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
