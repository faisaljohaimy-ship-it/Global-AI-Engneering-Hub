"""Re-check of W2-UP-01 (low): legitimate fts5 / rtree schemas are not flagged as unsafe.

The fts3/fts4/fts5/rtree/geopoly modules prepare read-only pragmas for themselves
("PRAGMA 'main'.page_size", "PRAGMA 'main'.data_version"). The W2-UP-01 authorizer denied them,
so such a schema was reported as high `unsafe-schema-sql` and its queries were never measured.
`detectors.schema_memory` now runs a script one statement at a time and allows exactly those
two pragmas, without a value, only while a statement of the script is already running (a
statement's own authorizer calls all come before it starts), i.e. only when a module issues
them. Every pragma the script itself states, and every file-touching path, stays refused.
"""

import pathlib
import shutil
import tempfile
import unittest

from engineering_os import detectors, upgrade_engine as engine
from engineering_os.upgrade_engine import upgrade

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKAPP = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
NOW = 1_800_000_000
FTS5 = """-- full-text search; the comment has a semicolon
CREATE TABLE docs (id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT);
CREATE VIRTUAL TABLE docs_fts USING fts5(title, body, content='docs', content_rowid='id');
CREATE TRIGGER docs_ai AFTER INSERT ON docs BEGIN
    INSERT INTO docs_fts (rowid, title, body) VALUES (new.id, new.title, new.body);
END;
INSERT INTO docs (title, body) VALUES ('first; with a semicolon', 'hello world');
"""
RTREE = """CREATE VIRTUAL TABLE places USING rtree(id, min_x, max_x, min_y, max_y);
INSERT INTO places VALUES (1, 0, 1, 0, 1);
"""
FTS4 = "CREATE VIRTUAL TABLE notes USING fts4(body);\nINSERT INTO notes (body) VALUES ('note');\n"


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-sv-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, sql, name="schema.sql"):
        (self.base / name).write_text(sql, encoding="utf-8")
        conn, problems = detectors.schema_memory(self.base, [name])
        return conn, problems


class ModuleSchemas(_Base):
    def test_fts5_rtree_and_fts4_schemas_load_and_their_queries_are_explained(self):
        for name, sql, query in (("fts5", FTS5, "SELECT rowid FROM docs_fts WHERE docs_fts MATCH 'hello'"),
                                 ("rtree", RTREE, "SELECT id FROM places WHERE min_x > 0"),
                                 ("fts4", FTS4, "SELECT body FROM notes WHERE notes MATCH 'note'")):
            with self.subTest(name):
                conn, problems = self.load(sql, f"{name}.sql")
                try:
                    self.assertEqual(problems, [])
                    self.assertTrue(conn.execute("EXPLAIN QUERY PLAN " + query).fetchall())
                finally:
                    conn.close()
                self.assertIsNone(detectors.explain_query(self.base, [f"{name}.sql"], query))
        conn, _ = self.load(FTS5)
        try:  # the statement boundaries kept the semicolons inside the comment, the trigger and the string
            self.assertEqual(conn.execute("SELECT title FROM docs").fetchall(), [("first; with a semicolon",)])
        finally:
            conn.close()

    def test_the_database_detector_reports_no_unsafe_sql_for_them(self):
        for name, sql in (("fts5", FTS5), ("rtree", RTREE)):
            (self.base / f"{name}.sql").write_text(sql, encoding="utf-8")
        report = detectors.detect_database(self.base)
        self.assertEqual([f for f in report["findings"] if f["kind"] in ("unsafe-schema-sql", "schema-error")], [])

    def test_pragmas_the_script_states_are_still_refused(self):
        hostile = {
            "PRAGMA page_size;": "PRAGMA page_size",
            "PRAGMA main.page_size;": "PRAGMA page_size",
            "PRAGMA page_size = 1024;": "PRAGMA page_size",
            "PRAGMA data_version;": "PRAGMA data_version",
            "PRAGMA main.data_version;": "PRAGMA data_version",
            "CREATE TABLE p AS SELECT * FROM pragma_page_size();": "PRAGMA page_size",
            FTS5 + "PRAGMA main.data_version;": "PRAGMA data_version",
            FTS5 + "CREATE TABLE p AS SELECT * FROM docs_fts, pragma_page_size();": "PRAGMA page_size",
            FTS5 + "CREATE TABLE p AS SELECT * FROM docs_fts, pragma_data_version();": "PRAGMA data_version",
            RTREE + "PRAGMA main.page_size;": "PRAGMA page_size",
            RTREE + "PRAGMA journal_mode = WAL;": "PRAGMA journal_mode",
            FTS5 + "ATTACH DATABASE ':memory:' AS other;": "ATTACH or VACUUM",
            FTS5 + "VACUUM INTO 'copy.db';": "ATTACH or VACUUM",
            RTREE + "SELECT load_extension('payload');": "function load_extension",
        }
        for number, (sql, refused) in enumerate(hostile.items()):
            with self.subTest(sql=sql[-50:]):
                conn, problems = self.load("CREATE TABLE a (x);\n" + sql, f"h{number}.sql")
                conn.close()
                self.assertEqual([(p["kind"], p["refused"]) for p in problems], [("unsafe-schema-sql", [refused])])
        self.assertEqual(sorted(p.name for p in self.base.iterdir() if not p.name.endswith(".sql")), [])

    def test_the_callers_own_statements_get_no_module_allowance(self):
        conn, problems = self.load(FTS5)
        try:
            self.assertEqual(problems, [])
            with self.assertRaises(detectors.sqlite3.DatabaseError):
                conn.execute("PRAGMA main.page_size").fetchall()
        finally:
            conn.close()


class Audit(_Base):
    def test_an_audit_measures_the_queries_of_a_schema_with_fts5_and_rtree(self):
        target = self.base / "target"
        shutil.copytree(TASKAPP, target)
        with (target / "schema.sql").open("a", encoding="utf-8") as stream:
            stream.write("\n" + FTS5 + RTREE)
        (self.base / "home").mkdir(mode=0o700)
        result = upgrade(target, command="Audit the task management system", workdir=self.base / "wd", now=NOW,
                         environ={"GAIE_HOME": str(self.base / "home")})
        self.assertEqual(result["status"], "audited")
        kinds = [f["kind"] for f in result["audit"]["findings"]] + [o["kind"] for o in result["audit"]["opportunities"]]
        self.assertNotIn("unsafe-schema-sql", kinds)
        self.assertNotIn("schema-error", kinds)
        self.assertIn("unindexed-filter", kinds)  # the taskapp's filtered queries are measured again
        self.assertEqual(engine.audit_queries(target, detectors.list_files(target), ["schema.sql"], "tests")[0]["kind"],
                         "unindexed-filter")


if __name__ == "__main__":
    unittest.main()
