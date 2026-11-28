"""Offline engineering planning over declared constraints and evaluator receipts.

This module ranks supplied alternatives and computes dependency schedules; it does
not invent architecture, infer causality from logs, call models or execute tasks.
Receipt identities are caller assertions: a trusted evaluator must supply them.

Layer L13 (Advanced Engineering Reasoning) extends the planner with adaptive
strategy selection, goal decomposition, constraint and dependency analysis,
evidence-weighted root-cause ranking, counterfactuals, uncertainty detection,
multi-perspective review, decision validation, trade-off sensitivity and a
model-routing hook. Every output carries ``"mode": "deterministic"`` and an
input/output SHA-256 receipt; see docs/specs/gaie-20-layers/REASONING.md.
SPDX-License-Identifier: MIT
"""

import copy
import math
import re
import time

from .orchestration import DIGEST, SECRET, SLUG, CoordinationError, _text, canonical, sha

MAX_AGE = 86400
ENGINE = 'reasoning'
LAYER = 'L13'
MODE = 'deterministic'
RECEIPT_FIELDS = frozenset({'engine', 'layer', 'operation', 'mode', 'input_sha256', 'output_sha256'})


class ReasoningError(ValueError):
    """Invalid or ambiguous planning metadata."""


def _shape(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ReasoningError("Missing or unknown fields")
    return value


def _id(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ReasoningError("Invalid identifier")
    try:
        return _text(value, 80)
    except CoordinationError:
        raise ReasoningError("Credential-shaped identifier refused") from None


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
    result = _seal('plan', request, result)
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
    selected = next((row for row in planned['request']['alternatives']
                     if row['id'] == planned['selected']), None)
    if selected is not None:
        cited = set(selected['evidence_ids'])
        if any(not _fresh(row['at'], now) for row in planned['request']['evidence']
               if row['id'] in cited):
            blockers.append('planning_evidence_expired')
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
    body = {'decision': 'blocked' if blockers else 'accepted', 'blockers': sorted(set(blockers)),
            'plan_sha256': planned['plan_sha256'], 'source_sha256': planned['source_sha256'],
            'reviewed_models': sorted(models), 'verified_checks': sorted(verified),
            'provider_calls': 0, 'tasks_executed': 0, 'evaluated_at': now,
            'limits': 'Acceptance validates supplied attestations; it grants no execution or production authority.'}
    return _seal('review', {'plan': planned, 'reviews': reviews, 'verification': verification}, body)


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
    body = {'candidate_roots': roots,
            'affected': {key: sorted(node for node in edges if key in ancestors[node]) for key in roots},
            'uncertain_nodes': unknown, 'causality_proven': False,
            'method': 'Observed failures traced through caller-declared dependency edges.'}
    return _seal('root-causes', {'observations': observations, 'dependencies': dependencies}, body)


# ---------------------------------------------------------------------------
# Layer L13 - advanced engineering reasoning.
#
# Every function below is a pure function of its payload (and, where noted, of an
# explicit clock): the same payload and clock always give the same output, and the
# output is sealed with "mode": "deterministic" plus an input/output receipt.
# No model, tool, network or file is used. Nothing here proves real-world causality,
# performance or cost; it reasons only over the facts and evidence it is given.
# ---------------------------------------------------------------------------

def _hash(value):
    try:
        return sha(value)
    except (TypeError, ValueError):
        raise ReasoningError("Input or output is not canonical JSON") from None


def _seal(operation, payload, body):
    """Attach mode and an input/output SHA-256 receipt (output hash excludes the receipt)."""
    output = dict(body, mode=MODE, operation=operation, provider_calls=0)
    output['receipt'] = {'engine': ENGINE, 'layer': LAYER, 'operation': operation, 'mode': MODE,
                         'input_sha256': _hash(payload), 'output_sha256': _hash(output)}
    return output


def verify_receipt(output, payload):
    """Check that ``output`` is a sealed deterministic result for exactly ``payload``.

    Hash consistency only; use ``replay`` to recompute the result itself.
    """
    if not isinstance(output, dict) or output.get('mode') != MODE or not isinstance(output.get('receipt'), dict):
        raise ReasoningError("Deterministic receipt required")
    receipt = output['receipt']
    if set(receipt) != RECEIPT_FIELDS or receipt['mode'] != MODE or receipt['engine'] != ENGINE \
            or receipt['layer'] != LAYER or receipt['operation'] != output.get('operation'):
        raise ReasoningError("Malformed receipt")
    # plan() adds its own plan_sha256 after sealing; other outputs may cite a reviewed plan's digest
    own_digest = ('plan_sha256',) if output.get('operation') == 'plan' else ()
    body = {key: value for key, value in output.items() if key != 'receipt' and key not in own_digest}
    if receipt['input_sha256'] != _hash(payload):
        raise ReasoningError("Receipt is bound to a different input")
    if receipt['output_sha256'] != _hash(body):
        raise ReasoningError("Output changed after sealing")
    if own_digest and output.get('plan_sha256') != _hash(
            {key: value for key, value in output.items() if key != 'plan_sha256'}):
        raise ReasoningError("Plan digest does not match")
    return True


def _schema(request, fields):
    _shape(request, fields)
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ReasoningError("Unknown schema")
    return request


def _r(value):
    return round(value, 9) + 0.0


def _flag(value):
    if type(value) is not bool:
        raise ReasoningError("Boolean required")
    return value


def _choice(value, allowed, what):
    if not isinstance(value, str) or value not in allowed:
        raise ReasoningError(f"Unknown {what}")
    return value


def _unique(*groups):
    seen = set()
    for group in groups:
        for key in group:
            if key in seen:
                raise ReasoningError("Duplicate identity across sections")
            seen.add(key)


def _mapping(value, check, maximum=64, minimum=0):
    if not isinstance(value, dict) or not minimum <= len(value) <= maximum:
        raise ReasoningError("Invalid bounded mapping")
    return {_id(key): check(item) for key, item in value.items()}


def _scalar(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _number(value, -10**12, 10**12)
    if isinstance(value, str):
        return _id(value)
    raise ReasoningError("Values must be booleans, finite numbers or identifiers")


def _kind(value):
    return 'bool' if isinstance(value, bool) else 'text' if isinstance(value, str) else 'number'


ORDERING = frozenset({'<', '<=', '>', '>='})
COMPARISONS = ORDERING | {'==', '!=', 'in', 'not_in'}


def _operand(op, value):
    _choice(op, COMPARISONS, "comparison operator")
    if op in ('in', 'not_in'):
        values = [_scalar(item) for item in _rows(value, 32, 1)]
        if len({_kind(item) for item in values}) != 1 or len({canonical(item) for item in values}) != len(values):
            raise ReasoningError("Membership lists need unique values of one type")
        return values
    value = _scalar(value)
    if op in ORDERING and _kind(value) != 'number':
        raise ReasoningError("Ordering comparison needs a number")
    return value


def _holds(actual, op, expected):
    if _kind(actual) != _kind(expected[0] if op in ('in', 'not_in') else expected):
        raise ReasoningError("Type mismatch in comparison")
    if op == '<':
        return actual < expected
    if op == '<=':
        return actual <= expected
    if op == '>':
        return actual > expected
    if op == '>=':
        return actual >= expected
    if op == '==':
        return actual == expected
    if op == '!=':
        return actual != expected
    return (actual in expected) == (op == 'in')


def _cycle(edges):
    """Return one dependency cycle as a node list (a -> b means a depends on b), or None."""
    state, stack = {}, []

    def visit(node):
        state[node] = 1
        stack.append(node)
        for dependency in sorted(edges[node]):
            if state.get(dependency) == 1:
                return stack[stack.index(dependency):] + [dependency]
            if dependency not in state:
                found = visit(dependency)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in sorted(edges):
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def _acyclic(edges, label):
    found = _cycle(edges)
    if found:
        raise ReasoningError(f"Dependency cycle among {label}s: {' -> '.join(found)}")


def _ancestors(edges):
    ancestors = {}
    for wave in _waves(edges, edges, len(edges) or 1):
        for key in wave:
            ancestors[key] = set(edges[key])
            for parent in edges[key]:
                ancestors[key].update(ancestors[parent])
    return ancestors


# -- strategy selection with adaptive depth ----------------------------------

DEPTHS = ('quick', 'standard', 'deep')
STRATEGY_WEIGHTS = (('risk', .30), ('complexity', .20), ('novelty', .15),
                    ('irreversibility', .20), ('evidence_gap', .15))
DEPTH_THRESHOLDS = (('deep', .60), ('standard', .30))
DEPTH_PROFILES = {
    'quick': {'plan_max_depth': 2, 'actions': ['constraints', 'validate-decision'], 'model_steps': []},
    'standard': {'plan_max_depth': 3,
                 'actions': ['decompose', 'constraints', 'dependencies', 'trade-off', 'uncertainty',
                             'validate-decision'], 'model_steps': []},
    'deep': {'plan_max_depth': 5,
             'actions': ['decompose', 'constraints', 'dependencies', 'trade-off', 'uncertainty',
                         'counterfactual', 'perspectives', 'validate-decision'],
             'model_steps': ['independent-review']},
}


def select_strategy(request):
    """Choose quick / standard / deep reasoning from declared task properties.

    All inputs are 0..1. ``reversibility`` 1 means trivially undone;
    ``evidence_coverage`` is the share of critical claims with fresh evidence
    (``detect_uncertainty`` computes it). Hard triggers can only raise depth.
    """
    _schema(request, {'schema_version', 'task', 'risk', 'complexity', 'novelty',
                      'reversibility', 'evidence_coverage'})
    task = _id(request['task'])
    value = {name: _number(request[name], 0, 1) for name in
             ('risk', 'complexity', 'novelty', 'reversibility', 'evidence_coverage')}
    factors = {'risk': value['risk'], 'complexity': value['complexity'], 'novelty': value['novelty'],
               'irreversibility': 1 - value['reversibility'], 'evidence_gap': 1 - value['evidence_coverage']}
    contributions = {name: _r(weight * factors[name]) for name, weight in STRATEGY_WEIGHTS}
    score = _r(sum(contributions.values()))
    by_score = next((depth for depth, low in DEPTH_THRESHOLDS if score >= low), 'quick')
    triggers = []
    if value['risk'] >= .8:
        triggers.append({'id': 'high_risk', 'minimum': 'deep', 'detail': f"risk {value['risk']:.2f} >= 0.80"})
    if value['reversibility'] <= .2 and value['risk'] >= .5:
        triggers.append({'id': 'irreversible_and_risky', 'minimum': 'deep',
                         'detail': f"reversibility {value['reversibility']:.2f} <= 0.20 with risk {value['risk']:.2f} >= 0.50"})
    if value['evidence_coverage'] <= .5:
        triggers.append({'id': 'weak_evidence', 'minimum': 'deep' if value['risk'] >= .5 else 'standard',
                         'detail': f"evidence coverage {value['evidence_coverage']:.2f} <= 0.50"})
    if value['novelty'] >= .8:
        triggers.append({'id': 'novel_problem', 'minimum': 'standard',
                         'detail': f"novelty {value['novelty']:.2f} >= 0.80"})
    depth = max([by_score] + [row['minimum'] for row in triggers], key=DEPTHS.index)
    leaders = sorted(contributions.items(), key=lambda row: (-row[1], row[0]))[:2]
    reason = f"{depth}: weighted score {score:.3f} selects {by_score}"
    escalations = [row for row in triggers if DEPTHS.index(row['minimum']) > DEPTHS.index(by_score)]
    if escalations:
        reason += '; escalated by ' + ', '.join(f"{row['id']} ({row['detail']})" for row in escalations)
    reason += '; largest contributors: ' + ', '.join(f"{name} {amount:.3f}" for name, amount in leaders)
    body = {'task': task, 'depth': depth, 'score': score, 'score_depth': by_score,
            'thresholds': {name: low for name, low in DEPTH_THRESHOLDS},
            'factors': {name: {'value': _r(factors[name]), 'weight': weight, 'contribution': contributions[name]}
                        for name, weight in STRATEGY_WEIGHTS},
            'triggers': triggers, 'reason': reason, **copy.deepcopy(DEPTH_PROFILES[depth])}
    return _seal('strategy', request, body)


# -- hierarchical decomposition feeding the wave planner ---------------------

def decompose(request):
    """Expand goal -> milestones -> tasks into ``plan()`` nodes.

    A milestone dependency means every task of the dependent milestone waits for
    the prerequisite milestone's exit tasks (tasks nothing else in it depends on).
    """
    _schema(request, {'schema_version', 'goal', 'milestones'})
    goal = _id(request['goal'])
    milestones = _indexed(request['milestones'], {'id', 'depends_on', 'tasks'}, 32)
    if not milestones:
        raise ReasoningError("At least one milestone required")
    tasks, owner = {}, {}
    for key, milestone in milestones.items():
        rows = _indexed(milestone['tasks'], {'id', 'depends_on', 'minutes', 'risk', 'novelty', 'confidence'})
        if not rows:
            raise ReasoningError("Milestone without tasks cannot be scheduled")
        for task_id, task in rows.items():
            if task_id in tasks:
                raise ReasoningError("Duplicate identity across sections")
            _number(task['minutes'], 1, 100000, integer=True)
            for name in ('risk', 'novelty', 'confidence'):
                _number(task[name], 0, 1)
            tasks[task_id], owner[task_id] = task, key
    if len(tasks) > 128:
        raise ReasoningError("At most 128 tasks per goal")
    _unique([goal], milestones, tasks)
    milestone_edges = {}
    for key, milestone in milestones.items():
        dependencies = set(_ids(milestone['depends_on']))
        if not dependencies <= milestones.keys() or key in dependencies:
            raise ReasoningError("Unknown or self milestone dependency")
        milestone_edges[key] = dependencies
    _acyclic(milestone_edges, 'milestone')
    task_edges = {}
    for key, task in tasks.items():
        dependencies = set(_ids(task['depends_on']))
        if not dependencies <= tasks.keys() or key in dependencies:
            raise ReasoningError("Unknown or self task dependency")
        task_edges[key] = dependencies
    exits = {key: sorted(task for task in tasks if owner[task] == key and not any(
        task in task_edges[other] for other in tasks if owner[other] == key)) for key in milestones}
    flat = {key: task_edges[key] | {item for prerequisite in milestone_edges[owner[key]] for item in exits[prerequisite]}
            for key in tasks}
    _acyclic(flat, 'task')
    order = [key for wave in _waves(flat, flat, 128) for key in wave]
    nodes = [{'id': key, 'parent': None, 'depends_on': sorted(flat[key]), 'minutes': tasks[key]['minutes'],
              'risk': tasks[key]['risk'], 'novelty': tasks[key]['novelty'], 'confidence': tasks[key]['confidence']}
             for key in order]
    summary = [{'id': key, 'level': 1, 'depends_on': sorted(milestone_edges[key]),
                'tasks': [task for task in order if owner[task] == key], 'exit_tasks': exits[key],
                'minutes': sum(tasks[task]['minutes'] for task in tasks if owner[task] == key),
                'max_risk': max(tasks[task]['risk'] for task in tasks if owner[task] == key),
                'min_confidence': min(tasks[task]['confidence'] for task in tasks if owner[task] == key)}
               for key in [item for wave in _waves(milestone_edges, milestone_edges, 32) for item in wave]]
    body = {'goal': goal, 'levels': {'goal': 0, 'milestone': 1, 'task': 2},
            'milestones': summary, 'milestone_waves': _waves(milestone_edges, milestone_edges, 32),
            'milestone_of': {key: owner[key] for key in sorted(owner)},
            'plan_nodes': nodes, 'task_count': len(tasks),
            'total_minutes': sum(task['minutes'] for task in tasks.values())}
    return _seal('decompose', request, body)


def plan_goal(request, *, now=None):
    """Decompose a goal and schedule its tasks with the existing wave planner."""
    _schema(request, {'schema_version', 'decomposition', 'plan'})
    decomposition = decompose(request['decomposition'])
    base = request['plan']
    if not isinstance(base, dict) or 'nodes' in base:
        raise ReasoningError("Plan base must omit nodes; they come from the decomposition")
    planned = plan(dict(copy.deepcopy(base), nodes=copy.deepcopy(decomposition['plan_nodes'])), now=now)
    dependencies = analyze_dependencies({'schema_version': 1, 'items': [
        {'id': node['id'], 'depends_on': node['depends_on'], 'minutes': node['minutes'], 'status': 'todo'}
        for node in decomposition['plan_nodes']]})
    owner = decomposition['milestone_of']
    body = {'goal': decomposition['goal'], 'status': planned['status'], 'selected': planned['selected'],
            'blockers': planned['blockers'],
            'waves_by_milestone': [{key: [task for task in wave if owner[task] == key]
                                    for key in sorted({owner[task] for task in wave})} for wave in planned['waves']],
            'critical_path': dependencies['critical_path'],
            'critical_path_minutes': dependencies['critical_path_minutes'],
            'decomposition': decomposition, 'plan': planned, 'dependencies': dependencies,
            'evaluated_at': planned['planned_at']}
    return _seal('plan-goal', request, body)


# -- constraint-based planning and dependency analysis ------------------------

def _attributes(value):
    return _mapping(value, _scalar, 64)


def _constraint_rows(rows, fields, maximum=64):
    result = _indexed(rows, fields, maximum)
    for row in result.values():
        _id(row['attribute'])
        row['value'] = _operand(row['op'], row['value'])
        if 'weight' in fields:
            _number(row['weight'], 0, 1)
            if row['weight'] <= 0:
                raise ReasoningError("Soft constraint weight must be positive")
    return result


def evaluate_constraints(request):
    """Hard constraints must hold; soft constraints are weight-scored.

    An option missing an attribute a constraint needs is ``undetermined`` (never
    silently passed or failed) and listed under ``needs_evidence``.
    """
    _schema(request, {'schema_version', 'decision', 'options', 'hard', 'soft'})
    decision = _id(request['decision'])
    options = _indexed(request['options'], {'id', 'attributes'}, 32)
    if not options:
        raise ReasoningError("At least one option required")
    attributes = {key: _attributes(option['attributes']) for key, option in options.items()}
    hard = _constraint_rows(request['hard'], {'id', 'attribute', 'op', 'value'})
    soft = _constraint_rows(request['soft'], {'id', 'attribute', 'op', 'value', 'weight'})
    if not hard:
        raise ReasoningError("At least one hard constraint required")
    _unique(hard, soft)
    total = sum(row['weight'] for row in soft.values())
    rows = []
    for key in sorted(options):
        values = attributes[key]

        def outcome(row):
            if row['attribute'] not in values:
                return 'unknown'
            return 'pass' if _holds(values[row['attribute']], row['op'], row['value']) else 'fail'
        hard_results = {cid: outcome(row) for cid, row in sorted(hard.items())}
        soft_results = {cid: outcome(row) for cid, row in sorted(soft.items())}
        earned = sum(soft[cid]['weight'] for cid, state in soft_results.items() if state == 'pass')
        unknown = sum(soft[cid]['weight'] for cid, state in soft_results.items() if state == 'unknown')
        violations = [cid for cid, state in hard_results.items() if state == 'fail']
        missing = [cid for cid, state in hard_results.items() if state == 'unknown']
        status = 'infeasible' if violations else 'undetermined' if missing else 'feasible'
        rows.append({'id': key, 'status': status, 'hard': hard_results, 'soft': soft_results,
                     'violations': violations, 'unknown_hard': missing,
                     'unknown_soft': [cid for cid, state in soft_results.items() if state == 'unknown'],
                     'soft_score': _r(earned / total) if total else None,
                     'soft_score_upper_bound': _r((earned + unknown) / total) if total else None})
    feasible = sorted((row for row in rows if row['status'] == 'feasible'),
                      key=lambda row: (-(row['soft_score'] or 0), row['id']))
    selected = feasible[0] if feasible else None
    contenders = [row for row in rows if row['status'] == 'undetermined' and (
        selected is None or (row['soft_score_upper_bound'] or 0) >= (selected['soft_score'] or 0))]
    needs = [{'option': row['id'], 'attributes': sorted({hard[cid]['attribute'] for cid in row['unknown_hard']}
                                                        | {soft[cid]['attribute'] for cid in row['unknown_soft']}),
              'reason': 'undetermined_option_could_change_the_selection'} for row in contenders]
    status = 'blocked' if selected is None else 'provisional' if needs else 'selected'
    body = {'decision': decision, 'status': status, 'selected': selected['id'] if selected else None,
            'ranking': [row['id'] for row in feasible], 'options': rows, 'needs_evidence': needs,
            'reason': ('no option satisfies every hard constraint' if selected is None else
                       f"{selected['id']} satisfies all {len(hard)} hard constraints with soft score "
                       f"{selected['soft_score'] if selected['soft_score'] is not None else 'n/a'}"
                       + ('; undetermined options could still win' if needs else ''))}
    return _seal('constraints', request, body)


ITEM_STATUSES = ('done', 'in_progress', 'todo', 'blocked')


def analyze_dependencies(request):
    """Topological order, critical path over remaining minutes, slack and blocked items."""
    _schema(request, {'schema_version', 'items'})
    items = _indexed(request['items'], {'id', 'depends_on', 'minutes', 'status'}, 256)
    if not items:
        raise ReasoningError("At least one item required")
    edges = {}
    for key, item in items.items():
        dependencies = set(_ids(item['depends_on']))
        if not dependencies <= items.keys() or key in dependencies:
            raise ReasoningError("Unknown or self dependency")
        edges[key] = dependencies
        _number(item['minutes'], 0, 100000, integer=True)
        _choice(item['status'], ITEM_STATUSES, "item status")
    _acyclic(edges, 'item')
    waves = _waves(edges, edges, 256)
    order = [key for wave in waves for key in wave]
    remaining = {key: 0 if items[key]['status'] == 'done' else items[key]['minutes'] for key in items}
    finish, previous = {}, {}
    for key in order:
        start = max((finish[item] for item in edges[key]), default=0)
        previous[key] = min((item for item in edges[key] if finish[item] == start), default=None)
        finish[key] = start + remaining[key]
    total = max(finish.values())
    node = min(key for key in items if finish[key] == total)
    path = []
    while node is not None:
        path.append(node)
        node = previous[node]
    path.reverse()
    dependents = {key: {other for other in items if key in edges[other]} for key in items}
    latest = {}
    for key in reversed(order):
        latest[key] = min((latest[child] - remaining[child] for child in dependents[key]), default=total)
    slack = {key: latest[key] - finish[key] for key in sorted(items)}
    ancestors = _ancestors(edges)
    blocked_roots = {key for key in items if items[key]['status'] == 'blocked'}
    blocked = {key: sorted((ancestors[key] | {key}) & blocked_roots) for key in sorted(items)
               if items[key]['status'] != 'done' and (ancestors[key] | {key}) & blocked_roots}
    ready = [key for key in sorted(items) if items[key]['status'] == 'todo'
             and all(items[item]['status'] == 'done' for item in edges[key])]
    conflicts = [key for key in sorted(items) if items[key]['status'] in ('done', 'in_progress')
                 and any(items[item]['status'] != 'done' for item in edges[key])]
    body = {'order': order, 'waves': waves, 'critical_path': path, 'critical_path_minutes': total,
            'critical_items': [key for key in sorted(items) if slack[key] == 0 and remaining[key] > 0],
            'slack_minutes': slack, 'blocked': blocked, 'ready': ready,
            'in_progress': [key for key in sorted(items) if items[key]['status'] == 'in_progress'],
            'status_conflicts': conflicts, 'remaining_minutes': sum(remaining.values())}
    return _seal('dependencies', request, body)


# -- root-cause analysis with evidence weighting and competing hypotheses -----

LOG_ODDS_SCALE = 3.0
STRUCTURE = {'observed_root': 1.0, 'unobserved_upstream_of_root': .5, 'downstream_of_failure': -1.0,
             'observed_passing': -2.0, 'not_upstream_of_failure': -1.0}
LEADING_SCORE, LEADING_MARGIN = .7, .2


def _log_line(value):
    if not isinstance(value, str) or len(value) > 1000:
        raise ReasoningError("Log lines must be strings up to 1000 characters")
    if SECRET.search(value) or any(ord(char) < 32 and char != '\t' for char in value):
        raise ReasoningError("Credential-shaped or control text in a log; redact it before analysis")
    return value


def _needle(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ReasoningError("Rule text must be 1-120 characters")
    return _log_line(value)


def analyze_root_causes(request):
    """Rank competing root-cause hypotheses by weighted, explainable evidence.

    Score = logistic(logit(prior) + structural term + sum of evidence terms); each
    evidence term is +/- 3 * weight * reliability. Log rules are literal substring
    matches (no regular expressions), counted once per rule. Log text is never echoed.
    Scores are evidence weights for ranking, not calibrated probabilities.
    """
    _schema(request, {'schema_version', 'dependencies', 'observations', 'hypotheses', 'logs', 'rules', 'evidence'})
    structural = root_causes(request['observations'], request['dependencies'])
    edges = {key: set(value) for key, value in request['dependencies'].items()}
    states = {row['id']: row['status'] for row in request['observations']}
    if 'failed' not in states.values():
        raise ReasoningError("Root-cause analysis needs at least one observed failure")
    hypotheses = _indexed(request['hypotheses'], {'id', 'node', 'prior'}, 32)
    if not hypotheses:
        raise ReasoningError("At least one hypothesis required")
    for row in hypotheses.values():
        if _id(row['node']) not in edges:
            raise ReasoningError("Hypothesis names an unknown node")
        _number(row['prior'], .01, .99)
    logs = _indexed(request['logs'], {'id', 'node', 'reliability', 'lines'}, 16)
    for row in logs.values():
        if _id(row['node']) not in edges:
            raise ReasoningError("Log names an unknown node")
        if _number(row['reliability'], 0, 1) <= 0:
            raise ReasoningError("Log reliability must be positive; drop a log that carries no evidence")
        for line in _rows(row['lines'], 5000):
            _log_line(line)
    rules = _indexed(request['rules'], {'id', 'contains', 'hypothesis', 'effect', 'weight'}, 64)
    evidence = _indexed(request['evidence'], {'id', 'hypothesis', 'effect', 'weight', 'reliability', 'sha256'})
    for row in list(rules.values()) + list(evidence.values()):
        if _id(row['hypothesis']) not in hypotheses:
            raise ReasoningError("Evidence names an unknown hypothesis")
        _choice(row['effect'], ('supports', 'refutes'), "evidence effect")
        if _number(row['weight'], 0, 1) <= 0:
            raise ReasoningError("Evidence and rule weights must be positive; drop a row that carries no weight")
    for row in rules.values():
        _needle(row['contains'])
    for row in evidence.values():
        if _number(row['reliability'], 0, 1) <= 0:
            raise ReasoningError("Evidence reliability must be positive; drop a row that carries no evidence")
        _digest(row['sha256'])
    ancestors = _ancestors(edges)
    roots = structural['candidate_roots']
    contributions = {key: [] for key in hypotheses}
    unmatched = []
    for key, rule in sorted(rules.items()):
        matches = [{'log': log_id, 'lines': [number for number, line in enumerate(log['lines'], 1)
                                             if rule['contains'] in line]} for log_id, log in sorted(logs.items())]
        matches = [row for row in matches if row['lines']]
        if not matches:
            unmatched.append(key)
            continue
        reliability = max(logs[row['log']]['reliability'] for row in matches)
        sign = 1 if rule['effect'] == 'supports' else -1
        contributions[rule['hypothesis']].append({'source': 'rule:' + key, 'effect': rule['effect'],
                                                  'delta': _r(sign * LOG_ODDS_SCALE * rule['weight'] * reliability),
                                                  'matches': matches})
    for key, row in sorted(evidence.items()):
        sign = 1 if row['effect'] == 'supports' else -1
        contributions[row['hypothesis']].append({'source': 'evidence:' + key, 'effect': row['effect'],
                                                 'delta': _r(sign * LOG_ODDS_SCALE * row['weight'] * row['reliability']),
                                                 'evidence_sha256': row['sha256']})
    ranked = []
    for key, row in hypotheses.items():
        node, state = row['node'], states.get(row['node'], 'unknown')
        if node in roots:
            position = 'observed_root'
        elif state == 'failed':
            position = 'downstream_of_failure'
        elif state == 'passed':
            position = 'observed_passing'
        elif any(node in ancestors[root] for root in roots):
            position = 'unobserved_upstream_of_root'
        else:
            position = 'not_upstream_of_failure'
        direct = contributions[key]
        support = _r(sum(item['delta'] for item in direct if item['delta'] > 0))
        refute = _r(-sum(item['delta'] for item in direct if item['delta'] < 0))
        log_odds = math.log(row['prior'] / (1 - row['prior'])) + STRUCTURE[position] + sum(item['delta'] for item in direct)
        score = 1 / (1 + math.exp(-max(-50, min(50, log_odds))))
        # Status follows the evidence weight, not the presence of rows: no weight either way is
        # unsupported, equal weight both ways is conflicting, and only more support than
        # refutation is supported (so a refuting or weightless row never reads as support).
        status = ('unsupported' if support <= 0 and refute <= 0
                  else 'conflicting' if support >= 1 and refute >= 1 or support == refute
                  else 'refuted' if refute > support else 'supported')
        ranked.append({'id': key, 'node': node, 'node_status': state, 'prior': row['prior'],
                       'structure': {'position': position, 'delta': STRUCTURE[position]},
                       'contributions': direct, 'support': support, 'refutation': refute,
                       'log_odds': round(log_odds, 6) + 0.0, 'score': round(score, 6) + 0.0, 'status': status})
    ranked.sort(key=lambda row: (-row['score'], row['id']))
    scale = sum(row['score'] for row in ranked)
    for row in ranked:
        row['share'] = round(row['score'] / scale, 6) + 0.0 if scale else 0.0
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    margin = round(top['score'] - (second['score'] if second else 0), 6) + 0.0
    competing = [row['id'] for row in ranked if top['score'] - row['score'] < LEADING_MARGIN and row['status'] != 'refuted']
    if top['status'] == 'supported' and top['score'] >= LEADING_SCORE and margin >= LEADING_MARGIN:
        conclusion = 'leading'
    elif len(competing) > 1:
        conclusion = 'contested'
    else:
        conclusion = 'insufficient_evidence'
    needs = []
    if conclusion == 'contested':
        needs.append({'reason': 'competing_hypotheses', 'hypotheses': competing,
                      'request': 'collect evidence that discriminates between ' + ', '.join(competing)})
        for row in ranked:
            if row['id'] in competing and row['node_status'] == 'unknown':
                needs.append({'reason': 'unobserved_node', 'node': row['node'], 'hypothesis': row['id'],
                              'request': f"observe {row['node']} directly"})
    if conclusion == 'insufficient_evidence':
        needs.append({'reason': 'weak_support', 'hypothesis': top['id'],
                      'request': f"leading score {top['score']:.3f} needs >= {LEADING_SCORE} with a {LEADING_MARGIN} margin"})
    for row in ranked:
        if row['status'] == 'conflicting':
            needs.append({'reason': 'conflicting_signals', 'hypothesis': row['id'],
                          'request': f"resolve contradictory evidence for {row['id']}"})
    body = {'conclusion': conclusion, 'leading': top['id'] if conclusion == 'leading' else None,
            'competing': competing if conclusion == 'contested' else [], 'margin': margin,
            'hypotheses': ranked, 'candidate_roots': roots, 'affected': structural['affected'],
            'uncertain_nodes': structural['uncertain_nodes'], 'unmatched_rules': unmatched,
            'needs_evidence': needs, 'causality_proven': False,
            'method': 'logit(prior) + structural position + sum(+/-3 * weight * reliability); literal log rules'}
    return _seal('rca', request, body)


# -- counterfactual evaluation -----------------------------------------------

EFFECT_OPS = ('set', 'add', 'multiply')
GATE_SEVERITIES = ('blocker', 'warning')


def _scenario(values, metrics, rules, gates):
    fired = [key for key, rule in sorted(rules.items())
             if all(_holds(values[row['assumption']], row['op'], row['value']) for row in rule['when'])]
    result = dict(metrics)
    for op in EFFECT_OPS:
        assigned = {}
        for key in fired:
            for effect in rules[key]['effects']:
                if effect['op'] != op:
                    continue
                if op == 'set':
                    if effect['metric'] in assigned and assigned[effect['metric']] != effect['value']:
                        raise ReasoningError(f"Conflicting set effects on {effect['metric']}")
                    assigned[effect['metric']] = effect['value']
                    result[effect['metric']] = effect['value']
                elif op == 'add':
                    result[effect['metric']] += effect['value']
                else:
                    result[effect['metric']] *= effect['value']
    result = {key: _r(value) for key, value in sorted(result.items())}
    if any(not math.isfinite(value) or abs(value) > 10**12 for value in result.values()):
        raise ReasoningError("Scenario metric left the finite bound")
    gate_states = {key: 'pass' if _holds(result[gate['metric']], gate['op'], gate['value']) else 'fail'
                   for key, gate in sorted(gates.items())}
    failing = [key for key, state in gate_states.items() if state == 'fail' and gates[key]['severity'] == 'blocker']
    flags = sorted({flag for key in fired for flag in rules[key]['flags']})
    return {'rules_fired': fired, 'metrics': result, 'gates': gate_states, 'failing_blockers': failing,
            'flags': flags, 'verdict': 'no-go' if failing else 'go'}


def counterfactual(request):
    """Re-evaluate a declared rule model with assumptions or decisions flipped.

    Effects apply set, then add, then multiply, independent of rule order; two
    rules setting one metric to different values is an explicit error.
    """
    _schema(request, {'schema_version', 'subject', 'assumptions', 'metrics', 'rules', 'gates', 'flips'})
    subject = _id(request['subject'])
    assumptions = _mapping(request['assumptions'], _scalar, 64, 1)
    metrics = _mapping(request['metrics'], lambda value: _number(value, -10**12, 10**12), 64, 1)
    rules = _indexed(request['rules'], {'id', 'when', 'effects', 'flags'}, 64)
    for rule in rules.values():
        for row in _rows(rule['when'], 16, 1):
            _shape(row, {'assumption', 'op', 'value'})
            if _id(row['assumption']) not in assumptions:
                raise ReasoningError("Rule condition names an unknown assumption")
            row['value'] = _operand(row['op'], row['value'])
        for row in _rows(rule['effects'], 16, 1):
            _shape(row, {'metric', 'op', 'value'})
            if _id(row['metric']) not in metrics:
                raise ReasoningError("Rule effect names an unknown metric")
            _choice(row['op'], EFFECT_OPS, "effect operator")
            _number(row['value'], -10**12, 10**12)
        rule['flags'] = sorted(_ids(rule['flags']))
    gates = _indexed(request['gates'], {'id', 'metric', 'op', 'value', 'severity'}, 64)
    for gate in gates.values():
        if _id(gate['metric']) not in metrics:
            raise ReasoningError("Gate names an unknown metric")
        _choice(gate['op'], ORDERING | {'==', '!='}, "gate operator")
        gate['value'] = _number(gate['value'], -10**12, 10**12)
        _choice(gate['severity'], GATE_SEVERITIES, "gate severity")
    flips = _indexed(request['flips'], {'id', 'set'}, 32)
    if not flips:
        raise ReasoningError("At least one flip required")
    _unique(rules, gates, flips)
    baseline = _scenario(assumptions, metrics, rules, gates)
    results = []
    for key, flip in sorted(flips.items()):
        changes = _mapping(flip['set'], _scalar, 16, 1)
        for name, value in changes.items():
            if name not in assumptions or _kind(value) != _kind(assumptions[name]):
                raise ReasoningError("Flip names an unknown assumption or changes its type")
        if all(assumptions[name] == value for name, value in changes.items()):
            raise ReasoningError("Flip changes nothing")
        changed = _scenario(dict(assumptions, **changes), metrics, rules, gates)
        metric_changes = {name: {'baseline': baseline['metrics'][name], 'counterfactual': changed['metrics'][name],
                                 'delta': _r(changed['metrics'][name] - baseline['metrics'][name])}
                          for name in sorted(metrics) if changed['metrics'][name] != baseline['metrics'][name]}
        gate_changes = [{'id': name, 'severity': gates[name]['severity'], 'baseline': baseline['gates'][name],
                         'counterfactual': changed['gates'][name]}
                        for name in sorted(gates) if changed['gates'][name] != baseline['gates'][name]]
        summary = f"{key}: verdict {baseline['verdict']} -> {changed['verdict']}"
        if changed['failing_blockers']:
            summary += '; failing blockers: ' + ', '.join(changed['failing_blockers'])
        if metric_changes:
            summary += '; ' + ', '.join(f"{name} {row['delta']:+g}" for name, row in metric_changes.items())
        results.append({'id': key,
                        'changes': {name: {'from': assumptions[name], 'to': value} for name, value in sorted(changes.items())},
                        'rules_fired': {'added': sorted(set(changed['rules_fired']) - set(baseline['rules_fired'])),
                                        'removed': sorted(set(baseline['rules_fired']) - set(changed['rules_fired']))},
                        'metrics': metric_changes, 'gates': gate_changes,
                        'flags': {'raised': sorted(set(changed['flags']) - set(baseline['flags'])),
                                  'cleared': sorted(set(baseline['flags']) - set(changed['flags']))},
                        'verdict': {'baseline': baseline['verdict'], 'counterfactual': changed['verdict']},
                        'verdict_changed': changed['verdict'] != baseline['verdict'],
                        'failing_blockers': changed['failing_blockers'], 'summary': summary})
    body = {'subject': subject, 'baseline': baseline, 'flips': results,
            'decision_sensitive_to': [row['id'] for row in results if row['verdict_changed']],
            'limits': 'Effects are the caller-declared rule model; real-world outcomes are not simulated or measured.'}
    return _seal('counterfactual', request, body)


# -- uncertainty detection and decision validation ----------------------------

EVIDENCE_VERDICTS = ('supports', 'contradicts', 'inconclusive')
CLAIM_TYPES = ('requirement', 'assumption')
MAX_EVIDENCE_AGE_SECONDS = 365 * 86400
NEEDS_EVIDENCE = ('missing', 'stale', 'conflicting', 'low_confidence', 'inconclusive')
STATUS_FLAGS = {'missing': 'missing_evidence', 'stale': 'stale_evidence', 'conflicting': 'conflicting_signals',
                'low_confidence': 'low_confidence_evidence', 'inconclusive': 'inconclusive_evidence',
                'contradicted': 'evidence_contradicts'}


def _assess(claims, rows, link, now, min_confidence):
    """Per-claim evidence status; no claim is ever covered by default."""
    evidence = _indexed(rows, {'id', link, 'kind', 'verdict', 'confidence', 'at', 'sha256'}, 256)
    buckets = {key: {'supports': [], 'contradicts': [], 'inconclusive': [], 'stale': [], 'future': [],
                     'wrong_kind': [], 'confidence': []} for key in claims}
    for key, row in sorted(evidence.items()):
        claim = _id(row[link])
        if claim not in claims:
            raise ReasoningError("Evidence references an unknown claim")
        _id(row['kind'])
        _choice(row['verdict'], EVIDENCE_VERDICTS, "evidence verdict")
        _number(row['confidence'], 0, 1)
        _number(row['at'], high=10**12)
        _digest(row['sha256'])
        bucket = buckets[claim]
        if row['kind'] not in claims[claim]['evidence_kinds']:
            bucket['wrong_kind'].append(key)
        elif row['at'] > now:
            bucket['future'].append(key)
        elif now - row['at'] > claims[claim]['max_age_seconds']:
            bucket['stale'].append(key)
        else:
            bucket[row['verdict']].append(key)
            if row['verdict'] == 'supports':
                bucket['confidence'].append(row['confidence'])
    result = {}
    for key, claim in sorted(claims.items()):
        bucket = buckets[key]
        best = max(bucket['confidence'], default=None)
        if bucket['supports'] and bucket['contradicts']:
            status = 'conflicting'
        elif bucket['contradicts']:
            status = 'contradicted'
        elif bucket['supports'] and best >= min_confidence:
            status = 'covered'
        elif bucket['supports']:
            status = 'low_confidence'
        elif bucket['inconclusive']:
            status = 'inconclusive'
        elif bucket['stale'] or bucket['future']:
            status = 'stale'
        else:
            status = 'missing'
        flags = [] if status == 'covered' else [STATUS_FLAGS[status]]
        if bucket['wrong_kind']:
            flags.append('wrong_evidence_kind')
        if bucket['future']:
            flags.append('future_dated_evidence')
        if bucket['stale'] and status != 'stale':
            flags.append('stale_evidence_ignored')
        result[key] = {'status': status, 'critical': claim['critical'], 'flags': flags,
                       'fresh_supporting': bucket['supports'], 'fresh_contradicting': bucket['contradicts'],
                       'inconclusive': bucket['inconclusive'], 'stale': bucket['stale'] + bucket['future'],
                       'wrong_kind': bucket['wrong_kind'], 'best_confidence': best}
    return result


def _needs(key, claim, state):
    kinds = ' or '.join(sorted(claim['evidence_kinds']))
    return {'claim': key, 'critical': claim['critical'], 'reason': state['status'],
            'acceptable_kinds': sorted(claim['evidence_kinds']), 'max_age_seconds': claim['max_age_seconds'],
            'request': f"provide fresh {kinds} evidence (at most {claim['max_age_seconds']} s old) for {key}"}


def _claim_rows(rows, fields, maximum=128):
    claims = _indexed(rows, fields, maximum)
    if not claims:
        raise ReasoningError("At least one claim or criterion required")
    for row in claims.values():
        _flag(row['critical'])
        row['evidence_kinds'] = set(_ids(row['evidence_kinds']))
        if not row['evidence_kinds']:
            raise ReasoningError("Acceptable evidence kinds required")
        _number(row['max_age_seconds'], 1, MAX_EVIDENCE_AGE_SECONDS, integer=True)
        if 'type' in row:
            _choice(row['type'], CLAIM_TYPES, "claim type")
            _id(row['criterion'])
    return claims


def detect_uncertainty(request, *, now=None):
    """Flag missing, stale, conflicting, inconclusive or low-confidence evidence.

    Nothing defaults to covered: each gap becomes an explicit flag and a
    ``needs_evidence`` item. ``evidence_coverage`` can feed ``select_strategy``.
    """
    _schema(request, {'schema_version', 'subject', 'claims', 'evidence', 'min_confidence'})
    subject = _id(request['subject'])
    claims = _claim_rows(request['claims'], {'id', 'type', 'criterion', 'critical', 'evidence_kinds', 'max_age_seconds'})
    minimum = _number(request['min_confidence'], 0, 1)
    now = _number(time.time() if now is None else now, high=10**12)
    states = _assess(claims, request['evidence'], 'claim', now, minimum)
    for key, state in states.items():
        state.update(type=claims[key]['type'], criterion=claims[key]['criterion'])
    needs = [_needs(key, claims[key], state) for key, state in states.items() if state['status'] in NEEDS_EVIDENCE]
    failing = [key for key, state in states.items() if state['status'] == 'contradicted']
    critical = [key for key in claims if claims[key]['critical']]
    covered = [key for key, state in states.items() if state['status'] == 'covered']
    uncovered_critical = [key for key in critical if states[key]['status'] != 'covered']
    level = ('high' if uncovered_critical else
             'medium' if len(covered) < len(claims) else 'low')
    body = {'subject': subject, 'claims': states, 'needs_evidence': needs, 'contradicted': failing,
            'flags': [{'claim': key, 'flag': flag} for key, state in states.items() for flag in state['flags']],
            'evidence_coverage': _r(len(covered) / len(claims)),
            'critical_evidence_coverage': _r(sum(1 for key in critical if key in covered) / len(critical)) if critical else None,
            'uncertainty': level, 'can_proceed': not uncovered_critical,
            'defaults_applied': [], 'evaluated_at': now}
    return _seal('uncertainty', request, body)


def validate_decision(request, *, now=None):
    """A decision passes only with fresh, sufficiently confident evidence for each critical criterion.

    Contradicting fresh evidence on a critical criterion rejects the decision;
    gaps on non-critical criteria are reported as warnings, never ignored.
    """
    _schema(request, {'schema_version', 'decision', 'criteria', 'evidence', 'min_confidence'})
    decision = _shape(request['decision'], {'id', 'choice', 'basis_sha256'})
    _id(decision['id'])
    _id(decision['choice'])
    if decision['basis_sha256'] is not None:
        _digest(decision['basis_sha256'])
    criteria = _claim_rows(request['criteria'], {'id', 'critical', 'evidence_kinds', 'max_age_seconds'})
    if not any(row['critical'] for row in criteria.values()):
        raise ReasoningError("At least one critical criterion required")
    minimum = _number(request['min_confidence'], 0, 1)
    now = _number(time.time() if now is None else now, high=10**12)
    states = _assess(criteria, request['evidence'], 'criterion', now, minimum)
    reasons = [f"{key}: {state['status']}" for key, state in states.items()
               if state['critical'] and state['status'] != 'covered']
    warnings = [f"{key}: {state['status']}" for key, state in states.items()
                if not state['critical'] and state['status'] != 'covered']
    body = {'decision': decision['id'], 'choice': decision['choice'], 'basis_sha256': decision['basis_sha256'],
            'status': 'rejected' if reasons else 'validated', 'criteria': states,
            'rejected_because': reasons, 'warnings': warnings,
            'missing_evidence': [_needs(key, criteria[key], state) for key, state in states.items()
                                 if state['critical'] and state['status'] in NEEDS_EVIDENCE],
            'evaluated_at': now,
            'limits': 'Validates evidence metadata and freshness; it does not authenticate the evidence collector.'}
    return _seal('validate-decision', request, body)


# -- multi-perspective review ------------------------------------------------

PERSPECTIVES = ('architecture', 'security', 'quality', 'cost', 'operability')
SEVERITIES = ('low', 'medium', 'high', 'critical')
FACTS = {
    'cyclic_module_dependencies': 'count', 'single_points_of_failure': 'count',
    'max_module_coupling': 'ratio', 'decision_record': 'bool',
    'secrets_in_repo': 'bool', 'auth_required': 'bool', 'auth_implemented': 'bool',
    'dependencies_pinned': 'bool', 'handles_personal_data': 'bool', 'encryption_at_rest': 'bool',
    'threat_model': 'bool',
    'failing_tests': 'count', 'line_coverage': 'ratio', 'integration_tests': 'bool',
    'static_analysis_clean': 'bool',
    'monthly_cost_usd': 'amount', 'monthly_budget_usd': 'amount', 'unapproved_paid_services': 'count',
    'stateful': 'bool', 'backups': 'bool', 'monitoring': 'bool', 'rollback_plan': 'bool', 'runbook': 'bool',
}
POLICY = {'max_module_coupling': .7, 'line_coverage_medium': .6, 'line_coverage_high': .3, 'budget_warning_ratio': .8}


def _when(fact, expected, needs):
    """Facts to require: ``needs`` only applies once ``fact`` is known to equal ``expected``."""
    return lambda f: (fact,) + (needs if f.get(fact) is expected else ())


# (perspective, check id, required facts given known facts, severity or None, message, recommendation)
CHECKS = (
    ('architecture', 'arch-cycles', lambda f: ('cyclic_module_dependencies',),
     lambda f: 'high' if f['cyclic_module_dependencies'] > 0 else None,
     'module dependency cycles are declared', 'break the cycles before adding features'),
    ('architecture', 'arch-single-point', lambda f: ('single_points_of_failure',),
     lambda f: 'medium' if f['single_points_of_failure'] > 0 else None,
     'single points of failure are declared', 'add redundancy or document the accepted risk'),
    ('architecture', 'arch-coupling', lambda f: ('max_module_coupling',),
     lambda f: 'medium' if f['max_module_coupling'] > POLICY['max_module_coupling'] else None,
     'module coupling exceeds 0.7', 'introduce a boundary or an interface between the coupled modules'),
    ('architecture', 'arch-decision-record', lambda f: ('decision_record',),
     lambda f: 'low' if not f['decision_record'] else None,
     'no architecture decision record', 'record the decision, alternatives and evidence'),
    ('security', 'sec-secrets', lambda f: ('secrets_in_repo',),
     lambda f: 'critical' if f['secrets_in_repo'] else None,
     'secrets are present in the repository', 'remove and rotate them; load secrets from the environment'),
    ('security', 'sec-auth', _when('auth_required', True, ('auth_implemented',)),
     lambda f: 'critical' if f['auth_required'] and not f['auth_implemented'] else None,
     'authentication is required but not implemented', 'implement and test authentication before release'),
    ('security', 'sec-pinned-dependencies', lambda f: ('dependencies_pinned',),
     lambda f: 'medium' if not f['dependencies_pinned'] else None,
     'dependencies are not pinned', 'pin exact versions with a lockfile and audit them'),
    ('security', 'sec-personal-data', _when('handles_personal_data', True, ('encryption_at_rest',)),
     lambda f: 'high' if f['handles_personal_data'] and not f['encryption_at_rest'] else None,
     'personal data is stored without encryption at rest', 'enable encryption at rest'),
    ('security', 'sec-threat-model', lambda f: ('threat_model',),
     lambda f: 'medium' if not f['threat_model'] else None,
     'no threat model', 'write a short threat model for the trust boundaries'),
    ('quality', 'qa-failing-tests', lambda f: ('failing_tests',),
     lambda f: 'critical' if f['failing_tests'] > 0 else None,
     'tests are failing', 'fix the failures; never skip or delete tests'),
    ('quality', 'qa-coverage', lambda f: ('line_coverage',),
     lambda f: ('high' if f['line_coverage'] < POLICY['line_coverage_high'] else
                'medium' if f['line_coverage'] < POLICY['line_coverage_medium'] else None),
     'line coverage is below policy', 'add tests for untested paths, including negative cases'),
    ('quality', 'qa-integration-tests', lambda f: ('integration_tests',),
     lambda f: 'high' if not f['integration_tests'] else None,
     'no integration tests', 'add integration tests across component boundaries'),
    ('quality', 'qa-static-analysis', lambda f: ('static_analysis_clean',),
     lambda f: 'low' if not f['static_analysis_clean'] else None,
     'static analysis reports issues', 'resolve or triage the static analysis findings'),
    ('cost', 'cost-budget', lambda f: ('monthly_cost_usd', 'monthly_budget_usd'),
     lambda f: ('high' if f['monthly_cost_usd'] > f['monthly_budget_usd'] else
                'low' if f['monthly_cost_usd'] > POLICY['budget_warning_ratio'] * f['monthly_budget_usd'] else None),
     'monthly cost is over or near the budget', 'reduce cost or get an explicit budget approval'),
    ('cost', 'cost-unapproved-paid', lambda f: ('unapproved_paid_services',),
     lambda f: 'critical' if f['unapproved_paid_services'] > 0 else None,
     'paid services are used without approval', 'remove them or obtain explicit owner approval'),
    ('operability', 'ops-backups', _when('stateful', True, ('backups',)),
     lambda f: 'high' if f['stateful'] and not f['backups'] else None,
     'stateful system without backups', 'configure and restore-test backups'),
    ('operability', 'ops-monitoring', lambda f: ('monitoring',),
     lambda f: 'medium' if not f['monitoring'] else None,
     'no monitoring', 'add health checks, error tracking and alerts'),
    ('operability', 'ops-rollback', lambda f: ('rollback_plan',),
     lambda f: 'high' if not f['rollback_plan'] else None,
     'no rollback plan', 'document and rehearse a rollback'),
    ('operability', 'ops-runbook', lambda f: ('runbook',),
     lambda f: 'low' if not f['runbook'] else None,
     'no runbook', 'write a runbook for common incidents'),
)
VERDICTS = ('pass', 'concerns', 'insufficient_evidence', 'fail')


def _fact(name, value):
    kind = FACTS[name]
    if kind == 'bool':
        return _flag(value)
    if kind == 'count':
        return _number(value, 0, 10**6, integer=True)
    if kind == 'ratio':
        return _number(value, 0, 1)
    return _number(value, 0, 10**9)


def review_perspectives(request):
    """Fixed, documented checks per perspective over declared facts.

    A check whose facts are missing yields a ``needs_evidence`` finding, never a pass.
    Judging code or design text itself would need a model (see ``route_model``).
    """
    _schema(request, {'schema_version', 'subject', 'facts', 'perspectives'})
    subject = _id(request['subject'])
    if not isinstance(request['facts'], dict) or len(request['facts']) > len(FACTS):
        raise ReasoningError("Facts must be a mapping")
    if not set(request['facts']) <= FACTS.keys():
        raise ReasoningError("Unknown review fact")
    facts = {name: _fact(name, value) for name, value in request['facts'].items()}
    chosen = _ids(request['perspectives'])
    if not chosen or not set(chosen) <= set(PERSPECTIVES):
        raise ReasoningError("Choose one or more known perspectives")
    report = {}
    for perspective in [name for name in PERSPECTIVES if name in chosen]:
        findings, needs, checked = [], [], []
        for owner, check, required, test, message, recommendation in CHECKS:
            if owner != perspective:
                continue
            checked.append(check)
            missing = [name for name in required(facts) if name not in facts]
            if missing:
                needs.append({'check': check, 'facts': missing})
                continue
            severity = test(facts)
            if severity:
                findings.append({'check': check, 'severity': severity, 'message': message,
                                 'recommendation': recommendation,
                                 'facts': {name: facts[name] for name in required(facts)}})
        findings.sort(key=lambda row: (-SEVERITIES.index(row['severity']), row['check']))
        worst = max((SEVERITIES.index(row['severity']) for row in findings), default=-1)
        verdict = ('fail' if worst >= SEVERITIES.index('high') else 'insufficient_evidence' if needs
                   else 'concerns' if findings else 'pass')
        report[perspective] = {'verdict': verdict, 'findings': findings, 'needs_evidence': needs, 'checked': checked}
    overall = max((row['verdict'] for row in report.values()), key=VERDICTS.index)
    body = {'subject': subject, 'verdict': overall, 'approved': overall in ('pass', 'concerns'),
            'perspectives': report, 'policy': dict(POLICY),
            'blocking_findings': [dict(row, perspective=name) for name, value in report.items()
                                  for row in value['findings'] if row['severity'] in ('high', 'critical')],
            'model_review': 'not-performed',
            'limits': 'Checks declared facts only; reading code or design documents would need a routed model review.'}
    return _seal('perspectives', request, body)


# -- engineering trade-off analysis with sensitivity --------------------------

def _totals(options, criteria, normalized, weights):
    return {option: sum(weights[c] * normalized[option][c] for c in criteria) for option in options}


def _winner(totals):
    return min(totals, key=lambda option: (-round(totals[option], 12), option))


def _shifted(criteria, weights, criterion, x):
    """Weights with ``criterion`` set to x and the others rescaled to keep the sum at one."""
    rest = 1 - weights[criterion]
    others = [c for c in criteria if c != criterion]
    return {c: x if c == criterion else
            (weights[c] * (1 - x) / rest if rest > 1e-12 else (1 - x) / len(others)) for c in criteria}


def trade_off(request):
    """Weighted criteria matrix with min-max normalisation and one-at-a-time weight sensitivity.

    For every criterion the result states the weight at which the winner changes
    (other weights rescaled proportionally), the new winner, and whether that
    flip lies within ``robustness_margin`` of the current weight. When the top
    totals tie, ``tied`` lists the tied options, ``winner`` is only the smallest id
    among them and ``robust`` is false.
    """
    _schema(request, {'schema_version', 'decision', 'options', 'criteria', 'values', 'robustness_margin'})
    decision = _id(request['decision'])
    options = _ids(request['options'])
    if not 2 <= len(options) <= 16:
        raise ReasoningError("Two to sixteen options required")
    criteria_rows = _indexed(request['criteria'], {'id', 'weight', 'direction'}, 16)
    if not criteria_rows:
        raise ReasoningError("At least one criterion required")
    criteria = sorted(criteria_rows)
    weights = {c: _number(criteria_rows[c]['weight'], 0, 1) for c in criteria}
    if abs(sum(weights.values()) - 1) > 1e-9:
        raise ReasoningError("Criterion weights must sum to one")
    for c in criteria:
        _choice(criteria_rows[c]['direction'], ('higher', 'lower'), "criterion direction")
    values = request['values']
    if not isinstance(values, dict) or set(values) != set(options):
        raise ReasoningError("Values needed for exactly the declared options")
    for option in options:
        if not isinstance(values[option], dict) or set(values[option]) != set(criteria):
            raise ReasoningError("Every option needs a value for every criterion")
        for c in criteria:
            _number(values[option][c], -10**12, 10**12)
    margin = _number(request['robustness_margin'], 0, 1)
    normalized = {option: {} for option in options}
    for c in criteria:
        column = [values[option][c] for option in options]
        low, high = min(column), max(column)
        for option in options:
            if high == low:
                score = 1.0
            elif criteria_rows[c]['direction'] == 'higher':
                score = (values[option][c] - low) / (high - low)
            else:
                score = (high - values[option][c]) / (high - low)
            normalized[option][c] = _r(score)
    totals = _totals(options, criteria, normalized, weights)
    ranking = sorted(options, key=lambda option: (-round(totals[option], 12), option))
    winner = ranking[0]
    sensitivity = []
    for c in criteria:
        row = {'criterion': c, 'weight': weights[c], 'increase': None, 'decrease': None}
        if len(criteria) > 1:
            base = {}
            for option in options:
                shifted = [_totals([option], criteria, normalized, _shifted(criteria, weights, c, x))[option] for x in (0, 1)]
                base[option] = (shifted[0], shifted[1] - shifted[0])   # total(x) = intercept + slope * x
            for direction, sign in (('increase', 1), ('decrease', -1)):
                crossings = []
                for option in options:
                    if option == winner:
                        continue
                    a = base[winner][0] - base[option][0]
                    b = base[winner][1] - base[option][1]
                    if abs(b) < 1e-12:
                        continue
                    x = -a / b
                    # the other option must strictly overtake inside [0, 1]; a tie
                    # reached only at the boundary is not a flip
                    if 0 <= x + sign * 1e-7 <= 1 and sign * (x - weights[c]) >= 0 and sign * b < 0:
                        crossings.append(x)
                if not crossings:
                    continue
                x = min(crossings) if sign > 0 else max(crossings)
                probe = x + sign * 1e-7
                new_winner = _winner(_totals(options, criteria, normalized, _shifted(criteria, weights, c, probe)))
                if new_winner == winner:
                    continue
                row[direction] = {'flip_weight': _r(x), 'change': _r(x - weights[c]), 'new_winner': new_winner,
                                  'weights_at_flip': {k: _r(v) for k, v in _shifted(criteria, weights, c, x).items()}}
        changes = [abs(row[d]['change']) for d in ('increase', 'decrease') if row[d]]
        row['min_change'] = _r(min(changes)) if changes else None
        row['within_margin'] = bool(changes) and min(changes) <= margin
        sensitivity.append(row)
    flippable = [row for row in sensitivity if row['min_change'] is not None]
    most = min(flippable, key=lambda row: (row['min_change'], row['criterion'])) if flippable else None
    tied = [option for option in ranking if round(totals[option], 12) == round(totals[winner], 12)]
    tie = len(tied) > 1
    body = {'decision': decision, 'winner': winner, 'runner_up': ranking[1], 'tie': tie, 'tied': tied if tie else [],
            'ranking': ranking, 'totals': {option: _r(totals[option]) for option in options},
            'margin': _r(totals[winner] - totals[ranking[1]]),
            'weights': weights, 'normalized': normalized,
            'contributions': {option: {c: _r(weights[c] * normalized[option][c]) for c in criteria} for option in options},
            'sensitivity': sensitivity,
            'most_sensitive': None if most is None else {
                'criterion': most['criterion'], 'min_change': most['min_change'],
                'new_winner': next(most[d]['new_winner'] for d in ('increase', 'decrease')
                                   if most[d] and abs(most[d]['change']) == most['min_change'])},
            # A tie has no single winner: ``winner`` is then only the id tie-break, never robust.
            'robust': not tie and not any(row['within_margin'] for row in sensitivity), 'robustness_margin': margin,
            'method': 'min-max normalised weighted sum; one weight varied, others rescaled proportionally'}
    return _seal('trade-off', request, body)


# -- model / tool routing hook -----------------------------------------------

MODEL_STEPS = ('design-critique', 'hypothesis-generation', 'independent-review',
               'natural-language-summary', 'unstructured-log-interpretation')
_CREDENTIAL_NAME = re.compile(r"[A-Z][A-Z0-9_]{2,63}")


def route_model(request, *, credentials_present=(), now=None):
    """Return the model-routing decision for a step that would need an AI model.

    Uses ``model_router.select_model``; no model is called and nothing is
    reserved. ``credentials_present`` lists environment variable NAMES the caller
    attests are configured; the process environment and secret values are never read.
    """
    _schema(request, {'schema_version', 'step', 'registry', 'routing', 'evidence'})
    step = _id(request['step'])
    if not isinstance(credentials_present, (list, tuple)) or len(credentials_present) > 32 or any(
            not isinstance(name, str) or not _CREDENTIAL_NAME.fullmatch(name) for name in credentials_present):
        raise ReasoningError("Credential presence is a list of environment variable names")
    names = sorted(set(credentials_present))
    if step in _ACTIONS and step != 'route-model':
        if any(request[key] is not None for key in ('registry', 'routing', 'evidence')):
            raise ReasoningError("Deterministic steps take no model routing metadata")
        body = {'step': step, 'requires_model': False, 'decision': 'not-needed', 'routing': None,
                'model_called': False, 'invocation': 'not-needed', 'credentials_considered': [],
                'reason': f"{step} is computed deterministically by the reasoning engine", 'evaluated_at': None}
        return _seal('route-model', request, body)
    if step not in MODEL_STEPS:
        raise ReasoningError("Unknown reasoning step")
    now = _number(time.time() if now is None else now, high=10**12)
    from .model_router import select_model
    try:
        routing = select_model(request['registry'], request['routing'], request['evidence'],
                               environ={name: 'present' for name in names}, now=now)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ReasoningError("Model routing rejected the registry, request or evidence") from None
    selected = routing['selected']
    body = {'step': step, 'requires_model': True, 'decision': routing['decision'], 'routing': routing,
            'model_called': False, 'invocation': 'not-performed', 'credentials_considered': names,
            'reason': (f"{step} needs model judgement; eligible model {selected['id']} selected by policy"
                       if selected else f"{step} needs model judgement; no model is eligible, so the step is blocked"),
            'next_action': ('revalidate quota and invoke through an approved runner; record its receipt separately'
                            if selected else 'register and project-verify a model, or perform the step by human review'),
            'evaluated_at': now}
    return _seal('route-model', request, body)


# -- engine entrypoint (contract: (action, payload, ctx) -> dict) -------------

def _review_action(payload, *, now=None):
    _shape(payload, {'plan', 'reviews', 'verification'})
    return review_decision(payload['plan'], payload['reviews'], payload['verification'], now=now)


def _root_causes_action(payload):
    _shape(payload, {'observations', 'dependencies'})
    return root_causes(payload['observations'], payload['dependencies'])


_ACTIONS = {
    'plan': (plan, ('now',), 'schedule caller-supplied task nodes and rank evidenced alternatives'),
    'review': (_review_action, ('now',), 'gate a plan on independent review and verification attestations'),
    'root-causes': (_root_causes_action, (), 'earliest observed failures along a declared dependency DAG'),
    'strategy': (select_strategy, (), 'choose quick, standard or deep reasoning with the reason'),
    'decompose': (decompose, (), 'expand goal, milestones and tasks into planner nodes'),
    'plan-goal': (plan_goal, ('now',), 'decompose a goal and schedule it with the wave planner'),
    'constraints': (evaluate_constraints, (), 'check hard constraints and score soft constraints'),
    'dependencies': (analyze_dependencies, (), 'critical path, slack, ready and blocked items'),
    'rca': (analyze_root_causes, (), 'rank competing root-cause hypotheses by weighted evidence'),
    'counterfactual': (counterfactual, (), 'evaluate what changes when assumptions or decisions flip'),
    'uncertainty': (detect_uncertainty, ('now',), 'flag missing, stale or conflicting evidence'),
    'perspectives': (review_perspectives, (), 'architecture, security, quality, cost and operability findings'),
    'validate-decision': (validate_decision, ('now',), 'accept a decision only with evidence for critical criteria'),
    'trade-off': (trade_off, (), 'weighted criteria matrix with weight sensitivity'),
    'route-model': (route_model, ('now', 'credentials'), 'routing decision for a step that needs a model; no call'),
}

ENGINE_RECORD = {
    'id': ENGINE, 'layer': LAYER,
    'title': {'en': 'Advanced Engineering Reasoning', 'ar': 'الاستدلال الهندسي المتقدم'},
    'entrypoint': 'engineering_os.reasoning:engine', 'health': 'engineering_os.reasoning:health',
    # payload-only computation: no repository, state, registry file, network or secret is read
    'actions': {name: {'side_effect': 'none', 'permissions': ['secrets:none'], 'summary': spec[2]}
                for name, spec in _ACTIONS.items()},
    'supersedes': [],
}


def engine(action, payload, ctx=None):
    """Engine-contract entrypoint. ``ctx`` may carry ``now`` and ``credentials_present``."""
    if not isinstance(action, str) or action not in _ACTIONS:
        raise ReasoningError("Unknown reasoning action")
    ctx = {} if ctx is None else ctx
    if not isinstance(ctx, dict):
        raise ReasoningError("Context must be an object")
    function, uses, _summary = _ACTIONS[action]
    options = {}
    if 'now' in uses:
        options['now'] = ctx.get('now')
    if 'credentials' in uses:
        options['credentials_present'] = ctx.get('credentials_present', ())
    return function(payload, **options)


def replay(action, payload, output, *, credentials_present=()):
    """Recompute ``output`` from ``payload`` at its recorded clock; True when identical."""
    verify_receipt(output, payload)
    if output['operation'] != action:
        raise ReasoningError("Receipt names another operation")
    clock = output.get('planned_at') if action == 'plan' else output.get('evaluated_at')
    again = engine(action, copy.deepcopy(payload), {'now': clock, 'credentials_present': credentials_present})
    return again == output


def health():
    """Side-effect-free self check of sealing and strategy selection."""
    probe = {'schema_version': 1, 'task': 'health-probe', 'risk': .1, 'complexity': .1, 'novelty': .1,
             'reversibility': .9, 'evidence_coverage': .9}
    try:
        result = select_strategy(probe)
        ok = verify_receipt(result, probe) and result['depth'] == 'quick'
    except Exception as error:  # health must report, not raise
        return {'ok': False, 'detail': f"reasoning self-check failed: {type(error).__name__}"}
    return {'ok': bool(ok), 'detail': f"{len(_ACTIONS)} deterministic actions; self-check receipt verified"}
