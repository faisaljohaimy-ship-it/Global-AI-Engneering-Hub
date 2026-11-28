"""Re-check of W2-UP-01 (low): target schema SQL cannot exhaust the engine's memory.

`detectors.schema_memory` bounded virtual-machine work but not memory: the reviewer's
two-statement schema (`printf('%.*c', 200000000, 'x')` and `zeroblob(200000000)`) loaded without
a refusal in under a second at 622 MB RSS. The in-memory database now has SQLITE_LIMIT_LENGTH,
SQLITE_LIMIT_SQL_LENGTH, a page limit on main and temp (temp kept in memory) and a time bound
next to the work bound; hitting one is reported as `unsafe-schema-sql`.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import detectors

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
HOSTILE = "CREATE TABLE big AS SELECT printf('%.*c', 200000000, 'x') AS a;\nCREATE TABLE blob AS SELECT zeroblob(200000000) AS b;\n"
# How a child measures the memory the target SQL itself costs, the same on any host. ru_maxrss cannot: Linux carries the
# parent's peak resident size into the child across execve (a child of a full unittest run started at 297 MB on a
# GitHub runner, so the old absolute budget failed there with the schema refused). VmHWM belongs to the child's own
# address space; clear_refs "5" resets it to the current size, so VmHWM - VmRSS, read around the load, is the peak
# growth during the load. Without /proc the ru_maxrss difference is used (a lower bound only).
MEASURE = """
import resource
def _status(key):
    try:
        with open("/proc/self/status") as stream:
            return next(int(line.split()[1]) for line in stream if line.startswith(key))
    except (OSError, StopIteration, ValueError):
        return None
def memory_start():
    try:
        with open("/proc/self/clear_refs", "w") as stream:
            stream.write("5")
    except OSError:
        pass
    return _status("VmRSS:"), resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
def memory_growth_kib(start):
    resident, maxrss = start
    peak = _status("VmHWM:")
    if resident is not None and peak is not None:
        return peak - resident
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - maxrss
"""
CHILD = MEASURE + """
import json, pathlib, sys
sys.path.insert(0, sys.argv[2])
from engineering_os import detectors
start = memory_start()
conn, problems = detectors.schema_memory(pathlib.Path(sys.argv[1]), ["hostile.sql"])
conn.close()
print(json.dumps({"problems": problems, "growth_kib": memory_growth_kib(start)}))
"""
BUDGET_KIB = 64 * 1024  # growth of the child while the schema loads (refused near 1 MiB here); unbounded it grew 622 MB


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
        self.assertLess(result["growth_kib"], BUDGET_KIB)

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


# --------------------------------------------------------------------------- re-check 2 (heap)
# Re-check 2 of the schema loader (medium): target schema SQL cannot hold the engine's memory.
#
# `detectors.schema_memory` ran each statement with ``.fetchall()``: the reviewer's two-line
# schema (a ``SELECT`` of 2500 ``zeroblob(999000)`` rows) reached 2,405 MB in 1.67 s, and the
# read-only audit of such a target hit a 1.5 GB cap. ``DISTINCT``, a recursive ``UNION`` and
# ``ORDER BY`` over one-megabyte strings reached a 1.2 GB cap as well: SQLite keeps those tables
# and its sorter in memory, outside ``max_page_count``. Now a statement runs to its first row and
# its rows are never read, the progress handler measures this process's resident growth every
# 100 instructions, and every statement runs under an address-space limit (straight-line code,
# such as a function with 999 one-megabyte arguments, allocates between two progress checks).
# Each hostile case below runs in a child process under a 1 GiB address-space cap, so a
# regression fails the test instead of exhausting the host.
HEAP_CAP_MIB = 1024  # the child's own RLIMIT_AS: a regression ends in MemoryError there, never on the host
HEAP_BUDGET_MIB = (detectors.SQL_ADDRESS_HEADROOM >> 20) + 32  # growth of the child's peak resident size while it loads
HEAP_ROWS = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c LIMIT {n}) "
HEAP_WIDE = "printf('%.*c', 999000, '{i}')"
HEAP_HOSTILE = {  # name: (schema, expected refusal)
    "distinct": (HEAP_ROWS.format(n=5000) + "SELECT count(*) FROM (SELECT DISTINCT printf('%.*c', 999000, 'x') || x FROM c);", "memory limit"),
    "recursive-union": ("WITH RECURSIVE c(x, s) AS (SELECT 1, printf('%.*c', 999000, 'x') UNION SELECT x + 1, s FROM c "
                        "WHERE x < 5000) SELECT count(*) FROM c;", "memory limit"),
    "order-by": (HEAP_ROWS.format(n=5000) + "SELECT count(*) FROM (SELECT printf('%.*c', 999000, 'x') || x AS v FROM c ORDER BY v);",
                 "memory limit"),
    "group-by-into-a-table": ("CREATE TABLE t(x); " + HEAP_ROWS.format(n=3000) + "INSERT INTO t SELECT count(*) FROM "
                              "(SELECT printf('%.*c', 999000, 'x') || x AS k FROM c GROUP BY k);", "memory limit"),
    "function-arguments": ("CREATE TABLE t(x); INSERT INTO t SELECT length(max(" + ", ".join(HEAP_WIDE.format(i=i % 10) for i in range(999))
                           + "));", "memory limit"),
    "wide-row": ("SELECT " + ", ".join(HEAP_WIDE.format(i=i % 10) for i in range(1999)) + ";", "memory limit"),
    "nested-views": ("CREATE VIEW v0 AS SELECT " + ", ".join(f"{i} AS c{i}" for i in range(100)) + ";\n"
                     + "".join(f"CREATE VIEW v{k} AS SELECT * FROM v{k - 1} UNION ALL SELECT * FROM v{k - 1};\n" for k in range(1, 17))
                     + "SELECT * FROM v16;", "memory limit"),
}
HEAP_CHILD = MEASURE + """
import json, pathlib, sys
sys.path.insert(0, sys.argv[2])
cap = int(sys.argv[3]) << 20
resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
from engineering_os import detectors
limit = resource.getrlimit(resource.RLIMIT_AS)
start = memory_start()
try:
    conn, problems = detectors.schema_memory(pathlib.Path(sys.argv[1]), ["schema.sql"])
    conn.close()
    result = [{"kind": p["kind"], "refused": p["refused"], "error": p["error"]} for p in problems]
