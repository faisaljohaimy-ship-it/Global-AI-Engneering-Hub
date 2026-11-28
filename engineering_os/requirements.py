"""Requirements & Specification Intelligence (GAIE layer L15): command or brief -> gaie.spec/1.

Deterministic and offline: no model is called. Arabic and English text is folded with
the master router's normalization (hamza/alef forms, taa marbuta, alef maqsura,
diacritics, tatweel; `engineering_os.gaie_router`), matched against the bilingual
knowledge packs in `governance/domains/`, and turned into a requirement specification
whose acceptance criteria follow one machine-checkable grammar
(`METHOD /path [condition] returns NNN [and expectation]`). Anything the text does not
settle becomes an open question; nothing is guessed. Pack defaults that are applied are
listed in `assumptions`. Every output carries the SHA-256 of its input and
`"mode": "deterministic"`. Standard library only. SPDX-License-Identifier: MIT.
"""
import argparse
import copy
import datetime
import json
import pathlib
import re
import sys

from . import gaie_router as router
from .contracts import sha256 as digest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOMAINS = ROOT / "governance" / "domains"
SCHEMA = "gaie.spec/1"
DIFF_SCHEMA = "gaie.spec-diff/1"
PACK_SCHEMA = "gaie.domain/1"
LEXICON_SCHEMA = "gaie.lexicon/1"
MODE = "deterministic"
FIELD_TYPES = ("text", "int", "number", "bool", "date", "datetime", "enum", "email")
RELATION_KINDS = ("many-to-one", "one-to-many", "many-to-many")
PRODUCT_TYPES = ("web-app", "mobile-app", "api-service", "dashboard")
INTENTS = ("new-system", "change")
LOCALES = ("ar", "en")
DATABASES = ("sqlite", "postgresql", "mysql")
PERMISSIONS = ("*", "read", "read:own", "write", "write:own", "delete", "approve", "export", "manage:users")
NFR_KEYS = ("security", "performance", "accessibility", "i18n")
RESERVED_FIELDS = ("id", "created_at", "updated_at")
INTEGRATION_ANSWERS = ("approve", "exclude")
MAX_INPUT = 20000
SPEC_KEYS = {"schema", "mode", "source", "title", "slug", "product_type", "domain", "locales", "roles", "entities",
             "relations", "features", "nfr", "ai", "integrations", "constraints", "open_questions"}
SPEC_OPTIONAL = {"intent", "assumptions"}

# \Z, not $: "$" also matches before a trailing newline ("Task\n" would validate).
_ENTITY = re.compile(r"^[A-Z][A-Za-z0-9]{0,62}\Z")
_SNAKE = re.compile(r"^[a-z][a-z0-9_]{0,62}\Z")
_KEBAB = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_FEATURE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\Z")
_ROLE = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*\Z")
_QUESTION = re.compile(r"^[a-z_]+(?::[A-Za-z0-9_-]+)?\Z")
_HEX = re.compile(r"^[0-9a-f]{64}\Z")
_ACCEPTANCE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) (/\S*)(?: (.+?))? returns ([1-5][0-9]{2})(?: and (.+))?\Z")
_SENTENCES = re.compile(r"[.;!?\n\r؛؟۔]+")
_CLAUSES = re.compile(r"[,،:()\[\]{}]+")
_ARABIC = re.compile("[ء-ي]")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# A field or feature mention attaches to the entity named right after it when linked ("add priority to
# tasks", Arabic «أولوية المهام» / «للمهام»), or to the entity before it when that entity "has" it
# ("tasks with priority", «المهام مع الأولوية»). Otherwise it has no owner and nothing is guessed.
_LINKS = frozenset({"to", "into", "for", "in", "on", "of", "from", "الي", "في", "علي", "من"})
_GAP = _LINKS | frozenset({"the", "a", "an", "each", "every", "field", "fields", "column", "attribute", "حقل", "حقول", "خانه",
                           "and", "و", "with", "مع"})
_HAS = frozenset({"has", "have", "having", "with", "where", "contain", "contains", "containing", "مع", "لها", "له",
                  "ذات", "ذو", "يحتوي", "تحتوي", "فيها", "فيه", "بها", "به"})
# Category precedence when two lexicon phrases of equal length cover the same words.
_RANK = {"domain": 0, "locale": 1, "integration": 2, "ai": 3, "product": 4, "database": 5, "feature": 6,
         "entity": 7, "field": 8, "role": 9, "nfr": 10}


class SpecError(ValueError):
    """A command, specification, knowledge pack or answer was refused; `errors` lists every reason."""

    def __init__(self, errors):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors))


class _Check:
    def __init__(self):
        self.errors = []

    def need(self, condition, message):
        if not condition:
            self.errors.append(message)
        return bool(condition)

    def done(self):
        if self.errors:
            raise SpecError(self.errors)


def _text_sha(text):
    return digest(text.encode("utf-8"))


def _snake(name):
    return _CAMEL.sub("_", name).lower()


def _label(item, lang):
    label = item.get("label")
    return label[lang] if isinstance(label, dict) and label.get(lang) else item["name"]


def _bilingual(check, value, where):
    ok = check.need(isinstance(value, dict) and set(value) == {"ar", "en"}, f"{where}: needs exactly ar and en")
    if ok:
        for lang in ("ar", "en"):
            check.need(isinstance(value[lang], str) and value[lang].strip(), f"{where}.{lang}: empty")
    return ok


def _strings(check, value, where, *, minimum=0, limit=500):
    ok = check.need(isinstance(value, list) and len(value) >= minimum, f"{where}: list of at least {minimum} strings")
    if ok:
        ok = check.need(all(isinstance(item, str) and 0 < len(item.strip()) <= limit for item in value),
                        f"{where}: non-empty strings up to {limit} characters")
        ok = ok and check.need(len(set(value)) == len(value), f"{where}: duplicates")
    return ok


# --------------------------------------------------------------------------- acceptance grammar

def parse_acceptance(text):
    """Structured check for one acceptance criterion; SpecError when it is not testable."""
    match = _ACCEPTANCE.match(text) if isinstance(text, str) else None
    if not match:
        raise SpecError(f"untestable acceptance criterion: {text!r} (expected 'METHOD /path [condition] returns NNN [and ...]')")
    method, path, condition, status, expect = match.groups()
    return {"method": method, "path": path, "condition": condition, "status": int(status), "expect": expect,
            "placeholders": re.findall(r"\{(\w+)\}", path)}


def acceptance_checks(spec):
    """Every acceptance criterion of a valid spec as a structured check an automated test can run."""
    report = validate_spec(spec)
    return {"mode": MODE, "spec_sha256": report["spec_sha256"], "checks": [
        {"feature": feature["id"], "index": index, "criterion": text, **parse_acceptance(text)}
        for feature in spec["features"] for index, text in enumerate(feature["acceptance"])]}


# --------------------------------------------------------------------------- field / entity / relation validators

def _check_value(field, value):
    kind = field.get("type")
    if kind in ("text", "email"):
        return isinstance(value, str) and len(value) <= field.get("max", MAX_INPUT)
    if kind == "int":
        return type(value) is int
    if kind == "number":
        return type(value) in (int, float)
    if kind == "bool":
        return type(value) is bool
    if kind == "enum":
        return value in (field.get("values") or [])
    if kind in ("date", "datetime"):
        try:
            (datetime.date if kind == "date" else datetime.datetime).fromisoformat(value)
        except (TypeError, ValueError):
            return False
        return True
    return False


def _check_field(check, field, where, *, extra=()):
    if not check.need(isinstance(field, dict), f"{where}: object required"):
        return None
    allowed = {"name", "type", "required", "label", "max", "min", "values", "default", "unique", *extra}
    check.need(set(field) <= allowed, f"{where}: unknown keys {sorted(set(field) - allowed)}")
    name = field.get("name")
    check.need(isinstance(name, str) and _SNAKE.match(name), f"{where}.name: snake_case required, got {name!r}")
    check.need(name not in RESERVED_FIELDS, f"{where}.name: {name!r} is reserved (implicit column)")
    where = f"{where}({name})"
    kind = field.get("type")
    if not check.need(kind in FIELD_TYPES, f"{where}.type: unknown field type {kind!r}; allowed {list(FIELD_TYPES)}"):
        return name
    check.need(type(field.get("required")) is bool, f"{where}.required: true or false")
    if "label" in field:
        _bilingual(check, field["label"], f"{where}.label")
    if "unique" in field:
        check.need(type(field["unique"]) is bool, f"{where}.unique: true or false")
    if kind == "enum":
        values = field.get("values")
        ok = check.need(isinstance(values, list) and values and len(set(map(str, values))) == len(values)
                        and all(isinstance(v, str) and _SNAKE.match(v) for v in values),
                        f"{where}: invalid enum (values must be unique snake_case strings, at least one)")
        check.need("min" not in field and "max" not in field, f"{where}: invalid enum (min/max not allowed)")
        if not ok:
            return name
    else:
        check.need("values" not in field, f"{where}: values only allowed for enum fields")
    if kind in ("text", "email", "int", "number"):
        bound = int if kind in ("text", "email", "int") else (int, float)
        for key in ("min", "max"):
            if key in field:
                check.need(isinstance(field[key], bound) and type(field[key]) is not bool, f"{where}.{key}: number required")
        if kind in ("text", "email") and "max" in field:
            check.need(isinstance(field["max"], int) and 0 < field["max"] <= 100000, f"{where}.max: 1..100000")
        if isinstance(field.get("min"), (int, float)) and isinstance(field.get("max"), (int, float)):
            check.need(field["min"] <= field["max"], f"{where}: min greater than max")
    else:
        check.need("min" not in field and "max" not in field, f"{where}: min/max not allowed for {kind}")
    if "default" in field:
        check.need(_check_value(field, field["default"]), f"{where}.default: {field['default']!r} does not match type {kind}")
    return name


def _check_entities(check, entities, where, *, extra_entity=(), extra_field=()):
    names = []
    if not check.need(isinstance(entities, list), f"{where}: list required"):
        return names
    plurals, folded = set(), set()
    for index, entity in enumerate(entities):
        at = f"{where}[{index}]"
        if not check.need(isinstance(entity, dict), f"{at}: object required"):
            continue
        allowed = {"name", "label", "plural", "fields", *extra_entity}
        check.need(set(entity) <= allowed, f"{at}: unknown keys {sorted(set(entity) - allowed)}")
        name = entity.get("name")
        if check.need(isinstance(name, str) and _ENTITY.match(name), f"{at}.name: PascalCase required, got {name!r}"):
            check.need(name.casefold() not in folded, f"{at}: duplicate entity {name!r}")
            folded.add(name.casefold())
            names.append(name)
            at = f"{where}({name})"
        if "label" in entity:
            _bilingual(check, entity["label"], f"{at}.label")
        if "plural" in entity:
            plural = entity["plural"]
            check.need(isinstance(plural, str) and _KEBAB.match(plural), f"{at}.plural: kebab-case required")
            check.need(plural not in plurals, f"{at}.plural: duplicate {plural!r}")
            plurals.add(plural)
        fields = entity.get("fields")
        if check.need(isinstance(fields, list) and fields, f"{at}.fields: at least one field"):
            seen = set()
            for position, field in enumerate(fields):
                field_name = _check_field(check, field, f"{at}.fields[{position}]", extra=extra_field)
                if field_name:
                    check.need(field_name not in seen, f"{at}: duplicate field {field_name!r}")
                    seen.add(field_name)
    return names


def _check_relations(check, relations, names, entities, where):
    if not check.need(isinstance(relations, list), f"{where}: list required"):
        return
    fields = {e.get("name"): {f.get("name") for f in e.get("fields", []) if isinstance(f, dict)}
              for e in entities if isinstance(e, dict)}
    seen = set()
    for index, relation in enumerate(relations):
        at = f"{where}[{index}]"
        if not check.need(isinstance(relation, dict), f"{at}: object required"):
            continue
        check.need({"from", "to", "kind", "required"} <= set(relation) <= {"from", "to", "kind", "required", "field"},
                   f"{at}: needs from, to, kind, required (field optional)")
        for end in ("from", "to"):
            check.need(relation.get(end) in names, f"{at}.{end}: relation to a missing entity {relation.get(end)!r}")
        check.need(relation.get("kind") in RELATION_KINDS, f"{at}.kind: {relation.get('kind')!r} not in {list(RELATION_KINDS)}")
        check.need(type(relation.get("required")) is bool, f"{at}.required: true or false")
        target = relation.get("to") if isinstance(relation.get("to"), str) else ""
        attribute = relation.get("field", _snake(target))
        if check.need(isinstance(attribute, str) and _SNAKE.match(attribute or ""), f"{at}.field: snake_case required"):
            key = (relation.get("from"), attribute)
            check.need(key not in seen, f"{at}: duplicate relation {relation.get('from')}.{attribute}")
            seen.add(key)
            own = fields.get(relation.get("from"), set())
            check.need(attribute not in own and f"{attribute}_id" not in own,
                       f"{at}: relation field {attribute!r} collides with a field of {relation.get('from')}")


