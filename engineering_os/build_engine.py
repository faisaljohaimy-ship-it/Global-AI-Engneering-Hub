"""GAIE Master Build Engine (layer L16): build an independent application from gaie.spec/1.

`build(spec, out_dir=..., hub_revision=...)` validates a requirement specification,
refuses duplicates and unsafe targets, renders `templates/app-stdlib` into an isolated
workspace, initializes the application as its own Git repository, runs the generated
unit, API and browser tests, and writes factory receipts that
`engineering_os.factory.evaluate_factory` revalidates.

Boundaries (see docs/specs/gaie-20-layers/BUILD_ENGINE.md):
- Deterministic code only; no model or provider is called and nothing leaves the
  machine. Generated tests use loopback sockets in child processes.
- The generated application never imports the hub; `.gaie/link.json` records which
  hub revision, templates and capabilities produced it.
- Creating or pushing to a remote repository is `external-write`: without an owner
  approval token the engine only writes `.gaie/repository-request.json`.
- Check reports are produced by this engine's own deterministic evaluators. They are
  evidence of executed checks, not an independent review; `verify()` re-runs them.
"""

import argparse
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
FIELD_TYPES = ("text", "int", "number", "bool", "date", "datetime", "enum", "email")
RELATION_KINDS = ("many-to-one", "one-to-many", "many-to-many")
LOCALES = ("ar", "en")
TARGETS = ["api", "backend", "database", "web"]
SPEC_KEYS = frozenset({"schema", "source", "title", "slug", "product_type", "domain", "locales", "roles", "entities",
                       "relations", "features", "nfr", "ai", "integrations", "constraints", "open_questions"})
FIELD_KEYS = frozenset({"name", "type", "required", "max", "min", "values", "default", "label"})
RESERVED_FIELDS = frozenset({"id", "created_at", "updated_at"})
RESERVED_COLLECTIONS = frozenset({"health", "schema"})
MAX_SPEC_BYTES = 256 * 1024
MAX_TEXT = 10000
MAX_BODY_BYTES = 64 * 1024
SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
ENTITY_NAME = re.compile(r"[A-Z][A-Za-z0-9]{0,39}")
FIELD_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
ENUM_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
FEATURE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
PERMISSION = re.compile(r"[a-z*][a-z0-9:*_-]{0,63}")
REVISION = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"[a-f0-9]{64}")
MARKER = re.compile(r"@@([A-Z_]+)@@")
GITHUB_REMOTE = re.compile(r"https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?")
REVIEWER = "master-build-checks"
GIT_NAME = "GAIE Master Build Engine"
GIT_EMAIL = "master-build@gaie.invalid"
REQUEST_FILE = ".gaie/repository-request.json"
FACTORY_DIR = ".gaie/factory"

VALIDATION_CHECKS = ("required", "types", "max_length", "enum", "unknown_field", "defaults")
VALIDATION_GLOBAL = ("test_text_rejects_control_characters", "test_dates_are_strict",
                     "test_numbers_are_finite_and_not_booleans")
MIGRATION_TESTS = ("test_up_creates_schema", "test_down_removes_schema", "test_up_is_idempotent")
API_OPS = ("create", "list", "get", "update", "delete", "validation", "not_found")
API_GLOBAL = ("test_health", "test_security_headers", "test_cross_origin_write_refused",
              "test_wrong_content_type_refused", "test_oversized_body_refused", "test_invalid_json_refused",
              "test_unknown_collection_404", "test_method_not_allowed", "test_bad_query_refused",
              "test_static_traversal_refused", "test_sql_injection_is_inert", "test_list_latency_budget",
              "test_seed_is_synthetic")
E2E_GLOBAL = ("e2e:labels", "e2e:keyboard", "e2e:headers", "e2e:csp", "e2e:no-external-requests")
VALIDATION_ID = "tests.test_validation.ValidationTests."
MIGRATION_ID = "tests.test_migrations.MigrationTests."
API_ID = "tests.test_api.ApiTests."


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


def _text(value, field, limit=200):
    _need(isinstance(value, str) and value.strip() and len(value) <= limit, f"{field}: text of 1-{limit} characters")
    _need(not any(ord(char) < 32 or ord(char) == 127 for char in value), f"{field}: control characters refused")
    _need(not SECRET.search(value), f"{field}: credential-shaped text refused")
    return value


def _bilingual(value, field, limit=200):
    _need(isinstance(value, dict) and set(value) == {"ar", "en"}, f"{field}: needs exactly ar and en")
    for lang in ("ar", "en"):
        _text(value[lang], f"{field}.{lang}", limit)
    return value


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


# ---------------------------------------------------------------------------
# gaie.spec/1 validation

