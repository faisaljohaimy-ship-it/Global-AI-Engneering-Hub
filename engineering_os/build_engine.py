"""GAIE Master Build Engine (layer L16): build an independent application from gaie.spec/1.

`build(spec, out_dir=..., hub_revision=...)` validates a requirement specification
(with `engineering_os.requirements`, layer L15), refuses duplicates and unsafe targets,
renders `templates/app-stdlib` into an isolated workspace, initializes the application
as its own Git repository, runs the generated unit, API, acceptance and browser tests,
and writes factory receipts that `engineering_os.factory.evaluate_factory` revalidates.

Boundaries (see docs/specs/gaie-20-layers/BUILD_ENGINE.md):
- Deterministic code only; no model or provider is called and nothing leaves the
  machine. Generated tests use loopback sockets in child processes.
- The generated application never imports the hub; `.gaie/link.json` records which
  hub revision, templates and capabilities produced it.
- Creating or pushing to a remote repository is `external-write`: without an owner
  approval token the engine only writes `.gaie/repository-request.json`.
- Acceptance criteria become executable tests only when they match a form the
  generated interpreter implements; any other criterion is reported as unmapped and
  blocks the factory. Check reports come from this engine's own deterministic
  evaluators: evidence of executed checks, not an independent review.
"""

import argparse
import ast
import copy
import datetime
import hashlib
import html
import importlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

from . import contracts, factory
from .orchestration import SECRET, sha

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates" / "app-stdlib"
PLAYWRIGHT_POLICY = ROOT / "catalog" / "capabilities" / "playwright.json"
PLAYWRIGHT_LOCK = ROOT / "motion-library" / "verify" / "package-lock.json"
HUB_URL = "https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub"
SPEC_SCHEMA = "gaie.spec/1"
REPORT_SCHEMA = "gaie.build-report/1"
LOCALES = ("ar", "en")
DIRECTION = {"ar": "rtl", "en": "ltr"}
TARGETS = ["api", "backend", "database", "web"]
RESERVED_TABLES = frozenset({"schema_migrations", "app_account", "app_session"})
RESERVED_FIELDS = frozenset({"id", "created_at", "updated_at", "created_by"})
RESERVED_SEGMENTS = frozenset({"progress"})
MAX_SPEC_BYTES = 512 * 1024
MAX_TEXT = 10000
MAX_BODY_BYTES = 64 * 1024
PBKDF2_ITERATIONS = 600000
MISSING_ID = 999999999
SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
IDENT = re.compile(r"[a-z][a-z0-9_]{0,62}")
REVISION = re.compile(r"[a-f0-9]{40}")
MARKER = re.compile(r"@@([A-Z_]+)@@")
GITHUB_REMOTE = re.compile(r"https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?")
REVIEWER = "master-build-checks"
GIT_NAME = "GAIE Master Build Engine"
GIT_EMAIL = "master-build@gaie.invalid"
REQUEST_FILE = ".gaie/repository-request.json"
FACTORY_DIR = ".gaie/factory"

VALIDATION_CHECKS = ("required", "types", "max_length", "enum", "unknown_field", "defaults")
VALIDATION_GLOBAL = ("test_partial_update_merges_stored_values", "test_text_rejects_control_characters",
                     "test_dates_are_strict", "test_numbers_are_finite_and_not_booleans")
MIGRATION_TESTS = ("test_up_creates_schema", "test_down_removes_schema", "test_up_is_idempotent")
API_OPS = ("create", "list", "get", "update", "patch", "delete", "validation", "not_found")
API_GLOBAL = ("test_health", "test_unauthenticated_requests_refused", "test_role_check_on_every_endpoint",
              "test_csrf_token_required", "test_login_logout_cycle", "test_login_lockout",
              "test_passwords_are_salted_pbkdf2", "test_scoped_roles_see_only_their_records",
              "test_progress_uses_one_aggregate_query", "test_security_headers", "test_pages_follow_requested_locale",
              "test_cross_origin_write_refused", "test_wrong_content_type_refused", "test_oversized_body_refused",
              "test_invalid_json_refused", "test_unknown_collection_404", "test_method_not_allowed",
              "test_bad_query_refused", "test_pagination_limits", "test_sort_and_filters",
              "test_static_traversal_refused", "test_sql_injection_is_inert", "test_list_latency_budget",
              "test_seed_is_synthetic")
E2E_GLOBAL = ("e2e:login", "e2e:labels", "e2e:keyboard", "e2e:focus-indicator", "e2e:headers", "e2e:logout",
              "e2e:csp", "e2e:no-external-requests")
VALIDATION_ID = "tests.test_validation.ValidationTests."
MIGRATION_ID = "tests.test_migrations.MigrationTests."
API_ID = "tests.test_api.ApiTests."
ACCEPTANCE_ID = "tests.test_acceptance.AcceptanceTests."

# Forms of the acceptance grammar `METHOD /path [condition] returns NNN [and expectation]`
# that tests/test_acceptance.py implements (first match wins). Anything else is unmapped.
_W = r"[a-z][a-z0-9_]*"
CONDITIONS = (
    ("valid-body", rf"with a valid body"),
    ("without-session", rf"without a session"),
    ("without-field", rf"without (?P<field>{_W})"),
    ("field-value-while-linked", rf"with (?P<field>{_W})=(?P<value>\S+) while a linked (?P<child>[a-z][a-z0-9 _]*?) "
                                 rf"is not (?P<child_value>[a-z0-9_]+)"),
    ("field-value", rf"with (?P<field>{_W})=(?P<value>\S+)"),
    ("longer-than", rf"with (?P<field>{_W}) longer than (?P<n>\d+) characters"),
    ("missing-reference", rf"with an? (?P<field>{_W}) that does not exist"),
    ("unknown-id", r"with an unknown id"),
    ("duplicate", rf"with a duplicate (?P<field>{_W})"),
    ("as-role", r"as (?P<role>[a-z][a-z0-9_-]*)"),
    ("valid-credentials", r"with valid credentials"),
    ("wrong-password", r"with a wrong password"),
    ("reference-existing", rf"with (?P<field>{_W}) of an existing (?P<entity>[a-z][a-z0-9 _]*)"),
    ("link-existing", rf"with an existing (?P<field>{_W})"),
    ("link-duplicate", r"with an? (?P<target>[a-z][a-z0-9 _]*?) already in the (?P<source>[a-z][a-z0-9 _]*)"),
    ("parent-without-children", r"for an? (?P<parent>[a-z][a-z0-9 _]*?) without (?P<children>[a-z][a-z0-9 _]*)"),
)
EXPECTATIONS = (
    ("record", r"the (?:updated )?record"),
    ("lists-created", r"lists the created records"),
    ("only-assigned", rf"only (?P<items>{_W}) assigned to that (?P<target>{_W})"),
    ("only-overdue", rf"only (?P<items>{_W}) with (?P<date>{_W}) before today and (?P<field>{_W}) not (?P<value>[a-z0-9_]+)"),
    ("only-field-value", rf"only (?P<items>{_W}) with (?P<field>{_W}) (?P<value>[a-z0-9_]+)"),
    ("ordered-nulls-last", rf"(?P<items>{_W}) ordered by (?P<field>{_W}) ascending with empty .+ last"),
    ("only-children", rf"only that (?P<parent>{_W})'s (?P<children>{_W})(?: ordered by (?P<order>{_W}))?"),
    ("progress", rf"total_(?P<items>{_W}), done_(?P=items) and percent equal to done_(?P=items) \* 100 / "
                 rf"total_(?P=items) rounded down"),
    ("percent-zero", r"percent 0"),
    ("membership", r"the membership"),
    ("session-cookie", r"a session cookie"),
    ("session-revoked", r"the session is no longer accepted"),
    ("html-dir-lang", r"html with dir=(?P<dir>rtl|ltr) and lang=(?P<lang>[a-z]{2})"),
    ("html-labels", r"html where every form input has a label"),
)
_CONDITIONS = [(key, re.compile(pattern)) for key, pattern in CONDITIONS]
_EXPECTATIONS = [(key, re.compile(pattern)) for key, pattern in EXPECTATIONS]
GRAMMAR = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) (/\S*)(?: (.+?))? returns ([1-5][0-9]{2})(?: and (.+))?$")


class BuildError(ValueError):
    """The build was refused or could not complete; nothing unsafe was attempted."""


class SpecError(BuildError):
    """The specification does not satisfy gaie.spec/1."""


class UnsupportedSpec(SpecError):
    """A valid specification asks for something the app-stdlib template cannot build."""


class OpenQuestions(SpecError):
    """The specification still has open questions; ask the owner before building."""


class WorkspaceError(BuildError):
    """The output directory is outside the allowed workspace or not empty."""


class DuplicateProject(BuildError):
    """A project or repository with this identity already exists; route to MASTER_UPGRADE."""

    def __init__(self, message, matches):
        super().__init__(message)
        self.matches = matches


class ApprovalRequired(BuildError):
    """An external-write step was attempted without a valid owner approval."""


# ---------------------------------------------------------------------------
# small helpers

