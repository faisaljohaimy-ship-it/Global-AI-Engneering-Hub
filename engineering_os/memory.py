"""Private project memory shared by Codex and Claude Code. SPDX-License-Identifier: MIT.

No prompts or source bodies are indexed automatically. Retrieval uses deterministic
words and a small engineering concept vocabulary, not embeddings or an LLM. Secret
shape rejection is a guardrail, not a detector for arbitrary personal/client data.
The caller must curate content. Checksums detect corruption, not a malicious user
with write access. Recorded verification is rechecked against source on retrieval.
"""

import ast
import contextlib
import copy
import fcntl
import hashlib
import os
import pathlib
import re

from .orchestration import (DIGEST, ENGINES, _atomic_write, _open_private,
                            _read_private, _safe_directory, _slug, _text, load_json, sha)

KINDS = frozenset({"architecture", "decision", "solution", "failure", "recovery", "checkpoint", "symbol"})
MAX_RECORDS = 2000
RECORD_FIELDS = {"project", "kind", "title", "summary", "tags", "symbols", "links", "provenance"}
CONCEPTS = ({"database", "sql", "schema", "migration", "postgres", "قاعدة", "بيانات"},
            {"failure", "error", "bug", "incident", "repair", "recovery", "خطأ", "إصلاح"},
            {"architecture", "design", "decision", "adr", "معمارية", "قرار"},
            {"test", "tests", "testing", "verification", "verified", "اختبار", "تحقق"})


class MemoryError(ValueError):
    """A private-memory request failed validation."""


def _digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise MemoryError("Invalid memory digest")
    return value


def _items(values, limit, item_limit=100, digest=False):
    if not isinstance(values, list) or len(values) > limit:
        raise MemoryError("Invalid bounded memory list")
    for item in values:
        _digest(item) if digest else _text(item, item_limit)
    if len(values) != len(set(values)):
        raise MemoryError("Duplicate memory list entry")
    return sorted(values)


def _provenance(value):
    if not isinstance(value, dict) or set(value) != {"engine", "source_sha256"} or value["engine"] not in ENGINES:
        raise MemoryError("Engine and source digest required")
    _digest(value["source_sha256"])
    return copy.deepcopy(value)


def _record(record):
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        raise MemoryError("Unknown or missing memory record fields")
    _slug(record["project"])
    if not isinstance(record["kind"], str) or record["kind"] not in KINDS:
        raise MemoryError("Unknown memory kind")
    _text(record["title"], 200)
    _text(record["summary"], 4000)
    value = copy.deepcopy(record)
    for key, limit, length in [("tags", 30, 80), ("symbols", 100, 200), ("links", 100, 64)]:
        value[key] = _items(record[key], limit, length, digest=key == "links")
    value["provenance"] = _provenance(record["provenance"])
    return value


def _content(record):
    return {key: value for key, value in record.items() if key != "provenance"}


def _safe_source(root, relative):
    if not isinstance(relative, str) or len(relative) > 500 or "\\" in relative:
        raise MemoryError("Invalid relative source path")
    path = pathlib.PurePosixPath(relative)
    if path.is_absolute() or any(part in {"..", ".git"} for part in path.parts) or str(path) != relative or not path.parts:
        raise MemoryError("Unsafe source path")
    root = pathlib.Path(root).absolute()
    for ancestor in [root, *root.parents]:
        if ancestor.is_symlink():
            raise MemoryError("Symlink source root refused")
    target = root
    for part in path.parts:
        target = target / part
        if target.is_symlink():
            raise MemoryError("Symlink source refused")
    if not target.is_file() or target.stat().st_size > 2 * 1024 * 1024:
        raise MemoryError("Missing or oversized source")
    return target


def _verification(value):
    if not isinstance(value, dict) or set(value) != {"receipt_sha256", "source_sha256", "solution_sha256"}:
        raise MemoryError("Invalid recorded verification")
    _digest(value["receipt_sha256"])
    _digest(value["solution_sha256"])
    sources = value["source_sha256"]
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 100:
        raise MemoryError("Source-bound verification required")
    for relative, digest in sources.items():
        if not isinstance(relative, str) or len(relative) > 500 or "\\" in relative:
            raise MemoryError("Invalid source binding")
        path = pathlib.PurePosixPath(relative)
        if path.is_absolute() or not path.parts or str(path) != relative or any(part in {"..", ".git"} for part in path.parts):
            raise MemoryError("Unsafe source binding")
        _digest(digest)
    return value


