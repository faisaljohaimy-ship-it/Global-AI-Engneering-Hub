"""Dependency pins must agree with the integrity-bearing lock file."""

import re
import unittest

import deps


class DependencyTests(unittest.TestCase):
    def test_pins_match_lock(self):
        self.assertEqual(deps.read_requirements(), deps.read_lock())

    def test_lock_entries_carry_hashes(self):
        for name, digest in deps.lock_hashes().items():
            with self.subTest(package=name):
                self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_requirements_are_exact_pins(self):
        for version in deps.read_requirements().values():
            self.assertTrue(re.fullmatch(r"\d+\.\d+\.\d+", version))


if __name__ == "__main__":
    unittest.main()