def _validate_field(entity, field):
    where = f"entities.{entity}.fields"
    _need(isinstance(field, dict) and {"name", "type", "required"} <= set(field) <= FIELD_KEYS,
          f"{where}: each field needs name, type, required (allowed: {sorted(FIELD_KEYS)})")
    name = field["name"]
    _need(isinstance(name, str) and FIELD_NAME.fullmatch(name), f"{where}: field name {name!r} must be snake_case")
    where = f"entities.{entity}.{name}"
    _need(name not in RESERVED_FIELDS, f"{where}: reserved field name")
    _need(field["type"] in FIELD_TYPES, f"{where}: type must be one of {list(FIELD_TYPES)}")
    _need(isinstance(field["required"], bool), f"{where}: required must be true or false")
    kind = field["type"]
    for bound in ("max", "min"):
        if bound in field:
            value = field[bound]
            _need(not isinstance(value, bool) and isinstance(value, (int, float)), f"{where}: {bound} must be a number")
            if kind in ("text", "email"):
                _need(bound == "max" and isinstance(value, int) and 1 <= value <= MAX_TEXT,
                      f"{where}: text max must be an integer 1-{MAX_TEXT} (min is not supported)")
            else:
                _need(kind in ("int", "number"), f"{where}: {bound} only applies to text, int and number")
                _need(abs(value) <= 2 ** 53 - 1 and (kind == "number" or isinstance(value, int)),
                      f"{where}: {bound} out of range")
    if "min" in field and "max" in field:
        _need(field["min"] <= field["max"], f"{where}: min > max")
    if kind == "enum":
        values = field.get("values")
        _need(isinstance(values, list) and 1 <= len(values) <= 50 and len(set(values)) == len(values)
              and all(isinstance(v, str) and ENUM_VALUE.fullmatch(v) for v in values),
              f"{where}: enum needs 1-50 unique values matching {ENUM_VALUE.pattern}")
    else:
        _need("values" not in field, f"{where}: values only apply to enum fields")
    if "default" in field:
        default = field["default"]
        valid = {
            "text": isinstance(default, str) and len(default) <= field.get("max", MAX_TEXT),
            "email": False,
            "int": isinstance(default, int) and not isinstance(default, bool),
            "number": isinstance(default, (int, float)) and not isinstance(default, bool),
            "bool": isinstance(default, bool),
            "date": isinstance(default, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", default)),
            "datetime": False,
            "enum": default in field.get("values", []),
        }[kind]
        if valid and kind in ("int", "number"):
            valid = field.get("min", default) <= default <= field.get("max", default)
        _need(valid, f"{where}: default does not match the field type and limits")
        if isinstance(default, str):
            _need(not SECRET.search(default) and not any(ord(c) < 32 for c in default), f"{where}: unsafe default")
    if "label" in field:
        _bilingual(field["label"], f"{where}.label", 80)
    return field


def validate_spec(spec, *, allow_open_questions=False):
    """Validate a gaie.spec/1 document; return a deep copy or raise SpecError."""
    _need(isinstance(spec, dict), "spec: JSON object required")
    try:
        size = len(contracts.canonical(spec).encode("utf-8"))
    except (TypeError, ValueError):
        raise SpecError("spec: must be plain JSON") from None
    _need(size <= MAX_SPEC_BYTES, f"spec: larger than {MAX_SPEC_BYTES} bytes")
    missing, extra = SPEC_KEYS - set(spec), set(spec) - SPEC_KEYS
    _need(not missing and not extra, f"spec: missing {sorted(missing)} / unknown {sorted(extra)}")
    _need(spec["schema"] == SPEC_SCHEMA, f"spec.schema must be {SPEC_SCHEMA}")
    source = spec["source"]
    _need(isinstance(source, dict) and set(source) == {"command", "language", "sha256"},
          "spec.source: needs exactly command, language, sha256")
    _text(source["command"], "spec.source.command", 4000)
    _need(source["language"] in LOCALES, "spec.source.language must be ar or en")
    _need(isinstance(source["sha256"], str) and DIGEST.fullmatch(source["sha256"]), "spec.source.sha256: 64 hex")
    _bilingual(spec["title"], "spec.title")
    _need(isinstance(spec["slug"], str) and len(spec["slug"]) <= 64 and SLUG.fullmatch(spec["slug"]),
          "spec.slug: kebab-case, at most 64 characters")
    _need(isinstance(spec["domain"], str) and len(spec["domain"]) <= 64 and SLUG.fullmatch(spec["domain"]),
          "spec.domain: kebab-case")
    _need(spec["product_type"] == "web-app",
          f"spec.product_type {spec['product_type']!r} is not supported by templates/app-stdlib (web-app only)",
          UnsupportedSpec)
    locales = spec["locales"]
    _need(isinstance(locales, list) and locales and len(set(locales)) == len(locales) and set(locales) <= set(LOCALES),
          "spec.locales: non-empty list of unique values from ar, en")
    roles = spec["roles"]
    _need(isinstance(roles, list) and len(roles) <= 20, "spec.roles: list of at most 20")
    role_ids = set()
    for role in roles:
        _need(isinstance(role, dict) and set(role) == {"id", "permissions"}, "spec.roles: id and permissions")
        _need(isinstance(role["id"], str) and SLUG.fullmatch(role["id"]) and role["id"] not in role_ids,
              "spec.roles: unique kebab-case ids")
        role_ids.add(role["id"])
        _need(isinstance(role["permissions"], list) and len(role["permissions"]) <= 20
              and all(isinstance(p, str) and PERMISSION.fullmatch(p) for p in role["permissions"]),
              f"spec.roles.{role['id']}: permissions")
    entities = spec["entities"]
    _need(isinstance(entities, list) and 1 <= len(entities) <= 30, "spec.entities: 1-30 entities")
    names = set()
    for entity in entities:
        _need(isinstance(entity, dict) and {"name", "fields"} <= set(entity) <= {"name", "fields", "label"},
              "spec.entities: each needs name and fields (optional label)")
        name = entity["name"]
        _need(isinstance(name, str) and ENTITY_NAME.fullmatch(name), f"spec.entities: name {name!r} must be PascalCase")
        _need(name.lower() not in names, f"spec.entities: duplicate entity {name}")
        names.add(name.lower())
        table = _snake(name)
        _need(table != "schema_migrations" and not table.startswith("sqlite_"), f"{name}: reserved table name")
        _need(_plural(table).replace("_", "-") not in RESERVED_COLLECTIONS, f"{name}: reserved collection name")
        fields = entity["fields"]
        _need(isinstance(fields, list) and 1 <= len(fields) <= 40, f"{name}: 1-40 fields")
        for field in fields:
            _validate_field(name, field)
        _need(len({f["name"] for f in fields}) == len(fields), f"{name}: duplicate field names")
        if "label" in entity:
            label = entity["label"]
            _need(isinstance(label, dict) and set(label) == {"ar", "en"}
                  and all(isinstance(label[k], list) and len(label[k]) == 2 for k in label),
                  f"{name}.label: {{ar: [singular, plural], en: [singular, plural]}}")
            for lang in ("ar", "en"):
                for text in label[lang]:
                    _text(text, f"{name}.label.{lang}", 80)
    by_name = {entity["name"]: entity for entity in entities}
    relations = spec["relations"]
    _need(isinstance(relations, list) and len(relations) <= 60, "spec.relations: list of at most 60")
    seen_pairs = set()
    for relation in relations:
        _need(isinstance(relation, dict) and set(relation) == {"from", "to", "kind", "required"},
              "spec.relations: each needs exactly from, to, kind, required")
        _need(relation["from"] in by_name and relation["to"] in by_name,
              f"spec.relations: unknown entity in {relation['from']!r} -> {relation['to']!r}")
        _need(relation["kind"] in RELATION_KINDS, f"spec.relations: kind must be one of {list(RELATION_KINDS)}")
        _need(isinstance(relation["required"], bool), "spec.relations: required must be true or false")
        if relation["kind"] == "many-to-many":
            _need(not relation["required"], "spec.relations: a required many-to-many relation is not supported",
                  UnsupportedSpec)
            pair = ("m2m", relation["from"], relation["to"])
        else:
            child, parent = ((relation["from"], relation["to"]) if relation["kind"] == "many-to-one"
                             else (relation["to"], relation["from"]))
            _need(not (child == parent and relation["required"]),
                  f"spec.relations: a required self-relation on {child} can never be satisfied")
            pair = ("ref", child, parent)
        _need(pair not in seen_pairs, f"spec.relations: two relations between {pair[1]} and {pair[2]} are not supported",
              UnsupportedSpec)
        seen_pairs.add(pair)
    features = spec["features"]
    _need(isinstance(features, list) and 1 <= len(features) <= 100, "spec.features: 1-100 features")
    feature_ids = set()
    for feature in features:
        _need(isinstance(feature, dict) and set(feature) == {"id", "title", "acceptance"},
              "spec.features: each needs exactly id, title, acceptance")
        fid = feature["id"]
        _need(isinstance(fid, str) and FEATURE_ID.fullmatch(fid) and fid.lower() not in feature_ids
              and not fid.lower().startswith("nfr"), f"spec.features: id {fid!r} invalid or duplicate")
        feature_ids.add(fid.lower())
        _bilingual(feature["title"], f"spec.features.{fid}.title")
        acceptance = feature["acceptance"]
        _need(isinstance(acceptance, list) and 1 <= len(acceptance) <= 50,
              f"spec.features.{fid}: 1-50 acceptance criteria")
        for index, item in enumerate(acceptance):
            _text(item, f"spec.features.{fid}.acceptance[{index}]", 500)
    nfr = spec["nfr"]
    _need(isinstance(nfr, dict) and len(nfr) <= 12, "spec.nfr: object with at most 12 categories")
    for key, items in nfr.items():
        _need(isinstance(key, str) and re.fullmatch(r"[a-z][a-z0-9]{0,23}", key), f"spec.nfr: category {key!r}")
        _need(isinstance(items, list) and len(items) <= 20, f"spec.nfr.{key}: list of at most 20")
        for index, item in enumerate(items):
            _text(item, f"spec.nfr.{key}[{index}]", 300)
    ai = spec["ai"]
    _need(isinstance(ai, dict) and set(ai) == {"needed", "use_cases"} and isinstance(ai["needed"], bool)
          and isinstance(ai["use_cases"], list), "spec.ai: needed (bool) and use_cases (list)")
    _need(not ai["needed"] and not ai["use_cases"],
          "spec.ai: AI features need an AI target, evaluation set and owner approval; app-stdlib builds none",
          UnsupportedSpec)
    _need(isinstance(spec["integrations"], list), "spec.integrations: list")
    _need(not spec["integrations"], "spec.integrations: external integrations are not built by app-stdlib",
          UnsupportedSpec)
    constraints = spec["constraints"]
    _need(isinstance(constraints, dict) and set(constraints) == {"runtime", "database", "no_paid_services"},
          "spec.constraints: needs exactly runtime, database, no_paid_services")
    _need(constraints["runtime"] == "python3-stdlib" and constraints["database"] == "sqlite",
          "spec.constraints: app-stdlib builds runtime python3-stdlib with database sqlite only", UnsupportedSpec)
    _need(constraints["no_paid_services"] is True,
          "spec.constraints.no_paid_services must be true: paid services need separate owner approval")
    questions = spec["open_questions"]
    _need(isinstance(questions, list) and len(questions) <= 50, "spec.open_questions: list")
    for question in questions:
        text = question if isinstance(question, str) else json.dumps(question, ensure_ascii=False)
        _text(text, "spec.open_questions[]", 1000)
    if questions and not allow_open_questions:
        raise OpenQuestions(f"spec has {len(questions)} open question(s); ask the owner before building")
    return copy.deepcopy(spec)


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
            for name in ready[:1]:
                result.append(name)
                del pending[name]
                for deps in pending.values():
                    deps.discard(name)
        if not pending:
            return result
    raise SpecError("spec.relations: required many-to-one relations form a cycle; no record could ever be created")


def derive_model(spec):
    """Tables, collections, references, links, labels and ordering for the application."""
    glossary = _load_template_data("glossary.json")
    entities = spec["entities"]
    by_name = {entity["name"]: entity for entity in entities}
    references, links = {name: [] for name in by_name}, {name: [] for name in by_name}
    edges_all, edges_required = [], []
    for relation in spec["relations"]:
        if relation["kind"] == "many-to-many":
            source, target = relation["from"], relation["to"]
            links[source].append({"field": _snake(target) + "_ids", "entity": target, "table": _snake(target),
                                  "link_table": f"{_snake(source)}_{_snake(target)}_link"})
            continue
        child, parent = ((relation["from"], relation["to"]) if relation["kind"] == "many-to-one"
                         else (relation["to"], relation["from"]))
        references[child].append({"field": _snake(parent) + "_id", "entity": parent, "table": _snake(parent),
                                  "required": relation["required"], "relation": "many-to-one"})
        edges_all.append((child, parent))
        if relation["required"]:
            edges_required.append((child, parent))
    order = _topological(entities, edges_all, edges_required)
    tables = set()
    model_entities, labels, gaps = [], {lang: {"entities": {}, "fields": {}, "values": {}} for lang in LOCALES}, []
    for name in order:
        entity = by_name[name]
        table = _snake(name)
        collection = _plural(table).replace("_", "-")
        fields = [{key: value for key, value in field.items() if key != "label"} for field in entity["fields"]]
        field_names = {field["name"] for field in fields}
        for item in references[name] + links[name]:
            _need(item["field"] not in field_names, f"{name}.{item['field']}: field name collides with a relation column")
            field_names.add(item["field"])
        text_fields = [field for field in fields if field["type"] == "text"]
        required_text = [field for field in text_fields if field["required"]]
        label_field = (required_text or text_fields or [None])[0]
        model_entities.append({
            "name": name, "table": table, "collection": collection,
            "label_field": label_field["name"] if label_field else None,
            "fields": fields, "references": references[name], "links": links[name],
        })
        tables.add(table)
        tables.update(link["link_table"] for link in links[name])
        # labels
        known = glossary["entities"].get(table)
        for lang in LOCALES:
            if "label" in entity:
                singular, plural = entity["label"][lang]
            elif known:
                singular, plural = known[lang]
            else:
                singular, plural = _humanize(name), _plural(_humanize(name))
                if lang == "ar":
                    gaps.append(f"entity {name}")
            labels[lang]["entities"][name] = {"singular": singular, "plural": plural}
    _need(len(tables) == len(model_entities) + sum(len(e["links"]) for e in model_entities),
          "spec: table names collide (entity vs link table)")
    for item in model_entities:
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
                names[ref["field"]] = labels[lang]["entities"][ref["entity"]]["singular"]
            for link in item["links"]:
                names[link["field"]] = labels[lang]["entities"][link["entity"]]["plural"]
            _need(len(set(names.values())) == len(names),
                  f"{item['name']}: two fields have the same {lang} label; add explicit labels", UnsupportedSpec)
            labels[lang]["fields"][item["name"]] = names
            labels[lang]["values"][item["name"]] = values
    p95 = 200
    for text in spec["nfr"].get("performance", []):
        match = re.search(r"p95[^0-9<]*<\s*(\d{1,5})\s*ms", text, re.I)
        if match:
            p95 = int(match.group(1))
    return {"entities": model_entities, "labels": labels, "translation_gaps": sorted(set(gaps)), "p95_ms": p95}


# ---------------------------------------------------------------------------
# requirements, test catalog and acceptance coverage

def expected_tests(model, locales):
    """Test ids the generated suites must report (python unittest ids and E2E case ids)."""
    python, e2e = [], []
    for entity in model["entities"]:
        table = entity["table"]
        python += [f"{VALIDATION_ID}test_{check}_{table}" for check in VALIDATION_CHECKS]
        python += [f"{API_ID}test_{op}_{table}" for op in API_OPS]
        for ref in entity["references"]:
            python += [f"{API_ID}test_reference_{table}_{ref['field']}_missing",
                       f"{API_ID}test_reference_{table}_{ref['field']}_delete_parent"]
        for link in entity["links"]:
            python.append(f"{API_ID}test_links_{table}_{link['field']}")
    python += [VALIDATION_ID + name for name in VALIDATION_GLOBAL]
    python += [MIGRATION_ID + name for name in MIGRATION_TESTS]
    python += [API_ID + name for name in API_GLOBAL]
    for locale in locales:
        e2e.append(f"e2e:{locale}:language")
        for entity in model["entities"]:
            e2e += [f"e2e:{locale}:{entity['table']}:{op}" for op in ("create", "update", "delete")]
    e2e += list(E2E_GLOBAL)
    return sorted(python), sorted(e2e)


_EN = lambda *words: re.compile(r"\b(?:" + "|".join(words) + r")\b", re.I)  # noqa: E731
OPS = {
    "create": (_EN("post", "create", "creates", "add", "adds", "201", "new", "insert"),
               ("إنشاء", "انشاء", "إضافة", "اضافة", "أنشئ", "ينشئ", "يضيف", "جديد")),
    "list": (_EN("list", "lists", "listing", "browse", "index", "view", "views", "shows", "show", "display", "displays"),
             ("قائمة", "عرض", "يعرض", "استعراض", "تظهر", "يظهر")),
    "get": (_EN("detail", "details", "retrieve", "retrieves", "fetch", "fetches", "one record"), ("تفاصيل",)),
    "update": (_EN("put", "patch", "update", "updates", "edit", "edits", "modify", "modifies", "rename", "change", "changes"),
               ("تعديل", "تحديث", "يعدل", "يحدث")),
    "delete": (_EN("delete", "deletes", "remove", "removes", "204"), ("حذف", "إزالة", "ازالة", "يحذف")),
    "validation": (re.compile(r"\b(?:400|invalid|validat\w*|reject\w*|required field\w*|field errors?)\b", re.I),
                   ("غير صالح", "التحقق", "مرفوض", "تحقق")),
    "not_found": (re.compile(r"\b(?:404|not found|missing record)\b", re.I), ("غير موجود",)),
    "relation": (re.compile(r"\b(?:409|conflict\w*|relation\w*|belongs?|linked|link|assign\w*|parent|dependent\w*)\b", re.I),
                 ("مرتبط", "تنتمي", "ينتمي", "ربط", "تابع")),
}
UI_WORDS = (re.compile(r"\b(?:ui|interface|page|screen|browser|form|forms|button|frontend|through the ui)\b", re.I),
            ("واجهة", "الواجهة", "صفحة", "نموذج", "شاشة", "متصفح"))
LOCALE_WORDS = {
    "ar": (re.compile(r"\b(?:arabic|rtl|right-to-left|ar)\b", re.I), ("عربي", "العربية", "عربية")),
    "en": (re.compile(r"\b(?:english|ltr|left-to-right|en)\b", re.I), ("إنجليزي", "الإنجليزية", "انجليزي", "إنكليزي")),
}
BILINGUAL = (re.compile(r"\b(?:bilingual|i18n|language|languages|locale|locales|translated)\b", re.I),
             ("ثنائي", "لغتين", "اللغة", "اللغتين"))
NFR_RULES = (
    ((re.compile(r"\bsecrets?\b|credential", re.I), ("أسرار", "سر")), ["static:security:secrets"]),
    ((re.compile(r"parameteri[sz]ed|sql injection|prepared statement", re.I), ("حقن",)), [API_ID + "test_sql_injection_is_inert"]),
    ((re.compile(r"security headers?|\bcsp\b|content-security|frame-ancestors|nosniff|clickjacking", re.I), ()),
     [API_ID + "test_security_headers", "e2e:headers", "e2e:csp"]),
    ((re.compile(r"csrf|cross-origin|same-origin|cross-site", re.I), ()), [API_ID + "test_cross_origin_write_refused"]),
    ((re.compile(r"\bp95\b|latency|response time", re.I), ("زمن الاستجابة",)), [API_ID + "test_list_latency_budget"]),
    ((re.compile(r"keyboard", re.I), ("لوحة المفاتيح",)), ["e2e:keyboard"]),
    ((re.compile(r"\blabels?\b|accessib\w*|screen reader|aria", re.I), ("تسميات", "إتاحة", "وصول")), ["e2e:labels"]),
    ((re.compile(r"size limit|payload|too large|\b413\b", re.I), ("حجم",)), [API_ID + "test_oversized_body_refused"]),
    ((re.compile(r"no network|offline|external request|\bcdn\b|third-party request", re.I), ()), ["e2e:no-external-requests"]),
    ((re.compile(r"synthetic|seed", re.I), ("تجريبي",)), [API_ID + "test_seed_is_synthetic"]),
    ((re.compile(r"migration|rollback|schema", re.I), ("ترحيل",)),
     [MIGRATION_ID + name for name in MIGRATION_TESTS] + ["static:database:migration"]),
    ((re.compile(r"input validation|validate input", re.I), ("التحقق من المدخلات",)), ["@validation"]),
)


def _hit(rule, text):
    pattern, arabic = rule
    return bool(pattern.search(text)) or any(word in text for word in arabic)


def _mentioned(model, text):
    found = []
    lowered = text.casefold()
    for entity in model["entities"]:
        words = {entity["name"].lower(), entity["table"].replace("_", " "), entity["collection"].replace("-", " "),
                 _plural(entity["name"].lower())}
        names = [model["labels"][lang]["entities"][entity["name"]] for lang in LOCALES]
        arabic = {names[0]["singular"], names[0]["plural"]}
        arabic |= {word[2:] for word in arabic if word.startswith("ال") and len(word) > 3}
        if (f"/api/{entity['collection']}" in lowered
                or re.search(r"\b(?:" + "|".join(re.escape(w) for w in sorted(words)) + r")\b", lowered)
                or any(word in text for word in arabic)):
            found.append(entity)
    return found


def map_criterion(model, locales, text, hint):
    """Evidence ids (generated tests, E2E cases, static checks) for one acceptance criterion."""
    entities = _mentioned(model, text) or hint
    evidence = set()
    for rule, ids in NFR_RULES:
        if _hit(rule, text):
            evidence.update(ids)
    ops = {op for op, rule in OPS.items() if _hit(rule, text)}
    named_locales = [loc for loc in locales if _hit(LOCALE_WORDS[loc], text)]
    ui = _hit(UI_WORDS, text) or bool(named_locales) or _hit(BILINGUAL, text)
    if "@validation" in evidence:
        evidence.discard("@validation")
        ops.add("validation")
        entities = entities or model["entities"]
    collection = re.search(r"/api/([a-z0-9-]+)(/(?:\{|:|\d)[^\s]*)?", text)
    if collection and collection.group(2) and "list" in ops and "update" not in ops and "delete" not in ops:
        ops.discard("list")
        ops.add("get")
    if not entities and ops:
        entities = model["entities"]
    if ui:
        targets = named_locales or list(locales)
        for loc in targets:
            evidence.add(f"e2e:{loc}:language")
            for entity in (entities if ops & {"create", "list", "update", "delete"} else []):
                for op in ops & {"create", "update", "delete", "list"}:
                    evidence.add(f"e2e:{loc}:{entity['table']}:{'create' if op == 'list' else op}")
        if ops & {"validation", "not_found", "relation", "get"}:
            ui = False
    if not ui:
        for entity in entities:
            table = entity["table"]
            for op in ops - {"relation"}:
                evidence.add(f"{API_ID}test_{op}_{table}")
                if op == "validation":
                    evidence.update(f"{VALIDATION_ID}test_{check}_{table}" for check in ("required", "types", "max_length"))
            if "relation" in ops:
                names = {item["name"] for item in entities}
                for ref in entity["references"]:
                    if len(entities) == 1 or ref["entity"] in names:
                        evidence.add(f"{API_ID}test_reference_{table}_{ref['field']}_missing")
                        evidence.add(f"{API_ID}test_reference_{table}_{ref['field']}_delete_parent")
                for link in entity["links"]:
                    if len(entities) == 1 or link["entity"] in names:
                        evidence.add(f"{API_ID}test_links_{table}_{link['field']}")
    return sorted(evidence)


def requirements(spec, model):
    """Factory requirements with acceptance ids, and the coverage map id -> (text, evidence)."""
    locales = spec["locales"]
    rows, coverage = [], {}
    for feature in spec["features"]:
        rid = feature["id"].lower()
        hint = _mentioned(model, feature["title"]["en"] + " " + feature["title"]["ar"])
        acceptance = []
        for index, text in enumerate(feature["acceptance"], 1):
            aid = f"{rid}-a{index}"
            acceptance.append(aid)
            coverage[aid] = {"requirement": rid, "text": text, "evidence": map_criterion(model, locales, text, hint)}
        rows.append({"id": rid, "summary": feature["title"]["en"], "acceptance": acceptance})
    for category, items in sorted(spec["nfr"].items()):
        if not items:
            continue
        rid = f"nfr-{category}"
        acceptance = []
        for index, text in enumerate(items, 1):
            aid = f"{rid}-a{index}"
            acceptance.append(aid)
            coverage[aid] = {"requirement": rid, "text": text, "evidence": map_criterion(model, locales, text, [])}
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
    _need(re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name or ""), f"unsafe identifier {name!r}", BuildError)
    return '"' + name + '"'