def _need(condition, message, error=SpecError):
    if not condition:
        raise error(message)


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _now(now):
    if now is None:
        moment = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    elif isinstance(now, datetime.datetime):
        _need(now.tzinfo is not None, "now must be timezone-aware", BuildError)
        moment = now.astimezone(datetime.timezone.utc).replace(microsecond=0)
    elif isinstance(now, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", now):
        moment = datetime.datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    else:
        raise BuildError("now must be a timezone-aware datetime or YYYY-MM-DDTHH:MM:SSZ")
    return moment


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _plural(word):
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", word):
        return word + "es"
    return word + "s"


def _humanize(name):
    words = _snake(name).replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def _strings(value, path=""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


# ---------------------------------------------------------------------------
# gaie.spec/1: validated by the L15 requirements engine, then checked for buildability

def _requirements():
    from . import requirements
    return requirements


def validate_spec(spec, *, allow_open_questions=False):
    """Validate with engineering_os.requirements, then refuse what app-stdlib cannot build.

    Returns a deep copy. Raises SpecError (invalid), OpenQuestions (not ready) or
    UnsupportedSpec (valid, but outside what this template generates).
    """
    _need(isinstance(spec, dict), "spec: JSON object required")
    try:
        size = len(contracts.canonical(spec).encode("utf-8"))
    except (TypeError, ValueError):
        raise SpecError("spec: must be plain JSON") from None
    _need(size <= MAX_SPEC_BYTES, f"spec: larger than {MAX_SPEC_BYTES} bytes")
    for path, text in _strings(spec):
        _need(not SECRET.search(text), f"{path}: credential-shaped text refused")
        if path != "source.command":
            _need(not any(ord(char) < 32 or ord(char) == 127 for char in text), f"{path}: control characters refused")
    requirements = _requirements()
    try:
        report = requirements.validate_spec(spec)
    except requirements.SpecError as error:
        problems = getattr(error, "errors", None) or [str(error)]
        raise SpecError("; ".join(problems[:20])) from None
    if not report["ready"]:
        if not allow_open_questions:
            raise OpenQuestions(f"spec has open questions {report['open_questions']}; ask the owner "
                                "(requirements.refine) before building")
        return copy.deepcopy(spec)
    _supported(spec)
    return copy.deepcopy(spec)


def _supported(spec):
    unsupported = lambda condition, message: _need(condition, message, UnsupportedSpec)  # noqa: E731
    unsupported(spec["product_type"] == "web-app",
                f"product_type {spec['product_type']!r} is not built by templates/app-stdlib (web-app only)")
    unsupported(not spec["ai"]["needed"] and not spec["ai"]["use_cases"],
                "AI features need an AI target, an evaluation set and owner approval; app-stdlib builds none")
    unsupported(not spec["integrations"], "external integrations are not built by app-stdlib")
    constraints = spec["constraints"]
    unsupported(constraints["runtime"] == "python3-stdlib" and constraints["database"] == "sqlite",
                "app-stdlib builds runtime python3-stdlib with database sqlite only")
    _need(constraints["no_paid_services"] is True, "constraints.no_paid_services must be true: paid services need "
                                                   "separate owner approval")
    unsupported(any("*" in role["permissions"] for role in spec["roles"]),
                "the generated application needs one administrator role with permission '*'")
    _need(len(spec["features"]) <= 80, "spec.features: at most 80 (the factory traces at most 100 requirements)")
    seen = set()
    for feature in spec["features"]:
        key = feature["id"].lower()
        _need(key not in seen and not key.startswith("nfr"), f"feature id {feature['id']!r} collides (case-insensitive or nfr-)")
        seen.add(key)
    for entity in spec["entities"]:
        table = _snake(entity["name"])
        unsupported(len(table) <= 40 and table not in RESERVED_TABLES and not table.startswith("sqlite_"),
                    f"{entity['name']}: reserved or too long table name")
        for field in entity["fields"]:
            unsupported(field["name"] not in RESERVED_FIELDS, f"{entity['name']}.{field['name']}: reserved field name")
    for relation in spec["relations"]:
        if relation["kind"] == "many-to-many":
            unsupported(not relation["required"], "a required many-to-many relation is not supported")
            unsupported(relation["from"] != relation["to"], "a many-to-many relation of an entity to itself is not supported")
        else:
            child = relation["from"] if relation["kind"] == "many-to-one" else relation["to"]
            parent = relation["to"] if relation["kind"] == "many-to-one" else relation["from"]
            _need(not (child == parent and relation["required"]),
                  f"a required self-relation on {child} can never be satisfied")


# ---------------------------------------------------------------------------
# entity model derived from the specification

def _load_template_data(name):
    return json.loads((TEMPLATE_DIR / name).read_text(encoding="utf-8"))


def _topological(entities, edges_all, edges_required):
    order = [entity["name"] for entity in entities]
    for edges in (edges_all, edges_required):
        pending = {name: {parent for child, parent in edges if child == name and parent != name} for name in order}
        result = []
        while pending:
            ready = [name for name in order if name in pending and not pending[name]]
            if not ready:
                break
            result.append(ready[0])
            del pending[ready[0]]
            for deps in pending.values():
                deps.discard(ready[0])
        if not pending:
            return result
    raise SpecError("spec.relations: required many-to-one relations form a cycle; no record could ever be created")


def _entity_labels(entity, known, lang, gaps):
    label = entity.get("label")
    if isinstance(label, dict) and isinstance(label.get(lang), list):
        return {"singular": label[lang][0], "plural": label[lang][1]}
    singular = label[lang] if isinstance(label, dict) else None
    if known and (singular is None or known[lang][0] == singular):
        return {"singular": known[lang][0], "plural": known[lang][1]}
    if singular is None:
        singular = _humanize(entity["name"])
        gaps.append(f"entity {entity['name']}")
    if lang == "en":
        return {"singular": singular, "plural": _plural(singular)}
    gaps.append(f"plural {entity['name']}")
    return {"singular": singular, "plural": singular}


def _nfr_numbers(spec):
    numbers = {"p95_ms": 200, "latency_records": 1000, "page_size": 50, "max_page_size": 200}
    for text in spec["nfr"].get("performance", []):
        match = re.search(r"p95[^0-9<]*<\s*(\d{1,5})\s*ms", text, re.I)
        if match:
            numbers["p95_ms"] = int(match.group(1))
        match = re.search(r"with\s+([\d,]{1,9})\s+records", text, re.I)
        if match:
            numbers["latency_records"] = min(int(match.group(1).replace(",", "")), 100000)
        match = re.search(r"default\s+(\d{1,4}),?\s*max\s+(\d{1,4})", text, re.I)
        if match and 1 <= int(match.group(1)) <= int(match.group(2)) <= 1000:
            numbers["page_size"], numbers["max_page_size"] = int(match.group(1)), int(match.group(2))
    return numbers


def derive_model(spec):
    """Tables, collections, references, links, labels, auth and ordering for the application."""
    glossary = _load_template_data("glossary.json")
    entities = spec["entities"]
    by_name = {entity["name"]: entity for entity in entities}
    references, links = {name: [] for name in by_name}, {name: [] for name in by_name}
    edges_all, edges_required = [], []
    for relation in spec["relations"]:
        if relation["kind"] == "many-to-many":
            source, target = relation["from"], relation["to"]
            attr = relation.get("field") or _snake(by_name[target].get("plural", _plural(_snake(target)))).replace("-", "_")
            links[source].append({"segment": attr.replace("_", "-"), "field": attr, "entity": target,
                                  "table": _snake(target), "link_table": f"{_snake(source)}_{attr}_link",
                                  "source_key": _snake(source) + "_id", "target_key": _snake(target) + "_id"})
            continue
        if relation["kind"] == "many-to-one":
            child, parent = relation["from"], relation["to"]
            attr = relation.get("field") or _snake(parent)
        else:
            child, parent = relation["to"], relation["from"]
            attr = relation.get("field") or _snake(parent)
        references[child].append({"field": attr + "_id", "attr": attr, "entity": parent, "table": _snake(parent),
                                  "required": relation["required"], "relation": "many-to-one"})
        edges_all.append((child, parent))
        if relation["required"]:
            edges_required.append((child, parent))
    order = _topological(entities, edges_all, edges_required)
    gaps, tables = [], set()
    labels = {lang: {"entities": {}, "fields": {}, "values": {}} for lang in LOCALES}
    model_entities = []
    for name in order:
        entity = by_name[name]
        table = _snake(name)
        collection = entity.get("plural") or _plural(table).replace("_", "-")
        fields = [{key: value for key, value in field.items() if key != "label"} for field in entity["fields"]]
        names = {field["name"] for field in fields}
        for ref in references[name]:
            _need(ref["field"] not in names, f"{name}.{ref['field']}: relation column collides with a field")
            names.add(ref["field"])
        text_fields = [field for field in fields if field["type"] == "text"]
        required_text = [field for field in text_fields if field["required"]]
        label_field = (required_text or text_fields or [None])[0]
        due = [f["name"] for f in fields if f["name"] == "due_date" and f["type"] == "date"]
        model_entities.append({"name": name, "table": table, "collection": collection,
                               "label_field": label_field["name"] if label_field else None,
                               "fields": fields, "references": references[name], "links": links[name],
                               "default_order": due})
        tables.add(table)
        tables.update(link["link_table"] for link in links[name])
        for lang in LOCALES:
            labels[lang]["entities"][name] = _entity_labels(entity, glossary["entities"].get(table), lang, gaps)
    _need(len(tables) == len(model_entities) + sum(len(e["links"]) for e in model_entities)
          and not tables & RESERVED_TABLES, "spec: table names collide", UnsupportedSpec)
    _need(len({e["collection"] for e in model_entities}) == len(model_entities), "spec: duplicate collections",
          UnsupportedSpec)
    for item in model_entities:
        for table_name in [item["table"]] + [link["link_table"] for link in item["links"]]:
            _need(IDENT.fullmatch(table_name), f"identifier too long: {table_name}", UnsupportedSpec)
    by_model = {e["name"]: e for e in model_entities}
    for item in model_entities:
        item["children"] = []
    for item in model_entities:
        for ref in item["references"]:
            if sum(1 for other in item["references"] if other["entity"] == ref["entity"]) == 1:
                by_model[ref["entity"]]["children"].append({"collection": item["collection"], "entity": item["name"],
                                                            "field": ref["field"]})
    for item in model_entities:
        segments = [link["segment"] for link in item["links"]]
        children = [child["collection"] for child in item["children"]]
        _need(len(set(segments)) == len(segments) and not set(segments) & (set(children) | RESERVED_SEGMENTS),
              f"{item['name']}: link path collides with a child collection or 'progress'", UnsupportedSpec)
        item["children"] = [child for child in item["children"] if child["collection"] not in RESERVED_SEGMENTS]
        entity = by_name[item["name"]]
        for lang in LOCALES:
            names, values = {}, {}
            for field in entity["fields"]:
                if "label" in field:
                    text = field["label"][lang]
                elif field["name"] in glossary["fields"]:
                    text = glossary["fields"][field["name"]][lang]
                else:
                    text = _humanize(field["name"])
                    if lang == "ar":
                        gaps.append(f"field {item['name']}.{field['name']}")
                names[field["name"]] = text
                if field["type"] == "enum":
                    shown = {}
                    for value in field["values"]:
                        known = glossary["values"].get(value)
                        shown[value] = known[lang] if known else _humanize(value)
                        if not known and lang == "ar":
                            gaps.append(f"value {item['name']}.{field['name']}={value}")
                    values[field["name"]] = shown
            for ref in item["references"]:
                if ref["attr"] == _snake(ref["entity"]):
                    names[ref["field"]] = labels[lang]["entities"][ref["entity"]]["singular"]
                elif ref["attr"] in glossary["fields"]:
                    names[ref["field"]] = glossary["fields"][ref["attr"]][lang]
                else:
                    names[ref["field"]] = _humanize(ref["attr"])
                    if lang == "ar":
                        gaps.append(f"field {item['name']}.{ref['field']}")
            _need(len(set(names.values())) == len(names),
                  f"{item['name']}: two fields have the same {lang} label; add explicit labels", UnsupportedSpec)
            labels[lang]["fields"][item["name"]] = names
            labels[lang]["values"][item["name"]] = values
    roles = {role["id"]: list(role["permissions"]) for role in spec["roles"]}
    admin = next(role["id"] for role in spec["roles"] if "*" in role["permissions"])
    principal = None
    for item in model_entities:
        email = next((f for f in item["fields"] if f["type"] == "email" and f.get("unique") and f["required"]), None)
        if email is not None:
            principal = {"entity": item["name"], "email_field": email["name"]}
            break
    model = {"entities": model_entities, "labels": labels, "translation_gaps": sorted(set(gaps)),
             "auth": {"roles": roles, "admin_role": admin, "principal": principal, "scoping": None,
                      "pbkdf2_iterations": PBKDF2_ITERATIONS, "session_hours": 12},
             "rules": {"progress": [], "overdue": [], "completion": []}, "nfr": _nfr_numbers(spec)}
    model["auth"]["scoping"] = _scoping(spec, model)
    return model


def _entity_by_word(model, word):
    """An entity named by a word of a criterion: name, table, collection or English label."""
    word = (word or "").strip().casefold().replace(" ", "_")
    for entity in model["entities"]:
        label = model["labels"]["en"]["entities"][entity["name"]]
        forms = {entity["name"].casefold(), entity["table"], entity["collection"].replace("-", "_"),
                 _plural(entity["table"]), label["singular"].casefold().replace(" ", "_"),
                 label["plural"].casefold().replace(" ", "_")}
        if word in forms:
            return entity
    return None


def _scoping(spec, model):
    """Row scoping when the specification says users see only records they belong to."""
    principal = model["auth"]["principal"]
    if principal is None:
        return None
    texts = list(spec["nfr"].get("security", [])) + [t for f in spec["features"] for t in f["acceptance"]]
    for text in texts:
        match = re.search(r"\bsee only (?P<what>[a-z_ ]+?) they belong to\b", text, re.I)
        if not match:
            continue
        entity = _entity_by_word(model, match.group("what"))
        if entity is None:
            continue
        link = next((l for l in entity["links"] if l["entity"] == principal["entity"]), None)
        if link is not None:
            return {"entity": entity["name"], "link_table": link["link_table"], "statement": text}
    return None


# ---------------------------------------------------------------------------
# acceptance criteria -> executable checks for tests/test_acceptance.py

def _typed(field, value):
    if field is None:
        return value
    if field["type"] == "int" and re.fullmatch(r"-?\d{1,15}", value):
        return int(value)
    if field["type"] == "number" and re.fullmatch(r"-?\d{1,15}(?:\.\d{1,9})?", value):
        return float(value)
    if field["type"] == "bool" and value in ("true", "false"):
        return value == "true"
    return value


def _route(model, locales, method, path, query):
    """Route kind and targets for an API path in the criterion, or None (unsupported)."""
    if path == "/":
        return {"kind": "page"} if method == "GET" else None
    if path == "/api/login":
        return {"kind": "login"} if method == "POST" else None
    if path == "/api/logout":
        return {"kind": "logout"} if method == "POST" else None
    parts = path.split("/")
    if len(parts) < 3 or parts[1] != "api":
        return None
    entity = next((e for e in model["entities"] if e["collection"] == parts[2]), None)
    if entity is None:
        return None
    base = "/".join(parts[:3])
    if len(parts) == 3:
        return {"kind": "collection", "entity": entity["name"], "base": base} if method in ("GET", "POST") else None
    if parts[3] != "{id}":
        return None
    if len(parts) == 4:
        return {"kind": "item", "entity": entity["name"], "base": base} if method in ("GET", "PUT", "PATCH", "DELETE") else None
    if len(parts) != 5:
        return None
    segment = parts[4]
    link = next((l for l in entity["links"] if l["segment"] == segment), None)
    if link is not None:
        return {"kind": "link", "entity": entity["name"], "link": link} if method == "POST" else None
    if segment == "progress" and method == "GET":
        return {"kind": "progress", "entity": entity["name"]}
    child = next((c for c in entity["children"] if c["collection"] == segment), None)
    if child is not None and method == "GET":
        return {"kind": "children", "entity": entity["name"], "child": child["entity"], "fk": child["field"]}
    return None


def _columns(entity):
    fields = {field["name"]: field for field in entity["fields"]}
    refs = {ref["field"]: ref for ref in entity["references"]}
    return fields, refs


def _resolve(model, locales, roles, check):
    """Return (route, condition groups, expectation groups) or raise KeyError(reason)."""
    method, path, query = check["method"], check["path"], check["query"]
    route = _route(model, locales, method, path, query)
    if route is None:
        raise KeyError(f"route {method} {path} is not generated")
    kind = route["kind"]
    entity = next((e for e in model["entities"] if e["name"] == route.get("entity")), None)
    fields, refs = _columns(entity) if entity else ({}, {})
    cond, cg = check["condition_id"], dict(check["condition"])
    exp, eg = check["expect_id"], dict(check["expect"])
    need = lambda ok, why: None if ok else (_ for _ in ()).throw(KeyError(why))  # noqa: E731
    if cond == "valid-body":
        need((kind == "collection" and method == "POST") or (kind == "item" and method in ("PUT", "PATCH")), "valid body")
    elif cond == "without-session":
        need(kind not in ("page", "login"), "session")
    elif cond == "without-field":
        need(kind == "collection" and method == "POST" and (cg["field"] in fields or cg["field"] in refs), "field")
    elif cond in ("field-value", "field-value-while-linked"):
        need(kind in ("collection", "item") and method in ("POST", "PUT", "PATCH") and cg["field"] in fields, "field")
        cg["value"] = _typed(fields[cg["field"]], cg["value"])
        if cond == "field-value-while-linked":
            child = _entity_by_word(model, cg["child"])
            need(child is not None and method in ("PUT", "PATCH"), "linked child")
            fk = [r for r in child["references"] if r["entity"] == entity["name"]]
            enum = [f for f in child["fields"] if f["type"] == "enum" and cg["child_value"] in f["values"]]
            need(len(fk) == 1 and enum and len(enum[0]["values"]) > 1, "linked child relation")
            cg.update(child=child["name"], fk=fk[0]["field"], child_field=enum[0]["name"])
            rule = {"entity": entity["name"], "field": cg["field"], "value": cg["value"], "child": child["name"],
                    "fk": fk[0]["field"], "child_field": enum[0]["name"], "child_value": cg["child_value"]}
            if rule not in model["rules"]["completion"]:
                model["rules"]["completion"].append(rule)
    elif cond == "longer-than":
        need(cg["field"] in fields and fields[cg["field"]]["type"] in ("text", "email") and method in ("POST", "PUT", "PATCH"),
             "text field")
    elif cond == "missing-reference":
        need(cg["field"] in refs and method in ("POST", "PUT", "PATCH"), "reference")
    elif cond == "unknown-id":
        need(kind == "item", "item")
    elif cond == "duplicate":
        need(kind == "collection" and method == "POST" and fields.get(cg["field"], {}).get("unique"), "unique field")
    elif cond == "as-role":
        need(cg["role"] in roles and kind in ("collection", "item"), "role")
    elif cond in ("valid-credentials", "wrong-password"):
        need(kind == "login", "login")
    elif cond == "reference-existing":
        target = _entity_by_word(model, cg["entity"])
        need(cg["field"] in refs and target is not None and refs[cg["field"]]["entity"] == target["name"]
             and method in ("POST", "PUT", "PATCH"), "reference target")
        cg["entity"] = target["name"]
    elif cond in ("link-existing", "link-duplicate"):
        need(kind == "link" and (cond == "link-duplicate" or cg["field"] == route["link"]["target_key"]), "link")
    elif cond == "parent-without-children":
        need(kind == "progress", "progress")
    elif cond is not None:
        raise KeyError(f"condition {cond}")
    if exp == "record":
        need(method in ("POST", "PUT", "PATCH") and kind in ("collection", "item"), "record")
    elif exp == "lists-created":
        need(kind == "collection" and method == "GET" and not query, "list")
    elif exp == "only-field-value":
        field = fields.get(eg["field"])
        need(kind == "collection" and field is not None and field["type"] == "enum" and eg["value"] in field["values"]
             and query == f"{eg['field']}={eg['value']}" and len(field["values"]) > 1, "enum filter")
    elif exp == "only-assigned":
        match = re.fullmatch(r"(?P<fk>[a-z_]+)=\{(?P<placeholder>[a-z_]+)\}", query)
        target = _entity_by_word(model, eg["target"])
        need(kind == "collection" and match and match.group("fk") in refs and target is not None
             and refs[match.group("fk")]["entity"] == target["name"], "reference filter")
        eg.update(fk=match.group("fk"), placeholder=match.group("placeholder"), target=target["name"])
    elif exp == "only-overdue":
        field = fields.get(eg["field"])
        need(kind == "collection" and query == "overdue=true" and fields.get(eg["date"], {}).get("type") == "date"
             and not fields[eg["date"]]["required"] and field is not None and field["type"] == "enum"
             and eg["value"] in field["values"] and len(field["values"]) > 1, "overdue")
        rule = {"entity": entity["name"], "date": eg["date"], "field": eg["field"], "value": eg["value"]}
        if rule not in model["rules"]["overdue"]:
            model["rules"]["overdue"].append(rule)
    elif exp == "ordered-nulls-last":
        need(kind == "collection" and query == f"sort={eg['field']}" and eg["field"] in fields
             and not fields[eg["field"]]["required"], "sort")
    elif exp == "only-children":
        child = next(e for e in model["entities"] if e["name"] == route["child"]) if kind == "children" else None
        need(child is not None and _entity_by_word(model, eg["parent"]) is entity
             and _entity_by_word(model, eg["children"]) is child, "children")
        if eg.get("order"):
            need(child["default_order"][:1] == [eg["order"]], "children order")
    elif exp in ("progress", "percent-zero"):
        need(kind == "progress", "progress")
        if exp == "progress":
            child = _entity_by_word(model, eg["items"])
            fk = [r for r in (child or {}).get("references", []) if r["entity"] == entity["name"]]
            enum = [f for f in (child or {}).get("fields", []) if f["type"] == "enum" and "done" in f["values"]]
            need(child is not None and len(fk) == 1 and enum and len(enum[0]["values"]) > 1, "progress child")
            rule = {"parent": entity["name"], "child": child["name"], "fk": fk[0]["field"], "field": enum[0]["name"],
                    "done": ["done"], "key": eg["items"]}
            if rule not in model["rules"]["progress"]:
                model["rules"]["progress"].append(rule)
    elif exp == "membership":
        need(kind == "link", "membership")
    elif exp == "session-cookie":
        need(kind == "login", "login")
    elif exp == "session-revoked":
        need(kind == "logout", "logout")
    elif exp == "html-dir-lang":
        need(kind == "page" and query == f"lang={eg['lang']}" and eg["lang"] in locales
             and DIRECTION[eg["lang"]] == eg["dir"], "page locale")
    elif exp == "html-labels":
        need(kind == "page", "page")
    elif exp is not None:
        raise KeyError(f"expectation {exp}")
    return route, cg, eg


def _match(table, text):
    if text is None:
        return None, {}
    for key, pattern in table:
        found = pattern.fullmatch(text.strip())
        if found:
            return key, {k: v for k, v in found.groupdict().items() if v is not None}
    raise KeyError(f"no implemented form matches {text!r}")


def compile_acceptance(spec, model):
    """Executable checks for every supported criterion and the reason for each unsupported one.

    Also derives the state rules (progress, overdue, completion) that the criteria require;
    they are added to model["rules"] so the generated server implements exactly them.
    """
    locales, roles = spec["locales"], {role["id"] for role in spec["roles"]}
    staged, checks, unmapped = [], [], {}
    for feature in spec["features"]:
        for index, criterion in enumerate(feature["acceptance"]):
            aid = f"{feature['id'].lower()}-a{index + 1}"
            parsed = GRAMMAR.match(criterion)
            if parsed is None:
                unmapped[aid] = "not in the acceptance grammar"
                continue
            method, full, condition, status, expect = parsed.groups()
            path, _, query = full.partition("?")
            try:
                cond_id, cond = _match(_CONDITIONS, condition)
                exp_id, exp = _match(_EXPECTATIONS, expect)
            except KeyError as error:
                unmapped[aid] = str(error.args[0])
                continue
            staged.append((aid, feature, index, {"criterion": criterion, "method": method, "path": full, "query": query,
                                                 "status": int(status), "condition_id": cond_id, "condition": cond,
                                                 "expect_id": exp_id, "expect": exp}, path))
    # progress/overdue rules come from their own criteria, so resolve those first.
    staged.sort(key=lambda row: row[3]["expect_id"] not in ("progress", "only-overdue"))
    for aid, feature, index, check, path in staged:
        try:
            route, cond, exp = _resolve(model, locales, roles, {**check, "path": path})
        except KeyError as error:
            unmapped[aid] = str(error.args[0])
            continue
        if route["kind"] == "progress":
            rule = next((r for r in model["rules"]["progress"] if r["parent"] == route["entity"]), None)
            if rule is None:
                unmapped[aid] = "no progress rule is defined for this entity"
                continue
            route = {**route, "rule": rule}
        test = f"test_{re.sub(r'[^a-z0-9]+', '_', feature['id'].lower())}_{index}"
        checks.append({"test": test, "acceptance_id": aid, "feature": feature["id"], "index": index, **check,
                       "condition": cond, "expect": exp, "route": route})
    position = {(f["id"], i): n for n, (f, i) in enumerate((f, i) for f in spec["features"] for i in range(len(f["acceptance"])))}
    checks.sort(key=lambda row: position[(row["feature"], row["index"])])
    return checks, unmapped


# ---------------------------------------------------------------------------
# requirements, test catalog and acceptance coverage

def expected_tests(model, locales, checks):
    """Test ids the generated suites must report (python unittest ids and E2E case ids)."""
    python, e2e = [], []
    for entity in model["entities"]:
        table = entity["table"]
        python += [f"{VALIDATION_ID}test_{check}_{table}" for check in VALIDATION_CHECKS]
        python += [f"{API_ID}test_{op}_{table}" for op in API_OPS]
        for ref in entity["references"]:
            python += [f"{API_ID}test_reference_{table}_{ref['field']}_missing",
                       f"{API_ID}test_reference_{table}_{ref['field']}_delete_parent"]
        python += [f"{API_ID}test_unique_{table}_{f['name']}" for f in entity["fields"] if f.get("unique")]
        python += [f"{API_ID}test_links_{table}_{link['segment'].replace('-', '_')}" for link in entity["links"]]
        python += [f"{API_ID}test_children_{table}_{child['collection'].replace('-', '_')}" for child in entity["children"]]
    python += [VALIDATION_ID + name for name in VALIDATION_GLOBAL]
    python += [MIGRATION_ID + name for name in MIGRATION_TESTS]
    python += [API_ID + name for name in API_GLOBAL]
    python += [ACCEPTANCE_ID + check["test"] for check in checks]
    dates = any(f["type"] == "date" for e in model["entities"] for f in e["fields"])
    for locale in locales:
        e2e.append(f"e2e:{locale}:language")
        if dates:
            e2e.append(f"e2e:{locale}:dates")
        for entity in model["entities"]:
            e2e += [f"e2e:{locale}:{entity['table']}:{op}" for op in ("create", "update", "delete")]
    e2e += list(E2E_GLOBAL)
    return sorted(python), sorted(e2e)


_EN = lambda *words: re.compile(r"\b(?:" + "|".join(words) + r")\b", re.I)  # noqa: E731
OPS = {
    "create": (_EN("post", "create", "creates", "created", "creating", "add", "adds", "added", "201", "new", "insert"),
               ("إنشاء", "انشاء", "إضافة", "اضافة", "أنشئ", "ينشئ", "يضيف", "جديد")),
    "list": (_EN("list", "lists", "listed", "listing", "browse", "index", "view", "views", "shows", "show", "display",
                 "displays"), ("قائمة", "عرض", "يعرض", "استعراض", "تظهر", "يظهر")),
    "update": (_EN("put", "patch", "update", "updates", "updated", "updating", "edit", "edits", "edited", "editing",
                   "modify", "modifies", "rename", "change", "changes"), ("تعديل", "تحديث", "يعدل", "يحدث")),
    "delete": (_EN("delete", "deletes", "deleted", "deleting", "remove", "removes", "removed", "removing", "204"),
               ("حذف", "إزالة", "ازالة", "يحذف")),
    "validation": (re.compile(r"\b(?:400|invalid|validat\w*|reject\w*|required field\w*|field errors?)\b", re.I),
                   ("غير صالح", "التحقق", "مرفوض", "تحقق")),
}
UI_WORDS = (re.compile(r"\b(?:ui|interface|page|screen|browser|form|forms|button|frontend)\b", re.I),
            ("واجهة", "الواجهة", "صفحة", "نموذج", "شاشة", "متصفح"))
LOCALE_WORDS = {
    "ar": (re.compile(r"\b(?:arabic|rtl|right-to-left|ar)\b", re.I), ("عربي", "العربية", "عربية")),
    "en": (re.compile(r"\b(?:english|ltr|left-to-right|en)\b", re.I), ("إنجليزي", "الإنجليزية", "انجليزي", "إنكليزي")),
}


def _nfr_rules(model, locales):
    """(pattern, evidence) pairs for non-functional statements; evidence only for what was generated."""
    dates = any(f["type"] == "date" for e in model["entities"] for f in e["fields"])
    rules = [
        (r"\bsecrets?\b|credential", ["static:security:secrets"]),
        (r"parameteri[sz]ed|sql injection|prepared statement", [API_ID + "test_sql_injection_is_inert"]),
        (r"security headers?|\bcsp\b|content-security|frame-ancestors|nosniff|clickjacking",
         [API_ID + "test_security_headers", "e2e:headers", "e2e:csp"]),
        (r"\bcsrf\b", [API_ID + "test_csrf_token_required", API_ID + "test_cross_origin_write_refused"]),
        (r"cross-origin|same-origin|cross-site", [API_ID + "test_cross_origin_write_refused"]),
        (r"\bp95\b|latency|response time", [API_ID + "test_list_latency_budget"]),
        (r"paginat", [API_ID + "test_pagination_limits"]),
        (r"keyboard", ["e2e:keyboard"]),
        (r"\bfocus\b", ["e2e:focus-indicator"]),
        (r"\blabels?\b|accessib\w*|screen reader|aria", ["e2e:labels"]),
        (r"size limit|payload|too large|\b413\b", [API_ID + "test_oversized_body_refused"]),
        (r"no network|offline|external request|\bcdn\b|third-party request", ["e2e:no-external-requests"]),
        (r"synthetic|\bseed", [API_ID + "test_seed_is_synthetic"]),
        (r"migration|rollback|\bschema\b", [MIGRATION_ID + name for name in MIGRATION_TESTS] + ["static:database:migration"]),
        (r"password|pbkdf2|hash", [API_ID + "test_passwords_are_salted_pbkdf2", API_ID + "test_login_lockout"]),
        (r"role check|every endpoint|\brbac\b|permission", [API_ID + "test_role_check_on_every_endpoint",
                                                            API_ID + "test_unauthenticated_requests_refused"]),
        (r"\bsessions?\b|sign[ -]?in|log[ -]?in", [API_ID + "test_login_logout_cycle"]),
        (r"input validation|validate input|validation on every", ["@validation"]),
    ]
    if model["rules"]["progress"]:
        rules.append((r"aggregate query", [API_ID + "test_progress_uses_one_aggregate_query"]))
    if model["auth"]["scoping"]:
        rules.append((r"see only .* belong to", [API_ID + "test_scoped_roles_see_only_their_records"]))
    if dates:
        rules.append((r"iso-?8601|displayed per locale", [VALIDATION_ID + "test_dates_are_strict"]
                      + [f"e2e:{loc}:dates" for loc in locales]))
    for loc in locales:
        rules.append((rf"^{loc} {DIRECTION[loc]}$", [f"e2e:{loc}:language", API_ID + "test_pages_follow_requested_locale"]))
    return [(re.compile(pattern, re.I), ids) for pattern, ids in rules]


def map_statement(model, locales, text):
    """Evidence ids for one non-functional statement (keyword rules; [] when nothing fits)."""
    evidence = set()
    for pattern, ids in _nfr_rules(model, locales):
        if pattern.search(text):
            evidence.update(ids)
    if "@validation" in evidence:
        evidence.discard("@validation")
        for entity in model["entities"]:
            evidence.add(f"{API_ID}test_validation_{entity['table']}")
            evidence.update(f"{VALIDATION_ID}test_{check}_{entity['table']}" for check in ("required", "types", "max_length"))
    return sorted(evidence)


def requirements(spec, model, checks, unmapped):
    """Factory requirements with acceptance ids, and the coverage map id -> (text, evidence)."""
    by_aid = {check["acceptance_id"]: check for check in checks}
    rows, coverage = [], {}
    for feature in spec["features"]:
        rid = feature["id"].lower()
        acceptance = []
        for index, text in enumerate(feature["acceptance"], 1):
            aid = f"{rid}-a{index}"
            acceptance.append(aid)
            check = by_aid.get(aid)
            coverage[aid] = {"requirement": rid, "text": text,
                             "evidence": [ACCEPTANCE_ID + check["test"]] if check else [],
                             "reason": None if check else unmapped.get(aid, "unmapped")}
        rows.append({"id": rid, "summary": feature["title"]["en"], "acceptance": acceptance})
    for category, items in sorted(spec["nfr"].items()):
        if not items:
            continue
        rid = f"nfr-{category}"
        acceptance = []
        for index, text in enumerate(items, 1):
            aid = f"{rid}-a{index}"
            acceptance.append(aid)
            evidence = map_statement(model, spec["locales"], text)
            coverage[aid] = {"requirement": rid, "text": text, "evidence": evidence,
                             "reason": None if evidence else "no generated test or check covers this statement"}
        rows.append({"id": rid, "summary": f"Non-functional ({category}): " + "; ".join(items)[:900],
                     "acceptance": acceptance})
    return rows, coverage


# ---------------------------------------------------------------------------
# rendering

def template_manifest():
    manifest = _load_template_data("manifest.json")
    _need(manifest.get("schema_version") == 1 and isinstance(manifest.get("files"), dict), "template manifest", BuildError)
    return manifest


def _template_files():
    manifest = template_manifest()
    listed = set(manifest["files"]) | set(manifest["data"]) | {"manifest.json"}
    present = {path.relative_to(TEMPLATE_DIR).as_posix() for path in TEMPLATE_DIR.rglob("*")
               if path.is_file() and "__pycache__" not in path.parts}
    _need(present == listed, f"template directory and manifest differ: {sorted(present ^ listed)}", BuildError)
    return manifest, {name: (TEMPLATE_DIR / name).read_bytes() for name in sorted(present)}


def _render(text, values, *, escape):
    def replace(match):
        key = match.group(1)
        if key not in values:
            raise BuildError(f"template marker @@{key}@@ has no value")
        return html.escape(values[key], quote=True) if escape else values[key]
    return MARKER.sub(replace, text)


def _sql_literal(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _q(name):
    _need(IDENT.fullmatch(name or ""), f"unsafe identifier {name!r}", BuildError)
    return '"' + name + '"'


def migrations_sql(model):
    sql_type = {"text": "TEXT", "email": "TEXT", "date": "TEXT", "datetime": "TEXT", "enum": "TEXT",
                "int": "INTEGER", "bool": "INTEGER", "number": "REAL"}
    roles = ", ".join(_sql_literal(role) for role in sorted(model["auth"]["roles"]))
    up = ["-- 0001_initial: generated from the specification by the GAIE Master Build Engine.",
          "-- Never edit an applied migration; add 0002_<name>.up.sql / .down.sql instead.", "",
          'CREATE TABLE "app_account" (\n  "id" INTEGER PRIMARY KEY AUTOINCREMENT,\n'
          '  "email" TEXT NOT NULL UNIQUE CHECK (length("email") <= 254),\n'
          f'  "role" TEXT NOT NULL CHECK ("role" IN ({roles})),\n'
          '  "password_salt" TEXT NOT NULL CHECK (length("password_salt") = 32),\n'
          '  "password_hash" TEXT NOT NULL CHECK (length("password_hash") = 64),\n'
          '  "password_iterations" INTEGER NOT NULL CHECK ("password_iterations" >= 1000),\n'
          '  "created_at" TEXT NOT NULL\n);',
          'CREATE TABLE "app_session" (\n  "token_sha256" TEXT PRIMARY KEY CHECK (length("token_sha256") = 64),\n'
          '  "account_id" INTEGER NOT NULL REFERENCES "app_account" ("id") ON DELETE CASCADE,\n'
          '  "csrf_token" TEXT NOT NULL,\n  "created_at" TEXT NOT NULL,\n  "expires_at" TEXT NOT NULL\n);',
          'CREATE INDEX "app_session_account_idx" ON "app_session" ("account_id");', ""]
    for entity in model["entities"]:
        columns = ['  "id" INTEGER PRIMARY KEY AUTOINCREMENT']
        for field in entity["fields"]:
            name = _q(field["name"])
            parts = [f"  {name} {sql_type[field['type']]}"]
            if field["required"]:
                parts.append("NOT NULL")
            if field.get("unique"):
                parts.append("UNIQUE")
            if "default" in field:
                parts.append("DEFAULT " + _sql_literal(field["default"]))
            checks = []
            if field["type"] in ("text", "email"):
                checks.append(f"length({name}) <= {field.get('max', MAX_TEXT)}")
            if field["type"] == "enum":
                checks.append(f"{name} IN (" + ", ".join(_sql_literal(v) for v in field["values"]) + ")")
            if field["type"] == "bool":
                checks.append(f"{name} IN (0, 1)")
            if field["type"] == "date":
                checks.append(f"length({name}) = 10")
            if field["type"] in ("int", "number"):
                if "min" in field:
                    checks.append(f"{name} >= {_sql_literal(field['min'])}")
                if "max" in field:
                    checks.append(f"{name} <= {_sql_literal(field['max'])}")
            if checks:
                parts.append("CHECK (" + " AND ".join(checks) + ")")
            columns.append(" ".join(parts))
        for ref in entity["references"]:
            action = "RESTRICT" if ref["required"] else "SET NULL"
            columns.append(f"  {_q(ref['field'])} INTEGER{' NOT NULL' if ref['required'] else ''} "
                           f"REFERENCES {_q(ref['table'])} (\"id\") ON DELETE {action}")
        columns += ['  "created_by" INTEGER REFERENCES "app_account" ("id") ON DELETE SET NULL',
                    '  "created_at" TEXT NOT NULL', '  "updated_at" TEXT NOT NULL']
        up.append(f"CREATE TABLE {_q(entity['table'])} (\n" + ",\n".join(columns) + "\n);")
        for ref in entity["references"]:
            up.append(f"CREATE INDEX {_q(entity['table'] + '_' + ref['field'] + '_idx')} "
                      f"ON {_q(entity['table'])} ({_q(ref['field'])});")
        for column in entity["default_order"]:
            up.append(f"CREATE INDEX {_q(entity['table'] + '_' + column + '_order_idx')} "
                      f"ON {_q(entity['table'])} ({_q(column)});")
        up.append("")
    for entity in model["entities"]:
        for link in entity["links"]:
            up.append(f"CREATE TABLE {_q(link['link_table'])} (\n"
                      f"  \"source_id\" INTEGER NOT NULL REFERENCES {_q(entity['table'])} (\"id\") ON DELETE CASCADE,\n"
                      f"  \"target_id\" INTEGER NOT NULL REFERENCES {_q(link['table'])} (\"id\") ON DELETE CASCADE,\n"
                      "  PRIMARY KEY (\"source_id\", \"target_id\")\n);")
            up.append(f"CREATE INDEX {_q(link['link_table'] + '_target_idx')} ON {_q(link['link_table'])} (\"target_id\");")
            up.append("")
    up.append("INSERT INTO schema_migrations (version) VALUES ('0001_initial');")
    down = ["-- Reverts 0001_initial: drops every table it created (data is lost).", ""]
    for entity in reversed(model["entities"]):
        for link in entity["links"]:
            down.append(f"DROP TABLE IF EXISTS {_q(link['link_table'])};")
    for entity in reversed(model["entities"]):
        down.append(f"DROP TABLE IF EXISTS {_q(entity['table'])};")
    down += ['DROP TABLE IF EXISTS "app_session";', 'DROP TABLE IF EXISTS "app_account";',
             "DELETE FROM schema_migrations WHERE version = '0001_initial';"]
    return "\n".join(up) + "\n", "\n".join(down) + "\n"


def seed_data(model, moment):
    labels = model["labels"]
    records, links, seeded = {}, [], []
    for entity in model["entities"]:
        rows = []
        singular_en = labels["en"]["entities"][entity["name"]]["singular"]
        singular_ar = labels["ar"]["entities"][entity["name"]]["singular"]
        for index in range(3):
            n = index + 1
            row = {}
            for field in entity["fields"]:
                kind, name = field["type"], field["name"]
                if kind == "text":
                    if name == entity["label_field"]:
                        value = f"Synthetic {singular_en.lower()} {n} · {singular_ar} تجريبي {n}"
                    else:
                        value = f"Synthetic {labels['en']['fields'][entity['name']][name].lower()} {n}"
                    row[name] = value[: field.get("max", MAX_TEXT)]
                elif kind == "email":
                    row[name] = f"synthetic.{entity['table']}{n}@example.invalid"[: field.get("max", 254)]
                elif kind == "enum":
                    row[name] = field.get("default", field["values"][index % len(field["values"])])
                elif kind in ("int", "number"):
                    value = n if kind == "int" else n * 1.5
                    row[name] = max(field.get("min", value), min(field.get("max", value), value))
                elif kind == "bool":
                    row[name] = field.get("default", index % 2 == 0)
                elif kind == "date":
                    row[name] = (moment + datetime.timedelta(days=7 * n)).strftime("%Y-%m-%d")
                elif kind == "datetime":
                    row[name] = (moment + datetime.timedelta(days=7 * n)).strftime("%Y-%m-%dT09:00:00Z")
            for ref in entity["references"]:
                if ref["entity"] in seeded:
                    row[ref["field"]] = {"$ref": [ref["entity"], index]}
            rows.append(row)
        records[entity["name"]] = rows
        seeded.append(entity["name"])
    for entity in model["entities"]:
        for link in entity["links"]:
            links += [{"source": [entity["name"], index], "segment": link["segment"], "target": [link["entity"], index]}
                      for index in range(3)]
    return {"label": "synthetic",
            "notice": {"en": "Synthetic sample records generated by the Master Build Engine; not real data. "
                             "No sign-in account is seeded.",
                       "ar": "سجلات تجريبية مولّدة آليًا؛ ليست بيانات حقيقية. لا يُنشأ أي حساب دخول تلقائيًا."},
            "records": records, "links": links}


def _i18n(spec, model):
    strings = _load_template_data("ui-strings.json")
    result = {}
    for lang in spec["locales"]:
        row = copy.deepcopy(strings[lang])
        row["app"] = {"title": spec["title"][lang]}
        row["entities"] = model["labels"][lang]["entities"]
        row["fields"] = model["labels"][lang]["fields"]
        row["values"] = model["labels"][lang]["values"]
        result[lang] = row
    return result


def _schema(spec, model):
    numbers = model["nfr"]
    return {"schema_version": 1,
            "app": {"slug": spec["slug"], "title": spec["title"], "locales": spec["locales"],
                    "default_locale": spec["locales"][0]},
            "limits": {"max_body_bytes": MAX_BODY_BYTES, "max_text": MAX_TEXT, "page_size": numbers["page_size"],
                       "max_page_size": numbers["max_page_size"]},
            "nfr": {"p95_ms": numbers["p95_ms"], "latency_records": numbers["latency_records"]},
            "auth": model["auth"], "rules": model["rules"],
            "entities": [{key: value for key, value in e.items() if key != "children"} for e in model["entities"]]}


def _api_doc(spec, model):
    lines = [f"# API reference — {spec['title']['en']}", "",
             "JSON over HTTP. Every route except `/api/health` and `/api/login` needs a session cookie from",
             "`POST /api/login`. Writes also need the session's `X-CSRF-Token` header, `Content-Type: application/json`",
             f"and a same-origin request. Bodies are limited to {MAX_BODY_BYTES} bytes. Errors have the shape "
             "`{\"error\": {\"code\", \"message\", \"fields\"?}}`.", "",
             "| Method | Path | Success | Errors |", "|---|---|---|---|",
             "| GET | `/api/health` | 200 `{\"ok\": true}` | |",
             "| POST | `/api/login` `{email, password}` | 200 + HttpOnly session cookie + `csrf_token` | 400, 401, 403, 429 |",
             "| POST | `/api/logout` | 204 | 401 |",
             "| GET | `/api/session` | 200 account + `csrf_token` | 401 |",
             "| GET | `/api/schema` | 200 entity model | 401, 403 |"]
    for entity in model["entities"]:
        base = f"/api/{entity['collection']}"
        filters = [f"`{ref['field']}`" for ref in entity["references"]]
        filters += [f"`{f['name']}`" for f in entity["fields"] if f["type"] in ("enum", "bool")]
        if any(rule["entity"] == entity["name"] for rule in model["rules"]["overdue"]):
            filters.append("`overdue=true`")
        lines += [f"| GET | `{base}` | 200 `{{items, total, limit, offset}}` | 400 bad_query, 401, 403 |",
                  f"| POST | `{base}` | 201 record + `Location` | 400 validation_failed, 409 duplicate, 401, 403, 413, 415 |",
                  f"| GET | `{base}/{{id}}` | 200 record | 404 not_found |",
                  f"| PUT / PATCH | `{base}/{{id}}` | 200 record | 400, 404, 409, 401, 403 |",
                  f"| DELETE | `{base}/{{id}}` | 204 | 404, 409 has_dependents, 401, 403 |"]
        for child in entity["children"]:
            lines.append(f"| GET | `{base}/{{id}}/{child['collection']}` | 200 that record's {child['collection']} | 404 |")
        for link in entity["links"]:
            lines.append(f"| GET / POST `{{{link['target_key']}}}` | `{base}/{{id}}/{link['segment']}` | 200 / 201 | 400, 404, 409 |")
            lines.append(f"| DELETE | `{base}/{{id}}/{link['segment']}/{{{link['target_key']}}}` | 204 | 404 |")
        if any(rule["parent"] == entity["name"] for rule in model["rules"]["progress"]):
            lines.append(f"| GET | `{base}/{{id}}/progress` | 200 totals and percent (one aggregate query) | 404 |")
        lines.append(f"| | list parameters for `{base}`: {', '.join(filters + ['`sort=<field>`', '`limit`', '`offset`'])} | | |")
    lines += ["", "## Entities", ""]
    for entity in model["entities"]:
        lines += [f"### {entity['name']} — `/api/{entity['collection']}`", "",
                  "| Field | Type | Required | Constraints |", "|---|---|---|---|"]
        for field in entity["fields"]:
            notes = []
            if "max" in field:
                notes.append(("max length " if field["type"] in ("text", "email") else "max ") + str(field["max"]))
            if "min" in field:
                notes.append(("min length " if field["type"] in ("text", "email") else "min ") + str(field["min"]))
            if field["type"] == "enum":
                notes.append("one of " + ", ".join(f"`{v}`" for v in field["values"]))
            if "default" in field:
                notes.append(f"default `{json.dumps(field['default'])}`")
            if field.get("unique"):
                notes.append("unique (409)")
            lines.append(f"| `{field['name']}` | {field['type']} | {'yes' if field['required'] else 'no'} | {'; '.join(notes)} |")
        for ref in entity["references"]:
            lines.append(f"| `{ref['field']}` | id of {ref['entity']} | {'yes' if ref['required'] else 'no'} | "
                         f"must exist (400); deleting the {ref['entity']} is "
                         f"{'refused while referenced (409)' if ref['required'] else 'allowed and clears it'} |")
        lines += ["| `id`, `created_at`, `updated_at` | read-only | | refused in request bodies |", ""]
    if model["rules"]["completion"]:
        lines += ["## State rules", ""]
        for rule in model["rules"]["completion"]:
            lines.append(f"- {rule['entity']}.{rule['field']} cannot become `{rule['value']}` while a linked "
                         f"{rule['child']} has {rule['child_field']} other than `{rule['child_value']}` (409).")
        lines.append("")
    roles = ", ".join(f"`{role}`: {', '.join(perms)}" for role, perms in sorted(model["auth"]["roles"].items()))
    lines += ["## Roles", "", f"Permissions by role: {roles}. `read`/`write`/`delete` map to GET, POST/PUT/PATCH and",
              "DELETE; `:own` limits writes to records the account created."]
    if model["auth"]["scoping"]:
        scoping = model["auth"]["scoping"]
        lines.append(f"Roles without `*` see only {scoping['entity']} records they are linked to (and their children).")
    return "\n".join(lines) + "\n"


def _package_files(slug):
    policy = json.loads(PLAYWRIGHT_POLICY.read_text(encoding="utf-8"))
    lock = json.loads(PLAYWRIGHT_LOCK.read_text(encoding="utf-8"))
    version = policy["version"]
    entries = {}
    for name in ("playwright", "playwright-core"):
        entry = lock["packages"]["node_modules/" + name]
        _need(entry["version"] == version and entry["integrity"] == policy["npm_integrities"][name],
              f"hub lockfile for {name} does not match the reviewed catalog policy", BuildError)
        entries["node_modules/" + name] = entry
    package = {"name": slug, "version": "0.1.0", "private": True,
               "description": "Development-only browser test tooling (the application itself has no Node dependency).",
               "devDependencies": {"playwright": version},
               "scripts": {"test": "python3 -I manage.py test", "test:e2e": "node tests/e2e/ui.e2e.mjs"}}
    root = {key: package[key] for key in ("name", "version", "devDependencies")}
    lockfile = {"name": slug, "version": "0.1.0", "lockfileVersion": 3, "requires": True,
                "packages": {"": root, **entries}}
    used = {"id": "catalog:microsoft/playwright", "version": version, "revision": policy["revision"],
            "scope": "dev-only browser E2E test; never a runtime dependency",
            "sources": [{"path": PLAYWRIGHT_POLICY.relative_to(ROOT).as_posix(), "sha256": _sha_bytes(PLAYWRIGHT_POLICY.read_bytes())},
                        {"path": PLAYWRIGHT_LOCK.relative_to(ROOT).as_posix(), "sha256": _sha_bytes(PLAYWRIGHT_LOCK.read_bytes())}]}
    return _json_bytes(package), _json_bytes(lockfile), used


def _git_blob(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _hublink():
    spec = importlib.util.spec_from_file_location("_gaie_build_hublink", ROOT / "hublink.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hub_revision(revision):
    _need(isinstance(revision, str) and REVISION.fullmatch(revision), "hub_revision must be a full 40-hex commit SHA",
          BuildError)
    link = _hublink()
    _need(link.has_commit(revision), f"hub_revision {revision[:12]} is not a commit of this hub", BuildError)
    return {"revision": revision, "on_main": link.on_main(revision), "hublink": link}


def _reproducible(revision, sources):
    """True when every template/data file used is byte-identical to the pinned hub commit."""
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "-r", revision, "--",
                              "templates/app-stdlib", "catalog/capabilities/playwright.json",
                              "motion-library/verify/package-lock.json", "engineering_os/build_engine.py"],
                             capture_output=True, text=True)
    blobs = {}
    for line in listing.stdout.splitlines():
        meta, _, path = line.partition("\t")
        blobs[path] = meta.split()[2] if len(meta.split()) == 3 else None
    return all(blobs.get(path) == _git_blob(data) for path, data in sources.items())


def render(spec, model, checks, *, hub, moment):
    """Return {relative path: bytes} for the whole application plus link metadata."""
    manifest, templates = _template_files()
    spec_bytes = _json_bytes(spec)
    spec_sha = _sha_bytes(spec_bytes)
    open_items = open_items_for(spec, model)
    entity_rows = ["| Entity | Collection | Fields | Relations |", "|---|---|---|---|"]
    for entity in model["entities"]:
        relations = [f"{ref['field']} → {ref['entity']}{' (required)' if ref['required'] else ''}" for ref in entity["references"]]
        relations += [f"{link['segment']} ↔ {link['entity']}" for link in entity["links"]]
        entity_rows.append(f"| {entity['name']} | `/api/{entity['collection']}` | "
                           f"{', '.join(f['name'] for f in entity['fields'])} | {', '.join(relations) or '—'} |")
    api_summary = "\n".join(f"- `/api/{e['collection']}` — list, create; `/api/{e['collection']}/{{id}}` — get, update, delete"
                            for e in model["entities"])
    strings = _load_template_data("ui-strings.json")
    common = {
        "TITLE_EN": spec["title"]["en"], "TITLE_AR": spec["title"]["ar"],
        "ENTITIES_TABLE": "\n".join(entity_rows), "API_SUMMARY": api_summary,
        "OPEN_ITEMS": "\n".join(f"- **{item['id']}** {item['summary']}" for item in open_items),
        "GENERATED_AT": _iso(moment), "HUB_REVISION": hub["revision"], "DATE": moment.strftime("%Y-%m-%d"),
        "SPEC_SHA": spec_sha, "ENTITY_LIST": ", ".join(e["name"] for e in model["entities"]),
        "ROLES": ", ".join(f"{role} ({', '.join(perms)})" for role, perms in sorted(model["auth"]["roles"].items())),
        "ADMIN_ROLE": model["auth"]["admin_role"], "MAX_BODY": str(MAX_BODY_BYTES),
        "ACCEPTANCE_COUNT": str(len(checks)),
    }

    def page_values(lang):
        ui = strings[lang]["ui"]
        return {**common, "TITLE": spec["title"][lang], "LANG": lang, "DIR": strings[lang]["dir"], "SKIP": ui["skip"],
                "LANGUAGE": ui["language"], "SECTIONS": ui["sections"], "FOOTER": ui["footer"], "NOSCRIPT": ui["noscript"],
                "LOGIN_TITLE": ui["loginTitle"], "EMAIL": ui["email"], "PASSWORD": ui["password"],
                "SIGN_IN": ui["signIn"], "SIGN_OUT": ui["signOut"]}

    files = {}
    for source, row in sorted(manifest["files"].items()):
        data = templates[source]
        if row["mode"] == "render-per-locale":
            for lang in spec["locales"]:
                files[row["to"].replace("{locale}", lang)] = _render(data.decode("utf-8"), page_values(lang),
                                                                     escape=True).encode("utf-8")
            continue
        if row["mode"] == "render":
            data = _render(data.decode("utf-8"), common, escape=row["to"].endswith(".html")).encode("utf-8")
        files[row["to"]] = data
    up, down = migrations_sql(model)
    package, lock, playwright_used = _package_files(spec["slug"])
    files.update({
        "app/schema.json": _json_bytes(_schema(spec, model)),
        "app/acceptance.json": _json_bytes({"schema": "app.acceptance/1", "spec_sha256": spec_sha, "checks": checks}),
        "app/seed_data.json": _json_bytes(seed_data(model, moment)),
        "static/i18n.json": _json_bytes(_i18n(spec, model)),
        "migrations/0001_initial.up.sql": up.encode("utf-8"),
        "migrations/0001_initial.down.sql": down.encode("utf-8"),
        "docs/API.md": _api_doc(spec, model).encode("utf-8"),
        "package.json": package,
        "package-lock.json": lock,
        ".gaie/spec.json": spec_bytes,
    })
    engine_bytes = pathlib.Path(__file__).read_bytes()
    sources = {f"templates/app-stdlib/{name}": data for name, data in templates.items()}
    sources.update({source["path"]: (ROOT / source["path"]).read_bytes() for source in playwright_used["sources"]})
    sources["engineering_os/build_engine.py"] = engine_bytes
    link = {
        "schema_version": 1, "hub_url": HUB_URL, "hub_revision": hub["revision"],
        "project": {"id": spec["slug"]}, "capabilities": [],
        "budget_additional_sar": 0, "production_runtime_dependency": False,
        "link_kind": "gaie-build/1", "generated_at": _iso(moment), "pin_on_main": hub["on_main"],
        "reproducible_from_pin": _reproducible(hub["revision"], sources),
        "spec_sha256": spec_sha,
        "generator": {"engine": "master-build", "layer": "L16", "module": "engineering_os/build_engine.py",
                      "module_sha256": _sha_bytes(engine_bytes), "template": "templates/app-stdlib",
                      "template_version": manifest["version"]},
        "used": [
            {"id": "template:app-stdlib", "installed_as": "generated source owned by the project",
             "files": [{"source": path, "sha256": _sha_bytes(data)} for path, data in sorted(sources.items())
                       if path.startswith("templates/")]},
            playwright_used,
            {"id": "engine:requirements", "interfaces": ["engineering_os.requirements:validate_spec"],
             "installed_as": "build-time specification gate only"},
            {"id": "engine:factory", "interfaces": ["engineering_os.factory:plan_factory",
                                                     "engineering_os.factory:evaluate_factory"],
             "installed_as": "build-time verification only"},
            {"id": "skill:gaie-build", "installed_as": "guidance only (prompts/MASTER_BUILD.md); not vendored"},
        ],
        "runtime_imports_from_hub": [],
        "register_hint": "To vendor hub skills later: python3 hub.py register <app> --revision <reviewed main SHA> "
                         "--capability skill:<name> --apply (writes .engineering/capabilities.json).",
    }
    files[".gaie/link.json"] = _json_bytes(link)
    return files, link


def open_items_for(spec, model):
    items = [
        {"id": "OI-REPO", "summary": "Approve creating the private GitHub repository described in "
                                     "`.gaie/repository-request.json` (external write; not done by the engine)."},
        {"id": "OI-LICENSE", "summary": "Choose a license (see `LICENSE-PENDING.md`); none was picked automatically."},
        {"id": "OI-DEPLOY", "summary": "Choose a deployment target (TLS reverse proxy, `--secure-cookies`); nothing was "
                                       "deployed and no environment was created."},
        {"id": "OI-IDENTITY", "summary": "Accounts are local (PBKDF2, created with `manage.py create-account`); decide "
                                         "whether to keep them or connect an identity provider, and add password reset/MFA."},
    ]
    if model["translation_gaps"]:
        items.append({"id": "OI-I18N", "summary": "Arabic labels missing (English shown): "
                                                  + ", ".join(model["translation_gaps"][:20])})
    return items


# ---------------------------------------------------------------------------
# workspace, registry and git

def default_workspace(environ=None):
    environ = os.environ if environ is None else environ
    if environ.get("GAIE_WORKSPACE"):
        return pathlib.Path(environ["GAIE_WORKSPACE"])
    from . import gaie_router  # existing private-state convention ($GAIE_HOME, outside Git)
    try:
        return gaie_router.gaie_home(environ) / "workspace"
    except gaie_router.RouteError as error:
        raise WorkspaceError(str(error)) from None


def _inside_git(path):
    return any((parent / ".git").exists() for parent in (path, *path.parents))


def check_target(out_dir, workspace):
    """Resolve and check the output directory; raise WorkspaceError when unsafe.

    The target must be a new (or empty) direct child of the workspace, reached
    without passing through any symlink, and the workspace must be outside the hub
    and outside every Git work tree.
    """
    workspace = pathlib.Path(workspace)
    _need(workspace.is_absolute() and workspace.is_dir() and not workspace.is_symlink(),
          "workspace must be an existing absolute directory (not a symlink)", WorkspaceError)
    real_ws = pathlib.Path(os.path.realpath(workspace))
    hub = pathlib.Path(os.path.realpath(ROOT))
    _need(real_ws != hub and hub not in real_ws.parents, "workspace must be outside the hub", WorkspaceError)
    _need(not _inside_git(real_ws), "workspace must not be inside a Git work tree", WorkspaceError)
    target = pathlib.Path(out_dir)
    _need(target.is_absolute(), "out_dir must be an absolute path", WorkspaceError)
    _need(".." not in target.parts, "out_dir must not contain '..'", WorkspaceError)
    current = pathlib.Path(os.path.abspath(target))
    reached = False
    for node in (current, *current.parents):
        if pathlib.Path(os.path.realpath(node)) == real_ws:
            reached = True
            break
        _need(not node.is_symlink(), "out_dir must not pass through symlinks", WorkspaceError)
    _need(reached, f"out_dir must be inside the allowed workspace {real_ws}", WorkspaceError)
    real = pathlib.Path(os.path.realpath(current))
    _need(real.parent == real_ws, "out_dir must be a direct child of the workspace", WorkspaceError)
    _need(SLUG.fullmatch(real.name or ""), "out_dir name must be kebab-case", WorkspaceError)
    if real.exists():
        _need(real.is_dir() and not any(real.iterdir()), "out_dir exists and is not empty", WorkspaceError)
    return real, real_ws


def find_existing(spec, *, workspace, environ=None, registry=None):
    """Registries consulted for an existing project with the same identity (fail-closed)."""
    slug = spec["slug"]
    titles = {spec["title"]["en"].casefold(), spec["title"]["ar"].casefold()}
    matches, sources = [], []
    for link_path in sorted(pathlib.Path(workspace).glob("*/.gaie/link.json")):
        try:
            data = json.loads(link_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("project", {}).get("id") == slug:
            matches.append({"source": "workspace", "id": slug, "path": link_path.parent.parent.name})
    sources.append({"source": "workspace", "status": "checked"})
    if registry is not None:
        found = registry(slug, title=spec["title"]) if callable(registry) else None
        if found is None:
            sources.append({"source": "registry", "status": "skipped: the given registry is not callable"})
        else:
            matches += [{"source": "registry", **dict(row)} for row in found]
            sources.append({"source": "registry", "status": "checked"})
        return {"matches": matches, "sources": sources}
    try:
        module = importlib.import_module("engineering_os.project_registry")
    except ImportError:
        module = None
    if module is not None:
        try:
            records = module.load(environ)
        except ValueError as error:
            raise BuildError(f"project registry unreadable, refusing to risk a duplicate: {error}") from None
        for key, record in records.items():
            names = {str(name).casefold() for name in (record.get("aliases") or []) + (record.get("private_aliases") or [])}
            names |= {str(v).casefold() for v in (record.get("names") or {}).values()}
            repository = (record.get("repository") or "").rstrip("/").split("/")[-1].casefold()
            if key == slug or slug in names or titles & names or repository == slug:
                matches.append({"source": record.get("source"), "id": key, "status": record.get("status")})
        sources.append({"source": "project_registry", "status": "checked", "projects": len(records)})
        return {"matches": matches, "sources": sources}
    from . import gaie_router
    try:
        rows = gaie_router.projects(environ)
    except gaie_router.RouteError as error:
        raise BuildError(f"project registry unreadable, refusing to risk a duplicate: {error}") from None
    for row in rows.values():
        aliases = {alias.casefold() for alias in row["aliases"]}
        if slug in aliases or row["id"] == slug or titles & aliases or row["slug"].split("/")[-1] == slug:
            matches.append({"source": row["source"], "id": row["id"]})
    sources.append({"source": "router-registry", "status": "checked (engineering_os.project_registry not present)"})
    return {"matches": matches, "sources": sources}


def _git_env(moment=None):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/nonexistent"),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
           "GIT_AUTHOR_NAME": GIT_NAME, "GIT_AUTHOR_EMAIL": GIT_EMAIL,
           "GIT_COMMITTER_NAME": GIT_NAME, "GIT_COMMITTER_EMAIL": GIT_EMAIL}
    if moment is not None:
        stamp = f"{int(moment.timestamp())} +0000"
        env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    return env


def _git(cwd, *args, moment=None, env=None, check=True):
    """Git in an engine-owned repository, without that repository's own programs.

    Hooks, fsmonitor and the untracked cache are off and lazy fetching is disabled. No transport is
    allowed except, for a push, the one of its explicit https:// or local destination
    (GIT_ALLOW_PROTOCOL overrides any protocol.* setting). Before any command but init, a repository
    whose config names a program, filter, include, URL rewrite, promisor, credential helper or HTTP
    setting is refused: a sandboxed child may have planted it (pr30-isolation F2), and `status` or
    `add` would run a clean filter on the host even with the flags above.
    """
    from .workspace_policy import DENIED_CONFIG
    destination = next((arg for arg in args[1:] if not arg.startswith("-")), "") if args[:1] == ("push",) else ""
    allowed = "https" if destination.startswith("https://") else "file" if destination.startswith("/") else ""
    flags = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
             "-c", "protocol.allow=never", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
             "-c", "core.autocrlf=false", "-c", "init.defaultBranch=main", "-C", str(cwd)]
    base = {**(env or _git_env(moment)), "GIT_NO_LAZY_FETCH": "1"}
    if args[:1] != ("init",):
        offline = {**base, "GIT_ALLOW_PROTOCOL": ""}
        located = subprocess.run([*flags, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
                                 capture_output=True, text=True, env=offline, timeout=120)
        places = located.stdout.splitlines() if located.returncode == 0 else []
        for config in ([pathlib.Path(places[1]) / "config", pathlib.Path(places[0]) / "config.worktree"]
                       if len(places) == 2 else []):
            if not os.path.lexists(config):
                continue
            listed = subprocess.run([*flags, "config", "--file", str(config), "--no-includes", "--name-only", "--null",
                                     "--list"], capture_output=True, text=True, env=offline, timeout=120)
            names = listed.stdout.split("\0") if listed.returncode == 0 else None
            if names is None or any(DENIED_CONFIG.fullmatch(name) or re.fullmatch(r"(credential|http)\..*|core\.askpass",
                                                                                 name, re.DOTALL) for name in names):
                raise BuildError("git refused: the repository config names programs, filters, credentials or "
                                 "transports that the engine never sets")
    command = [*flags, *args]
    result = subprocess.run(command, capture_output=True, text=True, env={**base, "GIT_ALLOW_PROTOCOL": allowed},
                            timeout=120)
    if check and result.returncode:
        raise BuildError(f"git {args[0]} failed: {result.stderr.strip()[:300]}")
    return result


def _write_files(target, files):
    target.mkdir(mode=0o700, exist_ok=True)
    # check_target also accepts an existing empty directory, which keeps its own mode (measured: 0777 stayed
    # 0777): make it private when the caller owns it, refuse it otherwise (recheck-security item 5). The
    # directory is opened without following a link and changed through that descriptor.
    handle = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        _need(os.fstat(handle).st_uid == os.geteuid(), f"the target directory {target} is not owned by the caller",
              WorkspaceError)
        os.fchmod(handle, 0o700)
    finally:
        os.close(handle)
    for relative, data in sorted(files.items()):
        parts = pathlib.PurePosixPath(relative).parts
        _need(parts and not relative.startswith("/") and ".." not in parts and parts[0] != ".git",
              f"unsafe generated path {relative}", BuildError)
        path = target.joinpath(*parts)
        directory = target
        for part in parts[:-1]:
            directory = directory / part
            directory.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.chmod(path, 0o700 if relative == "manage.py" else 0o600)


# ---------------------------------------------------------------------------
# verification: static checks and executed test suites

def _security_scan():
    spec = importlib.util.spec_from_file_location("_gaie_build_security_scan", ROOT / "scripts" / "security_scan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME_PREFIXES = ("app/", "static/", "migrations/", "tests/", "manage.py")
JS_FORBIDDEN = re.compile(r"\beval\s*\(|new\s+Function\b|\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|document\.write|"
                          r"setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"]|javascript:|document\.cookie")
PY_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__", "os.system", "os.popen",
                                "subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_output",
                                "subprocess.check_call", "pickle.loads", "pickle.load", "marshal.loads"})
PY_FORBIDDEN_IMPORTS = frozenset({"subprocess", "pickle", "marshal", "shelve", "ctypes", "socket", "urllib.request",
                                  "http.client", "ftplib", "smtplib", "telnetlib"})


def _python_imports(source):
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return tree, found


def _calls(tree):
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func, parts = node.func, []
            while isinstance(func, ast.Attribute):
                parts.append(func.attr)
                func = func.value
            if isinstance(func, ast.Name):
                parts.append(func.id)
                names.append(".".join(reversed(parts)))
    return names


def static_checks(target, files, model, spec, hub):
    """Deterministic checks of the generated bytes; returns {check id: {status, detail}}."""
    results = {}

    def record(check, problems, detail=None):
        results[check] = {"status": "failed" if problems else "passed",
                          "detail": {"problems": problems[:50], **(detail or {})}}

    stdlib, local = set(sys.stdlib_module_names), {"app", "tests"}
    problems, third_party = [], set()
    hub_markers = ("engineering_os", "hublink", "hub.py", "gaie_router", str(ROOT))
    for path, data in sorted(files.items()):
        if not path.startswith(RUNTIME_PREFIXES):
            continue
        text = data.decode("utf-8")
        for marker in hub_markers:
            if marker in text:
                problems.append(f"{path} references the hub ({marker if marker != str(ROOT) else 'hub path'})")
        if path.endswith(".py"):
            _, imports = _python_imports(text)
            for name in imports:
                if name.split(".")[0] not in stdlib | local:
                    third_party.add(name)
                    problems.append(f"{path} imports non-stdlib module {name}")
        if path.endswith((".js", ".mjs")):
            for spec_name in re.findall(r"""(?:from\s+|import\s*\(|require\()\s*['"]([^'"]+)['"]""", text):
                allowed = spec_name.startswith("node:") or (path.startswith("tests/e2e/") and spec_name in
                                                            ("playwright", "playwright/package.json"))
                if not allowed:
                    problems.append(f"{path} imports {spec_name}")
    problems += [f"{path} contains an absolute local path" for path, data in files.items()
                 if str(target) in data.decode("utf-8", "replace") or "/home/" in data.decode("utf-8", "replace")]
    pages = [f"static/index.{lang}.html" for lang in spec["locales"]]
    components = ["app/model.py", "app/db.py", "app/auth.py", "app/server.py", "app/seed.py", "static/app.js",
                  "static/app.css", "migrations/0001_initial.up.sql", "tests/test_api.py", "tests/test_acceptance.py",
                  "tests/e2e/ui.e2e.mjs", *pages]
    problems += [f"component missing: {path}" for path in components if path not in files]
    record("static:architecture:independence", problems,
           {"runtime": spec["constraints"]["runtime"], "database": spec["constraints"]["database"],
            "third_party_runtime_imports": sorted(third_party), "components": components})

    scanner = _security_scan()
    secret_hits = []
    for path, data in sorted(files.items()):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        secret_hits += [f"{finding.path}:{finding.line} {finding.rule}" for finding in scanner.secret_findings(path, text)]
    env_files = [path for path in files if pathlib.PurePosixPath(path).name.startswith(".env")
                 or pathlib.PurePosixPath(path).suffix in (".pem", ".key", ".p12")]
    record("static:security:secrets", secret_hits + [f"{p}: environment/key file" for p in env_files],
           {"scanner": "scripts/security_scan.py secret_findings", "files_scanned": len(files)})

    code_problems = []
    for path, data in sorted(files.items()):
        text = data.decode("utf-8", "replace")
        if path.endswith(".py"):
            code_problems += [f"{f.path}:{f.line} {f.rule}" for f in scanner.python_findings(path, text)]
            tree, imports = _python_imports(text)
            for call in _calls(tree):
                if call in PY_FORBIDDEN_CALLS:
                    code_problems.append(f"{path}: forbidden call {call}")
            if path.startswith(("app/", "manage.py")):
                code_problems += [f"{path}: forbidden import {name}" for name in imports if name in PY_FORBIDDEN_IMPORTS]
            if path == "app/db.py" and re.search(r"\.format\(|%\s*\(|\bf[\"'](?:SELECT|INSERT|UPDATE|DELETE)", text):
                code_problems.append(f"{path}: string-formatted SQL")
        if path.startswith("static/") and path.endswith(".js") and JS_FORBIDDEN.search(text):
            code_problems.append(f"{path}: forbidden dynamic code, cookie access or HTML injection sink")
        if path.endswith(".html"):
            if re.search(r"<script(?![^>]*\bsrc=)[^>]*>", text) or re.search(r"\son[a-z]+\s*=", text) \
                    or re.search(r"\sstyle\s*=", text):
                code_problems.append(f"{path}: inline script, handler or style")
            if re.search(r"""(?:src|href)\s*=\s*["']https?://""", text):
                code_problems.append(f"{path}: external resource")
    server = files.get("app/server.py", b"").decode("utf-8")
    auth = files.get("app/auth.py", b"").decode("utf-8")
    for needle in ("frame-ancestors 'none'", "X-Content-Type-Options", "nosniff", "max_body_bytes", "_same_origin",
                   "HttpOnly", "SameSite=Strict", "X-CSRF-Token", "hmac.compare_digest", "_authenticate"):
        if needle not in server:
            code_problems.append(f"app/server.py: missing {needle}")
    for needle in ("pbkdf2_hmac", "secrets.token_bytes(16)", "compare_digest", "token_digest"):
        if needle not in auth:
            code_problems.append(f"app/auth.py: missing {needle}")
    if model["auth"]["pbkdf2_iterations"] < 600000:
        code_problems.append("PBKDF2 iterations below 600000")
    record("static:security:code", code_problems, {"scanner": "scripts/security_scan.py python_findings + engine rules"})

    package = json.loads(files["package.json"])
    lock = json.loads(files["package-lock.json"])
    policy = json.loads(PLAYWRIGHT_POLICY.read_text(encoding="utf-8"))
    dep_problems = []
    if set(package) - {"name", "version", "private", "description", "devDependencies", "scripts"}:
        dep_problems.append("package.json declares more than dev tooling")
    if package.get("devDependencies") != {"playwright": policy["version"]}:
        dep_problems.append("devDependencies must be exactly the reviewed Playwright version")
    if any(key in package.get("scripts", {}) for key in ("preinstall", "install", "postinstall", "prepare")):
        dep_problems.append("install lifecycle scripts are not allowed")
    for name in ("playwright", "playwright-core"):
        entry = lock["packages"].get("node_modules/" + name, {})
        if entry.get("integrity") != policy["npm_integrities"][name] or entry.get("version") != policy["version"]:
            dep_problems.append(f"package-lock {name} does not match the reviewed integrity")
    dep_problems += [f"third-party runtime import {name}" for name in sorted(third_party)]
    record("static:dependencies", dep_problems,
           {"python_runtime": "standard library only", "node_dev": {"playwright": policy["version"]},
            "catalog": "catalog/capabilities/playwright.json"})

    record("static:database:migration", *_migration_check(files, model))

    gitignore = files.get(".gitignore", b"").decode("utf-8")
    iso_problems = [f".gitignore lacks {entry}" for entry in ("data/", "*.sqlite3", ".env") if entry not in gitignore]
    iso_problems += [f"database file generated: {path}" for path in files if path.endswith((".sqlite3", ".db", ".sqlite"))]
    seed = json.loads(files["app/seed_data.json"])
    if seed.get("label") != "synthetic":
        iso_problems.append("seed data is not labelled synthetic")
    for entity in model["entities"]:
        label = entity["label_field"]
        for row in seed["records"].get(entity["name"], []):
            if label and "synthetic" not in str(row.get(label, "")).lower() and len(str(row.get(label, ""))) >= 9:
                iso_problems.append(f"seed row of {entity['name']} not marked synthetic")
    record("static:database:isolation", iso_problems,
           {"database": "data/app.sqlite3 (gitignored, created at run time)", "seed": "app/seed_data.json label=synthetic",
            "accounts": "none seeded; created by the owner with manage.py create-account"})

    script = files.get("static/app.js", b"").decode("utf-8")
    css = files.get("static/app.css", b"").decode("utf-8")
    a11y = []
    for lang, page in zip(spec["locales"], pages):
        text = files.get(page, b"").decode("utf-8")
        a11y += [f"{page} lacks {needle}" for needle in (f'<html lang="{lang}" dir="{DIRECTION[lang]}">', '<main id="main"',
                                                         'class="skip-link"', 'role="status"', 'aria-live="polite"',
                                                         'role="alert"', 'for="login-email"', 'for="login-password"')
                 if needle not in text]
    a11y += [f"app.js lacks {needle}" for needle in ("for: id", "aria-describedby", "aria-invalid", "aria-pressed",
                                                     "aria-current", "root.dir", "Intl.DateTimeFormat") if needle not in script]
    a11y += [] if re.search(r":focus-visible\s*\{\s*outline:\s*3px", css) else ["app.css lacks a visible focus outline"]
    record("static:frontend:accessibility", a11y, {"checked": "landmarks, skip link, live regions, labels, RTL switch, focus"})

    readme = files.get("README.md", b"").decode("utf-8")
    api_doc = files.get("docs/API.md", b"").decode("utf-8")
    changelog = files.get("CHANGELOG.md", b"").decode("utf-8")
    doc_problems = [f"README lacks section {h}" for h in ("## Run", "## Test", "## API", "## Security", "## Open items")
                    if h not in readme]
    doc_problems += [f"docs/API.md lacks /api/{e['collection']}" for e in model["entities"]
                     if f"/api/{e['collection']}" not in api_doc]
    doc_problems += [] if re.search(r"## \[0\.1\.0\] - \d{4}-\d{2}-\d{2}", changelog) else ["CHANGELOG lacks 0.1.0 entry"]
    doc_problems += [] if "LICENSE-PENDING.md" in files and "OI-LICENSE" in readme else ["license decision not recorded"]
    doc_problems += [] if "LICENSE" not in files else ["a LICENSE was chosen without the owner"]
    doc_problems += [] if "docs/ARCHITECTURE.md" in files and "ADR-001" in files["docs/ARCHITECTURE.md"].decode() else ["ADRs missing"]
    doc_problems += [f"unrendered template marker in {p}" for p, d in files.items() if MARKER.search(d.decode("utf-8", "replace"))]
    record("static:documentation", doc_problems, {"documents": ["README.md", "docs/API.md", "docs/ARCHITECTURE.md",
                                                                "CHANGELOG.md", "LICENSE-PENDING.md"]})

    link = json.loads(files[".gaie/link.json"])
    link_problems = [f"link.json: {problem}" for problem in hub["hublink"].validate_manifest(link)]
    if link.get("hub_revision") != hub["revision"] or link.get("production_runtime_dependency") is not False:
        link_problems.append("link.json does not pin the build revision")
    record("static:link", link_problems, {"convention": "hublink.validate_manifest (same keys as .engineering/capabilities.json)",
                                          "pin_on_main": hub["on_main"], "reproducible_from_pin": link["reproducible_from_pin"]})
    return results


def _migration_check(files, model):
    problems, detail = [], {"database": "in-memory SQLite", "steps": ["up", "inspect", "down", "up"]}
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, "
                           "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        up = files["migrations/0001_initial.up.sql"].decode("utf-8")
        down = files["migrations/0001_initial.down.sql"].decode("utf-8")

        def tables():
            return {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}

        connection.executescript("BEGIN;\n" + up + "\nCOMMIT;")
        for entity in model["entities"]:
            columns = {row[1]: row for row in connection.execute(f"PRAGMA table_info({_q(entity['table'])})")}
            wanted = {"id", "created_by", "created_at", "updated_at"} | {f["name"] for f in entity["fields"]} \
                | {r["field"] for r in entity["references"]}
            if set(columns) != wanted:
                problems.append(f"{entity['table']}: columns {sorted(columns)} != {sorted(wanted)}")
            for field in entity["fields"]:
                if field["required"] and field["name"] in columns and not columns[field["name"]][3]:
                    problems.append(f"{entity['table']}.{field['name']}: required but nullable")
            fks = {(row[3], row[2]) for row in connection.execute(f"PRAGMA foreign_key_list({_q(entity['table'])})")}
            for ref in entity["references"]:
                if (ref["field"], ref["table"]) not in fks:
                    problems.append(f"{entity['table']}.{ref['field']}: foreign key missing")
            unique = set()
            for index in connection.execute(f"PRAGMA index_list({_q(entity['table'])})"):
                if index[2]:
                    unique |= {row[2] for row in connection.execute(f"PRAGMA index_info({_q(index[1])})")}
            for field in entity["fields"]:
                if field.get("unique") and field["name"] not in unique:
                    problems.append(f"{entity['table']}.{field['name']}: UNIQUE constraint missing")
        expected = {e["table"] for e in model["entities"]} | {l["link_table"] for e in model["entities"] for l in e["links"]} \
            | {"app_account", "app_session"}
        if tables() != expected | {"schema_migrations"}:
            problems.append(f"tables after up: {sorted(tables())}")
        if [r[0] for r in connection.execute("SELECT version FROM schema_migrations")] != ["0001_initial"]:
            problems.append("up migration does not record its version")
        connection.executescript("BEGIN;\n" + down + "\nCOMMIT;")
        if tables() != {"schema_migrations"} or connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]:
            problems.append("down migration does not restore the empty schema")
        connection.executescript("BEGIN;\n" + up + "\nCOMMIT;")
        if tables() != expected | {"schema_migrations"}:
            problems.append("up after down failed")
        detail["tables"] = sorted(expected)
    except sqlite3.Error as error:
        problems.append(f"SQLite error: {error}")
    finally:
        connection.close()
    return problems, detail


def _scrub(text, *paths):
    text = str(text or "")
    for path in paths:
        text = text.replace(str(path), "<path>")
    return re.sub(r"/(?:home|root|Users)/[^\s'\"]+", "<path>", text)[-1500:]


def _child_env(home):
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "TMPDIR": str(home),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}


