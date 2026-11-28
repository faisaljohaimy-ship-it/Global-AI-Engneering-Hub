"""GAIE project registry: one resolver for public-safe names and private project records.

Public and committed: `projects/registry.json` (public repositories registered with
the hub) and `projects/aliases.json` (public-safe identifiers only: id, Arabic and
English names, aliases, repository status). Private and never committed:
`$GAIE_HOME/projects.json` (default `~/.gaie`, outside every Git repository),
created only by an explicit `register` call. It holds what must not be public:
repository identity and folder, approved hub revision, capability manifest,
project skills, authorized integrations, deployment and database targets, release
history and checkpoints.

Resolution is lexical on normalized Arabic/English (hamza and alef forms, alef
maqsura, taa marbuta, diacritics, tatweel, case). An unknown, ambiguous or merely
similar name returns `needs-clarification` with candidates; nothing is guessed.
Each project's private record is returned only for that project. A registry entry
is a claim from the owner, not proof that the repository is reachable here.
Standard library only. SPDX-License-Identifier: MIT.
"""
import argparse
import copy
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
import unicodedata

try:
    from . import gaie_memory as memory
    from . import gaie_router as router
except ImportError:  # vendored beside the router
    import gaie_memory as memory
    import gaie_router as router

PRIVATE_FILE = "projects.json"
SCHEMA_VERSION = 1
CATALOG_FIELDS = frozenset({"id", "names", "aliases", "repository_status", "observed", "note"})
CATALOG_STATUSES = ("public-registry", "unverified")
PRIVATE_FIELDS = ("id", "repository", "path", "aliases", "visibility", "approved_hub_revision", "capability_manifest",
                  "project_skills", "authorized_integrations", "deployment_target", "database_target",
                  "release_history", "checkpoints")
HISTORY_FIELDS = ("release_history", "checkpoints")
STATUSES = ("registered-public", "registered-private", "unverified")
MAX_PRIVATE_BYTES, MAX_PROJECTS, MAX_HISTORY = 1024 * 1024, 200, 500
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}){0,7}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_NAME = re.compile(r"[a-z0-9][a-z0-9:._-]{0,63}")
_KEY = re.compile(r"[a-z][a-z0-9_-]{0,39}")
_PUBLIC_LEAK = re.compile(r"://|github\.com|vercel\.app|@", re.I)


class RegistryError(router.RouteError):
    """The registry or a record is invalid, conflicting or unknown."""


def _need(condition, message):
    if not condition:
        raise RegistryError(message)


def normalize_name(text):
    """Canonical comparison form of a project name (Arabic letter variants folded)."""
    return " ".join(router.normalize(text))


def private_path(environ=None):
    """$GAIE_HOME/projects.json; GAIE_HOME must be outside every Git repository."""
    return router.gaie_home(environ) / PRIVATE_FILE


# --- validation -------------------------------------------------------------------------------

def _text(value, field, limit=200):
    _need(isinstance(value, str) and value.strip() and len(value) <= limit, f"{field}: text of 1-{limit} characters")
    value = unicodedata.normalize("NFKC", value)
    _need(not memory.SECRET.search(value) and not memory.SPLIT.search(re.sub(r"\s+", "", value)),
          f"{field}: looks like a credential; secrets never enter the registry")
    _need(not any(ord(c) < 32 or unicodedata.category(c) in ("Cf", "Zl", "Zp") for c in value), f"{field}: control characters")
    return value.strip()


def _names(value, field, limit=32):
    _need(isinstance(value, list) and len(value) <= limit, f"{field}: list of at most {limit}")
    items = [_text(item, field, 80) for item in value]
    _need(len(set(items)) == len(items), f"{field}: duplicates")
    return items


def _slugs(value, field):
    _need(isinstance(value, list) and len(value) <= 64, f"{field}: list of at most 64")
    for item in value:
        _need(isinstance(item, str) and _NAME.fullmatch(item), f"{field}: lowercase names ([a-z0-9:._-])")
    _need(len(set(value)) == len(value), f"{field}: duplicates")
    return list(value)


def _mapping(value, field):
    _need(isinstance(value, dict) and 0 < len(value) <= 12, f"{field}: object with 1-12 entries")
    result = {}
    for key, item in value.items():
        _need(isinstance(key, str) and _KEY.fullmatch(key), f"{field}: keys are lowercase identifiers")
        _need(isinstance(item, (str, int, bool)) and not isinstance(item, float), f"{field}.{key}: text, integer or boolean")
        result[key] = _text(item, f"{field}.{key}") if isinstance(item, str) else item
    return result


