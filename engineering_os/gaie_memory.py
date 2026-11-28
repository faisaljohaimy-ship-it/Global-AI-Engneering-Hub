"""GAIE engineering memory: private, project-scoped, append-only knowledge.

Entries live under $GAIE_HOME/memory/<project>/entries.jsonl, outside every Git
repository, one directory per project. A query names exactly one project and
never reads another. Credential-shaped text is refused. Retrieval is lexical
(normalized Arabic/English token overlap), not embedding-based; `links` give a
one-hop knowledge graph. Standard library only. SPDX-License-Identifier: MIT.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import sys

try:
    from . import gaie_router as router
except ImportError:  # vendored beside the router
    import gaie_router as router

KINDS = ("decision", "pattern", "solution", "failure", "root-cause", "repair", "test-result",
         "quality-standard", "performance", "checkpoint", "release", "lesson")
RELATIONS = ("supersedes", "caused-by", "fixes", "depends-on", "relates-to")
PROJECT = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
DIGEST = re.compile(r"[a-f0-9]{64}")
MAX_BODY, MAX_ENTRIES, MAX_BYTES = 4000, 5000, 8 * 1024 * 1024
SECRET = re.compile(
    r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY|\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"
    r"|\bsk-(?:proj-|ant-|svcacct-|admin-)?[A-Za-z0-9_-]{24,}|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bAIza[A-Za-z0-9_-]{35}\b"
    r"|\bsb_secret_[A-Za-z0-9_-]{20,}|\bxox[baprs]-[A-Za-z0-9-]{10,}|\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}"
    r"|\bsk_[a-f0-9]{48}\b|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
    r"|\bBearer\s+[A-Za-z0-9_./+=-]{16,}|://[^\s/:@]+:[^\s/@]+@"
    r"|(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{8,}", re.I)


class MemoryError_(ValueError):
    pass


def _text(value, limit, name):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise MemoryError_(f"{name} must be 1-{limit} characters")
    if SECRET.search(value):
        raise MemoryError_(f"{name} looks like it contains a credential; refused")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise MemoryError_(f"{name} contains control characters")
    return value.strip()


class Memory:
    def __init__(self, project, environ=None):
        if not isinstance(project, str) or not PROJECT.fullmatch(project):
            raise MemoryError_("project must be a lowercase slug")
        self.project = project
        self.root = router.gaie_home(environ) / "memory" / project
        self.path = self.root / "entries.jsonl"

    def _guard(self):
        current = self.root
        for _ in range(3):
            if current.is_symlink():
                raise MemoryError_("symlink in memory path refused")
            current = current.parent
        if self.path.is_symlink():
            raise MemoryError_("symlink in memory path refused")

    def entries(self):
        self._guard()
        if not self.path.is_file():
            return []
        if self.path.stat().st_size > MAX_BYTES:
            raise MemoryError_("memory store exceeds its size bound")
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            body = {key: row[key] for key in row if key not in ("id", "created")}
            if row.get("project") != self.project or row.get("id") != _digest(body):
                raise MemoryError_("memory entry failed its integrity check")
            rows.append(row)
        return rows

    def add(self, kind, title, body, tags=(), evidence=(), links=(), now=None):
        if kind not in KINDS:
            raise MemoryError_(f"kind must be one of: {', '.join(KINDS)}")
        tags = sorted({_text(tag, 40, "tag").casefold() for tag in tags})
        receipts = []
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"kind", "sha256"} or not DIGEST.fullmatch(str(item["sha256"])):
                raise MemoryError_("evidence needs kind and a sha256 digest only")
            receipts.append({"kind": _text(item["kind"], 60, "evidence kind"), "sha256": item["sha256"]})
        existing = self.entries()
        known = {row["id"] for row in existing}
        edges = []
        for item in links:
            if not isinstance(item, dict) or set(item) != {"relation", "target"} or item["relation"] not in RELATIONS:
                raise MemoryError_("link needs a known relation and a target")
            if item["target"] not in known:
                raise MemoryError_("link target is not an entry of this project")
            edges.append({"relation": item["relation"], "target": item["target"]})
        content = {"project": self.project, "kind": kind, "title": _text(title, 160, "title"),
                   "body": _text(body, MAX_BODY, "body"), "tags": tags, "evidence": receipts, "links": edges}
        identity = _digest(content)
        if identity in known:
            return {"status": "duplicate", "id": identity}
        if len(existing) >= MAX_ENTRIES:
            raise MemoryError_("memory store is full; archive before adding")
        stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = {"id": identity, "created": stamp, **content}
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._guard()
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return {"status": "stored", "id": identity}

    def search(self, query="", kind=None, tag=None, limit=10):
        if kind is not None and kind not in KINDS:
            raise MemoryError_("unknown kind")
        wanted = set(router.normalize(query))
        scored = []
        for row in self.entries():
            if (kind and row["kind"] != kind) or (tag and tag.casefold() not in row["tags"]):
                continue
            title = set(router.normalize(row["title"])) | set(row["tags"])
            words = title | set(router.normalize(row["body"]))
            score = 2 * len(wanted & title) + len(wanted & words)
            if score or not wanted:
                scored.append((score, row["created"], row))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [dict(row, score=score) for score, _, row in scored[:max(1, min(limit, 50))]]

    def related(self, identity):
        rows = {row["id"]: row for row in self.entries()}
        if identity not in rows:
            raise MemoryError_("unknown entry")
        outgoing = [{"relation": link["relation"], "entry": rows[link["target"]]} for link in rows[identity]["links"]]
        incoming = [{"relation": link["relation"], "from": row} for row in rows.values()
                    for link in row["links"] if link["target"] == identity]
        return {"entry": rows[identity], "outgoing": outgoing, "incoming": incoming}

    def promote(self, identity):
        """A project-free candidate for manual review before any public reuse."""
        rows = {row["id"]: row for row in self.entries()}
        if identity not in rows:
            raise MemoryError_("unknown entry")
        row = rows[identity]
        return {"status": "candidate-requires-human-review", "kind": row["kind"], "title": row["title"],
                "body": row["body"], "tags": row["tags"],
                "warning": "Remove client names, identifiers and private context before publishing."}


def _digest(content):
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True)
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
    search.add_argument("--kind", choices=KINDS)
    search.add_argument("--tag")
    search.add_argument("--limit", type=int, default=10)
    for name in ("related", "promote"):
        commands.add_parser(name).add_argument("id")
    args = parser.parse_args(argv)
    try:
        memory = Memory(args.project)
        if args.cmd == "add":
            evidence = [dict(zip(("kind", "sha256"), item.split("=", 1))) for item in args.evidence]
            links = [dict(zip(("relation", "target"), item.split("=", 1))) for item in args.link]
            result = memory.add(args.kind, args.title, args.body, args.tag, evidence, links)
        elif args.cmd == "search":
            result = memory.search(args.query, args.kind, args.tag, args.limit)
        elif args.cmd == "related":
            result = memory.related(args.id)
        else:
            result = memory.promote(args.id)
    except (MemoryError_, router.RouteError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