def run_suites(target, *, e2e=True, timeout=1200):
    """Run the generated app's own test suites in child processes (hub not on any path)."""
    results = {"python": {"status": "not-run"}, "e2e": {"status": "not-run"}}
    with tempfile.TemporaryDirectory(prefix="gaie-build-run-") as tmp:
        home = pathlib.Path(tmp)
        report = home / "python-report.json"
        command = [sys.executable, "-I", "manage.py", "test", "--report", str(report)]
        try:
            run = subprocess.run(command, cwd=target, env=_child_env(home), capture_output=True, text=True, timeout=timeout)
            data = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else None
            if data and data.get("schema") == "app.test-report/1":
                results["python"] = {"status": "passed" if run.returncode == 0 else "failed",
                                     "command": "python3 -I manage.py test", "summary": data["summary"],
                                     "tests": {row["id"]: row["status"] for row in data["tests"]}}
                if run.returncode:
                    results["python"]["error"] = _scrub(run.stderr, target, home)
            else:
                results["python"] = {"status": "failed", "command": "python3 -I manage.py test",
                                     "error": _scrub(run.stderr, target, home)}
        except subprocess.TimeoutExpired:
            results["python"] = {"status": "failed", "error": f"timed out after {timeout} s"}
        node = shutil.which("node")
        if not e2e:
            results["e2e"] = {"status": "not-run", "reason": "E2E disabled by the caller"}
        elif node is None:
            results["e2e"] = {"status": "not-run", "reason": "node is not installed"}
        else:
            env = _child_env(home)
            env["APP_PYTHON"] = sys.executable
            for key in ("NODE_PATH", "PLAYWRIGHT_BROWSERS_PATH", "APP_CHROMIUM_EXECUTABLE"):
                if os.environ.get(key):
                    env[key] = os.environ[key]
            try:
                run = subprocess.run([node, "tests/e2e/ui.e2e.mjs"], cwd=target, env=env, capture_output=True,
                                     text=True, timeout=timeout)
                line = (run.stdout.strip().splitlines() or [""])[-1]
                data = json.loads(line) if line.startswith("{") else None
                if data and data.get("schema") == "app.e2e-report/1":
                    status = "passed" if run.returncode == 0 and data.get("ok") else (
                        "not-run" if run.returncode == 2 else "failed")
                    results["e2e"] = {"status": status, "command": "node tests/e2e/ui.e2e.mjs",
                                      "runner": data.get("runner"), "playwright_version": data.get("playwright_version"),
                                      "browser": data.get("browser"), "error": _scrub(data.get("error"), target, home) or None,
                                      "tests": {row["id"]: row["status"] for row in data.get("cases", [])},
                                      "failures": [{**row, "error": _scrub(row.get("error"), target, home)}
                                                   for row in data.get("cases", []) if row["status"] != "passed"][:20]}
                else:
                    results["e2e"] = {"status": "failed", "error": _scrub(run.stderr or run.stdout, target, home)}
            except subprocess.TimeoutExpired:
                results["e2e"] = {"status": "failed", "error": f"timed out after {timeout} s"}
    return results


