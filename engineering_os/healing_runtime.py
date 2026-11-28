"""Self repair for the built-in SQLite event ingestion profile.

The input is a settings document with three boolean options. The same fixed
SQLite runtime runs acceptance probes before repair, after repair, and after
restoring the original bytes. Results apply to this profile in a disposable
workspace. The caller supplies neither SQL nor executable code.
SPDX-License-Identifier: MIT
"""

import hashlib
import os
import pathlib
import sqlite3
import tempfile
from contextlib import closing

from .healing import VERSION, HealingError, _digest, _fields, _slug, artifact_digest
from .orchestration import canonical, load_json, sha

PROFILE = "sqlite-event-ingestion-v1"
SETTINGS_FILE = "settings.json"
OPTIONS = {
    "foreign_keys": "reject_orphan",
    "atomic_batches": "rollback_failed_batch",
    "deduplicate": "idempotent_replay",
}


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _settings(raw):
    try:
        value = load_json(raw)
    except (ValueError, TypeError, RecursionError) as error:
        raise HealingError("Invalid settings JSON") from error
    _fields(value, OPTIONS)
    if any(type(value[option]) is not bool for option in OPTIONS):
        raise HealingError("Each SQLite profile setting needs a boolean value")
    return value


def _replace_settings(root, raw):
    fd, name = tempfile.mkstemp(dir=root, prefix="settings-")
    temporary = pathlib.Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / SETTINGS_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def _bootstrap(connection, settings):
    connection.execute("PRAGMA foreign_keys = ON" if settings["foreign_keys"] else
                       "PRAGMA foreign_keys = OFF")
    connection.executescript("""
        CREATE TABLE streams (id INTEGER PRIMARY KEY);
        CREATE TABLE events (
            stream_id INTEGER NOT NULL REFERENCES streams(id),
            event_key INTEGER NOT NULL,
            value INTEGER NOT NULL
        );
        INSERT INTO streams VALUES (1), (2);
    """)
    if settings["deduplicate"]:
        connection.execute("CREATE UNIQUE INDEX event_identity ON events (stream_id, event_key)")


def _append_batch(connection, settings, rows):
    statement = "INSERT INTO events (stream_id, event_key, value) VALUES (?, ?, ?)"
    if settings["deduplicate"]:
        statement += " ON CONFLICT(stream_id, event_key) DO NOTHING"
    atomic = settings["atomic_batches"]
    if atomic:
        connection.execute("BEGIN")
    try:
        connection.executemany(statement, rows)
    except sqlite3.Error:
        if atomic:
            connection.rollback()
        raise
    if atomic:
        connection.commit()


def _events(connection, stream_id, event_key):
    return connection.execute(
        "SELECT value FROM events WHERE stream_id = ? AND event_key = ? ORDER BY rowid",
        (stream_id, event_key),
    ).fetchall()


def _rejected_batch(connection, settings, rows, expected_error):
    try:
        _append_batch(connection, settings, rows)
    except sqlite3.IntegrityError as error:
        if error.sqlite_errorname != expected_error:
            raise
        return True
    return False


def _probe(root, stage):
    """Run the same observable acceptance suite against a fresh on-disk database."""
    settings = _settings((root / SETTINGS_FILE).read_bytes())
    database = root / (stage + ".sqlite3")
    # SQLite databases and journals remain inside this mode-0700 directory.
    with closing(sqlite3.connect(database, isolation_level=None)) as connection:
        _bootstrap(connection, settings)
        _append_batch(connection, settings, [(1, 1, 10)])
        orphan = _rejected_batch(connection, settings, [(99, 1, 10)],
                                 "SQLITE_CONSTRAINT_FOREIGNKEY")
        reject_orphan = orphan and _events(connection, 99, 1) == []
        batch = _rejected_batch(connection, settings, [(1, 2, 20), (1, 3, None)],
                                "SQLITE_CONSTRAINT_NOTNULL")
        rollback_failed_batch = batch and _events(connection, 1, 2) == []
        _append_batch(connection, settings, [(1, 4, 40), (1, 4, 41), (2, 4, 42)])
        idempotent_replay = _events(connection, 1, 4) == [(40,)]

    with closing(sqlite3.connect(database)) as reopened:
        persisted = _events(reopened, 1, 1) == [(10,)]
        independent_streams = _events(reopened, 2, 4) == [(42,)]
    return {
        "reject_orphan": reject_orphan,
        "rollback_failed_batch": rollback_failed_batch,
        "idempotent_replay": idempotent_replay,
        "valid_write_persists": persisted,
        "distinct_streams_preserved": independent_streams,
    }


