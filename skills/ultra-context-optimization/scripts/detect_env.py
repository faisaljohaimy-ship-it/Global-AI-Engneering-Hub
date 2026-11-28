#!/usr/bin/env python3
"""Report what this machine can run, so tool choices rest on facts and not on assumptions.

    python3 detect_env.py [OUTPUT.json]

It records versions and yes/no answers only: no environment values, no account or user
names, no paths under the home directory. What a script cannot see (which tools the agent
host exposes, whether a plugin can be attached without a restart) is listed under
"ask_the_host" for the agent to answer from its own tool list.
"""
from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(os.environ.get("GAIE_TOOLS", Path.home() / ".gaie-tools"))


def version(command: str) -> str | None:
    try:
        done = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (done.stdout or done.stderr).strip().splitlines()
    return lines[0][:80] if done.returncode == 0 and lines else None


def reachable(host: str) -> bool:
    done = subprocess.run(["curl", "-s", "-o", "/dev/null", "-m", "10", "-w", "%{http_code}", f"https://{host}/"],
                          capture_output=True, text=True)
    return done.stdout.strip() not in ("", "000")


def main() -> int:
    node = version("node --version")
    node_major = int(node[1:].split(".")[0]) if node and node.startswith("v") else 0
    facts = {
        "system": platform.system(), "machine": platform.machine(), "cpus": os.cpu_count(),
        "memory_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1) if hasattr(os, "sysconf") else None,
        "python": platform.python_version(),
        "versions": {name: version(command) for name, command in {
            "uv": "uv --version", "node": "node --version", "npm": "npm --version", "git": "git --version",
            "ripgrep": "rg --version", "pyright": "pyright --version", "docker": "docker --version"}.items()},
        "no_network_namespace": subprocess.run(["unshare", "-n", "true"], capture_output=True).returncode == 0 if shutil.which("unshare") else False,
        "installed_here": {name: (TOOLS / path).exists() for name, path in {
            "headroom": "headroom/venv/bin/python", "serena": "serena/venv/bin/serena",
            "repomix": "repomix/node_modules/.bin/repomix", "context-mode": "context-mode/node_modules/context-mode/server.mjs",
            "node24": "node24/bin/node"}.items()},
        "reachable": {host: reachable(host) for host in ("pypi.org", "registry.npmjs.org", "nodejs.org", "mcp.context7.com")},
    }
    sg = version("sg --version")
    support = {
        "headroom in-process (hr)": "SUPPORTED" if sys.version_info >= (3, 11) else "UNSUPPORTED",
        "compression without network": "SUPPORTED" if facts["no_network_namespace"] else "PARTIALLY SUPPORTED",
        "serena one-shot (sym)": "SUPPORTED" if sys.version_info >= (3, 11) else "UNSUPPORTED",
        "context-mode server": "SUPPORTED" if node_major >= 24 or facts["installed_here"]["node24"] else "PARTIALLY SUPPORTED",
        "context7": "SUPPORTED" if facts["reachable"]["mcp.context7.com"] else "REQUIRES OWNER ACTION",
        "ripgrep": "SUPPORTED" if facts["versions"]["ripgrep"] else "UNSUPPORTED",
    }
    facts["support"] = support
    facts["notes"] = [note for note in (
        "`sg` on PATH is not ast-grep; use the ast-grep launcher" if not (sg and "ast-grep" in sg) and shutil.which("sg") else None,
        f"system Node is {node}; Context Mode 2.x needs Node 24.15 or newer" if node_major < 24 else None,
    ) if note]
    facts["ask_the_host"] = [
        "Can an MCP server or plugin be attached to the running session, or only after a restart?",
        "Does the host expose a native language-server tool?",
        "Does the host load tool definitions on demand?",
        "Who manages prompt caching and context compaction: the host, or the agent?",
    ]
    text = json.dumps(facts, indent=1)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text + "\n", encoding="utf-8")
    for name, state in support.items():
        print(f"{state:22} {name}")
    for note in facts["notes"]:
        print("note:", note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