def _evidence_status(evidence_id, statics, suites):
    if evidence_id.startswith("static:"):
        return statics.get(evidence_id, {}).get("status", "not-run")
    suite = suites["e2e"] if evidence_id.startswith("e2e:") else suites["python"]
    status = suite.get("tests", {}).get(evidence_id)
    if status is None:
        return "not-run" if suite["status"] == "not-run" else "missing"
    return status


def coverage_matrix(coverage, statics, suites, catalog):
    known = set(catalog[0]) | set(catalog[1]) | set(statics)
    rows = []
    for aid, row in sorted(coverage.items()):
        states = {eid: _evidence_status(eid, statics, suites) for eid in row["evidence"]}
        if not row["evidence"]:
            status = "unmapped"
        elif any(eid not in known for eid in row["evidence"]):
            status = "unknown-evidence"
        elif all(state == "passed" for state in states.values()):
            status = "passed"
        elif any(state in ("failed", "error", "missing") for state in states.values()):
            status = "failed"
        else:
            status = "not-run"
        rows.append({"acceptance": aid, "requirement": row["requirement"], "criterion": row["text"],
                     "evidence": states, "status": status, **({"reason": row["reason"]} if status == "unmapped" else {})})
    return rows


# ---------------------------------------------------------------------------
# factory receipts

