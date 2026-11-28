"""Drive a browser MCP server over stdio against a synthetic page and check what comes back.

    python3 mcp_browser_probe.py playwright-mcp|chrome-devtools-mcp TOOLS_DIR BROWSER OUT_DIR

Follows the acceptance line of the "browser-intelligence" pack: a local synthetic page,
an isolated browser profile, navigation, an accessibility snapshot, a screenshot, console
diagnostics, and one deliberately wrong call that the server must reject. The page is a
data: URL, so nothing is fetched. Prints one JSON object; exit status 1 if a check fails.
"""
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGE = "data:text/html,<title>Probe page</title><h1>Hello from the hub</h1><button>Go</button>"
WARN = "() => { console.warn('probe-warning'); return document.title; }"


def probe_module():
    path = ROOT / "skills" / "ultra-context-optimization" / "scripts" / "mcp_probe.py"
    spec = importlib.util.spec_from_file_location("mcp_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan(name, tools, browser, out):
    if name == "playwright-mcp":
        command = ["node", f"{tools}/playwright-mcp/node_modules/@playwright/mcp/cli.js", "--headless", "--isolated", "--no-sandbox",
                   "--browser", "chromium", "--executable-path", browser, "--output-dir", out]
        calls = [
            ("navigation", "browser_navigate", {"url": PAGE}, "Probe page", False),
            ("snapshot", "browser_snapshot", {}, 'heading "Hello from the hub"', False),
            ("script_and_console_write", "browser_evaluate", {"function": WARN}, "Probe page", False),
            ("console_diagnostics", "browser_console_messages", {}, "probe-warning", False),
            ("screenshot", "browser_take_screenshot", {"filename": "probe.png"}, "probe.png", False),
            ("wrong_arguments_rejected", "browser_click", {"element": "Go button"}, "Invalid", True),
        ]
    else:
        command = ["node", f"{tools}/chrome-devtools-mcp/node_modules/chrome-devtools-mcp/out/Default/gen/src/bin/chrome-devtools-mcp.js",
                   "--headless", "--isolated", "--executablePath", browser, "--chromeArg=--no-sandbox",
                   "--no-usage-statistics", "--no-performance-crux"]
        calls = [
            ("navigation", "new_page", {"url": PAGE}, "Probe page", False),
            ("snapshot", "take_snapshot", {"pageId": 2}, 'heading "Hello from the hub"', False),
            ("script_and_console_write", "evaluate_script", {"pageId": 2, "function": WARN}, "Probe page", False),
            ("console_diagnostics", "list_console_messages", {"pageId": 2}, "probe-warning", False),
            ("screenshot", "take_screenshot", {"pageId": 2, "filePath": f"{out}/probe.png"}, "probe.png", False),
            ("wrong_arguments_rejected", "take_snapshot", {}, "Invalid", True),
        ]
    return command, calls


def main():
    name, tools, browser, out = sys.argv[1:5]
    pathlib.Path(out).mkdir(parents=True, exist_ok=True)
    probe = probe_module()
    command, calls = plan(name, tools, browser, out)
    checks = {}
    with probe.Server(command, timeout=90, cwd=out) as server:
        tools_listed = len(server.tools())
        info = dict(server.info)
        for check, tool, arguments, expected, should_fail in calls:
            text, failed = server.call(tool, arguments)
            checks[check] = {"tool": tool, "expected_in_reply": expected, "rejected": failed,
                             "passed": expected in text and failed is should_fail}
    image = next(pathlib.Path(out).rglob("probe.png"), None)
    checks["screenshot"]["file_bytes"] = image.stat().st_size if image else 0
    checks["screenshot"]["png_signature"] = bool(image) and image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    checks["screenshot"]["passed"] = checks["screenshot"]["passed"] and checks["screenshot"]["png_signature"]
    passed = all(check["passed"] for check in checks.values())
    print(json.dumps({"server": name, "reported": info, "tools_listed": tools_listed, "page": "synthetic data: URL",
                      "profile": "isolated, in memory", "status": "passed" if passed else "failed", "checks": checks}, indent=1))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