except MemoryError:
    result = "MemoryError: the child's address-space cap was reached"
print(json.dumps({"problems": result, "growth_mib": memory_growth_kib(start) >> 10,
                  "limit_restored": list(resource.getrlimit(resource.RLIMIT_AS)) == list(limit)}))
"""
HEAP_AUDIT = MEASURE + """
import json, pathlib, sys
sys.path.insert(0, sys.argv[2])
cap = int(sys.argv[3]) << 20
resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
from engineering_os.upgrade_engine import upgrade
base = pathlib.Path(sys.argv[1])
start = memory_start()
try:
    status = upgrade(base / "target", command="Audit the task management system", workdir=base / "wd", now=1800000000,
                     environ={"GAIE_HOME": str(base / "home")})["status"]
except MemoryError:
    status = "MemoryError: the child's address-space cap was reached"
print(json.dumps({"status": status, "growth_mib": memory_growth_kib(start) >> 10}))
"""
# The address-space checks lower this process's RLIMIT_AS for a moment: they run in a child, never in the test runner,
# so no other thread of a full test run can meet the lowered limit.
HEAP_LIMITS = """
import json, pathlib, resource, sqlite3, sys
from unittest import mock
sys.path.insert(0, sys.argv[2])
from engineering_os import detectors
base, out = pathlib.Path(sys.argv[1]), {}
limit = resource.getrlimit(resource.RLIMIT_AS)
with mock.patch.object(detectors, "SQL_ADDRESS_HEADROOM", 8 << 20):  # small enough to stop the 999 arguments
    conn, problems = detectors.schema_memory(base, ["args.sql"])
conn.close()
out["refusal"] = [[p["kind"], p["refused"]] for p in problems]
out["restored_after_refusal"] = resource.getrlimit(resource.RLIMIT_AS) == limit
conn, problems = detectors.schema_memory(base, ["views.sql"])  # only CREATE VIEW: it loads
out["views_problems"] = problems
with mock.patch.object(detectors, "SQL_ADDRESS_HEADROOM", 32 << 20):
    try:
        conn.execute("EXPLAIN SELECT * FROM v16")
        out["caller"] = "ran"
    except sqlite3.Error as error:  # what detect_database and the query audit handle
        out["caller"] = type(error).__name__