def migrations_sql(model):
    sql_type = {"text": "TEXT", "email": "TEXT", "date": "TEXT", "datetime": "TEXT", "enum": "TEXT",
                "int": "INTEGER", "bool": "INTEGER", "number": "REAL"}
    up = ["-- 0001_initial: generated from the specification by the GAIE Master Build Engine.",
          "-- Never edit an applied migration; add 0002_<name>.up.sql / .down.sql instead.", ""]
    for entity in model["entities"]:
        columns = ['  "id" INTEGER PRIMARY KEY AUTOINCREMENT']
        for field in entity["fields"]:
            name = _q(field["name"])
            parts = [f"  {name} {sql_type[field['type']]}"]
            if field["required"]:
                parts.append("NOT NULL")
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
        columns += ['  "created_at" TEXT NOT NULL', '  "updated_at" TEXT NOT NULL']
        up.append(f"CREATE TABLE {_q(entity['table'])} (\n" + ",\n".join(columns) + "\n);")
        for ref in entity["references"]:
            up.append(f"CREATE INDEX {_q(entity['table'] + '_' + ref['field'] + '_idx')} "
                      f"ON {_q(entity['table'])} ({_q(ref['field'])});")
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
    down += ["DELETE FROM schema_migrations WHERE version = '0001_initial';"]
    return "\n".join(up) + "\n", "\n".join(down) + "\n"


