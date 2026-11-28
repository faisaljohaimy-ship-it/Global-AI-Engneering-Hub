"""Source-bound cinematic inventory. Local receipts are reviewer evidence, not attestation.

The owner's 200-name brief and main's 400 reference recipes are distinct sets.
PR16 is inspected historical source, never automatically imported or licensed here.
No browser, model, provider or render command is executed by this module.
SPDX-License-Identifier: MIT
"""
import datetime as dt
import hashlib
import pathlib
import time

from .orchestration import DIGEST, SLUG, load_json

ROOT = pathlib.Path(__file__).resolve().parents[1]
INVENTORY = 'docs/evidence/nextgen-cinematic-inventory.json'
INVENTORY_SHA256 = '2f333122218c14bb2bf66b763088374c9c23994df11e2fecd05fc036d56f2255'
CAMERA_SOURCE = 'motion-library/expansion/nextgen-camera.mjs'
CAMERA_IDS = frozenset({'camera-infinite-flythrough', 'camera-drone-approach', 'camera-macro-to-micro'})
BROWSERS = frozenset({'chromium', 'firefox', 'webkit'})
INPUTS = frozenset({CAMERA_SOURCE, 'packages/motion-sdk/index.mjs',
                   'tests/test_nextgen_camera_browser.mjs',
                   'motion-library/chromium-stack/package.json',
                   'motion-library/chromium-stack/package-lock.json'})
CHECKS = frozenset({'drawn', 'changes', 'deterministic', 'reduced_motion', 'rtl',
                    'exports', 'pause', 'stop', 'cleanup', 'cpu_budget'})
RECEIPT_SHA256 = {'chromium': '74f651227883ac0083c695d83f736c670d41de5cef8fac0f90b68a83b137e186'}


class CinematicError(ValueError):
    pass


def _file(relative):
    """Only canonical repo-local regular files, including every ancestor check."""
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise CinematicError('Invalid repository path')
    path = pathlib.PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or '.git' in path.parts or str(path) != relative:
        raise CinematicError('Unsafe repository path')
    result = ROOT
    for part in path.parts:
        result = result / part
        if result.is_symlink():
            raise CinematicError('Symlink source or proof refused')
    if not result.is_file():
        raise CinematicError('Missing source or proof')
    return result


def _read(relative):
    with _file(relative).open('rb') as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise CinematicError('Oversized cinematic metadata')
    return load_json(raw)


def _hash(relative):
    return hashlib.sha256(_file(relative).read_bytes()).hexdigest()


def _number(value, low, high):
    if type(value) not in {int, float} or not low <= value <= high:
        raise CinematicError('Invalid finite metric')
    return value


def _inventory():
    if _hash(INVENTORY) != INVENTORY_SHA256:
        raise CinematicError('Changed inspected owner inventory')
    value = _read(INVENTORY)
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise CinematicError('Invalid inventory schema')
    rows = value.get('motions')
    if not isinstance(rows, list) or len(rows) != 200:
        raise CinematicError('Owner brief must contain exactly 200 motions')
    numbers, identifiers = set(), set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'number', 'id', 'module', 'name', 'pr16_source', 'nextgen_source'}:
            raise CinematicError('Invalid brief row')
        if type(row['number']) is not int or not 1 <= row['number'] <= 200 or row['number'] in numbers:
            raise CinematicError('Duplicate or invalid brief number')
        if not isinstance(row['id'], str) or not SLUG.fullmatch(row['id']) or row['id'] in identifiers:
            raise CinematicError('Duplicate or invalid motion identity')
        if not isinstance(row['name'], str) or not 1 <= len(row['name']) <= 200 or not isinstance(row['module'], str) or not SLUG.fullmatch(row['module']):
            raise CinematicError('Invalid brief text')
        numbers.add(row['number']); identifiers.add(row['id'])
        if row['nextgen_source'] is not None and (row['id'] not in CAMERA_IDS or row['nextgen_source'] != CAMERA_SOURCE):
            raise CinematicError('Unknown local implementation')
        historical = row['pr16_source']
        if historical is not None:
            if not isinstance(historical, dict) or set(historical) != {'path', 'sha256'} or not isinstance(historical['sha256'], str) or not DIGEST.fullmatch(historical['sha256']):
                raise CinematicError('Invalid historical source binding')
            path = pathlib.PurePosixPath(historical['path'])
            if path.is_absolute() or '..' in path.parts or str(path) != historical['path'] or not str(path).startswith('packages/motion-engines/motions/'):
                raise CinematicError('Invalid historical path')
    if {row['id'] for row in rows if row['nextgen_source']} != CAMERA_IDS:
        raise CinematicError('Missing expected local source identity')
    return value