# --------------------------------------------------------------------------- spec validation

def validate_spec(spec):
    """Check a gaie.spec/1 document; SpecError lists every problem. Returns a deterministic report."""
    check = _Check()
    if not check.need(isinstance(spec, dict), "spec: object required"):
        check.done()
    keys = set(spec)
    check.need(SPEC_KEYS <= keys, f"spec: missing keys {sorted(SPEC_KEYS - keys)}")
    check.need(keys <= SPEC_KEYS | SPEC_OPTIONAL, f"spec: unknown keys {sorted(keys - SPEC_KEYS - SPEC_OPTIONAL)}")
    check.done()
    check.need(spec["schema"] == SCHEMA, f"schema: must be {SCHEMA}")
    check.need(spec["mode"] == MODE, f"mode: must be {MODE}")
    source = spec["source"]
    if check.need(isinstance(source, dict) and {"command", "language", "sha256"} <= set(source)
                  <= {"command", "language", "sha256", "answers", "knowledge_sha256", "base_sha256"},
                  "source: needs command, language, sha256 (answers, knowledge_sha256, base_sha256 optional)"):
        command = source["command"]
        if check.need(isinstance(command, str) and command.strip() and len(command) <= MAX_INPUT, "source.command: 1-20000 characters"):
            check.need(source["sha256"] == _text_sha(command), "source.sha256: does not match the command")
        check.need(source["language"] in LOCALES, "source.language: ar or en")
        if "answers" in source:
            check.need(isinstance(source["answers"], dict) and all(isinstance(k, str) and isinstance(v, str)
                                                                   for k, v in source["answers"].items()), "source.answers: text map")
        for key in ("knowledge_sha256", "base_sha256"):
            if key in source:
                check.need(isinstance(source[key], str) and _HEX.match(source[key]), f"source.{key}: sha256 hex")
    questions = spec["open_questions"]
    question_ids = set()
    if check.need(isinstance(questions, list), "open_questions: list required"):
        for index, question in enumerate(questions):
            at = f"open_questions[{index}]"
            if not check.need(isinstance(question, dict) and set(question) == {"id", "question", "choices"},
                              f"{at}: needs exactly id, question, choices"):
                continue
            qid = question["id"]
            check.need(isinstance(qid, str) and _QUESTION.match(qid), f"{at}.id: {qid!r}")
            check.need(qid not in question_ids, f"{at}: duplicate question {qid!r}")
            question_ids.add(qid)
            _bilingual(check, question["question"], f"{at}.question")
            if question["choices"] is not None:
                _strings(check, question["choices"], f"{at}.choices", minimum=1)
    pending = bool(question_ids)
    if "intent" in spec:
        check.need(spec["intent"] in INTENTS or (pending and spec["intent"] is None), f"intent: one of {list(INTENTS)}")
    for key, test in (("title", lambda v: _bilingual(_Check(), v, "title")),
                      ("slug", lambda v: isinstance(v, str) and _KEBAB.match(v)),
                      ("product_type", lambda v: v in PRODUCT_TYPES),
                      ("domain", lambda v: isinstance(v, str) and _KEBAB.match(v))):
        value = spec[key]
        check.need((pending and value is None) or test(value), f"{key}: invalid {value!r}" + ("" if pending else " (no open question explains it)"))
    if check.need(isinstance(spec["locales"], list) and spec["locales"] and set(spec["locales"]) <= set(LOCALES)
                  and len(set(spec["locales"])) == len(spec["locales"]), "locales: non-empty subset of ar, en"):
        locales = spec["locales"]
    else:
        locales = []
    roles = spec["roles"]
    if check.need(isinstance(roles, list), "roles: list required"):
        seen = set()
        for index, role in enumerate(roles):
            at = f"roles[{index}]"
            if not check.need(isinstance(role, dict) and {"id", "permissions"} <= set(role) <= {"id", "permissions", "label"},
                              f"{at}: needs id, permissions (label optional)"):
                continue
            check.need(isinstance(role["id"], str) and _ROLE.match(role["id"]), f"{at}.id: {role['id']!r}")
            check.need(role["id"] not in seen, f"{at}: duplicate role {role['id']!r}")
            seen.add(role["id"])
            if _strings(check, role["permissions"], f"{at}.permissions", minimum=1):
                unknown = sorted(set(role["permissions"]) - set(PERMISSIONS))
                check.need(not unknown, f"{at}.permissions: unknown {unknown}; allowed {list(PERMISSIONS)}")
            if "label" in role:
                _bilingual(check, role["label"], f"{at}.label")
    names = _check_entities(check, spec["entities"], "entities")
    _check_relations(check, spec["relations"], set(names), spec["entities"] if isinstance(spec["entities"], list) else [], "relations")
    features = spec["features"]
    if check.need(isinstance(features, list), "features: list required"):
        seen = set()
        for index, feature in enumerate(features):
            at = f"features[{index}]"
            if not check.need(isinstance(feature, dict) and {"id", "title", "acceptance"} <= set(feature)
                              <= {"id", "title", "acceptance", "acceptance_ar", "entities"},
                              f"{at}: needs id, title, acceptance (acceptance_ar, entities optional)"):
                continue
            fid = feature["id"]
            if check.need(isinstance(fid, str) and _FEATURE_ID.match(fid), f"{at}.id: {fid!r}"):
                check.need(fid not in seen, f"{at}: duplicate feature {fid!r}")
                seen.add(fid)
                at = f"features({fid})"
            _bilingual(check, feature["title"], f"{at}.title")
            acceptance = feature["acceptance"]
            if check.need(isinstance(acceptance, list) and acceptance, f"{at}.acceptance: empty acceptance (at least one testable criterion)"):
                if _strings(check, acceptance, f"{at}.acceptance", minimum=1, limit=400):
                    for criterion in acceptance:
                        try:
                            parse_acceptance(criterion)
                        except SpecError as error:
                            check.need(False, f"{at}.acceptance: {error.errors[0]}")
            if "acceptance_ar" in feature:
                check.need(isinstance(feature["acceptance_ar"], list) and isinstance(acceptance, list)
                           and len(feature["acceptance_ar"]) == len(acceptance)
                           and all(isinstance(t, str) and t.strip() for t in feature["acceptance_ar"]),
                           f"{at}.acceptance_ar: one non-empty Arabic line per criterion")
            if "entities" in feature:
                check.need(isinstance(feature["entities"], list) and all(e in names for e in feature["entities"]),
                           f"{at}.entities: unknown entity in {feature['entities']!r}")
    nfr = spec["nfr"]
    if check.need(isinstance(nfr, dict) and set(nfr) == set(NFR_KEYS), f"nfr: needs exactly {list(NFR_KEYS)}"):
        for key in NFR_KEYS:
            _strings(check, nfr[key], f"nfr.{key}")
        if isinstance(nfr["i18n"], list):
            if "ar" in locales:
                check.need("ar rtl" in nfr["i18n"], "nfr.i18n: Arabic locale needs 'ar rtl'")
            if "en" in locales:
                check.need("en ltr" in nfr["i18n"], "nfr.i18n: English locale needs 'en ltr'")
    ai = spec["ai"]
    if check.need(isinstance(ai, dict) and {"needed", "use_cases"} <= set(ai) <= {"needed", "use_cases", "provider"},
                  "ai: needs needed, use_cases (provider optional)"):
        check.need(type(ai["needed"]) is bool, "ai.needed: true or false")
        if _strings(check, ai["use_cases"], "ai.use_cases"):
            check.need(ai["needed"] or not ai["use_cases"], "ai: use cases listed but needed is false")
            check.need(not ai["needed"] or ai["use_cases"] or "ai_use_case" in question_ids, "ai: needed without a use case")
        provider = ai.get("provider")
        check.need(provider is None or (isinstance(provider, str) and _KEBAB.match(provider)), "ai.provider: kebab-case or null")
        if ai["needed"]:
            check.need(provider is not None or "ai_provider" in question_ids, "ai: needed but no provider and no open question")
    constraints = spec["constraints"]
    no_paid = True
    if check.need(isinstance(constraints, dict) and set(constraints) == {"runtime", "database", "no_paid_services"},
                  "constraints: needs exactly runtime, database, no_paid_services"):
        check.need(isinstance(constraints["runtime"], str) and constraints["runtime"].strip(), "constraints.runtime: text")
        check.need(constraints["database"] in DATABASES, f"constraints.database: one of {list(DATABASES)}")
        check.need(type(constraints["no_paid_services"]) is bool, "constraints.no_paid_services: true or false")
        no_paid = constraints["no_paid_services"] is not False
    integrations = spec["integrations"]
    if check.need(isinstance(integrations, list), "integrations: list required"):
        seen = set()
        for index, item in enumerate(integrations):
            at = f"integrations[{index}]"
            if not check.need(isinstance(item, dict) and set(item) == {"id", "title", "paid", "network", "approved"},
                              f"{at}: needs exactly id, title, paid, network, approved"):
                continue
            check.need(isinstance(item["id"], str) and _KEBAB.match(item["id"]) and item["id"] not in seen, f"{at}.id: {item['id']!r}")
            seen.add(item["id"])
            _bilingual(check, item["title"], f"{at}.title")
            for key in ("paid", "network", "approved"):
                check.need(type(item[key]) is bool, f"{at}.{key}: true or false")
            if item["paid"] is True and item["approved"] is not True and no_paid:
                check.need(f"integration:{item['id']}" in question_ids,
                           f"{at}: paid service {item['id']!r} is not approved and no open question asks for approval")
    if "assumptions" in spec:
        assumptions = spec["assumptions"]
        if check.need(isinstance(assumptions, list), "assumptions: list required"):
            ids = [a.get("id") for a in assumptions if isinstance(a, dict)]
            check.need(len(ids) == len(assumptions) and len(set(ids)) == len(ids), "assumptions: objects with unique ids")
            for item in assumptions:
                if isinstance(item, dict):
                    check.need(set(item) == {"id", "ar", "en"} and all(isinstance(item[k], str) and item[k] for k in item),
                               "assumptions: each needs id, ar, en")
    if not pending:
        check.need(bool(names), "entities: a spec without open questions needs at least one entity")
        check.need(isinstance(features, list) and bool(features), "features: a spec without open questions needs at least one feature")
        check.need(isinstance(roles, list) and bool(roles), "roles: a spec without open questions needs at least one role")
    check.done()
    return {"ok": True, "schema": SCHEMA, "spec_sha256": digest(spec), "ready": not pending,
            "open_questions": sorted(question_ids), "mode": MODE}


def is_ready(spec):
    """True when the spec validates and has no open question (the build engine may consume it)."""
    return validate_spec(spec)["ready"]


# --------------------------------------------------------------------------- knowledge packs

def _strict_json(path):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise SpecError(f"{path.name}: duplicate JSON key {key!r}")
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except json.JSONDecodeError as error:
        raise SpecError(f"{path.name}: invalid JSON ({error.msg} at line {error.lineno})") from None


def _words(text):
    """Router-normalized word tokens (hamza/alef/taa marbuta/diacritics/tatweel folded), hyphens split."""
    return [part for token in router.normalize(text) for part in token.split("-") if part]


def _keywords(check, value, where, *, minimum=1):
    if not check.need(isinstance(value, dict) and set(value) == {"ar", "en"}, f"{where}: needs ar and en keyword lists"):
        return
    for lang in ("ar", "en"):
        if _strings(check, value[lang], f"{where}.{lang}", minimum=minimum, limit=80):
            check.need(all(_words(word) for word in value[lang]), f"{where}.{lang}: keyword without letters")


def _check_acceptance_items(check, items, where, sample=None):
    if not check.need(isinstance(items, list) and items, f"{where}: empty acceptance"):
        return
    for index, item in enumerate(items):
        at = f"{where}[{index}]"
        if check.need(isinstance(item, dict) and set(item) == {"en", "ar"}, f"{at}: needs en and ar"):
            check.need(isinstance(item["ar"], str) and item["ar"].strip(), f"{at}.ar: empty")
            text = _fill(item["en"], sample) if sample and isinstance(item["en"], str) else item["en"]
            try:
                parse_acceptance(text)
            except SpecError as error:
                check.need(False, f"{at}: {error.errors[0]}")


