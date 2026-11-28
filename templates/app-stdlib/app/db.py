"""SQLite storage: migrations, parameterized CRUD, relations, accounts and sessions.

Values always travel as SQL parameters. Identifiers come only from the validated
schema and are quoted by `ident`, which refuses anything outside [a-z][a-z0-9_]*.
A `scope` (see `Scope`) restricts which rows a signed-in account can see.
"""
import contextlib
import pathlib
import re
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "migrations"
IDENT = re.compile(r"[a-z][a-z0-9_]{0,62}")
VERSION = re.compile(r"\d{4}_[a-z0-9_]{1,60}")
MIGRATIONS_TABLE = ("CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")


class ReferenceMissing(Exception):
    def __init__(self, fields):
        super().__init__("referenced record not found")
        self.fields = fields


class HasDependents(Exception):
    def __init__(self, dependents):
        super().__init__("record has dependent records")
        self.dependents = dependents


class Duplicate(Exception):
    def __init__(self, fields):
        super().__init__("duplicate value")
        self.fields = fields


class StateConflict(Exception):
    def __init__(self, detail):
        super().__init__("state rule violated")
        self.detail = detail


def ident(name):
    if not isinstance(name, str) or not IDENT.fullmatch(name):
        raise ValueError("unsafe SQL identifier")
    return '"' + name + '"'


def _marks(count):
    return ", ".join("?" for _ in range(count))