def _receipt(browser, now, max_age, budget):
    """A malformed, stale or changed receipt withdraws every affected runtime claim."""
    if _hash(f'docs/evidence/nextgen-camera-{browser}.json') != RECEIPT_SHA256.get(browser):
        raise CinematicError('Changed or unreviewed receipt bytes')
    value = _read(f'docs/evidence/nextgen-camera-{browser}.json')
    if not isinstance(value, dict) or value.get('schema_version') != 1 or value.get('status') != 'passed' or value.get('browser') != browser:
        raise CinematicError('Invalid browser receipt')
    stamp = value.get('recorded_at_utc')
    if not isinstance(stamp, str):
        raise CinematicError('Missing receipt time')
    at = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if at.tzinfo is None or at.utcoffset() != dt.timedelta(0) or not 0 <= now - at.timestamp() <= max_age:
        raise CinematicError('Stale or future browser proof')
    inputs = value.get('inputs')
    if not isinstance(inputs, dict) or set(inputs) != INPUTS or any(not isinstance(v, str) or not DIGEST.fullmatch(v) or _hash(k) != v for k, v in inputs.items()):
        raise CinematicError('Changed or incomplete source binding')
    reviewed_version = _read('motion-library/chromium-stack/package.json')['devDependencies']['playwright']
    if value.get('playwright_version') != reviewed_version:
        raise CinematicError('Unreviewed browser harness runtime')
    if not isinstance(value.get('browser_version'), str) or not value['browser_version'] or len(value['browser_version']) > 80:
        raise CinematicError('Missing browser identity')
    if value.get('page_errors') != 0 or type(value.get('page_errors')) is not int or value.get('external_requests') != 0 or type(value.get('external_requests')) is not int:
        raise CinematicError('Runtime page/network failure')
    if any(value.get(key) is not False for key in ['production_fps_verified', 'real_devices_verified', 'gpu_runtime_verified']):
        raise CinematicError('Unsupported performance/device/GPU claim')
    rows = value.get('cases')
    if not isinstance(rows, list) or len(rows) != 6:
        raise CinematicError('Incomplete browser matrix')
    found = set()
    for row in rows:
        if not isinstance(row, dict) or row.get('id') not in CAMERA_IDS:
            raise CinematicError('Unknown browser motion')
        viewport = row.get('viewport')
        if viewport not in [{'width': 390, 'height': 844}, {'width': 1280, 'height': 720}]:
            raise CinematicError('Unverified viewport')
        key = (row['id'], viewport['width'], viewport['height'])
        if key in found:
            raise CinematicError('Duplicate browser case')
        found.add(key)
        checks = row.get('checks')
        if not isinstance(checks, dict) or set(checks) != CHECKS or any(v is not True for v in checks.values()):
            raise CinematicError('Failed required rendering behavior')
        frames = row.get('frames')
        if not isinstance(frames, list) or len(frames) != 3:
            raise CinematicError('Missing pixel proof')
        for frame in frames:
            if not isinstance(frame, dict) or set(frame) != {'sha256', 'drawn_pixels'} or not isinstance(frame['sha256'], str) or not DIGEST.fullmatch(frame['sha256']):
                raise CinematicError('Invalid pixel proof')
            if type(frame['drawn_pixels']) is not int or not 100 < frame['drawn_pixels'] <= viewport['width'] * viewport['height']:
                raise CinematicError('Blank or invalid frame')
        if len({frame['sha256'] for frame in frames}) != 3:
            raise CinematicError('Frames did not change')
        benchmark = row.get('benchmark')
        if not isinstance(benchmark, dict) or benchmark.get('kind') != 'synchronous-sampling-and-draw' or benchmark.get('frames') != 45 or benchmark.get('within_cpu_budget') is not True or benchmark.get('production_fps_verified') is not False or benchmark.get('engine') != 'canvas2d':
            raise CinematicError('Invalid performance evidence')
        p95 = _number(benchmark.get('p95_ms'), 0, budget)
        maximum = _number(benchmark.get('max_ms'), p95, 100000)
        _number(benchmark.get('median_ms'), 0, p95)
        _number(benchmark.get('budget_ms'), p95, budget)
    return {'browser': browser, 'version': value.get('browser_version'),
            'playwright': value.get('playwright_version'), 'cases': len(found),
            'source_bound': True, 'receipt_sha256': _hash(f'docs/evidence/nextgen-camera-{browser}.json'),
            'maximum_p95_ms': max(row['benchmark']['p95_ms'] for row in rows)}


