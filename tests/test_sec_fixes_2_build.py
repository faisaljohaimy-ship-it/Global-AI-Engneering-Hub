"""recheck-security item 5 (private mode): an existing empty target directory, which check_target accepts,
is made private (0700) by build_engine._write_files when the caller owns it and refused otherwise.

Measured before the fix with the reviewer's private_mode.py: a pre-existing empty target with mode 0777,
built under umask 0, kept 0777 (other users could rename or replace files in the application root).
"""
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import build_engine  # noqa: E402

FILES = {"manage.py": b"print('ok')\n", "app/__init__.py": b"", "app/views.py": b"x = 1\n"}


class WriteFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="gaie-sf2b-", dir="/tmp" if os.path.isdir("/tmp") else None))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.umask = os.umask(0)  # the widest umask: every mode below comes from the engine
        self.addCleanup(os.umask, self.umask)

    def modes(self, target):
        return {str(path.relative_to(target)): stat.S_IMODE(path.lstat().st_mode) for path in target.rglob("*")}

    def test_an_existing_open_target_is_made_private(self):
        target = self.tmp / "app-root"
        target.mkdir()
        target.chmod(0o777)
        build_engine._write_files(target, FILES)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
        self.assertEqual(self.modes(target), {"manage.py": 0o700, "app": 0o700, "app/__init__.py": 0o600,
                                              "app/views.py": 0o600})

    def test_a_missing_target_is_created_private(self):
        target = self.tmp / "new-root"
        build_engine._write_files(target, FILES)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)

    def test_a_target_owned_by_someone_else_is_refused_before_anything_is_written(self):
        if os.geteuid() != 0:
            raise unittest.SkipTest("needs root to give the target to another uid")
        target = self.tmp / "foreign-root"
        target.mkdir()
        target.chmod(0o777)
        try:
            os.chown(target, 65534, 65534)
        except OSError as error:  # a user namespace that maps only the caller (the layer sandbox): EINVAL
            raise unittest.SkipTest(f"cannot give the target to another uid here: {error}")
        with self.assertRaises(build_engine.WorkspaceError):
            build_engine._write_files(target, FILES)
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o777)  # not changed either

    def test_a_target_reached_through_a_link_is_not_followed(self):
        real = self.tmp / "real-root"
        real.mkdir()
        real.chmod(0o777)
        link = self.tmp / "link-root"
        link.symlink_to(real)
        with self.assertRaises(OSError):
            build_engine._write_files(link, FILES)
        self.assertEqual(list(real.iterdir()), [])
        self.assertEqual(stat.S_IMODE(real.stat().st_mode), 0o777)


if __name__ == "__main__":
    unittest.main()