def validate_pack(pack):
    """Check one gaie.domain/1 knowledge pack."""
    check = _Check()
    allowed = {"schema", "id", "version", "title", "summary", "keywords", "product_type", "primary", "rationale",
               "roles", "entities", "relations", "features", "nfr"}
    if not check.need(isinstance(pack, dict) and set(pack) == allowed, f"pack: fields must be exactly {sorted(allowed)}"):
        check.done()
    where = f"pack {pack.get('id')}"
    check.need(pack["schema"] == PACK_SCHEMA, f"{where}: schema must be {PACK_SCHEMA}")
    check.need(isinstance(pack["id"], str) and _KEBAB.match(pack["id"]), f"{where}: id must be kebab-case")
    check.need(type(pack["version"]) is int and pack["version"] >= 1, f"{where}: version >= 1")
    for key in ("title", "summary", "rationale"):
        _bilingual(check, pack[key], f"{where}.{key}")
    _keywords(check, pack["keywords"], f"{where}.keywords")
    check.need(pack["product_type"] in PRODUCT_TYPES, f"{where}.product_type: {pack['product_type']!r}")
    names = _check_entities(check, pack["entities"], f"{where}.entities",
                            extra_entity=("synonyms", "optional", "portable"), extra_field=("keywords",))
    entities = pack["entities"] if isinstance(pack["entities"], list) else []
    core = set()
    for entity in entities:
        if isinstance(entity, dict):
            _keywords(check, entity.get("synonyms"), f"{where}.{entity.get('name')}.synonyms")
            for flag in ("optional", "portable"):
                if flag in entity:
                    check.need(type(entity[flag]) is bool, f"{where}.{entity.get('name')}.{flag}: true or false")
            check.need("label" in entity and "plural" in entity, f"{where}.{entity.get('name')}: label and plural required")
            if not entity.get("optional"):
                core.add(entity.get("name"))
            for field in entity.get("fields", []):
                if isinstance(field, dict) and "keywords" in field:
                    _keywords(check, field["keywords"], f"{where}.{entity.get('name')}.{field.get('name')}.keywords")
                if isinstance(field, dict):
                    check.need("label" in field, f"{where}.{entity.get('name')}.{field.get('name')}: label required")
    check.need(pack["primary"] in core, f"{where}.primary: must be a non-optional entity")
    _check_relations(check, pack["relations"], set(names), entities, f"{where}.relations")
    roles = pack["roles"]
    if check.need(isinstance(roles, list) and roles, f"{where}.roles: at least one"):
        probe = _Check()
        for role in roles:
            ok = isinstance(role, dict) and set(role) == {"id", "label", "permissions"} and isinstance(role.get("id"), str) \
                and _ROLE.match(role["id"]) and _bilingual(probe, role.get("label"), "label") \
                and isinstance(role.get("permissions"), list) and role["permissions"] and set(role["permissions"]) <= set(PERMISSIONS)
            check.need(ok, f"{where}.roles: invalid role {role!r}")
        check.need(any("*" in r.get("permissions", []) for r in roles if isinstance(r, dict)), f"{where}.roles: one role needs '*'")
    features = pack["features"]
    if check.need(isinstance(features, list) and features, f"{where}.features: at least one"):
        seen = set()
        for feature in features:
            if not check.need(isinstance(feature, dict) and set(feature) == {"id", "requires", "title", "acceptance"},
                              f"{where}.features: needs id, requires, title, acceptance"):
                continue
            check.need(isinstance(feature["id"], str) and _KEBAB.match(feature["id"]) and feature["id"] not in seen,
                       f"{where}.features: bad or duplicate id {feature['id']!r}")
            seen.add(feature["id"])
            check.need(isinstance(feature["requires"], list) and feature["requires"] and set(feature["requires"]) <= set(names),
                       f"{where}.features({feature['id']}).requires: known entities only")
            _bilingual(check, feature["title"], f"{where}.features({feature['id']}).title")
            _check_acceptance_items(check, feature["acceptance"], f"{where}.features({feature['id']}).acceptance")
    nfr = pack["nfr"]
    if check.need(isinstance(nfr, dict) and set(nfr) == set(NFR_KEYS), f"{where}.nfr: needs exactly {list(NFR_KEYS)}"):
        for key in NFR_KEYS:
            _strings(check, nfr[key], f"{where}.nfr.{key}")
    check.done()
    return pack


_SAMPLE = {"plural": "items", "label_en": "Item", "label_ar": "عنصر", "enum_field": "status", "enum_field_ar": "الحالة",
           "required_field": "name", "required_field_ar": "الاسم"}


def validate_lexicon(lexicon):
    """Check the shared gaie.lexicon/1 file (_common.json)."""
    check = _Check()
    allowed = {"schema", "version", "note", "control", "fields", "features", "integrations", "ai", "roles", "products",
               "databases", "locales", "nfr", "defaults"}
    if not check.need(isinstance(lexicon, dict) and set(lexicon) == allowed, f"lexicon: fields must be exactly {sorted(allowed)}"):
        check.done()
    check.need(lexicon["schema"] == LEXICON_SCHEMA, f"lexicon: schema must be {LEXICON_SCHEMA}")
    control = lexicon["control"]
    if check.need(isinstance(control, dict) and set(control) == {"negations", "new", "add", "remove", "change", "coordinators"},
                  "lexicon.control: negations, new, add, remove, change, coordinators"):
        for key, value in control.items():
            _keywords(check, value, f"lexicon.control.{key}")
    seen = set()
    for index, field in enumerate(lexicon["fields"] if isinstance(lexicon["fields"], list) else []):
        name = _check_field(check, field, f"lexicon.fields[{index}]", extra=("keywords",))
        check.need(name not in seen, f"lexicon.fields: duplicate {name!r}")
        seen.add(name)
        if isinstance(field, dict):
            check.need("label" in field, f"lexicon.fields({name}): label required")
            _keywords(check, field.get("keywords"), f"lexicon.fields({name}).keywords")
    for key, required in (("features", {"id", "title", "keywords", "needs", "acceptance"}),
                          ("integrations", {"id", "title", "paid", "network", "keywords"}),
                          ("roles", {"id", "label", "permissions", "keywords"}),
                          ("products", {"id", "keywords"}), ("databases", {"id", "keywords"}),
                          ("locales", {"id", "keywords"}), ("nfr", {"id", "category", "keywords", "add"})):
        rows = lexicon[key]
        if not check.need(isinstance(rows, list) and rows, f"lexicon.{key}: non-empty list"):
            continue
        ids = []
        for row in rows:
            if not check.need(isinstance(row, dict) and set(row) == required, f"lexicon.{key}: fields must be exactly {sorted(required)}"):
                continue
            ids.append(row["id"])
            _keywords(check, row["keywords"], f"lexicon.{key}({row['id']}).keywords")
            if key == "features":
                check.need(isinstance(row["id"], str) and _KEBAB.match(row["id"]), f"lexicon.features: id {row['id']!r}")
                _bilingual(check, row["title"], f"lexicon.features({row['id']}).title")
                check.need(isinstance(row["needs"], list) and set(row["needs"]) <= {"enum_field", "required_field"},
                           f"lexicon.features({row['id']}).needs")
                _check_acceptance_items(check, row["acceptance"], f"lexicon.features({row['id']}).acceptance", _SAMPLE)
            elif key == "integrations":
                _bilingual(check, row["title"], f"lexicon.integrations({row['id']}).title")
                check.need(type(row["paid"]) is bool and type(row["network"]) is bool, f"lexicon.integrations({row['id']}): paid/network bool")
            elif key == "roles":
                check.need(isinstance(row["id"], str) and _ROLE.match(row["id"]) and set(row["permissions"]) <= set(PERMISSIONS),
                           f"lexicon.roles({row['id']})")
            elif key == "products":
                check.need(row["id"] in PRODUCT_TYPES, f"lexicon.products: {row['id']!r}")
            elif key == "databases":
                check.need(row["id"] in DATABASES, f"lexicon.databases: {row['id']!r}")
            elif key == "locales":
                check.need(row["id"] in LOCALES, f"lexicon.locales: {row['id']!r}")
            elif key == "nfr":
                check.need(row["category"] in NFR_KEYS, f"lexicon.nfr({row['id']}).category")
                _strings(check, row["add"], f"lexicon.nfr({row['id']}).add", minimum=1)
        check.need(len(set(ids)) == len(ids), f"lexicon.{key}: duplicate ids")
    ai = lexicon["ai"]
    if check.need(isinstance(ai, dict) and set(ai) == {"generic", "use_cases", "providers"}, "lexicon.ai: generic, use_cases, providers"):
        _keywords(check, ai["generic"], "lexicon.ai.generic")
        check.need(isinstance(ai["providers"], list) and "drop" in ai["providers"]
                   and all(isinstance(p, str) and _KEBAB.match(p) for p in ai["providers"]), "lexicon.ai.providers: kebab ids incl. drop")
        for row in ai["use_cases"] if isinstance(ai["use_cases"], list) else []:
            if check.need(isinstance(row, dict) and set(row) == {"id", "title", "keywords"}, "lexicon.ai.use_cases: id, title, keywords"):
                check.need(isinstance(row["id"], str) and _KEBAB.match(row["id"]), f"lexicon.ai.use_cases: id {row['id']!r}")
                _bilingual(check, row["title"], f"lexicon.ai.use_cases({row['id']}).title")
                _keywords(check, row["keywords"], f"lexicon.ai.use_cases({row['id']}).keywords")
    defaults = lexicon["defaults"]
    if check.need(isinstance(defaults, dict) and set(defaults) == {"nfr", "constraints"}, "lexicon.defaults: nfr, constraints"):
        nfr = defaults["nfr"]
        if check.need(isinstance(nfr, dict) and set(nfr) == set(NFR_KEYS), "lexicon.defaults.nfr"):
            for key in NFR_KEYS:
                _strings(check, nfr[key], f"lexicon.defaults.nfr.{key}")
        constraints = defaults["constraints"]
        check.need(isinstance(constraints, dict) and set(constraints) == {"runtime", "database", "no_paid_services"}
                   and constraints.get("database") in DATABASES and constraints.get("no_paid_services") is True,
                   "lexicon.defaults.constraints: runtime, database, no_paid_services=true")
    check.done()
    return lexicon


def load_knowledge(directory=None):
    """Validated lexicon and domain packs ({'lexicon', 'packs', 'sha256'}) from governance/domains/."""
    root = pathlib.Path(directory) if directory is not None else DOMAINS
    if not root.is_dir():
        raise SpecError(f"knowledge directory not found: {root.name}")
    paths = sorted(root.glob("*.json"))
    for path in paths:
        if path.is_symlink():
            raise SpecError(f"{path.name}: symlinked knowledge files are refused")
    lexicon_path = root / "_common.json"
    if not lexicon_path.is_file():
        raise SpecError("_common.json lexicon is missing")
    lexicon = validate_lexicon(_strict_json(lexicon_path))
    packs = {}
    for path in paths:
        if path.name.startswith("_"):
            continue
        pack = validate_pack(_strict_json(path))
        if pack["id"] != path.stem:
            raise SpecError(f"{path.name}: pack id {pack['id']!r} must equal the file name")
        packs[pack["id"]] = pack
    if not packs:
        raise SpecError("no domain packs found")
    owners = {}
    for pack in packs.values():
        phrases = [("keyword", w) for lang in LOCALES for w in pack["keywords"][lang]]
        phrases += [("entity", w) for e in pack["entities"] for lang in LOCALES for w in e["synonyms"][lang]]
        for kind, word in phrases:
            key = (kind, tuple(_words(word)))
            if owners.setdefault(key, pack["id"]) != pack["id"]:
                raise SpecError(f"{kind} phrase {word!r} is claimed by packs {owners[key]} and {pack['id']}")
    return {"lexicon": lexicon, "packs": packs, "sha256": digest({"lexicon": lexicon, "packs": packs})}


def domain_packs(directory=None):
    """Summary of the available domain packs (id, version, title, entities, features)."""
    knowledge = load_knowledge(directory)
    return {"mode": MODE, "knowledge_sha256": knowledge["sha256"], "packs": [
        {"id": p["id"], "version": p["version"], "title": p["title"], "product_type": p["product_type"],
         "entities": [e["name"] for e in p["entities"] if not e.get("optional")],
         "optional_entities": [e["name"] for e in p["entities"] if e.get("optional")],
         "features": [f["id"] for f in p["features"]]} for p in knowledge["packs"].values()]}


# --------------------------------------------------------------------------- text analysis

def _variants(token):
    """Spellings a command token may stand for: Arabic clitic prefixes (و ف ب ل ك ال لل) and English plurals."""
    out = {token}
    if _ARABIC.search(token):
        out.add(router._strip(token))
        for prefix in ("لل", "ولل", "فلل"):
            if token.startswith(prefix) and len(token) - len(prefix) >= 2:
                out.add(token[len(prefix):])
    else:
        if len(token) > 4 and token.endswith("ies"):
            out.add(token[:-3] + "y")
        if len(token) > 3 and token.endswith("es"):
            out.add(token[:-2])
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            out.add(token[:-1])
    return out