def _ids_status(ids, statics, suites):
    states = {eid: _evidence_status(eid, statics, suites) for eid in ids}
    if ids and all(state == "passed" for state in states.values()):
        return "passed", states
    if any(state in ("failed", "error", "missing") for state in states.values()):
        return "failed", states
    return "not-run", states


def _stage_checks(ctx):
    statics, suites, catalog = ctx["statics"], ctx["suites"], ctx["catalog"]
    python_ids, e2e_ids = catalog
    unit = [t for t in python_ids if t.startswith((VALIDATION_ID, MIGRATION_ID))]
    api = [t for t in python_ids if t.startswith((API_ID, ACCEPTANCE_ID))]
    contract = [t for t in python_ids if t.startswith(ACCEPTANCE_ID) or (t.startswith(API_ID) and any(
        f"test_{op}_" in t for op in API_OPS + ("reference", "unique", "links", "children")))]
    authz = [API_ID + name for name in ("test_unauthenticated_requests_refused", "test_role_check_on_every_endpoint",
                                        "test_csrf_token_required", "test_cross_origin_write_refused",
                                        "test_login_logout_cycle", "test_scoped_roles_see_only_their_records",
                                        "test_method_not_allowed")]
    browser = [t for t in e2e_ids if t.count(":") >= 2 or t in ("e2e:login", "e2e:logout")]
    a11y = ["e2e:labels", "e2e:keyboard", "e2e:focus-indicator"] + [f"e2e:{loc}:language" for loc in ctx["spec"]["locales"]] \
        + ["static:frontend:accessibility"]
    security = ["static:security:code", API_ID + "test_security_headers", API_ID + "test_sql_injection_is_inert",
                API_ID + "test_oversized_body_refused", API_ID + "test_invalid_json_refused",
                API_ID + "test_passwords_are_salted_pbkdf2", API_ID + "test_login_lockout", "e2e:csp", "e2e:headers",
                "e2e:no-external-requests"]
    matrix = ctx["coverage"]
    mapped = [row for row in matrix if row["status"] not in ("unmapped", "unknown-evidence")]

    def acceptance():
        problems = [f"{row['acceptance']}: {row['status']} ({row.get('reason', '')})" for row in matrix if row not in mapped]
        return ("passed" if not problems else "failed",
                {"rule": "every acceptance criterion maps to a generated test or static check",
                 "criteria": len(matrix), "mapped": len(mapped), "problems": problems})

    def regression():
        status, states = _ids_status(python_ids + e2e_ids, statics, suites)
        unpassed = [row["acceptance"] for row in matrix if row["status"] != "passed"]
        extra = sorted(set(suites["python"].get("tests", {})) - set(python_ids))
        if status == "passed" and unpassed:
            status = "failed"
        return status, {"rule": "every expected test executed and passed; every acceptance criterion passed",
                        "expected": len(states), "not_passed": [k for k, v in states.items() if v != "passed"][:40],
                        "criteria_not_passed": unpassed, "additional_tests": extra}

    def ids(names, rule):
        def check():
            status, states = _ids_status(names, statics, suites)
            return status, {"rule": rule, "evidence": states}
        return check

    def release_review():
        problems = list(statics["static:link"]["detail"]["problems"])
        request = ctx["repository_request"]
        if not request or request.get("visibility") != "private" or request.get("status") != "awaiting-approval":
            problems.append("repository request missing or not private/awaiting approval")
        if ctx["source_commit"] is None:
            problems.append("no source commit")
        if ctx["git_clean"] is not True:
            problems.append("working tree not clean at the source commit")
        return ("passed" if not problems else "failed",
                {"rule": "pinned link, clean source commit, private repository request awaiting approval, no deployment",
                 "source_commit": ctx["source_commit"], "deployment_authorized": False, "problems": problems})

    def rollback():
        status, states = _ids_status(["static:database:migration", MIGRATION_ID + "test_down_removes_schema"], statics, suites)
        return status, {"rule": "down migration verified; source commit is the rollback point", "evidence": states,
                        "rollback_point": ctx["source_commit"]}

    return {
        ("requirements", "acceptance"): acceptance,
        ("architecture", "architecture_review"): ids(["static:architecture:independence", "static:link"],
                                                     "no hub imports or paths; stdlib-only runtime; components present"),
        ("database", "migration"): ids(["static:database:migration"] + [MIGRATION_ID + n for n in MIGRATION_TESTS],
                                       "up/down/up verified in-process and by the app's own migration tests"),
        ("database", "data_isolation"): ids(["static:database:isolation"], "runtime data gitignored; seed synthetic"),
        ("api", "contract"): ids(contract, "every acceptance criterion and CRUD/relation checks over real HTTP"),
        ("api", "authorization"): ids(authz + ["static:security:code"],
                                      "sessions, roles on every endpoint, CSRF, same-origin, scoping, method checks"),
        ("backend", "integration"): ids(unit + api, "the complete Python suite passed against the real server"),
        ("frontend", "browser"): ids(browser, "sign in, create/update/delete through the UI in every locale (Chromium)"),
        ("frontend", "accessibility"): ids(a11y, "labels, keyboard reachability, focus indicator, lang/dir, landmarks"),
        ("testing", "unit"): ids(unit, "validation and migration unit tests"),
        ("testing", "integration"): ids(api, "API and acceptance tests on a free loopback port"),
        ("testing", "regression"): regression,
        ("security", "secrets"): ids(["static:security:secrets"], "scripts/security_scan.py secret rules over every file"),
        ("security", "dependencies"): ids(["static:dependencies"], "stdlib runtime; dev-only Playwright pinned to the review"),
        ("security", "security"): ids(security, "no eval/shell/HTML sinks; PBKDF2; headers, CSP, size limits, SQL inertness"),
        ("documentation", "documentation_review"): ids(["static:documentation"], "README run/test/API, API.md, ADRs, CHANGELOG"),
        ("release", "release_review"): release_review,
        ("release", "rollback"): rollback,
    }