def _repository(value, field="repository"):
    _need(isinstance(value, str) and router.REPOSITORY.fullmatch(value), f"{field}: an https://github.com/owner/name URL")
    return value


def validate_private(row):
    """Return a normalized private record or raise RegistryError."""
    _need(isinstance(row, dict), "private project rows must be objects")
    unknown = set(row) - set(PRIVATE_FIELDS)
    _need(not unknown, f"private record: unknown field {sorted(unknown)[0] if unknown else ''!r}")
    key = row.get("id")
    _need(isinstance(key, str) and router.SLUG.fullmatch(key), "private project id must be a lowercase slug")
    record = {"id": key}
    if row.get("repository") is not None:
        record["repository"] = _repository(row["repository"])
    if row.get("path") is not None:
        _need(isinstance(row["path"], str) and _PATH.fullmatch(row["path"]),
              "path: relative folder inside the repository (no '..', no leading '/' or '.')")
        _need("repository" in record, "path needs the repository it belongs to")
        record["path"] = row["path"]
    record["aliases"] = _names(row.get("aliases", []), "private aliases")
    visibility = row.get("visibility", "private")
    _need(visibility in ("private", "public"), "private project visibility must be private or public")
    record["visibility"] = visibility
    if row.get("approved_hub_revision") is not None:
        _need(isinstance(row["approved_hub_revision"], str) and _REVISION.fullmatch(row["approved_hub_revision"]),
              "approved_hub_revision: a 40-character lowercase commit SHA")
        record["approved_hub_revision"] = row["approved_hub_revision"]
    if row.get("capability_manifest") is not None:
        _need(isinstance(row["capability_manifest"], str) and _PATH.fullmatch(row["capability_manifest"].lstrip("."))
              and ".." not in row["capability_manifest"], "capability_manifest: repository-relative path")
        record["capability_manifest"] = row["capability_manifest"]
    for field in ("project_skills", "authorized_integrations"):
        record[field] = _slugs(row.get(field, []), field)
    for field in ("deployment_target", "database_target"):
        if row.get(field) is not None:
            record[field] = _mapping(row[field], field)
    for field in HISTORY_FIELDS:
        entries = row.get(field, [])
        _need(isinstance(entries, list) and len(entries) <= MAX_HISTORY, f"{field}: list of at most {MAX_HISTORY}")
        record[field] = [_mapping(entry, field) for entry in entries]
    return record


def _validate_catalog_entry(entry):
    _need(isinstance(entry, dict) and set(entry) <= CATALOG_FIELDS and {"id", "names", "aliases", "repository_status"} <= set(entry),
          f"catalog entry fields must be within {sorted(CATALOG_FIELDS)}")
    _need(isinstance(entry["id"], str) and router.SLUG.fullmatch(entry["id"]), "catalog id must be a lowercase slug")
    names = entry["names"]
    _need(isinstance(names, dict) and set(names) == {"en", "ar"}, f"{entry['id']}: names need exactly en and ar")
    for lang in ("en", "ar"):
        _text(names[lang], f"{entry['id']}.names.{lang}", 80)
    _need(router._ARABIC.search(names["ar"]), f"{entry['id']}: the Arabic name must contain Arabic letters")
    _names(entry["aliases"], f"{entry['id']}.aliases")
    _need(entry["repository_status"] in CATALOG_STATUSES, f"{entry['id']}: repository_status in {CATALOG_STATUSES}")
    if "observed" in entry:
        observed = entry["observed"]
        _need(isinstance(observed, dict) and set(observed) == {"exists", "visibility", "date", "method"},
              f"{entry['id']}: observed needs exists, visibility, date, method")
        _need(observed["visibility"] == "public" and entry["repository_status"] == "public-registry",
              f"{entry['id']}: only public repositories are observed in the public catalog")
    # privacy guard: the committed catalog never carries a URL, host or account
    for value in _strings(entry):
        _need(not _PUBLIC_LEAK.search(value), f"{entry['id']}: the public catalog must not contain a URL, host or account")
    return entry


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


# --- loading ----------------------------------------------------------------------------------