out["restored_after_caller"] = resource.getrlimit(resource.RLIMIT_AS) == limit
out["views"] = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'view'").fetchone()[0]
conn.close()
print(json.dumps(out))
"""
HEAP_BOUNDED = detectors._process_memory()[1] is not None  # the address-space bound needs the process size (/proc/self/statm)


class SchemaHeap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-sh-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def child(self, sql):
        (self.base / "schema.sql").write_text(sql, encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", "-c", HEAP_CHILD, str(self.base), str(ROOT), str(HEAP_CAP_MIB)],
                              capture_output=True, text=True, timeout=120, check=True)
        return json.loads(done.stdout)

    def test_the_reviewers_select_rows_are_never_read(self):
        result = self.child("CREATE TABLE t(id INTEGER PRIMARY KEY, title TEXT);\n" + HEAP_ROWS.format(n=2500)
                            + "SELECT zeroblob(999000) FROM c;\n")
        self.assertEqual(result["problems"], [])  # a SELECT changes no schema: it runs to its first row only
        self.assertLess(result["growth_mib"], HEAP_BUDGET_MIB)
        self.assertTrue(result["limit_restored"])

    @unittest.skipUnless(HEAP_BOUNDED, "the address-space bound needs /proc/self/statm")
    def test_memory_heavy_statements_are_refused_within_a_small_budget(self):
        for name, (sql, reason) in HEAP_HOSTILE.items():
            with self.subTest(name):
                result = self.child(sql)
                self.assertIsInstance(result["problems"], list, result)
                self.assertEqual([(p["kind"], p["refused"]) for p in result["problems"]], [("unsafe-schema-sql", [reason])])
                self.assertIn("MiB", result["problems"][0]["error"])  # the measured growth and the bounds are stated
                self.assertLess(result["growth_mib"], HEAP_BUDGET_MIB)
                self.assertTrue(result["limit_restored"])

    @unittest.skipUnless(HEAP_BOUNDED, "the address-space bound needs /proc/self/statm")
    def test_the_address_space_limit_is_restored_and_bounds_the_callers_statements(self):
        (self.base / "args.sql").write_text(HEAP_HOSTILE["function-arguments"][0], encoding="utf-8")
        (self.base / "views.sql").write_text(HEAP_HOSTILE["nested-views"][0].rsplit("SELECT * FROM v16;", 1)[0], encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", "-c", HEAP_LIMITS, str(self.base), str(ROOT)], capture_output=True, text=True,
                              timeout=120, check=True)
        self.assertEqual(json.loads(done.stdout), {"refusal": [["unsafe-schema-sql", ["memory limit"]]], "restored_after_refusal": True,
                                                   "views_problems": [], "caller": "SqlMemoryLimit", "restored_after_caller": True,
                                                   "views": 17})

    def test_a_script_past_its_work_bound_is_stopped(self):
        (self.base / "work.sql").write_text(HEAP_ROWS.format(n=1_000_000) + "SELECT count(*) FROM c;", encoding="utf-8")
        with mock.patch.object(detectors, "SQL_WORK_LIMIT", 10_000):
            conn, problems = detectors.schema_memory(self.base, ["work.sql"])
        conn.close()
        self.assertEqual([(p["kind"], p["refused"]) for p in problems], [("unsafe-schema-sql", ["work limit"])])

    def test_a_returning_statement_makes_all_its_changes(self):
        (self.base / "seed.sql").write_text("CREATE TABLE t(x); INSERT INTO t VALUES (1), (2), (3) RETURNING x, zeroblob(999000);",
                                            encoding="utf-8")
        conn, problems = detectors.schema_memory(self.base, ["seed.sql"])
        try:
            self.assertEqual((problems, conn.execute("SELECT count(*) FROM t").fetchone()[0]), ([], 3))
        finally:
            conn.close()

    def test_a_schema_near_the_page_bounds_still_loads(self):
        seed = ("CREATE TABLE s(id INTEGER PRIMARY KEY, body TEXT); CREATE INDEX s_body ON s(body);\n"
                "WITH RECURSIVE c(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM c WHERE i < 1700) "
                "INSERT INTO s(body) SELECT printf('%.*c', 4000, 'x') || i FROM c;\n"
                "CREATE TEMP TABLE w(id INTEGER PRIMARY KEY, body TEXT);\n"
                "WITH RECURSIVE c(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM c WHERE i < 1700) "
                "INSERT INTO w(body) SELECT printf('%.*c', 4000, 'y') || i FROM c;\n"
                "CREATE INDEX temp.w_body ON w(body);\nSELECT count(*) FROM (SELECT DISTINCT body FROM s ORDER BY body);\n")
        result = self.child(seed)  # about 29 MB of pages in main and temp, plus a sort over them
        self.assertEqual(result["problems"], [])
        self.assertLess(result["growth_mib"], HEAP_BUDGET_MIB)
        conn, problems = detectors.schema_memory(FIXTURE, ["schema.sql"])
        conn.close()
        self.assertEqual(problems, [])

    def test_the_read_only_audit_of_the_reviewers_target_stays_small(self):
        target = self.base / "target"
        shutil.copytree(FIXTURE, target)
        with open(target / "schema.sql", "a", encoding="utf-8") as stream:
            stream.write("\n" + HEAP_ROWS.format(n=2500) + "SELECT zeroblob(999000) FROM c;\n")
        (self.base / "home").mkdir(mode=0o700)
        done = subprocess.run([sys.executable, "-I", "-c", HEAP_AUDIT, str(self.base), str(ROOT), str(HEAP_CAP_MIB + 512)],
                              capture_output=True, text=True, timeout=300, check=True)  # audit mode runs no target code
        result = json.loads(done.stdout)
        self.assertEqual(result["status"], "audited")
        self.assertLess(result["growth_mib"], HEAP_BUDGET_MIB)


if __name__ == "__main__":
    unittest.main()
