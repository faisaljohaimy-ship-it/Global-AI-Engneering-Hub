"""Unified private engineering memory (GAIE layer L14) shared by Codex and Claude Code.

This is the single storage engine; `engineering_os.gaie_memory` is a facade over it.
A store is a private directory outside every Git checkout holding `memory.jsonl`:
one header line (revision, counts, SHA-256 of the canonical state) followed by one
canonical JSON line per record and per indexed source file. Writes are locked
(fcntl), atomic and private (0600 files, 0700 directory); every read re-verifies the
schema, each record's content identity, graph links and the checksum.
`MemoryStore.for_project(root, project)` opens an isolated store at root/<project>/
that refuses any other project's records, symbols and checkpoints.

Honest limits: retrieval is deterministic lexical and concept matching, not
embeddings or a model. The secret guard refuses credential shapes and explicit
private markers; it is not a detector for arbitrary private or client data, so the
caller must still curate content. Checksums detect corruption and casual edits, not
a writer who recomputes them; a checkpoint is authenticated only when its SHA-256
reaches `restore` through a trusted channel. "Verified" means a supplied, passed,
source-bound receipt matched; this module never runs tests or providers. No source
bodies or docstrings are stored: the symbol index keeps names, signatures, line
numbers and file digests. SPDX-License-Identifier: MIT.
"""

import ast
import collections
import contextlib
import copy
import datetime
import fcntl
import hashlib
import os
import pathlib
import re
import stat
import unicodedata
import uuid

if __package__:
    from .gaie_router import normalize as _words
    from .orchestration import (DIGEST, ENGINES, MAX_BYTES, SECRET as TASK_SECRET, CoordinationError, _atomic_write,
                                _open_private, _safe_directory, _slug, _text, canonical, load_json, sha)
    from scripts.security_scan import secret_findings
else:  # vendored beside gaie_memory.py together with gaie_router.py, orchestration.py and security_scan.py
    from gaie_router import normalize as _words
    from orchestration import (DIGEST, ENGINES, MAX_BYTES, SECRET as TASK_SECRET, CoordinationError, _atomic_write,
                               _open_private, _safe_directory, _slug, _text, canonical, load_json, sha)
    from security_scan import secret_findings

ENGINE_ID = "gaie-engineering-memory"
SCHEMA_VERSION = 2
STATE_FILE, LEGACY_STATE_FILE, LOCK_FILE = "memory.jsonl", "memory.json", "memory.lock"
CHECKPOINT_FORMAT = "gaie-memory-checkpoint"
LEGACY_KINDS = frozenset({"architecture", "decision", "solution", "failure", "recovery", "checkpoint", "symbol"})
KINDS = LEGACY_KINDS | {"pattern", "root-cause", "repair", "test-result", "quality-standard", "performance",
                        "release", "lesson", "adr", "task"}
STRUCTURED = frozenset({"adr", "task"})
MERGEABLE = frozenset({"architecture", "decision", "pattern", "solution", "lesson", "quality-standard",
                       "performance", "failure", "root-cause", "repair"})
VERIFIABLE = frozenset({"solution", "repair"})
RELATIONS = ("references", "supersedes", "caused-by", "fixes", "depends-on", "relates-to", "explains",
             "verifies", "concerns", "implements")
ADR_STATUSES = ("proposed", "accepted", "superseded")
TASK_STATUSES = ("in-progress", "blocked", "done")
SYMBOL_KINDS = ("class", "function", "method", "async-function", "async-method")
MAX_RECORDS, MAX_SYMBOL_FILES, MAX_DEFINITIONS, MAX_FILE_DEFINITIONS = 5000, 2000, 20000, 1000
RECORD_FIELDS = {"project", "kind", "title", "summary", "tags", "symbols", "links", "provenance"}
OPTIONAL_FIELDS = ("relations", "evidence", "sources", "attributes")
ROW_FIELDS = {"seq", "created", "record", "provenances", "verification", "merged", "lifecycle"}
HEADER_FIELDS = {"format", "schema_version", "revision", "project", "records", "symbol_files", "state_sha256"}
STATE_FIELDS = {"schema_version", "revision", "project", "records", "symbols", "sha256"}
ADR_ID = re.compile(r"ADR-\d{4,6}")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
QUALNAME = re.compile(r"[^\W\d]\w*(?:\.[^\W\d]\w*)*")
CONCEPTS = ({"database", "sql", "schema", "migration", "postgres", "قاعدة", "بيانات"},
            {"failure", "error", "bug", "incident", "repair", "recovery", "خطأ", "إصلاح"},
            {"architecture", "design", "decision", "adr", "معمارية", "قرار"},
            {"test", "tests", "testing", "verification", "verified", "اختبار", "تحقق"})
EXTRA_CONCEPTS = ({"performance", "slow", "latency", "cache", "index", "throughput", "أداء"},
                  {"security", "auth", "authentication", "permission", "isolation", "أمان"},
                  {"money", "price", "pricing", "discount", "currency", "cents", "total"})
STOPWORDS = frozenset({"a", "an", "the", "of", "to", "for", "and", "or", "in", "on", "at", "by", "with", "from", "is", "was",
                       "are", "be", "do", "does", "did", "we", "our", "it", "this", "that", "why", "what", "how", "where",
                       "في", "من", "علي", "الي", "عن", "و", "لماذا", "ما", "هل"})
# Broader than the task-store pattern: the credential shapes the GAIE factory memory refused (PR #26).
BROAD_SECRET = re.compile(
    r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bglpat-[A-Za-z0-9_-]{16,}"
    r"|\bnpm_[A-Za-z0-9]{20,}|\bwhsec_[A-Za-z0-9]{16,}|\bsbp_[A-Za-z0-9]{20,}|\bya29\.[A-Za-z0-9_-]{16,}"
    r"|\bsk-(?:proj-|ant-|svcacct-|admin-)?[A-Za-z0-9_-]{24,}|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bAIza[A-Za-z0-9_-]{35}\b"
    r"|\bsb_secret_[A-Za-z0-9_-]{20,}|\bxox[baprs]-[A-Za-z0-9-]{10,}|\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}"
    r"|\bsk_[a-f0-9]{48}\b|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
    r"|\b(?:Bearer|Basic)\s+[A-Za-z0-9_./+=-]{12,}|://[^\s/@]+:[^\s@]+@|hooks\.slack\.com/services/"
    r"|(?:password|passwd|pwd|secret|api[\s_-]?key|token|private[\s_-]?key|access[\s_-]?key|role[\s_-]?key|credential)\w*"
    r"[\"']?\s*(?:[:=]|\bis\b)\s*[\"']?\S{4,}", re.I)
SPLIT_SECRET = re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:proj-|ant-)[A-Za-z0-9_-]{24,}"
                          r"|xox[baprs]-[A-Za-z0-9-]{20,}|-----BEGIN(?:[A-Z]+)?PRIVATEKEY")
# Explicit markers only, so ordinary prose about "private" state stays storable.
PRIVATE_MARKER = re.compile(
    r"(?i:<\s*/?\s*(?:private|confidential)\s*>|\[\s*(?:private|confidential)\s*\]|\bgaie:private\b|\w*private_marker\b)"
    r"|\b(?:CONFIDENTIAL|PROPRIETARY)\b|\bDO NOT (?:SHARE|COMMIT|PUBLISH|DISTRIBUTE)\b|\b(?:INTERNAL|CLIENT)[ _-]ONLY\b"
    r"|سري للغاية|للاستخدام الداخلي فقط|خاص وسري")
_BAD_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})
_DEFINITION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class MemoryError(ValueError):
    """A private-memory request failed validation."""


class SecretRefused(MemoryError):
    """Credential-shaped or private-marked content; nothing was written."""


class IsolationError(MemoryError):
    """A request crossed a project boundary."""


class IntegrityError(MemoryError):
    """A state file or checkpoint failed its integrity or schema check."""


class MissingMemory(MemoryError):
    """No private memory has been recorded at this location yet."""


# ---------------------------------------------------------------- validation

def _refuse_secrets(value):
    for text in {value, unicodedata.normalize("NFKC", value)}:
        if (TASK_SECRET.search(text) or BROAD_SECRET.search(text) or SPLIT_SECRET.search(re.sub(r"\s+", "", text))
                or PRIVATE_MARKER.search(text) or secret_findings("memory.txt", text)):
            raise SecretRefused("Credential-shaped or private-marked text refused; nothing was stored")


def _guard(value, limit, field="text", multiline=False):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise MemoryError(f"{field} must be 1-{limit} characters")
    if any(unicodedata.category(char) in _BAD_CATEGORIES and not (multiline and char in "\n\t") for char in value):
        raise MemoryError(f"{field} contains control or format characters")
    _refuse_secrets(value)
    return value


def _safe_text(value, limit):
    """Single-line text: the task-store rules plus the full memory guard."""
    _text(value, limit)
    return _guard(value, limit)


def _digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise MemoryError("Invalid memory digest")
    return value


def _items(values, limit, item_limit=100, digest=False):
    if not isinstance(values, list) or len(values) > limit:
        raise MemoryError("Invalid bounded memory list")
    for item in values:
        _digest(item) if digest else _safe_text(item, item_limit)
    if len(values) != len(set(values)):
        raise MemoryError("Duplicate memory list entry")
    return sorted(values)


def _provenance(value):
    if not isinstance(value, dict) or set(value) != {"engine", "source_sha256"} or value["engine"] not in ENGINES:
        raise MemoryError("Engine and source digest required")
    _digest(value["source_sha256"])
    return copy.deepcopy(value)


def _relative(relative):
    if not isinstance(relative, str) or len(relative) > 500 or "\\" in relative:
        raise MemoryError("Invalid relative source path")
    path = pathlib.PurePosixPath(relative)
    if path.is_absolute() or not path.parts or str(path) != relative or any(part in {"..", ".git"} for part in path.parts):
        raise MemoryError("Unsafe source path")
    return relative


def _safe_source(root, relative):
    _relative(relative)
    root = pathlib.Path(root).absolute()
    for ancestor in [root, *root.parents]:
        if ancestor.is_symlink():
            raise MemoryError("Symlink source root refused")
    target = root
    for part in pathlib.PurePosixPath(relative).parts:
        target = target / part
        if target.is_symlink():
            raise MemoryError("Symlink source refused")
    if not target.is_file() or target.stat().st_size > 2 * 1024 * 1024:
        raise MemoryError("Missing or oversized source")
    return target


