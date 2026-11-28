#!/usr/bin/env python3
"""Talk to a local MCP server over stdio: list its tools, or call some, and print a short result.

    python3 mcp_probe.py [--timeout S] [--out FILE] [--call NAME JSON]... -- COMMAND...

Used to prove that a locally installed server starts and answers before anyone relies on
it. It starts the server as a child process and stops it afterwards; it opens no port.
With --out, the full text of every reply is written to FILE as JSON and only one line per
call is printed.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time


class ServerError(RuntimeError):
    pass


class Server:
    """One MCP server process, spoken to with newline-delimited JSON-RPC."""

    def __init__(self, command: list[str], timeout: float = 60.0, env: dict | None = None, cwd: str | None = None):
        self.timeout = timeout
        self.counter = 0
        self.pending = b""
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=env, cwd=cwd, bufsize=0)
        started = time.perf_counter()
        try:
            hello = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                "clientInfo": {"name": "mcp-probe", "version": "1"}})
            self.info = hello.get("result", {}).get("serverInfo", {})
            self.notify("notifications/initialized")
        except Exception:
            self.close()
            raise
        self.ready_seconds = time.perf_counter() - started

    def __enter__(self) -> "Server":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for pipe in (self.process.stdin, self.process.stdout):
            try:
                pipe.close()
            except OSError:
                pass

    def write(self, message: dict) -> None:
        try:
            self.process.stdin.write((json.dumps(message) + "\n").encode())
        except OSError as problem:
            raise ServerError(f"server is gone: {problem}") from problem

    def line(self, deadline: float) -> bytes:
        """The next line of the server's output. Reads the pipe directly, so a line that
        arrived together with the previous one is not left waiting in a buffer."""
        while b"\n" not in self.pending:
            if time.time() > deadline:
                raise TimeoutError
            ready, _, _ = select.select([self.process.stdout], [], [], 0.5)
            if not ready:
                continue
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                code = self.process.wait()
                raise ServerError(f"server exited with {code}")
            self.pending += chunk
        line, _, self.pending = self.pending.partition(b"\n")
        return line

    def notify(self, method: str, params: dict | None = None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.write(message)

    def request(self, method: str, params: dict | None = None) -> dict:
        self.counter += 1
        message = {"jsonrpc": "2.0", "method": method, "id": self.counter}
        if params is not None:
            message["params"] = params
        self.write(message)
        deadline = time.time() + self.timeout
        while True:
            try:
                line = self.line(deadline)
            except TimeoutError:
                raise ServerError(f"no answer to {method} within {self.timeout:.0f} s") from None
            try:
                reply = json.loads(line)
            except ValueError:
                continue  # a log line on stdout
            if isinstance(reply, dict) and reply.get("id") == self.counter:
                return reply

    def tools(self) -> list[dict]:
        return self.request("tools/list", {}).get("result", {}).get("tools", [])

    def call(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Return the text of the reply and whether the server marked it as an error."""
        reply = self.request("tools/call", {"name": name, "arguments": arguments})
        result = reply.get("result", reply.get("error", {}))
        text = "\n".join(block.get("text", "") for block in result.get("content", []) if isinstance(block, dict))
        return text or json.dumps(result)[:400], bool(result.get("isError") or "error" in reply)


def main() -> int:
    argv = sys.argv[1:]
    if "--" not in argv:
        raise SystemExit(__doc__.split("\n\n")[1])
    split = argv.index("--")
    options, command = argv[:split], argv[split + 1:]
    timeout, calls, index, out, replies = 60.0, [], 0, None, []
    while index < len(options):
        if options[index] == "--timeout":
            timeout = float(options[index + 1])
            index += 2
        elif options[index] == "--out":
            out = options[index + 1]
            index += 2
        elif options[index] == "--call":
            calls.append((options[index + 1], json.loads(options[index + 2])))
            index += 3
        else:
            raise SystemExit(f"unknown option {options[index]}")
    try:
        with Server(command, timeout) as server:
            tools = server.tools()
            print(f"server {server.info.get('name')} {server.info.get('version')} ready in {server.ready_seconds:.1f}s, {len(tools)} tools")
            if not calls:
                for tool in tools:
                    first = (tool.get("description") or "").strip().splitlines()
                    print(f"  {tool['name']}: {first[0][:110] if first else ''}")
            for name, arguments in calls:
                began = time.perf_counter()
                text, failed = server.call(name, arguments)
                seconds = round(time.perf_counter() - began, 3)
                replies.append({"tool": name, "arguments": arguments, "seconds": seconds, "error": failed, "text": text})
                print(f"--- {name} ({seconds:.2f}s, {len(text)} chars{', error' if failed else ''})")
                if not out:
                    print(text[:1200])
    except ServerError as problem:
        print(f"mcp_probe: {problem}", file=sys.stderr)
        return 1
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(replies, handle, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