def audit_inventory(request=None, *, now=None):
    """Read-only unified inventory; runtime eligibility requires every requested browser.

    Requests select required browsers and stricter freshness/CPU budgets only.
    Reported receipts must still be reviewed before project adoption. API accepts
    no arbitrary paths, rendering commands, remote engines or paid services.
    """
    request = {'schema_version': 1, 'required_browsers': ['chromium', 'firefox', 'webkit'],
               'max_age_seconds': 86400, 'max_p95_ms': 25} if request is None else request
    fields = {'schema_version', 'required_browsers', 'max_age_seconds', 'max_p95_ms'}
    if not isinstance(request, dict) or set(request) != fields or type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise CinematicError('Invalid cinematic request')
    browsers = request['required_browsers']
    if not isinstance(browsers, list) or not browsers or any(not isinstance(x, str) or x not in BROWSERS for x in browsers) or len(set(browsers)) != len(browsers):
        raise CinematicError('Unknown or duplicate required browser')
    age = _number(request['max_age_seconds'], 1, 86400)
    budget = _number(request['max_p95_ms'], .1, 25)
    now = _number(time.time() if now is None else now, 0, 2**53 - 1)
    inventory = _inventory()
    local_source_present = _file(CAMERA_SOURCE).is_file()
    verified, withdrawn = {}, {}
    for browser in sorted(BROWSERS):
        try:
            verified[browser] = _receipt(browser, now, age, budget)
        except (ValueError, OSError, TypeError, KeyError, OverflowError):
            withdrawn[browser] = 'missing_stale_changed_or_failed_receipt'
    complete = set(browsers) <= set(verified)
    rows = []
    for row in inventory['motions']:
        local = bool(row['nextgen_source']) and local_source_present
        rows.append({'id': row['id'], 'number': row['number'], 'name': row['name'],
                     'source_state': 'local_implemented' if local else 'historical_pr16_only' if row['pr16_source'] else 'not_implemented',
                     'runtime_state': 'verified_requested_browsers' if local and complete else 'not_verified_for_requested_browsers'})
    return {'schema_version': 1, 'brief_count': len(rows),
            'historical_pr16_source_count': sum(bool(row['pr16_source']) for row in inventory['motions']),
            'local_implemented_count': sum(row['source_state'] == 'local_implemented' for row in rows),
            'not_implemented_in_either_inspected_source_count': sum(row['source_state'] == 'not_implemented' for row in rows),
            'operational_for_requested_browsers_count': sum(row['runtime_state'] == 'verified_requested_browsers' for row in rows),
            'required_browsers': sorted(browsers), 'verified_browser_receipts': verified,
            'withdrawn_browser_claims': withdrawn, 'motions': rows,
            'engines': {'canvas2d': 'source_bound_browser_evidence' if verified else 'implemented_source_only',
                        **{name: 'not_activated_by_this_change' for name in ['threejs', 'webgpu', 'webgl', 'gsap', 'motion', 'remotion', 'blender', 'rive', 'lottie', 'react-three-fiber', 'shader-engines', 'gpu-particle-systems']}},
            'pr16': {**inventory['brief'], 'merged': False, 'runtime_reverified_here': False, 'license': 'outside_existing_scoped_MIT; adoption_requires_owner_review'},
            'production_fps_verified': False, 'real_devices_verified': False,
            'reference_recipes_excluded': 400, 'provider_calls': 0,
            'evidence_boundary': 'Local reviewer receipts bound to source, not authenticated attestation or project activation.'}


def catalog_report():
    return audit_inventory()