def _verify_state(state):
    if not isinstance(state, dict) or set(state) != {"schema_version", "revision", "records", "sha256"} or type(state["schema_version"]) is not int or state["schema_version"] != 1:
        raise MemoryError("Invalid memory state")
    if type(state["revision"]) is not int or not 0 <= state["revision"] <= 2**53 - 1 or not isinstance(state["records"], dict) or len(state["records"]) > MAX_RECORDS:
        raise MemoryError("Invalid bounded memory state")
    if state["revision"] < len(state["records"]):
        raise MemoryError("Memory revision predates its records")
    if state["sha256"] != sha({key: value for key, value in state.items() if key != "sha256"}):
        raise MemoryError("Memory checksum mismatch")
    for identifier, row in state["records"].items():
        _digest(identifier)
        if not isinstance(row, dict) or set(row) != {"record", "provenances", "verification"}:
            raise MemoryError("Invalid stored memory row")
        record = _record(row["record"])
        if record != row["record"] or sha(_content(record)) != identifier:
            raise MemoryError("Changed memory identity")
        provenances = row["provenances"]
        if not isinstance(provenances, list) or not 1 <= len(provenances) <= 100:
            raise MemoryError("Invalid stored provenance")
        for provenance in provenances:
            _provenance(provenance)
        if len({sha(item) for item in provenances}) != len(provenances) or record["provenance"] not in provenances:
            raise MemoryError("Invalid duplicate provenance")
        if row["verification"] is not None:
            _verification(row["verification"])
            if record["kind"] != "solution" or row["verification"]["solution_sha256"] != identifier:
                raise MemoryError("Verification identity mismatch")
        for link in record["links"]:
            if link not in state["records"] or state["records"][link]["record"]["project"] != record["project"]:
                raise MemoryError("Cross-project or missing graph link")
    return True


def _terms(text):
    return set(re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE))