def _stage_content(ctx):
    spec, model, files = ctx["spec"], ctx["model"], ctx["files"]
    file_ref = lambda path: {"path": path, "sha256": _sha_bytes(files[path])}  # noqa: E731
    suites = ctx["suites"]
    pages = [f"static/index.{lang}.html" for lang in spec["locales"]]
    return {
        "requirements": {
            "requirements": [{"id": row["id"], "summary": row["summary"],
                              "acceptance": [{"id": aid, "criterion": ctx["coverage_map"][aid]["text"],
                                              "evidence": ctx["coverage_map"][aid]["evidence"]} for aid in row["acceptance"]]}
                             for row in ctx["requirements"]],
            "data_boundaries": {"storage": "local SQLite file data/app.sqlite3, gitignored",
                                "seed": "synthetic records only; no accounts", "hub": "no runtime dependency",
                                "personal_data": "account e-mails and records entered by operators; passwords only as PBKDF2 hashes"},
            "spec": file_ref(".gaie/spec.json"), "acceptance": file_ref("app/acceptance.json"),
            "open_items": ctx["open_items"]},
        "architecture": {
            "components": [file_ref(path) for path in ("app/model.py", "app/db.py", "app/auth.py", "app/server.py",
                                                       "app/seed.py", "static/app.js", "manage.py", *pages)],
            "decisions": [{"id": "ADR-001", "decision": "modular monolith on the Python standard library + SQLite"},
                          {"id": "ADR-002", "decision": "same-origin JSON API with per-session CSRF tokens"},
                          {"id": "ADR-003", "decision": "local PBKDF2 accounts, HttpOnly SameSite=Strict sessions, roles from the spec"},
                          {"id": "ADR-004", "decision": "bilingual UI without a build step; server-side lang/dir"}],
            "constraints": spec["constraints"], "document": file_ref("docs/ARCHITECTURE.md")},
        "database": {
            "entities": [{"name": e["name"], "table": e["table"],
                          "columns": ["id"] + [f["name"] for f in e["fields"]] + [r["field"] for r in e["references"]]}
                         for e in model["entities"]],
            "migrations": [file_ref("migrations/0001_initial.up.sql")],
            "rollback": [file_ref("migrations/0001_initial.down.sql")]},
        "api": {
            "operations": [{"collection": f"/api/{e['collection']}",
                            "methods": ["GET", "POST", "GET {id}", "PUT {id}", "PATCH {id}", "DELETE {id}"],
                            "sub_resources": [c["collection"] for c in e["children"]] + [l["segment"] for l in e["links"]]}
                           for e in model["entities"]],
            "authentication": {"mode": "local accounts, PBKDF2-HMAC-SHA256, HttpOnly SameSite=Strict session cookie",
                               "csrf": "per-session token in X-CSRF-Token", "roles": model["auth"]["roles"],
                               "scoping": model["auth"]["scoping"]},
            "errors": [400, 401, 403, 404, 405, 409, 411, 413, 415, 429], "reference": file_ref("docs/API.md"),
            "rules": model["rules"]},
        "backend": {
            "services": [file_ref("app/server.py"), file_ref("app/db.py"), file_ref("app/auth.py")],
            "boundaries": ["request body <= %d bytes" % MAX_BODY_BYTES, "parameterized SQL", "identifiers from schema only",
                           "session + role check before every data route"],
            "configuration": ["serve --host (loopback unless --allow-network)", "serve --port", "--db PATH",
                              "--secure-cookies", "create-account --email --role"]},
        "frontend": {
            "routes": ["/", "/?lang=<locale>", "/static/app.js", "/static/app.css", "/static/i18n.json"],
            "components": [file_ref(path) for path in pages] + [file_ref("static/app.js"), file_ref("static/i18n.json")],
            "accessibility": ["labels for every control", "keyboard reachable", "skip link", "live regions",
                              "visible focus outline", "lang/dir per locale"] + [f"locale {loc}" for loc in spec["locales"]]},
        "testing": {
            "suites": [{"name": "python", **{k: v for k, v in suites["python"].items() if k != "tests"}},
                       {"name": "e2e", **{k: v for k, v in suites["e2e"].items() if k != "tests"}}],
            "regressions": {"expected_tests": len(ctx["catalog"][0]) + len(ctx["catalog"][1]),
                            "acceptance_tests": len(ctx["checks"])},
            "coverage": ctx["coverage"]},
        "security": {
            "threats": ["XSS via record values", "CSRF", "clickjacking", "SQL injection", "oversized bodies",
                        "path traversal", "secret leakage", "credential stuffing", "session theft",
                        "unauthenticated network exposure"],
            "findings": [{"id": "SEC-1", "severity": "medium", "summary": "local accounts without password reset or MFA",
                          "status": "accepted for 0.1.0; open item OI-IDENTITY"},
                         {"id": "SEC-2", "severity": "low", "summary": "login lockout is per process (in memory)",
                          "status": "accepted; a reverse proxy rate limit is recommended"}]
                        + [{"id": key, "status": value["status"]} for key, value in sorted(ctx["statics"].items())
                           if key.startswith(("static:security", "static:dependencies"))],
            "remediations": ["loopback bind by default; --allow-network only behind TLS and a proxy",
                             "CSP default-src 'self' with frame-ancestors 'none'", "textContent-only DOM updates",
                             "PBKDF2 600000 iterations with per-account salt", "CSRF token bound to the session"]},
        "documentation": {
            "setup": [file_ref("README.md")],
            "operations": [file_ref("docs/API.md"), file_ref("CHANGELOG.md")],
            "limitations": [item["summary"] for item in ctx["open_items"]]},
        "release": {
            "revision": ctx["source_commit"] or "uncommitted",
            "rollback": {"code": f"git revert/reset to {ctx['source_commit']}", "data": "python3 manage.py migrate --down 1"},
            "verification": {"repository_request": REQUEST_FILE, "deployment_authorized": False,
                             "remote": "not created (needs owner approval)"}},
    }


