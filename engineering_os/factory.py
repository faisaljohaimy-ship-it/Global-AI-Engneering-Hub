"""Deterministic artifact workflow for the software factory. SPDX-License-Identifier: MIT.

This module plans delivery and verifies artifacts and supplied evaluator receipts.
It does not generate a complete application, execute artifact code, authenticate
reviewers, run tests or deploy. Receipts need an independently trusted evaluator;
checksums bind bytes and dependencies, not the truth of an evaluator's assertion.
Keep project artifacts and receipts in private project storage, outside this hub.
"""

import copy
import hashlib
import os
import pathlib
import re
import stat

from .orchestration import DIGEST, _slug, _text, canonical, load_json, sha

TARGETS = frozenset({'web', 'backend', 'mobile', 'ai', 'database', 'api'})
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_RECEIPTS = 12
# Stage-specific data contracts supplement the universal acceptance trace.
CONTRACTS = {
    'requirements': ('specification', ('requirements', 'data_boundaries'), ('acceptance',)),
    'architecture': ('architecture', ('components', 'decisions', 'constraints'), ('architecture_review',)),
    'database': ('database', ('entities', 'migrations', 'rollback'), ('migration', 'data_isolation')),
    'api': ('api', ('operations', 'authentication', 'errors'), ('contract', 'authorization')),
    'frontend': ('frontend', ('routes', 'components', 'accessibility'), ('browser', 'accessibility')),
    'backend': ('backend', ('services', 'boundaries', 'configuration'), ('integration',)),
    'mobile': ('mobile', ('screens', 'platforms', 'offline'), ('device', 'accessibility')),
    'ai': ('ai', ('models', 'privacy', 'evaluation'), ('evaluation', 'privacy')),
    'testing': ('test_report', ('suites', 'regressions', 'coverage'), ('unit', 'integration', 'regression')),
    'security': ('security_report', ('threats', 'findings', 'remediations'), ('secrets', 'dependencies', 'security')),
    'documentation': ('documentation', ('setup', 'operations', 'limitations'), ('documentation_review',)),
    'release': ('release_manifest', ('revision', 'rollback', 'verification'), ('release_review', 'rollback')),
}


class FactoryError(ValueError):
    """A malformed workflow or unverifiable artifact was refused."""


def _exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise FactoryError('Invalid ' + label + ' fields')


def _list(value, label, maximum=200, nonempty=True):
    if not isinstance(value, list) or len(value) > maximum or (nonempty and not value):
        raise FactoryError('Invalid ' + label + ' list')
    return value


def _identifier(value):
    try:
        return _slug(value)
    except ValueError as error:
        raise FactoryError('Invalid identifier') from error


def _digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise FactoryError('Invalid SHA256')
    return value