def _file_sha256(root, relative):
    return hashlib.sha256(_safe_source(root, relative).read_bytes()).hexdigest()


def _unique_sorted(rows, key, message):
    rows.sort(key=key)
    if len({key(row) for row in rows}) != len(rows):
        raise MemoryError(message)
    return rows


def _relations(values):
    if not isinstance(values, list) or len(values) > 50:
        raise MemoryError("Invalid bounded relation list")
    rows = []
    for item in values:
        if not isinstance(item, dict) or set(item) != {"relation", "target"} or item["relation"] not in RELATIONS:
            raise MemoryError("Relation needs a known type and a target")
        rows.append({"relation": item["relation"], "target": _digest(item["target"])})
    return _unique_sorted(rows, lambda row: (row["relation"], row["target"]), "Duplicate relation")


def _evidence(values):
    if not isinstance(values, list) or len(values) > 50:
        raise MemoryError("Invalid bounded evidence list")
    rows = []
    for item in values:
        if not isinstance(item, dict) or set(item) != {"kind", "sha256"}:
            raise MemoryError("Evidence holds a kind and a sha256 digest only")
        rows.append({"kind": _safe_text(item["kind"], 60), "sha256": _digest(item["sha256"])})
    return _unique_sorted(rows, lambda row: (row["kind"], row["sha256"]), "Duplicate evidence")


def _sources(values):
    if not isinstance(values, list) or len(values) > 50:
        raise MemoryError("Invalid bounded source list")
    rows = []
    for item in values:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise MemoryError("Source evidence holds a path and a sha256 digest only")
        rows.append({"path": _safe_text(_relative(item["path"]), 500), "sha256": _digest(item["sha256"])})
    return _unique_sorted(rows, lambda row: row["path"], "Duplicate source path")


def _steps(values, field):
    if not isinstance(values, list) or len(values) > 100:
        raise MemoryError(f"{field} must be a bounded list")
    for item in values:
        _safe_text(item, 300)
    if len(set(values)) != len(values):
        raise MemoryError(f"Duplicate step in {field}")
    return list(values)


def failure_signature(text):
    """Deterministic failure fingerprint: addresses, digests, directories and numbers are folded."""
    _guard(text, 500, "failure signature", multiline=True)
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"0x[0-9a-f]+", "<addr>", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", text)
    text = re.sub(r"(?:[a-z]:)?(?:[\\/][^\s\\/:'\"]+)+[\\/]([^\s\\/:'\"]+)", r"\1", text)
    text = re.sub(r"\d+", "#", text)
    return re.sub(r"\s+", " ", text).strip()[:500].strip()


def _attributes(kind, value):
    if not isinstance(value, dict):
        raise MemoryError("Attributes must be an object")
    if kind == "adr":
        if not {"adr_id", "context", "consequences"} <= set(value) <= {"adr_id", "context", "consequences", "supersedes"}:
            raise MemoryError("ADR attributes are adr_id, context, consequences and optional supersedes")
        if not isinstance(value["adr_id"], str) or not ADR_ID.fullmatch(value["adr_id"]):
            raise MemoryError("Invalid ADR id")
        _guard(value["context"], 4000, "ADR context", multiline=True)
        _guard(value["consequences"], 4000, "ADR consequences", multiline=True)
        if "supersedes" in value and (not isinstance(value["supersedes"], str) or not ADR_ID.fullmatch(value["supersedes"])
                                      or value["supersedes"] == value["adr_id"]):
            raise MemoryError("Invalid superseded ADR id")
    elif kind == "task":
        if set(value) != {"task_id", "status", "done", "remaining"}:
            raise MemoryError("Task attributes are task_id, status, done and remaining")
        _slug(value["task_id"])
        if value["status"] not in TASK_STATUSES:
            raise MemoryError("Unknown task status")
        done, remaining = _steps(value["done"], "done"), _steps(value["remaining"], "remaining")
        if set(done) & set(remaining) or (value["status"] == "done") != (not remaining):
            raise MemoryError("A step is either done or remaining; only a task without remaining steps is done")
    elif kind == "failure":
        if set(value) != {"signature"} or not isinstance(value["signature"], str) \
                or failure_signature(value["signature"]) != value["signature"]:
            raise MemoryError("Failure attributes hold one normalized signature")
    else:
        raise MemoryError("Attributes are not defined for this kind")
    return copy.deepcopy(value)


def _record(record):
    if not isinstance(record, dict) or not RECORD_FIELDS <= set(record) or set(record) - RECORD_FIELDS - set(OPTIONAL_FIELDS):
        raise MemoryError("Unknown or missing memory record fields")
    _slug(record["project"])
    if not isinstance(record["kind"], str) or record["kind"] not in KINDS:
        raise MemoryError("Unknown memory kind")
    _safe_text(record["title"], 200)
    _guard(record["summary"], 4000, "summary", multiline=True)
    value = {key: record[key] for key in ("project", "kind", "title", "summary")}
    for key, limit, length in [("tags", 30, 80), ("symbols", 100, 200), ("links", 100, 64)]:
        value[key] = _items(record[key], limit, length, digest=key == "links")
    value["provenance"] = _provenance(record["provenance"])
    # Empty optional fields normalize away so schema-1 identities stay stable.
    for key, check in (("relations", _relations), ("evidence", _evidence), ("sources", _sources)):
        if record.get(key):
            value[key] = check(record[key])
    if record.get("attributes"):
        value["attributes"] = _attributes(record["kind"], record["attributes"])
    elif record["kind"] in STRUCTURED:
        raise MemoryError("This kind needs structured attributes")
    return value


def _content(record):
    return {key: value for key, value in record.items() if key != "provenance"}


def _targets(record):
    return list(record["links"]) + [row["target"] for row in record.get("relations", ())]


def _verification(value):
    if not isinstance(value, dict) or set(value) != {"receipt_sha256", "source_sha256", "solution_sha256"}:
        raise MemoryError("Invalid recorded verification")
    _digest(value["receipt_sha256"])
    _digest(value["solution_sha256"])
    sources = value["source_sha256"]
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 100:
        raise MemoryError("Source-bound verification required")
    for relative, digest in sources.items():
        try:
            _relative(relative)
        except MemoryError:
            raise MemoryError("Unsafe source binding") from None
        _safe_text(relative, 500)
        _digest(digest)
    return value


