"""Run the fixed, repository-owned acceptance suites for the 20 local layers.

The report covers these named checks at the current checkout. Provider accounts,
devices and deployed products require their own evidence. SPDX-License-Identifier: MIT.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile

from . import control


CHECKS = {
    'L01': ('tests/test_sdk.py',),
    'L02': ('tests/test_model_router.py',),
    'L03': ('tests/test_os_orchestration.py',),
    'L04': ('tests/test_hub.py',),
    'L05': ('tests/test_claude_bridge.py', 'tests/test_capability_scope.py',
            'tests/test_master_approval.py', 'tests/test_master_workflow.py', 'tests/test_mcp_local_tools.py'),
    'L06': ('tests/test_factory_generate.py',),
    'L07': ('tests/test_engineering_memory.py',),
    'L08': ('tests/test_universal_motion_sdk.mjs',),
    'L09': ('tests/test_security.py', 'tests/test_security_scan.py'),
    'L10': ('tests/test_link.py',),
    'L11': ('tests/test_release_provenance.py',),
    'L12': ('tests/test_technology_discovery.py',),
    'L13': ('tests/test_reasoning.py',),
    'L14': ('tests/test_engineering_memory.py',),
    'L15': ('tests/test_factory.py',),
    'L16': ('tests/test_factory_generate.py',),
    'L17': ('tests/test_healing.py', 'tests/test_healing_runtime.py'),
    'L18': ('tests/test_cinematic_intelligence.py', 'tests/test_nextgen_camera.mjs',
            'tests/test_nextgen_originals.mjs', 'tests/test_nextgen_motion_catalog.mjs',
            'tests/test_nextgen_motion_compositions.mjs', 'tests/test_nextgen_motion_light.mjs',
            'tests/test_nextgen_motion_particles.mjs', 'tests/test_nextgen_motion_physics.mjs',
            'tests/test_nextgen_motion_scenes.mjs', 'tests/test_nextgen_motion_symbols.mjs',
            'tests/test_nextgen_motion_systems.mjs', 'tests/test_nextgen_motion_ui.mjs',
            'tests/test_nextgen_motion_webgl.mjs'),
    'L19': ('tests/test_economics.py',),
    'L20': ('tests/test_intelligence.py', 'tests/test_claude_bridge.py', 'tests/test_layer_checks.py',
            'tests/test_master_approval.py', 'tests/test_master_workflow.py', 'tests/test_capability_scope.py',
            'tests/test_claude_native_fixture.py', 'tests/test_mcp_local_tools.py'),
}

MCP_INPUTS = (
    '.mcp.json', 'CLAUDE.md', 'engineering_os/claude_bridge.py', 'engineering_os/intelligence.py',
    'engineering_os/master_approval.py', 'engineering_os/master_workflow.py', 'engineering_os/capability_scope.py',
    'engineering_os/mcp_local_tools.py', 'scripts/verify_claude_master_mcp.py',
    'engineering_os/orchestration.py', 'engineering_os/memory.py', 'engineering_os/factory.py',
    'engineering_os/factory_generate.py', 'engineering_os/healing.py', 'engineering_os/healing_runtime.py',
    'engineering_os/reasoning.py', 'engineering_os/economics.py', 'engineering_os/cinematic.py',
    'scripts/security_scan.py',
)
SUPPLEMENTARY_INPUTS = {
    'L05': MCP_INPUTS,
    'L11': ('scripts/verify_release.py', '.github/workflows/release.yml', '.github/workflows/nextgen-intelligence.yml'),
    'L20': MCP_INPUTS,
}
COMMON_INPUTS = ('engineering_os/control.py', 'engineering_os/layer_checks.py')
MAX_INPUT_BYTES = 16 * 1024 * 1024
SUITE_TIMEOUT = 90


def _run_suite(name):
    path = control.safe_path(name)
    if not path.is_file():
        return {'suite': name, 'status': 'missing', 'tests': 0, 'skipped': 0}
    env = {'PATH': os.environ.get('PATH', os.defpath), 'LANG': 'C.UTF-8'}
    if path.suffix == '.py':
        # A fresh interpreter with an empty bytecode location ensures the observed
        # source is loaded, even when the caller previously imported repository modules.
        with tempfile.TemporaryDirectory(prefix='gaie-layer-cache-') as cache:
            result = subprocess.run(
                [sys.executable, '-E', '-s', '-B', '-X', f'pycache_prefix={cache}', '-m', 'unittest',
                 'discover', '-s', str(path.parent), '-p', path.name],
                cwd=control.ROOT, env=env, capture_output=True, text=True, timeout=SUITE_TIMEOUT,
            )
        counts = re.findall(r'^Ran (\d+) tests? in [0-9.]+s$', result.stderr, re.MULTILINE)
        count = int(counts[0]) if len(counts) == 1 else 0
        summaries = [line for line in result.stderr.splitlines()
                     if line == 'OK' or line.startswith(('OK (', 'FAILED ('))]
        skipped = sum(map(int, re.findall(r'\bskipped=(\d+)', '\n'.join(summaries))))
        passed = result.returncode == 0 and count > 0 and summaries == ['OK']
        return {'suite': name, 'status': 'passed' if passed else 'failed', 'tests': count, 'skipped': skipped}
    if path.suffix != '.mjs':
        return {'suite': name, 'status': 'unavailable', 'tests': 0, 'skipped': 0}
    result = subprocess.run(['node', '--test', '--test-reporter=tap', name],
                            cwd=control.ROOT, env=env, capture_output=True, text=True, timeout=SUITE_TIMEOUT)
    rows = re.findall(r'^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$', result.stdout, re.MULTILINE)
    counts = {key: int(value) for key, value in rows}
    count = int(counts.get('tests', 0))
    skipped = int(counts.get('skipped', 0)) + int(counts.get('todo', 0))
    passed = (result.returncode == 0 and count > 0 and len(rows) == len(counts) == 6
              and counts['pass'] == count and counts['fail'] == counts['cancelled'] == skipped == 0)
    return {'suite': name, 'status': 'passed' if passed else 'failed',
            'tests': count, 'skipped': skipped}


def _file_stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _snapshot(names):
    values = {}
    for name in sorted(names):
        try:
            path = control.safe_path(name)
            if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                continue
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_INPUT_BYTES:
                    continue
                data = stream.read(MAX_INPUT_BYTES + 1)
                after = os.fstat(stream.fileno())
                if (len(data) == before.st_size and _file_stamp(before) == _file_stamp(after)
                        and _file_stamp(after) == _file_stamp(path.stat(follow_symlinks=False))):
                    values[name] = (hashlib.sha256(data).hexdigest(), _file_stamp(after))
        except (OSError, ValueError):
            continue
    return values


def _passed_suite(expected, result):
    return (isinstance(result, dict) and result.get('suite') == expected
            and result.get('status') == 'passed'
            and type(result.get('tests')) is int and result['tests'] > 0
            and type(result.get('skipped')) is int and result['skipped'] == 0)


def verify_layers(layer=None):
    """Measure all selected tests between two snapshots of their declared inputs."""
    if layer is not None and layer not in CHECKS:
        raise ValueError('Unknown layer')
    if set(CHECKS) != {row[0] for row in control.LAYERS}:
        raise ValueError('Layer and acceptance suite identifiers differ')
    scope = {}
    for identifier, _, sources in control.LAYERS:
        if layer is not None and identifier != layer:
            continue
        scope[identifier] = set((*sources, *CHECKS[identifier], *COMMON_INPUTS,
                                 *SUPPLEMENTARY_INPUTS.get(identifier, ())))
    inputs = set().union(*scope.values())
    before = _snapshot(inputs)

    suites = {}
    for identifier in scope:
        for name in CHECKS[identifier]:
            if name not in suites:
                try:
                    suites[name] = _run_suite(name)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    suites[name] = {'suite': name, 'status': 'unavailable', 'tests': 0, 'skipped': 0}

    after = _snapshot(inputs)
    changed = sorted(name for name in inputs if before.get(name) != after.get(name))
    rows = []
    for identifier, names in scope.items():
        checks = [suites[name] for name in CHECKS[identifier]]
        unavailable = sorted(names - (before.keys() & after.keys()))
        passed = not changed and not unavailable and bool(checks) and all(
            _passed_suite(expected, check) for expected, check in zip(CHECKS[identifier], checks))
        hashes = {name: before[name][0] for name in sorted(names) if name in before}
        rows.append({'id': identifier, 'status': 'passed' if passed else 'failed',
                     'checks': checks, 'source_sha256': hashes, 'unavailable_inputs': unavailable})
    return {'schema_version': 1, 'scope': 'fixed local acceptance suites',
            'passed': sum(row['status'] == 'passed' for row in rows), 'layers': rows,
            'inputs_changed_during_verification': changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layer', choices=tuple(CHECKS))
    report = verify_layers(parser.parse_args().layer)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['passed'] == len(report['layers']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
