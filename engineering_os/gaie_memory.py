"""GAIE engineering memory: private, project-scoped knowledge for Claude Code sessions.

A facade over the unified engine `engineering_os.memory` (layer L14). Each project is
an isolated engine store at $GAIE_HOME/memory/<project>/memory.jsonl, outside every
Git repository; a query names exactly one project and never reads another. The PR #26
API and CLI are kept (add, search, related, promote, entries) and the engine adds
brief, next, where, why, adr, task, failure, recall, solutions, index, status,
checkpoint and restore. Legacy append-only journals (entries.jsonl) are verified and imported
into the engine on first use, so nothing written by an older copy is lost.

Vendored alone (a skill engine directory or project pack without memory.py,
orchestration.py and security_scan.py beside it) the engine cannot be imported, so the
frozen PR #26 journal serves add/search/related/promote ("portable-journal" backend);
it refuses a project the engine already manages, so the two never split. Credential
-shaped text is refused on a best-effort basis: a filter, not a guarantee, so do not
paste secrets. Retrieval is lexical, not embedding-based. Standard library only.
SPDX-License-Identifier: MIT.
"""
import argparse
import contextlib
import datetime
import errno
import fcntl
import hashlib
import importlib
import importlib.util
import json
import os
import pathlib
import re
import stat
import sys
import unicodedata

try:
    from . import gaie_router as router
except ImportError:  # vendored beside the router
    import gaie_router as router

HERE = pathlib.Path(__file__).resolve().parent


def _load_engine():
    """The unified engine: package import, a hub checkout run as a script, or vendored files; else None."""
    if __package__:
        return importlib.import_module(".memory", __package__)
    if HERE.name == "engineering_os" and (HERE / "memory.py").is_file() and (HERE.parent / "scripts/security_scan.py").is_file():
        if str(HERE.parent) not in sys.path:
            sys.path.insert(0, str(HERE.parent))
        return importlib.import_module("engineering_os.memory")
    if all((HERE / name).is_file() for name in ("memory.py", "orchestration.py", "security_scan.py", "gaie_router.py")):
        spec = importlib.util.spec_from_file_location("gaie_engine_memory", HERE / "memory.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return None


ENGINE = _load_engine()
KINDS = ("decision", "pattern", "solution", "failure", "root-cause", "repair", "test-result",
         "quality-standard", "performance", "checkpoint", "release", "lesson", "architecture", "recovery")
LEGACY_RELATIONS = ("supersedes", "caused-by", "fixes", "depends-on", "relates-to")
RELATIONS = ENGINE.RELATIONS if ENGINE else LEGACY_RELATIONS
PROJECT = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
DIGEST = re.compile(r"[a-f0-9]{64}")
JOURNAL = "entries.jsonl"
JOURNAL_LOCK = "entries.lock"
FIELDS = ("project", "kind", "title", "body", "tags", "evidence", "links", "previous", "created")
MAX_BODY, MAX_ENTRIES, MAX_BYTES = 4000, 5000, 8 * 1024 * 1024
# Token edges are ASCII-aware: `\b` treats an Arabic letter, a digit or "_" as part of the word, so
# "وAKIA…" (the conjunction wa- attached to a key) or "aws_AKIA…" slipped past it.
_L, _R = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
# Arabic labels for a password, a secret number, an access key or code and the loanwords توكن / باسورد, at parity
# with the English rule below (recheck-authz M2): any suffix on the label, then ":", "=" or the prose "هي"/"هو"
# ("is") and a value, with up to three words of the same line between label and separator; ة or ه and ي or ى
# spellings. Harakat and tatweel are removed from a scanned copy (_ARABIC_MARKS). Without such a separator the
# label is prose ("كلمة المرور يجب أن تكون طويلة") and stays storable.
_ARABIC_SECRET_LABEL = (r"(?:كلم[ةه]\s+(?:ال)?(?:مرور|سر)|(?:ال)?رقم\s+(?:ال)?سر[يى]"
                        r"|رمز\s+(?:ال)?(?:مرور|دخول|وصول|تحقق|سر[يى])|مفتاح\s+(?:ال)?\s*(?:api|واجهة|وصول|سر[يى]|خاص)"
                        r"|(?:ال)?(?:توكن|باسورد|باسوورد))\w*"
                        r"(?:[ \t]+[^\s:=\"'«»,،؛.]+){0,3}?(?:\s*[:=]\s*|\s+(?:هي|هو|هى)\s+)[\"'«]?\S{4,}")
_ARABIC_MARKS = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")  # harakat, Quranic marks, tatweel
# The engine's BROAD_SECRET (engineering_os/memory.py), kept identical for a vendored copy without the engine.
SECRET = re.compile(
    rf"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY|{_L}gh[pousr]_[A-Za-z0-9]{{20,}}|{_L}github_pat_[A-Za-z0-9_]{{20,}}"
    rf"|{_L}glpat-[A-Za-z0-9_-]{{16,}}|{_L}npm_[A-Za-z0-9]{{20,}}|{_L}whsec_[A-Za-z0-9]{{16,}}|{_L}sbp_[A-Za-z0-9]{{20,}}"
    rf"|{_L}ya29\.[A-Za-z0-9_-]{{16,}}|{_L}sk-(?:proj-|ant-|svcacct-|admin-)?[A-Za-z0-9_-]{{24,}}"
    rf"|{_L}(?:AKIA|ASIA)[0-9A-Z]{{16}}{_R}|{_L}AIza[A-Za-z0-9_-]{{35}}{_R}|{_L}sb_secret_[A-Za-z0-9_-]{{20,}}"
    rf"|{_L}xox[baprs]-[A-Za-z0-9-]{{10,}}|{_L}(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{{20,}}|{_L}sk_[a-f0-9]{{48}}{_R}"
    rf"|{_L}eyJ[A-Za-z0-9_-]{{10,}}\.[A-Za-z0-9_-]{{20,}}\.[A-Za-z0-9_-]{{20,}}"
    rf"|{_L}(?:Bearer|Basic)\s+[A-Za-z0-9_./+=-]{{12,}}|://[^\s/@]+:[^\s@]+@|hooks\.slack\.com/services/"
    r"|(?:password|passwd|pwd|secret|api[\s_-]?key|token|private[\s_-]?key|access[\s_-]?key|role[\s_-]?key|credential)\w*"
    rf"[\"']?\s*(?:[:=]|{_L}is{_R})\s*[\"']?\S{{4,}}|{_ARABIC_SECRET_LABEL}", re.I)


SPLIT = re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:proj-|ant-)[A-Za-z0-9_-]{24,}|xox[baprs]-[A-Za-z0-9-]{20,}")