def _public_sources():
    registry = router._load(router._first(router.HERE / "projects.json", router.ROOT / "projects/registry.json"))
    aliases = router._load(router._first(router.HERE / "aliases.json", router.ROOT / "projects/aliases.json"))
    _need(isinstance(registry.get("projects"), list), "projects/registry.json: projects list required")
    public = {}
    for row in registry["projects"]:
        _need(isinstance(row, dict) and isinstance(row.get("id"), str) and router.SLUG.fullmatch(row["id"]), "public project id")
        _need(row["id"] not in public, "public registry: duplicate id")
        public[row["id"]] = row
    legacy = aliases.get("aliases", {})
    catalog = aliases.get("catalog", [])
    _need(isinstance(legacy, dict) and isinstance(catalog, list), "aliases.json: aliases object and catalog list")
    return public, legacy, catalog


def _read_private(environ=None):
    path = private_path(environ)
    if path.is_symlink():
        raise RegistryError("private registry symlink refused")
    if not path.is_file():
        return []
    _need(path.stat().st_size <= MAX_PRIVATE_BYTES, "private registry exceeds its size bound")
    data = router._load(path)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION \
            or not isinstance(data.get("projects"), list):
        raise RegistryError("invalid private project registry")
    _need(len(data["projects"]) <= MAX_PROJECTS, "private registry: too many projects")
    rows = [validate_private(row) for row in data["projects"]]
    ids = [row["id"] for row in rows]
    _need(len(ids) == len(set(ids)), "private registry: duplicate id")
    return rows


def _record(key, **fields):
    base = {"id": key, "names": None, "aliases": [key], "private_aliases": [], "visibility": "public",
            "source": "public-registry", "repository": None, "path": None, "status": "unverified",
            "observed": None, "note": None, "private": None}
    base.update(fields)
    return base


def _build(public, legacy, catalog, private_rows):
    records = {}
    for key, row in public.items():
        records[key] = _record(key, repository=_repository(row.get("repository"), f"{key}.repository"),
                               visibility=row.get("visibility", "public"), status="registered-public")
    unknown = set(legacy) - set(records)
    _need(not unknown, f"alias for unregistered project: {sorted(unknown)[0] if unknown else ''}")
    for key, names in legacy.items():
        records[key]["aliases"] += _names(names, f"{key} aliases")
    seen = set()
    for entry in catalog:
        _validate_catalog_entry(entry)
        key = entry["id"]
        _need(key not in seen, f"catalog: duplicate id {key}")
        seen.add(key)
        if entry["repository_status"] == "public-registry":
            _need(key in records, f"catalog: {key} claims the public registry but is not listed there")
        else:
            _need(key not in records, f"catalog: {key} is in the public registry; its status must be public-registry")
            records[key] = _record(key, visibility="unknown", source="public-catalog")
        record = records[key]
        record.update(names=dict(entry["names"]), observed=entry.get("observed"), note=entry.get("note"))
        record["aliases"] += [entry["names"]["en"], entry["names"]["ar"], *entry["aliases"]]
    for row in private_rows:
        key = row["id"]
        record = records.get(key)
        if record is None:
            _need("repository" in row, f"private project {key}: repository required for a project unknown to the public catalog")
            record = records[key] = _record(key, visibility=row["visibility"], source="private-overlay",
                                            repository=row["repository"], path=row.get("path"), status="registered-private")
        elif record["status"] == "registered-public":
            _need(row.get("repository") in (None, record["repository"]) and "path" not in row,
                  f"private record for {key} conflicts with its public repository")
        elif "repository" in row:
            record.update(repository=row["repository"], path=row.get("path"), visibility=row["visibility"],
                          source="private-overlay", status="registered-private")
        record["private_aliases"] = list(row["aliases"])
        record["private"] = copy.deepcopy({k: v for k, v in row.items() if k != "id"})
    _check(records)
    return records