def _entries(knowledge, base):
    """Phrase index by first token: lexicon rows {cat, key, phrase, rank, order} and control-word rows."""
    lexicon, packs = knowledge["lexicon"], knowledge["packs"]
    rows = []

    def add(category, key, words):
        for word in [w for lang in LOCALES for w in words[lang]] if isinstance(words, dict) else words:
            phrase = tuple(_words(word))
            if phrase:
                rows.append({"cat": category, "key": key, "phrase": phrase, "rank": _RANK[category], "order": len(rows)})

    if base is not None:
        for entity in base["entities"]:
            words = [entity["name"], _CAMEL.sub(" ", entity["name"]), entity.get("plural", "").replace("-", " ")]
            words += [entity["label"][lang] for lang in LOCALES if isinstance(entity.get("label"), dict)]
            add("entity", ("base", entity["name"]), [w for w in words if w])
    for pack in packs.values():
        add("domain", pack["id"], pack["keywords"])
        for entity in pack["entities"]:
            add("entity", (pack["id"], entity["name"]), entity["synonyms"])
    for field in _field_lexicon(knowledge).values():
        add("field", field["name"], field["keywords"])
    for row in lexicon["features"]:
        add("feature", row["id"], row["keywords"])
    for row in lexicon["integrations"]:
        add("integration", row["id"], row["keywords"])
    add("ai", "generic", lexicon["ai"]["generic"])
    for row in lexicon["ai"]["use_cases"]:
        add("ai", row["id"], row["keywords"])
    for category, key in (("role", "roles"), ("product", "products"), ("database", "databases"), ("locale", "locales"), ("nfr", "nfr")):
        for row in lexicon[key]:
            add(category, row["id"], row["keywords"])
    index = {}
    for row in rows:
        index.setdefault(row["phrase"][0], []).append(row)
    control, order = {}, 0
    for name, words in lexicon["control"].items():
        for word in (w for lang in LOCALES for w in words[lang]):
            phrase = tuple(_words(word))
            control.setdefault(phrase[0], []).append({"cat": name, "phrase": phrase, "order": order})
            order += 1
    return index, control


def _field_lexicon(knowledge):
    """Addable fields: the shared lexicon first, then pack fields that declare keywords (first definition wins)."""
    fields = {}
    for field in knowledge["lexicon"]["fields"]:
        fields.setdefault(field["name"], field)
    for pack in knowledge["packs"].values():
        for entity in pack["entities"]:
            for field in entity["fields"]:
                if "keywords" in field:
                    fields.setdefault(field["name"], field)
    return fields


def _scan(tokens, index):
    variants = [_variants(token) for token in tokens]
    hits, seen = [], set()
    for start in range(len(tokens)):
        for variant in sorted(variants[start]):
            for row in index.get(variant, ()):
                size = len(row["phrase"])
                if (start, row["order"]) in seen or start + size > len(tokens):
                    continue
                if all(row["phrase"][k] in variants[start + k] for k in range(1, size)):
                    seen.add((start, row["order"]))
                    hits.append((start, size, row))
    return hits


def _analyse(text, index, control):
    """Sentences -> ordered hits with negation and add/remove mode resolved per clause.

    A remove verb («احذف», "remove") switches the clause to removal only as a command: at the start of
    the clause, after a coordinator, or with the conjunction و/ف attached ("members can delete their own
    comments" removes nothing). Any lexicon phrase after a negation in its clause is negated.
    """
    sentences = []
    for raw_sentence in _SENTENCES.split(text):
        hits, words, spans = [], [], []
        for raw_clause in _CLAUSES.split(raw_sentence):
            tokens = _words(raw_clause)
            if not tokens:
                continue
            offset, clause = len(words), (len(sentences), len(words))
            words.extend(tokens)
            spans.append((offset, offset + len(tokens)))
            candidates = sorted(_scan(tokens, index), key=lambda h: (-h[1], h[2]["rank"], h[0], h[2]["order"]))
            taken, chosen = [False] * len(tokens), []
            for start, size, row in candidates:
                if any(taken[start:start + size]):
                    continue
                for k in range(start, start + size):
                    taken[k] = True
                chosen.append((start, size, row, False))
            for start, size, row in candidates:  # an entity spelled exactly like a domain keyword still names its owner
                if row["cat"] == "entity" and any(c[2]["cat"] == "domain" and c[0] == start and c[1] == size
                                                  and c[2]["key"] == row["key"][0] for c in chosen):
                    chosen.append((start, size, row, True))
            signals = sorted(((s, n, r["cat"]) for s, n, r in _scan(tokens, control)), key=lambda h: (h[0], -h[1]))
            coordinators = {s for s, n, cat in signals if cat == "coordinators"}
            for start, size, row, owner_only in sorted(chosen, key=lambda c: (c[0], c[3], c[2]["order"])):
                negated = any(cat == "negations" and s < start for s, n, cat in signals)
                mode = "add"
                for s, n, cat in signals:
                    if s >= start:
                        break
                    if cat == "add":
                        mode = "add"
                    elif cat == "remove" and (s == 0 or (s - 1) in coordinators or tokens[s][:1] in "وف"):
                        mode = "remove"
                hits.append({"cat": row["cat"], "key": row["key"], "pos": offset + start, "end": offset + start + size,
                             "negated": negated, "mode": mode, "owner_only": owner_only, "clause": clause})
            hits.extend({"cat": "signal:" + cat, "key": cat, "pos": offset + s, "end": offset + s + n, "negated": False,
                         "mode": "add", "owner_only": True, "clause": clause} for s, n, cat in signals)
        sentences.append({"hits": hits, "raw": words, "clauses": spans})
    return sentences


# Words that name a locale or a role inside a removal or negation ("remove the Arabic locale",
# "without english", «بدون الإنجليزية», "remove the user role", «احذف دور المستخدم»), and the
# filler words allowed between the remove/negation word and that name. Matched on router-normalized
# tokens with the same clitic/plural variants as the lexicon.
_LANGUAGE_NAMES = {"ar": ("arabic", "عربي", "عربية", "العربية"),
                   "en": ("english", "إنجليزي", "إنجليزية", "الإنجليزية", "انجليزي", "انجليزية", "إنكليزي", "إنكليزية")}
_ROLE_WORDS = ("role", "roles", "دور", "أدوار", "الدور", "الأدوار")
_REMOVAL_FILLERS = ("the", "a", "an", "any", "both", "and", "or", "nor", "in", "use", "using", "language", "languages",
                    "locale", "locales", "interface", "ui", "version", "support", "translation", "translations", "اللغة",
                    "لغة", "اللغتين", "واجهة", "الواجهة", "النسخة", "نسخة", "دعم", "ترجمة")


def _normalized(words):
    return frozenset(token for word in words for token in _words(word))


_LANGUAGE_TOKENS = {key: _normalized(words) for key, words in _LANGUAGE_NAMES.items()}
_ROLE_TOKENS = _normalized(_ROLE_WORDS)
_FILLER_TOKENS = _normalized(_REMOVAL_FILLERS)


# --------------------------------------------------------------------------- builder

_Q = {
    "intent": ("هل هذا نظام جديد أم تعديل على نظام قائم؟", "Is this a new system or a change to an existing one?"),
    "base": ("هذا الأمر يعدّل نظامًا قائمًا: مرّر مواصفته الحالية (gaie.spec/1) في الوسيط base.",
             "This command changes an existing system: pass its current gaie.spec/1 as base."),
    "domain": ("ما مجال النظام المطلوب؟", "Which domain is the system for?"),
    "product_type": ("ما نوع المنتج المطلوب؟", "Which product type is wanted?"),
    "database": ("أي قاعدة بيانات تُستخدم؟", "Which database should be used?"),
    "field_entity": ("إلى أي كيان يُضاف الحقل «{name}»؟", "Which entity gets the field '{name}'?"),
    "remove_field": ("من أي كيان يُحذف الحقل «{name}»؟", "Which entity loses the field '{name}'?"),
    "feature_entity": ("على أي كيان تُطبَّق الميزة «{name}»؟", "Which entity does the feature '{name}' apply to?"),
    "relation": ("بأي كيان يرتبط «{name}» (يتبعه)، أو none إن كان مستقلًا؟",
                 "Which entity does '{name}' belong to (many-to-one), or none if it stands alone?"),
    "ai_use_case": ("ما قدرة الذكاء الاصطناعي المطلوبة؟", "Which AI capability is needed?"),
    "ai_provider": ("الذكاء الاصطناعي يحتاج نموذجًا: نموذج محلي، أم واجهة مدفوعة بموافقة المالك، أم حذف الجزء الذكي؟",
                    "AI needs a model: a local model, an owner-approved paid API, or drop the AI part?"),
    "integration": ("«{name}» خدمة مدفوعة: هل توافق عليها أم تُستبعد؟", "'{name}' is a paid service: approve or exclude it?"),
    "locale_removal": ("الأمر ينفي اللغة «{name}» في تعديل نظام قائم: هل تُحذف هذه اللغة من النظام أم تبقى؟",
                       "The command negates the locale '{name}' of an existing system: remove it or keep it?"),
    "locale_needed": ("«{name}» هي اللغة الوحيدة للنظام فلا يمكن حذفها: أكّد إبقاءها أو أضف لغة أخرى في الأمر.",
                      "'{name}' is the only locale of the system and cannot be removed: confirm keeping it, or add another locale in the command."),
    "role_removal": ("الأمر ينفي الدور «{name}» في تعديل نظام قائم: هل يُحذف هذا الدور أم يبقى؟",
                     "The command negates the role '{name}' of an existing system: remove it or keep it?"),
    "role_needed": ("الدور «{name}» لا يُحذف: هو الدور الوحيد أو دور الصلاحيات الكاملة (*) الوحيد. أكّد إبقاءه.",
                    "The role '{name}' cannot be removed: it is the only role or the only full-permission (*) role. Confirm keeping it."),
}
_A = {
    "domain-pack": ("طُبّقت حزمة المجال «{name}» الإصدار {version} بكياناتها الافتراضية: {entities}.",
                    "Domain pack '{name}' v{version} applied with its default entities: {entities}."),
    "domain-weak": ("حُدد المجال «{name}» من أسماء الكيانات المذكورة فقط ({entities}).",
                    "Domain '{name}' inferred only from the entities the command names ({entities})."),
    "pack-rationale": ("{ar}", "{en}"),
    "product-default": ("نوع المنتج الافتراضي للمجال: {name}.", "Default product type of the domain: {name}."),
    "mobile-pwa": ("تطبيق الجوال يُسلَّم تطبيق ويب قابلًا للتثبيت (PWA) على بيئة بايثون القياسية؛ التطبيق الأصلي يحتاج قرارًا منفصلًا.",
                   "The mobile app is delivered as an installable web app (PWA) on the stdlib runtime; a native app needs a separate decision."),
    "locales-default": ("اللغات: {name} (العربية من اليمين لليسار).", "Locales: {name} (Arabic right-to-left)."),
    "constraints-default": ("القيود الافتراضية: بايثون القياسية وSQLite وبلا خدمات مدفوعة.",
                            "Default constraints: Python standard library, SQLite, no paid services."),
    "excluded": ("استُبعد بطلب الأمر: {name}.", "Excluded by the command: {name}."),
    "removed": ("حُذف بطلب الأمر: {name}.", "Removed by the command: {name}."),
    "ignored": ("ذُكر «{name}» وهو من مجال آخر ({entities}) فلم يُضف.", "'{name}' belongs to another domain ({entities}) and was not added."),
    "adopted": ("أُضيف الكيان «{name}» من حزمة {entities}.", "Entity '{name}' adopted from pack {entities}."),
    "optional-field": ("الحقل {name} أُضيف اختياريًا كي لا تنكسر السجلات القائمة.", "Field {name} added as optional so existing rows stay valid."),
    "standalone": ("الكيان «{name}» مستقل بلا علاقة (بإجابة المالك).", "Entity '{name}' stands alone without a relation (owner answer)."),
    "primary-kept": ("الكيان الأساسي «{name}» لا يُستبعد من حزمة مجاله.", "The primary entity '{name}' of the pack cannot be excluded."),
    "ai-dropped": ("أُلغي جزء الذكاء الاصطناعي بإجابة المالك.", "The AI part was dropped by the owner's answer."),
    "answer-moot": ("الإجابة {name} لم تعد لازمة بعد الإجابات الأخرى فلم تُطبَّق.",
                    "Answer {name} became moot after the other answers and was not applied."),
    "feature-na": ("الميزة «{name}» تحتاج حقل تعداد ولا يوجد كيان مناسب.", "Feature '{name}' needs an enum field and no entity has one."),
}


def _assumption(key, suffix="", **values):
    ar, en = _A[key]
    filled = {k: (", ".join(v) if isinstance(v, (list, tuple)) else str(v)) for k, v in values.items()}
    return {"id": key + (":" + suffix if suffix else ""), "ar": ar.format(**filled), "en": en.format(**filled)}


