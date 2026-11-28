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
LOCAL_INVENTORY = 'docs/evidence/nextgen-local-motion-inventory.json'
AGGREGATE_CATALOG = 'motion-library/expansion/nextgen-catalog.mjs'
WEBGL_SOURCE = 'motion-library/expansion/nextgen-motion-webgl.mjs'
WEBGL_IDS = frozenset({
    'particles-gpu-swarm', 'shaders-noise-displacement', 'shaders-raymarched-geometry',
    'shaders-sdf-morph', 'shaders-ripple', 'shaders-chromatic-aberration', 'shaders-fractal',
    'shaders-wave-interference', 'shaders-fresnel', 'shaders-material-dissolve',
    'compositions-multi-engine-cinematic', 'compositions-gpu-interface-transformation',
})
INPUTS = frozenset({LOCAL_INVENTORY, AGGREGATE_CATALOG, 'packages/motion-sdk/index.mjs',
                   'tests/test_nextgen_originals_browser.mjs', 'motion-library/verify/serve.mjs',
                   'motion-library/chromium-stack/package.json',
                   'motion-library/chromium-stack/package-lock.json'})
CHECKS = frozenset({'drawn', 'changes', 'deterministic', 'reduced_motion', 'rtl',
                    'exports', 'pause', 'stop', 'cleanup', 'cpu_budget'})
WEBGL_INPUTS = frozenset({WEBGL_SOURCE, 'tests/test_nextgen_webgl_browser.mjs',
                         'motion-library/chromium-stack/harness.html',
                         'motion-library/chromium-stack/package.json',
                         'motion-library/chromium-stack/package-lock.json',
                         'motion-library/verify/serve.mjs'})
WEBGL_CHECKS = frozenset({'actual_webgl2', 'drawn', 'opaque', 'changes', 'deterministic',
                         'reduced_motion', 'rtl', 'png', 'duplicate_canvas_rejected', 'cleanup',
                         'bounded_framebuffer', 'budget'})
RECEIPT_SHA256 = {'chromium': '9d2d71ea508598c6c1b832c2a6a57e6fffb29dba4bfea72ffcab984834fb5565', 'firefox': '7649722f9ea66f22e9ef36b6aa74a39042145b9faa94b6c8ccf121bd8817aa1a', 'webkit': '2d1b89f8f7a11382e9c3f27016591fe6c0f68012256bfab7f1fe587b55a7f2c2'}
WEBGL_RECEIPT_SHA256 = {'chromium': 'd9c7e57d34d044aab2eb8da0dcf1f081a7b5071f2cedda5e5f81fabf6556a3fb', 'firefox': 'ede4c28302684b0b785417178b2bb46829208d59ed08d86a267a27205073c9d6', 'webkit': 'ff0bf9467faf65b25df4a6c28f615ee48aae7aa6afac03468650c815d86d9d37'}


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


def _bytes(relative):
    with _file(relative).open('rb') as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise CinematicError('Oversized cinematic metadata')
    return raw


def _read(relative):
    return load_json(_bytes(relative))


def _hash(relative):
    return hashlib.sha256(_bytes(relative)).hexdigest()


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


def _local_catalogs(inventory):
    manifest = _read(LOCAL_INVENTORY)
    if not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'catalogs'} or manifest['schema_version'] != 1:
        raise CinematicError('Invalid local motion inventory')
    available = {row['id'] for row in inventory['motions'] if row['pr16_source'] is None}
    sources = set()
    identities = {}
    catalogs = manifest['catalogs']
    if not isinstance(catalogs, list) or not 1 <= len(catalogs) <= 20:
        raise CinematicError('Invalid local catalog list')
    for catalog in catalogs:
        if not isinstance(catalog, dict) or set(catalog) != {'source', 'ids'}:
            raise CinematicError('Invalid local catalog entry')
        source = catalog['source']
        if (not isinstance(source, str) or not source.startswith('motion-library/expansion/nextgen-')
                or not source.endswith('.mjs') or source in sources or source == AGGREGATE_CATALOG):
            raise CinematicError('Invalid or duplicate catalog source')
        _file(source)
        sources.add(source)
        ids = catalog['ids']
        if not isinstance(ids, list) or not ids or len(ids) > len(available):
            raise CinematicError('Invalid motion identity list')
        for identifier in ids:
            if not isinstance(identifier, str) or identifier not in available or identifier in identities:
                raise CinematicError('Motion ID is duplicate, absent from the brief or historical')
            identities[identifier] = source
    if any(identities.get(identifier) != CAMERA_SOURCE for identifier in CAMERA_IDS):
        raise CinematicError('Missing first camera catalog')
    return identities, INPUTS | sources