def _check(records):
    rules = router.policy()
    reserved = router._words([w for group in rules["verbs"].values() for w in group]) | router._words(rules["negations"]) \
        | router._words(rules["coordinators"]) | router._words(rules["clause_breaks"]) | router._words(rules["fillers"])
    keyed = []
    for record in records.values():
        names = [*record["aliases"], *record["private_aliases"]]
        record["_keys"] = sorted({tuple(router.normalize(a)) for a in names if router.normalize(a)})
        for key in record["_keys"]:
            if any(token in reserved or router._strip(token, router._ALIAS_PREFIX) in reserved for token in key):
                raise RegistryError("a project alias contains a command word; rename it")
        keyed += [(key, record["id"]) for key in record["_keys"]]
    for key, owner in keyed:
        for other, other_owner in keyed:
            if owner != other_owner and router._find(list(other), list(key), router._ALIAS_PREFIX):
                raise RegistryError("one project alias matches inside another project's alias; fix the registry before routing")
    places = {}
    for record in records.values():
        if record["repository"]:
            record["slug"] = router._slug_of(record["repository"])
            place = (record["slug"], record["path"] or "")
            _need(place not in places, "one repository (and folder) is registered under two projects")
            places[place] = record["id"]
        else:
            record["slug"] = None


def load(environ=None):
    """Every project record, public and private, keyed by id (internal: holds private data)."""
    public, legacy, catalog = _public_sources()
    return _build(public, legacy, catalog, _read_private(environ))


def routing_rows(environ=None, records=None):
    """Rows in the router's shape. Private details other than repository and folder stay out."""
    rows = {}
    for key, record in (load(environ) if records is None else records).items():
        rows[key] = {"id": key, "repository": record["repository"], "path": record["path"],
                     "visibility": record["visibility"], "source": record["source"], "slug": record["slug"],
                     "aliases": [*record["aliases"], *record["private_aliases"]], "_keys": record["_keys"],
                     "names": copy.deepcopy(record["names"]), "repository_check": repository_check(record),
                     "deployment_target_registered": bool((record["private"] or {}).get("deployment_target"))}
    return rows


# --- public API -------------------------------------------------------------------------------

def repository_check(record):
    """What the registry knows about the repository. Offline: never a reachability claim."""
    status = record["status"]
    evidence = {"registered-public": "listed in projects/registry.json",
                "registered-private": "registered by the owner in the private registry",
                "unverified": "no repository registered; it is never guessed"}[status]
    return {"status": status, "repository_known": record["repository"] is not None, "source": record["source"],
            "evidence": evidence, "observed": copy.deepcopy(record["observed"]),
            "reachability": "not checked by the registry; the executing agent verifies access in its environment"}


def public_view(record):
    return {"id": record["id"], "names": copy.deepcopy(record["names"]), "aliases": list(record["aliases"]),
            "visibility": record["visibility"], "repository_check": repository_check(record), "note": record["note"]}


def get(project_id, private=False, *, environ=None):
    """One project. `private=True` adds that project's own private record, and no other."""
    records = load(environ)
    _need(isinstance(project_id, str) and project_id in records, f"unknown project: {project_id!r}")
    record = records[project_id]
    view = public_view(record)
    if private:
        view["private"] = copy.deepcopy(record["private"]) if record["private"] is not None else None
    return view


def resolve(text, *, environ=None):
    """One project for a sentence, or needs-clarification with candidates."""
    if not isinstance(text, str) or not text.strip() or len(text) > router.MAX_TEXT:
        raise RegistryError("text must be 1-2000 characters")
    records = load(environ)
    matched, suggestions = router.resolve(router.normalize(text), routing_rows(environ, records))
    if len(matched) == 1:
        return {"status": "resolved", "project": public_view(records[matched[0]["id"]])}
    if matched:
        return {"status": "needs-clarification", "reason": "Several projects match; name exactly one.",
                "candidates": sorted(row["id"] for row in matched)}
    reason = "No registered project matches. Close names are candidates only, never selected." if suggestions else \
        "No registered project matches. Name the project or register it privately; nothing is guessed."
    return {"status": "needs-clarification", "reason": reason, "candidates": suggestions, "known_projects": sorted(records)}


