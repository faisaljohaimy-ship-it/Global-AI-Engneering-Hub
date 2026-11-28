"""Validate the browser adapter's fixed command, scope and receipt requirements."""

import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from engineering_os import control, mcp_local_tools
from engineering_os.orchestration import canonical


class BrowserMCPTests(unittest.TestCase):
    def test_cache_rejects_relative_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as local:
            alias = pathlib.Path(local) / 'alias'
            alias.symlink_to(local, target_is_directory=True)
            with self.assertRaises(ValueError):
                mcp_local_tools.validate_browser_cache(alias)
            with self.assertRaises(ValueError):
                mcp_local_tools.validate_browser_cache('relative')

    def test_browser_adapter_uses_fixed_fixture_and_rejects_changed_source_binding(self):
        policy = control.read(control.ROOT / 'catalog/capabilities/playwright.json')
        reviewed = control.read(control.ROOT / policy['runtime_receipt'])
        receipt = {**reviewed, 'inputs': {**reviewed['inputs'], 'harness.html': '0' * 64}}
        response = subprocess.CompletedProcess([], 0, canonical(receipt), b'')
        with patch.object(mcp_local_tools, '_browser_policy', return_value=(policy, reviewed)), \
                patch.object(mcp_local_tools.shutil, 'which', return_value='/usr/bin/node'), \
                patch.object(mcp_local_tools.subprocess, 'run', return_value=response) as called:
            with self.assertRaises(ValueError):
                mcp_local_tools.browser_qa(pathlib.Path('/tmp/browser-cache'))
        command = called.call_args.args[0]
        self.assertEqual(command, ['/usr/bin/node', 'motion-library/chromium-stack/smoke.mjs',
                                   '--frames', '30', '--frame-budget-ms', '20'])
        self.assertEqual(set(called.call_args.kwargs['env']), {'PATH', 'PLAYWRIGHT_BROWSERS_PATH'})


if __name__ == '__main__':
    unittest.main()
