"""Offline engineering planning over declared constraints and evaluator receipts.

This module ranks supplied alternatives and computes dependency schedules; it does
not invent architecture, infer causality from logs, call models or execute tasks.
Receipt identities are caller assertions: a trusted evaluator must supply them.
SPDX-License-Identifier: MIT
"""

import copy
import math
import re
import time

from .orchestration import DIGEST, SLUG, _text, canonical, sha

MAX_AGE = 86400


class ReasoningError(ValueError):
    """Invalid or ambiguous planning metadata."""


def _shape(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ReasoningError("Missing or unknown fields")
    return value


def _id(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ReasoningError("Invalid identifier")
    return _text(value, 80)


def _digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ReasoningError("Invalid SHA256")
    return value


def _number(value, low=0, high=10**9, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value) or integer and type(value) is not int:
        raise ReasoningError("Invalid bounded finite number")
    return value


def _rows(value, maximum=128, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ReasoningError("Invalid bounded list")
    return value


def _ids(value):
    values = [_id(item) for item in _rows(value)]
    if len(set(values)) != len(values):
        raise ReasoningError("Duplicate identifier")
    return values


def _indexed(rows, fields, maximum=128):
    result = {}
    for row in _rows(rows, maximum):
        _shape(row, fields)
        key = _id(row['id'])
        if key in result:
            raise ReasoningError("Duplicate identity")
        result[key] = copy.deepcopy(row)
    return result


def _fresh(at, now):
    _number(at, high=10**12)
    return 0 <= now - at <= MAX_AGE


def _waves(nodes, edges, parallel):
    pending = set(nodes)
    complete = set()
    waves = []
    while pending:
        ready = sorted(key for key in pending if edges[key] <= complete)[:parallel]
        if not ready:
            raise ReasoningError("Dependency or hierarchy cycle")
        waves.append(ready)
        pending.difference_update(ready)
        complete.update(ready)
    return waves


def plan(request, *, now=None):
    """Return a deterministic provisional plan; all candidates are caller supplied.

    ``max_minutes`` bounds the conservative wave schedule's elapsed duration.
    ``cost_units`` are arbitrary planning units, never currency or token billing.
    Evidence is structurally checked and source/project/time bound, not signed.
    """
    _shape(request, {'schema_version', 'project', 'task', 'source_sha256', 'nodes',
                     'constraints', 'alternatives', 'evidence'})
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ReasoningError("Unknown schema")
    _id(request['project'])
    _id(request['task'])
    _digest(request['source_sha256'])
    now = _number(time.time() if now is None else now, high=10**12)
    constraints = _shape(request['constraints'], {'max_minutes', 'max_parallel', 'max_depth',
                         'max_cost_units', 'max_latency_ms', 'min_quality', 'required_checks'})
    _number(constraints['max_minutes'], 1, integer=True)
    _number(constraints['max_parallel'], 1, 128, integer=True)
    _number(constraints['max_depth'], 1, 5, integer=True)
    for name in ['max_cost_units', 'max_latency_ms']:
        _number(constraints[name])
    _number(constraints['min_quality'], 0, 1)
    checks = sorted(_ids(constraints['required_checks']))
    if not checks:
        raise ReasoningError("At least one verification check required")
    nodes = _indexed(request['nodes'], {'id', 'parent', 'depends_on', 'minutes', 'risk', 'novelty', 'confidence'})
    if not nodes:
        raise ReasoningError("At least one task node required")
    edges = {}
    for key, node in nodes.items():
        dependencies = set(_ids(node['depends_on']))
        if node['parent'] is not None:
            dependencies.add(_id(node['parent']))
        if not dependencies <= nodes.keys() or key in dependencies:
            raise ReasoningError("Unknown or self dependency")
        edges[key] = dependencies
        _number(node['minutes'], 1, 100000, integer=True)
        for name in ['risk', 'novelty', 'confidence']:
            _number(node[name], 0, 1)
    waves = _waves(nodes, edges, constraints['max_parallel'])
    elapsed = sum(max(nodes[key]['minutes'] for key in wave) for wave in waves)
    hierarchy = {}
    for wave in waves:
        for key in wave:
            hierarchy[key] = 1 if nodes[key]['parent'] is None else hierarchy[nodes[key]['parent']] + 1
    uncertainty = [key for key in sorted(nodes) if nodes[key]['confidence'] < .8]
    complexity_score = (len(nodes) / 8 + sum(len(e) for e in edges.values()) / 8
                        + max(n['risk'] for n in nodes.values()) * 1.5
                        + max(n['novelty'] for n in nodes.values())
                        + max(1 - n['confidence'] for n in nodes.values())
                        + (max(hierarchy.values()) - 1) / 2)
    complexity = min(5, max(1, math.ceil(complexity_score)))
    depth = min(complexity, constraints['max_depth'])
    evidence = _indexed(request['evidence'], {'id', 'project', 'source_sha256', 'at', 'kind', 'sha256', 'confidence'}, 256)
    evidence_rejected = {}
    for key, row in evidence.items():
        _id(row['project'])
        _id(row['kind'])
        _digest(row['source_sha256'])
        _digest(row['sha256'])
        _number(row['confidence'], 0, 1)
        reasons = []
        if row['project'] != request['project']:
            reasons.append('project_mismatch')
        if row['source_sha256'] != request['source_sha256']:
            reasons.append('source_mismatch')
        if not _fresh(row['at'], now):
            reasons.append('stale_or_future')
        if reasons:
            evidence_rejected[key] = reasons
    alternatives = _indexed(request['alternatives'], {'id', 'cost_units', 'latency_ms', 'quality', 'evidence_ids'})
    if not alternatives:
        raise ReasoningError("At least one architecture alternative required")
    ranked = []
    for key, alternative in sorted(alternatives.items()):
        _number(alternative['cost_units'])
        _number(alternative['latency_ms'])
        _number(alternative['quality'], 0, 1)
        cited = _ids(alternative['evidence_ids'])
        if not set(cited) <= evidence.keys():
            raise ReasoningError("Unknown evidence reference")
        reasons = []
        if not cited or any(item in evidence_rejected for item in cited):
            reasons.append('missing_valid_evidence')
        confidence = min((evidence[item]['confidence'] for item in cited), default=0)
        quality = alternative['quality'] * confidence
        if alternative['cost_units'] > constraints['max_cost_units']:
            reasons.append('cost_units_budget')
        if alternative['latency_ms'] > constraints['max_latency_ms']:
            reasons.append('latency_budget')
        if quality < constraints['min_quality']:
            reasons.append('evidence_adjusted_quality_floor')
        score = round(quality * .7 + .15 / (1 + alternative['cost_units']) + .15 / (1 + alternative['latency_ms']), 12)
        ranked.append({'id': key, 'score': score, 'confidence': confidence,
                       'evidence_adjusted_quality': quality, 'rejected': reasons})
    ranked.sort(key=lambda row: (-row['score'], row['id']))
    eligible = [row for row in ranked if not row['rejected']]
    blockers = []
    if elapsed > constraints['max_minutes']:
        blockers.append('elapsed_minutes_budget')
    if depth < complexity:
        blockers.append('reasoning_depth_budget')
    if not eligible:
        blockers.append('no_evidenced_feasible_alternative')
    selected = eligible[0]['id'] if eligible and not blockers else None
    selected_score = next((row['score'] for row in ranked if row['id'] == selected), None)
    result = {'schema_version': 1, 'project': request['project'], 'task': request['task'],
              'source_sha256': request['source_sha256'], 'request_sha256': sha(request),
              'request': copy.deepcopy(request),
              'planned_at': now, 'status': 'blocked' if blockers else 'provisional',
              'selected': selected, 'blockers': blockers, 'complexity': complexity,
              'reasoning_depth': depth, 'strategy': ['direct', 'decompose', 'compare', 'adversarial-review', 'staged-validation'][complexity - 1],
              'hierarchy_levels': {key: hierarchy[key] for key in sorted(hierarchy)},
              'waves': waves, 'elapsed_minutes': elapsed,
              'dependency_edges': {key: sorted(edges[key]) for key in sorted(edges)},
              'uncertain_nodes': uncertainty, 'evidence_rejected': evidence_rejected,
              'alternatives': ranked,
              'counterfactuals': [{'alternative': row['id'], 'score_delta': None if selected_score is None else round(row['score'] - selected_score, 12),
                                  'constraints_to_resolve': row['rejected']} for row in ranked if row['id'] != selected],
              'review_requirements': {'distinct_models': 2, 'required_checks': checks},
              'provider_calls': 0, 'executed_tasks': 0,
              'limits': 'Declared estimates and evaluator assertions; no live model, execution, causal or billing proof.'}
    result['plan_sha256'] = sha(result)
    return result


def review_decision(planned, reviews, verification, *, now=None):
    """Validate independent model review and deterministic verification attestations.

    This gate checks metadata, freshness and digests. It does not authenticate a
    reviewer, execute a check or establish that a supplied receipt is truthful.
    """
    if not isinstance(planned, dict) or not isinstance(planned.get('plan_sha256'), str):
        raise ReasoningError("Plan receipt required")
    if sha({key: value for key, value in planned.items() if key != 'plan_sha256'}) != planned['plan_sha256']:
        raise ReasoningError("Changed plan")
    if not {'request', 'planned_at'} <= planned.keys():
        raise ReasoningError("Original request and planning time required")
    expected = plan(planned['request'], now=planned['planned_at'])
    if expected != planned:
        raise ReasoningError("Plan differs from deterministic request recomputation")
    now = _number(time.time() if now is None else now, high=10**12)
    blockers = list(planned['blockers'])
    if planned['status'] != 'provisional' or planned['selected'] is None:
        blockers.append('plan_not_provisional')
    if not _fresh(planned['planned_at'], now):
        blockers.append('plan_expired')
    models, reviewers = set(), set()
    for row in _rows(reviews, maximum=20):
        _shape(row, {'reviewer', 'model', 'revision', 'decision', 'plan_sha256', 'source_sha256', 'evidence_sha256', 'at'})
        reviewer = _id(row['reviewer'])
        model = _id(row['model'])
        if not isinstance(row['revision'], str) or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', row['revision']):
            raise ReasoningError("Pinned model revision required")
        for field in ['plan_sha256', 'source_sha256', 'evidence_sha256']:
            _digest(row[field])
        if row['decision'] not in {'approved', 'rejected'}:
            raise ReasoningError("Invalid review decision")
        if reviewer in reviewers or model in models:
            raise ReasoningError("Independent reviewer and model identities required")
        reviewers.add(reviewer)
        models.add(model)
        if row['decision'] != 'approved':
            blockers.append('model_review_rejected')
        if row['plan_sha256'] != planned['plan_sha256'] or row['source_sha256'] != planned['source_sha256'] or not _fresh(row['at'], now) or row['at'] < planned['planned_at']:
            blockers.append('review_not_bound_or_fresh')
    if len(models) < planned['review_requirements']['distinct_models']:
        blockers.append('insufficient_distinct_model_reviews')
    verified = set()
    for row in _rows(verification, maximum=128):
        _shape(row, {'id', 'status', 'source_sha256', 'plan_sha256', 'at', 'sha256'})
        key = _id(row['id'])
        if key in verified:
            raise ReasoningError("Duplicate verification check")
        verified.add(key)
        _digest(row['source_sha256'])
        _digest(row['plan_sha256'])
        _digest(row['sha256'])
        if row['status'] not in {'passed', 'failed'}:
            raise ReasoningError("Invalid verification status")
        if row['status'] != 'passed' or row['plan_sha256'] != planned['plan_sha256'] or row['source_sha256'] != planned['source_sha256'] or not _fresh(row['at'], now) or row['at'] < planned['planned_at']:
            blockers.append('verification_failed_or_unbound')
    if not set(planned['review_requirements']['required_checks']) <= verified:
        blockers.append('missing_required_verification')
    return {'decision': 'blocked' if blockers else 'accepted', 'blockers': sorted(set(blockers)),
            'plan_sha256': planned['plan_sha256'], 'source_sha256': planned['source_sha256'],
            'reviewed_models': sorted(models), 'verified_checks': sorted(verified),
            'provider_calls': 0, 'tasks_executed': 0,
            'limits': 'Acceptance validates supplied attestations; it grants no execution or production authority.'}


def root_causes(observations, dependencies):
    """Find earliest observed failures along an explicit causal dependency DAG.

    A root is a failed node without a failed ancestor, not a proven real-world
    cause. Missing observations and declared hypotheses remain uncertainty.
    """
    if not isinstance(dependencies, dict) or not 1 <= len(dependencies) <= 128:
        raise ReasoningError("Bounded dependency mapping required")
    edges = {_id(key): set(_ids(value)) for key, value in dependencies.items()}
    if any(not value <= edges.keys() or key in value for key, value in edges.items()):
        raise ReasoningError("Unknown or self dependency")
    waves = _waves(edges, edges, 128)
    states = {}
    for row in _rows(observations):
        _shape(row, {'id', 'status', 'evidence_sha256'})
        key = _id(row['id'])
        if key not in edges or key in states or row['status'] not in {'passed', 'failed', 'unknown'}:
            raise ReasoningError("Invalid observation")
        _digest(row['evidence_sha256'])
        states[key] = row['status']
    ancestors = {}
    for wave in waves:
        for key in wave:
            ancestors[key] = set(edges[key])
            for parent in edges[key]:
                ancestors[key].update(ancestors[parent])
    failed = {key for key, value in states.items() if value == 'failed'}
    roots = sorted(key for key in failed if not ancestors[key] & failed)
    unknown = sorted(key for key in edges if states.get(key, 'unknown') == 'unknown')
    return {'candidate_roots': roots,
            'affected': {key: sorted(node for node in edges if key in ancestors[node]) for key in roots},
            'uncertain_nodes': unknown, 'causality_proven': False,
            'method': 'Observed failures traced through caller-declared dependency edges.'}