def seed_data(model, moment):
    labels = model["labels"]
    records = {}
    seeded = []
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
                    row[name] = f"synthetic.user{n}@example.invalid"[: field.get("max", 254)]
                elif kind == "enum":
                    row[name] = field["values"][index % len(field["values"])]
                elif kind in ("int", "number"):
                    value = n if kind == "int" else n * 1.5
                    row[name] = max(field.get("min", value), min(field.get("max", value), value))
                elif kind == "bool":
                    row[name] = index % 2 == 0
                elif kind == "date":
                    row[name] = (moment + datetime.timedelta(days=7 * n)).strftime("%Y-%m-%d")
                elif kind == "datetime":
                    row[name] = (moment + datetime.timedelta(days=7 * n)).strftime("%Y-%m-%dT09:00:00Z")
            for ref in entity["references"]:
                if ref["entity"] in seeded:
                    row[ref["field"]] = {"$ref": [ref["entity"], index]}
            for link in entity["links"]:
                row[link["field"]] = [{"$ref": [link["entity"], index]}] if link["entity"] in seeded else []
            rows.append(row)
        records[entity["name"]] = rows
        seeded.append(entity["name"])
    return {"label": "synthetic",
            "notice": {"en": "Synthetic sample records generated by the Master Build Engine; not real data.",
                       "ar": "سجلات تجريبية مولّدة آليًا؛ ليست بيانات حقيقية."},
            "records": records}


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
    return {"schema_version": 1,
            "app": {"slug": spec["slug"], "title": spec["title"], "locales": spec["locales"],
                    "default_locale": spec["locales"][0]},
            "limits": {"max_body_bytes": MAX_BODY_BYTES, "max_text": MAX_TEXT, "page_size": 100, "max_page_size": 500},
            "nfr": {"p95_ms": model["p95_ms"]},
            "entities": model["entities"]}