def write_factory_evidence(target, ctx):
    root = target / FACTORY_DIR
    root.mkdir(parents=True, exist_ok=True)
    request = {"schema_version": 1, "project": ctx["spec"]["slug"], "source_revision": ctx["source_commit"],
               "requirements": ctx["requirements"], "targets": TARGETS}
    plan = factory.plan_factory(request)
    traces = {row["id"]: row["acceptance"] for row in plan["request"]["requirements"]}
    contents, checks = _stage_content(ctx), _stage_checks(ctx)

    def write(relative, value):
        data = _json_bytes(value)
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": relative, "sha256": _sha_bytes(data)}

    receipts, by_stage = [], {}
    for stage in plan["stages"]:
        document = {"schema_version": 1, "project": request["project"], "source_revision": request["source_revision"],
                    "kind": stage["artifact_kind"], "traces": traces, "content": contents[stage["id"]]}
        artifact = write(f"artifacts/{stage['id']}.json", document)
        rows = []
        for check_id in stage["required_checks"]:
            status, detail = checks[(stage["id"], check_id)]()
            proof = {"schema_version": 1, "project": request["project"], "source_revision": request["source_revision"],
                     "plan_sha256": plan["plan_sha256"], "stage": stage["id"], "check": check_id, "status": status,
                     "artifact_sha256": artifact["sha256"], "acceptance": traces}
            evidence = write(f"checks/{stage['id']}-{check_id}.json", proof)
            write(f"details/{stage['id']}-{check_id}.json", {"stage": stage["id"], "check": check_id, "status": status,
                                                              "evaluator": REVIEWER, "kind": "deterministic", **detail})
            rows.append({"id": check_id, "status": status, "evidence": evidence})
        receipt = {"schema_version": 1, "project": request["project"], "source_revision": request["source_revision"],
                   "plan_sha256": plan["plan_sha256"], "stage": stage["id"],
                   "dependencies": {key: sha(by_stage[key]) for key in stage["depends_on"]},
                   "artifact": artifact, "checks": rows, "reviewer": REVIEWER}
        by_stage[stage["id"]] = receipt
        receipts.append(receipt)
    write("request.json", request)
    write("plan.json", plan)
    write("receipts.json", receipts)
    evaluation = factory.evaluate_factory(plan, receipts, artifact_root=root)
    write("evaluation.json", evaluation)
    return plan, receipts, evaluation