def _stamp(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise MemoryError("Timestamps must be timezone-aware datetimes")
    return now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lifecycle(value, kind):
    if kind != "adr":
        if value is not None:
            raise IntegrityError("Lifecycle is only defined for ADRs")
        return
    if not isinstance(value, dict) or set(value) != {"status", "history", "superseded_by"} or value["status"] not in ADR_STATUSES:
        raise IntegrityError("Invalid ADR lifecycle")
    history = value["history"]
    if not isinstance(history, list) or not 1 <= len(history) <= 50 or any(
            not isinstance(step, dict) or set(step) != {"status", "at"} or step["status"] not in ADR_STATUSES
            or not isinstance(step["at"], str) or not TIMESTAMP.fullmatch(step["at"]) for step in history):
        raise IntegrityError("Invalid ADR history")
    later = value["superseded_by"]
    if history[-1]["status"] != value["status"] or (value["status"] == "superseded") != (later is not None) \
            or (later is not None and (not isinstance(later, str) or not ADR_ID.fullmatch(later))):
        raise IntegrityError("Inconsistent ADR lifecycle")


def _merged(values, identifier):
    if not isinstance(values, list) or len(values) > 100:
        raise IntegrityError("Invalid merge provenance")
    seen = set()
    for item in values:
        if not isinstance(item, dict) or set(item) != {"content_sha256", "title", "provenance"} or item["content_sha256"] == identifier:
            raise IntegrityError("Invalid merge provenance")
        _digest(item["content_sha256"])
        _safe_text(item["title"], 200)
        _provenance(item["provenance"])
        key = (item["content_sha256"], sha(item["provenance"]))
        if key in seen:
            raise IntegrityError("Duplicate merge provenance")
        seen.add(key)


def _symbol_file(value):
    if not isinstance(value, dict) or set(value) != {"sha256", "module", "definitions"}:
        raise IntegrityError("Invalid symbol index entry")
    _digest(value["sha256"])
    _safe_text(value["module"], 300)
    definitions = value["definitions"]
    if not isinstance(definitions, list) or len(definitions) > MAX_FILE_DEFINITIONS:
        raise IntegrityError("Invalid bounded symbol definitions")
    names = set()
    for item in definitions:
        if not isinstance(item, dict) or set(item) != {"qualname", "kind", "line", "end_line", "signature"} \
                or not isinstance(item["qualname"], str) or not QUALNAME.fullmatch(item["qualname"]) \
                or item["kind"] not in SYMBOL_KINDS or type(item["line"]) is not int or type(item["end_line"]) is not int \
                or not 1 <= item["line"] <= item["end_line"] or item["qualname"] in names:
            raise IntegrityError("Invalid symbol definition")
        _safe_text(item["qualname"], 300)
        _safe_text(item["signature"], 300)
        names.add(item["qualname"])
    return len(definitions)


def _verify_state(state):
    if not isinstance(state, dict) or set(state) != STATE_FIELDS or type(state["schema_version"]) is not int \
            or state["schema_version"] != SCHEMA_VERSION:
        raise IntegrityError("Invalid memory state")
    records, symbols, bound = state["records"], state["symbols"], state["project"]
    if type(state["revision"]) is not int or not 0 <= state["revision"] <= 2**53 - 1 or not isinstance(records, dict) \
            or len(records) > MAX_RECORDS or not isinstance(symbols, dict) or len(symbols) > 100:
        raise IntegrityError("Invalid bounded memory state")
    if bound is not None:
        _slug(bound)
    if state["revision"] < len(records):
        raise IntegrityError("Memory revision predates its records")
    if state["sha256"] != sha({key: value for key, value in state.items() if key != "sha256"}):
        raise IntegrityError("Memory checksum mismatch")
    seqs, adrs = set(), {}
    for identifier, row in records.items():
        _digest(identifier)
        if not isinstance(row, dict) or set(row) != ROW_FIELDS or type(row["seq"]) is not int or row["seq"] < 1 or row["seq"] in seqs \
                or not (row["created"] is None or (isinstance(row["created"], str) and TIMESTAMP.fullmatch(row["created"]))):
            raise IntegrityError("Invalid stored memory row")
        seqs.add(row["seq"])
        record = _record(row["record"])
        if record != row["record"] or sha(_content(record)) != identifier:
            raise IntegrityError("Changed memory identity")
        if bound is not None and record["project"] != bound:
            raise IsolationError("Foreign project knowledge in an isolated store")
        provenances = row["provenances"]
        if not isinstance(provenances, list) or not 1 <= len(provenances) <= 100:
            raise IntegrityError("Invalid stored provenance")
        for provenance in provenances:
            _provenance(provenance)
        if len({sha(item) for item in provenances}) != len(provenances) or record["provenance"] not in provenances:
            raise IntegrityError("Invalid duplicate provenance")
        if row["verification"] is not None:
            _verification(row["verification"])
            if record["kind"] not in VERIFIABLE or row["verification"]["solution_sha256"] != identifier:
                raise IntegrityError("Verification identity mismatch")
        _merged(row["merged"], identifier)
        _lifecycle(row["lifecycle"], record["kind"])
        if record["kind"] == "adr":
            key = (record["project"], record["attributes"]["adr_id"])
            if key in adrs:
                raise IntegrityError("Duplicate ADR id")
            adrs[key] = row
    for row in records.values():
        for target in _targets(row["record"]):
            other = records.get(target)
            if other is None or other["record"]["project"] != row["record"]["project"] or other["seq"] >= row["seq"]:
                raise MemoryError("Cross-project or missing graph link")
    for (project, _), row in adrs.items():
        later = row["lifecycle"]["superseded_by"]
        if later is not None and (project, later) not in adrs:
            raise IntegrityError("Superseding ADR is missing")
    total = 0
    for project, files in symbols.items():
        _slug(project)
        if bound is not None and project != bound:
            raise IsolationError("Foreign project symbols in an isolated store")
        if not isinstance(files, dict) or not files or len(files) > MAX_SYMBOL_FILES:
            raise IntegrityError("Invalid bounded symbol index")
        for relative, entry in files.items():
            _safe_text(_relative(relative), 500)
            total += _symbol_file(entry)
    if total > MAX_DEFINITIONS:
        raise IntegrityError("Symbol index exceeds its bound")
    return True


def _seal(state):
    state = {key: value for key, value in state.items() if key != "sha256"}
    state["sha256"] = sha(state)
    _verify_state(state)
    return state


def _empty(project):
    return _seal({"schema_version": SCHEMA_VERSION, "revision": 0, "project": project, "records": {}, "symbols": {}})


def _serialize(state):
    header = {"format": ENGINE_ID, "schema_version": SCHEMA_VERSION, "revision": state["revision"], "project": state["project"],
              "records": len(state["records"]), "symbol_files": sum(len(files) for files in state["symbols"].values()),
              "state_sha256": state["sha256"]}
    lines = [canonical(header)]
    for identifier, row in sorted(state["records"].items(), key=lambda item: item[1]["seq"]):
        lines.append(canonical({"type": "record", "id": identifier, "row": row}))
    for project in sorted(state["symbols"]):
        for relative in sorted(state["symbols"][project]):
            lines.append(canonical({"type": "symbols", "project": project, "path": relative,
                                    "file": state["symbols"][project][relative]}))
    return b"\n".join(lines) + b"\n"


def _parse(data):
    if not data.endswith(b"\n"):
        raise IntegrityError("Truncated memory state")
    rows = []
    for line in data[:-1].split(b"\n"):
        try:
            value = load_json(line)
        except (ValueError, UnicodeDecodeError):
            raise IntegrityError("Malformed memory line") from None
        if canonical(value) != line:
            raise IntegrityError("Noncanonical memory line")
        rows.append(value)
    header = rows[0]
    if not isinstance(header, dict) or set(header) != HEADER_FIELDS or header["format"] != ENGINE_ID \
            or header["schema_version"] != SCHEMA_VERSION:
        raise IntegrityError("Missing or invalid memory header")
    records, symbols, last_seq, last_file = {}, {}, 0, None
    for row in rows[1:]:
        if isinstance(row, dict) and set(row) == {"type", "id", "row"} and row["type"] == "record" and last_file is None:
            if not isinstance(row["row"], dict) or type(row["row"].get("seq")) is not int or row["row"]["seq"] <= last_seq \
                    or not isinstance(row["id"], str) or row["id"] in records:
                raise IntegrityError("Memory records are out of order or repeated")
            last_seq = row["row"]["seq"]
            records[row["id"]] = row["row"]
        elif isinstance(row, dict) and set(row) == {"type", "project", "path", "file"} and row["type"] == "symbols" \
                and isinstance(row["project"], str) and isinstance(row["path"], str):
            key = (row["project"], row["path"])
            if last_file is not None and key <= last_file:
                raise IntegrityError("Symbol index lines are out of order")
            last_file = key
            symbols.setdefault(row["project"], {})[row["path"]] = row["file"]
        else:
            raise IntegrityError("Unknown memory line")
    if header["records"] != len(records) or header["symbol_files"] != sum(len(files) for files in symbols.values()):
        raise IntegrityError("Memory line count mismatch")
    state = {"schema_version": SCHEMA_VERSION, "revision": header["revision"], "project": header["project"],
             "records": records, "symbols": symbols, "sha256": header["state_sha256"]}
    _verify_state(state)
    return state


def _from_v1(value):
    """Convert a verified schema-1 state (PR #25 single-object format); record identities are unchanged."""
    if not isinstance(value, dict) or set(value) != {"schema_version", "revision", "records", "sha256"} \
            or value["schema_version"] != 1 or not isinstance(value["records"], dict):
        raise IntegrityError("Invalid schema-1 memory state")
    if value["sha256"] != sha({key: item for key, item in value.items() if key != "sha256"}):
        raise IntegrityError("Memory checksum mismatch")
    records = value["records"]
    for row in records.values():
        if not isinstance(row, dict) or set(row) != {"record", "provenances", "verification"} or not isinstance(row["record"], dict) \
                or not isinstance(row["record"].get("links"), list):
            raise IntegrityError("Invalid schema-1 memory row")
    order, placed = [], set()
    while len(order) < len(records):
        ready = [key for key in sorted(records) if key not in placed and all(link in placed for link in records[key]["record"]["links"])]
        if not ready:
            raise IntegrityError("Missing or cyclic schema-1 links")
        order.extend(ready)
        placed.update(ready)
    converted = {key: {"seq": index + 1, "created": None, "record": records[key]["record"], "provenances": records[key]["provenances"],
                       "verification": records[key]["verification"], "merged": [], "lifecycle": None}
                 for index, key in enumerate(order)}
    return _seal({"schema_version": SCHEMA_VERSION, "revision": value["revision"], "project": None,
                  "records": converted, "symbols": {}})


def _bind(state, project):
    """Bind an unbound state to one project, refusing it if it holds anything else."""
    if project is None or state["project"] == project:
        return state
    if state["project"] is not None:
        raise IsolationError("This memory belongs to another project")
    if any(row["record"]["project"] != project for row in state["records"].values()) or set(state["symbols"]) - {project}:
        raise IsolationError("This memory holds other projects' knowledge")
    return _seal(dict(state, project=project))


def _atomic_write_bytes(path, data):
    """`orchestration._atomic_write` for pre-serialized JSONL bytes: private temp file, fsync, replace."""
    if len(data) > MAX_BYTES:
        raise MemoryError("Memory state exceeds its bounded size")
    if path.is_symlink():
        raise CoordinationError("Symlink state file refused")
    if path.exists():
        os.close(_open_private(path, os.O_RDONLY))
    temporary = path.parent / (".write-" + uuid.uuid4().hex)
    try:
        fd = _open_private(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _read_bytes(path, limit=MAX_BYTES):
    fd = _open_private(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise IntegrityError("Oversized private file")
    return data


# ---------------------------------------------------------------- retrieval helpers

def _terms(text):
    return set(re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE))


def _folded(text):
    """Folded Arabic/English terms; identifiers split on dots, underscores, hyphens and camelCase."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return {part for word in _words(text) for part in [word, *word.split("-")] if part}


_FOLDED_CONCEPTS = tuple({term for word in group for term in _folded(word)} for group in CONCEPTS + EXTRA_CONCEPTS)


def _attribute_text(record):
    attributes = record.get("attributes") or {}
    texts = [attributes.get(key, "") for key in ("context", "consequences", "signature")]
    return texts + list(attributes.get("done", ())) + list(attributes.get("remaining", ()))


def _near_key(record):
    if record["kind"] not in MERGEABLE:
        return None
    words = sorted(_folded(record["title"]) - STOPWORDS)
    if not words:
        return None
    return sha({"project": record["project"], "kind": record["kind"], "title": words, "symbols": record["symbols"],
                "links": record["links"], **{key: record.get(key) for key in OPTIONAL_FIELDS}})


def _source_state(source_root, relative, digest):
    if source_root is None:
        return "unchecked"
    try:
        return "fresh" if _file_sha256(source_root, relative) == digest else "stale"
    except (MemoryError, OSError):
        return "missing"


def _verification_status(row, source_root):
    verification = row["verification"]
    if verification is None:
        return "unverified"
    if source_root is None:
        return "evidence-recorded"
    current = all(_source_state(source_root, relative, digest) == "fresh" for relative, digest in verification["source_sha256"].items())
    return "source-matches-recorded-test" if current else "stale"


def _evidence_status(record, source_root):
    files = [{"path": item["path"], "recorded_sha256": item["sha256"],
              "status": _source_state(source_root, item["path"], item["sha256"])} for item in record.get("sources", ())]
    states = {item["status"] for item in files}
    status = "none" if not files else "stale" if "stale" in states else "missing" if "missing" in states \
        else "unchecked" if "unchecked" in states else "fresh"
    return {"status": status, "files": files}


_LABELS = {"unverified": "UNVERIFIED: no passed, source-bound test receipt is bound to this entry",
           "evidence-recorded": "Receipt bound; source digests not rechecked in this call",
           "source-matches-recorded-test": "Verified: current source matches the passed test receipt",
           "stale": "STALE: source changed since the recorded test receipt"}


def _module_name(relative):
    parts = list(pathlib.PurePosixPath(relative).with_suffix("").parts)
    if parts[-1] == "__init__" and len(parts) > 1:
        parts.pop()
    return ".".join(parts)


def _definitions(tree):
    """Definitions in the schema-1 depth-first order: (qualname, node, directly inside a class)."""
    found, pending = [], [(tree, "", False)]
    while pending:
        node, prefix, in_class = pending.pop()
        inner = in_class
        if isinstance(node, _DEFINITION_NODES):
            prefix = f"{prefix}.{node.name}" if prefix else node.name
            found.append((prefix, node, in_class))
            inner = isinstance(node, ast.ClassDef)
        pending.extend((child, prefix, inner) for child in reversed(list(ast.iter_child_nodes(node))))
    return found


def _signature(node):
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(item) for item in node.bases + node.keywords]
        text = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
    else:
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        text = f"{prefix} {node.name}({ast.unparse(node.args)})" + (f" -> {ast.unparse(node.returns)}" if node.returns else "")
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= 300 else text[:297] + "..."


def _symbol_entry(node, qualname, in_class):
    if isinstance(node, ast.ClassDef):
        kind = "class"
    else:
        kind = ("async-" if isinstance(node, ast.AsyncFunctionDef) else "") + ("method" if in_class else "function")
    return {"qualname": qualname, "kind": kind, "line": node.lineno, "end_line": max(node.lineno, node.end_lineno or node.lineno),
            "signature": _signature(node)}


def _credential_source(relative, text):
    return bool(TASK_SECRET.search(text) or BROAD_SECRET.search(text) or secret_findings(relative, text))


# ---------------------------------------------------------------- the engine

class MemoryStore:
    """A user-owned, locked local store outside Git; not an access-control service."""

    def __init__(self, state_dir, project=None, create=True, *, read_only=False):
        if project is not None:
            _slug(project)
        self.project = project
        self._read_only = read_only
        directory = pathlib.Path(state_dir).absolute()
        self.path = directory / STATE_FILE
        self._cache = None
        if read_only:
            if ".." in directory.parts:
                raise IsolationError("Memory directory must be normalized")
            for ancestor in (directory, *directory.parents):
                if ancestor.is_symlink():
                    raise CoordinationError("Symlink state directory refused")
                if os.path.lexists(ancestor / ".git"):
                    raise CoordinationError("Task state must remain outside Git repositories")
            try:
                info = directory.stat()
            except FileNotFoundError:
                raise MissingMemory("No private memory recorded here") from None
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise CoordinationError("State directory must be user-owned mode 0700")
            self.directory = directory
            return
        if not create and not ((directory / STATE_FILE).is_file() or (directory / LEGACY_STATE_FILE).is_file()):
            raise MissingMemory("No private memory recorded here")
        self.directory = _safe_directory(directory)
        with self._locked():
            if not self.path.exists() and not self.path.is_symlink():
                legacy = self.directory / LEGACY_STATE_FILE
                state = _from_v1(load_json(_read_bytes(legacy))) if legacy.exists() else _empty(None)
                self._write(_bind(state, project))
            self._load()

    @classmethod
    def for_project(cls, root, project, create=True):
        """Open root/<project>/ as an isolated store; the path is derived from the slug, never supplied."""
        _slug(project)
        base = pathlib.Path(root).absolute()
        if ".." in base.parts:
            raise IsolationError("Memory root must be a normalized path")
        target = base / project
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise IsolationError("Project memory directory must be a real directory")
        if not create and not target.is_dir():
            raise MissingMemory("No private memory recorded for this project")
        _safe_directory(base)
        store = cls(target, project=project, create=create)
        if os.path.realpath(store.directory) != os.path.join(os.path.realpath(base), project):
            raise IsolationError("Project memory escaped its root")
        return store

    def _require_write(self):
        if self._read_only:
            raise MemoryError("A read-only memory store cannot be written")

    @contextlib.contextmanager
    def _locked(self):
        self._require_write()
        _safe_directory(self.directory)
        fd = _open_private(self.directory / LOCK_FILE, os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _write(self, state):
        state = _seal(state)
        if self.project is not None and state["project"] != self.project:
            raise IsolationError("This memory belongs to another project")
        _atomic_write_bytes(self.path, _serialize(state))
        self._cache = None

    def _load(self):
        try:
            data = _read_bytes(self.path)
        except FileNotFoundError:
            if not self._read_only:
                raise
            try:
                legacy = _read_bytes(self.directory / LEGACY_STATE_FILE)
            except FileNotFoundError:
                raise MissingMemory("No private memory recorded here") from None
            return _bind(_from_v1(load_json(legacy)), self.project)
        digest = hashlib.sha256(data).hexdigest()
        if self._cache is None or self._cache[0] != digest:
            state = _parse(data)
            if self.project is not None and state["project"] != self.project:
                raise IsolationError("This state directory belongs to another project")
            self._cache = (digest, state)
        return copy.deepcopy(self._cache[1])

    def _check(self, project, state=None):
        _slug(project)
        bound = self.project or (state or {}).get("project")
        if bound is not None and project != bound:
            raise IsolationError("Project isolation: this memory belongs to another project")
        return project

    def _mutate(self, change):
        with self._locked():
            state = self._load()
            before = len(state["records"])
            result, changed = change(state)
            if changed:
                # One revision per write, or per record when a transaction adds several (revision >= records).
                state["revision"] += max(1, len(state["records"]) - before)
                self._write(state)
            result["revision"] = state["revision"]
            return result

    @staticmethod
    def _rows(state, project):
        return sorted(((key, row) for key, row in state["records"].items() if row["record"]["project"] == project),
                      key=lambda item: item[1]["seq"])

    def _view(self, project, use):
        """Give `use(state, rows)` only this project's snapshot rows, in insertion order."""
        self._check(project)
        state = self.snapshot()
        self._check(project, state)
        return use(state, self._rows(state, project))

    def snapshot(self):
        if self._read_only:
            # Writers atomically replace the journal. A reader sees one complete
            # revision without creating a lock or persisting a legacy migration.
            return self._load()
        with self._locked():
            return self._load()

    # -- records -----------------------------------------------------------

    def _insert(self, state, record, now=None, structured=False):
        record = _record(record)
        self._check(record["project"], state)
        if record["kind"] in STRUCTURED and not structured:
            raise MemoryError("Use adr_add or task_progress for this kind")
        identifier, records = sha(_content(record)), state["records"]
        for target in _targets(record):
            if target not in records or records[target]["record"]["project"] != record["project"]:
                raise MemoryError("Link requires existing knowledge in the same project")
        if identifier in records:
            row = records[identifier]
            if record["provenance"] in row["provenances"]:
                return {"id": identifier, "deduplicated": True, "merged": False}, False
            if len(row["provenances"]) >= 100:
                raise MemoryError("Provenance limit reached")
            row["provenances"].append(record["provenance"])
            return {"id": identifier, "deduplicated": True, "merged": False}, True
        key = _near_key(record)
        if key is not None:
            for other, row in sorted(records.items(), key=lambda item: item[1]["seq"]):
                if _near_key(row["record"]) == key:
                    merged = {"content_sha256": identifier, "title": record["title"], "provenance": record["provenance"]}
                    if merged in row["merged"]:
                        return {"id": other, "deduplicated": True, "merged": True}, False
                    if len(row["merged"]) >= 100:
                        raise MemoryError("Merge provenance limit reached")
                    row["merged"].append(merged)
                    return {"id": other, "deduplicated": True, "merged": True}, True
        if len(records) >= MAX_RECORDS:
            raise MemoryError("Memory record limit reached")
        records[identifier] = {"seq": 1 + max((row["seq"] for row in records.values()), default=0), "created": _stamp(now),
                               "record": record, "provenances": [record["provenance"]], "verification": None,
                               "merged": [], "lifecycle": None}
        return {"id": identifier, "deduplicated": False, "merged": False}, True

    def put(self, record, now=None):
        """Store a record: exact content duplicates add provenance; near-duplicate titles merge with provenance."""
        return self._mutate(lambda state: self._insert(state, record, now))

    def put_many(self, records, now=None):
        """Insert several records in one locked transaction (all or nothing)."""
        if not isinstance(records, list) or len(records) > MAX_RECORDS:
            raise MemoryError("Invalid bounded record batch")

        def change(state):
            results = [self._insert(state, record, now) for record in records]
            return {"results": [result for result, _ in results]}, any(changed for _, changed in results)
        return self._mutate(change)

    def import_batch(self, project, items):
        """One transaction of records that may reference earlier items by key (used by importers).

        Each item is {"key", "record", "refs": [{"relation", "key"}], "now"}; refs resolve to the stored ids of
        earlier items. An item the guard or validator refuses is skipped and reported; refs to it are dropped.
        """
        if not isinstance(items, list) or len(items) > MAX_RECORDS:
            raise MemoryError("Invalid bounded import batch")

        def change(state):
            self._check(project, state)
            ids, refused, changed = {}, [], False
            for item in items:
                if not isinstance(item, dict) or set(item) != {"key", "record", "refs", "now"} or not isinstance(item["refs"], list) \
                        or not isinstance(item["record"], dict) or not all(isinstance(ref, dict) for ref in item["refs"]):
                    raise MemoryError("Import items need key, record, refs and now")
                record = dict(item["record"], relations=list(item["record"].get("relations", ())) + [
                    {"relation": ref["relation"], "target": ids[ref["key"]]} for ref in item["refs"] if ref.get("key") in ids])
                if record.get("project") != project:
                    raise IsolationError("Imported record belongs to another project")
                try:
                    result, more = self._insert(state, record, item["now"])
                except MemoryError:
                    refused.append(item["key"])
                    continue
                ids[item["key"]], changed = result["id"], changed or more
            return {"ids": ids, "refused": refused}, changed
        return self._mutate(change)

    def _build(self, project, kind, title, summary, engine, *, tags=(), symbols=(), relations=(), evidence=(),
               sources=(), attributes=None, source_root=None):
        """A record with provenance; source paths are bound to their current SHA-256."""
        if engine not in ENGINES:
            raise MemoryError("Unknown engine")
        if sources and source_root is None:
            raise MemoryError("Binding sources needs the source root")
        record = {"project": project, "kind": kind, "title": title, "summary": summary, "tags": list(tags),
                  "symbols": list(symbols), "links": []}
        bound = [{"path": path, "sha256": _file_sha256(source_root, path)} for path in sources]
        for key, value in (("relations", list(relations)), ("evidence", list(evidence)), ("sources", bound), ("attributes", attributes)):
            if value:
                record[key] = value
        placeholder = _record(dict(record, provenance={"engine": engine, "source_sha256": "0" * 64}))
        return dict(record, provenance={"engine": engine, "source_sha256": sha(_content(placeholder))})

    def get(self, project, identifier):
        _digest(identifier)

        def use(state, rows):
            for key, row in rows:
                if key == identifier:
                    return dict(copy.deepcopy(row), id=key)
            raise MemoryError("Unknown entry in this project")
        return self._view(project, use)

    def entries(self, project):
        return self._view(project, lambda state, rows: [dict(copy.deepcopy(row), id=key) for key, row in rows])

    def graph(self, project):
        def use(state, rows):
            rows = sorted(rows)
            nodes = [{"id": key, "kind": row["record"]["kind"], "title": row["record"]["title"]} for key, row in rows]
            edges = [{"from": key, "to": target, "relation": "references"} for key, row in rows for target in row["record"]["links"]]
            edges += [{"from": key, "to": item["target"], "relation": item["relation"]}
                      for key, row in rows for item in row["record"].get("relations", ())]
            return {"project": project, "nodes": nodes, "edges": edges}
        return self._view(project, use)

    def search(self, project, query, limit=10, source_root=None):
        """Schema-1 lexical-concept search over records (unchanged scoring and status vocabulary)."""
        _slug(project)
        _safe_text(query, 500)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise MemoryError("Invalid retrieval limit")
        terms = _terms(query)

        def use(state, rows):
            found = []
            for identifier, row in rows:
                record = row["record"]
                words = _terms(" ".join([record["title"], record["summary"], *record["tags"], *record["symbols"]]))
                direct = len(words & terms)
                concepts = sum(bool(terms & group) and bool(words & group) for group in CONCEPTS)
                symbol_hits = sum(query.casefold() == symbol.casefold() for symbol in record["symbols"])
                score = direct * 4 + concepts + symbol_hits * 10
                if not score:
                    continue
                status = _verification_status(row, source_root)
                found.append({"id": identifier, "score": score, "record": copy.deepcopy(record),
                              "provenances": copy.deepcopy(row["provenances"]),
                              "verification_status": "candidate" if status == "unverified" else status,
                              "verification": copy.deepcopy(row["verification"]), "retrieval": "lexical-concept; no embeddings"})
            return sorted(found, key=lambda item: (-item["score"], item["id"]))[:limit]
        return self._view(project, use)

    def retrieve(self, project, query=None, limit=10, kinds=None, tags=None, include_symbols=True, source_root=None):
        """Ranked concept retrieval over entries and indexed symbols; without a query, entries newest first.

        Superseded ADRs and task versions stay visible, flagged, at half score (rounded up).
        """
        if query:
            _safe_text(query, 500)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise MemoryError("Invalid retrieval limit")
        kinds = None if kinds is None else set(kinds)
        if kinds is not None and not kinds <= KINDS:
            raise MemoryError("Unknown memory kind")
        tags = None if tags is None else {tag.casefold() for tag in tags}
        wanted, exact = (_folded(query), query.casefold()) if query else (set(), None)
        wanted = (wanted - STOPWORDS) or wanted

        def use(state, rows):
            superseded = {item["target"] for _, row in rows if row["record"]["kind"] in STRUCTURED
                          for item in row["record"].get("relations", ()) if item["relation"] == "supersedes"}
            found = []
            for identifier, row in rows:
                record = row["record"]
                if (kinds is not None and record["kind"] not in kinds) or (tags is not None and not tags & {tag.casefold() for tag in record["tags"]}):
                    continue
                score = 0
                if wanted:
                    title = _folded(record["title"]) | {term for item in row["merged"] for term in _folded(item["title"])}
                    body = _folded(" ".join([record["summary"], *_attribute_text(record)]))
                    labels = {term for tag in record["tags"] for term in _folded(tag)}
                    symbols = {term for symbol in record["symbols"] for term in _folded(symbol)}
                    words = title | body | labels | symbols
                    score = (3 * len(wanted & title) + 2 * len(wanted & labels) + 3 * len(wanted & symbols) + len(wanted & body)
                             + sum(bool(wanted & group) and bool(words & group) for group in _FOLDED_CONCEPTS)
                             + 10 * sum(exact == symbol.casefold() for symbol in record["symbols"]))
                    if not score:
                        continue
                lifecycle = row["lifecycle"]["status"] if row["lifecycle"] else None
                old = identifier in superseded or lifecycle == "superseded"
                found.append({"type": "entry", "id": identifier, "seq": row["seq"], "kind": record["kind"], "title": record["title"],
                              "summary": record["summary"], "tags": list(record["tags"]), "score": (score + 1) // 2 if old else score,
                              "superseded": old, "lifecycle": lifecycle,
                              "created": row["created"], "merged_variants": len(row["merged"]),
                              "verification_status": _verification_status(row, source_root) if record["kind"] in VERIFIABLE else None,
                              "evidence_status": _evidence_status(record, source_root)["status"]})
            if wanted and include_symbols and (kinds is None or "symbol" in kinds) and tags is None:
                for relative, entry in sorted(state["symbols"].get(project, {}).items()):
                    for item in entry["definitions"]:
                        own = _folded(item["qualname"])
                        score = (4 * len(wanted & own) + len(wanted & _folded(entry["module"])) + len(wanted & _folded(item["signature"]))
                                 + 12 * (exact in {item["qualname"].casefold(), f"{entry['module']}.{item['qualname']}".casefold()}))
                        if score:
                            found.append({"type": "symbol", "id": f"symbol:{relative}#{item['qualname']}", "seq": 0, "score": score,
                                          "path": relative, "module": entry["module"], **item, "superseded": False,
                                          "source_status": _source_state(source_root, relative, entry["sha256"])})
            if wanted:
                found.sort(key=lambda item: (-item["score"], item["superseded"], -item["seq"], item["id"]))
            else:
                found.sort(key=lambda item: (item["superseded"], -item["seq"]))
            for item in found:
                del item["seq"]
                item["retrieval"] = "lexical-concept; no embeddings"
            return found[:limit]
        return self._view(project, use)

    # -- knowledge graph ---------------------------------------------------

    @staticmethod
    def _graph_edges(state, project, rows):
        """Typed nodes (entries, modules, classes, functions) and edges (stored relations plus contains/mentions)."""
        nodes, edges, index = {}, set(), collections.defaultdict(list)
        for key, row in rows:
            nodes[key] = {"id": key, "type": "entry", "kind": row["record"]["kind"], "title": row["record"]["title"]}
            edges.update((key, "references", target) for target in row["record"]["links"])
            edges.update((key, item["relation"], item["target"]) for item in row["record"].get("relations", ()))
        for relative, entry in sorted(state["symbols"].get(project, {}).items()):
            module = f"symbol:{relative}"
            nodes[module] = {"id": module, "type": "symbol", "kind": "module", "qualname": entry["module"], "path": relative, "line": 1}
            index[entry["module"]].append(module)
            owners = {}
            for item in entry["definitions"]:
                node = f"symbol:{relative}#{item['qualname']}"
                nodes[node] = {"id": node, "type": "symbol", "kind": item["kind"], "qualname": item["qualname"],
                               "path": relative, "line": item["line"]}
                owners[item["qualname"]] = node
                index[item["qualname"]].append(node)
                index[f"{entry['module']}.{item['qualname']}"].append(node)
            for item in entry["definitions"]:
                edges.add((owners.get(item["qualname"].rpartition(".")[0], module), "contains", owners[item["qualname"]]))
        for key, row in rows:
            edges.update((key, "mentions", node) for name in row["record"]["symbols"] for node in index.get(name, ()))
        return nodes, sorted(edges)

    def neighbours(self, project, node, relation=None, direction="both"):
        if direction not in {"both", "out", "in"}:
            raise MemoryError("Direction is both, out or in")

        def use(state, rows):
            nodes, edges = self._graph_edges(state, project, rows)
            if node not in nodes:
                raise MemoryError("Unknown graph node in this project")
            outgoing = [{"relation": name, "node": nodes[end]} for start, name, end in edges
                        if start == node and relation in (None, name)]
            incoming = [{"relation": name, "node": nodes[start]} for start, name, end in edges
                        if end == node and relation in (None, name)]
            return {"node": nodes[node], "outgoing": outgoing if direction != "in" else [],
                    "incoming": incoming if direction != "out" else []}
        return self._view(project, use)

    def graph_path(self, project, source, target, max_depth=6, relations=None):
        """Shortest undirected path by deterministic BFS; each hop reports the stored edge direction."""
        if type(max_depth) is not int or not 1 <= max_depth <= 20:
            raise MemoryError("Invalid path depth")

        def use(state, rows):
            nodes, edges = self._graph_edges(state, project, rows)
            if source not in nodes or target not in nodes:
                raise MemoryError("Unknown graph node in this project")
            adjacent = collections.defaultdict(list)
            for start, name, end in edges:
                if relations is None or name in relations:
                    adjacent[start].append((end, name, "forward"))
                    adjacent[end].append((start, name, "backward"))
            parents, frontier = {source: None}, [source]
            for _ in range(max_depth):
                following = []
                for current in frontier:
                    for nxt, name, way in sorted(adjacent[current]):
                        if nxt not in parents:
                            parents[nxt] = (current, name, way)
                            following.append(nxt)
                frontier = following
                if target in parents or not frontier:
                    break
            if target not in parents:
                return {"found": False, "length": None, "nodes": [], "hops": []}
            hops, current = [], target
            while parents[current] is not None:
                previous, name, way = parents[current]
                hops.append({"from": previous, "relation": name, "to": current, "direction": way})
                current = previous
            hops.reverse()
            return {"found": True, "length": len(hops), "nodes": [source] + [hop["to"] for hop in hops], "hops": hops}
        return self._view(project, use)

    # -- architecture decision records ---------------------------------------

    @staticmethod
    def _adrs(rows):
        return {row["record"]["attributes"]["adr_id"]: (key, row) for key, row in rows if row["record"]["kind"] == "adr"}

    @staticmethod
    def _retire(adrs, adr_id, later, at):
        _, row = adrs[adr_id]
        row["lifecycle"] = {"status": "superseded", "history": row["lifecycle"]["history"] + [{"status": "superseded", "at": at}],
                            "superseded_by": later}

    def adr_add(self, project, title, context, decision, consequences, *, engine="claude-code", status="proposed",
                supersedes=None, tags=(), symbols=(), sources=(), source_root=None, now=None):
        """Record ADR-NNNN. Once an ADR that supersedes another is accepted, the older one is superseded."""
        if status not in {"proposed", "accepted"}:
            raise MemoryError("A new ADR is proposed or accepted")

        def change(state):
            self._check(project, state)
            adrs = self._adrs(self._rows(state, project))
            for adr_id, (key, row) in adrs.items():
                known = row["record"]["attributes"]
                if (row["record"]["title"], row["record"]["summary"], known["context"], known["consequences"],
                        known.get("supersedes")) == (title, decision, context, consequences, supersedes):
                    return {"adr_id": adr_id, "id": key, "status": row["lifecycle"]["status"], "deduplicated": True}, False
            attributes = {"adr_id": f"ADR-{len(adrs) + 1:04d}", "context": context, "consequences": consequences}
            relations = []
            if supersedes is not None:
                if supersedes not in adrs or adrs[supersedes][1]["lifecycle"]["status"] == "superseded":
                    raise MemoryError("Only an existing, current ADR can be superseded")
                attributes["supersedes"] = supersedes
                relations.append({"relation": "supersedes", "target": adrs[supersedes][0]})
            record = self._build(project, "adr", title, decision, engine, tags=tags, symbols=symbols, relations=relations,
                                 sources=sources, attributes=attributes, source_root=source_root)
            result, _ = self._insert(state, record, now, structured=True)
            at = _stamp(now)
            state["records"][result["id"]]["lifecycle"] = {"status": status, "history": [{"status": status, "at": at}],
                                                           "superseded_by": None}
            if supersedes is not None and status == "accepted":
                self._retire(adrs, supersedes, attributes["adr_id"], at)
            return {"adr_id": attributes["adr_id"], "id": result["id"], "status": status, "deduplicated": False}, True
        return self._mutate(change)

    def adr_status(self, project, adr_id, status, now=None):
        """proposed -> accepted; accepting an ADR that supersedes another retires the older one."""
        if status != "accepted":
            raise MemoryError("Only proposed -> accepted is set directly; supersede with a new ADR")

        def change(state):
            self._check(project, state)
            adrs = self._adrs(self._rows(state, project))
            if adr_id not in adrs:
                raise MemoryError("Unknown ADR in this project")
            key, row = adrs[adr_id]
            if row["lifecycle"]["status"] != "proposed":
                raise MemoryError("Only a proposed ADR can be accepted")
            older = row["record"]["attributes"].get("supersedes")
            if older is not None and adrs[older][1]["lifecycle"]["status"] == "superseded":
                raise MemoryError("The superseded ADR was already retired by another ADR")
            at = _stamp(now)
            row["lifecycle"] = {"status": "accepted", "history": row["lifecycle"]["history"] + [{"status": "accepted", "at": at}],
                                "superseded_by": None}
            if older is not None:
                self._retire(adrs, older, adr_id, at)
            return {"adr_id": adr_id, "id": key, "status": "accepted"}, True
        return self._mutate(change)

    @staticmethod
    def _adr_view(key, row, source_root=None):
        record, lifecycle = row["record"], row["lifecycle"]
        return {"adr_id": record["attributes"]["adr_id"], "id": key, "title": record["title"], "status": lifecycle["status"],
                "context": record["attributes"]["context"], "decision": record["summary"],
                "consequences": record["attributes"]["consequences"], "supersedes": record["attributes"].get("supersedes"),
                "superseded_by": lifecycle["superseded_by"], "history": copy.deepcopy(lifecycle["history"]),
                "tags": list(record["tags"]), "symbols": list(record["symbols"]), "evidence": _evidence_status(record, source_root)}

    def adr(self, project, adr_id, source_root=None):
        def use(state, rows):
            adrs = self._adrs(rows)
            if adr_id not in adrs:
                raise MemoryError("Unknown ADR in this project")
            return self._adr_view(*adrs[adr_id], source_root)
        return self._view(project, use)

    def adrs(self, project, status=None):
        if status is not None and status not in ADR_STATUSES:
            raise MemoryError("Unknown ADR status")
        return self._view(project, lambda state, rows: [self._adr_view(key, row) for _, (key, row) in sorted(self._adrs(rows).items())
                                                        if status in (None, row["lifecycle"]["status"])])

    def why(self, project, question, limit=3, source_root=None):
        """Why was decision X taken: recorded ADR/decision text only, never generated reasoning."""
        _safe_text(question, 500)
        match = ADR_ID.search(question)
        if match:
            answers = [self.adr(project, match.group(0), source_root)]
        else:
            adrs = {item["id"]: item for item in self.adrs(project)}
            hits = self.retrieve(project, question, limit=limit, kinds={"adr", "decision", "architecture"}, source_root=source_root)
            answers = [adrs.get(hit["id"]) or {"id": hit["id"], "kind": hit["kind"], "title": hit["title"],
                                               "decision": hit["summary"], "status": "recorded"} for hit in hits]
        return {"question": question, "answers": answers,
                "basis": "recorded ADR and decision text only; deterministic retrieval, no model reasoning"}

    # -- verified solutions --------------------------------------------------

    def verify(self, project, identifier, source_root, receipt_path, receipt_sha256):
        """Bind a passed, source-bound test receipt to a solution or repair entry."""
        _slug(project)
        _digest(identifier)
        _digest(receipt_sha256)
        receipt_path = pathlib.Path(receipt_path).absolute()
        _safe_directory(receipt_path.parent)
        # Parse and hash the same private file bytes to avoid mismatched reads.
        data = _read_bytes(receipt_path)
        actual = hashlib.sha256(data).hexdigest()
        receipt = load_json(data)
        if actual != receipt_sha256 or not isinstance(receipt, dict) or set(receipt) != {"schema_version", "status", "solution_sha256", "source_sha256"} \
                or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1 or receipt["status"] != "passed":
            raise MemoryError("Passed source-bound test receipt required")
        value = _verification({"receipt_sha256": receipt_sha256, "solution_sha256": receipt["solution_sha256"],
                               "source_sha256": receipt["source_sha256"]})
        if value["solution_sha256"] != identifier:
            raise MemoryError("Test receipt belongs to a different solution")
        for relative, digest in value["source_sha256"].items():
            if _file_sha256(source_root, relative) != digest:
                raise MemoryError("Source differs from test evidence")

        def change(state):
            self._check(project, state)
            row = state["records"].get(identifier)
            if row is None or row["record"]["project"] != project or row["record"]["kind"] not in VERIFIABLE:
                raise MemoryError("Project-scoped solution required")
            row["verification"] = value
            return {"id": identifier, "verification_status": "source-matches-recorded-test",
                    "limitation": "Supplied test receipt; no test process or provider invoked by memory."}, True
        return self._mutate(change)

    def verify_solution(self, project, identifier, source_root, receipt_path, receipt_sha256):
        return self.verify(project, identifier, source_root, receipt_path, receipt_sha256)

    def solutions(self, project, source_root=None):
        """The verified-solutions registry; anything without a passed receipt is marked UNVERIFIED."""
        def use(state, rows):
            result = []
            for key, row in rows:
                if row["record"]["kind"] in VERIFIABLE:
                    status = _verification_status(row, source_root)
                    result.append({"id": key, "kind": row["record"]["kind"], "title": row["record"]["title"], "status": status,
                                   "verified": status in {"evidence-recorded", "source-matches-recorded-test"},
                                   "receipt_sha256": row["verification"]["receipt_sha256"] if row["verification"] else None,
                                   "label": _LABELS[status]})
            return result
        return self._view(project, use)

    def evidence_status(self, project, identifier, source_root=None):
        return dict(_evidence_status(self.get(project, identifier)["record"], source_root), id=identifier)

    # -- failure and recovery memory -----------------------------------------

    def record_failure(self, project, signature, summary, *, engine="claude-code", title=None, root_cause=None, fix=None,
                       tags=(), symbols=(), sources=(), source_root=None, now=None):
        """failure signature -> failure entry <-explains- root cause <-fixes- fix; bind a receipt with `verify`."""
        normalized = failure_signature(signature)
        title = title or signature.strip().splitlines()[0][:200]

        def change(state):
            failure = self._build(project, "failure", title, summary, engine, tags=tags, symbols=symbols, sources=sources,
                                  attributes={"signature": normalized}, source_root=source_root)
            first, changed = self._insert(state, failure, now)
            more, also = self._recovery(state, project, first["id"], title, root_cause, fix, engine, now)
            return {"failure": first["id"], "merged": first["merged"], **more, "signature": normalized,
                    "signature_sha256": hashlib.sha256(normalized.encode()).hexdigest()}, changed or also
        return self._mutate(change)

    def _recovery(self, state, project, failure_id, title, root_cause, fix, engine, now):
        result, changed = {"root_cause": None, "fix": None}, False
        if root_cause is not None:
            cause = self._build(project, "root-cause", f"Root cause: {title}"[:200], root_cause, engine,
                                relations=[{"relation": "explains", "target": failure_id}])
            inserted, changed = self._insert(state, cause, now)
            result["root_cause"] = inserted["id"]
        if fix is not None:
            relations = [{"relation": "fixes", "target": failure_id}]
            if result["root_cause"]:
                relations.append({"relation": "relates-to", "target": result["root_cause"]})
            repair, more = self._insert(state, self._build(project, "repair", f"Fix: {title}"[:200], fix, engine, relations=relations), now)
            result["fix"], changed = repair["id"], changed or more
        return result, changed

    def record_recovery(self, project, failure_id, *, root_cause=None, fix=None, engine="claude-code", now=None):
        """Attach a later root cause and/or fix to a recorded failure."""
        _digest(failure_id)

        def change(state):
            self._check(project, state)
            row = state["records"].get(failure_id)
            if row is None or row["record"]["project"] != project or row["record"]["kind"] != "failure":
                raise MemoryError("Unknown failure in this project")
            return self._recovery(state, project, failure_id, row["record"]["title"], root_cause, fix, engine, now)
        return self._mutate(change)

    def recall_failure(self, project, signature, limit=5, source_root=None):
        """Known failures for a signature (exact fingerprint, else term overlap >= 0.5) with causes, fixes, verification."""
        wanted = failure_signature(signature)
        terms = _folded(wanted)

        def use(state, rows):
            found = []
            for key, row in rows:
                record = row["record"]
                if record["kind"] != "failure" or "attributes" not in record:
                    continue
                known = record["attributes"]["signature"]
                score = 1.0 if known == wanted else round(len(terms & _folded(known)) / max(1, len(terms | _folded(known))), 3)
                if score < 0.5:
                    continue
                causes = [{"id": other, "summary": item["record"]["summary"]} for other, item in rows
                          if item["record"]["kind"] == "root-cause" and {"relation": "explains", "target": key} in item["record"].get("relations", ())]
                fixes = []
                for other, item in rows:
                    if item["record"]["kind"] == "repair" and {"relation": "fixes", "target": key} in item["record"].get("relations", ()):
                        status = _verification_status(item, source_root)
                        fixes.append({"id": other, "summary": item["record"]["summary"], "verification_status": status, "label": _LABELS[status]})
                verified = any(fix["verification_status"] in {"evidence-recorded", "source-matches-recorded-test"} for fix in fixes)
                found.append({"failure": key, "title": record["title"], "signature": known, "match": "exact" if score == 1.0 else "similar",
                              "score": score, "root_causes": causes, "fixes": fixes, "occurrences": 1 + len(row["merged"]),
                              "status": "verified-fix" if verified else "unverified-fix" if fixes else "root-cause-only" if causes else "unresolved"})
            return sorted(found, key=lambda item: (-item["score"], item["failure"]))[:limit]
        return self._view(project, use)

    # -- task progress (cross-session) ---------------------------------------

    @staticmethod
    def _latest_tasks(rows):
        older = {item["target"] for _, row in rows if row["record"]["kind"] == "task"
                 for item in row["record"].get("relations", ()) if item["relation"] == "supersedes"}
        return {row["record"]["attributes"]["task_id"]: (key, row) for key, row in rows
                if row["record"]["kind"] == "task" and key not in older}

    @staticmethod
    def _version(rows, key):
        by_key, version = dict(rows), 1
        while True:
            older = [item["target"] for item in by_key[key]["record"].get("relations", ()) if item["relation"] == "supersedes"]
            if not older:
                return version
            key, version = older[0], version + 1

    def task_progress(self, project, task_id, title, done, remaining, *, engine="claude-code", status=None, summary=None,
                      decisions=(), symbols=(), now=None):
        """Record a new version of a task's progress; the previous version is superseded, never rewritten."""
        status = status or ("done" if not remaining else "in-progress")

        def change(state):
            self._check(project, state)
            rows = self._rows(state, project)
            adrs, previous = self._adrs(rows), self._latest_tasks(rows).get(task_id)
            relations = []
            for decision in decisions:
                if decision in adrs:
                    relations.append({"relation": "concerns", "target": adrs[decision][0]})
                elif isinstance(decision, str) and decision in state["records"] and state["records"][decision]["record"]["project"] == project:
                    relations.append({"relation": "concerns", "target": decision})
                else:
                    raise MemoryError("Decision reference must be an ADR id or entry of this project")
            attributes = {"task_id": task_id, "status": status, "done": list(done), "remaining": list(remaining)}
            text = summary or f"{len(done)} step(s) done, {len(remaining)} remaining" + (f"; next: {remaining[0]}" if remaining else "")
            if previous:
                old = previous[1]["record"]
                same = sorted((item["relation"], item["target"]) for item in old.get("relations", ()) if item["relation"] == "concerns")
                if (old["attributes"], old["title"], old["symbols"], same) == (attributes, title, sorted(symbols),
                                                                               sorted((item["relation"], item["target"]) for item in relations)) \
                        and (summary is None or old["summary"] == summary):
                    return {"id": previous[0], "task_id": task_id, "version": self._version(rows, previous[0]),
                            "next": remaining[0] if remaining else None, "unchanged": True}, False
                relations.append({"relation": "supersedes", "target": previous[0]})
            record = self._build(project, "task", title, text, engine, symbols=symbols, relations=relations, attributes=attributes)
            inserted, changed = self._insert(state, record, now, structured=True)
            return {"id": inserted["id"], "task_id": task_id, "version": self._version(self._rows(state, project), inserted["id"]),
                    "next": remaining[0] if remaining else None, "unchanged": False}, changed
        return self._mutate(change)

    def next_steps(self, project, task_id=None):
        """Latest progress per task (or one task): done, remaining, next step and the decisions it rests on."""
        def use(state, rows):
            adrs = {key: self._adr_view(key, row) for key, row in rows if row["record"]["kind"] == "adr"}
            result = []
            for name, (key, row) in sorted(self._latest_tasks(rows).items()):
                if task_id not in (None, name):
                    continue
                attributes = row["record"]["attributes"]
                decisions = [{"adr_id": adrs[item["target"]]["adr_id"], "title": adrs[item["target"]]["title"],
                              "status": adrs[item["target"]]["status"]} for item in row["record"].get("relations", ())
                             if item["relation"] == "concerns" and item["target"] in adrs]
                result.append({"task_id": name, "id": key, "title": row["record"]["title"], "status": attributes["status"],
                               "version": self._version(rows, key), "done": list(attributes["done"]),
                               "remaining": list(attributes["remaining"]),
                               "next": attributes["remaining"][0] if attributes["remaining"] else None,
                               "decisions": decisions, "symbols": list(row["record"]["symbols"]), "updated": row["created"]})
            if task_id is not None and not result:
                raise MemoryError("Unknown task in this project")
            return result
        return self._view(project, use)

    def brief(self, project, source_root=None):
        """A compact resume briefing for a new session, built from private memory only."""
        tasks = self.next_steps(project)

        def use(state, rows):
            adrs = [self._adr_view(key, row) for _, (key, row) in sorted(self._adrs(rows).items())]
            files = state["symbols"].get(project, {})
            solutions = collections.Counter(_verification_status(row, source_root) for _, row in rows if row["record"]["kind"] in VERIFIABLE)
            return {"project": project, "revision": state["revision"], "state_sha256": state["sha256"],
                    "open_tasks": [task for task in tasks if task["status"] != "done"],
                    "done_tasks": [task["task_id"] for task in tasks if task["status"] == "done"],
                    "adrs": {status: [{"adr_id": item["adr_id"], "title": item["title"]} for item in adrs if item["status"] == status]
                             for status in ADR_STATUSES},
                    "solutions": dict(sorted(solutions.items())),
                    "recent_failures": [{"id": key, "title": row["record"]["title"],
                                         "signature": row["record"].get("attributes", {}).get("signature")}
                                        for key, row in rows if row["record"]["kind"] == "failure"][-5:],
                    "symbol_index": {"files": len(files), "definitions": sum(len(entry["definitions"]) for entry in files.values())},
                    "entries": len(rows), "source": "private memory only" if source_root is None else "private memory + source digests",
                    "reasoning": "deterministic; no model call"}
        return self._view(project, use)

    # -- symbol index --------------------------------------------------------

    def index_python(self, project, path, source_root, engine):
        """Schema-1 per-file index: one symbol record per definition, plus the file's symbol-index entry."""
        self._check(project)
        if engine not in ENGINES:
            raise MemoryError("Unknown indexing engine")
        target = _safe_source(source_root, path)
        data = target.read_bytes()
        # Guard transient source too; never store source bodies or docstrings.
        if _credential_source(path, data.decode("utf-8")):
            raise MemoryError("Credential-shaped source refused")
        definitions = _definitions(ast.parse(data, filename=path))
        if len(definitions) > 100:
            raise MemoryError("Python symbol count exceeds bounded index")
        digest = hashlib.sha256(data).hexdigest()
        entry = {"sha256": digest, "module": _module_name(path),
                 "definitions": [_symbol_entry(node, name, in_class) for name, node, in_class in definitions]}
        _symbol_file(entry)

        def change(state):
            results = [self._insert(state, {"project": project, "kind": "symbol", "title": name,
                                            "summary": f"{type(node).__name__} {path}:{node.lineno}", "tags": ["python"],
                                            "symbols": [name], "links": [], "provenance": {"engine": engine, "source_sha256": digest}})
                       for name, node, _ in definitions]
            state["symbols"].setdefault(project, {})[path] = entry
            return {"results": [result for result, _ in results]}, True
        outcome = self._mutate(change)
        return [dict(result, revision=outcome["revision"]) for result in outcome["results"]]

    def index_repository(self, project, source_root, engine="claude-code", paths=None):
        """Index modules, classes, functions, signatures and line numbers; no bodies or docstrings are stored.

        With `paths=None` the project's whole symbol index is replaced, so deleted files disappear.
        Unparseable, unsafe or credential-shaped files are skipped and reported by reason only.
        """
        self._check(project)
        if engine not in ENGINES:
            raise MemoryError("Unknown indexing engine")
        root = pathlib.Path(source_root).absolute()
        if not root.is_dir() or any(ancestor.is_symlink() for ancestor in [root, *root.parents]):
            raise MemoryError("Source root must be a real directory")
        if paths is None:
            candidates = []
            for directory, folders, files in os.walk(root, followlinks=False):
                folders[:] = sorted(name for name in folders if not name.startswith(".")
                                    and name not in {"__pycache__", "node_modules", "venv", "build", "dist"})
                candidates += [pathlib.Path(directory, name).relative_to(root).as_posix() for name in sorted(files) if name.endswith(".py")]
                if len(candidates) > MAX_SYMBOL_FILES:
                    raise MemoryError("Too many Python files for the bounded symbol index")
        elif not isinstance(paths, list) or len(paths) > MAX_SYMBOL_FILES:
            raise MemoryError("Invalid bounded path list")
        else:
            candidates = [_relative(item) for item in paths]
        files, skipped = {}, []
        for relative in candidates:
            reason = None
            try:
                _guard(relative, 500, "path")
                data = _safe_source(root, relative).read_bytes()
                text = data.decode("utf-8")
                if _credential_source(relative, text):
                    reason = "credential-shaped-content"
                else:
                    entry = {"sha256": hashlib.sha256(data).hexdigest(), "module": _module_name(relative),
                             "definitions": [_symbol_entry(node, name, inner)
                                             for name, node, inner in _definitions(ast.parse(text, filename=relative))]}
                    _symbol_file(entry)
                    files[relative] = entry
            except SecretRefused:
                reason = "refused-identifier"
            except SyntaxError:
                reason = "syntax-error"
            except UnicodeDecodeError:
                reason = "not-utf8"
            except (MemoryError, CoordinationError, OSError, RecursionError):
                reason = "unsafe-missing-or-invalid"
            if reason:
                try:
                    skipped.append({"path": _guard(relative, 500, "path"), "reason": reason})
                except MemoryError:
                    skipped.append({"path": None, "reason": reason})

        def change(state):
            self._check(project, state)
            current = {} if paths is None else dict(state["symbols"].get(project, {}))
            for relative in candidates:
                current.pop(relative, None)
            current.update(files)
            if current:
                state["symbols"][project] = current
            else:
                state["symbols"].pop(project, None)
            return {"project": project, "files": len(files), "definitions": sum(len(entry["definitions"]) for entry in files.values()),
                    "skipped": skipped, "source_bodies_stored": False}, True
        return self._mutate(change)

    def where(self, project, name, source_root=None, limit=20):
        """Locate a symbol from the index; sources are read only when `source_root` is given (staleness)."""
        _safe_text(name, 300)
        wanted = name.casefold()

        def use(state, rows):
            found = []
            for relative, entry in sorted(state["symbols"].get(project, {}).items()):
                module = entry["module"]
                candidates = [({"qualname": module, "kind": "module", "line": 1, "end_line": 1, "signature": f"module {module}"},
                               {module.casefold(), relative.casefold()})]
                candidates += [(item, {item["qualname"].casefold(), f"{module}.{item['qualname']}".casefold()}) for item in entry["definitions"]]
                for item, names in candidates:
                    last = item["qualname"].rpartition(".")[2].casefold()
                    score = 3 if wanted in names else 2 if any(full.endswith("." + wanted) for full in names) else 1 if last == wanted else 0
                    if score:
                        found.append((-score, relative, item["line"], {"path": relative, "module": module, **item,
                                      "file_sha256": entry["sha256"], "match": {3: "exact", 2: "suffix", 1: "name"}[score],
                                      "source_status": _source_state(source_root, relative, entry["sha256"])}))
            return [item for *_, item in sorted(found, key=lambda row: row[:3])][:limit]
        return self._view(project, use)

    def symbol_status(self, project, source_root):
        """Per indexed file: fresh, stale (changed since indexing) or missing."""
        return self._view(project, lambda state, rows: {relative: _source_state(source_root, relative, entry["sha256"])
                                                        for relative, entry in sorted(state["symbols"].get(project, {}).items())})

    # -- checkpoints ---------------------------------------------------------

    def checkpoint(self, destination):
        """Write a new SHA-256 sealed checkpoint file into a private directory outside Git."""
        self._require_write()
        destination = pathlib.Path(destination).absolute()
        _safe_directory(destination.parent)
        if destination.exists() or destination.is_symlink():
            raise MemoryError("Checkpoint already exists")
        state = self.snapshot()
        value = {"schema_version": SCHEMA_VERSION, "format": CHECKPOINT_FORMAT, "project": state["project"],
                 "state": state, "state_sha256": sha(state)}
        _atomic_write(destination, value, exclusive=True)
        return {"state_sha256": value["state_sha256"], "revision": state["revision"], "project": state["project"],
                "checkpoint_sha256": hashlib.sha256(canonical(value) + b"\n").hexdigest()}

    def restore(self, checkpoint, expected_sha256=None):
        """Restore into an empty store; tampered, unexpected or foreign-project checkpoints are refused."""
        self._require_write()
        checkpoint = pathlib.Path(checkpoint).absolute()
        _safe_directory(checkpoint.parent)
        data = _read_bytes(checkpoint)
        actual = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and _digest(expected_sha256) != actual:
            raise IntegrityError("Checkpoint differs from the expected SHA-256")
        value = load_json(data)
        if isinstance(value, dict) and value.get("schema_version") == 1:
            if set(value) != {"schema_version", "state", "state_sha256"} or value["state_sha256"] != sha(value["state"]):
                raise IntegrityError("Invalid checkpoint checksum/schema")
            state = _from_v1(value["state"])
        elif isinstance(value, dict) and set(value) == {"schema_version", "format", "project", "state", "state_sha256"} \
                and type(value["schema_version"]) is int and value["schema_version"] == SCHEMA_VERSION and value["format"] == CHECKPOINT_FORMAT:
            if value["state_sha256"] != sha(value["state"]) or not isinstance(value["state"], dict) or value["state"].get("project") != value["project"]:
                raise IntegrityError("Invalid checkpoint checksum/schema")
            state = value["state"]
            _verify_state(state)
        else:
            raise IntegrityError("Invalid checkpoint checksum/schema")
        state = _bind(state, self.project)
        with self._locked():
            if self._load()["revision"]:
                raise MemoryError("Restore requires an empty store")
            self._write(state)
        return {"state_sha256": sha(value["state"]), "revision": state["revision"], "project": state["project"],
                "checkpoint_sha256": actual}


# ---------------------------------------------------------------- engine contract (CONTRACTS.md section 2)

_READ, _WRITE = ["read:state", "secrets:none"], ["read:state", "write:state", "secrets:none"]
_ACTIONS = {
    # action: (method, required payload keys, optional payload keys, side effect, permissions, summary)
    "put": ("put", ("record",), (), "state-write", _WRITE, "Store a record (content-hash and near-title dedup)."),
    "search": ("search", ("query",), ("limit",), "none", _READ, "Schema-1 lexical-concept record search."),
    "retrieve": ("retrieve", (), ("query", "limit", "kinds", "tags", "include_symbols"), "none", _READ + ["read:repo"],
                 "Ranked retrieval over entries and indexed symbols."),
    "graph": ("graph", (), (), "none", _READ, "Project knowledge graph nodes and edges."),
    "neighbours": ("neighbours", ("node",), ("relation", "direction"), "none", _READ, "Typed neighbours of a graph node."),
    "path": ("graph_path", ("source", "target"), ("max_depth", "relations"), "none", _READ, "Shortest path between two graph nodes."),
    "adr-add": ("adr_add", ("title", "context", "decision", "consequences"), ("engine", "status", "supersedes", "tags", "symbols"),
                "state-write", _WRITE, "Record an architecture decision record."),
    "adr-status": ("adr_status", ("adr_id", "status"), (), "state-write", _WRITE, "Accept a proposed ADR."),
    "adr-get": ("adr", ("adr_id",), (), "none", _READ + ["read:repo"], "Read one ADR with its evidence status."),
    "why": ("why", ("question",), ("limit",), "none", _READ + ["read:repo"], "Why a decision was taken, from recorded text."),
    "solutions": ("solutions", (), (), "none", _READ + ["read:repo"], "Verified-solutions registry; unverified ones marked."),
    "verify": ("verify", ("id", "receipt_path", "receipt_sha256"), (), "state-write", _WRITE + ["read:repo"],
               "Bind a passed source-bound receipt to a solution or fix."),
    "failure-record": ("record_failure", ("signature", "summary"), ("engine", "title", "root_cause", "fix", "tags", "symbols"),
                       "state-write", _WRITE, "Record a failure signature, root cause and fix."),
    "failure-recall": ("recall_failure", ("signature",), ("limit",), "none", _READ + ["read:repo"], "Known failures for a signature."),
    "task-progress": ("task_progress", ("task_id", "title", "done", "remaining"),
                      ("engine", "status", "summary", "decisions", "symbols"), "state-write", _WRITE, "Record a new version of task progress."),
    "next-steps": ("next_steps", (), ("task_id",), "none", _READ, "Done, remaining and next steps per task."),
    "brief": ("brief", (), (), "none", _READ + ["read:repo"], "Resume briefing for a new session."),
    "index": ("index_repository", (), ("engine", "paths"), "state-write", _WRITE + ["read:repo"], "Index Python symbols."),
    "where": ("where", ("name",), ("limit",), "none", _READ + ["read:repo"], "Locate a symbol from the index."),
    "evidence-status": ("evidence_status", ("id",), (), "none", _READ + ["read:repo"], "Fresh, stale or missing source evidence."),
    "checkpoint": ("checkpoint", ("destination",), (), "state-write", _WRITE, "Write a SHA-256 sealed checkpoint."),
    "restore": ("restore", ("checkpoint",), ("expected_sha256",), "state-write", _WRITE, "Restore an empty store from a checkpoint."),
}
_SOURCE_ROOT = {"retrieve", "adr-get", "why", "solutions", "verify", "failure-recall", "brief", "index", "where", "evidence-status"}
_RENAMED = {"id": "identifier"}

ENGINE_RECORD = {
    "id": "memory", "layer": "L14",
    "title": {"en": "Persistent engineering memory", "ar": "الذاكرة الهندسية الدائمة"},
    "entrypoint": "engineering_os.memory:invoke", "health": "engineering_os.memory:health",
    "actions": {name: {"side_effect": spec[3], "permissions": list(spec[4]), "summary": spec[5]} for name, spec in _ACTIONS.items()},
    "supersedes": ["engineering_os.gaie_memory"],
}


def invoke(action, payload, ctx):
    """Engine entrypoint `(action, payload, ctx) -> dict`; always a project-isolated store under ctx['state_dir']."""
    if action not in _ACTIONS:
        raise MemoryError("Unknown memory action")
    if not isinstance(payload, dict) or not isinstance(ctx, dict) or not ctx.get("state_dir"):
        raise MemoryError("Payload object and ctx.state_dir (private memory root) are required")
    method, required, optional, side_effect, _, _ = _ACTIONS[action]
    keys = set(payload) - {"project"}
    if "project" not in payload or not set(required) <= keys or keys - set(required) - set(optional):
        raise MemoryError("Payload fields do not match the action")
    project = payload["project"]
    store = MemoryStore.for_project(ctx["state_dir"], project, create=side_effect != "none")
    arguments = {_RENAMED.get(key, key): payload[key] for key in keys}
    if action in _SOURCE_ROOT:
        if action in {"verify", "index"} and not ctx.get("source_root"):
            raise MemoryError("ctx.source_root is required")
        arguments["source_root"] = ctx.get("source_root")
    for key in ("kinds", "tags", "relations", "decisions", "symbols", "paths", "done", "remaining"):
        if key in arguments and not isinstance(arguments[key], list):
            raise MemoryError(f"{key} must be a list")
    if action == "put":
        if not isinstance(payload["record"], dict) or payload["record"].get("project") != project:
            raise IsolationError("Record project must match the payload project")
        return store.put(payload["record"])
    if action in {"checkpoint", "restore"}:
        return getattr(store, method)(**arguments)
    result = getattr(store, method)(project, **arguments)
    return result if isinstance(result, dict) else {"items": result}


def health():
    """Side-effect-free self check: the guard refuses a synthetic token and the format round-trips."""
    try:
        try:
            _refuse_secrets("gh" + "p_" + "Z" * 36)
            return {"ok": False, "detail": "secret guard accepted a synthetic token"}
        except SecretRefused:
            pass
        state = _empty("health")
        if _parse(_serialize(state)) != state:
            return {"ok": False, "detail": "state serialization does not round-trip"}
        return {"ok": True, "detail": f"{ENGINE_ID} schema {SCHEMA_VERSION}: guard and serialization verified in memory"}
    except Exception as error:  # health reports, never raises
        return {"ok": False, "detail": type(error).__name__}