def _api_doc(spec, model):
    lines = [f"# API reference — {spec['title']['en']}", "",
             "JSON over HTTP. Writes need `Content-Type: application/json` and a same-origin request.",
             f"Bodies are limited to {MAX_BODY_BYTES} bytes. Errors have the shape "
             "`{\"error\": {\"code\", \"message\", \"fields\"?}}`.", "",
             "| Method | Path | Success | Errors |", "|---|---|---|---|",
             "| GET | `/api/health` | 200 `{\"ok\": true}` | |",
             "| GET | `/api/schema` | 200 entity model | |"]
    for entity in model["entities"]:
        base = f"/api/{entity['collection']}"
        filters = ", ".join(f"`{ref['field']}`" for ref in entity["references"])
        lines += [f"| GET | `{base}` | 200 `{{items, total, limit, offset}}` | 400 bad_query |",
                  f"| POST | `{base}` | 201 record + `Location` | 400 validation_failed, 409 reference_not_found, 413, 415, 403 |",
                  f"| GET | `{base}/{{id}}` | 200 record | 404 not_found |",
                  f"| PUT | `{base}/{{id}}` | 200 record | 400, 404, 409, 413, 415, 403 |",
                  f"| DELETE | `{base}/{{id}}` | 204 | 404, 409 has_dependents, 403 |"]
        if filters:
            lines.append(f"| | list filters for `{base}`: {filters}, `limit` (1-500), `offset` | | |")
    lines += ["", "## Entities", ""]
    for entity in model["entities"]:
        lines += [f"### {entity['name']} — `/api/{entity['collection']}`", "",
                  "| Field | Type | Required | Constraints |", "|---|---|---|---|"]
        for field in entity["fields"]:
            notes = []
            if "max" in field:
                notes.append(("max length " if field["type"] in ("text", "email") else "max ") + str(field["max"]))
            if "min" in field:
                notes.append(f"min {field['min']}")
            if field["type"] == "enum":
                notes.append("one of " + ", ".join(f"`{v}`" for v in field["values"]))
            if "default" in field:
                notes.append(f"default `{json.dumps(field['default'])}`")
            lines.append(f"| `{field['name']}` | {field['type']} | {'yes' if field['required'] else 'no'} | {'; '.join(notes)} |")
        for ref in entity["references"]:
            lines.append(f"| `{ref['field']}` | id of {ref['entity']} | {'yes' if ref['required'] else 'no'} | "
                         f"must exist (409); deleting the {ref['entity']} is {'refused while referenced (409)' if ref['required'] else 'allowed and clears it'} |")
        for link in entity["links"]:
            lines.append(f"| `{link['field']}` | list of {link['entity']} ids | no | each must exist (409); no duplicates |")
        lines += ["| `id`, `created_at`, `updated_at` | read-only | | refused in request bodies |", ""]
    lines += ["## Status codes", "",
              "| Status | Code | Meaning |", "|---|---|---|",
              "| 201 | | created |", "| 204 | | deleted |",
              "| 400 | `validation_failed`, `invalid_json`, `bad_query` | the request is malformed; `fields` names each problem |",
              "| 403 | `cross_origin` | the write did not come from the application's own origin |",
              "| 404 | `not_found`, `unknown_collection` | no such record or collection |",
              "| 405 | `method_not_allowed` | see the `Allow` header |",
              "| 409 | `reference_not_found`, `has_dependents`, `constraint_failed` | relation check failed |",
              "| 411 / 413 / 415 | `length_required`, `payload_too_large`, `unsupported_media_type` | body rules |", ""]
    return "\n".join(lines)


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
                              "motion-library/verify/package-lock.json"], capture_output=True, text=True)
    blobs = {}
    for line in listing.stdout.splitlines():
        meta, _, path = line.partition("\t")
        blobs[path] = meta.split()[2] if len(meta.split()) == 3 else None
    return all(blobs.get(path) == _git_blob(data) for path, data in sources.items())