def _receipt(browser, now, max_age, budget, identities, expected_inputs, *, webgl=False):
    """A malformed, stale or changed receipt withdraws every affected runtime claim."""
    engine = 'webgl' if webgl else 'originals'
    raw = _bytes(f'docs/evidence/nextgen-{engine}-{browser}.json')
    digest = hashlib.sha256(raw).hexdigest()
    pins = WEBGL_RECEIPT_SHA256 if webgl else RECEIPT_SHA256
    if digest != pins.get(browser):
        raise CinematicError('Changed or unreviewed receipt bytes')
    value = load_json(raw)
    if not isinstance(value, dict) or value.get('schema_version') != (1 if webgl else 2) or value.get('status') != 'passed' or value.get('browser') != browser:
        raise CinematicError('Invalid browser receipt')
    stamp = value.get('recorded_at_utc')
    if not isinstance(stamp, str):
        raise CinematicError('Missing receipt time')
    at = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if at.tzinfo is None or at.utcoffset() != dt.timedelta(0) or not 0 <= now - at.timestamp() <= max_age:
        raise CinematicError('Stale or future browser proof')
    inputs = value.get('inputs')
    if not isinstance(inputs, dict) or set(inputs) != expected_inputs or any(not isinstance(v, str) or not DIGEST.fullmatch(v) or _hash(k) != v for k, v in inputs.items()):
        raise CinematicError('Changed or incomplete source binding')
    reviewed_version = _read('motion-library/chromium-stack/package.json')['devDependencies']['playwright']
    if value.get('playwright_version') != reviewed_version:
        raise CinematicError('Unreviewed browser harness runtime')
    if not isinstance(value.get('browser_version'), str) or not value['browser_version'] or len(value['browser_version']) > 80:
        raise CinematicError('Missing browser identity')
    if value.get('page_errors') != 0 or type(value.get('page_errors')) is not int or value.get('external_requests') != 0 or type(value.get('external_requests')) is not int:
        raise CinematicError('Runtime page/network failure')
    acceleration_claim = 'hardware_verified' if webgl else 'gpu_runtime_verified'
    if any(value.get(key) is not False for key in ['production_fps_verified', 'real_devices_verified', acceleration_claim]):
        raise CinematicError('Unsupported performance/device/GPU claim')
    if webgl and value.get('runtime') != 'webgl2':
        raise CinematicError('WebGL2 engine proof required')
    rows = value.get('cases')
    if not isinstance(rows, list) or len(rows) != 2 * len(identities):
        raise CinematicError('Incomplete browser matrix')
    found = set()
    for row in rows:
        if not isinstance(row, dict) or row.get('id') not in identities:
            raise CinematicError('Unknown browser motion')
        viewport = row.get('viewport')
        if viewport not in [{'width': 390, 'height': 844}, {'width': 1280, 'height': 720}]:
            raise CinematicError('Unverified viewport')
        key = (row['id'], viewport['width'], viewport['height'])
        if key in found:
            raise CinematicError('Duplicate browser case')
        found.add(key)
        checks = row.get('checks')
        if not isinstance(checks, dict) or set(checks) != (WEBGL_CHECKS if webgl else CHECKS) or any(v is not True for v in checks.values()):
            raise CinematicError('Failed required rendering behavior')
        area = viewport['width'] * viewport['height']
        if webgl:
            runtime = row.get('runtime')
            if not isinstance(runtime, dict) or runtime.get('engine') != 'webgl2' or runtime.get('viewport') != viewport:
                raise CinematicError('Missing WebGL2 render evidence')
            renderers = ['webgl2', 'canvas2d'] if row['id'] == 'compositions-multi-engine-cinematic' else ['webgl2']
            if runtime.get('renderers') != renderers or runtime.get('hardware_verified') is not False:
                raise CinematicError('Invalid renderer claim')
            if row['id'] == 'particles-gpu-swarm' and runtime.get('particles') != 2048:
                raise CinematicError('Incomplete GPU particle proof')
            size = runtime['source_framebuffer']
            if (not isinstance(size, dict) or set(size) != {'width', 'height'}
                    or any(type(v) is not int or not 1 <= v <= 416 for v in size.values())):
                raise CinematicError('Invalid framebuffer dimensions')
            area = size['width'] * size['height']
            if area > 131072:
                raise CinematicError('WebGL2 framebuffer exceeds budget')
        frames = row.get('frames')
        if not isinstance(frames, list) or len(frames) != 3:
            raise CinematicError('Missing pixel proof')
        for frame in frames:
            fields = {'sha256', 'drawn_pixels', 'opaque_pixels'} if webgl else {'sha256', 'drawn_pixels'}
            if not isinstance(frame, dict) or set(frame) != fields or not isinstance(frame['sha256'], str) or not DIGEST.fullmatch(frame['sha256']):
                raise CinematicError('Invalid pixel proof')
            if type(frame['drawn_pixels']) is not int or not 100 < frame['drawn_pixels'] <= area:
                raise CinematicError('Blank or invalid frame')
            if webgl and frame['opaque_pixels'] != area:
                raise CinematicError('Invalid WebGL2 opacity proof')
        if len({frame['sha256'] for frame in frames}) != 3:
            raise CinematicError('Frames did not change')
        benchmark = row.get('benchmark')
        benchmark_kind = 'webgl2-draw-and-finish' if webgl else 'synchronous-sampling-and-draw'
        if (not isinstance(benchmark, dict) or benchmark.get('kind') != benchmark_kind
                or benchmark.get('frames') != (24 if webgl else 45)
                or benchmark.get('within_cpu_budget') is not True
                or benchmark.get('production_fps_verified') is not False
                or (not webgl and benchmark.get('engine') != 'canvas2d')):
            raise CinematicError('Invalid performance evidence')
        p95 = _number(benchmark.get('p95_ms'), 0, budget)
        _number(benchmark.get('max_ms'), p95, 100000)
        _number(benchmark.get('median_ms'), 0, p95)
        _number(benchmark.get('budget_ms'), p95, 25)
    return {'browser': browser, 'version': value.get('browser_version'),
            'playwright': value.get('playwright_version'), 'cases': len(found),
            'source_bound': True, 'receipt_sha256': digest,
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
    local, expected_inputs = _local_catalogs(inventory)
    webgl_authored = (ROOT / WEBGL_SOURCE).is_file()
    if webgl_authored:
        _file(WEBGL_SOURCE)
        eligible = {row['id'] for row in inventory['motions'] if row['pr16_source'] is None}
        if not WEBGL_IDS <= eligible or WEBGL_IDS & local.keys():
            raise CinematicError('WebGL catalog overlaps the Canvas2D or historical inventory')
    verified, withdrawn = {}, {}
    verified_webgl = {}
    for browser in sorted(BROWSERS):
        try:
            verified[browser] = _receipt(browser, now, age, budget, local, expected_inputs)
        except (ValueError, OSError, TypeError, KeyError, OverflowError):
            withdrawn[browser] = 'missing_stale_changed_or_failed_receipt'
        if webgl_authored:
            try:
                verified_webgl[browser] = _receipt(browser, now, age, budget, WEBGL_IDS, WEBGL_INPUTS, webgl=True)
            except (ValueError, OSError, TypeError, KeyError, OverflowError):
                pass
    complete = set(browsers) <= set(verified)
    complete_webgl = set(browsers) <= set(verified_webgl)
    rows = []
    for row in inventory['motions']:
        present = row['id'] in local
        webgl = webgl_authored and row['id'] in WEBGL_IDS
        runtime_verified = (present and complete) or (webgl and complete_webgl)
        rows.append({'id': row['id'], 'number': row['number'], 'name': row['name'],
                     'source_state': 'local_implemented' if present or webgl else 'historical_pr16_only' if row['pr16_source'] else 'not_implemented',
                     'engine': 'webgl2' if webgl else 'canvas2d' if present else None,
                     'runtime_state': 'verified_requested_browsers' if runtime_verified else 'not_verified_for_requested_browsers'})
    return {'schema_version': 1, 'brief_count': len(rows),
            'historical_pr16_source_count': sum(bool(row['pr16_source']) for row in inventory['motions']),
            'local_implemented_count': sum(row['source_state'] == 'local_implemented' for row in rows),
            'not_implemented_in_either_inspected_source_count': sum(row['source_state'] == 'not_implemented' for row in rows),
            'operational_for_requested_browsers_count': sum(row['runtime_state'] == 'verified_requested_browsers' for row in rows),
            'required_browsers': sorted(browsers), 'verified_browser_receipts': verified,
            'verified_webgl2_browser_receipts': verified_webgl,
            'withdrawn_browser_claims': withdrawn, 'motions': rows,
            'engines': {'canvas2d': 'source_bound_browser_evidence' if verified else 'implemented_source_only',
                        'webgl2': 'source_bound_browser_evidence' if verified_webgl else 'implemented_source_only' if webgl_authored else 'unavailable',
                        **{name: 'not_activated_by_this_change' for name in ['threejs', 'webgpu', 'gsap', 'motion', 'remotion', 'blender', 'rive', 'lottie', 'react-three-fiber']}},
            'pr16': {**inventory['brief'], 'merged': False, 'runtime_reverified_here': False, 'license': 'outside_existing_scoped_MIT; adoption_requires_owner_review'},
            'production_fps_verified': False, 'real_devices_verified': False,
            'reference_recipes_excluded': 400, 'provider_calls': 0,
            'evidence_boundary': 'Local reviewer receipts bound to source, not authenticated attestation or project activation.'}


def catalog_report():
    return audit_inventory()