def evaluate(app_dir):
    """Re-validate the stored receipts against the application's current bytes (no execution)."""
    root = pathlib.Path(app_dir) / FACTORY_DIR
    try:
        request = json.loads((root / "request.json").read_text(encoding="utf-8"))
        receipts = json.loads((root / "receipts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BuildError(f"factory evidence unreadable: {error}") from None
    plan = factory.plan_factory(request)
    return factory.evaluate_factory(plan, receipts, artifact_root=root)


# ---------------------------------------------------------------------------
# repository request and the gated publish step

def request_repository(app_dir, *, spec=None, moment=None):
    """Write .gaie/repository-request.json for the owner. Never contacts GitHub."""
    app_dir = pathlib.Path(app_dir)
    if spec is None:
        spec = json.loads((app_dir / ".gaie/spec.json").read_text(encoding="utf-8"))
    request = {
        "schema": "gaie.repository-request/1", "status": "awaiting-approval",
        "name": spec["slug"], "visibility": "private",
        "description": f"{spec['title']['en']} — {spec['title']['ar']} (generated by the GAIE Master Build Engine)",
        "owner_account": "chosen by the owner at approval time",
        "side_effect": "external-write", "approval": "owner approval token for engine master-build, action publish",
        "steps_after_approval": [
            "Create the private repository (owner, or a host tool authorized for ext:github).",
            "python3 -m engineering_os.build_engine publish <app> --remote https://github.com/<owner>/" + spec["slug"]
            + ".git --grant <grant.json> --token-file <token>",
        ],
        "network_calls_made": 0,
    }
    if moment is not None:
        request["requested_at"] = _iso(moment)
    path = app_dir / REQUEST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(request))
    return request


def check_approval(grant, token, *, now=None):
    """Validate an owner approval for master-build/publish (external-write). Raise ApprovalRequired."""
    if grant is None or token is None:
        raise ApprovalRequired("publishing is external-write: an owner approval grant and token are required")
    try:
        contracts.validate_grant(grant)
    except contracts.ContractError as error:
        raise ApprovalRequired(f"invalid grant: {error}") from None
    moment = _now(now)
    expires = datetime.datetime.strptime(grant["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    if expires <= moment:
        raise ApprovalRequired("grant expired")
    if "publish" not in grant["engines"].get("master-build", []):
        raise ApprovalRequired("grant does not cover master-build/publish")
    if contracts.side_effect_rank(grant["max_side_effect"]) < contracts.side_effect_rank("external-write"):
        raise ApprovalRequired("grant max_side_effect is below external-write")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest() if isinstance(token, str) else ""
    for approval in grant["approvals"]:
        if (approval["side_effect"] == "external-write" and approval["engine"] == "master-build"
                and approval["action"] == "publish" and approval["token_sha256"] == digest):
            return approval
    raise ApprovalRequired("no matching owner approval for master-build/publish")


def _remote(remote, name):
    if not isinstance(remote, str) or not remote or remote.startswith("-") or any(c in remote for c in "\n\r\0 "):
        raise BuildError("remote must be an https://github.com/<owner>/<name>.git URL or a local bare repository")
    match = GITHUB_REMOTE.fullmatch(remote)
    if match:
        if match.group(2) != name:
            raise BuildError(f"remote repository name must be {name!r} as requested")
        return remote, "github"
    path = pathlib.Path(remote)
    if path.is_absolute() and path.is_dir() and not path.is_symlink():
        bare = _git(path, "rev-parse", "--is-bare-repository", check=False)
        if bare.returncode == 0 and bare.stdout.strip() == "true":
            return str(path), "local-bare"
    raise BuildError("remote must be an https://github.com/<owner>/<name>.git URL or a local bare repository")


def register_project(app_dir, repository, *, environ=None, apply=False):
    """Record a published project in the private registry ($GAIE_HOME, state-write; dry-run by default)."""
    from . import project_registry
    app_dir = pathlib.Path(app_dir)
    spec = json.loads((app_dir / ".gaie/spec.json").read_text(encoding="utf-8"))
    link = json.loads((app_dir / ".gaie/link.json").read_text(encoding="utf-8"))
    url = repository[:-4] if repository.endswith(".git") else repository
    return project_registry.register(spec["slug"], environ=environ, apply=apply, repository=url, visibility="private",
                                     approved_hub_revision=link["hub_revision"])


def publish(app_dir, *, remote, grant=None, token=None, now=None, environ=None):
    """Push the app's main branch to an owner-created remote. Gated by an approval token.

    Without a valid approval this writes the repository request and raises
    ApprovalRequired before any Git network operation. After an approved push to
    GitHub the project is recorded in the private registry.
    """
    app_dir = pathlib.Path(app_dir)
    spec = json.loads((app_dir / ".gaie/spec.json").read_text(encoding="utf-8"))
    try:
        approval = check_approval(grant, token, now=now)
    except ApprovalRequired:
        if not (app_dir / REQUEST_FILE).is_file():
            request_repository(app_dir, spec=spec)
        raise
    url, kind = _remote(remote, spec["slug"])
    if _git(app_dir, "status", "--porcelain").stdout.strip():
        raise BuildError("the application working tree is not clean; commit before publishing")
    env = _git_env()
    if kind == "github":  # the owner's environment supplies credentials; the engine never handles them
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    pushed = _git(app_dir, "push", "--porcelain", url, "refs/heads/main:refs/heads/main", env=env)
    head = _git(app_dir, "rev-parse", "HEAD").stdout.strip()
    registered = register_project(app_dir, url, environ=environ, apply=True) if kind == "github" else None
    return {"status": "pushed", "remote_kind": kind, "remote": url if kind == "github" else "<local bare repository>",
            "commit": head, "approved_by": approval["approved_by"], "side_effect": "external-write",
            "registered": registered, "output": pushed.stdout.strip()[-500:]}


# ---------------------------------------------------------------------------
# the build pipeline

def plan(spec, *, allow_open_questions=False):
    """Validate and describe what a build would produce; writes nothing."""
    spec = validate_spec(spec, allow_open_questions=allow_open_questions)
    requirements_engine = _requirements()
    if not requirements_engine.is_ready(spec):
        return {"project": spec.get("slug"), "ready": False,
                "open_questions": [q["id"] for q in spec["open_questions"]]}
    model = derive_model(spec)
    checks, unmapped = compile_acceptance(spec, model)
    rows, coverage = requirements(spec, model, checks, unmapped)
    request = {"schema_version": 1, "project": spec["slug"], "source_revision": "0" * 40,
               "requirements": rows, "targets": TARGETS}
    stages = [stage["id"] for stage in factory.plan_factory(request)["stages"]]
    python_ids, e2e_ids = expected_tests(model, spec["locales"], checks)
    return {"project": spec["slug"], "ready": True, "entities": [e["name"] for e in model["entities"]],
            "collections": [f"/api/{e['collection']}" for e in model["entities"]],
            "factory_stages": stages, "expected_tests": {"python": len(python_ids), "e2e": len(e2e_ids)},
            "acceptance": {"criteria": len(coverage), "executable": len(checks)},
            "unmapped_criteria": {aid: row["reason"] for aid, row in sorted(coverage.items()) if not row["evidence"]},
            "rules": model["rules"], "scoping": model["auth"]["scoping"],
            "translation_gaps": model["translation_gaps"], "open_items": open_items_for(spec, model)}


def build(spec, *, out_dir, hub_revision, now=None, workspace=None, environ=None, registry=None,
          verify=True, e2e=True):
    """Generate, commit, test and evidence an independent application. Returns a build report."""
    moment = _now(now)
    spec = validate_spec(spec)
    hub = _hub_revision(hub_revision)
    if workspace is None:
        workspace = default_workspace(environ)
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    target, workspace = check_target(out_dir, workspace)
    existing = find_existing(spec, workspace=workspace, environ=environ, registry=registry)
    if existing["matches"]:
        raise DuplicateProject(f"project {spec['slug']!r} already exists; route to MASTER_UPGRADE", existing["matches"])
    model = derive_model(spec)
    checks, unmapped = compile_acceptance(spec, model)
    rows, coverage_map = requirements(spec, model, checks, unmapped)
    files, link = render(spec, model, checks, hub=hub, moment=moment)
    created = not target.exists()
    pipeline = [{"step": "spec", "status": "passed", "validator": "engineering_os.requirements.validate_spec"},
                {"step": "registry-check", "status": "passed", "sources": existing["sources"]}]
    try:
        _write_files(target, files)
        pipeline.append({"step": "scaffold", "status": "passed", "files": len(files)})
        _git(target, "init", "--quiet", "--template=", "-b", "main")
        _git(target, "add", "--all")
        message = (f"feat: initial {spec['slug']} application\n\nGenerated by the GAIE Master Build Engine (L16) from "
                   f"spec sha256 {link['spec_sha256'][:16]} at hub revision {hub['revision'][:12]}.\n")
        _git(target, "commit", "--quiet", "-m", message, moment=moment)
        source_commit = _git(target, "rev-parse", "HEAD").stdout.strip()
        git_clean = not _git(target, "status", "--porcelain").stdout.strip()
        pipeline.append({"step": "git-init", "status": "passed", "commit": source_commit})
    except BaseException:
        if created and target.exists():
            shutil.rmtree(target)
        elif target.exists():
            for child in target.iterdir():
                shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
        raise
    statics = static_checks(target, files, model, spec, hub)
    suites = run_suites(target, e2e=e2e) if verify else {
        "python": {"status": "not-run", "reason": "verify=False"}, "e2e": {"status": "not-run", "reason": "verify=False"}}
    pipeline.append({"step": "static-checks", "status": "passed" if all(v["status"] == "passed" for v in statics.values())
                     else "failed", "checks": {k: v["status"] for k, v in statics.items()}})
    states = {suites["python"]["status"], suites["e2e"]["status"]}
    pipeline.append({"step": "tests", "status": "passed" if states == {"passed"} else "failed" if "failed" in states
                     else "not-run", "python": suites["python"].get("summary"), "e2e": suites["e2e"].get("status")})
    catalog = expected_tests(model, spec["locales"], checks)
    matrix = coverage_matrix(coverage_map, statics, suites, catalog)
    repository = request_repository(target, spec=spec, moment=moment)
    ctx = {"spec": spec, "model": model, "files": files, "statics": statics, "suites": suites, "catalog": catalog,
           "coverage": matrix, "coverage_map": coverage_map, "requirements": rows, "checks": checks,
           "source_commit": source_commit, "git_clean": git_clean, "repository_request": repository,
           "open_items": open_items_for(spec, model)}
    factory_plan, receipts, evaluation = write_factory_evidence(target, ctx)
    pipeline.append({"step": "factory", "status": "passed" if evaluation["delivery_review_ready"] else "blocked",
                     "verified": evaluation["verified_count"], "stages": len(factory_plan["stages"])})
    _git(target, "add", "--", FACTORY_DIR, REQUEST_FILE)
    _git(target, "commit", "--quiet", "-m", f"chore(gaie): factory evidence for {source_commit[:12]}\n", moment=moment)
    evidence_commit = _git(target, "rev-parse", "HEAD").stdout.strip()
    leftovers = [line[3:] for line in _git(target, "status", "--porcelain", "--untracked-files=all").stdout.split("\n")
                 if line.strip()]
    pipeline.append({"step": "repository", "status": "awaiting-approval", "request": REQUEST_FILE})
    return {
        "schema": REPORT_SCHEMA, "ok": bool(evaluation["delivery_review_ready"]), "project": spec["slug"],
        "out_dir": str(target), "source_commit": source_commit, "evidence_commit": evidence_commit,
        "hub_revision": hub["revision"], "pin_on_main": hub["on_main"], "reproducible_from_pin": link["reproducible_from_pin"],
        "untracked_after_build": leftovers, "pipeline": pipeline,
        "static_checks": {k: v["status"] for k, v in statics.items()},
        "static_problems": {k: v["detail"]["problems"] for k, v in statics.items() if v["status"] != "passed"},
        "tests": {name: {k: v for k, v in suite.items() if k != "tests"} for name, suite in suites.items()},
        "acceptance": {"criteria": len(matrix), "executable": len(checks), "unmapped": unmapped},
        "rules": model["rules"], "coverage": matrix, "factory": evaluation, "open_items": ctx["open_items"],
        "repository": {"status": repository["status"], "request": REQUEST_FILE, "visibility": "private"},
        "provider_calls": 0, "network": "none outside loopback (generated tests bind 127.0.0.1 in child processes)",
        "deployment_authorized": False,
        "evidence_kind": {"deterministic": ["spec validation", "rendering", "static checks", "factory receipts"],
                          "executed": ["generated unit/API/acceptance tests", "Playwright E2E"] if verify else [],
                          "model_reasoning": [], "simulated": []},
    }


# ---------------------------------------------------------------------------
# control-plane facade

ENGINE_RECORD = {
    "id": "master-build", "layer": "L16",
    "title": {"en": "Master Build Engine", "ar": "محرك البناء الرئيسي"},
    "entrypoint": "engineering_os.build_engine:engine",
    "health": "engineering_os.build_engine:health",
    "actions": {
        "plan-app": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"],
                     "summary": "Validate a gaie.spec/1 and describe the application, tests and factory stages without writing."},
        "build": {"side_effect": "workspace-write",
                  "permissions": ["read:repo", "read:registry", "write:workspace", "exec:sandbox", "secrets:none"],
                  "summary": "Generate, locally commit, test and evidence an independent application in a workspace."},
        "evaluate-app": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"],
                         "summary": "Re-validate a built application's factory receipts against its bytes."},
        "request-repository": {"side_effect": "workspace-write", "permissions": ["write:workspace", "secrets:none"],
                               "summary": "Write repository-request.json for the owner; never contacts GitHub."},
        "publish": {"side_effect": "external-write", "permissions": ["ext:github", "write:state", "secrets:none"],
                    "summary": "Push the app to an owner-created private remote and register it; needs an owner approval token."},
    },
    "supersedes": [],
}


def health():
    """Template integrity and required hub files, without side effects."""
    try:
        manifest, templates = _template_files()
        for path in (PLAYWRIGHT_POLICY, PLAYWRIGHT_LOCK, ROOT / "hublink.py", ROOT / "scripts" / "security_scan.py"):
            if not path.is_file():
                return {"ok": False, "detail": f"missing {path.relative_to(ROOT)}"}
        _requirements()
        return {"ok": True, "detail": f"templates/app-stdlib {manifest['version']}: {len(templates)} files"}
    except (BuildError, OSError, ValueError, ImportError) as error:
        return {"ok": False, "detail": str(error)}


def engine(action, payload, ctx=None):
    """Contract entrypoint `(action, payload, ctx) -> dict`; payload is data, never instructions.

    Action names are distinct from the factory actions (spec, plan, evaluate) that
    engineering_os.adapters.master_build already serves, so both can share one record.
    """
    if action not in ENGINE_RECORD["actions"]:
        raise BuildError(f"unknown action {action!r}")
    if not isinstance(payload, dict):
        raise BuildError("payload must be an object")
    if action == "plan-app":
        return plan(payload["spec"], allow_open_questions=bool(payload.get("allow_open_questions")))
    if action == "build":
        allowed = {"spec", "out_dir", "hub_revision", "now", "workspace", "verify", "e2e"}
        if set(payload) - allowed:
            raise BuildError(f"unknown build payload keys {sorted(set(payload) - allowed)}")
        return build(payload["spec"], out_dir=payload["out_dir"], hub_revision=payload["hub_revision"],
                     now=payload.get("now"), workspace=payload.get("workspace"),
                     verify=payload.get("verify", True), e2e=payload.get("e2e", True))
    if action == "evaluate-app":
        return evaluate(payload["app_dir"])
    if action == "request-repository":
        return request_repository(payload["app_dir"])
    return publish(payload["app_dir"], remote=payload.get("remote"), grant=payload.get("grant"),
                   token=payload.get("token"), now=payload.get("now"))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m engineering_os.build_engine", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("plan")
    one.add_argument("--spec", required=True)
    one = commands.add_parser("build")
    one.add_argument("--spec", required=True)
    one.add_argument("--out", required=True)
    one.add_argument("--hub-revision", required=True)
    one.add_argument("--workspace")
    one.add_argument("--now")
    one.add_argument("--no-verify", action="store_true")
    one.add_argument("--no-e2e", action="store_true")
    one = commands.add_parser("evaluate")
    one.add_argument("app")
    one = commands.add_parser("publish")
    one.add_argument("app")
    one.add_argument("--remote", required=True)
    one.add_argument("--grant")
    one.add_argument("--token-file")
    args = parser.parse_args(argv)
    try:
        if args.command in ("plan", "build"):
            spec = json.loads(pathlib.Path(args.spec).read_text(encoding="utf-8"))
        if args.command == "plan":
            result = plan(spec)
        elif args.command == "build":
            result = build(spec, out_dir=args.out, hub_revision=args.hub_revision, now=args.now,
                           workspace=args.workspace, verify=not args.no_verify, e2e=not args.no_e2e)
        elif args.command == "evaluate":
            result = evaluate(args.app)
        else:
            grant = json.loads(pathlib.Path(args.grant).read_text(encoding="utf-8")) if args.grant else None
            token = pathlib.Path(args.token_file).read_text(encoding="utf-8").strip() if args.token_file else None
            result = publish(args.app, remote=args.remote, grant=grant, token=token)
    except BuildError as error:
        print(json.dumps({"ok": False, "error": type(error).__name__, "detail": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