def _write(path, rows):
    home = path.parent
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    _need(not home.is_symlink() and not path.is_symlink(), "private registry symlink refused")
    info = home.stat()  # another user must not be able to swap or delete the private registry
    _need(info.st_uid == os.getuid() and not info.st_mode & 0o022,
          "GAIE_HOME must belong to the current user and not be writable by group or others")
    payload = json.dumps({"schema_version": SCHEMA_VERSION, "projects": sorted(rows, key=lambda r: r["id"])},
                         ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _need(len(payload.encode("utf-8")) <= MAX_PRIVATE_BYTES, "private registry would exceed its size bound")
    descriptor, temporary = tempfile.mkstemp(prefix=".projects-", suffix=".json", dir=home)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def _sha(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _save(environ, rows, apply, project_id, done, planned):
    public, legacy, catalog = _public_sources()
    _build(public, legacy, catalog, rows)  # every conflict is refused before anything is written
    path = private_path(environ)
    record = next(row for row in rows if row["id"] == project_id)
    result = {"status": done if apply else planned, "project": project_id, "private_registry": str(path),
              "record_sha256": _sha(record)}
    if apply:
        _write(path, rows)
    return result


def register(project_id, *, environ=None, apply=False, replace=False, **fields):
    """Validate and store one project's private record (dry-run unless apply=True).

    fields: repository, path, aliases, visibility, approved_hub_revision,
    capability_manifest, project_skills, authorized_integrations, deployment_target,
    database_target, release_history, checkpoints.
    """
    record = validate_private({"id": project_id, **fields})
    rows = _read_private(environ)
    existing = [row for row in rows if row["id"] == project_id]
    _need(not existing or replace, f"{project_id} is already registered privately; pass replace=True to update it")
    rows = [row for row in rows if row["id"] != project_id] + [record]
    _need(len(rows) <= MAX_PROJECTS, "private registry: too many projects")
    return _save(environ, rows, apply, project_id, "registered", "would-register")


def append(project_id, field, entry, *, environ=None, apply=False):
    """Append one entry to a privately registered project's release history or checkpoints."""
    _need(field in HISTORY_FIELDS, f"field must be one of {HISTORY_FIELDS}")
    rows = _read_private(environ)
    target = next((row for row in rows if row["id"] == project_id), None)
    _need(target is not None, f"{project_id} has no private record; register it first")
    target = validate_private({**target, field: [*target[field], entry]})
    rows = [target if row["id"] == project_id else row for row in rows]
    return _save(environ, rows, apply, project_id, "appended", "would-append")


# --- CLI --------------------------------------------------------------------------------------

def _pairs(values, field):
    result = {}
    for value in values or []:
        key, sep, item = value.partition("=")
        _need(sep and key, f"{field}: use key=value")
        result[key] = item
    return result or None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="cmd", required=True)
    commands.add_parser("list")
    resolve_parser = commands.add_parser("resolve")
    resolve_parser.add_argument("text")
    get_parser = commands.add_parser("get")
    get_parser.add_argument("project")
    get_parser.add_argument("--private", action="store_true", help="include this project's private record")
    reg = commands.add_parser("register", help="dry-run unless --apply")
    reg.add_argument("project")
    reg.add_argument("--repository")
    reg.add_argument("--path")
    reg.add_argument("--alias", action="append", default=[])
    reg.add_argument("--visibility", default="private", choices=("private", "public"))
    reg.add_argument("--hub-revision", dest="approved_hub_revision")
    reg.add_argument("--manifest", dest="capability_manifest")
    reg.add_argument("--skill", action="append", default=[], dest="project_skills")
    reg.add_argument("--integration", action="append", default=[], dest="authorized_integrations")
    reg.add_argument("--deployment", action="append", metavar="KEY=VALUE")
    reg.add_argument("--database", action="append", metavar="KEY=VALUE")
    reg.add_argument("--replace", action="store_true")
    reg.add_argument("--apply", action="store_true")
    add = commands.add_parser("append", help="dry-run unless --apply")
    add.add_argument("project")
    add.add_argument("field", choices=HISTORY_FIELDS)
    add.add_argument("entry", nargs="+", metavar="KEY=VALUE")
    add.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "list":
            result = [public_view(record) for record in load().values()]
        elif args.cmd == "resolve":
            result = resolve(args.text)
        elif args.cmd == "get":
            result = get(args.project, private=args.private)
        elif args.cmd == "register":
            fields = {key: getattr(args, key) for key in ("repository", "path", "approved_hub_revision", "capability_manifest")
                      if getattr(args, key) is not None}
            fields.update(aliases=args.alias, visibility=args.visibility, project_skills=args.project_skills,
                          authorized_integrations=args.authorized_integrations)
            for field, values in (("deployment_target", args.deployment), ("database_target", args.database)):
                if values:
                    fields[field] = _pairs(values, field)
            result = register(args.project, apply=args.apply, replace=args.replace, **fields)
        else:
            result = append(args.project, args.field, _pairs(args.entry, args.field), apply=args.apply)
    except (router.RouteError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 2 if isinstance(result, dict) and result.get("status") == "needs-clarification" else 0


if __name__ == "__main__":
    sys.exit(main())