def render(spec, model, *, hub, moment):
    """Return {relative path: bytes} for the whole application plus link metadata."""
    manifest, templates = _template_files()
    spec_bytes = _json_bytes(spec)
    spec_sha = _sha_bytes(spec_bytes)
    open_items = open_items_for(spec, model)
    entity_rows = ["| Entity | Collection | Fields | Relations |", "|---|---|---|---|"]
    for entity in model["entities"]:
        relations = [f"{ref['field']} → {ref['entity']}{' (required)' if ref['required'] else ''}" for ref in entity["references"]]
        relations += [f"{link['field']} ↔ {link['entity']}" for link in entity["links"]]
        entity_rows.append(f"| {entity['name']} | `/api/{entity['collection']}` | "
                           f"{', '.join(f['name'] for f in entity['fields'])} | {', '.join(relations) or '—'} |")
    api_summary = "\n".join(f"- `/api/{e['collection']}` — list, create; `/api/{e['collection']}/{{id}}` — get, update, delete"
                            for e in model["entities"])
    strings = _load_template_data("ui-strings.json")
    default = spec["locales"][0]
    values = {
        "TITLE": spec["title"][default], "TITLE_EN": spec["title"]["en"], "TITLE_AR": spec["title"]["ar"],
        "LANG": default, "DIR": strings[default]["dir"], "SKIP": strings[default]["ui"]["skip"],
        "LANGUAGE": strings[default]["ui"]["language"], "SECTIONS": strings[default]["ui"]["sections"],
        "FOOTER": strings[default]["ui"]["footer"], "NOSCRIPT": strings[default]["ui"]["noscript"],
        "ENTITIES_TABLE": "\n".join(entity_rows), "API_SUMMARY": api_summary,
        "OPEN_ITEMS": "\n".join(f"- **{item['id']}** {item['summary']}" for item in open_items),
        "GENERATED_AT": _iso(moment), "HUB_REVISION": hub["revision"], "DATE": moment.strftime("%Y-%m-%d"),
        "SPEC_SHA": spec_sha, "ENTITY_LIST": ", ".join(e["name"] for e in model["entities"]),
        "ROLES": ", ".join(role["id"] for role in spec["roles"]) or "none", "MAX_BODY": str(MAX_BODY_BYTES),
    }
    files = {}
    for source, row in sorted(manifest["files"].items()):
        data = templates[source]
        if row["mode"] == "render":
            data = _render(data.decode("utf-8"), values, escape=row["to"].endswith(".html")).encode("utf-8")
        files[row["to"]] = data
    up, down = migrations_sql(model)
    package, lock, playwright_used = _package_files(spec["slug"])
    files.update({
        "app/schema.json": _json_bytes(_schema(spec, model)),
        "app/seed_data.json": _json_bytes(seed_data(model, moment)),
        "static/i18n.json": _json_bytes(_i18n(spec, model)),
        "migrations/0001_initial.up.sql": up.encode("utf-8"),
        "migrations/0001_initial.down.sql": down.encode("utf-8"),
        "docs/API.md": _api_doc(spec, model).encode("utf-8"),
        "package.json": package,
        "package-lock.json": lock,
        ".gaie/spec.json": spec_bytes,
    })
    sources = {f"templates/app-stdlib/{name}": data for name, data in templates.items()}
    sources.update({source["path"]: (ROOT / source["path"]).read_bytes() for source in playwright_used["sources"]})
    engine_bytes = pathlib.Path(__file__).read_bytes()
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
        {"id": "OI-DEPLOY", "summary": "Choose a deployment target; nothing was deployed and no environment was created."},
        {"id": "OI-AUTH", "summary": "Choose an identity provider: roles "
                                    f"({', '.join(r['id'] for r in spec['roles']) or 'none defined'}) are not enforced yet; "
                                    "the server binds to loopback only."},
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
    """Registries consulted for an existing project with the same identity."""
    slug, titles = spec["slug"], {spec["title"]["en"].casefold(), spec["title"]["ar"]}
    matches, sources = [], []
    for link_path in sorted(pathlib.Path(workspace).glob("*/.gaie/link.json")):
        try:
            data = json.loads(link_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("project", {}).get("id") == slug:
            matches.append({"source": "workspace", "id": slug, "path": link_path.parent.parent.name})
    sources.append({"source": "workspace", "status": "checked"})
    from . import gaie_router
    try:
        rows = gaie_router.projects(environ)
    except gaie_router.RouteError as error:
        raise BuildError(f"project registry unreadable, refusing to risk a duplicate: {error}") from None
    for row in rows.values():
        aliases = {alias.casefold() for alias in row["aliases"]}
        if slug in aliases or row["id"] == slug or titles & aliases or row["slug"].split("/")[-1] == slug:
            matches.append({"source": row["source"], "id": row["id"], "repository": row.get("repository")})
    sources.append({"source": "router-registry", "status": "checked", "projects": len(rows)})
    module = registry
    if module is None:
        try:
            module = importlib.import_module("engineering_os.project_registry")
        except ImportError:
            module = None
            sources.append({"source": "project_registry", "status": "skipped: engineering_os.project_registry not present"})
    if module is not None:
        finder = module if callable(module) else getattr(module, "find_existing", None)
        if finder is None:
            sources.append({"source": "project_registry", "status": "skipped: no find_existing(slug, title=...) interface"})
        else:
            found = finder(slug, title=spec["title"]) or []
            matches += [{"source": "project_registry", **dict(row)} for row in found]
            sources.append({"source": "project_registry", "status": "checked"})
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
    command = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
               "-c", "core.autocrlf=false", "-c", "init.defaultBranch=main", "-C", str(cwd), *args]
    result = subprocess.run(command, capture_output=True, text=True, env=env or _git_env(moment), timeout=120)
    if check and result.returncode:
        raise BuildError(f"git {args[0]} failed: {result.stderr.strip()[:300]}")
    return result


def _write_files(target, files):
    target.mkdir(mode=0o755, exist_ok=True)
    for relative, data in sorted(files.items()):
        parts = pathlib.PurePosixPath(relative).parts
        _need(parts and not relative.startswith("/") and ".." not in parts and parts[0] != ".git",
              f"unsafe generated path {relative}", BuildError)
        path = target.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as stream:
            stream.write(data)
        os.chmod(path, 0o755 if relative == "manage.py" else 0o644)


# ---------------------------------------------------------------------------
# verification: static checks and executed test suites

def _security_scan():
    spec = importlib.util.spec_from_file_location("_gaie_build_security_scan", ROOT / "scripts" / "security_scan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME_PREFIXES = ("app/", "static/", "migrations/", "tests/", "manage.py")
JS_FORBIDDEN = re.compile(r"\beval\s*\(|new\s+Function\b|\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|document\.write|"
                          r"setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"]|javascript:")
PY_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__", "os.system", "os.popen", "os.exec",
                                "subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_output",
                                "subprocess.check_call", "pickle.loads", "pickle.load", "marshal.loads"})
PY_FORBIDDEN_IMPORTS = frozenset({"subprocess", "pickle", "marshal", "shelve", "ctypes", "socket", "urllib.request",
                                  "http.client", "ftplib", "smtplib", "telnetlib"})


def _python_imports(source):
    import ast
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return tree, found


def _calls(tree):
    import ast
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

    stdlib = set(sys.stdlib_module_names)
    local = {"app", "tests"}
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
                top = name.split(".")[0]
                if top not in stdlib and top not in local:
                    third_party.add(name)
                    problems.append(f"{path} imports non-stdlib module {name}")
        if path.endswith((".js", ".mjs")):
            for spec_name in re.findall(r"""(?:from\s+|import\s*\(|require\()\s*['"]([^'"]+)['"]""", text):
                allowed = spec_name.startswith("node:") or (path.startswith("tests/e2e/") and spec_name in
                                                            ("playwright", "playwright/package.json"))
                if not allowed:
                    problems.append(f"{path} imports {spec_name}")
    absolute = [path for path, data in files.items() if str(target) in data.decode("utf-8", "replace")
                or "/home/" in data.decode("utf-8", "replace")]
    problems += [f"{path} contains an absolute local path" for path in absolute]
    components = ["app/model.py", "app/db.py", "app/server.py", "app/seed.py", "static/index.html", "static/app.js",
                  "static/app.css", "migrations/0001_initial.up.sql", "tests/test_api.py", "tests/e2e/ui.e2e.mjs"]
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
                if call in PY_FORBIDDEN_CALLS or call.split(".")[0] in ("eval", "exec"):
                    code_problems.append(f"{path}: forbidden call {call}")
            if path.startswith(("app/", "manage.py")):
                code_problems += [f"{path}: forbidden import {name}" for name in imports if name in PY_FORBIDDEN_IMPORTS]
            if path == "app/db.py" and re.search(r"\.format\(|%\s*\(|\bf[\"'](?:SELECT|INSERT|UPDATE|DELETE)", text):
                code_problems.append(f"{path}: string-formatted SQL")
        if path.startswith("static/") and path.endswith(".js") and JS_FORBIDDEN.search(text):
            code_problems.append(f"{path}: forbidden dynamic code or HTML injection sink")
        if path.endswith(".html"):
            if re.search(r"<script(?![^>]*\bsrc=)[^>]*>", text) or re.search(r"\son[a-z]+\s*=", text) \
                    or re.search(r"\sstyle\s*=", text):
                code_problems.append(f"{path}: inline script, handler or style")
            if re.search(r"""(?:src|href)\s*=\s*["']https?://""", text):
                code_problems.append(f"{path}: external resource")
    server = files.get("app/server.py", b"").decode("utf-8")
    for needle in ("frame-ancestors 'none'", "X-Content-Type-Options", "nosniff", "max_body_bytes", "_same_origin"):
        if needle not in server:
            code_problems.append(f"app/server.py: missing {needle}")
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
           {"database": "data/app.sqlite3 (gitignored, created at run time)", "seed": "app/seed_data.json label=synthetic"})

    index = files.get("static/index.html", b"").decode("utf-8")
    script = files.get("static/app.js", b"").decode("utf-8")
    a11y = [f"index.html lacks {needle}" for needle in ('lang="', 'dir="', '<main id="main"', 'class="skip-link"',
                                                        'role="status"', 'aria-live="polite"', 'role="alert"')
            if needle not in index]
    a11y += [f"app.js lacks {needle}" for needle in ("for: id", "aria-describedby", "aria-invalid", "aria-pressed",
                                                     "aria-current", "root.dir") if needle not in script]
    record("static:frontend:accessibility", a11y, {"checked": "landmarks, skip link, live regions, labels, RTL switch"})

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
            wanted = {"id", "created_at", "updated_at"} | {f["name"] for f in entity["fields"]} \
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
        expected = {e["table"] for e in model["entities"]} | {l["link_table"] for e in model["entities"] for l in e["links"]}
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
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "TMPDIR": str(home),
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}
    return env


