"""Project-scoped GAIE MCP server for Claude Code and other stdio hosts.

The checked-in configuration exposes bounded inline operations. An operator can
enable private memory, a project artifact root, or one new factory destination
at process startup. Tool calls cannot choose those locations or run commands.
SPDX-License-Identifier: MIT
"""

import argparse
import sys

from scripts.security_scan import secret_findings

from .capability_scope import CapabilityScope
from .master_approval import approved_route, verify_master_approval
from .mcp_local_tools import browser_qa, validate_browser_cache
from .orchestration import SECRET, canonical, load_json


PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_MESSAGE = 1024 * 1024
MAX_OUTPUT = 2 * MAX_MESSAGE
BRIDGE_TOOLS = {
    "gaie_capabilities": ("List scoped engineering operations and availability.", True),
    "gaie_master_status": ("Check whether the approved MASTER integration is enabled.", True),
    "gaie_master_route": ("Route one build or upgrade command with the approved GAIE router. Supply command.", True),
    "gaie_master_execute": ("Run the selected approved MASTER workflow. Supply command and structured workflow.", False),
    "gaie_browser_qa": ("Run the reviewed local Chromium QA fixture at the existing 20 ms budget.", True),
}


def _result(identifier, result):
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def _error(identifier, code, message):
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}


def _tool_response(text, is_error=False):
    if len(text.encode("utf-8")) > MAX_OUTPUT:
        return _tool_response("Result exceeds the MCP output limit. Narrow the request or use the local CLI.", True)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


class Bridge:
    """Authorize scopes at launch and use the same engine dispatch for every caller."""

    def __init__(self, project, *, memory_dir=None, artifact_root=None, destination=None,
                 checkpoint_dir=None, receipt_dir=None, browser_cache=None,
                 master_approval=None, master_approval_sha256=None, master_source_root=None,
                 master_workspace=None):
        self.scope = CapabilityScope(project, memory_dir=memory_dir, artifact_root=artifact_root,
                                     destination=destination, checkpoint_dir=checkpoint_dir,
                                     receipt_dir=receipt_dir)
        self.project = self.scope.project
        self.browser_cache = validate_browser_cache(browser_cache) if browser_cache is not None else None
        self.approval_args = None
        if any(value is not None for value in (master_approval, master_approval_sha256,
                                                master_source_root, master_workspace)):
            if master_approval is None or master_approval_sha256 is None:
                raise ValueError("Exact local MASTER approval is required")
            self.approval_args = {"approval_file": master_approval, "approval_sha256": master_approval_sha256,
                                  "source_root": master_source_root}
            verify_master_approval(**self.approval_args)
        self.master_workspace = master_workspace
        self.tools = dict(self.scope.tools)
        self.tools.update({name: name for name in ("gaie_capabilities", "gaie_master_status")})
        if self.approval_args is not None:
            self.tools.update({name: name for name in ("gaie_master_route", "gaie_master_execute")})
        if self.browser_cache is not None:
            self.tools["gaie_browser_qa"] = "gaie_browser_qa"
        self.initialized = False
        self.ready = False

    def list_tools(self):
        items = self.scope.list_tools()
        for name, (description, read_only) in BRIDGE_TOOLS.items():
            if name in self.tools:
                items.append({
                    "name": name, "description": description,
                    "inputSchema": {"type": "object", "properties": {"request": {"type": "object"}},
                                    "required": ["request"], "additionalProperties": False},
                    "annotations": {"readOnlyHint": read_only, "destructiveHint": False, "openWorldHint": False},
                })
        return items

    def _master_status(self):
        if self.approval_args is None:
            return {"status": "approval-required", "master_tools_enabled": False}
        try:
            approval = verify_master_approval(**self.approval_args)
        except (ValueError, OSError, TypeError, KeyError):
            return {"status": "approval-invalid", "master_tools_enabled": False}
        return {"status": "approved-source-verified", "master_tools_enabled": True,
                "revision": approval["revision"], "approval_sha256": approval["approval_sha256"]}

    def _dispatch_tool(self, operation, request):
        if operation not in BRIDGE_TOOLS:
            return self.scope.invoke(operation, request)
        if not isinstance(request, dict):
            raise ValueError("Expected a request object")
        if operation in {"gaie_capabilities", "gaie_master_status", "gaie_browser_qa"}:
            if request:
                raise ValueError("This tool expects an empty request object")
            if operation == "gaie_master_status":
                return self._master_status()
            if operation == "gaie_browser_qa":
                if self.browser_cache is None:
                    raise ValueError("Local browser scope is disabled")
                return browser_qa(self.browser_cache)
            external = self.scope.external_catalog()
            for item in external:
                item["mcp_enabled"] = item["id"] == "microsoft/playwright" and self.browser_cache is not None
                if item["id"] == "microsoft/playwright":
                    item["mcp_tool"] = "gaie_browser_qa"
                elif item["id"] == "headroomlabs-ai/headroom":
                    item["mcp_boundary"] = "Approved local CLI. The reviewed scope excludes MCP."
            return {"project": self.project, "operations": self.scope.catalog(),
                    "master": self._master_status(), "external_capabilities": external}
        expected = {"command", "workflow"} if operation == "gaie_master_execute" else {"command"}
        if self.approval_args is None or set(request) != expected:
            raise ValueError("Approved MASTER command required")
        route = approved_route(request["command"], workspace_root=self.master_workspace,
                               **self.approval_args)
        if operation == "gaie_master_route":
            return route
        from .master_workflow import run_master
        workflow = request["workflow"]
        if not isinstance(workflow, dict) or workflow.get("project") != self.project:
            raise ValueError("MASTER workflow targets another project")
        return run_master(route, workflow, approval_revision=route["master_approval"]["revision"],
                          invoke=self.scope.invoke, available=tuple(self.scope.tools.values()))

    def call(self, operation, arguments):
        try:
            if not isinstance(arguments, dict) or set(arguments) != {"request"}:
                raise ValueError("Expected a request object")
            request = arguments["request"]
            encoded = canonical(request).decode("utf-8")
            if SECRET.search(encoded) or secret_findings("mcp.json", encoded):
                raise ValueError("Credential-shaped tool input refused")
            value = self._dispatch_tool(operation, request)
            encoded = canonical(value).decode("utf-8")
            if SECRET.search(encoded) or secret_findings("mcp.json", encoded):
                raise ValueError("Credential-shaped tool output refused")
            return _tool_response(encoded)
        except (ValueError, OSError, KeyError, TypeError, SyntaxError, RecursionError, OverflowError):
            return _tool_response("GAIE rejected the request. Check the project scope, request schema and local evidence.", True)

    def handle(self, message):
        if not isinstance(message, dict):
            return _error(None, -32600, "Invalid request")
        identifier = message.get("id")
        has_id = "id" in message
        if has_id and not (type(identifier) is int or isinstance(identifier, str)):
            return _error(None, -32600, "Invalid request ID")
        if isinstance(identifier, str):
            try:
                bounded = 0 < len(identifier.encode("utf-8")) <= 128
            except UnicodeError:
                bounded = False
            if not bounded or SECRET.search(identifier) or secret_findings("mcp.json", identifier):
                return _error(None, -32600, "Invalid request ID")
        method = message.get("method")
        params = message.get("params", {})
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _error(identifier, -32600, "Invalid request")
        if not has_id:
            if method == "notifications/initialized" and self.initialized and isinstance(params, dict):
                self.ready = True
            return None
        if not isinstance(params, dict):
            return _error(identifier, -32602, "Invalid parameters")
        if method == "initialize":
            offered = params.get("protocolVersion")
            if self.initialized or not isinstance(offered, str):
                return _error(identifier, -32602, "Invalid initialization")
            self.initialized = True
            return _result(identifier, {
                "protocolVersion": offered if offered in PROTOCOLS else PROTOCOLS[0],
                "serverInfo": {"name": "gaie-engineering", "version": "1.0.0"},
                "capabilities": {"tools": {"listChanged": False}},
            })
        if method == "ping":
            return _result(identifier, {})
        if not self.ready:
            return _error(identifier, -32000, "MCP initialization required")
        if method == "tools/list":
            if set(params) - {"_meta"}:
                return _error(identifier, -32602, "Invalid listing parameters")
            return _result(identifier, {"tools": self.list_tools()})
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or name not in self.tools or set(params) - {"name", "arguments", "_meta"}:
                return _error(identifier, -32602, "Tool unavailable or invalid parameters")
            return _result(identifier, self.call(self.tools[name], params.get("arguments", {})))
        return _error(identifier, -32601, "Method not found")


