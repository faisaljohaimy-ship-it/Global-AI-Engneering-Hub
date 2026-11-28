"""Run the fixed, repository-owned acceptance suites for the 20 local layers.

The report covers these named checks at the current checkout. Provider accounts,
devices and deployed products require their own evidence. SPDX-License-Identifier: MIT.
"""

import argparse
import hashlib
import io
import json
import re
import subprocess
import unittest

from . import control


CHECKS = {
    'L01': ('tests/test_sdk.py',),
    'L02': ('tests/test_model_router.py',),
    'L03': ('tests/test_os_orchestration.py',),
    'L04': ('tests/test_hub.py',),
    'L05': ('tests/test_claude_bridge.py',),
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
    'L20': ('tests/test_intelligence.py', 'tests/test_claude_bridge.py', 'tests/test_layer_checks.py'),
}


def _run_suite(name):
    path = control.safe_path(name)
    if not path.is_file():
        return {'suite': name, 'status': 'missing', 'tests': 0, 'skipped': 0}
    if path.suffix == '.py':
        suite = unittest.TestLoader().discover(str(path.parent), pattern=path.name)
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        passed = result.wasSuccessful() and result.testsRun > 0 and not result.skipped
        return {'suite': name, 'status': 'passed' if passed else 'failed',
                'tests': result.testsRun, 'skipped': len(result.skipped)}
    result = subprocess.run(['node', '--test', '--test-reporter=tap', name],
                            cwd=control.ROOT, capture_output=True, text=True, timeout=90)
    counts = dict(re.findall(r'^# (tests|skipped|todo) (\d+)$', result.stdout, re.MULTILINE))
    count = int(counts.get('tests', 0))
    skipped = int(counts.get('skipped', 0)) + int(counts.get('todo', 0))
    passed = result.returncode == 0 and count > 0 and len(counts) == 3 and not skipped
    return {'suite': name, 'status': 'passed' if passed else 'failed',
            'tests': count, 'skipped': skipped}


def verify_layers(layer=None):
    """Measure fixed local tests and bind their result to the declared source paths."""
    if layer is not None and layer not in CHECKS:
        raise ValueError('Unknown layer')
    if set(CHECKS) != {row[0] for row in control.LAYERS}:
        raise ValueError('Layer and acceptance suite identifiers differ')
    rows = []
    suites = {}
    for identifier, _, sources in control.LAYERS:
        if layer is not None and identifier != layer:
            continue
        inputs = sorted(set([*sources, *CHECKS[identifier], 'engineering_os/layer_checks.py']))
        hashes = {name: hashlib.sha256(control.safe_path(name).read_bytes()).hexdigest()
                  for name in inputs if control.safe_path(name).is_file()}
        for name in CHECKS[identifier]:
            if name not in suites:
                try:
                    suites[name] = _run_suite(name)
                except (OSError, subprocess.TimeoutExpired):
                    suites[name] = {'suite': name, 'status': 'unavailable', 'tests': 0, 'skipped': 0}
        checks = [suites[name] for name in CHECKS[identifier]]
        passed = len(hashes) == len(inputs) and control.source_matches(hashes) and all(
            check['status'] == 'passed' for check in checks)
        rows.append({'id': identifier, 'status': 'passed' if passed else 'failed',
                     'checks': checks, 'source_sha256': hashes})
    return {'schema_version': 1, 'scope': 'fixed local acceptance suites',
            'passed': sum(row['status'] == 'passed' for row in rows), 'layers': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layer', choices=tuple(CHECKS))
    report = verify_layers(parser.parse_args().layer)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['passed'] == len(report['layers']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
