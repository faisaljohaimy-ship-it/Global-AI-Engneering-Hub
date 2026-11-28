"""Project-scoped GAIE MCP server for Claude Code and other stdio hosts.

The checked-in configuration exposes bounded inline operations. An operator can
enable private memory, a project artifact root, or one new factory destination
at process startup. Tool calls cannot choose those locations or run commands.
SPDX-License-Identifier: MIT
"""

import argparse
import pathlib
import sys

from scripts.security_scan import secret_findings

from .intelligence import OPERATIONS, dispatch
from .orchestration import SECRET, _safe_directory, _slug, canonical, load_json


PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_MESSAGE = 1024 * 1024
MAX_OUTPUT = 2 * MAX_MESSAGE
TOOLS = {
    "architecture": ("Inspect the twenty-layer local architecture and its evidence.", None),
    "reasoning-plan": ("Build a bounded engineering plan from constraints and evidence.", None),
    "reasoning-review": ("Review a plan with supplied verification and review receipts.", None),
    "root-causes": ("Trace observed failures on a declared dependency graph.", None),
    "memory-search": ("Find knowledge in the configured private project memory.", "memory_dir"),
    "memory-graph": ("Inspect links in the configured private project memory.", "memory_dir"),
    "memory-put": ("Record one curated item in the configured private project memory.", "memory_dir"),
    "memory-index": ("Index Python symbols in the configured project source tree.", "source_and_memory"),
    "factory-plan": ("Plan stage gates for structured engineering requirements.", None),
    "factory-evaluate": ("Verify factory artifacts within the configured project root.", "artifact_root"),
    "factory-generate": ("Generate and verify a SQLite service at the configured new destination.", "destination"),
    "healing-analyze": ("Diagnose regressions using source-bound observations.", None),
    "healing-verify": ("Check a candidate and rollback using disposable artifacts and declared assertions.", None),
    "healing-repair": ("Test and repair bounded SQLite settings in disposable storage.", None),
    "healing-replay": ("Re-run a SQLite repair report against the original supplied settings.", None),
    "economics": ("Summarize engineering usage and cost evidence for this project.", None),
    "economics-measure": ("Measure fixed offline engineering operations in this process.", None),
    "cinematic": ("Inspect original-motion implementation and current browser evidence.", None),
}
UNSCOPED = frozenset({"architecture", "root-causes", "cinematic"})
MUTATING = frozenset({"memory-put", "memory-index", "factory-generate"})
NESTED_PROJECT = {
    "reasoning-review": ("plan", "request"),
    "factory-evaluate": ("plan", "request"),
    "healing-replay": ("request",),
    "economics-measure": ("request",),
}


def _wire_name(operation):
    return "gaie_" + operation.replace("-", "_")


def _result(identifier, result):
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def _error(identifier, code, message):
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}


def _tool_response(text, is_error=False):
    if len(text.encode("utf-8")) > MAX_OUTPUT:
        return _tool_response("Result exceeds the MCP output limit. Narrow the request or use the local CLI.", True)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _absolute_path(value):
    result = pathlib.Path(value)
    if not result.is_absolute() or ".." in result.parts:
        raise ValueError("Configured paths must be absolute and canonical")
    if any(part.is_symlink() for part in (result, *result.parents)):
        raise ValueError("Symlink directory refused")
    return result


def _relative_path(value, suffix):
    if not isinstance(value, str) or not value or len(value) > 256 or "\\" in value:
        raise ValueError("Artifact path rejected")
    path = pathlib.PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or path.suffix != suffix
            or any(part.startswith(".") for part in path.parts)):
        raise ValueError("Artifact path rejected")
    return path


class Bridge:
    """Track MCP startup and authorize the subset of tools bound at launch."""

    def __init__(self, project, *, memory_dir=None, artifact_root=None, destination=None):
        self.project = _slug(project)
        self.memory_dir = _safe_directory(_absolute_path(memory_dir)) if memory_dir else None
        self.artifact_root = _absolute_path(artifact_root) if artifact_root else None
        if self.artifact_root is not None and not self.artifact_root.is_dir():
            raise ValueError("Artifact root must be an existing directory")
        self.destination = _absolute_path(destination) if destination else None
        if self.destination is not None:
            if self.destination.exists() or not self.destination.parent.is_dir():
                raise ValueError("Factory destination must be new with a private existing parent")
            _safe_directory(self.destination.parent)
        enabled = {
            None, *[name for name in ("memory_dir", "artifact_root", "destination") if getattr(self, name)]
        }
        if self.memory_dir and self.artifact_root:
            enabled.add("source_and_memory")
        self.tools = {_wire_name(op): op for op, (_, requirement) in TOOLS.items()
                      if op in OPERATIONS and requirement in enabled}
        self.initialized = False
        self.ready = False

    def list_tools(self):
        return [
            {"name": name, "description": TOOLS[op][0] + " Input uses the GAIE CLI request schema.",
             "inputSchema": {"type": "object", "properties": {"request": {"type": "object"}},
                             "required": ["request"], "additionalProperties": False},
             "annotations": {"readOnlyHint": op not in MUTATING, "destructiveHint": False,
                             "openWorldHint": False}}
            for name, op in self.tools.items()
        ]

    def _scope(self, operation, request):
        if not isinstance(request, dict):
            raise ValueError("Expected a request object")
        if "project" in request and request["project"] != self.project:
            raise ValueError("Call targets another project")
        if operation not in UNSCOPED:
            subject = request
            for key in NESTED_PROJECT.get(operation, ()):
                subject = subject[key]
            if subject["project"] != self.project:
                raise ValueError("Call targets another project")
        encoded = canonical(request).decode("utf-8")
        if SECRET.search(encoded) or secret_findings("mcp.json", encoded):
            raise ValueError("Credential-shaped tool input refused")
        if operation == "memory-index":
            _relative_path(request["path"], ".py")
            request = {**request, "engine": "claude-code"}
        elif operation == "memory-put":
            provenance = request["provenance"]
            if not isinstance(provenance, dict) or provenance.get("engine") != "claude-code":
                raise ValueError("Memory writes require Claude Code provenance")
        elif operation == "factory-evaluate":
            for receipt in request["receipts"]:
                _relative_path(receipt["artifact"]["path"], ".json")
                for check in receipt["checks"]:
                    _relative_path(check["evidence"]["path"], ".json")
        return request

    def call(self, operation, arguments):
        try:
            if not isinstance(arguments, dict) or set(arguments) != {"request"}:
                raise ValueError("Expected a request object")
            request = self._scope(operation, arguments["request"])
            artifact_root = self.destination if operation == "factory-generate" else self.artifact_root
            value = dispatch(operation, request, state_dir=self.memory_dir, artifact_root=artifact_root)
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
    args = parser.parse_args(argv)
    try:
        bridge = Bridge(args.project, memory_dir=args.memory_dir, artifact_root=args.artifact_root,
                        destination=args.destination)
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
