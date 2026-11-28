"""Offline next-generation engine entry point shared by Codex and Claude Code.

Modules load only for the selected operation. No model, tool installation,
production release or repair process is started by this dispatcher.
SPDX-License-Identifier: MIT
"""

import argparse
import json
import os
import pathlib
import stat
import sys

from .orchestration import MAX_BYTES, load_json


OPERATIONS = (
    "reasoning-plan", "reasoning-review", "root-causes",
    "memory-put", "memory-search", "memory-graph", "memory-index",
    "memory-checkpoint", "memory-restore", "memory-verify",
    "factory-plan", "factory-evaluate", "factory-generate",
    "healing-analyze", "healing-verify", "healing-repair", "healing-replay",
    "economics", "economics-measure", "cinematic", "architecture",
)


def read_request(path):
    """Read bounded JSON, refusing duplicate keys and nonfinite numbers."""
    path = pathlib.Path(path).absolute()
    if '..' in path.parts:
        raise ValueError("Noncanonical input path")
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                     dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError("Input must be a bounded regular file")
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Request too large")
    value = load_json(data)
    if not isinstance(value, dict):
        raise ValueError("Request must be an object")
    return value


def _fields(value, required, optional=()):
    if not set(required) <= set(value) or not set(value) <= set(required) | set(optional):
        raise ValueError("Unknown or missing operation fields")


def dispatch(operation, request, *, state_dir=None, artifact_root=None):
    """Dispatch structured local work without importing unrelated engines."""
    if not isinstance(request, dict):
        raise ValueError("Request must be an object")
    if operation == "reasoning-plan":
        from .reasoning import plan
        return plan(request)
    if operation == "reasoning-review":
        from .reasoning import review_decision
        _fields(request, ("plan", "reviews", "verification"))
        return review_decision(request["plan"], request["reviews"], request["verification"])
    if operation == "root-causes":
        from .reasoning import root_causes
        _fields(request, ("observations", "dependencies"))
        return root_causes(request["observations"], request["dependencies"])
    if operation.startswith("memory-"):
        from .memory import MemoryStore
        if state_dir is None:
            raise ValueError("Private memory directory is required")
        # Validate each envelope before creating any store.
        envelopes = {
            "memory-search": (("project", "query"), ("limit",)),
            "memory-graph": (("project",), ()),
            "memory-index": (("project", "path", "engine"), ()),
            "memory-checkpoint": (("destination",), ()),
            "memory-restore": (("checkpoint",), ()),
            "memory-verify": (("project", "id", "receipt_path", "receipt_sha256"), ()),
        }
        if operation != "memory-put":
            if operation not in envelopes:
                raise ValueError("Unknown memory operation")
            _fields(request, *envelopes[operation])
        if operation in {"memory-index", "memory-verify"} and artifact_root is None:
            raise ValueError("Artifact root required")
        store = MemoryStore(state_dir)
        if operation == "memory-put":
            return store.put(request)
        if operation == "memory-search":
            return store.search(request["project"], request["query"],
                                limit=request.get("limit", 10), source_root=artifact_root)
        if operation == "memory-graph":
            return store.graph(request["project"])
        if operation == "memory-index":
            return store.index_python(request["project"], request["path"],
                                      artifact_root, request["engine"])
        if operation == "memory-checkpoint":
            return store.checkpoint(request["destination"])
        if operation == "memory-restore":
            return store.restore(request["checkpoint"])
        return store.verify_solution(request["project"], request["id"], artifact_root,
                                     request["receipt_path"], request["receipt_sha256"])
    if operation == "factory-plan":
        from .factory import plan_factory
        return plan_factory(request)
    if operation == "factory-evaluate":
        from .factory import evaluate_factory
        _fields(request, ("plan", "receipts"))
        if artifact_root is None:
            raise ValueError("Artifact root required")
        return evaluate_factory(request["plan"], request["receipts"], artifact_root=artifact_root)
    if operation == "factory-generate":
        from .factory_generate import generate_system
        if artifact_root is None:
            raise ValueError("New private destination required")
        return generate_system(request, destination=artifact_root)
    if operation == "healing-analyze":
        from .healing import analyze
        return analyze(request)
    if operation == "healing-verify":
        from .healing import verify_repair
        return verify_repair(request)
    if operation == "healing-repair":
        from .healing_runtime import repair_sqlite
        return repair_sqlite(request)
    if operation == "healing-replay":
        from .healing_runtime import verify_sqlite_repair
        _fields(request, ("request", "report"))
        return verify_sqlite_repair(request["request"], request["report"])
    if operation == "economics":
        from .economics import summarize
        return summarize(request)
    if operation == "economics-measure":
        from .economics import measure_runtime
        return measure_runtime(request)
    if operation == "cinematic":
        from .cinematic import audit_inventory
        return audit_inventory(request)
    if operation == "architecture":
        from .control import architecture
        _fields(request, ())
        return architecture()
    raise ValueError("Unknown operation")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--input", required=True, type=pathlib.Path)
    parser.add_argument("--state-dir", type=pathlib.Path,
                        help="Private memory directory outside every Git checkout")
    parser.add_argument("--artifact-root", type=pathlib.Path,
                        help="Project root for verification, or new private destination for factory-generate")
    args = parser.parse_args(argv)
    try:
        result = dispatch(args.operation, read_request(args.input),
                          state_dir=args.state_dir, artifact_root=args.artifact_root)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, RecursionError, SyntaxError, OverflowError):
        # Never echo input, private paths or raw exception payloads.
        print("Intelligence request rejected; check schema, private state and source evidence.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
