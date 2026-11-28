"""Entity model and record validation. Python standard library only.

The entity model is data (app/schema.json). Every table, column and collection name
used in SQL or URLs comes from that file and is checked against a strict pattern
when it is loaded; request data never becomes an identifier.
"""
import datetime
import json
import math
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "schema.json"
IDENT = re.compile(r"[a-z][a-z0-9_]{0,62}")
COLLECTION = re.compile(r"[a-z][a-z0-9-]{0,62}")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?")
FIELD_TYPES = frozenset({"text", "int", "number", "bool", "date", "datetime", "enum", "email"})
READ_ONLY = frozenset({"id", "created_at", "updated_at", "created_by"})
MAX_INT = 2 ** 53 - 1


class SchemaError(ValueError):
    """app/schema.json is malformed; the application refuses to start."""


class ValidationError(ValueError):
    """A record failed validation. `fields` maps a field name to an error code."""

    def __init__(self, fields):
        super().__init__("validation failed: " + ", ".join(f"{k}={v}" for k, v in sorted(fields.items())))
        self.fields = dict(sorted(fields.items()))


def _need(condition, message):
    if not condition:
        raise SchemaError(message)


class Entity:
    def __init__(self, raw):
        _need(isinstance(raw, dict), "entity must be an object")
        self.raw = raw
        self.name = raw["name"]
        self.table = raw["table"]
        self.collection = raw["collection"]
        self.label_field = raw.get("label_field")
        self.fields = [dict(field) for field in raw["fields"]]
        self.references = [dict(ref) for ref in raw.get("references", [])]
        self.links = [dict(link) for link in raw.get("links", [])]
        self.default_order = list(raw.get("default_order", []))
        _need(IDENT.fullmatch(self.table or ""), f"bad table name {self.table!r}")
        _need(COLLECTION.fullmatch(self.collection or ""), f"bad collection {self.collection!r}")
        names = set()
        for field in self.fields:
            _need(IDENT.fullmatch(field.get("name") or ""), f"bad field name {field.get('name')!r}")
            _need(field.get("type") in FIELD_TYPES, f"bad field type {field.get('type')!r}")
            names.add(field["name"])
        for ref in self.references:
            _need(IDENT.fullmatch(ref.get("field") or "") and IDENT.fullmatch(ref.get("table") or ""), "bad reference")
            names.add(ref["field"])
        for link in self.links:
            _need(all(IDENT.fullmatch(link.get(key) or "") for key in ("table", "link_table", "target_key"))
                  and COLLECTION.fullmatch(link.get("segment") or ""), "bad link")
        _need(len(names) == len(self.fields) + len(self.references), "duplicate field")
        _need(not names & READ_ONLY, "reserved field name")
        for column in self.default_order:
            _need(column in names, f"bad default order column {column!r}")
        self.columns = [field["name"] for field in self.fields] + [ref["field"] for ref in self.references]
        self.children = []

    def field(self, name):
        for field in self.fields:
            if field["name"] == name:
                return field
        return None

    def reference(self, name):
        for ref in self.references:
            if ref["field"] == name:
                return ref
        return None


class Schema:
    def __init__(self, raw):
        _need(isinstance(raw, dict) and raw.get("schema_version") == 1, "schema_version must be 1")
        self.raw = raw
        self.app = raw["app"]
        self.limits = raw["limits"]
        self.nfr = raw.get("nfr", {})
        self.auth = raw["auth"]
        self.rules = raw.get("rules", {})
        self.entities = [Entity(row) for row in raw["entities"]]
        self.by_name = {entity.name: entity for entity in self.entities}
        self.by_collection = {entity.collection: entity for entity in self.entities}
        _need(len(self.by_name) == len(self.entities) == len(self.by_collection), "duplicate entity")
        for entity in self.entities:
            for target in entity.references + entity.links:
                _need(target["entity"] in self.by_name, f"unknown related entity {target['entity']!r}")
            for ref in entity.references:
                parent = self.by_name[ref["entity"]]
                if sum(1 for other in entity.references if other["entity"] == parent.name) == 1:
                    parent.children.append({"collection": entity.collection, "entity": entity, "field": ref["field"]})
        roles = self.auth["roles"]
        _need(isinstance(roles, dict) and self.auth["admin_role"] in roles, "auth roles")
        scoping = self.auth.get("scoping")
        if scoping:
            _need(scoping["entity"] in self.by_name and IDENT.fullmatch(scoping["link_table"]), "bad scoping")

    def public(self):
        return self.raw

    def permissions(self, role):
        return frozenset(self.auth["roles"].get(role, []))