def connect(path):
    connection = sqlite3.connect(str(path), timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextlib.contextmanager
def session(path):
    connection = connect(path)
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


# -- migrations ----------------------------------------------------------------

def migrations(directory=MIGRATIONS):
    rows = []
    for up in sorted(pathlib.Path(directory).glob("*.up.sql")):
        version = up.name[: -len(".up.sql")]
        down = up.with_name(version + ".down.sql")
        if not VERSION.fullmatch(version) or not down.is_file():
            raise ValueError(f"migration {up.name} needs a matching .down.sql and a NNNN_name version")
        rows.append((version, up, down))
    return rows


def applied(connection):
    connection.execute(MIGRATIONS_TABLE)
    connection.commit()
    return [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]


def _script(connection, sql):
    connection.commit()
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
    except sqlite3.Error:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def migrate(connection, directory=MIGRATIONS):
    """Apply pending migrations in order; each one is a single transaction."""
    done = set(applied(connection))
    ran = []
    for version, up, _ in migrations(directory):
        if version not in done:
            _script(connection, up.read_text(encoding="utf-8"))
            ran.append(version)
    return ran


def rollback(connection, directory=MIGRATIONS, steps=1):
    """Revert the most recent `steps` migrations using their .down.sql scripts."""
    done = applied(connection)
    known = {version: down for version, _, down in migrations(directory)}
    reverted = []
    for version in reversed(done[-steps:] if steps else []):
        _script(connection, known[version].read_text(encoding="utf-8"))
        reverted.append(version)
    return reverted


# -- visibility ----------------------------------------------------------------

class Scope:
    """Rows visible to one account: everything (admin) or only scoped records."""

    def __init__(self, schema, account=None, principal_id=None, own=False):
        self.schema, self.account, self.principal_id, self.own = schema, account, principal_id, own
        config = schema.auth.get("scoping")
        self.limited = bool(config) and account is not None and "*" not in schema.permissions(account["role"])
        self.config = config

    def clause(self, entity):
        """SQL condition (and params) restricting `entity` rows, or ('', [])."""
        parts, params = [], []
        if self.limited:
            members = ("SELECT " + ident("source_id") + " FROM " + ident(self.config["link_table"]) + " WHERE "
                       + ident("target_id") + " = ?")
            if entity.name == self.config["entity"]:
                parts.append(ident("id") + " IN (" + members + ")")
                params.append(self.principal_id or 0)
            else:
                for ref in entity.references:
                    if ref["entity"] == self.config["entity"]:
                        parts.append(ident(ref["field"]) + " IN (" + members + ")")
                        params.append(self.principal_id or 0)
        if self.own and self.account is not None:
            parts.append(ident("created_by") + " = ?")
            params.append(self.account["id"])
        return " AND ".join(parts), params


UNSCOPED = None


def _where(entity, scope, conditions=(), params=()):
    parts, values = list(conditions), list(params)
    if scope is not None:
        clause, extra = scope.clause(entity)
        if clause:
            parts.append(clause)
            values += extra
    return ((" WHERE " + " AND ".join(parts)) if parts else ""), values


# -- records -------------------------------------------------------------------

def _to_db(entity, column, value):
    field = entity.field(column)
    if field is not None and field["type"] == "bool" and value is not None:
        return 1 if value else 0
    return value


def _record(entity, row):
    record = {"id": row["id"]}
    for field in entity.fields:
        value = row[field["name"]]
        record[field["name"]] = bool(value) if field["type"] == "bool" and value is not None else value
    for ref in entity.references:
        record[ref["field"]] = row[ref["field"]]
    record["created_at"] = row["created_at"]
    record["updated_at"] = row["updated_at"]
    return record


def exists(connection, table, record_id):
    sql = "SELECT 1 FROM " + ident(table) + " WHERE " + ident("id") + " = ?"
    return connection.execute(sql, (record_id,)).fetchone() is not None


def visible(connection, entity, record_id, scope):
    where, params = _where(entity, scope, [ident("id") + " = ?"], [record_id])
    return connection.execute("SELECT 1 FROM " + ident(entity.table) + where, params).fetchone() is not None


def get(connection, entity, record_id, scope=UNSCOPED):
    where, params = _where(entity, scope, [ident("id") + " = ?"], [record_id])
    row = connection.execute("SELECT * FROM " + ident(entity.table) + where, params).fetchone()
    return None if row is None else _record(entity, row)


def stored(connection, entity, record_id):
    """The raw row (including created_by) without any scope, for authorization decisions."""
    row = connection.execute("SELECT * FROM " + ident(entity.table) + " WHERE " + ident("id") + " = ?",
                             (record_id,)).fetchone()
    return None if row is None else {**_record(entity, row), "created_by": row["created_by"]}


def order_clause(entity, sort=None):
    columns, descending = list(entity.default_order), False
    if sort:
        descending = sort.startswith("-")
        columns = [sort.lstrip("-")]
    parts = []
    for column in columns:
        parts += [ident(column) + " IS NULL", ident(column) + (" DESC" if descending else "")]
    parts.append(ident("id"))
    return " ORDER BY " + ", ".join(parts)


def list_records(connection, entity, *, scope=UNSCOPED, equals=None, before=None, not_equal=None,
                 sort=None, limit=50, offset=0):
    conditions, params = [], []
    for column, value in sorted((equals or {}).items()):
        conditions.append(ident(column) + " = ?")
        params.append(value)
    for column, value in sorted((before or {}).items()):
        conditions.append(ident(column) + " < ?")
        params.append(value)
    for column, value in sorted((not_equal or {}).items()):
        conditions.append("(" + ident(column) + " IS NULL OR " + ident(column) + " != ?)")
        params.append(value)
    where, params = _where(entity, scope, conditions, params)
    total = connection.execute("SELECT COUNT(*) FROM " + ident(entity.table) + where, params).fetchone()[0]
    sql = "SELECT * FROM " + ident(entity.table) + where + order_clause(entity, sort) + " LIMIT ? OFFSET ?"
    rows = connection.execute(sql, params + [limit, offset]).fetchall()
    return [_record(entity, row) for row in rows], total


def check_references(connection, schema, entity, values, scope=UNSCOPED):
    missing = {}
    for ref in entity.references:
        value = values.get(ref["field"])
        if value is not None and not visible(connection, schema.by_name[ref["entity"]], value, scope):
            missing[ref["field"]] = "not_found"
    if missing:
        raise ReferenceMissing(missing)


def check_unique(connection, entity, values, record_id=None):
    duplicates = {}
    for field in entity.fields:
        value = values.get(field["name"])
        if field.get("unique") and value is not None:
            sql = ("SELECT 1 FROM " + ident(entity.table) + " WHERE " + ident(field["name"]) + " = ? AND "
                   + ident("id") + " != ?")
            if connection.execute(sql, (value, record_id or 0)).fetchone():
                duplicates[field["name"]] = "duplicate"
    if duplicates:
        raise Duplicate(duplicates)


def check_rules(connection, schema, entity, values, record_id):
    """State rules derived from the specification (e.g. a milestone cannot be reached
    while a linked task is not done)."""
    for rule in schema.rules.get("completion", []):
        if rule["entity"] != entity.name or values.get(rule["field"]) != rule["value"] or record_id is None:
            continue
        child = schema.by_name[rule["child"]]
        sql = ("SELECT COUNT(*) FROM " + ident(child.table) + " WHERE " + ident(rule["fk"]) + " = ? AND ("
               + ident(rule["child_field"]) + " IS NULL OR " + ident(rule["child_field"]) + " != ?)")
        open_children = connection.execute(sql, (record_id, rule["child_value"])).fetchone()[0]
        if open_children:
            raise StateConflict({"rule": f"{entity.name}.{rule['field']}={rule['value']} needs every linked "
                                         f"{child.name}.{rule['child_field']}={rule['child_value']}",
                                 "open": open_children})


def dependents(connection, schema, entity, record_id):
    found = {}
    for other in schema.entities:
        for ref in other.references:
            if ref["entity"] == entity.name and ref.get("required"):
                sql = "SELECT COUNT(*) FROM " + ident(other.table) + " WHERE " + ident(ref["field"]) + " = ?"
                count = connection.execute(sql, (record_id,)).fetchone()[0]
                if count:
                    found[other.name] = found.get(other.name, 0) + count
    return found


def insert(connection, entity, values, now, created_by=None):
    columns = list(entity.columns) + ["created_by", "created_at", "updated_at"]
    params = [_to_db(entity, column, values.get(column)) for column in entity.columns] + [created_by, now, now]
    sql = ("INSERT INTO " + ident(entity.table) + " (" + ", ".join(ident(c) for c in columns) + ") VALUES ("
           + _marks(len(columns)) + ")")
    return connection.execute(sql, params).lastrowid


def update(connection, entity, record_id, values, now):
    columns = list(entity.columns) + ["updated_at"]
    params = [_to_db(entity, column, values.get(column)) for column in entity.columns] + [now, record_id]
    sql = ("UPDATE " + ident(entity.table) + " SET " + ", ".join(ident(c) + " = ?" for c in columns)
           + " WHERE " + ident("id") + " = ?")
    return bool(connection.execute(sql, params).rowcount)


def delete(connection, schema, entity, record_id):
    found = dependents(connection, schema, entity, record_id)
    if found:
        raise HasDependents(found)
    sql = "DELETE FROM " + ident(entity.table) + " WHERE " + ident("id") + " = ?"
    return bool(connection.execute(sql, (record_id,)).rowcount)


# -- many-to-many links and aggregates -----------------------------------------

def link_targets(connection, schema, link, source_id):
    target = schema.by_name[link["entity"]]
    sql = ("SELECT t.* FROM " + ident(target.table) + " t JOIN " + ident(link["link_table"]) + " l ON l."
           + ident("target_id") + " = t." + ident("id") + " WHERE l." + ident("source_id") + " = ? ORDER BY t."
           + ident("id"))
    return [_record(target, row) for row in connection.execute(sql, (source_id,))]


def add_link(connection, link, source_id, target_id):
    sql = ("SELECT 1 FROM " + ident(link["link_table"]) + " WHERE " + ident("source_id") + " = ? AND "
           + ident("target_id") + " = ?")
    if connection.execute(sql, (source_id, target_id)).fetchone():
        raise Duplicate({link["target_key"]: "duplicate"})
    connection.execute("INSERT INTO " + ident(link["link_table"]) + " (" + ident("source_id") + ", "
                       + ident("target_id") + ") VALUES (?, ?)", (source_id, target_id))


def remove_link(connection, link, source_id, target_id):
    sql = ("DELETE FROM " + ident(link["link_table"]) + " WHERE " + ident("source_id") + " = ? AND "
           + ident("target_id") + " = ?")
    return bool(connection.execute(sql, (source_id, target_id)).rowcount)


def progress(connection, schema, rule, parent_id):
    """Completion of a parent's children in ONE aggregate query."""
    child = schema.by_name[rule["child"]]
    done = rule["done"]
    sql = ("SELECT COUNT(*), COALESCE(SUM(CASE WHEN " + ident(rule["field"]) + " IN (" + _marks(len(done))
           + ") THEN 1 ELSE 0 END), 0) FROM " + ident(child.table) + " WHERE " + ident(rule["fk"]) + " = ?")
    total, finished = connection.execute(sql, (*done, parent_id)).fetchone()
    return {f"total_{rule['key']}": total, f"done_{rule['key']}": finished,
            "percent": (finished * 100 // total) if total else 0}


# -- accounts and sessions -----------------------------------------------------

def create_account(connection, email, role, salt, digest, iterations, now):
    sql = ("INSERT INTO " + ident("app_account") + " (" + ", ".join(ident(c) for c in (
        "email", "role", "password_salt", "password_hash", "password_iterations", "created_at")) + ") VALUES ("
        + _marks(6) + ")")
    return connection.execute(sql, (email, role, salt, digest, iterations, now)).lastrowid


def account_by_email(connection, email):
    sql = "SELECT * FROM " + ident("app_account") + " WHERE " + ident("email") + " = ?"
    return connection.execute(sql, (email,)).fetchone()


def create_session(connection, token_sha256, account_id, csrf_token, now, expires_at):
    sql = ("INSERT INTO " + ident("app_session") + " (" + ", ".join(ident(c) for c in (
        "token_sha256", "account_id", "csrf_token", "created_at", "expires_at")) + ") VALUES (" + _marks(5) + ")")
    connection.execute(sql, (token_sha256, account_id, csrf_token, now, expires_at))


def session_account(connection, token_sha256, now):
    sql = ("SELECT a." + ident("id") + " AS id, a." + ident("email") + " AS email, a." + ident("role")
           + " AS role, s." + ident("csrf_token") + " AS csrf_token FROM " + ident("app_session") + " s JOIN "
           + ident("app_account") + " a ON a." + ident("id") + " = s." + ident("account_id") + " WHERE s."
           + ident("token_sha256") + " = ? AND s." + ident("expires_at") + " > ?")
    row = connection.execute(sql, (token_sha256, now)).fetchone()
    return None if row is None else dict(row)


def delete_session(connection, token_sha256):
    connection.execute("DELETE FROM " + ident("app_session") + " WHERE " + ident("token_sha256") + " = ?",
                       (token_sha256,))


def principal_id(connection, schema, email):
    """Id of the principal entity record (for example the Member) with this e-mail, if any."""
    principal = schema.auth.get("principal")
    if not principal:
        return None
    entity = schema.by_name[principal["entity"]]
    sql = "SELECT " + ident("id") + " FROM " + ident(entity.table) + " WHERE " + ident(principal["email_field"]) + " = ?"
    row = connection.execute(sql, (email,)).fetchone()
    return None if row is None else row[0]
