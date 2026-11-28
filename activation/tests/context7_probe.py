"""Context7: start the pinned server over stdio, find one library and ask for its documentation.

    python3 context7_probe.py TOOLS_DIR

Only a library name and a question are sent to the service: no code and no project text.
Prints one JSON object; exit status 1 if the service did not return documentation, which
is what happens without an API key once the shared anonymous allowance is used up.
"""
import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIBRARY, QUESTION = "pydantic-ai", "FunctionModel and TestModel for testing agents without a provider"


def main():
    package = pathlib.Path(sys.argv[1]) / "context7" / "node_modules" / "@upstash" / "context7-mcp"
    entry = json.loads((package / "package.json").read_text())["bin"]
    entry = entry if isinstance(entry, str) else next(iter(entry.values()))
    spec = importlib.util.spec_from_file_location("mcp_probe", ROOT / "skills" / "ultra-context-optimization" / "scripts" / "mcp_probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    with probe.Server(["node", str(package / entry)], timeout=60) as server:
        tools = {tool["name"] for tool in server.tools()}
        found, refused = server.call("resolve-library-id", {"libraryName": LIBRARY, "query": QUESTION})
        library = re.search(r"/[\w.\-]+/[\w.\-]*pydantic[\w.\-/]*", found)
        answer, failed = server.call("query-docs", {"libraryId": library.group(0), "query": QUESTION}) if library and not refused else ("", True)
    checks = {"server_lists_both_tools": tools >= {"resolve-library-id", "query-docs"}, "library_resolved": bool(library) and not refused,
              "documentation_returned": not failed and ("TestModel" in answer or "FunctionModel" in answer)}
    passed = all(checks.values())
    print(json.dumps({"server": "context7", "status": "passed" if passed else "failed", "checks": checks,
                      "service_said": (found if refused or not library else answer)[:120] if not passed else None}, indent=1))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