class MemoryStore:
    """A user-owned, locked local JSON store outside Git; not an access-control service."""

    def __init__(self, state_dir):
        self.directory = _safe_directory(state_dir)
        self.path = self.directory / "memory.json"
        with self._locked():
            if not self.path.exists():
                self._write({"schema_version": 1, "revision": 0, "records": {}})
            self._load()

    @contextlib.contextmanager
    def _locked(self):
        _safe_directory(self.directory)
        fd = _open_private(self.directory / "memory.lock", os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _write(self, state):
        state = {key: value for key, value in state.items() if key != "sha256"}
        state["sha256"] = sha(state)
        _verify_state(state)
        _atomic_write(self.path, state)

    def _load(self):
        state = _read_private(self.path)
        _verify_state(state)
        return state

    def snapshot(self):
        with self._locked():
            return copy.deepcopy(self._load())

    def put(self, record):
        record = _record(record)
        identifier = sha(_content(record))
        with self._locked():
            state = self._load()
            for link in record["links"]:
                if link not in state["records"] or state["records"][link]["record"]["project"] != record["project"]:
                    raise MemoryError("Link requires existing knowledge in the same project")
            exists = identifier in state["records"]
            if exists:
                row = state["records"][identifier]
                if record["provenance"] not in row["provenances"]:
                    if len(row["provenances"]) >= 100:
                        raise MemoryError("Provenance limit reached")
                    row["provenances"].append(record["provenance"])
                    state["revision"] += 1
                    self._write(state)
            else:
                if len(state["records"]) >= MAX_RECORDS:
                    raise MemoryError("Memory record limit reached")
                state["records"][identifier] = {"record": record, "provenances": [record["provenance"]], "verification": None}
                state["revision"] += 1
                self._write(state)
            return {"id": identifier, "deduplicated": exists, "revision": state["revision"]}

    def graph(self, project):
        _slug(project)
        records = self.snapshot()["records"]
        nodes = [{"id": identifier, "kind": row["record"]["kind"], "title": row["record"]["title"]}
                 for identifier, row in sorted(records.items()) if row["record"]["project"] == project]
        edges = [{"from": identifier, "to": target, "relation": "references"}
                 for identifier, row in sorted(records.items()) if row["record"]["project"] == project for target in row["record"]["links"]]
        return {"project": project, "nodes": nodes, "edges": edges}

    def search(self, project, query, limit=10, source_root=None):
        _slug(project)
        _text(query, 500)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise MemoryError("Invalid retrieval limit")
        terms = _terms(query)
        rows = []
        for identifier, row in self.snapshot()["records"].items():
            record = row["record"]
            if record["project"] != project:
                continue
            words = _terms(" ".join([record["title"], record["summary"], *record["tags"], *record["symbols"]]))
            direct = len(words & terms)
            concepts = sum(bool(terms & group) and bool(words & group) for group in CONCEPTS)
            symbol_hits = sum(query.casefold() == symbol.casefold() for symbol in record["symbols"])
            score = direct * 4 + concepts + symbol_hits * 10
            if not score:
                continue
            verification = row["verification"]
            status = "candidate"
            if verification:
                status = "evidence-recorded"
                if source_root is not None:
                    try:
                        current = all(hashlib.sha256(_safe_source(source_root, relative).read_bytes()).hexdigest() == digest
                                      for relative, digest in verification["source_sha256"].items())
                    except (OSError, ValueError):
                        current = False
                    status = "source-matches-recorded-test" if current else "stale"
            rows.append({"id": identifier, "score": score, "record": copy.deepcopy(record),
                         "provenances": copy.deepcopy(row["provenances"]), "verification_status": status,
                         "verification": copy.deepcopy(verification), "retrieval": "lexical-concept; no embeddings"})
        return sorted(rows, key=lambda item: (-item["score"], item["id"]))[:limit]

    def index_python(self, project, path, source_root, engine):
        _slug(project)
        if engine not in ENGINES:
            raise MemoryError("Unknown indexing engine")
        target = _safe_source(source_root, path)
        data = target.read_bytes()
        # Guard transient source too; never store source bodies or docstrings.
        from .orchestration import SECRET
        if SECRET.search(data.decode("utf-8")):
            raise MemoryError("Credential-shaped source refused")
        tree = ast.parse(data, filename=path)
        definitions = []
        pending = [(tree, "")]
        while pending:
            node, prefix = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                prefix = f"{prefix}.{node.name}" if prefix else node.name
                definitions.append((prefix, node.lineno, type(node).__name__))
                if len(definitions) > 100:
                    raise MemoryError("Python symbol count exceeds bounded index")
            pending.extend((child, prefix) for child in reversed(list(ast.iter_child_nodes(node))))
        digest = hashlib.sha256(data).hexdigest()
        return [self.put({"project": project, "kind": "symbol", "title": name,
                          "summary": f"{kind} {path}:{line}", "tags": ["python"], "symbols": [name], "links": [],
                          "provenance": {"engine": engine, "source_sha256": digest}}) for name, line, kind in definitions]

    def verify_solution(self, project, identifier, source_root, receipt_path, receipt_sha256):
        _slug(project)
        _digest(identifier)
        _digest(receipt_sha256)
        receipt_path = pathlib.Path(receipt_path).absolute()
        _safe_directory(receipt_path.parent)
        # Parse and hash the same private file bytes to avoid mismatched reads.
        fd = _open_private(receipt_path, os.O_RDONLY)
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise MemoryError("Oversized verification receipt")
        actual = hashlib.sha256(data).hexdigest()
        receipt = load_json(data)
        if actual != receipt_sha256 or not isinstance(receipt, dict) or set(receipt) != {"schema_version", "status", "solution_sha256", "source_sha256"} or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1 or receipt["status"] != "passed":
            raise MemoryError("Passed source-bound test receipt required")
        value = _verification({"receipt_sha256": receipt_sha256, "solution_sha256": receipt["solution_sha256"], "source_sha256": receipt["source_sha256"]})
        if value["solution_sha256"] != identifier:
            raise MemoryError("Test receipt belongs to a different solution")
        for relative, digest in value["source_sha256"].items():
            if hashlib.sha256(_safe_source(source_root, relative).read_bytes()).hexdigest() != digest:
                raise MemoryError("Source differs from test evidence")
        with self._locked():
            state = self._load()
            row = state["records"].get(identifier)
            if row is None or row["record"]["project"] != project or row["record"]["kind"] != "solution":
                raise MemoryError("Project-scoped solution required")
            row["verification"] = value
            state["revision"] += 1
            self._write(state)
            return {"id": identifier, "verification_status": "source-matches-recorded-test", "revision": state["revision"],
                    "limitation": "Supplied test receipt; no test process or provider invoked by memory."}

    def checkpoint(self, destination):
        destination = pathlib.Path(destination).absolute()
        _safe_directory(destination.parent)
        if destination.exists() or destination.is_symlink():
            raise MemoryError("Checkpoint already exists")
        state = self.snapshot()
        value = {"schema_version": 1, "state": state, "state_sha256": sha(state)}
        _atomic_write(destination, value, exclusive=True)
        return {"state_sha256": value["state_sha256"], "revision": state["revision"]}

    def restore(self, checkpoint):
        checkpoint = pathlib.Path(checkpoint).absolute()
        _safe_directory(checkpoint.parent)
        value = _read_private(checkpoint)
        if not isinstance(value, dict) or set(value) != {"schema_version", "state", "state_sha256"} or type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["state_sha256"] != sha(value["state"]):
            raise MemoryError("Invalid checkpoint checksum/schema")
        _verify_state(value["state"])
        with self._locked():
            if self._load()["revision"]:
                raise MemoryError("Restore requires an empty store")
            self._write(value["state"])
        return {"revision": value["state"]["revision"], "state_sha256": value["state_sha256"]}