def serve(bridge, input_stream, output_stream):
    """Process bounded newline-delimited messages without writing to stderr."""
    while line := input_stream.readline(MAX_MESSAGE + 1):
        if len(line) > MAX_MESSAGE:
            # Drain the rest of an oversized frame in bounded reads to keep framing.
            while line and not line.endswith(b"\n"):
                line = input_stream.readline(MAX_MESSAGE + 1)
            response = _error(None, -32700, "Message too large")
        else:
            try:
                response = bridge.handle(load_json(line.decode("utf-8")))
            except (ValueError, TypeError, RecursionError, OverflowError):
                response = _error(None, -32700, "Invalid JSON-RPC message")
        if response is not None:
            output_stream.write(canonical(response) + b"\n")
            output_stream.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--memory-dir")
    parser.add_argument("--artifact-root")
    parser.add_argument("--destination")
    parser.add_argument("--checkpoint-dir")
    parser.add_argument("--receipt-dir")
    parser.add_argument("--browser-cache")
    parser.add_argument("--master-approval")
    parser.add_argument("--master-approval-sha256")
    parser.add_argument("--master-source-root")
    parser.add_argument("--master-workspace")
    args = parser.parse_args(argv)
    try:
        bridge = Bridge(**vars(args))
    except (OSError, ValueError):
        print("GAIE MCP startup rejected the configured project or directory scope.", file=sys.stderr)
        return 1
    try:
        serve(bridge, sys.stdin.buffer, sys.stdout.buffer)
    except BrokenPipeError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
