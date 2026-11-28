"""recheck-fixes (a): an origin the workspace policy cannot parse reaches the upgrade engine's callers as UpgradeError.

workspace_policy._repo_id raises WorkspacePolicyError for a GitHub remote it cannot reduce to one owner/name on the
default port (for example https://github.com:8443/<owner>/<name>). route_command used to let that error escape, so a
caller that catches UpgradeError (the engine's one refusal type) saw an unexpected exception. _registered_origin now
converts it, keeping the policy's message.
"""

import pathlib
import tempfile
import unittest
from unittest import mock

from engineering_os import upgrade_engine as engine, workspace_policy
from engineering_os.upgrade_engine import UpgradeError

REMOTES = "origin\thttps://github.com:8443/acme/app.git (fetch)\norigin\thttps://github.com:8443/acme/app.git (push)\n"


class OriginErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-or-", dir="/tmp")
        self.workspace = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def patched(self, repo_id):
        return (mock.patch.object(workspace_policy, "_git_checkout_marker", return_value=True),
                mock.patch.object(workspace_policy, "_git", return_value=REMOTES),
                mock.patch.object(workspace_policy, "_repo_id", side_effect=repo_id))

    def test_an_unparseable_origin_is_refused_as_an_upgrade_error_with_the_policy_message(self):
        error = workspace_policy.WorkspacePolicyError("GitHub remote on a non-default port is refused.")
        marker, git, repo_id = self.patched(error)
        with marker, git, repo_id, self.assertRaises(UpgradeError) as caught:
            engine._registered_origin(self.workspace, {"GAIE_HOME": str(self.workspace / "home")})
        self.assertIn("GitHub remote on a non-default port is refused.", str(caught.exception))
        self.assertIn("cannot be ruled out as a registered project", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_a_parseable_unregistered_origin_is_still_no_project(self):
        marker, git, repo_id = self.patched(lambda value: "acme/app")
        with marker, git, repo_id:
            self.assertIsNone(engine._registered_origin(self.workspace, {"GAIE_HOME": str(self.workspace / "home")}))


if __name__ == "__main__":
    unittest.main()