def _revision(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', value):
        raise FactoryError('A pinned source revision is required')
    return value


def _unique_ids(values, label, maximum=200, nonempty=True):
    values = _list(values, label, maximum, nonempty)
    for value in values:
        _identifier(value)
    if len(values) != len(set(values)):
        raise FactoryError('Duplicate ' + label)
    return sorted(values)


def _request(request):
    _exact(request, {'schema_version', 'project', 'source_revision', 'requirements', 'targets'}, 'request')
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise FactoryError('Invalid schema version')
    _identifier(request['project'])
    _revision(request['source_revision'])
    targets = _unique_ids(request['targets'], 'targets', 6)
    if not set(targets) <= TARGETS:
        raise FactoryError('Unknown target')
    requirements = []
    for row in _list(request['requirements'], 'requirements', 100):
        _exact(row, {'id', 'summary', 'acceptance'}, 'requirement')
        _identifier(row['id'])
        try:
            _text(row['summary'], 1000)
        except ValueError as error:
            raise FactoryError('Unsafe requirement summary') from error
        requirements.append({**row, 'acceptance': _unique_ids(row['acceptance'], 'acceptance', 50)})
    if len({row['id'] for row in requirements}) != len(requirements):
        raise FactoryError('Duplicate requirement')
    return {**copy.deepcopy(request), 'targets': targets,
            'requirements': sorted(requirements, key=lambda row: row['id'])}


def plan_factory(request):
    """Produce a deterministic dependency graph and artifact/check contracts.

    All requirements are traced at every stage. Unneeded technology stages are
    omitted according to explicit targets; mandatory testing/security/release
    stages cannot be omitted. Actual source revision validity is a caller gate.
    """
    request = _request(request)
    targets = set(request['targets'])
    requirements = [row['id'] for row in request['requirements']]
    stages = []

    def add(identifier, dependencies):
        kind, fields, checks = CONTRACTS[identifier]
        stages.append({'id': identifier, 'depends_on': sorted(dependencies),
                       'artifact_kind': kind, 'required_fields': list(fields),
                       'required_checks': list(checks), 'requirements': requirements})

    add('requirements', [])
    add('architecture', ['requirements'])
    implementation = []
    for target, stage in [('database', 'database'), ('api', 'api'), ('backend', 'backend'),
                          ('web', 'frontend'), ('mobile', 'mobile'), ('ai', 'ai')]:
        if target not in targets:
            continue
        dependencies = ['architecture']
        if stage == 'api' and 'database' in targets:
            dependencies.append('database')
        if stage == 'backend':
            dependencies += sorted(targets & {'api', 'database'})
        if stage in {'frontend', 'mobile'} and 'api' in targets:
            dependencies.append('api')
        if stage == 'ai' and 'backend' in targets:
            dependencies.append('backend')
        add(stage, dependencies)
        implementation.append(stage)
    add('testing', implementation)
    add('security', ['testing'])
    add('documentation', ['architecture', 'testing'])
    add('release', ['security', 'documentation'])
    result = {'schema_version': 1, 'request': request, 'request_sha256': sha(request),
              'stages': stages, 'provider_calls': 0, 'deployment_authorized': False,
              'boundary': 'Local artifact verification; evaluator assertions require independent trust.'}
    result['plan_sha256'] = sha(result)
    return result


def _plan(plan):
    if not isinstance(plan, dict) or 'request' not in plan or plan != plan_factory(plan['request']):
        raise FactoryError('Changed or malformed plan')
    return plan


def _read_artifact(root, relative, expected):
    _digest(expected)
    if not isinstance(relative, str) or not relative or len(relative) > 256 or '\\' in relative:
        raise FactoryError('Invalid artifact path')
    parts = pathlib.PurePosixPath(relative).parts
    if pathlib.PurePosixPath(relative).is_absolute() or any(part in {'.', '..', '.git'} for part in parts):
        raise FactoryError('Unsafe artifact path')
    if relative != pathlib.PurePosixPath(relative).as_posix():
        raise FactoryError('Noncanonical artifact path')
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise FactoryError('Symlink artifact refused')
    try:
        directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                         dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARTIFACT_BYTES:
                raise FactoryError('Artifact must be a bounded regular file')
            raw = stream.read(MAX_ARTIFACT_BYTES + 1)
        if not raw or len(raw) > MAX_ARTIFACT_BYTES or hashlib.sha256(raw).hexdigest() != expected:
            raise FactoryError('Artifact bytes missing, oversized or changed')
        value = load_json(raw)
    except (OSError, UnicodeError, ValueError) as error:
        raise FactoryError('Artifact read or integrity check failed') from error
    if not isinstance(value, dict):
        raise FactoryError('Artifact must be a JSON object')
    return value


def _validate_receipt(plan, stage, receipt, root, completed):
    _exact(receipt, {'schema_version', 'project', 'source_revision', 'plan_sha256',
                     'stage', 'dependencies', 'artifact', 'checks', 'reviewer'}, 'receipt')
    request = plan['request']
    if type(receipt['schema_version']) is not int or receipt['schema_version'] != 1:
        raise FactoryError('Invalid receipt version')
    if any(receipt[key] != request[key] for key in ['project', 'source_revision']):
        raise FactoryError('Receipt project/source mismatch')
    if receipt['plan_sha256'] != plan['plan_sha256'] or receipt['stage'] != stage['id']:
        raise FactoryError('Receipt plan/stage mismatch')
    _identifier(receipt['reviewer'])
    expected_dependencies = {key: completed[key]['receipt_sha256'] for key in stage['depends_on']}
    if receipt['dependencies'] != expected_dependencies:
        raise FactoryError('Missing or stale dependency receipts')
    artifact = receipt['artifact']
    _exact(artifact, {'path', 'sha256'}, 'artifact reference')
    document = _read_artifact(root, artifact['path'], artifact['sha256'])
    fields = {'schema_version', 'project', 'source_revision', 'kind', 'traces', 'content'}
    _exact(document, fields, 'artifact document')
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise FactoryError('Invalid artifact version')
    if document['kind'] != stage['artifact_kind'] or any(document[key] != request[key] for key in ['project', 'source_revision']):
        raise FactoryError('Artifact project/source/kind mismatch')
    traces = document['traces']
    expected_traces = {row['id']: row['acceptance'] for row in request['requirements']}
    if traces != expected_traces:
        raise FactoryError('Incomplete requirement acceptance trace')
    content = document['content']
    if not isinstance(content, dict) or not set(stage['required_fields']) <= set(content):
        raise FactoryError('Missing stage-specific artifact fields')
    # Reject empty deliverables. Deeper domain checks belong to the evaluator.
    if any(content[key] is None or content[key] == '' or content[key] == [] or content[key] == {}
           or isinstance(content[key], bool) for key in stage['required_fields']):
        raise FactoryError('Empty stage deliverable')
    checks = _list(receipt['checks'], 'checks', 50)
    seen = set()
    for check in checks:
        _exact(check, {'id', 'status', 'evidence'}, 'check')
        _identifier(check['id'])
        if check['id'] in seen:
            raise FactoryError('Duplicate check')
        seen.add(check['id'])
        _exact(check['evidence'], {'path', 'sha256'}, 'check evidence')
        proof = _read_artifact(root, check['evidence']['path'], check['evidence']['sha256'])
        _exact(proof, {'schema_version', 'project', 'source_revision', 'plan_sha256', 'stage',
                       'check', 'status', 'artifact_sha256', 'acceptance'}, 'check report')
        if type(proof['schema_version']) is not int or proof['schema_version'] != 1:
            raise FactoryError('Invalid check version')
        expected = {'project': request['project'], 'source_revision': request['source_revision'],
                    'plan_sha256': plan['plan_sha256'], 'stage': stage['id'], 'check': check['id'],
                    'status': 'passed', 'artifact_sha256': artifact['sha256'], 'acceptance': expected_traces}
        if check['status'] != 'passed' or any(proof[key] != value for key, value in expected.items()):
            raise FactoryError('Check is failing or lacks source/artifact/acceptance binding')
    if not set(stage['required_checks']) <= seen:
        raise FactoryError('Missing mandatory checks')
    return {'id': stage['id'], 'status': 'verified', 'artifact_sha256': artifact['sha256'],
            'receipt_sha256': sha(receipt), 'checks': sorted(seen)}


def evaluate_factory(plan, receipts, *, artifact_root):
    """Revalidate the complete graph; failed predecessors block dependent stages.

    A structurally valid receipt with invalid evidence produces a blocked result.
    Malformed workflow identity or duplicate/unknown stages raises FactoryError.
    All existing receipts are revalidated on each invocation, so changing any
    referenced artifact withdraws downstream verification. No file is written.
    """
    plan = _plan(plan)
    receipts = _list(receipts, 'receipts', MAX_RECEIPTS, nonempty=False)
    root = pathlib.Path(artifact_root).absolute()
    if any(path.is_symlink() for path in [root, *root.parents]) or not root.is_dir():
        raise FactoryError('Artifact root must be an existing directory without symlinks')
    known = {stage['id'] for stage in plan['stages']}
    by_stage = {}
    for receipt in receipts:
        if not isinstance(receipt, dict) or not isinstance(receipt.get('stage'), str) or receipt['stage'] not in known or receipt['stage'] in by_stage:
            raise FactoryError('Duplicate or unknown receipt stage')
        by_stage[receipt['stage']] = receipt
    completed, results = {}, []
    for stage in plan['stages']:
        missing = [key for key in stage['depends_on'] if key not in completed]
        result = {'id': stage['id'], 'status': 'blocked', 'reason': 'dependencies_unverified', 'dependencies': missing}
        if not missing:
            if stage['id'] not in by_stage:
                result = {'id': stage['id'], 'status': 'ready', 'reason': 'artifact_and_checks_required'}
            else:
                try:
                    result = _validate_receipt(plan, stage, by_stage[stage['id']], root, completed)
                    completed[stage['id']] = result
                except (ValueError, KeyError, TypeError) as error:
                    result = {'id': stage['id'], 'status': 'blocked', 'reason': str(error)}
        results.append(result)
    return {'schema_version': 1, 'project': plan['request']['project'], 'plan_sha256': plan['plan_sha256'],
            'stages': results, 'ready': [row['id'] for row in results if row['status'] == 'ready'],
            'verified_count': len(completed), 'delivery_review_ready': len(completed) == len(plan['stages']),
            'deployment_authorized': False, 'provider_calls': 0,
            'evidence_boundary': 'Hashes verify referenced bytes; evaluator identity and real execution are external trust gates.'}


def validate_stage(plan, stage_id, receipts, *, artifact_root):
    """Return one stage after revalidating its complete predecessor chain."""
    _identifier(stage_id)
    result = evaluate_factory(plan, receipts, artifact_root=artifact_root)
    for stage in result['stages']:
        if stage['id'] == stage_id:
            return stage
    raise FactoryError('Unknown stage')