def _fill(template, values):
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


class _Builder:
    def __init__(self, text, language, knowledge, answers, base, base_sha, strict=True):
        self.text, self.language, self.knowledge, self.strict = text, language, knowledge, strict
        self.lexicon, self.packs = knowledge["lexicon"], knowledge["packs"]
        self.fields = _field_lexicon(knowledge)
        self.answers, self.used = dict(answers), set()
        self.base, self.base_sha = base, base_sha
        self.questions, self.assumptions = {}, {}
        self.excluded = {"entity": set(), "feature": set(), "integration": set(), "ai": False}
        self.touched, self.added, self.removed_roles = [], [], []
        self.generic = []

    # -- questions and assumptions
    def ask(self, kind, choices, name="", suffix=""):
        qid = kind + (":" + suffix if suffix else "")
        if qid in self.answers:
            value = self.answers[qid]
            if choices is not None and value not in choices:
                raise SpecError(f"answer {qid}: {value!r} is not one of {choices}")
            self.used.add(qid)
            return value
        ar, en = _Q[kind]
        self.questions[qid] = {"id": qid, "question": {"ar": ar.format(name=name), "en": en.format(name=name)},
                               "choices": list(choices) if choices is not None else None}
        return None

    def note(self, key, suffix="", **values):
        item = _assumption(key, suffix, **values)
        self.assumptions.setdefault(item["id"], item)

    # -- helpers on the spec under construction
    @staticmethod
    def entity(spec, name):
        return next((e for e in spec["entities"] if e["name"] == name), None)

    def pack_entity(self, source, name):
        pack = self.packs.get(source)
        return next((e for e in pack["entities"] if e["name"] == name), None) if pack else None

    @staticmethod
    def plain_entity(entity):
        return {"name": entity["name"], "label": copy.deepcopy(entity["label"]), "plural": entity["plural"],
                "fields": [{k: copy.deepcopy(v) for k, v in f.items() if k != "keywords"} for f in entity["fields"]]}

    def link(self, spec, source):
        """Relations of a pack whose two ends are present."""
        names = {e["name"] for e in spec["entities"]}
        pack = self.packs.get(source)
        for relation in pack["relations"] if pack else []:
            key = (relation["from"], relation.get("field", _snake(relation["to"])))
            if relation["from"] in names and relation["to"] in names and key not in {
                    (r["from"], r.get("field", _snake(r["to"]))) for r in spec["relations"]}:
                spec["relations"].append(copy.deepcopy(relation))

    def drop_entity(self, spec, name):
        for relation in spec["relations"]:
            other = relation["from"] if relation["to"] == name else None
            if other and other != name and other not in self.touched:
                self.touched.append(other)
        spec["entities"] = [e for e in spec["entities"] if e["name"] != name]
        spec["relations"] = [r for r in spec["relations"] if name not in (r["from"], r["to"])]
        spec["features"] = [f for f in spec["features"] if name not in f.get("entities", [])]
        self.generic = [f for f in self.generic if name not in f.get("entities", [])]

    def drop_field(self, spec, owner, field_name):
        entity = self.entity(spec, owner)
        if entity is None or all(f["name"] != field_name for f in entity["fields"]):
            return False
        if len(entity["fields"]) == 1:
            return False
        entity["fields"] = [f for f in entity["fields"] if f["name"] != field_name]
        pattern = re.compile(r"\b" + re.escape(field_name) + r"\b")
        keep = lambda f: owner not in f.get("entities", []) or f["id"] == "manage-" + entity["plural"] \
            or not any(pattern.search(text) for text in f["acceptance"])
        spec["features"] = [f for f in spec["features"] if keep(f)]
        self.generic = [f for f in self.generic if keep(f)]
        if owner not in self.touched:
            self.touched.append(owner)
        return True

    @staticmethod
    def owner(sentence, hit, owners):
        """Entity a field/feature mention belongs to, or None when the words do not link them."""
        covered = {p for h in sentence["hits"] if h["cat"] in ("field", "feature") for p in range(h["pos"], h["end"])}
        following = [o for o in owners if o["pos"] >= hit["end"]]
        if following:
            first = following[0]
            gap = sentence["raw"][hit["end"]:first["pos"]]
            raw = first["raw"]
            arabic = bool(_ARABIC.search(raw))
            linked = any(t in _LINKS for t in gap) or (arabic and raw[:1] == "ل") or (
                not gap and first["clause"] == hit["clause"] and arabic and raw[:1] not in "وف")
            if linked and all(t in _GAP or (hit["end"] + i) in covered for i, t in enumerate(gap)):
                return first["name"]
        preceding = [o for o in owners if o["end"] <= hit["pos"]]
        if preceding:
            last = preceding[-1]
            gap = sentence["raw"][last["end"]:hit["pos"]]
            if any(t in _HAS for t in gap) or (not gap and last["clause"] == hit["clause"]):
                return last["name"]
        return None

    def field_def(self, name, change):
        field = {k: copy.deepcopy(v) for k, v in self.fields[name].items() if k != "keywords"}
        if change and field["required"] and "default" not in field:
            field["required"] = False
        return field

    def add_field(self, spec, owner, name, change):
        entity = self.entity(spec, owner)
        if any(f["name"] == name for f in entity["fields"]):
            return
        relation_fields = {r.get("field", _snake(r["to"])) for r in spec["relations"] if r["from"] == owner}
        if name in relation_fields or name.endswith("_id") and name[:-3] in relation_fields:
            return
        field = self.field_def(name, change)
        if change and field["required"] is False and self.fields[name]["required"]:
            self.note("optional-field", f"{owner}.{name}", name=f"{owner}.{name}")
        entity["fields"].append(field)
        if owner not in self.touched:
            self.touched.append(owner)

    # -- pipeline
    def run(self):
        index, control = _entries(self.knowledge, self.base)
        sentences = _analyse(self.text, index, control)
        intent = self.intent(sentences)
        empty = {"title": None, "slug": None, "product_type": None, "domain": None, "locales": self.default_locales(),
                 "roles": [], "entities": [], "relations": [], "features": [], "ai": {"needed": False, "use_cases": [], "provider": None},
                 "integrations": [], "constraints": copy.deepcopy(self.lexicon["defaults"]["constraints"])}
        if intent == "change" and self.base is None:
            self.ask("base", None)
            return self.finish(empty, intent, None, sentences, partial=True)
        if self.base is not None:
            spec = copy.deepcopy({k: v for k, v in self.base.items() if k not in ("open_questions", "source", "schema", "mode")})
            for item in self.base.get("assumptions", []):
                self.assumptions.setdefault(item["id"], item)
            spec.pop("assumptions", None)
            spec.setdefault("intent", "change")
            pack = self.packs.get(spec["domain"])
            self.apply(spec, sentences, pack, change=True)
            return self.finish(spec, "change", pack, sentences)
        pack = self.domain(sentences)
        if pack is None:
            return self.finish(empty, intent, None, sentences, partial=True)
        spec = self.skeleton(pack, sentences)
        self.apply(spec, sentences, pack, change=False)
        return self.finish(spec, intent, pack, sentences)

    def intent(self, sentences):
        try:
            verbs = router.classify(self.text, router.policy())[0]
        except (router.RouteError, OSError, KeyError, ValueError):
            verbs = []
        signals = {h["key"] for s in sentences for h in s["hits"] if h["cat"].startswith("signal:")}
        new = "build" in verbs or "new" in signals
        change = bool({"upgrade", "accelerate", "repair"} & set(verbs)) or bool({"add", "remove", "change"} & signals)
        if self.base is not None:
            if new and not change:
                raise SpecError("base= was given but the command asks for a new system")
            return "change"
        if new:
            return "new-system"
        if change:
            return "change"
        return self.ask("intent", list(INTENTS))

    def domain(self, sentences):
        hits = [h for s in sentences for h in s["hits"] if not h["negated"] and h["mode"] == "add"]
        strong = sorted({h["key"] for h in hits if h["cat"] == "domain"})
        weak = {}
        for h in hits:
            if h["cat"] == "entity" and h["key"][0] in self.packs and not h["owner_only"]:
                weak.setdefault(h["key"][0], set()).add(h["key"][1])
        if len(strong) == 1:
            return self.packs[strong[0]]
        candidates = strong or sorted(weak)
        if len(candidates) == 1:
            pack = self.packs[candidates[0]]
            self.note("domain-weak", name=pack["id"], entities=sorted(weak[pack["id"]]))
            return pack
        answer = self.ask("domain", candidates if len(candidates) > 1 else sorted(self.packs))
        return self.packs[answer] if answer else None

    def default_locales(self):
        return [self.language, "en" if self.language == "ar" else "ar"]

    def skeleton(self, pack, sentences):
        mentioned = {h["key"][1] for s in sentences for h in s["hits"] if h["cat"] == "entity" and h["key"][0] == pack["id"]
                     and not h["negated"] and h["mode"] == "add"}
        entities = [self.plain_entity(e) for e in pack["entities"] if not e.get("optional") or e["name"] in mentioned]
        spec = {"intent": None, "title": copy.deepcopy(pack["title"]), "slug": pack["id"], "product_type": pack["product_type"],
                "domain": pack["id"], "locales": self.default_locales(), "roles": [
                    {"id": r["id"], "label": copy.deepcopy(r["label"]), "permissions": list(r["permissions"])} for r in pack["roles"]],
                "entities": entities, "relations": [], "features": [], "ai": {"needed": False, "use_cases": [], "provider": None},
                "integrations": [], "constraints": copy.deepcopy(self.lexicon["defaults"]["constraints"])}
        self.link(spec, pack["id"])
        self.note("domain-pack", name=pack["id"], version=pack["version"], entities=[e["name"] for e in entities])
        self.note("pack-rationale", ar=pack["rationale"]["ar"], en=pack["rationale"]["en"])
        self.note("constraints-default")
        return spec

    def apply(self, spec, sentences, pack, change):
        mentions = {key: [] for key in ("integration", "ai", "role", "nfr", "product", "database", "locale")}
        removals, role_words = self.removal_requests(spec, sentences)
        for sentence in sentences:
            hits = [h for h in sentence["hits"] if not h["cat"].startswith("signal:")
                    and not (h["cat"] == "entity" and (h["clause"][0], h["pos"]) in role_words)]
            # "remove X from Y" / "without X for Y": Y only names the owner of the removed X.
            targets = {(h["clause"], h["mode"], h["negated"]) for h in hits if h["cat"] in ("field", "feature")}
            owners = []
            for hit in (h for h in hits if h["cat"] == "entity"):
                name = self.entity_hit(spec, hit, pack, change, (hit["clause"], hit["mode"], hit["negated"]) in targets)
                if name:
                    owners.append({"pos": hit["pos"], "end": hit["end"], "name": name, "raw": sentence["raw"][hit["pos"]],
                                   "clause": hit["clause"]})
            owners.sort(key=lambda o: (o["pos"], o["end"]))
            for hit in hits:
                if hit["cat"] == "field":
                    self.field_hit(spec, sentence, hit, owners, change)
                elif hit["cat"] == "feature":
                    self.feature_hit(spec, sentence, hit, owners, pack, change)
                elif hit["cat"] in mentions:
                    mentions[hit["cat"]].append(hit)
        self.relations(spec)
        self.products(spec, mentions["product"], pack, change)
        self.databases(spec, mentions["database"])
        self.locales(spec, mentions["locale"], change, removals["locale"])
        self.roles(spec, mentions["role"], change, removals["role"])
        self.integrations(spec, mentions["integration"], change)
        self.ai(spec, mentions["ai"], change)
        self.features(spec, pack, change)
        self.nfr(spec, mentions["nfr"], pack, change)

    def entity_hit(self, spec, hit, pack, change, has_targets):
        source, name = hit["key"]
        present = self.entity(spec, name) is not None
        dropping = hit["mode"] == "remove" or (hit["negated"] and not change)
        if hit["owner_only"] or (dropping and has_targets):
            return name if present else None
        if hit["negated"] and change:
            return name if present else None
        if dropping:
            if pack and name == pack["primary"] and not change:
                self.note("primary-kept", name, name=name)
                return name
            self.excluded["entity"].add(name)
            if present:
                self.drop_entity(spec, name)
                self.note("removed" if change else "excluded", name, name=name)
            elif not change:
                self.note("excluded", name, name=name)
            return None
        if present:
            return name
        if name in self.excluded["entity"]:
            return None
        if source == "base":
            return None
        definition = self.pack_entity(source, name)
        if not (pack and source == pack["id"]) and not definition.get("portable"):
            self.note("ignored", name, name=name, entities=source)
            return None
        spec["entities"].append(self.plain_entity(definition))
        self.added.append(name)
        self.link(spec, source)
        if pack and source != pack["id"]:
            self.note("adopted", name, name=name, entities=source)
        return name

    def field_hit(self, spec, sentence, hit, owners, change):
        name = hit["key"]
        owner = self.owner(sentence, hit, owners)
        dropping = hit["mode"] == "remove" or (hit["negated"] and not change)
        if hit["negated"] and change:
            return
        holders = sorted(e["name"] for e in spec["entities"] if any(f["name"] == name for f in e["fields"]))
        if dropping:
            if owner:
                if self.drop_field(spec, owner, name):
                    self.note("removed" if change else "excluded", f"{owner}.{name}", name=f"{owner}.{name}")
                return
            if not change:
                for holder in holders:
                    if self.drop_field(spec, holder, name):
                        self.note("excluded", f"{holder}.{name}", name=f"{holder}.{name}")
                return
            target = holders[0] if len(holders) == 1 else (self.ask("remove_field", holders, name, name) if holders else None)
            if target and self.drop_field(spec, target, name):
                self.note("removed", f"{target}.{name}", name=f"{target}.{name}")
            return
        if owner:
            self.add_field(spec, owner, name, change)
            return
        if holders or not spec["entities"]:
            return
        target = self.ask("field_entity", sorted(e["name"] for e in spec["entities"]), name, name)
        if target:
            self.add_field(spec, target, name, change)

    def feature_hit(self, spec, sentence, hit, owners, pack, change):
        template = next(row for row in self.lexicon["features"] if row["id"] == hit["key"])
        dropping = hit["mode"] == "remove" or (hit["negated"] and not change)
        if hit["negated"] and change:
            return
        owner = self.owner(sentence, hit, owners)
        if dropping:
            prefix = template["id"] + "-"
            self.excluded["feature"].add(template["id"] if owner is None else f"{template['id']}-{self.entity(spec, owner)['plural']}")
            for collection in (spec["features"], self.generic):
                for feature in [f for f in collection if f["id"].startswith(prefix)
                                and (owner is None or f["id"] == f"{template['id']}-{self.entity(spec, owner)['plural']}")]:
                    collection.remove(feature)
                    self.note("removed" if change else "excluded", feature["id"], name=feature["id"])
            return
        if owner is None and spec["entities"]:
            primary = pack["primary"] if pack and self.entity(spec, pack["primary"]) else spec["entities"][0]["name"]
            owner = primary
        if owner is None:
            return
        if "enum_field" in template["needs"] and not self.enum_of(self.entity(spec, owner)):
            fitting = sorted(e["name"] for e in spec["entities"] if self.enum_of(e))
            if not fitting:
                self.note("feature-na", template["id"], name=template["id"])
                return
            owner = self.ask("feature_entity", fitting, template["id"], template["id"])
            if owner is None:
                return
        feature = self.instantiate(template, self.entity(spec, owner))
        if feature["id"] in self.excluded["feature"] or template["id"] in self.excluded["feature"]:
            return
        if all(f["id"] != feature["id"] for f in spec["features"] + self.generic):
            self.generic.append(feature)

    @staticmethod
    def enum_of(entity):
        return next((f for f in entity["fields"] if f["type"] == "enum"), None)

    def instantiate(self, template, entity):
        enum = self.enum_of(entity)
        required = next((f for f in entity["fields"] if f["required"] and "default" not in f),
                        next((f for f in entity["fields"] if f["required"]), entity["fields"][0]))
        values = {"plural": entity["plural"], "label_en": _label(entity, "en"), "label_ar": _label(entity, "ar"),
                  "enum_field": enum["name"] if enum else "", "enum_field_ar": _label(enum, "ar") if enum else "",
                  "required_field": required["name"], "required_field_ar": _label(required, "ar")}
        return {"id": f"{template['id']}-{entity['plural']}",
                "title": {lang: _fill(template["title"][lang], values) for lang in LOCALES},
                "acceptance": [_fill(item["en"], values) for item in template["acceptance"]],
                "acceptance_ar": [_fill(item["ar"], values) for item in template["acceptance"]],
                "entities": [entity["name"]]}

    def relations(self, spec):
        names = [e["name"] for e in spec["entities"]]
        if len(names) < 2:
            return
        for name in names:
            if any(name in (r["from"], r["to"]) for r in spec["relations"]) or f"standalone:{name}" in self.assumptions:
                continue
            answer = self.ask("relation", sorted(n for n in names if n != name) + ["none"], name, name)
            if answer == "none":
                self.note("standalone", name, name=name)
            elif answer:
                field = _snake(answer)
                own = {f["name"] for f in self.entity(spec, name)["fields"]}
                while field in own or f"{field}_id" in own:
                    field += "_ref"
                spec["relations"].append({"from": name, "to": answer, "kind": "many-to-one", "required": False, "field": field})
                if name not in self.touched:
                    self.touched.append(name)

    def products(self, spec, hits, pack, change):
        found = sorted({h["key"] for h in hits if not h["negated"]})
        if len(found) == 1:
            spec["product_type"] = found[0]
        elif len(found) > 1:
            answer = self.ask("product_type", found)
            if answer:
                spec["product_type"] = answer
        elif not change and pack:
            self.note("product-default", name=pack["product_type"])
        if spec["product_type"] == "mobile-app":
            self.note("mobile-pwa")

    def databases(self, spec, hits):
        found = sorted({h["key"] for h in hits if not h["negated"]})
        if len(found) == 1:
            spec["constraints"]["database"] = found[0]
        elif len(found) > 1:
            answer = self.ask("database", found)
            if answer:
                spec["constraints"]["database"] = answer

    def locales(self, spec, hits, change, removals=()):
        found = sorted({h["key"] for h in hits if not h["negated"] and h["mode"] == "add"})
        if len(found) == 1:
            spec["locales"] = found
        elif not change:
            self.note("locales-default", name=spec["locales"])
        for key, how in removals:
            if key not in spec["locales"]:
                continue  # already absent: the request holds
            if len(spec["locales"]) == 1:
                self.ask("locale_needed", ["keep"], key, key)
                continue
            if how == "negated" and change and self.ask("locale_removal", ["remove", "keep"], key, key) != "remove":
                continue
            spec["locales"] = [locale for locale in spec["locales"] if locale != key]
            self.note("removed" if change else "excluded", "locale-" + key, name=key)

    def roles(self, spec, hits, change=False, removals=()):
        present = {r["id"] for r in spec["roles"]}
        dropped = {key for key, _ in removals}
        for hit in hits:
            if hit["negated"] or hit["mode"] == "remove" or hit["key"] in present or hit["key"] in dropped:
                continue
            row = next(r for r in self.lexicon["roles"] if r["id"] == hit["key"])
            spec["roles"].append({"id": row["id"], "label": copy.deepcopy(row["label"]), "permissions": list(row["permissions"])})
            present.add(row["id"])
        for key, how in removals:
            role = next((r for r in spec["roles"] if r["id"] == key), None)
            if role is None:
                continue
            others = [r for r in spec["roles"] if r["id"] != key]
            if not others or ("*" in role["permissions"] and not any("*" in r["permissions"] for r in others)):
                self.ask("role_needed", ["keep"], key, key)
                continue
            if how == "negated" and change and self.ask("role_removal", ["remove", "keep"], key, key) != "remove":
                continue
            spec["roles"] = others
            self.removed_roles.append(key)
            self.note("removed" if change else "excluded", "role-" + key, name=key)

    def removal_requests(self, spec, sentences):
        """Locales and roles that a removal ("remove the Arabic locale") or a negation ("without english")
        names directly; also the (sentence, position) of each role name, which then names no entity.

        A name counts only when it follows the remove/negation word in the same clause with nothing but
        filler words in between (a remove word only at a command position, as in _analyse) and ends the
        clause or is followed by a filler, a role word or another name ("no arabic title" names a field,
        not the locale). A role name needs the word role/دور next to it unless it is a lexicon role keyword.
        """
        removals, role_words = {"locale": [], "role": []}, set()
        lexicon_roles = {row["id"]: row for row in self.lexicon["roles"]}
        phrases = []
        for role in spec["roles"]:
            words = [role["id"].replace("-", " ").replace("_", " ")]
            if isinstance(role.get("label"), dict):
                words += [role["label"][lang] for lang in LOCALES if role["label"].get(lang)]
            keywords = lexicon_roles[role["id"]]["keywords"] if role["id"] in lexicon_roles else {}
            words += [w for lang in LOCALES for w in keywords.get(lang, [])]
            for word in words:
                phrase = tuple(_words(word))
                if phrase:
                    phrases.append((phrase, role["id"], word in [w for lang in LOCALES for w in keywords.get(lang, [])]))
        phrases.sort(key=lambda row: -len(row[0]))
        for index, sentence in enumerate(sentences):
            words = sentence["raw"]
            variants = [_variants(word) for word in words]
            signals = [h for h in sentence["hits"] if h["cat"] in ("signal:remove", "signal:negations", "signal:coordinators")]
            for start, end in sentence.get("clauses", []):
                coordinators = {h["pos"] for h in signals if h["key"] == "coordinators" and start <= h["pos"] < end}
                for signal in (h for h in signals if h["key"] in ("remove", "negations") and start <= h["pos"] < end):
                    s = signal["pos"]
                    if signal["key"] == "remove" and not (s == start or (s - 1) in coordinators or words[s][:1] in "وف"):
                        continue
                    how = "remove" if signal["key"] == "remove" else "negated"
                    q, role_word = signal["end"], False

                    def free(k):  # the name ending before k modifies nothing after it
                        return k >= end or bool(variants[k] & (_FILLER_TOKENS | _ROLE_TOKENS)) or any(
                            variants[k] & tokens for tokens in _LANGUAGE_TOKENS.values())

                    while q < end:
                        if variants[q] & _ROLE_TOKENS:
                            role_word, q = True, q + 1
                            continue
                        language = next((key for key, tokens in _LANGUAGE_TOKENS.items() if variants[q] & tokens), None)
                        if language is not None:
                            if not free(q + 1):
                                break
                            removals["locale"].append((language, how))
                            q += 1
                            continue
                        match = next((row for row in phrases if q + len(row[0]) <= end
                                      and all(row[0][k] in variants[q + k] for k in range(len(row[0])))), None)
                        if match is not None:
                            after = q + len(match[0])
                            if (role_word or match[2] or (after < end and variants[after] & _ROLE_TOKENS)) and free(after):
                                removals["role"].append((match[1], how))
                                role_words.update((index, k) for k in range(q, after))
                            q = after
                            continue
                        if variants[q] & _FILLER_TOKENS:
                            q += 1
                            continue
                        break
        for key in removals:
            seen, unique = set(), []
            for item in removals[key]:
                if item[0] not in seen:
                    seen.add(item[0])
                    unique.append(item)
            removals[key] = unique
        return removals, role_words

    def integrations(self, spec, hits, change):
        for hit in hits:
            row = next(r for r in self.lexicon["integrations"] if r["id"] == hit["key"])
            if hit["negated"] or hit["mode"] == "remove":
                if change and hit["mode"] != "remove":
                    continue
                self.excluded["integration"].add(row["id"])
                if any(i["id"] == row["id"] for i in spec["integrations"]):
                    spec["integrations"] = [i for i in spec["integrations"] if i["id"] != row["id"]]
                self.note("removed" if change else "excluded", row["id"], name=row["id"])
                continue
            if row["id"] in self.excluded["integration"] or any(i["id"] == row["id"] for i in spec["integrations"]):
                continue
            item = {"id": row["id"], "title": copy.deepcopy(row["title"]), "paid": row["paid"], "network": row["network"],
                    "approved": not row["paid"]}
            spec["integrations"].append(item)
        for item in list(spec["integrations"]):
            if item["paid"] and not item["approved"] and spec["constraints"]["no_paid_services"]:
                answer = self.ask("integration", list(INTEGRATION_ANSWERS), item["title"]["en"], item["id"])
                if answer == "approve":
                    item["approved"] = True
                elif answer == "exclude":
                    spec["integrations"].remove(item)
                    self.note("excluded", item["id"], name=item["id"])

    def ai(self, spec, hits, change):
        ai = spec["ai"]
        ai.setdefault("provider", None)
        use_cases = list(ai["use_cases"])
        generic = False
        for hit in hits:
            if hit["negated"] or hit["mode"] == "remove":
                if change and hit["mode"] != "remove":
                    continue
                self.excluded["ai"] = True
                continue
            if hit["key"] == "generic":
                generic = True
            elif hit["key"] not in use_cases:
                use_cases.append(hit["key"])
        if self.excluded["ai"]:
            if use_cases or generic or ai["needed"]:
                self.note("removed" if change else "excluded", "ai", name="ai")
            spec["ai"] = {"needed": False, "use_cases": [], "provider": None}
            return
        if generic and not use_cases:
            answer = self.ask("ai_use_case", [row["id"] for row in self.lexicon["ai"]["use_cases"]])
            if answer:
                use_cases.append(answer)
        needed = bool(use_cases) or generic
        provider = ai["provider"]
        if needed and provider is None:
            provider = self.ask("ai_provider", list(self.lexicon["ai"]["providers"]))
            if provider == "drop":
                self.note("ai-dropped")
                spec["ai"] = {"needed": False, "use_cases": [], "provider": None}
                return
        spec["ai"] = {"needed": needed, "use_cases": use_cases, "provider": provider}

    # -- features
    def crud(self, spec, entity):
        plural, label_en, label_ar = entity["plural"], _label(entity, "en"), _label(entity, "ar")
        rows = [(f"POST /api/{plural} with a valid body returns 201 and the record", f"إنشاء {label_ar} ببيانات صحيحة يعيد 201 والسجل")]
        required = next((f for f in entity["fields"] if f["required"] and "default" not in f), None)
        if required:
            rows.append((f"POST /api/{plural} without {required['name']} returns 400", f"إنشاء {label_ar} بدون «{_label(required, 'ar')}» يعيد 400"))
        for field in [f for f in entity["fields"] if f["type"] == "enum"][:3]:
            rows.append((f"POST /api/{plural} with {field['name']}=not_a_value returns 400",
                         f"إنشاء {label_ar} بقيمة غير مسموحة في «{_label(field, 'ar')}» يعيد 400"))
        text = next((f for f in entity["fields"] if f["type"] in ("text", "email") and "max" in f), None)
        if text:
            rows.append((f"POST /api/{plural} with {text['name']} longer than {text['max']} characters returns 400",
                         f"إنشاء {label_ar} بقيمة «{_label(text, 'ar')}» أطول من {text['max']} حرفًا يعيد 400"))
        for field in (f for f in entity["fields"] if f.get("unique")):
            rows.append((f"POST /api/{plural} with a duplicate {field['name']} returns 409",
                         f"إنشاء {label_ar} بقيمة مكررة في «{_label(field, 'ar')}» يعيد 409"))
        for relation in (r for r in spec["relations"] if r["from"] == entity["name"] and r["kind"] == "many-to-one"):
            target = self.entity(spec, relation["to"])
            column = relation.get("field", _snake(relation["to"])) + "_id"
            rows.append((f"POST /api/{plural} with a {column} that does not exist returns 400",
                         f"إنشاء {label_ar} مرتبط بـ«{_label(target, 'ar')}» غير موجود يعيد 400"))
        rows += [(f"GET /api/{plural} returns 200 and lists the created records", f"عرض سجلات {label_ar} يعيد 200 ويشمل السجلات المنشأة"),
                 (f"GET /api/{plural}/{{id}} with an unknown id returns 404", f"طلب {label_ar} بمعرّف غير موجود يعيد 404"),
                 (f"PATCH /api/{plural}/{{id}} with a valid body returns 200 and the updated record", f"تعديل {label_ar} ببيانات صحيحة يعيد 200 والسجل المحدث"),
                 (f"DELETE /api/{plural}/{{id}} as admin returns 204", f"حذف {label_ar} بصلاحية مدير النظام يعيد 204")]
        return {"id": f"manage-{plural}", "title": {"ar": f"إدارة سجلات {label_ar}", "en": f"Create, list, update and delete {label_en} records"},
                "acceptance": [r[0] for r in rows], "acceptance_ar": [r[1] for r in rows], "entities": [entity["name"]]}

    def common(self, spec, pack):
        primary = pack["primary"] if pack and self.entity(spec, pack["primary"]) else spec["entities"][0]["name"]
        plural = self.entity(spec, primary)["plural"]
        limited = [r for r in spec["roles"] if "*" not in r["permissions"] and "delete" not in r["permissions"]]
        features = [{"id": "auth", "title": {"ar": "تسجيل الدخول والخروج", "en": "Sign in and sign out"},
                     "acceptance": ["POST /api/login with valid credentials returns 200 and a session cookie",
                                    "POST /api/login with a wrong password returns 401",
                                    "POST /api/logout returns 204 and the session is no longer accepted"],
                     "acceptance_ar": ["الدخول ببيانات صحيحة يعيد 200 وملف تعريف جلسة", "الدخول بكلمة مرور خاطئة يعيد 401",
                                       "الخروج يعيد 204 ولا تُقبل الجلسة بعده"], "entities": []}]
        rbac = [(f"GET /api/{plural} without a session returns 401", "الطلب بدون جلسة دخول يعيد 401"),
                (f"DELETE /api/{plural}/{{id}} as admin returns 204", "الحذف بصلاحية مدير النظام يعيد 204")]
        if limited:
            role = limited[-1]["id"]
            rbac.insert(1, (f"DELETE /api/{plural}/{{id}} as {role} returns 403", f"الحذف بدور {_label({'name': role, 'label': limited[-1].get('label')}, 'ar')} يعيد 403"))
        features.append({"id": "rbac", "title": {"ar": "الصلاحيات حسب الدور", "en": "Role-based permissions"},
                         "acceptance": [r[0] for r in rbac], "acceptance_ar": [r[1] for r in rbac], "entities": [primary]})
        if spec["product_type"] != "api-service":
            ui = []
            for locale in spec["locales"]:
                direction = "rtl" if locale == "ar" else "ltr"
                ui.append((f"GET /?lang={locale} returns 200 and html with dir={direction} and lang={locale}",
                           f"الواجهة بلغة {locale} تعيد 200 وصفحة HTML باتجاه {direction}"))
            ui.append(("GET / returns 200 and html where every form input has a label", "كل حقل إدخال في الواجهة له تسمية"))
            features.append({"id": "ui-locales", "title": {"ar": "واجهة ثنائية اللغة ومتاحة", "en": "Bilingual, accessible interface"},
                             "acceptance": [u[0] for u in ui], "acceptance_ar": [u[1] for u in ui], "entities": []})
        return features

    def ai_features(self, spec):
        result = []
        titles = {row["id"]: row["title"] for row in self.lexicon["ai"]["use_cases"]}
        for case in spec["ai"]["use_cases"]:
            result.append({"id": f"ai-{case}", "title": copy.deepcopy(titles.get(case, {"ar": case, "en": case})),
                           "acceptance": [f"POST /api/ai/{case} with an empty input returns 400",
                                          f"POST /api/ai/{case} while no model is configured returns 503 and no generated result",
                                          f"POST /api/ai/{case} with a valid input returns 200 and the result labelled with the model id"],
                           "acceptance_ar": ["طلب بمدخل فارغ يعيد 400", "بدون نموذج مهيأ يعيد 503 ولا يختلق نتيجة",
                                             "طلب صحيح يعيد 200 ونتيجة موسومة بمعرّف النموذج"], "entities": []})
        return result

    def features(self, spec, pack, change):
        names = {e["name"] for e in spec["entities"]}
        if not spec["entities"]:
            return
        pack_features = []
        for feature in pack["features"] if pack else []:
            if set(feature["requires"]) <= names:
                pack_features.append({"id": feature["id"], "title": copy.deepcopy(feature["title"]),
                                      "acceptance": [a["en"] for a in feature["acceptance"]],
                                      "acceptance_ar": [a["ar"] for a in feature["acceptance"]],
                                      "entities": list(feature["requires"])})
        pack_features = [f for f in pack_features if self.fields_intact(spec, pack, f)]
        ai = self.ai_features(spec)
        if not change:
            crud = [self.crud(spec, e) for e in spec["entities"]]
            spec["features"] = crud + pack_features + self.generic + ai + self.common(spec, pack)
            return
        present = {f["id"]: i for i, f in enumerate(spec["features"])}
        for name in self.touched:
            entity = self.entity(spec, name)
            if entity and f"manage-{entity['plural']}" in present and name not in self.added:
                spec["features"][present[f"manage-{entity['plural']}"]] = self.crud(spec, entity)
        new = [self.crud(spec, self.entity(spec, n)) for n in self.added if self.entity(spec, n)]
        new += [f for f in pack_features if set(f["entities"]) & set(self.added)]
        new += self.generic + [f for f in ai if f["id"] not in present]
        if not spec["ai"]["needed"]:
            spec["features"] = [f for f in spec["features"] if not f["id"].startswith("ai-")]
        for feature in new:
            if all(f["id"] != feature["id"] for f in spec["features"]):
                spec["features"].append(feature)
        regenerate = {"ui-locales"} | ({"rbac"} if self.removed_roles else set())
        for feature in self.common(spec, pack):
            if feature["id"] in regenerate and feature["id"] in present:
                index = next(i for i, f in enumerate(spec["features"]) if f["id"] == feature["id"])
                spec["features"][index] = feature

    def fields_intact(self, spec, pack, feature):
        """False when a pack criterion names a pack field its entity no longer has (excluded or removed)."""
        for name in feature["entities"]:
            original = {f["name"] for f in self.pack_entity(pack["id"], name)["fields"]} if self.pack_entity(pack["id"], name) else set()
            missing = original - {f["name"] for f in self.entity(spec, name)["fields"]}
            for field in missing:
                pattern = re.compile(r"\b" + re.escape(field) + r"\b")
                if any(pattern.search(text) for text in feature["acceptance"]):
                    return False
        return True

    def nfr(self, spec, hits, pack, change):
        defaults = self.lexicon["defaults"]["nfr"]
        nfr = copy.deepcopy(spec.get("nfr")) if change and isinstance(spec.get("nfr"), dict) else {
            key: list(defaults[key]) + [item for item in (pack["nfr"][key] if pack else []) if item not in defaults[key]]
            for key in NFR_KEYS}
        for hit in hits:
            if hit["negated"]:
                continue
            row = next(r for r in self.lexicon["nfr"] if r["id"] == hit["key"])
            for item in row["add"]:
                if item not in nfr[row["category"]]:
                    nfr[row["category"]].append(item)
        extra = []
        if any(i["network"] for i in spec["integrations"]):
            extra.append(("security", "integration credentials read from environment variables, never stored in the repository"))
        if spec["ai"]["needed"]:
            extra += [("security", "no record data sent to a paid AI API without owner approval"),
                      ("security", "AI output labelled as model-generated, never presented as verified fact")]
        for category, item in extra:
            if item not in nfr[category]:
                nfr[category].append(item)
        directions = [f"{locale} {'rtl' if locale == 'ar' else 'ltr'}" for locale in spec["locales"]]
        nfr["i18n"] = directions + [item for item in nfr["i18n"] if item not in ("ar rtl", "en ltr")]
        spec["nfr"] = nfr

    def finish(self, spec, intent, pack, sentences, partial=False):
        if partial:
            spec["nfr"] = {key: list(self.lexicon["defaults"]["nfr"][key]) for key in NFR_KEYS}
            spec["nfr"]["i18n"] = [f"{l} {'rtl' if l == 'ar' else 'ltr'}" for l in spec["locales"]] + spec["nfr"]["i18n"]
        unused = sorted(set(self.answers) - self.used)
        if unused and self.strict:
            raise SpecError([f"answer {qid!r} does not match an open question of this command" for qid in unused])
        for qid in unused:  # refine(): an earlier answer made this question moot (e.g. intent=change)
            self.note("answer-moot", qid, name=f"{qid}={self.answers.pop(qid)}")
        order = ["intent", "base", "domain", "product_type", "database", "field_entity", "remove_field", "feature_entity",
                 "relation", "ai_use_case", "ai_provider", "integration", "locale_removal", "locale_needed", "role_removal",
                 "role_needed"]
        questions = sorted(self.questions.values(), key=lambda q: (order.index(q["id"].split(":")[0]), q["id"]))
        source = {"command": self.text, "language": self.language, "sha256": _text_sha(self.text),
                  "answers": {k: self.answers[k] for k in sorted(self.answers)}, "knowledge_sha256": self.knowledge["sha256"]}
        if self.base_sha:
            source["base_sha256"] = self.base_sha
        result = {"schema": SCHEMA, "mode": MODE, "source": source, "intent": intent if intent else None}
        for key in ("title", "slug", "product_type", "domain", "locales", "roles", "entities", "relations", "features", "nfr",
                    "ai", "integrations", "constraints"):
            result[key] = spec[key]
        result["open_questions"] = questions
        result["assumptions"] = list(self.assumptions.values())
        validate_spec(result)
        return result


