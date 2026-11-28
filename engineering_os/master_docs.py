"""Central manifest of the MASTER documents: version, SHA-256 and pin history.

The MASTER documents (prompts/MASTER_BUILD.md, prompts/MASTER_UPGRADE.md) are the
agent instructions behind the build and upgrade engines. The manifest
governance/policies/master-prompts.json records for each one its canonical path,
current version, SHA-256, size, the install destinations it is copied to, and an
append-only history of pinned versions. This module finds the manifest relative
to its own location in every install layout, verifies the bytes on disk against
it, and returns a document only when they match. `pin` is the only command that
changes a version, a digest or the history.

What a match proves: the bytes on disk equal a recorded digest. What it does not
prove: that the owner approved them. One pull request can change a document and
the manifest together; approval rests on review rules outside this file
(CODEOWNERS plus branch protection on main). The history chain detects an edited,
reordered or removed entry, but anyone who can edit the file can recompute the
chain, so it is an integrity check, not a signature. Editing a MASTER document
changes agent instructions, not engine code.

Standard library only and standalone (no package imports), so the file can be
vendored beside the router. SPDX-License-Identifier: MIT.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import stat
import sys

if __name__ == "__main__":
    sys.dont_write_bytecode = True

HERE = pathlib.Path(__file__).resolve().parent
SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 1 << 20
MAX_DOCUMENT_BYTES = 1 << 20
MAX_LABEL = 200
# Where this loader and the manifest sit in each install layout, relative to the
# layout root. "hub": a hub checkout, and also the plugin root (the plugin source is
# the repository itself, see .claude-plugin/marketplace.json). "pack": a project
# registered with pack:gaie-factory (catalog/packs.json). "claude": a .claude
# directory written by scripts/gaie_bootstrap.py (user or project scope). The
# document paths of the installed layouts come from each record's installed_as.
LAYOUTS = {
    "hub": {"loader": "engineering_os/master_docs.py", "manifest": "governance/policies/master-prompts.json"},
    "pack": {"loader": ".engineering/gaie/master_docs.py", "manifest": ".engineering/gaie/master-prompts.json"},
    "claude": {"loader": "skills/gaie-master-router/engine/master_docs.py",
               "manifest": "skills/gaie-master-router/engine/master-prompts.json"},
}
INSTALLED_LAYOUTS = ("pack", "claude")
STATUSES = ("current", "drift", "missing", "link")
TOP_KEYS = ("schema_version", "policy_version", "implementation", "authority", "documents")
DOCUMENT_KEYS = ("path", "version", "sha256", "bytes", "installed_as", "history")
ENTRY_KEYS = ("version", "sha256", "date", "approved_by", "reference", "chain")
OPTIONAL_ENTRY_KEYS = ("same_bytes",)
NAME = re.compile(r"MASTER_[A-Z][A-Z0-9_]{0,40}")
VERSION = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")
DIGEST = re.compile(r"[0-9a-f]{64}")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class MasterDocsError(ValueError):
    """A MASTER document or its manifest cannot be trusted, or a pin was refused."""


# ---------------------------------------------------------------- parsing and validation

def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MasterDocsError(f"manifest has a duplicate key: {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise MasterDocsError(f"manifest has a non-standard number: {value}")


def _parse(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MasterDocsError("manifest is not UTF-8") from error
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except json.JSONDecodeError as error:
        raise MasterDocsError(f"manifest is not valid JSON: {error}") from error


def _relative(value, field):
    if (not isinstance(value, str) or not value or len(value) > 255 or "\\" in value or "\x00" in value
            or value.startswith("/") or any(part in ("", ".", "..") for part in value.split("/"))):
        raise MasterDocsError(f"{field}: a relative POSIX path without '.' or '..' is required")
    return value


def _label(value, field):
    if (not isinstance(value, str) or not value or len(value) > MAX_LABEL or value != value.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise MasterDocsError(f"{field}: 1-{MAX_LABEL} printable characters on one line are required")
    return value


def _version(value, field):
    match = VERSION.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise MasterDocsError(f"{field}: version X.Y.Z required, got {value!r}")
    return tuple(int(part) for part in match.groups())


def _digest(value, field):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise MasterDocsError(f"{field}: lowercase hexadecimal SHA-256 required")
    return value


def _date(value, field):
    if not isinstance(value, str) or not DATE.fullmatch(value):
        raise MasterDocsError(f"{field}: date YYYY-MM-DD required, got {value!r}")
    try:
        datetime.date.fromisoformat(value)
    except ValueError as error:
        raise MasterDocsError(f"{field}: {error}") from error
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def chain_digest(name, previous, entry):
    """Digest binding one history entry to the entry before it (or to the document name)."""
    body = {key: value for key, value in entry.items() if key != "chain"}
    seed = previous if previous is not None else f"gaie-master-docs:{name}"
    return hashlib.sha256(seed.encode("utf-8") + b"\n" + _canonical(body)).hexdigest()


def _exact(value, required, optional, field):
    if not isinstance(value, dict):
        raise MasterDocsError(f"{field}: object required")
    keys = set(value)
    if not set(required) <= keys or not keys <= set(required) | set(optional):
        raise MasterDocsError(f"{field}: fields must be {sorted(required)}"
                              + (f" plus optional {sorted(optional)}" if optional else ""))


def _history(name, record):
    history = record["history"]
    if not isinstance(history, list) or not history:
        raise MasterDocsError(f"{name}: history must be a non-empty list")
    previous = None
    for index, entry in enumerate(history):
        field = f"{name}.history[{index}]"
        _exact(entry, ENTRY_KEYS, OPTIONAL_ENTRY_KEYS, field)
        version = _version(entry["version"], f"{field}.version")
        _digest(entry["sha256"], f"{field}.sha256")
        _date(entry["date"], f"{field}.date")
        _label(entry["approved_by"], f"{field}.approved_by")
        _label(entry["reference"], f"{field}.reference")
        _digest(entry["chain"], f"{field}.chain")
        same = "same_bytes" in entry
        if same and entry["same_bytes"] is not True:
            raise MasterDocsError(f"{field}.same_bytes: only true is allowed")
        if previous is None:
            if same:
                raise MasterDocsError(f"{field}: the first entry cannot repeat earlier bytes")
        else:
            if version <= _version(previous["version"], "previous"):
                raise MasterDocsError(f"{field}: version {entry['version']} does not increase over "
                                      f"{previous['version']}; history was rewritten, not appended")
            if entry["date"] < previous["date"]:
                raise MasterDocsError(f"{field}: date {entry['date']} precedes {previous['date']}; "
                                      "history was rewritten, not appended")
            if (entry["sha256"] == previous["sha256"]) != same:
                raise MasterDocsError(f"{field}: same_bytes must be set exactly when the bytes repeat the previous entry")
        if entry["chain"] != chain_digest(name, previous["chain"] if previous else None, entry):
            raise MasterDocsError(f"{field}: chain digest mismatch; history was rewritten, not appended")
        previous = entry
    if (previous["version"], previous["sha256"]) != (record["version"], record["sha256"]):
        raise MasterDocsError(f"{name}: current version and sha256 differ from the last history entry")


def validate(manifest):
    """Raise MasterDocsError unless `manifest` is a well-formed manifest; return it."""
    _exact(manifest, TOP_KEYS, (), "manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != SCHEMA_VERSION:
        raise MasterDocsError(f"manifest schema_version must be {SCHEMA_VERSION}")
    _version(manifest["policy_version"], "policy_version")
    _relative(manifest["implementation"], "implementation")
    if not isinstance(manifest["authority"], str) or not manifest["authority"].strip():
        raise MasterDocsError("authority: non-empty text required")
    documents = manifest["documents"]
    if not isinstance(documents, dict) or not documents:
        raise MasterDocsError("documents: non-empty object required")
    claimed = {}
    for name, record in documents.items():
        if not NAME.fullmatch(name):
            raise MasterDocsError(f"document name {name!r} must look like MASTER_NAME")
        _exact(record, DOCUMENT_KEYS, (), name)
        _relative(record["path"], f"{name}.path")
        _exact(record["installed_as"], INSTALLED_LAYOUTS, (), f"{name}.installed_as")
        for layout in INSTALLED_LAYOUTS:
            _relative(record["installed_as"][layout], f"{name}.installed_as.{layout}")
        for layout, path in (("hub", record["path"]), *record["installed_as"].items()):
            other = claimed.setdefault((layout, path), name)
            if other != name:
                raise MasterDocsError(f"{name} and {other} claim the same {layout} path {path}")
        _version(record["version"], f"{name}.version")
        _digest(record["sha256"], f"{name}.sha256")
        if type(record["bytes"]) is not int or not 0 < record["bytes"] <= MAX_DOCUMENT_BYTES:
            raise MasterDocsError(f"{name}.bytes: integer 1-{MAX_DOCUMENT_BYTES} required")
        _history(name, record)
    return manifest


def assert_appended(previous, current):
    """Refuse `current` unless each history in `previous` is an unchanged prefix of it."""
    validate(previous)
    validate(current)
    for name, record in previous["documents"].items():
        if name not in current["documents"]:
            raise MasterDocsError(f"{name}: removed from the manifest; history was rewritten, not appended")
        old, new = record["history"], current["documents"][name]["history"]
        if new[:len(old)] != old:
            raise MasterDocsError(f"{name}: history was rewritten, not appended")
    return True


# ---------------------------------------------------------------- files

def _read(base, relative, limit):
    """(state, detail, bytes) of one file below `base`; never follows a symlink.

    state is "present", "missing" (absent or not a regular file), "link" or "large".
    """
    path = base
    info = None
    for part in relative.split("/"):
        path = path / part
        try:
            info = os.lstat(path)
        except (FileNotFoundError, NotADirectoryError):
            return "missing", f"{relative} not found", None
        if stat.S_ISLNK(info.st_mode):
            return "link", f"symlink refused: {path.relative_to(base).as_posix()}", None
    if not stat.S_ISREG(info.st_mode):
        return "missing", f"{relative} is not a regular file", None
    if info.st_size > limit:
        return "large", f"{relative} is larger than {limit} bytes", None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        return "missing", f"{relative} cannot be opened: {error.strerror}", None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            return "missing", f"{relative} changed while it was read", None
        chunks, remaining = [], limit + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(descriptor)
    data = b"".join(chunks)
    if len(data) > limit:
        return "large", f"{relative} is larger than {limit} bytes", None
    return "present", "", data


def _locate(root=None):
    """(layout, layout root, manifest path relative to it) for this call."""
    if root is None:
        for layout, spec in LAYOUTS.items():
            parts = pathlib.PurePosixPath(spec["loader"]).parent.parts
            if HERE.parts[-len(parts):] == parts:
                base = pathlib.Path(*HERE.parts[:-len(parts)])
                if os.path.lexists(base / spec["manifest"]):
                    return layout, base, spec["manifest"]
        raise MasterDocsError(f"no MASTER manifest found for the loader in {HERE}; pass a root directory")
    base = pathlib.Path(os.path.abspath(os.fspath(root)))
    for layout, directory in (*((name, base) for name in LAYOUTS), ("claude", base / ".claude")):
        if os.path.lexists(directory / LAYOUTS[layout]["manifest"]):
            return layout, directory, LAYOUTS[layout]["manifest"]
    raise MasterDocsError(f"no MASTER manifest under {base}: expected one of "
                          + ", ".join(spec["manifest"] for spec in LAYOUTS.values()))


def _manifest_at(base, relative):
    state, detail, data = _read(base, relative, MAX_MANIFEST_BYTES)
    if state != "present":
        raise MasterDocsError(f"manifest refused: {detail}")
    return validate(_parse(data))


def _document_path(layout, record):
    return record["path"] if layout == "hub" else record["installed_as"][layout]


def _check(base, layout, name, record):
    relative = _document_path(layout, record)
    state, detail, data = _read(base, relative, MAX_DOCUMENT_BYTES)
    row = {"name": name, "path": relative, "version": record["version"], "sha256": record["sha256"]}
    if state == "present":
        actual = hashlib.sha256(data).hexdigest()
        if actual == record["sha256"] and len(data) == record["bytes"]:
            state, detail = "current", ""
        else:
            state, detail = "drift", f"{len(data)} bytes with sha256 {actual} differ from the pinned {record['version']}"
            row["actual_sha256"] = actual
    elif state == "large":
        state = "drift"
    row["status"] = state
    if detail:
        row["detail"] = detail
    return row, data


def _name(name, manifest):
    if not isinstance(name, str) or not name.strip():
        raise MasterDocsError("a MASTER document name is required")
    key = name.strip().upper().replace("-", "_")
    if not key.startswith("MASTER_"):
        key = "MASTER_" + key
    if key not in manifest["documents"]:
        raise MasterDocsError(f"unknown MASTER document {name!r}; known: {', '.join(sorted(manifest['documents']))}")
    return key


# ---------------------------------------------------------------- public API

def load_manifest(root=None):
    """The validated manifest for `root` (default: the layout this file is installed in)."""
    _, base, relative = _locate(root)
    return _manifest_at(base, relative)


def verify(root=None):
    """Status of every MASTER document against the manifest.

    Returns {"ok", "layout", "root", "manifest", "policy_version", "documents": [{"name",
    "path", "version", "sha256", "status"}]} where status is current, drift, missing or
    link (a "detail" says why). Raises MasterDocsError when the manifest itself is
    missing, symlinked, malformed, has duplicate keys or a rewritten history.
    """
    layout, base, relative = _locate(root)
    manifest = _manifest_at(base, relative)
    documents = [_check(base, layout, name, record)[0] for name, record in sorted(manifest["documents"].items())]
    return {"ok": all(row["status"] == "current" for row in documents), "layout": layout, "root": str(base),
            "manifest": relative, "policy_version": manifest["policy_version"], "documents": documents}


def load(name, root=None):
    """(text, record) of one MASTER document whose bytes equal the manifest; else MasterDocsError."""
    layout, base, relative = _locate(root)
    manifest = _manifest_at(base, relative)
    key = _name(name, manifest)
    record = manifest["documents"][key]
    row, data = _check(base, layout, key, record)
    if row["status"] != "current":
        raise MasterDocsError(f"{key} is {row['status']} at {row['path']}: {row.get('detail', '')}".rstrip(": "))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MasterDocsError(f"{key} is not UTF-8 text") from error
    return text, {"name": key, "path": row["path"], "canonical_path": record["path"], "version": record["version"],
                  "sha256": record["sha256"], "bytes": record["bytes"], "layout": layout, "root": str(base),
                  "manifest": relative, "pinned": dict(record["history"][-1])}


def serialize(manifest):
    """The exact bytes `pin` writes: two-space JSON in field order, one trailing newline."""
    return (json.dumps(validate(manifest), indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _write(base, relative, data):
    state, detail, _ = _read(base, relative, MAX_MANIFEST_BYTES)
    if state != "present":
        raise MasterDocsError(f"manifest refused: {detail}")
    path = base / relative
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        if os.path.lexists(temporary):
            os.unlink(temporary)
        raise


def pin(version, approved_by, reference, names=None, root=None, date=None, allow_same_bytes=False, dry_run=False):
    """Append a history entry for each selected document and record its current bytes.

    Without `names`, every drifted document is pinned. The version must be greater
    than each selected document's pinned version, and identical bytes are refused
    unless `allow_same_bytes`. Only a hub checkout's manifest can be pinned.
    """
    layout, base, relative = _locate(root)
    if layout != "hub":
        raise MasterDocsError(f"pin changes only a hub checkout's manifest; this is a {layout} install, "
                              "which is verified, never pinned")
    manifest = _manifest_at(base, relative)
    target = _version(version, "version")
    _label(approved_by, "approved_by")
    _label(reference, "reference")
    date = _date(date if date is not None else datetime.datetime.now(datetime.timezone.utc).date().isoformat(), "date")
    rows = {name: _check(base, layout, name, record) for name, record in manifest["documents"].items()}
    broken = [row for row, _ in rows.values() if row["status"] in ("missing", "link")]
    if broken:
        raise MasterDocsError(f"cannot pin while {broken[0]['name']} is {broken[0]['status']}: {broken[0]['detail']}")
    if names:
        selected = sorted({_name(name, manifest) for name in names})
    else:
        selected = sorted(name for name, (row, _) in rows.items() if row["status"] == "drift")
        if not selected and not allow_same_bytes:
            raise MasterDocsError("nothing to pin: every document equals its pinned sha256 "
                                  "(pass --allow-same-bytes to re-pin identical bytes under a new version)")
        selected = selected or sorted(manifest["documents"])
    updated = json.loads(json.dumps(manifest))
    pinned = []
    for name in selected:
        record = updated["documents"][name]
        row, data = rows[name]
        if data is None:
            raise MasterDocsError(f"{name}: {row['detail']}")
        if target <= _version(record["version"], f"{name}.version"):
            raise MasterDocsError(f"{name}: version {version} must be greater than the pinned {record['version']}")
        digest = hashlib.sha256(data).hexdigest()
        same = digest == record["sha256"]
        if same and not allow_same_bytes:
            raise MasterDocsError(f"{name}: the bytes equal the pinned {record['version']}; "
                                  "pass --allow-same-bytes to re-pin them under a new version")
        last = record["history"][-1]
        if date < last["date"]:
            raise MasterDocsError(f"{name}: date {date} precedes the last pinned date {last['date']}")
        entry = {"version": version, "sha256": digest, "date": date, "approved_by": approved_by, "reference": reference}
        if same:
            entry["same_bytes"] = True
        entry["chain"] = chain_digest(name, last["chain"], entry)
        pinned.append({"name": name, "from": record["version"], "to": version, "sha256": digest, "bytes": len(data),
                       "same_bytes": same})
        record["history"].append(entry)
        record.update(version=version, sha256=digest, bytes=len(data))
    data = serialize(updated)
    assert_appended(manifest, updated)
    if not dry_run:
        _write(base, relative, data)
    return {"ok": True, "dry_run": bool(dry_run), "manifest": relative, "pinned": pinned}


# ---------------------------------------------------------------- command line

def _table(report):
    lines = [f"layout {report['layout']}  manifest {report['manifest']}  {'ok' if report['ok'] else 'NOT OK'}"]
    for row in report["documents"]:
        line = f"{row['name']:<16} {row['version']:<8} {row['status']:<8} {row['path']}  {row['sha256'][:16]}"
        lines.append(line + (f"  ({row['detail']})" if row.get("detail") else ""))
    return "\n".join(lines)


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="install root to check (default: the layout this file sits in)")
    common.add_argument("--json", action="store_true", help="print JSON")
    parser = argparse.ArgumentParser(prog="master_docs", description="Verify, show or pin the MASTER documents.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", parents=[common], help="compare every document with the manifest")
    show = commands.add_parser("show", parents=[common], help="print one document if its bytes are pinned")
    show.add_argument("name", help="MASTER_BUILD, MASTER_UPGRADE, build or upgrade")
    pin_parser = commands.add_parser("pin", parents=[common], help="record new bytes under a new version")
    pin_parser.add_argument("names", nargs="*", help="documents to pin (default: every drifted document)")
    pin_parser.add_argument("--version", required=True, help="new version X.Y.Z, greater than the pinned one")
    pin_parser.add_argument("--approved-by", required=True, help="approval label, for example 'owner'")
    pin_parser.add_argument("--reference", required=True, help="approval reference, for example 'PR #31'")
    pin_parser.add_argument("--date", help="approval date YYYY-MM-DD (default: today, UTC)")
    pin_parser.add_argument("--allow-same-bytes", action="store_true", help="allow a new version for identical bytes")
    pin_parser.add_argument("--dry-run", action="store_true", help="report the change without writing")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            report = verify(args.root)
            print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else _table(report))
            return 0 if report["ok"] else 1
        if args.command == "show":
            text, record = load(args.name, args.root)
            if args.json:
                print(json.dumps({"ok": True, "record": record, "text": text}, indent=2, ensure_ascii=False))
            else:
                sys.stdout.flush()
                sys.stdout.buffer.write(text.encode("utf-8"))
                sys.stdout.buffer.flush()
            return 0
        result = pin(args.version, args.approved_by, args.reference, args.names, args.root, args.date,
                     args.allow_same_bytes, args.dry_run)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            verb = "would pin" if result["dry_run"] else "pinned"
            for row in result["pinned"]:
                print(f"{verb} {row['name']} {row['from']} -> {row['to']} sha256 {row['sha256']} ({row['bytes']} bytes)")
        return 0
    except (MasterDocsError, OSError) as error:
        if args.json:
            print(json.dumps({"ok": False, "error": str(error)}, indent=2, ensure_ascii=False))
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
