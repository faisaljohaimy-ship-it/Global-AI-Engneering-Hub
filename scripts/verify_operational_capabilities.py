"""Run fixed, local fixtures against the Hub's callable capability surfaces."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engineering_os.model_router import select_model
from engineering_os.orchestration import TaskStore, verify_state


def require(condition, message):
    if not condition:
        raise ValueError(message)


def child(executable, args, cwd, data=""):
    return subprocess.run(
        [executable, *args], cwd=cwd, input=data, encoding="utf-8",
        capture_output=True, timeout=15, check=True, env={"LANG": "C.UTF-8"},
    ).stdout


def sdk_probe(directory):
    metadata = directory / ".engineering"
    metadata.mkdir()
    specimen = b"Synthetic evidence for the GAIE SDK smoke check.\n"
    (metadata / "specimen.txt").write_bytes(specimen)
    # The fixture verifies local integrity. A real project's pin requires hub.py verify --strict.
    manifest = {
        "schema_version": 1, "hub_revision": "0" * 40,
        "production_runtime_dependency": False, "budget_additional_sar": 0,
        "capabilities": [{"id": "smoke-fixture", "files": [{
            "path": ".engineering/specimen.txt", "sha256": hashlib.sha256(specimen).hexdigest(),
        }]}],
    }
    (metadata / "capabilities.json").write_text(json.dumps(manifest), encoding="utf-8")
    messages = [
        {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"method": "notifications/initialized"},
        {"id": 2, "method": "tools/list"},
        {"id": 3, "method": "tools/call", "params": {"name": "engineering_verify"}},
        {"id": 4, "method": "tools/call", "params": {
            "name": "engineering_discover", "arguments": {"query": "headroom"},
        }},
    ]
    data = "".join(json.dumps({"jsonrpc": "2.0", **message}) + "\n" for message in messages)
    response = child(sys.executable, ["-I", str(ROOT / "sdk/engineering_sdk.py"), "mcp",
                                     "--project", str(directory)], directory, data)
    frames = [json.loads(line) for line in response.splitlines()]
    require([frame["id"] for frame in frames] == [1, 2, 3, 4] and
            all(frame["jsonrpc"] == "2.0" for frame in frames), "unexpected MCP responses")
    info, listing, integrity, discover = [frame["result"] for frame in frames]
    require(info["protocolVersion"] == "2025-06-18"
            and info["serverInfo"]["name"] == "engineering-sdk", "unexpected SDK handshake")
    tools = sorted(entry["name"] for entry in listing["tools"])
    require(tools == ["engineering_discover", "engineering_verify"], "unexpected SDK tools")
    require(integrity["isError"] is False and discover["isError"] is False, "SDK tool call failed")
    checked = json.loads(integrity["content"][0]["text"])
    discovered = json.loads(discover["content"][0]["text"])
    require(checked["files"] == 1 and checked["status"] == "local-integrity-verified",
            "fixture file integrity was not checked")
    require(any(row["id"] == "headroomlabs-ai/headroom" and row["status"] == "approved"
                for row in discovered), "approved Headroom catalog entry was not discovered")
    return {"version": info["serverInfo"]["version"], "tools": tools,
            "files_verified": checked["files"], "scope": "stdio synthetic project"}


def orchestration_probe(directory):
    store = TaskStore(directory / "state")
    owner = {"id": "fixture-owner", "engine": "codex", "role": "orchestrator"}
    worker = {"id": "fixture-worker", "engine": "codex", "role": "development"}
    reviewer = {"id": "fixture-reviewer", "engine": "claude-code", "role": "development"}
    task = store.create_task({
        "id": "sample-activation", "project": "synthetic-project",
        "branch": "codex/sample-activation", "paths": ["src/sample.txt"],
        "title": "Resume a synthetic project check", "priority": 0,
    }, owner, store.snapshot()["revision"])
    task = store.claim(task["id"], worker, task["version"])
    refs = [{"kind": "fixture", "sha256": hashlib.sha256(b"fixture").hexdigest()}]
    handover = store.handover(task["id"], worker, task["version"], task["lease"]["id"],
                             "Review the synthetic fixture.", refs)
    reopened = TaskStore(store.directory)
    claimed = reopened.claim(handover["id"], reviewer, handover["version"])
    snapshot = reopened.snapshot()
    require(verify_state(snapshot) and claimed["owner"] == reviewer
            and claimed["handover"]["receipts"] == refs, "task handover could not be recovered")
    return {"journal_revision": snapshot["revision"], "handover_recovered": True,
            "scope": "synthetic actor labels and a fresh TaskStore reader"}


def routing_probe(_directory):
    registry = json.loads((ROOT / "catalog/models/registry.json").read_text(encoding="utf-8"))
    decision = select_model(registry, {
        "project": "synthetic-project", "task": "code-review", "complexity": 1,
        "input_tokens": 25, "output_tokens": 25, "privacy": "public", "permissions": [],
        "max_cost_usd": 0, "min_quality": 0, "max_latency_ms": 1000,
    }, environ={})
    require(decision["decision"] == "blocked" and decision["selected"] is None
            and decision["provider_calls"] == 0, "routing accepted absent project evidence")
    return {"decision": decision["decision"], "candidates_rejected": len(decision["rejected"]),
            "scope": "local eligibility decision with absent project evidence"}


def motion_probe(directory):
    node = shutil.which("node")
    if not node:
        return None
    entry = ROOT / "scripts/verify_motion_capability.mjs"
    return json.loads(child(node, [str(entry)], directory))


def search_probe(directory):
    rg = shutil.which("rg")
    if not rg:
        return None
    expected = "اختبار الحركة"
    matched = child(rg, ["--no-config", "--fixed-strings", expected, "-"], directory,
                    f"fixture\n{expected}\n")
    require(matched == expected + "\n", "literal Arabic fixture did not match")
    version = child(rg, ["--no-config", "--version"], directory).splitlines()[0]
    return {"version": version, "matching_lines": 1, "scope": "literal UTF-8 stdin fixture"}


PROBES = {
    "engineering-sdk": (sdk_probe, ("sdk/engineering_sdk.py", "sdk/capabilities.json",
                                    "catalog/registry.json", "integrations/PROGRAMS.json")),
    "agent-orchestration": (orchestration_probe, ("engineering_os/orchestration.py",)),
    "model-router": (routing_probe, ("engineering_os/model_router.py",
                                     "engineering_os/orchestration.py", "catalog/models/registry.json")),
    "motion-sdk": (motion_probe, ("scripts/verify_motion_capability.mjs", "packages/motion-sdk/index.mjs",
                                  "motion-library/expansion/catalog.mjs", "motion-library/expansion/definitions.json",
                                  "motion-library/expansion/families.mjs", "motion-library/expansion/systems.mjs",
                                  "motion-library/expansion/geometry.mjs")),
    "ripgrep": (search_probe, ()),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=PROBES, action="append",
                        help="Select a fixed probe. The default runs every probe.")
    args = parser.parse_args(argv)
    results = {}
    for name in dict.fromkeys(args.only or PROBES):
        probe, sources = PROBES[name]
        start = monotonic()
        try:
            with TemporaryDirectory(prefix="gaie-activation-") as folder:
                details = probe(Path(folder))
            result = ({"state": "TESTED", "details": details} if details is not None
                      else {"state": "BLOCKED", "reason": "required executable is unavailable"})
        except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.SubprocessError) as error:
            result = {"state": "BLOCKED", "reason": "fixture failed", "error_kind": type(error).__name__}
        result["wall_ms"] = round((monotonic() - start) * 1000, 2)
        result["source_sha256"] = {source: hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
                                   for source in sources}
        results[name] = result
    print(json.dumps({"schema_version": 1, "scope": "local synthetic fixtures",
                      "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "checks": results}, indent=2, ensure_ascii=False))
    return 0 if all(row["state"] == "TESTED" for row in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