def run_suites(target, *, e2e=True, timeout=900):
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
                     "evidence": states, "status": status})
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
    api = [t for t in python_ids if t.startswith(API_ID)]
    contract = [t for t in api if any(f"test_{op}_" in t for op in API_OPS) or "test_reference_" in t or "test_links_" in t]
    authz = [API_ID + name for name in ("test_cross_origin_write_refused", "test_wrong_content_type_refused",
                                        "test_method_not_allowed")]
    browser = [t for t in e2e_ids if t.count(":") >= 2]
    a11y = ["e2e:labels", "e2e:keyboard"] + [f"e2e:{loc}:language" for loc in ctx["spec"]["locales"]] \
        + ["static:frontend:accessibility"]
    security = ["static:security:code", API_ID + "test_security_headers", API_ID + "test_sql_injection_is_inert",
                API_ID + "test_oversized_body_refused", API_ID + "test_invalid_json_refused", "e2e:csp", "e2e:headers",
                "e2e:no-external-requests"]
    matrix = ctx["coverage"]
    mapped = [row for row in matrix if row["status"] not in ("unmapped", "unknown-evidence")]

    def acceptance():
        problems = [f"{row['acceptance']}: {row['status']}" for row in matrix if row not in mapped]
        return ("passed" if not problems else "failed",
                {"rule": "every acceptance criterion maps to generated tests or static checks",
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
        ("api", "contract"): ids(contract, "CRUD, status codes and relation checks per entity over real HTTP"),
        ("api", "authorization"): ids(authz + ["static:security:code"],
                                      "write boundary: same-origin JSON only, 405 for unsupported methods, loopback "
                                      "default; user authentication is NOT implemented (open item OI-AUTH)"),
        ("backend", "integration"): ids(unit + api, "the complete Python suite passed against the real server"),
        ("frontend", "browser"): ids(browser, "create/update/delete through the UI in every locale (Chromium)"),
        ("frontend", "accessibility"): ids(a11y, "labels, keyboard reachability, lang/dir switch, landmarks"),
        ("testing", "unit"): ids(unit, "validation and migration unit tests"),
        ("testing", "integration"): ids(api, "API integration tests on a free loopback port"),
        ("testing", "regression"): regression,
        ("security", "secrets"): ids(["static:security:secrets"], "scripts/security_scan.py secret rules over every file"),
        ("security", "dependencies"): ids(["static:dependencies"], "stdlib runtime; dev-only Playwright pinned to the review"),
        ("security", "security"): ids(security, "no eval/shell/HTML sinks; headers, CSP, size limits, SQL inertness"),
        ("documentation", "documentation_review"): ids(["static:documentation"], "README run/test/API, API.md, ADRs, CHANGELOG"),
        ("release", "release_review"): release_review,
        ("release", "rollback"): rollback,
    }


def _stage_content(ctx):
    spec, model, files = ctx["spec"], ctx["model"], ctx["files"]
    file_ref = lambda path: {"path": path, "sha256": _sha_bytes(files[path])}  # noqa: E731
    suites = ctx["suites"]
    matrix = ctx["coverage"]
    return {
        "requirements": {
            "requirements": [{"id": row["id"], "summary": row["summary"],
                              "acceptance": [{"id": aid, "criterion": ctx["coverage_map"][aid]["text"],
                                              "evidence": ctx["coverage_map"][aid]["evidence"]} for aid in row["acceptance"]]}
                             for row in ctx["requirements"]],
            "data_boundaries": {"storage": "local SQLite file data/app.sqlite3, gitignored",
                                "seed": "synthetic records only", "hub": "no runtime dependency",
                                "personal_data": "none by default; operators enter their own records"},
            "spec": file_ref(".gaie/spec.json"), "open_items": ctx["open_items"]},
        "architecture": {
            "components": [file_ref(path) for path in ("app/model.py", "app/db.py", "app/server.py", "app/seed.py",
                                                       "static/index.html", "static/app.js", "manage.py")],
            "decisions": [{"id": "ADR-001", "decision": "modular monolith on the Python standard library + SQLite"},
                          {"id": "ADR-002", "decision": "same-origin JSON API as CSRF defence"},
                          {"id": "ADR-003", "decision": "no authentication in 0.1.0; loopback by default"},
                          {"id": "ADR-004", "decision": "bilingual UI without a build step"}],
            "constraints": spec["constraints"], "document": file_ref("docs/ARCHITECTURE.md")},
        "database": {
            "entities": [{"name": e["name"], "table": e["table"],
                          "columns": ["id"] + [f["name"] for f in e["fields"]] + [r["field"] for r in e["references"]]}
                         for e in model["entities"]],
            "migrations": [file_ref("migrations/0001_initial.up.sql")],
            "rollback": [file_ref("migrations/0001_initial.down.sql")]},
        "api": {
            "operations": [{"collection": f"/api/{e['collection']}",
                            "methods": ["GET", "POST", "GET {id}", "PUT {id}", "DELETE {id}"]} for e in model["entities"]],
            "authentication": {"mode": "none", "boundary": "loopback bind by default; same-origin JSON writes",
                               "open_item": "OI-AUTH"},
            "errors": [400, 403, 404, 405, 409, 411, 413, 415], "reference": file_ref("docs/API.md")},
        "backend": {
            "services": [file_ref("app/server.py"), file_ref("app/db.py")],
            "boundaries": ["request body <= %d bytes" % MAX_BODY_BYTES, "parameterized SQL", "identifiers from schema only"],
            "configuration": ["serve --host (loopback unless --allow-network)", "serve --port", "--db PATH"]},
        "frontend": {
            "routes": ["/", "/static/app.js", "/static/app.css", "/static/i18n.json"],
            "components": [file_ref("static/index.html"), file_ref("static/app.js"), file_ref("static/i18n.json")],
            "accessibility": ["labels for every control", "keyboard reachable", "skip link", "live regions",
                              "lang/dir per locale"] + [f"locale {loc}" for loc in spec["locales"]]},
        "testing": {
            "suites": [{"name": "python", **{k: v for k, v in suites["python"].items() if k != "tests"}},
                       {"name": "e2e", **{k: v for k, v in suites["e2e"].items() if k != "tests"}}],
            "regressions": {"expected_tests": len(ctx["catalog"][0]) + len(ctx["catalog"][1])},
            "coverage": matrix},
        "security": {
            "threats": ["XSS via record values", "CSRF", "clickjacking", "SQL injection", "oversized bodies",
                        "path traversal", "secret leakage", "unauthenticated network exposure"],
            "findings": [{"id": "SEC-1", "severity": "medium", "summary": "no user authentication; roles not enforced",
                          "status": "accepted for local use; open item OI-AUTH"}]
                        + [{"id": key, "status": value["status"]} for key, value in sorted(ctx["statics"].items())
                           if key.startswith(("static:security", "static:dependencies"))],
            "remediations": ["loopback bind by default; --allow-network only behind an authenticating proxy",
                             "CSP default-src 'self' with frame-ancestors 'none'", "textContent-only DOM updates"]},
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


def publish(app_dir, *, remote, grant=None, token=None, now=None):
    """Push the app's main branch to an owner-created remote. Gated by an approval token.

    Without a valid approval this writes the repository request and raises
    ApprovalRequired before any Git network operation.
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
    status = _git(app_dir, "status", "--porcelain")
    if status.stdout.strip():
        raise BuildError("the application working tree is not clean; commit before publishing")
    env = _git_env()
    if kind == "github":  # the owner's environment supplies credentials; the engine never handles them
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    pushed = _git(app_dir, "push", "--porcelain", url, "refs/heads/main:refs/heads/main", env=env)
    head = _git(app_dir, "rev-parse", "HEAD").stdout.strip()
    return {"status": "pushed", "remote_kind": kind, "remote": url if kind == "github" else "<local bare repository>",
            "commit": head, "approved_by": approval["approved_by"], "side_effect": "external-write",
            "output": pushed.stdout.strip()[-500:]}


# ---------------------------------------------------------------------------
# the build pipeline

def plan(spec, *, allow_open_questions=False):
    """Validate and describe what a build would produce; writes nothing."""
    spec = validate_spec(spec, allow_open_questions=allow_open_questions)
    model = derive_model(spec)
    rows, coverage = requirements(spec, model)
    request = {"schema_version": 1, "project": spec["slug"], "source_revision": "0" * 40,
               "requirements": rows, "targets": TARGETS}
    stages = [stage["id"] for stage in factory.plan_factory(request)["stages"]]
    python_ids, e2e_ids = expected_tests(model, spec["locales"])
    return {"project": spec["slug"], "entities": [e["name"] for e in model["entities"]],
            "collections": [f"/api/{e['collection']}" for e in model["entities"]],
            "factory_stages": stages, "expected_tests": {"python": len(python_ids), "e2e": len(e2e_ids)},
            "unmapped_criteria": [aid for aid, row in sorted(coverage.items()) if not row["evidence"]],
            "translation_gaps": model["translation_gaps"], "open_items": open_items_for(spec, model)}


def build(spec, *, out_dir, hub_revision, now=None, workspace=None, environ=None, registry=None,
          verify=True, e2e=True, allow_open_questions=False):
    """Generate, commit, test and evidence an independent application. Returns a build report."""
    moment = _now(now)
    spec = validate_spec(spec, allow_open_questions=allow_open_questions)
    hub = _hub_revision(hub_revision)
    if workspace is None:
        workspace = default_workspace(environ)
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    target, workspace = check_target(out_dir, workspace)
    existing = find_existing(spec, workspace=workspace, environ=environ, registry=registry)
    if existing["matches"]:
        raise DuplicateProject(f"project {spec['slug']!r} already exists; route to MASTER_UPGRADE", existing["matches"])
    model = derive_model(spec)
    rows, coverage_map = requirements(spec, model)
    files, link = render(spec, model, hub=hub, moment=moment)
    created = not target.exists()
    pipeline = [{"step": "spec", "status": "passed"}, {"step": "registry-check", "status": "passed",
                                                         "sources": existing["sources"]}]
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
    catalog = expected_tests(model, spec["locales"])
    matrix = coverage_matrix(coverage_map, statics, suites, catalog)
    repository = request_repository(target, spec=spec, moment=moment)
    ctx = {"spec": spec, "model": model, "files": files, "statics": statics, "suites": suites, "catalog": catalog,
           "coverage": matrix, "coverage_map": coverage_map, "requirements": rows, "source_commit": source_commit,
           "git_clean": git_clean, "repository_request": repository, "open_items": open_items_for(spec, model)}
    factory_plan, receipts, evaluation = write_factory_evidence(target, ctx)
    pipeline.append({"step": "factory", "status": "passed" if evaluation["delivery_review_ready"] else "blocked",
                     "verified": evaluation["verified_count"], "stages": len(factory_plan["stages"])})
    _git(target, "add", "--", FACTORY_DIR, REQUEST_FILE)
    _git(target, "commit", "--quiet", "-m", f"chore(gaie): factory evidence for {source_commit[:12]}\n", moment=moment)
    evidence_commit = _git(target, "rev-parse", "HEAD").stdout.strip()
    leftovers = _git(target, "status", "--porcelain", "--untracked-files=all").stdout.split("\n")
    leftovers = [line[3:] for line in leftovers if line.strip()]
    pipeline.append({"step": "repository", "status": "awaiting-approval", "request": REQUEST_FILE})
    return {
        "schema": REPORT_SCHEMA, "ok": bool(evaluation["delivery_review_ready"]), "project": spec["slug"],
        "out_dir": str(target), "source_commit": source_commit, "evidence_commit": evidence_commit,
        "hub_revision": hub["revision"], "pin_on_main": hub["on_main"], "reproducible_from_pin": link["reproducible_from_pin"],
        "untracked_after_build": leftovers, "pipeline": pipeline, "static_checks": {k: v["status"] for k, v in statics.items()},
        "static_problems": {k: v["detail"]["problems"] for k, v in statics.items() if v["status"] != "passed"},
        "tests": {name: {k: v for k, v in suite.items() if k != "tests"} for name, suite in suites.items()},
        "coverage": matrix, "factory": evaluation, "open_items": ctx["open_items"],
        "repository": {"status": repository["status"], "request": REQUEST_FILE, "visibility": "private"},
        "provider_calls": 0, "network": "none outside loopback (generated tests bind 127.0.0.1 in child processes)",
        "deployment_authorized": False,
        "evidence_kind": {"deterministic": ["spec validation", "rendering", "static checks", "factory receipts"],
                          "executed": ["generated unit/API tests", "Playwright E2E"] if verify else [],
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
        "plan": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"],
                 "summary": "Validate a gaie.spec/1 and describe the application and factory stages without writing."},
        "build": {"side_effect": "workspace-write",
                  "permissions": ["read:repo", "read:registry", "write:workspace", "exec:sandbox", "secrets:none"],
                  "summary": "Generate, locally commit, test and evidence an independent application in a workspace."},
        "evaluate": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"],
                     "summary": "Re-validate a built application's factory receipts against its bytes."},
        "request-repository": {"side_effect": "workspace-write", "permissions": ["write:workspace", "secrets:none"],
                               "summary": "Write repository-request.json for the owner; never contacts GitHub."},
        "publish": {"side_effect": "external-write", "permissions": ["ext:github", "secrets:none"],
                    "summary": "Push the app to an owner-created private remote; requires an owner approval token."},
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
        return {"ok": True, "detail": f"templates/app-stdlib {manifest['version']}: {len(templates)} files"}
    except (BuildError, OSError, ValueError) as error:
        return {"ok": False, "detail": str(error)}


def engine(action, payload, ctx=None):
    """Contract entrypoint `(action, payload, ctx) -> dict`; payload is data, never instructions."""
    if action not in ENGINE_RECORD["actions"]:
        raise BuildError(f"unknown action {action!r}")
    if not isinstance(payload, dict):
        raise BuildError("payload must be an object")
    if action == "plan":
        return plan(payload["spec"], allow_open_questions=bool(payload.get("allow_open_questions")))
    if action == "build":
        allowed = {"spec", "out_dir", "hub_revision", "now", "workspace", "verify", "e2e"}
        if set(payload) - allowed:
            raise BuildError(f"unknown build payload keys {sorted(set(payload) - allowed)}")
        return build(payload["spec"], out_dir=payload["out_dir"], hub_revision=payload["hub_revision"],
                     now=payload.get("now"), workspace=payload.get("workspace"),
                     verify=payload.get("verify", True), e2e=payload.get("e2e", True))
    if action == "evaluate":
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
