"""Narrow MCP adapter for the reviewed local Playwright probe.

The approved Headroom surface remains the local CLI. This module does not
enable installation, caller URLs, browser profiles, or provider requests.
SPDX-License-Identifier: MIT
"""

import datetime as dt
import hashlib
import os
import pathlib
import shutil
import subprocess

from . import control
from .orchestration import load_json


MODULE = 'motion-library/chromium-stack'


def _browser_policy():
    policy = control.read(control.safe_path('catalog/capabilities/playwright.json'))
    entry = next(row for row in control.read(control.safe_path('catalog/registry.json'))
                 if row['id'] == 'microsoft/playwright')
    required_reviews = ('license_review', 'security_review', 'commercial_review')
    if (entry['status'] != 'approved' or entry.get('revision') != policy['revision']
            or any(entry.get(key) != 'approved' for key in required_reviews)):
        raise ValueError('Reviewed Playwright pin required')
    receipt = control.read(control.safe_path(policy['runtime_receipt']), policy['runtime_receipt_sha256'])
    # Check that this harness matches the reviewed run. The returned QA result
    # must come from the new invocation, even if the historic receipt expired.
    recorded = dt.datetime.fromisoformat(receipt['recorded_at_utc'].replace('Z', '+00:00'))
    if control.runtime_review(policy, recorded) is None:
        raise ValueError('Reviewed browser harness does not match the checkout')
    packages = control.read(control.safe_path(f'{MODULE}/package-lock.json'))['packages']
    for name in ('playwright', 'playwright-core'):
        package = packages[f'node_modules/{name}']
        installed = control.read(control.safe_path(f'{MODULE}/node_modules/{name}/package.json'))
        if (package['integrity'] != policy['npm_integrities'][name]
                or package['version'] != policy['version'] or installed['version'] != policy['version']):
            raise ValueError('Install the existing exact Playwright lock first')
    return policy, receipt


def validate_browser_cache(value):
    """This directory is supplied by the operator at startup, never by MCP."""
    path = pathlib.Path(value)
    if not path.is_absolute() or '..' in path.parts or not path.is_dir():
        raise ValueError('Browser cache needs a canonical installed directory')
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('Symlink browser cache refused')
    _browser_policy()
    return path


def browser_qa(cache):
    """Run the existing 30-frame, 20 ms probe against its loopback fixture."""
    policy, reviewed = _browser_policy()
    node = shutil.which('node')
    if not node:
        raise ValueError('Approved browser runtime unavailable')
    try:
        result = subprocess.run(
            [node, f'{MODULE}/smoke.mjs', '--frames', '30', '--frame-budget-ms', '20'],
            cwd=control.ROOT, env={'PATH': os.environ.get('PATH', os.defpath),
                                  'PLAYWRIGHT_BROWSERS_PATH': str(cache)},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=100, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Local browser probe exceeded its deadline') from exc
    if len(result.stdout) > 512 * 1024:
        raise ValueError('Browser receipt exceeds its bound')
    report = load_json(result.stdout)
    if (report.get('inputs') != reviewed['inputs']
            or report['toolchain']['playwright'] != policy['version']
            or report['network'] != {'bind': '127.0.0.1', 'external_requests': 0, 'authenticated_profiles': False}
            or report.get('functional_rendering_cases') != 3
            or report['performance_budget']['frame_budget_ms'] != 20
            or not control.source_matches({f'{MODULE}/{p}': h for p, h in reviewed['inputs'].items()})):
        raise ValueError('Local browser receipt does not match the approved runtime scope')
    cases = report['cases']
    if (len(cases) != 3 or {row['id'] for row in cases} != {row['id'] for row in reviewed['cases']}
            or any(row['benchmark']['frames'] != 30 or row['external_requests'] != 0
                   or row['page_errors'] != 0 for row in cases)):
        raise ValueError('Incomplete browser cases')
    passed = result.returncode == 0 and report['status'] == 'passed'
    return {'status': 'passed' if passed else 'failed', 'playwright': policy['version'],
            'browser': report['browser'], 'cases': len(cases), 'frames_per_case': 30,
            'frame_budget_ms': 20, 'maximum_p95_ms': max(row['benchmark']['p95_interval_ms'] for row in cases),
            'source_sha256': report['inputs'], 'receipt_sha256': hashlib.sha256(result.stdout).hexdigest(),
            'external_requests': 0, 'production_fps_verified': False}
