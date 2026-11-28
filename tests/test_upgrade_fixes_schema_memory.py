"""Re-check of W2-UP-01 (low): target schema SQL cannot exhaust the engine's memory.

`detectors.schema_memory` bounded virtual-machine work but not memory: the reviewer's
two-statement schema (`printf('%.*c', 200000000, 'x')` and `zeroblob(200000000)`) loaded without
a refusal in under a second at 622 MB RSS. The in-memory database now has SQLITE_LIMIT_LENGTH,
SQLITE_LIMIT_SQL_LENGTH, a page limit on main and temp (temp kept in memory) and a time bound
next to the work bound; hitting one is reported as `unsafe-schema-sql`.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import detectors

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
HOSTILE = "CREATE TABLE big AS SELECT printf('%.*c', 200000000, 'x') AS a;\nCREATE TABLE blob AS SELECT zeroblob(200000000) AS b;\n"
CHILD = """
import json, pathlib, resource, sys
sys.path.insert(0, sys.argv[2])
from engineering_os import detectors
conn, problems = detectors.schema_memory(pathlib.Path(sys.argv[1]), ["hostile.sql"])
conn.close()
print(json.dumps({"problems": problems, "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
"""
BUDGET_KIB = 160 * 1024  # an interpreter with sqlite3 needs a few tens of MiB; the unbounded load reached 622 MB


class SchemaMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-sm-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, sql, name="schema.sql"):
        (self.base / name).write_text(sql, encoding="utf-8")
        conn, problems = detectors.schema_memory(self.base, [name])
        conn.close()
        return problems

    def test_the_reviewers_schema_is_refused_within_a_small_memory_budget(self):
        (self.base / "hostile.sql").write_text(HOSTILE, encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", "-c", CHILD, str(self.base), str(ROOT)], capture_output=True, text=True,
                              timeout=120, check=True)
        result = json.loads(done.stdout)
        self.assertEqual([(p["path"], p["kind"], p["refused"]) for p in result["problems"]],
                         [("hostile.sql", "unsafe-schema-sql", ["size limit"])])
        self.assertLess(result["maxrss_kib"], BUDGET_KIB)

    def test_values_statements_and_pages_are_bounded(self):
        cases = {
            "blob": "CREATE TABLE b AS SELECT zeroblob(5000000) AS b;",
            "statement": "CREATE TABLE s(x); INSERT INTO s VALUES ('" + "x" * (detectors.SQL_STATEMENT_LIMIT + 10) + "');",
            "pages": "CREATE TABLE r(x); INSERT INTO r SELECT zeroblob(900000) FROM "
                     "(WITH RECURSIVE c(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM c WHERE i < 40) SELECT i FROM c);",
            "temp-pages": "CREATE TEMP TABLE r(x); INSERT INTO r SELECT zeroblob(900000) FROM "
                          "(WITH RECURSIVE c(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM c WHERE i < 40) SELECT i FROM c);",
        }
        for name, sql in cases.items():
            with self.subTest(name):
                problems = self.load(sql, f"{name}.sql")
                self.assertEqual([(p["kind"], p["refused"]) for p in problems], [("unsafe-schema-sql", ["size limit"])])

    def test_a_string_past_the_value_bound_is_never_built(self):
        (self.base / "text.sql").write_text("CREATE TABLE t AS SELECT printf('%.*c', 5000000, 'x') AS a;", encoding="utf-8")
        conn, problems = detectors.schema_memory(self.base, ["text.sql"])
        try:  # SQLite's printf returns NULL instead of a value longer than SQLITE_LIMIT_LENGTH
            self.assertEqual((problems, conn.execute("SELECT typeof(a) FROM t").fetchone()[0]), ([], "null"))
        finally:
            conn.close()

    def test_a_script_past_its_time_bound_is_stopped(self):
        with mock.patch.object(detectors, "SQL_TIME_LIMIT_S", -1.0):
            problems = self.load("CREATE TABLE a(x); WITH RECURSIVE c(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM c WHERE i < 100000) "
                                 "SELECT count(*) FROM c;")
        self.assertEqual([(p["kind"], p["refused"]) for p in problems], [("unsafe-schema-sql", ["time limit"])])

    def test_ordinary_schemas_and_seed_rows_still_load(self):
        conn, problems = detectors.schema_memory(FIXTURE, ["schema.sql"])
        try:
            self.assertEqual(problems, [])
            self.assertIn("tasks", [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")])
        finally:
            conn.close()
        self.assertEqual(self.load("CREATE TABLE s(id INTEGER PRIMARY KEY, body TEXT); INSERT INTO s(body) SELECT printf('%.*c', 1000, 'x') "
                                   "FROM (WITH RECURSIVE c(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM c WHERE i < 500) SELECT i FROM c);"), [])


if __name__ == "__main__":
    unittest.main()
