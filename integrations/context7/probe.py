"""Context7 remote MCP probe: initialize, list tools, resolve one library, query its docs.

    python3 integrations/context7/probe.py [--library NAME --question TEXT] [--out FILE]

Talks to exactly one endpoint, https://mcp.context7.com/mcp, over MCP streamable HTTP
with the Python standard library. Nothing is installed: no npm package, no lock.

Credentials: this script never reads, prints or stores an API key.
- In a Claude Code cloud session the key is an environment network secret; the
  session's HTTPS proxy injects it into requests to mcp.context7.com.
- On a workstation, run it with CONTEXT7_API_KEY set; the value goes only into the
  Authorization header of requests to the one allowed host and is never echoed.
  Without a key the service answers from a small shared anonymous allowance.

Only a library name and a question are sent: no code and no project text. The receipt
records digests and sizes of what came back, not the documentation itself.
Exit status 0 when every check passed, 1 otherwise.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

ENDPOINT = "https://mcp.context7.com/mcp"
ALLOWED_HOST = "mcp.context7.com"
PROTOCOL = "2025-06-18"
DEFAULT_LIBRARY = "fastapi"
DEFAULT_QUESTION = "dependency injection with Depends"
MAX_BYTES = 2 * 1024 * 1024
LIBRARY_ID = re.compile(r"Context7-compatible library ID:\s*(/[\w.\-]+/[\w.\-/]+)")
SAFE_TEXT = re.compile(r"^[\w .,:/@+#'()\-]{1,200}$")


class Client:
    def __init__(self, endpoint=ENDPOINT, timeout=60):
        host = urllib.parse.urlsplit(endpoint)
        if host.scheme != "https" or host.hostname != ALLOWED_HOST:
            raise SystemExit(f"refused: endpoint must be https://{ALLOWED_HOST}/...")
        self.endpoint, self.timeout, self.session, self.next_id = endpoint, timeout, None, 0
        self.key_source = "environment variable" if os.environ.get("CONTEXT7_API_KEY") else "proxy network secret or none"

    def _post(self, payload):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL, "User-Agent": "gaie-context7-probe/1"}
        key = os.environ.get("CONTEXT7_API_KEY")
        if key:
            headers["Authorization"] = "Bearer " + key
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            self.session = response.headers.get("Mcp-Session-Id") or self.session
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise RuntimeError("response larger than the probe allows")
        return body.decode("utf-8", errors="replace")

    def request(self, method, params=None):
        self.next_id += 1
        text = self._post({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        messages = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")] or [text]
        for raw in messages:
            message = json.loads(raw)
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error'].get('message', 'error')}")
                return message["result"]
        raise RuntimeError(f"{method}: no matching response")

    def notify(self, method):
        try:
            self._post({"jsonrpc": "2.0", "method": method})
        except Exception:
            pass  # notifications have no result; a stateless server may answer 202 or 4xx

    def call(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        text = "".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")
        return text, bool(result.get("isError"))


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def run(library, question, endpoint=ENDPOINT):
    for value in (library, question):
        if not SAFE_TEXT.match(value):
            raise SystemExit("refused: library and question must be short plain text (no code, no project text)")
    client, started = Client(endpoint), time.monotonic()
    init = client.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                         "clientInfo": {"name": "gaie-context7-probe", "version": "1"}})
    client.notify("notifications/initialized")
    tools = {tool["name"]: {"required": sorted(tool.get("inputSchema", {}).get("required", [])),
                            "read_only": (tool.get("annotations") or {}).get("readOnlyHint") is True,
                            "destructive": (tool.get("annotations") or {}).get("destructiveHint") is not False}
             for tool in client.request("tools/list").get("tools", [])}
    found, found_error = client.call("resolve-library-id", {"libraryName": library, "query": question})
    match = LIBRARY_ID.search(found)
    library_id = match.group(1) if match else None
    docs, docs_error = (client.call("query-docs", {"libraryId": library_id, "query": question})
                        if library_id and not found_error else ("", True))
    checks = {
        "initialize": init.get("serverInfo", {}).get("name") == "Context7",
        "lists_resolve_library_id": "resolve-library-id" in tools,
        "lists_query_docs": "query-docs" in tools,
        "only_read_only_lookup_tools": set(tools) == {"resolve-library-id", "query-docs"}
                                       and all(v["read_only"] and not v["destructive"] for v in tools.values()),
        "library_resolved": bool(library_id) and not found_error,
        "documentation_returned": not docs_error and len(docs) >= 200,
    }
    return {
        "server": {"name": init.get("serverInfo", {}).get("name"), "version": init.get("serverInfo", {}).get("version"),
                   "protocol": init.get("protocolVersion")},
        "tools": tools,
        "calls": {
            "resolve-library-id": {"arguments": {"libraryName": library, "query": question}, "is_error": found_error,
                                   "chars": len(found), "sha256": digest(found), "library_id": library_id},
            "query-docs": {"arguments": {"libraryId": library_id, "query": question}, "is_error": docs_error,
                           "chars": len(docs), "sha256": digest(docs),
                           "first_heading": next((l.strip() for l in docs.splitlines() if l.startswith("#")), None)},
        },
        "checks": checks,
        "status": "passed" if all(checks.values()) else "failed",
        "duration_s": round(time.monotonic() - started, 2),
        "key_source": client.key_source,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--library", default=DEFAULT_LIBRARY)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--out", type=pathlib.Path, help="also write the receipt to this JSON file")
    args = parser.parse_args(argv)
    try:
        result = run(args.library, args.question)
    except (OSError, RuntimeError, ValueError) as error:
        result = {"status": "failed", "error": type(error).__name__ + ": " + str(error)[:200]}
    receipt = {
        "schema": "gaie.context7-probe/1",
        "endpoint": ENDPOINT,
        "transport": "MCP streamable HTTP (remote); nothing installed",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": {"path": "integrations/context7/probe.py",
                      "sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()},
        "keys_read_into_output": 0, "paid_services": 0, "provider_calls": 0,
        **result,
    }
    text = json.dumps(receipt, indent=1, ensure_ascii=False) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