# --------------------------------------------------------------------------- public API

def _input(text):
    if not isinstance(text, str) or not text.strip():
        raise SpecError("command or brief must be non-empty text")
    if len(text) > MAX_INPUT:
        raise SpecError(f"command or brief longer than {MAX_INPUT} characters")
    return text


def _language(text, language):
    if language is None:
        return "ar" if _ARABIC.search(text) else "en"
    if language not in LOCALES:
        raise SpecError(f"language must be one of {list(LOCALES)} or None")
    return language


def _answers(answers):
    if answers is None:
        return {}
    if not isinstance(answers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in answers.items()):
        raise SpecError("answers must map question ids to text")
    if "base" in answers:
        raise SpecError("the 'base' question is answered by passing the existing specification as base=, not as text")
    return dict(answers)


def parse(command_or_brief, *, language=None, base=None, answers=None, domains_dir=None):
    """Owner command or brief (Arabic or English) -> gaie.spec/1 dict. Deterministic; unknowns become open_questions.

    `base` is the current, complete spec of an existing system for a change command; `answers` resolves open
    questions (normally through refine()); `domains_dir` overrides governance/domains/ (tests).
    """
    if base is not None:
        validate_spec(base)
        if base["open_questions"]:
            raise SpecError("base specification still has open questions; refine it first")
    return _parse(command_or_brief, language, base, answers, domains_dir, digest(base) if base is not None else None)