class MemoryError_(ValueError):
    pass


READ_METHODS = frozenset({"adr", "adrs", "brief", "entries", "evidence_status", "graph", "graph_path", "neighbours",
                          "next_steps", "recall_failure", "retrieve", "search", "solutions", "symbol_status", "where",
                          "why"})


def _imported(store, project):
    """{journal entry id: engine id} of the legacy journal entries this engine store already holds."""
    return {provenance["source_sha256"]: entry["id"] for entry in store.entries(project)
            for provenance in entry["provenances"] + [item["provenance"] for item in entry["merged"]]}


def _text(value, limit, name):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise MemoryError_(f"{name} must be 1-{limit} characters")
    value = unicodedata.normalize("NFKC", value)
    if any(SECRET.search(text) or SPLIT.search(re.sub(r"\s+", "", text))  # SPLIT: a token broken across lines
           for text in (value, _ARABIC_MARKS.sub("", value))):
        raise MemoryError_(f"{name} looks like it contains a credential; refused")
    if any((ord(char) < 32 and char not in "\n\t") or unicodedata.category(char) in ("Cf", "Zl", "Zp") for char in value):
        raise MemoryError_(f"{name} contains control characters")
    return value.strip()


def _digest(content):
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@contextlib.contextmanager
def _translated():
    """Engine, coordination and routing refusals surface as MemoryError_ (the PR #26 contract)."""
    try:
        yield
    except MemoryError_:
        raise
    except ValueError as error:  # engine MemoryError, CoordinationError, RouteError and JSON errors are ValueErrors
        raise MemoryError_(str(error)) from None