def repair_sqlite(request):
    """Reproduce defects, repair the supported settings and test exact rollback.

    `settings_sha256` binds the exact UTF-8 input text, including line endings.
    A verified candidate is returned for separate review. This function writes
    only to a disposable private directory that closes before it returns.
    """
    _fields(request, {"schema_version", "project", "settings_json", "settings_sha256"})
    if type(request["schema_version"]) is not int or request["schema_version"] != VERSION:
        raise HealingError("Invalid SQLite healing schema version")
    project = _slug(request["project"])
    settings_json = request["settings_json"]
    baseline_artifact = artifact_digest({SETTINGS_FILE: settings_json})
    baseline = settings_json.encode("utf-8")
    baseline_hash = _hash(baseline)
    if baseline_hash != _digest(request["settings_sha256"]):
        raise HealingError("Changed SQLite settings bytes")
    settings = _settings(baseline)

    with tempfile.TemporaryDirectory(prefix="gaie-sqlite-healing-") as directory:
        root = pathlib.Path(directory)
        _replace_settings(root, baseline)
        try:
            before = _probe(root, "baseline")
            repairs = sorted(option for option, test in OPTIONS.items()
                             if not settings[option] and not before[test])
            candidate = (canonical({**settings, **dict.fromkeys(repairs, True)}) + b"\n"
                         if repairs else baseline)
            _replace_settings(root, candidate)
            after = _probe(root, "candidate")
            candidate_hash = _hash((root / SETTINGS_FILE).read_bytes())
        except sqlite3.Error as error:
            raise HealingError("SQLite acceptance probe could not complete") from error
        finally:
            _replace_settings(root, baseline)
        try:
            rolled_back = _probe(root, "rollback")
        except sqlite3.Error as error:
            raise HealingError("SQLite rollback probe could not complete") from error
        rollback_hash = _hash((root / SETTINGS_FILE).read_bytes())

    rollback_verified = rollback_hash == baseline_hash and rolled_back == before
    candidate_verified = candidate_hash == _hash(candidate) and all(after.values())
    verified = rollback_verified and candidate_verified
    status = "blocked"
    if verified:
        status = "repair-verified" if repairs else "healthy"
    result = {
        "schema_version": VERSION,
        "project": project,
        "profile": PROFILE,
        "status": status,
        "sqlite_version": sqlite3.sqlite_version,
        "source_sha256": _hash(pathlib.Path(__file__).read_bytes()),
        "baseline_sha256": baseline_hash,
        "baseline_artifact_sha256": baseline_artifact,
        "candidate_sha256": candidate_hash,
        "candidate_json": candidate.decode("utf-8") if status == "repair-verified" else None,
        "rollback_sha256": rollback_hash,
        "original_failures": [name for name, passed in before.items() if not passed],
        "changed_settings": repairs,
        "before": before,
        "after": after,
        "rollback": rolled_back,
        "rollback_verified": rollback_verified,
        "runtime_tested": True,
        "runtime_scope": "built-in SQLite ingestion acceptance probes in a private temporary directory",
        "untrusted_code_executed": False,
        "requires_human_review": True,
        "production_mutations": 0,
        "deployment_allowed": False,
    }
    result["receipt_sha256"] = sha(result)
    return result


def verify_sqlite_repair(request, report):
    """Replay the fixed probe suite and reject a changed or foreign receipt."""
    if not isinstance(report, dict) or "receipt_sha256" not in report:
        raise HealingError("SQLite repair receipt required")
    digest = _digest(report["receipt_sha256"])
    try:
        observed = sha({key: value for key, value in report.items() if key != "receipt_sha256"})
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        raise HealingError("Invalid SQLite repair receipt") from error
    if observed != digest:
        raise HealingError("Changed SQLite repair receipt")
    replayed = repair_sqlite(request)
    if replayed["receipt_sha256"] != digest:
        raise HealingError("SQLite repair receipt does not match current replay")
    return replayed
