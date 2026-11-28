"""Finding W2-UP-01: a read-only audit must never let a target's schema SQL reach a file.

The templates under `tests/fixtures/upgrade/unsafe-sql/` are rendered into a copy of the
taskapp fixture with `{outside}` set to a private temporary directory. Before the fix the audit
ran them with `executescript`, so `ATTACH` created `outside/created-by-audit.db` holding the
planted row while the report said "audited", files_written 0. Now target SQL only runs in a
throwaway `:memory:` database whose authorizer denies ATTACH/VACUUM, DETACH, PRAGMA (outside
introspection and connection-local switches) and load_extension, with the attached-database
limit at 0; the refusal is reported as `unsafe-schema-sql`.
"""

import json
import pathlib
import shutil
import tempfile
import unittest

from engineering_os import detectors, upgrade_engine as engine
from engineering_os.upgrade_engine import upgrade

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKAPP = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
UNSAFE = ROOT / "tests" / "fixtures" / "upgrade" / "unsafe-sql"
NOW = 1_800_000_000
AUDIT = "Audit the task management system"


def tree(root):
    root = pathlib.Path(root)
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-w2up01-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)
        self.outside = self.base / "outside"
        self.outside.mkdir()
        (self.base / "home").mkdir(mode=0o700)
        self.environ = {"GAIE_HOME": str(self.base / "home")}

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, template):
        return (UNSAFE / template).read_text(encoding="utf-8").replace("{outside}", str(self.outside))

    def target(self, files, schema=None):
        target = self.base / "target"
        shutil.copytree(TASKAPP, target)
        for rel, template in files.items():
            (target / rel).write_text(self.render(template), encoding="utf-8")
        if schema is not None:
            manifest = json.loads((target / "gaie-upgrade.json").read_text(encoding="utf-8"))
            manifest["schema"] = schema
            (target / "gaie-upgrade.json").write_text(json.dumps(manifest), encoding="utf-8")
        return target

    def audit(self, target):
        return upgrade(target, command=AUDIT, workdir=self.base / "audit-wd", now=NOW, environ=self.environ)


class AuditNeverExecutesTargetSqlAgainstAFile(_Base):
    def test_planted_attach_file_never_appears_and_the_sql_is_reported_as_refused(self):
        target = self.target({"reports.sql": "attach.sql.tmpl"})
        result = self.audit(target)
        self.assertEqual(tree(self.outside), [], "the audit created a file outside the target")
        self.assertEqual(result["status"], "audited")
        self.assertEqual(result["no_change_proof"]["files_written"], 0)
        unsafe = [f for f in result["audit"]["findings"] if f["kind"] == "unsafe-schema-sql"]
        self.assertEqual([f["location"]["path"] for f in unsafe], ["reports.sql"])
        self.assertEqual(unsafe[0]["severity"], "high")
        self.assertIn("ATTACH or VACUUM", unsafe[0]["evidence"]["refused"])
        self.assertIn("reports.sql", [d["location"]["path"] for d in result["audit"]["defects"]])

    def test_vacuum_into_and_load_extension_are_refused(self):
        target = self.target({"archive.sql": "vacuum-into.sql.tmpl", "ext.sql": "load-extension.sql.tmpl"})
        result = self.audit(target)
        self.assertEqual(tree(self.outside), [])
        refused = {f["location"]["path"]: f["evidence"]["refused"] for f in result["audit"]["findings"] if f["kind"] == "unsafe-schema-sql"}
        self.assertEqual(refused, {"archive.sql": ["ATTACH or VACUUM"], "ext.sql": ["function load_extension"]})

    def test_a_schema_declared_only_in_the_upgrade_manifest_is_refused_by_the_query_audit(self):
        target = self.target({"views.sql": "view-attach.sql.tmpl"}, schema=["schema.sql", "views.sql"])
        result = self.audit(target)
        self.assertEqual(tree(self.outside), [])
        self.assertEqual(result["status"], "audited")
        rows = [o for o in result["audit"]["opportunities"] if o["kind"] == "unsafe-schema-sql"]
        self.assertEqual([(o["path"], o["evidence"]["refused"]) for o in rows], [("views.sql", ["ATTACH or VACUUM"])])
        self.assertFalse(any(o["kind"] == "unindexed-filter" for o in result["audit"]["opportunities"]))


class SchemaMemory(_Base):
    def write(self, name, text):
        (self.base / name).write_text(text, encoding="utf-8")
        return name

    def load(self, text):
        conn, problems = detectors.schema_memory(self.base, [self.write("s.sql", text)])
        try:
            tables = sorted(row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"))
        finally:
            conn.close()
        return tables, problems

    def test_ordinary_schemas_with_connection_local_pragmas_load(self):
        tables, problems = self.load("PRAGMA foreign_keys = ON;\nPRAGMA user_version = 3;\n"
                                     "CREATE TABLE a (id INTEGER PRIMARY KEY);\nCREATE TABLE b (a_id INTEGER REFERENCES a(id));\n"
                                     "CREATE INDEX b_a ON b (a_id);\nINSERT INTO a VALUES (1);\n")
        self.assertEqual((tables, problems), (["a", "b"], []))

    def test_file_reaching_statements_are_refused_and_stop_the_script(self):
        cases = {f"ATTACH DATABASE '{self.outside}/x.db' AS x;": "ATTACH or VACUUM",
                 f"VACUUM INTO '{self.outside}/v.db';": "ATTACH or VACUUM",
                 "VACUUM;": "ATTACH or VACUUM",
                 "DETACH DATABASE temp;": "DETACH",
                 "PRAGMA journal_mode = WAL;": "PRAGMA journal_mode",
                 "PRAGMA temp_store_directory = '/tmp';": "PRAGMA temp_store_directory",
                 "SELECT load_extension('x');": "function load_extension"}
        for statement, label in cases.items():
            with self.subTest(statement=statement):
                tables, problems = self.load("CREATE TABLE before_it (a);\n" + statement + "\nCREATE TABLE after_it (b);\n")
                self.assertEqual(tables, ["before_it"])
                self.assertEqual([(p["path"], p["kind"], p["refused"]) for p in problems], [("s.sql", "unsafe-schema-sql", [label])])
        self.assertEqual(tree(self.outside), [])

    def test_unbounded_work_is_stopped(self):
        _, problems = self.load("CREATE TABLE n AS WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT x FROM c;")
        self.assertEqual([(p["kind"], p["refused"]) for p in problems], [("unsafe-schema-sql", ["work limit"])])

    def test_broken_sql_stays_a_schema_error(self):
        _, problems = self.load("CREATE TABL oops (a);")
        self.assertEqual([(p["kind"], p["refused"]) for p in problems], [("schema-error", [])])

    def test_detectors_and_the_upgrade_engine_use_the_guarded_database(self):
        rel = self.write("evil.sql", self.render("attach.sql.tmpl"))
        error = detectors.explain_query(self.base, [rel], "SELECT 1")
        self.assertIn("unsafe-schema-sql", error)
        report = detectors.detect_database(self.base, [rel])
        self.assertEqual([f["kind"] for f in report["findings"]], ["unsafe-schema-sql"])
        conn, problems = engine._schema_db(self.base, [rel])
        self.assertIsNone(conn)
        self.assertEqual(problems[0]["refused"], ["ATTACH or VACUUM"])
        self.assertEqual(tree(self.outside), [])


if __name__ == "__main__":
    unittest.main()
