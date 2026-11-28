"""SQLite storage: migrations and parameterized CRUD. Python standard library only.

Values always travel as SQL parameters. Identifiers come only from the validated
schema and are quoted by `ident`, which refuses anything outside [a-z][a-z0-9_]*.
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


def _to_db(entity, column, value):
    field = entity.field(column)
    if field is not None and field["type"] == "bool" and value is not None:
        return 1 if value else 0
    return value


def _record(connection, entity, row):
    record = {"id": row["id"]}
    for field in entity.fields:
        value = row[field["name"]]
        record[field["name"]] = bool(value) if field["type"] == "bool" and value is not None else value
    for ref in entity.references:
        record[ref["field"]] = row[ref["field"]]
    for link in entity.links:
        sql = ("SELECT " + ident("target_id") + " FROM " + ident(link["link_table"]) + " WHERE "
               + ident("source_id") + " = ? ORDER BY " + ident("target_id"))
        record[link["field"]] = [item[0] for item in connection.execute(sql, (row["id"],))]
    record["created_at"] = row["created_at"]
    record["updated_at"] = row["updated_at"]
    return record


def exists(connection, table, record_id):
    sql = "SELECT 1 FROM " + ident(table) + " WHERE " + ident("id") + " = ?"
    return connection.execute(sql, (record_id,)).fetchone() is not None


def get(connection, entity, record_id):
    sql = "SELECT * FROM " + ident(entity.table) + " WHERE " + ident("id") + " = ?"
    row = connection.execute(sql, (record_id,)).fetchone()
    return None if row is None else _record(connection, entity, row)


def list_records(connection, entity, filters, limit, offset):
    where, params = [], []
    for column, value in sorted(filters.items()):
        where.append(ident(column) + " = ?")
        params.append(value)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = connection.execute("SELECT COUNT(*) FROM " + ident(entity.table) + clause, params).fetchone()[0]
    sql = ("SELECT * FROM " + ident(entity.table) + clause + " ORDER BY " + ident("id") + " LIMIT ? OFFSET ?")
    rows = connection.execute(sql, params + [limit, offset]).fetchall()
    return [_record(connection, entity, row) for row in rows], total


def check_references(connection, schema, entity, values, links):
    missing = {}
    for ref in entity.references:
        value = values.get(ref["field"])
        if value is not None and not exists(connection, ref["table"], value):
            missing[ref["field"]] = "not_found"
    for link in entity.links:
        if any(not exists(connection, link["table"], item) for item in links.get(link["field"], [])):
            missing[link["field"]] = "not_found"
    if missing:
        raise ReferenceMissing(missing)


def dependents(connection, schema, entity, record_id):
    found = {}
    for other in schema.entities:
        for ref in other.references:
            if ref["entity"] == entity.name and ref.get("required"):
                sql = "SELECT COUNT(*) FROM " + ident(other.table) + " WHERE " + ident(ref["field"]) + " = ?"
                count = connection.execute(sql, (record_id,)).fetchone()[0]
                if count:
                    found[other.name] = count
    return found


def _set_links(connection, entity, record_id, links):
    for link in entity.links:
        table = ident(link["link_table"])
        connection.execute("DELETE FROM " + table + " WHERE " + ident("source_id") + " = ?", (record_id,))
        sql = ("INSERT INTO " + table + " (" + ident("source_id") + ", " + ident("target_id") + ") VALUES (?, ?)")
        connection.executemany(sql, [(record_id, target) for target in links.get(link["field"], [])])


def insert(connection, entity, values, links, now):
    columns = list(entity.columns) + ["created_at", "updated_at"]
    params = [_to_db(entity, column, values.get(column)) for column in entity.columns] + [now, now]
    sql = ("INSERT INTO " + ident(entity.table) + " (" + ", ".join(ident(c) for c in columns) + ") VALUES ("
           + _marks(len(columns)) + ")")
    record_id = connection.execute(sql, params).lastrowid
    _set_links(connection, entity, record_id, links)
    return record_id


def update(connection, entity, record_id, values, links, now):
    columns = list(entity.columns) + ["updated_at"]
    params = [_to_db(entity, column, values.get(column)) for column in entity.columns] + [now, record_id]
    sql = ("UPDATE " + ident(entity.table) + " SET " + ", ".join(ident(c) + " = ?" for c in columns)
           + " WHERE " + ident("id") + " = ?")
    changed = connection.execute(sql, params).rowcount
    if changed:
        _set_links(connection, entity, record_id, links)
    return bool(changed)


def delete(connection, schema, entity, record_id):
    found = dependents(connection, schema, entity, record_id)
    if found:
        raise HasDependents(found)
    sql = "DELETE FROM " + ident(entity.table) + " WHERE " + ident("id") + " = ?"
    return bool(connection.execute(sql, (record_id,)).rowcount)
