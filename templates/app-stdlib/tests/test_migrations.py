"""Unit tests of the migration runner against a private temporary SQLite database."""
import pathlib
import tempfile
import unittest

from tests.support import SCHEMA
from app import db


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.connection = db.connect(pathlib.Path(self.tmp.name) / "m.sqlite3")
        self.addCleanup(self.connection.close)

    def tables(self):
        rows = self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                       "AND name NOT LIKE 'sqlite_%'").fetchall()
        return {row[0] for row in rows}

    def test_up_creates_schema(self):
        applied = db.migrate(self.connection)
        self.assertEqual(applied, [version for version, _, _ in db.migrations()])
        for entity in SCHEMA.entities:
            self.assertIn(entity.table, self.tables())
            columns = {row[1] for row in self.connection.execute("PRAGMA table_info(" + db.ident(entity.table) + ")")}
            self.assertTrue(set(entity.columns) | {"id", "created_by", "created_at", "updated_at"} <= columns, entity.name)
            for link in entity.links:
                self.assertIn(link["link_table"], self.tables())
        self.assertTrue({"app_account", "app_session"} <= self.tables())
        self.assertEqual(self.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_down_removes_schema(self):
        db.migrate(self.connection)
        db.rollback(self.connection, steps=len(db.migrations()))
        self.assertEqual(self.tables(), {"schema_migrations"})
        self.assertEqual(db.applied(self.connection), [])

    def test_up_is_idempotent(self):
        db.migrate(self.connection)
        self.assertEqual(db.migrate(self.connection), [])
        db.rollback(self.connection, steps=len(db.migrations()))
        self.assertEqual(len(db.migrate(self.connection)), len(db.migrations()))


if __name__ == "__main__":
    unittest.main()