def load_schema(path=SCHEMA_PATH):
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return Schema(raw)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SchemaError(f"cannot load {path}: {error}") from None


def allowed(permissions, need):
    """`need` is read, write or delete. Returns 'all', 'own' or None."""
    if "*" in permissions or need in permissions:
        return "all"
    if f"{need}:own" in permissions:
        return "own"
    return None


def _control(text):
    return any((ord(char) < 32 and char not in "\n\t") or ord(char) == 127 for char in text)


def check_value(field, value, limits):
    """Return the normalized value or raise KeyError(code)."""
    kind = field["type"]
    if kind in ("text", "email"):
        if not isinstance(value, str):
            raise KeyError("type")
        value = value.strip()
        if _control(value):
            raise KeyError("format")
        if len(value) > field.get("max", limits["max_text"]):
            raise KeyError("max_length")
        if field.get("required") and not value:
            raise KeyError("required")
        if value and len(value) < field.get("min", 0):
            raise KeyError("min_length")
        if kind == "email" and value and not EMAIL.fullmatch(value):
            raise KeyError("format")
        return value if value else None
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise KeyError("type")
        if abs(value) > MAX_INT:
            raise KeyError("max")
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise KeyError("type")
    if kind in ("int", "number"):
        if "min" in field and value < field["min"]:
            raise KeyError("min")
        if "max" in field and value > field["max"]:
            raise KeyError("max")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise KeyError("type")
        return value
    if kind == "enum":
        if not isinstance(value, str):
            raise KeyError("type")
        if value not in field["values"]:
            raise KeyError("enum")
        return value
    if kind == "date":
        if not isinstance(value, str):
            raise KeyError("type")
        try:
            if not DATE.fullmatch(value):
                raise ValueError
            datetime.date.fromisoformat(value)
        except ValueError:
            raise KeyError("format") from None
        return value
    if kind == "datetime":
        if not isinstance(value, str):
            raise KeyError("type")
        try:
            if not DATETIME.fullmatch(value):
                raise ValueError
            datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise KeyError("format") from None
        return value
    raise KeyError("type")


def _identifier(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_INT


def validate(entity, payload, limits, base=None):
    """Validate a record for create (base=None) or update (base = the stored record).

    For an update the payload is merged over the stored values (PATCH semantics; a
    full PUT body simply replaces every value). Returns the complete column values.
    """
    if not isinstance(payload, dict):
        raise ValidationError({"_body": "type"})
    errors = {}
    known = {field["name"] for field in entity.fields} | {ref["field"] for ref in entity.references}
    for key in payload:
        if key in READ_ONLY:
            errors[str(key)[:64]] = "read_only"
        elif key not in known:
            errors[str(key)[:64]] = "unknown_field"
    merged = dict(payload)
    if base is not None:
        merged = {column: base.get(column) for column in entity.columns}
        merged.update({key: value for key, value in payload.items() if key in known})
    values = {}
    for field in entity.fields:
        name = field["name"]
        if name not in merged:
            if "default" in field:
                values[name] = field["default"]
            elif field.get("required"):
                errors[name] = "required"
            else:
                values[name] = None
            continue
        value = merged[name]
        if value is None:
            if field.get("required"):
                errors[name] = "required"
            else:
                values[name] = None
            continue
        try:
            values[name] = check_value(field, value, limits)
        except KeyError as error:
            errors[name] = error.args[0]
            continue
        if values[name] is None and field.get("required"):
            errors[name] = "required"
    for ref in entity.references:
        value = merged.get(ref["field"])
        if value is None:
            if ref.get("required"):
                errors[ref["field"]] = "required"
            values[ref["field"]] = None
        elif not _identifier(value):
            errors[ref["field"]] = "type"
        else:
            values[ref["field"]] = value
    if errors:
        raise ValidationError(errors)
    return values
