"""Finding W2-UP-03: neither the audit nor the upgrade changes the original, and the report says what really happened.

The overlay pair `tests/fixtures/upgrade/taskapp-wal/data/tasks.store{,-wal}` is copied into a
taskapp copy as `data/tasks.db{,-wal}`, so the detectors' database scan opens it. Before the
fix the detectors ran on the original in upgrade mode and opened `*.db` with `mode=ro`, which
creates the `-shm` of a WAL database beside it: the audit ended "audit-changed-something" with
files_written 0, and a rejected upgrade still said "the original system is unchanged". Now an
upgrade runs the detectors on a disposable copy, every database is opened with
`mode=ro&immutable=1`, and `files_written` and both summaries follow the real comparison.
"""

import hashlib
import pathlib
import shutil
import tempfile
import types
import unittest
from unittest import mock

from engineering_os import detectors, upgrade_engine as engine
from engineering_os.upgrade_engine import upgrade

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKAPP = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp"
OVERLAY = ROOT / "tests" / "fixtures" / "upgrade" / "taskapp-wal"
NOW = 1_800_000_000


def digest(root):
    root = pathlib.Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-w2up03-", dir="/tmp")
        self.base = pathlib.Path(self.tmp.name)
        (self.base / "home").mkdir(mode=0o700)
        self.environ = {"GAIE_HOME": str(self.base / "home")}
        self.target = self.base / "target"
        shutil.copytree(TASKAPP, self.target)
        for suffix in ("", "-wal"):  # the taskapp database itself, in WAL mode with 5 committed rows in its -wal
            shutil.copyfile(OVERLAY / "data" / f"tasks.store{suffix}", self.target / "data" / f"tasks.db{suffix}")
        self.before = digest(self.target)

    def tearDown(self):
        self.tmp.cleanup()

    def run_engine(self, command, name="wd"):
        return upgrade(self.target, command=command, workdir=self.base / name, now=NOW, environ=self.environ)

    def assert_original_untouched(self):
        self.assertEqual(digest(self.target), self.before)
        self.assertEqual(sorted(p.name for p in (self.target / "data").iterdir()), ["tasks.db", "tasks.db-wal"])


class OriginalStaysUntouched(_Base):
    def test_the_detectors_open_a_wal_database_without_creating_its_shm(self):
        report = detectors.detect_database(self.target, ["data/tasks.db"])
        self.assertEqual((report["status"], report["findings"]), ("ran", []))
        self.assert_original_untouched()

    def test_an_audit_of_a_live_wal_database_writes_nothing(self):
        result = self.run_engine("Audit the task management system")
        self.assertEqual(result["status"], "audited")
        self.assertEqual(result["no_change_proof"]["files_written"], 0)
        self.assertTrue(result["no_change_proof"]["target_unchanged"])
        self.assertTrue(result["summary"]["en"].endswith("nothing was changed."))
        self.assertFalse(result["baseline"]["data"]["data/tasks.db"]["complete"])
        self.assert_original_untouched()

    def test_an_upgrade_runs_the_detectors_on_a_disposable_copy_only(self):
        seen = []
        real = detectors.run_all

        def spy(where, *args, **kwargs):
            seen.append(pathlib.Path(where).resolve())
            return real(where, *args, **kwargs)

        with mock.patch.object(detectors, "run_all", spy):
            result = self.run_engine("Upgrade the task management system")
        self.assertTrue(seen)
        for where in seen:
            self.assertNotEqual(where, self.target.resolve())
            self.assertNotIn(self.target.resolve(), where.parents)
        self.assertIn(pathlib.Path(result["run_dir"]), seen[0].parents)
        self.assertFalse(seen[0].exists(), "the disposable copy is removed")
        self.assertTrue(result["regression"]["checks"]["original-unchanged"])
        self.assertTrue(result["target"]["unchanged"])
        self.assertIn("the original system is unchanged.", result["summary"]["en"])
        self.assertIn("النظام الأصلي لم يتغير", result["summary"]["ar"])
        self.assert_original_untouched()


class ReportsFollowTheComparison(_Base):
    def test_an_audit_that_changed_the_target_says_so_and_counts_the_files(self):
        real = detectors.run_all

        def intruding(where, *args, **kwargs):  # stands in for any side effect during the audit
            (pathlib.Path(where) / "data" / "tasks.db-shm").write_bytes(b"\0" * 32)
            return real(where, *args, **kwargs)

        with mock.patch.object(detectors, "run_all", intruding):
            result = self.run_engine("افحص نظام إدارة المهام")
        self.assertEqual(result["status"], "audit-changed-something")
        self.assertEqual(result["no_change_proof"]["files_written"], 1)
        self.assertFalse(result["no_change_proof"]["target_unchanged"])
        self.assertIn("WARNING: 1 file(s) changed during the audit", result["summary"]["en"])
        self.assertIn("تحذير", result["summary"]["ar"])
        self.assertNotIn("nothing was changed", result["summary"]["en"])

    def test_the_upgrade_summary_never_claims_an_unchanged_original_when_the_check_failed(self):
        for unchanged, english, arabic in ((True, "the original system is unchanged.", "النظام الأصلي لم يتغير."),
                                           (False, "WARNING: the original system changed during the run", "تحذير: تغيّر النظام الأصلي")):
            run = types.SimpleNamespace(requested={"unmet": []}, regression_report={"checks": {"original-unchanged": unchanged}})
            summary = engine._summary(run, "rejected", [])
            with self.subTest(unchanged=unchanged):
                self.assertIn(english, summary["en"])
                self.assertIn(arabic, summary["ar"])
                self.assertEqual("is unchanged" in summary["en"], unchanged)


if __name__ == "__main__":
    unittest.main()