def _parse(text, language, base, answers, domains_dir, base_sha, strict=True):
    text = _input(text)
    knowledge = load_knowledge(domains_dir)
    return _Builder(text, _language(text, language), knowledge, _answers(answers), base, base_sha, strict).run()


def refine(spec, answers, *, base=None, domains_dir=None):
    """Resolve open questions of a spec with the owner's answers; returns a new spec (the input is not changed).

    The command is re-parsed with all answers so far, so the result equals what a fully specified command
    would give. A change spec re-applies its command, idempotently, to the state it already reached.
    """
    validate_spec(spec)
    answers = _answers(answers)
    if not answers and base is None:
        raise SpecError("refine needs at least one answer (or base= for the 'base' question)")
    open_ids = {q["id"]: q for q in spec["open_questions"]}
    for qid, value in answers.items():
        if qid not in open_ids:
            raise SpecError(f"{qid!r} is not an open question of this spec; open: {sorted(open_ids)}")
        choices = open_ids[qid]["choices"]
        if choices is not None and value not in choices:
            raise SpecError(f"answer {qid}: {value!r} is not one of {choices}")
    source = spec["source"]
    merged = {**source.get("answers", {}), **answers}
    if base is not None:
        if "base" not in open_ids:
            raise SpecError("base= given but the spec does not ask for one")
        validate_spec(base)
        if base["open_questions"]:
            raise SpecError("base specification still has open questions; refine it first")
        return _parse(source["command"], source["language"], base, merged, domains_dir, digest(base), strict=False)
    if "base_sha256" in source:
        return _parse(source["command"], source["language"], spec, merged, domains_dir, source["base_sha256"], strict=False)
    return _parse(source["command"], source["language"], None, merged, domains_dir, None, strict=False)