def _engine_required():
    if ENGINE is None:
        raise MemoryError_("this command needs the unified engine: vendor memory.py, orchestration.py and "
                           "security_scan.py beside gaie_memory.py (docs/specs/gaie-20-layers/MEMORY.md)")


class Memory:
    def __init__(self, project, environ=None):
        if not isinstance(project, str) or not PROJECT.fullmatch(project):
            raise MemoryError_("project must be a lowercase slug")
        self.project = project
        self.home = router.gaie_home(environ)
        self.root = self.home / "memory" / project
        self.journal = self.root / JOURNAL
        self.backend = "engine" if ENGINE else "portable-journal"
        self.path = self.root / ENGINE.STATE_FILE if ENGINE else self.journal
        self.import_report = None

    # -- engine backend ------------------------------------------------------

    def store(self, create=True):
        """This project's isolated engine store (None when nothing is recorded and create is False)."""
        _engine_required()
        with _translated():
            legacy = self.journal.is_file() and not self.journal.is_symlink()
            if not create and not legacy and not os.path.lexists(self.root):
                return None
            if create or legacy:
                self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                store = ENGINE.MemoryStore.for_project(self.home / "memory", self.project, create=create or legacy)
            except ENGINE.MissingMemory:
                return None
            if legacy:
                self._import_journal(store)
            return store

    def reader(self):
        """This project's engine store opened read-only, or None when nothing is recorded (pr30-authz F2).

        A read creates nothing: no directory, no lock file, no persisted schema migration. The one exception is
        the documented first use of a legacy journal that holds entries the engine has not imported yet: those are
        imported first, through store()."""
        _engine_required()
        with _translated():
            store = None
            if os.path.lexists(self.root):
                base = self.home / "memory"
                info = os.lstat(base)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                    raise MemoryError_("$GAIE_HOME/memory must be a caller-owned mode 0700 directory")
                if self.root.is_symlink() or os.path.realpath(self.root) != os.path.join(os.path.realpath(base), self.project):
                    raise MemoryError_("project memory directory must be a real directory inside its root")
                try:
                    store = ENGINE.MemoryStore(self.root, project=self.project, create=False, read_only=True)
                    store.snapshot()
                except ENGINE.MissingMemory:
                    store = None
            if self.journal.is_file() and not self.journal.is_symlink():
                rows = _journal_rows(self)
                if rows and (store is None or {row["id"] for row in rows} - set(_imported(store, self.project))):
                    return self.store(create=False)
            return store

    def _import_journal(self, store):
        """Verify the PR #26 hash chain and import new journal entries into the engine in one transaction."""
        rows = _journal_rows(self)
        seen = _imported(store, self.project)
        items, known = [], {}
        for row in rows:
            if row["id"] in seen:
                known[row["id"]] = seen[row["id"]]
                continue
            record = {"project": self.project, "kind": row["kind"], "title": row["title"], "summary": row["body"],
                      "tags": row["tags"], "symbols": [], "links": [], "evidence": row["evidence"],
                      "provenance": {"engine": "claude-code", "source_sha256": row["id"]}}
            refs = [{"relation": link["relation"], "key": link["target"]} for link in row["links"]]
            for ref in refs:  # targets imported earlier resolve through their recorded engine ids
                if ref["key"] in known:
                    record.setdefault("relations", []).append({"relation": ref["relation"], "target": known[ref["key"]]})
            created = datetime.datetime.strptime(row["created"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
            items.append({"key": row["id"], "record": record, "refs": [ref for ref in refs if ref["key"] not in known], "now": created})
        if items:
            result = store.import_batch(self.project, items)
            self.import_report = {"imported": len(result["ids"]), "refused": len(result["refused"])}

    @staticmethod
    def _row(entry, previous):
        record = entry["record"]
        links = [{"relation": item["relation"], "target": item["target"]} for item in record.get("relations", ())]
        links += [{"relation": "references", "target": target} for target in record["links"]]
        return {"id": entry["id"], "project": record["project"], "kind": record["kind"], "title": record["title"],
                "body": record["summary"], "tags": list(record["tags"]), "evidence": list(record.get("evidence", ())),
                "links": links, "previous": previous, "created": entry["created"]}

    def _portable(self):
        if (self.root / "memory.jsonl").exists():
            raise MemoryError_("this project is managed by the unified engine; this copy cannot read it. Vendor "
                               "memory.py, orchestration.py and security_scan.py beside gaie_memory.py")

    # -- PR #26 API ----------------------------------------------------------

    def entries(self):
        if ENGINE is None:
            self._portable()
            return _journal_rows(self)
        store = self.reader()
        if store is None:
            return []
        with _translated():
            entries = store.entries(self.project)
        return [self._row(entry, entries[index - 1]["id"] if index else None) for index, entry in enumerate(entries)]

    def add(self, kind, title, body, tags=(), evidence=(), links=(), now=None, engine="claude-code"):
        if kind not in KINDS:
            raise MemoryError_(f"kind must be one of: {', '.join(KINDS)}")
        tags = sorted({_text(tag, 40, "tag").casefold() for tag in tags})
        receipts = []
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"kind", "sha256"} or not DIGEST.fullmatch(str(item["sha256"])):
                raise MemoryError_("evidence needs kind and a sha256 digest only")
            receipts.append({"kind": _text(item["kind"], 60, "evidence kind"), "sha256": item["sha256"]})
        edges = []
        for item in links:
            if not isinstance(item, dict) or set(item) != {"relation", "target"} or item["relation"] not in RELATIONS:
                raise MemoryError_("link needs a known relation and a target")
            edges.append({"relation": item["relation"], "target": item["target"]})
        title, body = _text(title, 160, "title"), _text(body, MAX_BODY, "body")
        if ENGINE is None:
            self._portable()
            return _journal_add(self, kind, title, body, tags, receipts, edges, now)
        content = {"project": self.project, "kind": kind, "title": title, "body": body, "tags": tags, "evidence": receipts, "links": edges}
        record = {"project": self.project, "kind": kind, "title": title, "summary": body, "tags": tags, "symbols": [], "links": [],
                  "relations": edges, "evidence": receipts, "provenance": {"engine": engine, "source_sha256": _digest(content)}}
        with _translated():
            if not all(isinstance(edge["target"], str) and DIGEST.fullmatch(edge["target"]) for edge in edges):
                raise MemoryError_("link target is not an entry of this project")
            try:
                result = self.store().put(record, now=now)
            except ENGINE.MemoryError as error:
                if "Link requires" in str(error):
                    raise MemoryError_("link target is not an entry of this project") from None
                raise
        status = "merged" if result["merged"] else "duplicate" if result["deduplicated"] else "stored"
        return {"status": status, "id": result["id"]}

    def search(self, query="", kind=None, tag=None, limit=10):
        if kind is not None and kind not in (ENGINE.KINDS if ENGINE else KINDS):
            raise MemoryError_("unknown kind")
        limit = max(1, min(limit, 50))
        if ENGINE is None:
            self._portable()
            return _journal_search(self, query, kind, tag, limit)
        store = self.reader()
        if store is None:
            return []
        with _translated():
            hits = store.retrieve(self.project, query or None, limit=limit, kinds=[kind] if kind else None,
                                  tags=[tag] if tag else None, include_symbols=False)
        rows = {row["id"]: row for row in self.entries()}
        return [dict(rows[hit["id"]], score=hit["score"]) for hit in hits]

    def related(self, identity):
        rows = {row["id"]: row for row in self.entries()}
        if identity not in rows:
            raise MemoryError_("unknown entry")
        if ENGINE is None:
            outgoing = [{"relation": link["relation"], "entry": rows[link["target"]]} for link in rows[identity]["links"]]
            incoming = [{"relation": link["relation"], "from": row} for row in rows.values()
                        for link in row["links"] if link["target"] == identity]
            return {"entry": rows[identity], "outgoing": outgoing, "incoming": incoming}
        with _translated():
            graph = self.reader().neighbours(self.project, identity)
        return {"entry": rows[identity],
                "outgoing": [{"relation": edge["relation"], "entry": rows[edge["node"]["id"]]} for edge in graph["outgoing"]
                             if edge["node"]["type"] == "entry"],
                "incoming": [{"relation": edge["relation"], "from": rows[edge["node"]["id"]]} for edge in graph["incoming"]
                             if edge["node"]["type"] == "entry"]}

    def promote(self, identity):
        """A project-free candidate for manual review before any public reuse."""
        rows = {row["id"]: row for row in self.entries()}
        if identity not in rows:
            raise MemoryError_("unknown entry")
        row = rows[identity]
        return {"status": "candidate-requires-human-review", "kind": row["kind"], "title": row["title"],
                "body": row["body"], "tags": row["tags"],
                "warning": "Remove client names, identifiers and private context before publishing."}

    # -- engine-only API (ADR, tasks, failures, symbols, checkpoints) ----------

    def call(self, method, *args, create=True, **kwargs):
        """Run an engine method bound to this project; refusals surface as MemoryError_. Read methods open the store
        read-only and create nothing."""
        store = self.reader() if method in READ_METHODS else self.store(create=create)
        if store is None:
            raise MemoryError_("no memory recorded for this project yet")
        with _translated():
            target = getattr(store, method)
            return target(*args, **kwargs) if method in {"checkpoint", "restore"} else target(self.project, *args, **kwargs)


# -- frozen PR #26 journal (portable backend and import source) -----------------

def _journal_guard(memory):
    """SEC-10: GAIE_HOME, its memory directory and the project directory, where they exist, are real directories the
    caller owns; GAIE_HOME is not writable by group or others and the two memory directories are mode 0700."""
    for directory, mask, shown in ((memory.home, 0o022, "$GAIE_HOME"), (memory.root.parent, 0o077, "$GAIE_HOME/memory"),
                                   (memory.root, 0o077, f"$GAIE_HOME/memory/{memory.project}")):
        try:
            info = os.lstat(directory)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise MemoryError_("symlink in memory path refused")
        if not stat.S_ISDIR(info.st_mode):
            raise MemoryError_(f"{shown} is not a directory; refused")
        if info.st_uid != os.getuid():
            raise MemoryError_(f"{shown} is owned by another user; refused")
        if stat.S_IMODE(info.st_mode) & mask:
            fix = "go-w" if mask == 0o022 else "700"
            raise MemoryError_(f"{shown} is open to other users; refused. Fix: chmod {fix} \"{shown}\"")


def _private_file(memory, name, flags, what):
    """SEC-10: a file of the project directory as a regular file the caller owns, with one link and no group/other
    bits. O_NOFOLLOW refuses a symbolic link, O_NONBLOCK keeps a FIFO from blocking the open, and fstat checks the
    opened file itself. An existing file that fails a check is refused, never repaired: the message names the fix."""
    shown = f'"$GAIE_HOME/memory/{memory.project}/{name}"'
    try:
        descriptor = os.open(memory.root / name, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise MemoryError_("symlink in memory path refused") from None
        if error.errno == errno.ENXIO:
            raise MemoryError_(f"{what} is not a regular file; refused") from None
        raise MemoryError_(f"{what} cannot be opened ({errno.errorcode.get(error.errno, 'error')})") from None
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        problem = f"{what} is not a regular file; refused"
    elif info.st_uid != os.getuid():
        problem = f"{what} is owned by another user; refused"
    elif info.st_nlink != 1:
        problem = (f"{what} has {info.st_nlink} links, so a write could land in another file; refused. "
                   f"Fix: cp {shown} {shown[:-1]}.new\" && mv {shown[:-1]}.new\" {shown}")
    elif stat.S_IMODE(info.st_mode) & 0o077:
        problem = f"{what} is open to other users; refused. Fix: chmod 600 {shown}"
    else:
        return descriptor
    os.close(descriptor)
    raise MemoryError_(problem)


def _journal_open(memory, flags):
    return _private_file(memory, JOURNAL, flags, "memory journal")


@contextlib.contextmanager
def _journal_locked(memory, exclusive):
    """w2-memory-heal-orch M1: one writer at a time over read, check and append (an exclusive flock on a private lock
    file beside the journal). Readers share the lock when the lock file exists; a read never creates it."""
    if not exclusive and not os.path.lexists(memory.root / JOURNAL_LOCK):
        yield
        return
    descriptor = _private_file(memory, JOURNAL_LOCK, os.O_RDWR | os.O_CREAT if exclusive else os.O_RDONLY,
                               "memory journal lock")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        os.close(descriptor)


def _journal_rows(memory):
    _journal_guard(memory)
    if not os.path.lexists(memory.journal):
        return []
    with _journal_locked(memory, exclusive=False):
        return _read_journal(memory)


def _read_journal(memory):
    if not os.path.lexists(memory.journal):
        return []
    with os.fdopen(_journal_open(memory, os.O_RDONLY), "rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise MemoryError_("memory store exceeds its size bound")
    rows, previous = [], None
    for line in data.decode("utf-8").splitlines():
        try:
            row = json.loads(line)
            body = {key: row[key] for key in FIELDS}
        except (ValueError, KeyError, TypeError):
            raise MemoryError_("memory entry is malformed") from None
        if set(row) != set(FIELDS) | {"id"} or row["project"] != memory.project or row["id"] != _digest(body) \
                or row["previous"] != previous:
            raise MemoryError_("memory entry failed its integrity check")
        previous = row["id"]
        rows.append(row)
    return rows


def _journal_next(memory, existing, kind, title, body, tags, receipts, edges, now):
    """(id, row to append after `existing`), or (id of the duplicate, None); refusals raise MemoryError_."""
    known = {row["id"] for row in existing}
    for edge in edges:
        if edge["relation"] not in LEGACY_RELATIONS or edge["target"] not in known:
            raise MemoryError_("link target is not an entry of this project")
    content = {"project": memory.project, "kind": kind, "title": title, "body": body, "tags": tags, "evidence": receipts, "links": edges}
    duplicate = next((row["id"] for row in existing if all(row[key] == content[key] for key in content)), None)
    if duplicate:
        return duplicate, None
    if len(existing) >= MAX_ENTRIES:
        raise MemoryError_("memory store is full; archive before adding")
    content["previous"] = existing[-1]["id"] if existing else None
    content["created"] = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    identity = _digest(content)
    return identity, {"id": identity, **content}


def _journal_add(memory, kind, title, body, tags, receipts, edges, now):
    identity, row = _journal_next(memory, _journal_rows(memory), kind, title, body, tags, receipts, edges, now)
    if row is None:
        return {"status": "duplicate", "id": identity}
    for directory in (memory.root.parent.parent, memory.root.parent):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    memory.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _journal_guard(memory)
    with _journal_locked(memory, exclusive=True):
        # Again under the lock: another writer may have appended since the first read.
        identity, row = _journal_next(memory, _read_journal(memory), kind, title, body, tags, receipts, edges, now)
        if row is None:
            return {"status": "duplicate", "id": identity}
        data = memoryview((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
        descriptor = _journal_open(memory, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            while data:
                data = data[os.write(descriptor, data):]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return {"status": "stored", "id": identity}


def _journal_search(memory, query, kind, tag, limit):
    wanted = set(router.normalize(query))
    scored = []
    for row in _journal_rows(memory):
        if (kind and row["kind"] != kind) or (tag and tag.casefold() not in row["tags"]):
            continue
        title = set(router.normalize(row["title"])) | set(row["tags"])
        words = title | set(router.normalize(row["body"]))
        score = 2 * len(wanted & title) + len(wanted & words)
        if score or not wanted:
            scored.append((score, row["created"], row))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [dict(row, score=score) for score, _, row in scored[:limit]]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--engine", choices=("claude-code", "codex"), default="claude-code", help="provenance of new knowledge")
    commands = parser.add_subparsers(dest="cmd", required=True)
    add = commands.add_parser("add")
    add.add_argument("--kind", required=True, choices=KINDS)
    add.add_argument("--title", required=True)
    add.add_argument("--body", required=True)
    add.add_argument("--tag", action="append", default=[])
    add.add_argument("--evidence", action="append", default=[], metavar="KIND=SHA256")
    add.add_argument("--link", action="append", default=[], metavar="RELATION=ENTRY_ID")
    search = commands.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--kind", choices=ENGINE.KINDS if ENGINE else KINDS)
    search.add_argument("--tag")
    search.add_argument("--limit", type=int, default=10)
    for name in ("related", "promote"):
        commands.add_parser(name).add_argument("id")
    # Engine-only commands: how a new session resumes (see docs/specs/gaie-20-layers/MEMORY.md).
    commands.add_parser("brief", help="resume briefing: open tasks, next steps, ADRs, failures, symbol index")
    commands.add_parser("next").add_argument("--task")
    commands.add_parser("where", help="locate a symbol from the index").add_argument("name")
    commands.add_parser("why", help="why a decision was taken (ADR-NNNN or a question)").add_argument("question")
    adr = commands.add_parser("adr", help="record an architecture decision")
    for name in ("--title", "--context", "--decision", "--consequences"):
        adr.add_argument(name, required=True)
    adr.add_argument("--status", choices=("proposed", "accepted"), default="proposed")
    adr.add_argument("--supersedes")
    commands.add_parser("adr-accept").add_argument("adr_id")
    task = commands.add_parser("task", help="record a new version of task progress")
    task.add_argument("--id", required=True)
    task.add_argument("--title", required=True)
    task.add_argument("--done", action="append", default=[])
    task.add_argument("--remaining", action="append", default=[])
    task.add_argument("--decision", action="append", default=[])
    task.add_argument("--status", choices=("in-progress", "blocked", "done"))
    failure = commands.add_parser("failure", help="record a failure signature, root cause and fix")
    failure.add_argument("--signature", required=True)
    failure.add_argument("--summary", required=True)
    failure.add_argument("--root-cause")
    failure.add_argument("--fix")
    commands.add_parser("recall", help="known failures for a signature").add_argument("signature")
    commands.add_parser("solutions").add_argument("--source-root")
    commands.add_parser("index", help="index Python symbols of a source tree").add_argument("--root", required=True)
    commands.add_parser("status", help="indexed files: fresh, stale or missing in a checkout").add_argument("--root", required=True)
    commands.add_parser("checkpoint").add_argument("--to", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--from", dest="source", required=True)
    restore.add_argument("--sha256")
    args = parser.parse_args(argv)
    try:
        memory = Memory(args.project)
        if args.cmd == "add":
            evidence = [dict(zip(("kind", "sha256"), item.split("=", 1))) for item in args.evidence]
            links = [dict(zip(("relation", "target"), item.split("=", 1))) for item in args.link]
            result = memory.add(args.kind, args.title, args.body, args.tag, evidence, links, engine=args.engine)
        elif args.cmd == "search":
            result = memory.search(args.query, args.kind, args.tag, args.limit)
        elif args.cmd == "related":
            result = memory.related(args.id)
        elif args.cmd == "promote":
            result = memory.promote(args.id)
        elif args.cmd == "brief":
            result = memory.call("brief", create=False)
        elif args.cmd == "next":
            result = memory.call("next_steps", args.task, create=False)
        elif args.cmd == "where":
            result = memory.call("where", args.name, create=False)
        elif args.cmd == "why":
            result = memory.call("why", args.question, create=False)
        elif args.cmd == "adr":
            result = memory.call("adr_add", args.title, args.context, args.decision, args.consequences, engine=args.engine,
                                 status=args.status, supersedes=args.supersedes)
        elif args.cmd == "adr-accept":
            result = memory.call("adr_status", args.adr_id, "accepted")
        elif args.cmd == "task":
            result = memory.call("task_progress", args.id, args.title, args.done, args.remaining, engine=args.engine,
                                 status=args.status, decisions=args.decision)
        elif args.cmd == "failure":
            result = memory.call("record_failure", args.signature, args.summary, engine=args.engine,
                                 root_cause=args.root_cause, fix=args.fix)
        elif args.cmd == "recall":
            result = memory.call("recall_failure", args.signature, create=False)
        elif args.cmd == "solutions":
            result = memory.call("solutions", source_root=args.source_root, create=False)
        elif args.cmd == "index":
            result = memory.call("index_repository", args.root, engine=args.engine)
        elif args.cmd == "status":
            result = memory.call("symbol_status", args.root, create=False)
        elif args.cmd == "checkpoint":
            result = memory.call("checkpoint", args.to, create=False)
        else:
            result = memory.call("restore", args.source, expected_sha256=args.sha256)
    except (MemoryError_, router.RouteError, OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