def _index(items, key):
    return {key(item): item for item in items}


def _relation_key(relation):
    return f"{relation['from']}.{relation.get('field', _snake(relation['to']))}->{relation['to']}"


def diff_specs(old, new):
    """Deterministic change set between two valid specs, for the upgrade engine; flags breaking changes."""
    validate_spec(old)
    validate_spec(new)
    breaking = []
    old_entities, new_entities = _index(old["entities"], lambda e: e["name"]), _index(new["entities"], lambda e: e["name"])
    entities = {"added": sorted(set(new_entities) - set(old_entities)), "removed": sorted(set(old_entities) - set(new_entities)),
                "changed": []}
    breaking += [{"kind": "entity-removed", "entity": name} for name in entities["removed"]]
    for name in sorted(set(old_entities) & set(new_entities)):
        before, after = _index(old_entities[name]["fields"], lambda f: f["name"]), _index(new_entities[name]["fields"], lambda f: f["name"])
        change = {"name": name, "fields": {"added": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after)), "changed": []}}
        for field in change["fields"]["removed"]:
            breaking.append({"kind": "field-removed", "entity": name, "field": field})
        for field in change["fields"]["added"]:
            if after[field]["required"] and "default" not in after[field]:
                breaking.append({"kind": "required-field-added", "entity": name, "field": field})
        for field in sorted(set(before) & set(after)):
            if before[field] != after[field]:
                change["fields"]["changed"].append({"name": field, "before": before[field], "after": after[field]})
                if before[field]["type"] != after[field]["type"]:
                    breaking.append({"kind": "field-type-changed", "entity": name, "field": field})
                if after[field]["required"] and not before[field]["required"] and "default" not in after[field]:
                    breaking.append({"kind": "field-now-required", "entity": name, "field": field})
                lost = sorted(set(before[field].get("values", [])) - set(after[field].get("values", [])))
                if before[field]["type"] == "enum" and after[field]["type"] == "enum" and lost:
                    breaking.append({"kind": "enum-values-removed", "entity": name, "field": field, "values": lost})
                if after[field].get("unique") and not before[field].get("unique"):
                    breaking.append({"kind": "field-now-unique", "entity": name, "field": field})
                if before[field]["type"] == after[field]["type"]:  # a tighter bound can reject stored values
                    for bound, tighter in (("max", lambda old, new: new < old), ("min", lambda old, new: new > old)):
                        old_bound, new_bound = before[field].get(bound), after[field].get(bound)
                        if bound == "min" and after[field]["type"] in ("text", "email"):  # no min = length 0
                            old_bound = 0 if old_bound is None else old_bound
                        if new_bound is not None and (old_bound is None or tighter(old_bound, new_bound)):
                            breaking.append({"kind": "field-tightened", "entity": name, "field": field,
                                             "constraint": bound, "before": old_bound, "after": new_bound})
        other = {k: v for k, v in old_entities[name].items() if k != "fields"} != {k: v for k, v in new_entities[name].items() if k != "fields"}
        if any(change["fields"].values()) or other:
            change["meta_changed"] = other
            if other and old_entities[name].get("plural") != new_entities[name].get("plural"):
                breaking.append({"kind": "entity-path-changed", "entity": name})
            entities["changed"].append(change)
    old_rel, new_rel = _index(old["relations"], _relation_key), _index(new["relations"], _relation_key)
    relations = {"added": [new_rel[k] for k in sorted(set(new_rel) - set(old_rel))],
                 "removed": [old_rel[k] for k in sorted(set(old_rel) - set(new_rel))],
                 "changed": [{"key": k, "before": old_rel[k], "after": new_rel[k]} for k in sorted(set(old_rel) & set(new_rel)) if old_rel[k] != new_rel[k]]}
    breaking += [{"kind": "relation-removed", "relation": _relation_key(r)} for r in relations["removed"]]
    breaking += [{"kind": "relation-changed", "relation": c["key"]} for c in relations["changed"]]
    breaking += [{"kind": "required-relation-added", "relation": _relation_key(r)} for r in relations["added"]
                 if r["required"] and r["from"] in old_entities]
    old_features, new_features = _index(old["features"], lambda f: f["id"]), _index(new["features"], lambda f: f["id"])
    features = {"added": sorted(set(new_features) - set(old_features)), "removed": sorted(set(old_features) - set(new_features)), "changed": []}
    breaking += [{"kind": "feature-removed", "feature": fid} for fid in features["removed"]]
    for fid in sorted(set(old_features) & set(new_features)):
        before, after = old_features[fid], new_features[fid]
        if before != after:
            features["changed"].append({"id": fid, "title_changed": before["title"] != after["title"],
                                        "acceptance": {"added": [a for a in after["acceptance"] if a not in before["acceptance"]],
                                                       "removed": [a for a in before["acceptance"] if a not in after["acceptance"]]}})
    old_roles, new_roles = _index(old["roles"], lambda r: r["id"]), _index(new["roles"], lambda r: r["id"])
    roles = {"added": sorted(set(new_roles) - set(old_roles)), "removed": sorted(set(old_roles) - set(new_roles)),
             "changed": sorted(r for r in set(old_roles) & set(new_roles) if old_roles[r] != new_roles[r])}
    breaking += [{"kind": "role-removed", "role": r} for r in roles["removed"]]
    old_int, new_int = _index(old["integrations"], lambda i: i["id"]), _index(new["integrations"], lambda i: i["id"])
    integrations = {"added": sorted(set(new_int) - set(old_int)), "removed": sorted(set(old_int) - set(new_int))}
    nfr = {"added": {k: [i for i in new["nfr"][k] if i not in old["nfr"][k]] for k in NFR_KEYS},
           "removed": {k: [i for i in old["nfr"][k] if i not in new["nfr"][k]] for k in NFR_KEYS}}
    nfr = {side: {k: v for k, v in rows.items() if v} for side, rows in nfr.items()}
    scalars = {key: {"before": old[key], "after": new[key]} for key in ("title", "slug", "product_type", "domain", "locales", "ai", "constraints")
               if old[key] != new[key]}
    if "locales" in scalars and set(old["locales"]) - set(new["locales"]):
        breaking.append({"kind": "locale-removed", "locales": sorted(set(old["locales"]) - set(new["locales"]))})
    counts = {"added": len(entities["added"]) + len(relations["added"]) + len(features["added"]) + len(roles["added"]) + len(integrations["added"])
              + sum(len(c["fields"]["added"]) for c in entities["changed"]),
              "removed": len(entities["removed"]) + len(relations["removed"]) + len(features["removed"]) + len(roles["removed"])
              + len(integrations["removed"]) + sum(len(c["fields"]["removed"]) for c in entities["changed"]),
              "changed": len(features["changed"]) + len(relations["changed"]) + len(roles["changed"]) + len(scalars)
              + sum(len(c["fields"]["changed"]) for c in entities["changed"]),
              "breaking": len(breaking)}
    old_sha, new_sha = digest(old), digest(new)
    return {"schema": DIFF_SCHEMA, "mode": MODE, "old_sha256": old_sha, "new_sha256": new_sha, "identical": old_sha == new_sha,
            "entities": entities, "relations": relations, "features": features, "roles": roles, "integrations": integrations,
            "nfr": nfr, "scalars": scalars, "breaking": breaking, "summary": counts}


# --------------------------------------------------------------------------- engine facade (contracts.validate_engine signature)

def engine(action, payload, ctx=None):
    """Control-plane entrypoint: (action, payload, ctx) -> dict. No side effects; payloads are data, never instructions."""
    if not isinstance(payload, dict):
        raise SpecError("payload must be an object")
    shapes = {"parse": ({"command"}, {"command", "language", "answers", "base"}), "refine": ({"spec", "answers"}, {"spec", "answers", "base"}),
              "validate": ({"spec"}, {"spec"}), "diff": ({"old", "new"}, {"old", "new"}), "acceptance": ({"spec"}, {"spec"}), "packs": (set(), set())}
    if action not in shapes:
        raise SpecError(f"unknown action {action!r}; allowed {sorted(shapes)}")
    required, allowed = shapes[action]
    if not required <= set(payload) <= allowed:
        raise SpecError(f"{action}: payload keys must include {sorted(required)} and stay within {sorted(allowed)}")
    request = digest(payload)
    if action == "parse":
        result = {"spec": parse(payload["command"], language=payload.get("language"), answers=payload.get("answers"), base=payload.get("base"))}
    elif action == "refine":
        result = {"spec": refine(payload["spec"], payload["answers"], base=payload.get("base"))}
    elif action == "validate":
        result = {"report": validate_spec(payload["spec"])}
    elif action == "diff":
        result = {"diff": diff_specs(payload["old"], payload["new"])}
    elif action == "acceptance":
        result = {"acceptance": acceptance_checks(payload["spec"])}
    else:
        result = {"packs": domain_packs()}
    return {"ok": True, "engine": "requirements", "action": action, "mode": MODE, "request_sha256": request, "result": result}


def health():
    """Loads and validates the knowledge packs without side effects."""
    try:
        knowledge = load_knowledge()
    except SpecError as error:
        return {"ok": False, "detail": str(error)}
    return {"ok": True, "detail": f"{len(knowledge['packs'])} domain packs; knowledge sha256 {knowledge['sha256'][:12]}"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="cmd", required=True)
    parse_cmd = commands.add_parser("parse")
    parse_cmd.add_argument("text")
    parse_cmd.add_argument("--language", choices=LOCALES)
    for name in ("validate", "acceptance"):
        commands.add_parser(name).add_argument("spec")
    diff_cmd = commands.add_parser("diff")
    diff_cmd.add_argument("old")
    diff_cmd.add_argument("new")
    commands.add_parser("packs")
    args = parser.parse_args(argv)
    read = lambda path: _strict_json(pathlib.Path(path))
    try:
        if args.cmd == "parse":
            result = parse(args.text, language=args.language)
        elif args.cmd == "validate":
            result = validate_spec(read(args.spec))
        elif args.cmd == "acceptance":
            result = acceptance_checks(read(args.spec))
        elif args.cmd == "diff":
            result = diff_specs(read(args.old), read(args.new))
        else:
            result = domain_packs()
    except (SpecError, OSError) as error:
        print(json.dumps({"ok": False, "errors": getattr(error, "errors", [str(error)])}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not (isinstance(result, dict) and result.get("open_questions")) else 2


if __name__ == "__main__":
    sys.exit(main())
