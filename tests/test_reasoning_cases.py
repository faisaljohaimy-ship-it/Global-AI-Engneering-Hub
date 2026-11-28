"""Layer L13 reasoning cases. Every fixture here is synthetic (simulated figures, no
real project, provider, price list or benchmark); no model or network is used."""
import copy
import json
import unittest
from unittest import mock

from engineering_os import reasoning as r
from engineering_os.reasoning import ReasoningError

NOW = 1800000000
DAY = 86400


def sealed(test, output, payload, operation):
    """Every L13 output is deterministic and bound to its exact input by a receipt."""
    test.assertEqual(output['mode'], 'deterministic')
    test.assertEqual(output['operation'], operation)
    test.assertEqual(output['provider_calls'], 0)
    test.assertTrue(r.verify_receipt(output, payload))
    return output


# -- case 1: storage for a small project-management demo app -------------------

def storage_options():
    # simulated figures for a demo workload, not vendor quotes or measurements
    return {'schema_version': 1, 'decision': 'pm-demo-storage',
            'options': [
                {'id': 'sqlite', 'attributes': {'monthly_cost_usd': 0, 'ops_hours_per_month': .5,
                                                'sustained_writes_per_second': 400, 'managed_backups': False,
                                                'setup_minutes': 5}},
                {'id': 'postgres', 'attributes': {'monthly_cost_usd': 15, 'ops_hours_per_month': 3,
                                                  'sustained_writes_per_second': 4000, 'managed_backups': True,
                                                  'setup_minutes': 45}}],
            'hard': [{'id': 'demo-budget', 'attribute': 'monthly_cost_usd', 'op': '<=', 'value': 10},
                     {'id': 'peak-write-load', 'attribute': 'sustained_writes_per_second', 'op': '>=', 'value': 50}],
            'soft': [{'id': 'low-ops', 'attribute': 'ops_hours_per_month', 'op': '<=', 'value': 1, 'weight': .4},
                     {'id': 'fast-setup', 'attribute': 'setup_minutes', 'op': '<=', 'value': 15, 'weight': .3},
                     {'id': 'backups', 'attribute': 'managed_backups', 'op': '==', 'value': True, 'weight': .3}]}


def storage_trade_off():
    return {'schema_version': 1, 'decision': 'pm-demo-storage', 'options': ['sqlite', 'postgres'],
            'criteria': [{'id': 'monthly-cost', 'weight': .25, 'direction': 'lower'},
                         {'id': 'ops-effort', 'weight': .20, 'direction': 'lower'},
                         {'id': 'scalability', 'weight': .30, 'direction': 'higher'},
                         {'id': 'concurrency', 'weight': .15, 'direction': 'higher'},
                         {'id': 'setup-minutes', 'weight': .10, 'direction': 'lower'}],
            'values': {'sqlite': {'monthly-cost': 0, 'ops-effort': .5, 'scalability': 2, 'concurrency': 1,
                                  'setup-minutes': 5},
                       'postgres': {'monthly-cost': 15, 'ops-effort': 3, 'scalability': 9, 'concurrency': 100,
                                    'setup-minutes': 45}},
            'robustness_margin': .1}


def storage_decision(evidence):
    return {'schema_version': 1, 'decision': {'id': 'pm-demo-storage', 'choice': 'sqlite', 'basis_sha256': None},
            'criteria': [{'id': 'within-budget', 'critical': True, 'evidence_kinds': ['pricing'],
                          'max_age_seconds': 30 * DAY},
                         {'id': 'write-throughput', 'critical': True, 'evidence_kinds': ['load-test'],
                          'max_age_seconds': 7 * DAY},
                         {'id': 'developer-experience', 'critical': False, 'evidence_kinds': ['review'],
                          'max_age_seconds': 30 * DAY}],
            'evidence': evidence, 'min_confidence': .7}


def evidence(identifier, link, claim, kind, verdict='supports', confidence=.9, at=NOW - 3600, digest='5'):
    return {'id': identifier, link: claim, 'kind': kind, 'verdict': verdict, 'confidence': confidence,
            'at': at, 'sha256': digest * 64}


class StorageChoiceCase(unittest.TestCase):
    def test_hard_budget_excludes_postgres_and_soft_scores_explain_sqlite(self):
        request = storage_options()
        original = copy.deepcopy(request)
        with mock.patch('socket.socket', side_effect=AssertionError('no network')):
            one, two = r.evaluate_constraints(request), r.evaluate_constraints(request)
        self.assertEqual(one, two)
        self.assertEqual(request, original)
        sealed(self, one, request, 'constraints')
        self.assertEqual(one['status'], 'selected')
        self.assertEqual(one['selected'], 'sqlite')
        rows = {row['id']: row for row in one['options']}
        self.assertEqual(rows['postgres']['status'], 'infeasible')
        self.assertEqual(rows['postgres']['violations'], ['demo-budget'])
        self.assertEqual(rows['sqlite']['soft_score'], .7)
        self.assertEqual(rows['sqlite']['soft']['backups'], 'fail')

    def test_raising_the_budget_lets_soft_constraints_rank_both(self):
        request = storage_options()
        request['hard'][0]['value'] = 20
        result = r.evaluate_constraints(request)
        self.assertEqual(result['ranking'], ['sqlite', 'postgres'])
        self.assertEqual({row['id']: row['status'] for row in result['options']},
                         {'sqlite': 'feasible', 'postgres': 'feasible'})

    def test_option_missing_a_hard_fact_is_undetermined_and_needs_evidence(self):
        request = storage_options()
        request['options'].append({'id': 'hosted-postgres', 'attributes': {
            'ops_hours_per_month': .5, 'sustained_writes_per_second': 2000, 'managed_backups': True,
            'setup_minutes': 10}})
        result = r.evaluate_constraints(request)
        rows = {row['id']: row for row in result['options']}
        self.assertEqual(rows['hosted-postgres']['status'], 'undetermined')
        self.assertEqual(rows['hosted-postgres']['unknown_hard'], ['demo-budget'])
        self.assertEqual(result['status'], 'provisional')
        self.assertEqual(result['needs_evidence'][0]['option'], 'hosted-postgres')
        self.assertEqual(result['needs_evidence'][0]['attributes'], ['monthly_cost_usd'])

    def test_trade_off_matrix_picks_sqlite_with_explicit_contributions(self):
        request = storage_trade_off()
        result = sealed(self, r.trade_off(request), request, 'trade-off')
        self.assertEqual(result['winner'], 'sqlite')
        self.assertEqual(result['totals'], {'sqlite': .55, 'postgres': .45})
        self.assertEqual(result['margin'], .1)
        self.assertEqual(result['contributions']['sqlite']['monthly-cost'], .25)
        self.assertEqual(result['normalized']['postgres']['monthly-cost'], 0)

    def test_decision_validates_only_with_evidence_for_each_critical_criterion(self):
        rows = [evidence('pricing-sheet', 'criterion', 'within-budget', 'pricing'),
                evidence('write-load-test', 'criterion', 'write-throughput', 'load-test', confidence=.8)]
        request = storage_decision(rows)
        result = sealed(self, r.validate_decision(request, now=NOW), request, 'validate-decision')
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(result['rejected_because'], [])
        self.assertEqual(result['warnings'], ['developer-experience: missing'])
        self.assertTrue(r.replay('validate-decision', request, result))

    def test_strategy_for_the_storage_choice_is_standard_with_reason(self):
        request = {'schema_version': 1, 'task': 'pm-demo-storage', 'risk': .3, 'complexity': .3,
                   'novelty': .2, 'reversibility': .5, 'evidence_coverage': .8}
        result = sealed(self, r.select_strategy(request), request, 'strategy')
        self.assertEqual(result['depth'], 'standard')
        self.assertEqual(result['score'], .31)
        self.assertTrue(result['reason'].startswith('standard: weighted score 0.310 selects standard'))
        self.assertIn('trade-off', result['actions'])
        self.assertEqual(result['model_steps'], [])


# -- case 2: root cause of a failing build from logs and a dependency graph -------

def failing_build():
    return {'schema_version': 1,
            'dependencies': {'registry': [], 'lockfile': [], 'npm-install': ['lockfile', 'registry'],
                             'codegen': ['npm-install'], 'compile': ['codegen', 'npm-install'],
                             'unit-tests': ['compile'], 'bundle': ['compile']},
            'observations': [{'id': 'npm-install', 'status': 'failed', 'evidence_sha256': 'd' * 64},
                             {'id': 'compile', 'status': 'failed', 'evidence_sha256': 'e' * 64},
                             {'id': 'unit-tests', 'status': 'failed', 'evidence_sha256': 'f' * 64},
                             {'id': 'codegen', 'status': 'passed', 'evidence_sha256': '1' * 64}],
            'hypotheses': [{'id': 'lockfile-drift', 'node': 'lockfile', 'prior': .3},
                           {'id': 'registry-outage', 'node': 'registry', 'prior': .3},
                           {'id': 'compiler-regression', 'node': 'compile', 'prior': .2}],
            'logs': [{'id': 'npm-install-log', 'node': 'npm-install', 'reliability': .9, 'lines': [
                         'npm http fetch GET 200 https://registry.example.test/react 120ms',
                         'npm ERR! code ERESOLVE',
                         'npm ERR! ERESOLVE unable to resolve dependency tree',
                         '\tnpm ERR! peer react@"^18.2.0" from react-dom@18.2.0']},
                     {'id': 'tsc-log', 'node': 'compile', 'reliability': .8, 'lines': [
                         "src/main.tsx(3,22): error TS2307: Cannot find module 'react-dom/client'"]}],
            'rules': [{'id': 'eresolve', 'contains': 'ERESOLVE', 'hypothesis': 'lockfile-drift',
                       'effect': 'supports', 'weight': .7},
                      {'id': 'registry-reachable', 'contains': 'fetch GET 200', 'hypothesis': 'registry-outage',
                       'effect': 'refutes', 'weight': .6},
                      {'id': 'timeout', 'contains': 'ETIMEDOUT', 'hypothesis': 'registry-outage',
                       'effect': 'supports', 'weight': .8},
                      {'id': 'missing-module', 'contains': 'TS2307', 'hypothesis': 'compiler-regression',
                       'effect': 'refutes', 'weight': .5}],
            'evidence': [{'id': 'lockfile-diff', 'hypothesis': 'lockfile-drift', 'effect': 'supports',
                          'weight': .6, 'reliability': .9, 'sha256': '2' * 64}]}


class FailingBuildCase(unittest.TestCase):
    def test_lockfile_drift_leads_with_weighted_explainable_evidence(self):
        request = failing_build()
        result = sealed(self, r.analyze_root_causes(request), request, 'rca')
        self.assertEqual(result['candidate_roots'], ['npm-install'])
        self.assertEqual(result['conclusion'], 'leading')
        self.assertEqual(result['leading'], 'lockfile-drift')
        ranked = {row['id']: row for row in result['hypotheses']}
        self.assertEqual([row['id'] for row in result['hypotheses']],
                         ['lockfile-drift', 'registry-outage', 'compiler-regression'])
        lockfile = ranked['lockfile-drift']
        self.assertEqual(lockfile['structure'], {'position': 'unobserved_upstream_of_root', 'delta': .5})
        self.assertEqual([(row['source'], row['delta']) for row in lockfile['contributions']],
                         [('rule:eresolve', 1.89), ('evidence:lockfile-diff', 1.62)])
        self.assertEqual(lockfile['contributions'][0]['matches'], [{'log': 'npm-install-log', 'lines': [2, 3]}])
        self.assertEqual(ranked['compiler-regression']['structure']['position'], 'downstream_of_failure')
        self.assertEqual(ranked['registry-outage']['status'], 'refuted')
        self.assertEqual(result['unmatched_rules'], ['timeout'])
        self.assertAlmostEqual(sum(row['share'] for row in result['hypotheses']), 1, places=5)
        self.assertFalse(result['causality_proven'])

    def test_log_text_is_never_echoed_into_the_result(self):
        result = r.analyze_root_causes(failing_build())
        text = json.dumps(result)
        self.assertNotIn('unable to resolve', text)
        self.assertNotIn('registry.example.test', text)

    def test_competing_hypotheses_are_contested_and_ask_for_discriminating_evidence(self):
        request = failing_build()
        request['evidence'] = []
        request['logs'][0]['lines'] = ['npm ERR! code ERESOLVE', 'npm ERR! network ETIMEDOUT']
        result = r.analyze_root_causes(request)
        self.assertEqual(result['conclusion'], 'contested')
        self.assertIsNone(result['leading'])
        self.assertEqual(result['competing'], ['registry-outage', 'lockfile-drift'])   # rank order
        self.assertLess(result['margin'], .2)
        reasons = [row['reason'] for row in result['needs_evidence']]
        self.assertIn('competing_hypotheses', reasons)
        self.assertEqual(sorted(row['node'] for row in result['needs_evidence'] if row['reason'] == 'unobserved_node'),
                         ['lockfile', 'registry'])

    def test_contradictory_evidence_is_flagged_not_averaged_away(self):
        request = failing_build()
        request['evidence'].append({'id': 'lockfile-verified', 'hypothesis': 'lockfile-drift', 'effect': 'refutes',
                                    'weight': .9, 'reliability': .9, 'sha256': '3' * 64})
        result = r.analyze_root_causes(request)
        lockfile = next(row for row in result['hypotheses'] if row['id'] == 'lockfile-drift')
        self.assertEqual(lockfile['status'], 'conflicting')
        self.assertIn({'reason': 'conflicting_signals', 'hypothesis': 'lockfile-drift',
                       'request': 'resolve contradictory evidence for lockfile-drift'}, result['needs_evidence'])

    def test_rca_rejects_unbound_secret_shaped_or_failure_free_input(self):
        for change in ['unknown-node', 'unknown-hypothesis', 'secret', 'control', 'no-failure', 'cycle', 'prior']:
            request = failing_build()
            if change == 'unknown-node':
                request['hypotheses'][0]['node'] = 'missing'
            elif change == 'unknown-hypothesis':
                request['rules'][0]['hypothesis'] = 'missing'
            elif change == 'secret':
                request['logs'][0]['lines'].append('token ghp_' + 'A' * 36)
            elif change == 'control':
                request['logs'][0]['lines'].append('bell \x07')
            elif change == 'no-failure':
                for row in request['observations']:
                    row['status'] = 'passed'
            elif change == 'cycle':
                request['dependencies']['lockfile'] = ['unit-tests']
            else:
                request['hypotheses'][0]['prior'] = 1
            with self.subTest(change=change), self.assertRaises(ReasoningError):
                r.analyze_root_causes(request)


# -- case 3: counterfactual of skipping integration tests before release --------

def release_model():
    return {'schema_version': 1, 'subject': 'release-1-4',
            'assumptions': {'run_integration_tests': True, 'run_unit_tests': True},
            'metrics': {'escaped_defect_probability': .05, 'release_hours': 6, 'verified_contracts': 12},
            'rules': [{'id': 'skip-integration',
                       'when': [{'assumption': 'run_integration_tests', 'op': '==', 'value': False}],
                       'effects': [{'metric': 'escaped_defect_probability', 'op': 'add', 'value': .25},
                                   {'metric': 'release_hours', 'op': 'add', 'value': -2},
                                   {'metric': 'verified_contracts', 'op': 'add', 'value': -9}],
                       'flags': ['unverified-api-db-contract', 'unverified-auth-flow']},
                      {'id': 'skip-unit', 'when': [{'assumption': 'run_unit_tests', 'op': '==', 'value': False}],
                       'effects': [{'metric': 'escaped_defect_probability', 'op': 'add', 'value': .15},
                                   {'metric': 'release_hours', 'op': 'add', 'value': -1}],
                       'flags': ['unverified-units']}],
            'gates': [{'id': 'defect-risk', 'metric': 'escaped_defect_probability', 'op': '<=', 'value': .1,
                       'severity': 'blocker'},
                      {'id': 'contract-coverage', 'metric': 'verified_contracts', 'op': '>=', 'value': 10,
                       'severity': 'blocker'},
                      {'id': 'fits-window', 'metric': 'release_hours', 'op': '<=', 'value': 8, 'severity': 'warning'}],
            'flips': [{'id': 'skip-integration-tests', 'set': {'run_integration_tests': False}}]}


class SkipIntegrationTestsCase(unittest.TestCase):
    def test_skipping_integration_tests_saves_time_but_flips_release_to_no_go(self):
        request = release_model()
        result = sealed(self, r.counterfactual(request), request, 'counterfactual')
        self.assertEqual(result['baseline']['verdict'], 'go')
        flip = result['flips'][0]
        self.assertTrue(flip['verdict_changed'])
        self.assertEqual(flip['verdict'], {'baseline': 'go', 'counterfactual': 'no-go'})
        self.assertEqual(flip['failing_blockers'], ['contract-coverage', 'defect-risk'])
        self.assertEqual(flip['metrics']['release_hours']['delta'], -2)
        self.assertEqual(flip['metrics']['escaped_defect_probability']['counterfactual'], .3)
        self.assertEqual(flip['flags']['raised'], ['unverified-api-db-contract', 'unverified-auth-flow'])
        self.assertEqual(flip['rules_fired']['added'], ['skip-integration'])
        self.assertEqual(result['decision_sensitive_to'], ['skip-integration-tests'])
        self.assertTrue(flip['summary'].startswith('skip-integration-tests: verdict go -> no-go'))

    def test_effect_order_is_independent_of_rule_order(self):
        request = release_model()
        request['flips'] = [{'id': 'skip-both', 'set': {'run_integration_tests': False, 'run_unit_tests': False}}]
        forward = r.counterfactual(request)
        request['rules'].reverse()
        backward = r.counterfactual(request)
        self.assertEqual(forward['flips'], backward['flips'])
        self.assertEqual(forward['flips'][0]['metrics']['escaped_defect_probability']['counterfactual'], .45)

    def test_sqlite_versus_postgres_counterfactual_exposes_budget_and_contention(self):
        request = {'schema_version': 1, 'subject': 'pm-demo-storage',
                   'assumptions': {'storage': 'sqlite', 'expected_peak_writers': 3},
                   'metrics': {'monthly_cost_usd': 0, 'ops_hours_per_month': .5, 'write_contention': 0},
                   'rules': [{'id': 'postgres-hosting', 'when': [{'assumption': 'storage', 'op': '==', 'value': 'postgres'}],
                              'effects': [{'metric': 'monthly_cost_usd', 'op': 'add', 'value': 15},
                                          {'metric': 'ops_hours_per_month', 'op': 'add', 'value': 2.5}], 'flags': []},
                             {'id': 'single-writer-contention',
                              'when': [{'assumption': 'storage', 'op': '==', 'value': 'sqlite'},
                                       {'assumption': 'expected_peak_writers', 'op': '>', 'value': 20}],
                              'effects': [{'metric': 'write_contention', 'op': 'set', 'value': 1}],
                              'flags': ['sqlite-write-lock-contention']}],
                   'gates': [{'id': 'demo-budget', 'metric': 'monthly_cost_usd', 'op': '<=', 'value': 10,
                              'severity': 'blocker'},
                             {'id': 'no-contention', 'metric': 'write_contention', 'op': '==', 'value': 0,
                              'severity': 'blocker'}],
                   'flips': [{'id': 'choose-postgres', 'set': {'storage': 'postgres'}},
                             {'id': 'multi-tenant-growth', 'set': {'expected_peak_writers': 50}}]}
        result = r.counterfactual(request)
        flips = {row['id']: row for row in result['flips']}
        self.assertEqual(flips['choose-postgres']['failing_blockers'], ['demo-budget'])
        self.assertEqual(flips['multi-tenant-growth']['failing_blockers'], ['no-contention'])
        self.assertEqual(flips['multi-tenant-growth']['flags']['raised'], ['sqlite-write-lock-contention'])
        self.assertEqual(result['decision_sensitive_to'], ['choose-postgres', 'multi-tenant-growth'])

    def test_counterfactual_rejects_unknown_conflicting_or_empty_flips(self):
        for change in ['unknown-assumption', 'type-change', 'no-change', 'conflicting-set', 'unknown-metric',
                       'ordering-on-bool']:
            request = release_model()
            if change == 'unknown-assumption':
                request['flips'][0]['set'] = {'deploy_on_friday': True}
            elif change == 'type-change':
                request['flips'][0]['set'] = {'run_integration_tests': 0}
            elif change == 'no-change':
                request['flips'][0]['set'] = {'run_integration_tests': True}
            elif change == 'conflicting-set':
                for value, rule in zip([1, 2], request['rules']):
                    rule['when'] = [{'assumption': 'run_unit_tests', 'op': '==', 'value': True}]
                    rule['effects'] = [{'metric': 'release_hours', 'op': 'set', 'value': value}]
            elif change == 'unknown-metric':
                request['gates'][0]['metric'] = 'happiness'
            else:
                request['rules'][0]['when'][0].update(op='<', value=1)
            with self.subTest(change=change), self.assertRaises(ReasoningError):
                r.counterfactual(request)


# -- case 4: uncertainty when performance evidence is missing -------------------

def api_claims(rows):
    return {'schema_version': 1, 'subject': 'pm-demo-api', 'min_confidence': .7,
            'claims': [{'id': 'p95-latency', 'type': 'requirement', 'criterion': 'performance', 'critical': True,
                        'evidence_kinds': ['benchmark', 'load-test'], 'max_age_seconds': 7 * DAY},
                       {'id': 'crud-correct', 'type': 'requirement', 'criterion': 'quality', 'critical': True,
                        'evidence_kinds': ['test-run'], 'max_age_seconds': DAY},
                       {'id': 'single-region-users', 'type': 'assumption', 'criterion': 'architecture',
                        'critical': False, 'evidence_kinds': ['owner-confirmation'], 'max_age_seconds': 30 * DAY}],
            'evidence': rows}


def ci_run():
    return evidence('ci-run', 'claim', 'crud-correct', 'test-run', confidence=.95, digest='3')


class MissingPerformanceEvidenceCase(unittest.TestCase):
    def test_missing_benchmark_is_flagged_and_blocks_without_silent_defaults(self):
        rows = [ci_run(), evidence('perf-opinion', 'claim', 'p95-latency', 'review', confidence=.5, digest='4')]
        request = api_claims(rows)
        result = sealed(self, r.detect_uncertainty(request, now=NOW), request, 'uncertainty')
        p95 = result['claims']['p95-latency']
        self.assertEqual(p95['status'], 'missing')
        self.assertEqual(p95['flags'], ['missing_evidence', 'wrong_evidence_kind'])
        self.assertEqual(p95['wrong_kind'], ['perf-opinion'])
        self.assertEqual(result['claims']['crud-correct']['status'], 'covered')
        self.assertFalse(result['can_proceed'])
        self.assertEqual(result['uncertainty'], 'high')
        self.assertEqual(result['defaults_applied'], [])
        self.assertEqual(result['critical_evidence_coverage'], .5)
        needed = {row['claim']: row for row in result['needs_evidence']}
        self.assertEqual(sorted(needed), ['p95-latency', 'single-region-users'])
        self.assertEqual(needed['p95-latency']['acceptable_kinds'], ['benchmark', 'load-test'])
        self.assertTrue(needed['p95-latency']['critical'])
        self.assertTrue(r.replay('uncertainty', request, result))

    def test_stale_future_conflicting_inconclusive_and_low_confidence_are_distinct(self):
        cases = {
            'stale': ([evidence('old-bench', 'claim', 'p95-latency', 'benchmark', at=NOW - 8 * DAY)], 'stale_evidence'),
            'future': ([evidence('odd-bench', 'claim', 'p95-latency', 'benchmark', at=NOW + 60)], 'future_dated_evidence'),
            'conflicting': ([evidence('bench-a', 'claim', 'p95-latency', 'benchmark'),
                             evidence('bench-b', 'claim', 'p95-latency', 'load-test', verdict='contradicts')],
                            'conflicting_signals'),
            'inconclusive': ([evidence('noisy', 'claim', 'p95-latency', 'benchmark', verdict='inconclusive')],
                             'inconclusive_evidence'),
            'low': ([evidence('tiny-sample', 'claim', 'p95-latency', 'benchmark', confidence=.4)],
                    'low_confidence_evidence'),
            'contradicted': ([evidence('slow', 'claim', 'p95-latency', 'load-test', verdict='contradicts')],
                             'evidence_contradicts'),
        }
        for name, (rows, flag) in cases.items():
            result = r.detect_uncertainty(api_claims([ci_run()] + rows), now=NOW)
            with self.subTest(name=name):
                self.assertIn(flag, result['claims']['p95-latency']['flags'])
                self.assertFalse(result['can_proceed'])
        result = r.detect_uncertainty(api_claims([ci_run(), cases['contradicted'][0][0]]), now=NOW)
        self.assertEqual(result['contradicted'], ['p95-latency'])
        self.assertNotIn('p95-latency', [row['claim'] for row in result['needs_evidence']])

    def test_fresh_benchmark_covers_the_claim_and_coverage_feeds_strategy_depth(self):
        rows = [ci_run(), evidence('bench', 'claim', 'p95-latency', 'benchmark', confidence=.85)]
        covered = r.detect_uncertainty(api_claims(rows), now=NOW)
        self.assertTrue(covered['can_proceed'])
        self.assertEqual(covered['uncertainty'], 'medium')   # the non-critical assumption is still open
        missing = r.detect_uncertainty(api_claims([ci_run()]), now=NOW)
        depth = {}
        for name, result in [('covered', covered), ('missing', missing)]:
            depth[name] = r.select_strategy({'schema_version': 1, 'task': 'pm-demo-api', 'risk': .6,
                                             'complexity': .4, 'novelty': .3, 'reversibility': .6,
                                             'evidence_coverage': result['critical_evidence_coverage']})
        self.assertEqual(depth['covered']['depth'], 'standard')
        self.assertEqual(depth['missing']['depth'], 'deep')
        self.assertEqual([row['id'] for row in depth['missing']['triggers']], ['weak_evidence'])
        self.assertEqual(depth['missing']['model_steps'], ['independent-review'])


# -- case 5: trade-off sensitivity flip ----------------------------------------

class TradeOffSensitivityCase(unittest.TestCase):
    def test_scalability_weight_is_the_smallest_change_that_flips_the_winner(self):
        result = r.trade_off(storage_trade_off())
        self.assertFalse(result['robust'])
        self.assertEqual(result['most_sensitive'], {'criterion': 'scalability', 'min_change': .063636364,
                                                    'new_winner': 'postgres'})
        rows = {row['criterion']: row for row in result['sensitivity']}
        flip = rows['scalability']['increase']
        self.assertEqual(flip['flip_weight'], .363636364)
        self.assertEqual(flip['new_winner'], 'postgres')
        self.assertIsNone(rows['scalability']['decrease'])
        self.assertEqual(rows['monthly-cost']['decrease']['flip_weight'], .166666667)
        self.assertIsNone(rows['setup-minutes']['decrease'])   # only a boundary tie, never a strict flip
        self.assertAlmostEqual(sum(flip['weights_at_flip'].values()), 1, places=6)

    def test_recomputing_just_past_and_short_of_the_flip_confirms_it(self):
        flip = r.trade_off(storage_trade_off())['sensitivity']
        flip = next(row for row in flip if row['criterion'] == 'scalability')['increase']
        for offset, winner in [(.01, 'postgres'), (-.01, 'sqlite')]:
            request = storage_trade_off()
            target = flip['flip_weight'] + offset
            scale = (1 - target) / (1 - .30)
            for row in request['criteria']:
                row['weight'] = target if row['id'] == 'scalability' else row['weight'] * scale
            correction = 1 - sum(row['weight'] for row in request['criteria'])
            request['criteria'][0]['weight'] += correction
            with self.subTest(offset=offset):
                self.assertEqual(r.trade_off(request)['winner'], winner)

    def test_wide_margin_is_robust_and_three_options_rank_fully(self):
        request = storage_trade_off()
        request['robustness_margin'] = .05
        self.assertTrue(r.trade_off(request)['robust'])
        request['options'].append('duckdb')
        request['values']['duckdb'] = {'monthly-cost': 0, 'ops-effort': .5, 'scalability': 4, 'concurrency': 1,
                                       'setup-minutes': 5}
        result = r.trade_off(request)
        self.assertEqual(result['winner'], 'duckdb')
        self.assertEqual(result['ranking'], ['duckdb', 'sqlite', 'postgres'])

    def test_trade_off_rejects_bad_weights_and_incomplete_matrices(self):
        for change in ['weights', 'missing-cell', 'extra-option', 'direction', 'one-option', 'nan']:
            request = storage_trade_off()
            if change == 'weights':
                request['criteria'][0]['weight'] = .5
            elif change == 'missing-cell':
                del request['values']['postgres']['concurrency']
            elif change == 'extra-option':
                request['values']['mysql'] = dict(request['values']['sqlite'])
            elif change == 'direction':
                request['criteria'][0]['direction'] = 'sideways'
            elif change == 'one-option':
                request['options'] = ['sqlite']
                del request['values']['postgres']
            else:
                request['values']['sqlite']['scalability'] = float('nan')
            with self.subTest(change=change), self.assertRaises(ReasoningError):
                r.trade_off(request)


# -- planning, dependencies, review and routing --------------------------------

def launch_goal():
    def task(identifier, minutes, depends_on=(), risk=.3, confidence=.85):
        return {'id': identifier, 'depends_on': list(depends_on), 'minutes': minutes, 'risk': risk,
                'novelty': .2, 'confidence': confidence}
    return {'schema_version': 1, 'goal': 'pm-demo-launch', 'milestones': [
        {'id': 'm-storage', 'depends_on': [], 'tasks': [task('schema', 30), task('migrations', 20, ['schema'])]},
        {'id': 'm-api', 'depends_on': ['m-storage'],
         'tasks': [task('crud-endpoints', 60), task('auth', 45, risk=.5, confidence=.7),
                   task('api-tests', 30, ['crud-endpoints', 'auth'])]},
        {'id': 'm-ui', 'depends_on': ['m-storage'], 'tasks': [task('board-view', 90, confidence=.75)]},
        {'id': 'm-release', 'depends_on': ['m-api', 'm-ui'], 'tasks': [task('release-checks', 15)]}]}


def plan_base():
    return {'schema_version': 1, 'project': 'pm-demo', 'task': 'launch', 'source_sha256': 'a' * 64,
            'constraints': {'max_minutes': 400, 'max_parallel': 2, 'max_depth': 5, 'max_cost_units': 10,
                            'max_latency_ms': 100, 'min_quality': .7, 'required_checks': ['tests']},
            'alternatives': [{'id': 'sqlite', 'cost_units': 0, 'latency_ms': 5, 'quality': .9,
                              'evidence_ids': ['bench']}],
            'evidence': [{'id': 'bench', 'project': 'pm-demo', 'source_sha256': 'a' * 64, 'at': NOW,
                          'kind': 'benchmark', 'sha256': 'b' * 64, 'confidence': .9}]}


class GoalPlanningAndDependencies(unittest.TestCase):
    def test_goal_milestones_tasks_feed_the_existing_wave_planner(self):
        decomposition = sealed(self, r.decompose(launch_goal()), launch_goal(), 'decompose')
        self.assertEqual(decomposition['milestone_waves'], [['m-storage'], ['m-api', 'm-ui'], ['m-release']])
        nodes = {row['id']: row for row in decomposition['plan_nodes']}
        self.assertEqual(nodes['auth']['depends_on'], ['migrations'])
        self.assertEqual(nodes['release-checks']['depends_on'], ['api-tests', 'board-view'])
        request = {'schema_version': 1, 'decomposition': launch_goal(), 'plan': plan_base()}
        result = sealed(self, r.plan_goal(request, now=NOW), request, 'plan-goal')
        self.assertEqual(result['status'], 'provisional')
        self.assertEqual(result['plan']['waves'], [['schema'], ['migrations'], ['auth', 'board-view'],
                                                   ['crud-endpoints'], ['api-tests'], ['release-checks']])
        self.assertEqual(result['critical_path'], ['schema', 'migrations', 'crud-endpoints', 'api-tests',
                                                   'release-checks'])
        self.assertEqual(result['critical_path_minutes'], 155)
        self.assertEqual(result['waves_by_milestone'][2], {'m-api': ['auth'], 'm-ui': ['board-view']})
        self.assertTrue(r.replay('plan-goal', request, result))

    def test_critical_path_slack_ready_and_blocked_items(self):
        request = {'schema_version': 1, 'items': [
            {'id': 'schema', 'depends_on': [], 'minutes': 30, 'status': 'done'},
            {'id': 'auth', 'depends_on': ['schema'], 'minutes': 45, 'status': 'in_progress'},
            {'id': 'crud', 'depends_on': ['schema'], 'minutes': 60, 'status': 'todo'},
            {'id': 'sso-vendor', 'depends_on': [], 'minutes': 0, 'status': 'blocked'},
            {'id': 'sso', 'depends_on': ['sso-vendor', 'auth'], 'minutes': 20, 'status': 'todo'},
            {'id': 'release', 'depends_on': ['crud', 'sso'], 'minutes': 15, 'status': 'todo'}]}
        result = sealed(self, r.analyze_dependencies(request), request, 'dependencies')
        self.assertEqual(result['critical_path'], ['schema', 'auth', 'sso', 'release'])
        self.assertEqual(result['critical_path_minutes'], 80)
        self.assertEqual(result['slack_minutes']['crud'], 5)
        self.assertEqual(result['ready'], ['crud'])
        self.assertEqual(result['blocked'], {'release': ['sso-vendor'], 'sso': ['sso-vendor'],
                                             'sso-vendor': ['sso-vendor']})
        request['items'][0]['status'] = 'todo'
        self.assertEqual(r.analyze_dependencies(request)['status_conflicts'], ['auth'])

    def test_cyclic_dependencies_are_rejected_with_the_cycle_named(self):
        request = {'schema_version': 1, 'items': [
            {'id': 'a', 'depends_on': ['c'], 'minutes': 1, 'status': 'todo'},
            {'id': 'b', 'depends_on': ['a'], 'minutes': 1, 'status': 'todo'},
            {'id': 'c', 'depends_on': ['b'], 'minutes': 1, 'status': 'todo'}]}
        with self.assertRaisesRegex(ReasoningError, 'a -> c -> b -> a'):
            r.analyze_dependencies(request)
        goal = launch_goal()
        goal['milestones'][0]['depends_on'] = ['m-release']
        with self.assertRaisesRegex(ReasoningError, 'milestone'):
            r.decompose(goal)
        goal = launch_goal()   # a task reaching back into a milestone that depends on its own
        goal['milestones'][0]['tasks'][0]['depends_on'] = ['api-tests']
        with self.assertRaisesRegex(ReasoningError, 'cycle among tasks'):
            r.decompose(goal)

    def test_decomposition_and_goal_planning_reject_malformed_structure(self):
        for change in ['empty-milestone', 'duplicate-id', 'goal-id-reuse', 'unknown-task-dep', 'plan-nodes']:
            goal, base = launch_goal(), plan_base()
            if change == 'empty-milestone':
                goal['milestones'][2]['tasks'] = []
            elif change == 'duplicate-id':
                goal['milestones'][1]['tasks'][0]['id'] = 'schema'
            elif change == 'goal-id-reuse':
                goal['goal'] = 'm-api'
            elif change == 'unknown-task-dep':
                goal['milestones'][1]['tasks'][0]['depends_on'] = ['missing']
            else:
                base['nodes'] = []
            with self.subTest(change=change), self.assertRaises(ReasoningError):
                r.plan_goal({'schema_version': 1, 'decomposition': goal, 'plan': base}, now=NOW)


def demo_facts():
    return {'cyclic_module_dependencies': 0, 'single_points_of_failure': 1, 'max_module_coupling': .4,
            'decision_record': True, 'secrets_in_repo': False, 'auth_required': True, 'auth_implemented': True,
            'dependencies_pinned': True, 'handles_personal_data': True, 'encryption_at_rest': False,
            'threat_model': False, 'failing_tests': 0, 'line_coverage': .72, 'integration_tests': True,
            'static_analysis_clean': True, 'monthly_cost_usd': 0, 'monthly_budget_usd': 10,
            'unapproved_paid_services': 0, 'stateful': True, 'monitoring': True, 'rollback_plan': True,
            'runbook': False}


class MultiPerspectiveReview(unittest.TestCase):
    def request(self, facts):
        return {'schema_version': 1, 'subject': 'pm-demo', 'facts': facts, 'perspectives': list(r.PERSPECTIVES)}

    def test_findings_are_reported_per_perspective_and_missing_facts_need_evidence(self):
        request = self.request(demo_facts())
        result = sealed(self, r.review_perspectives(request), request, 'perspectives')
        verdicts = {name: row['verdict'] for name, row in result['perspectives'].items()}
        self.assertEqual(verdicts, {'architecture': 'concerns', 'security': 'fail', 'quality': 'pass',
                                    'cost': 'pass', 'operability': 'insufficient_evidence'})
        self.assertEqual(result['verdict'], 'fail')
        self.assertFalse(result['approved'])
        self.assertEqual([row['check'] for row in result['blocking_findings']], ['sec-personal-data'])
        self.assertEqual(result['perspectives']['operability']['needs_evidence'],
                         [{'check': 'ops-backups', 'facts': ['backups']}])
        self.assertEqual(result['model_review'], 'not-performed')

    def test_resolving_findings_and_evidence_approves_with_low_concerns(self):
        facts = dict(demo_facts(), encryption_at_rest=True, threat_model=True, backups=True,
                     single_points_of_failure=0, runbook=True, monthly_cost_usd=9)
        result = r.review_perspectives(self.request(facts))
        self.assertTrue(result['approved'])
        self.assertEqual(result['verdict'], 'concerns')
        self.assertEqual(result['perspectives']['cost']['findings'][0]['check'], 'cost-budget')
        self.assertEqual(result['perspectives']['cost']['findings'][0]['severity'], 'low')

    def test_conditional_facts_are_only_required_when_they_apply(self):
        facts = dict(demo_facts(), auth_required=False, stateful=False)
        del facts['auth_implemented']
        result = r.review_perspectives(self.request(facts))
        self.assertEqual(result['perspectives']['operability']['needs_evidence'], [])
        self.assertEqual(result['perspectives']['security']['needs_evidence'], [])
        facts = demo_facts()
        del facts['auth_implemented']
        self.assertEqual(r.review_perspectives(self.request(facts))['perspectives']['security']['needs_evidence'],
                         [{'check': 'sec-auth', 'facts': ['auth_implemented']}])

    def test_unknown_or_mistyped_facts_and_perspectives_are_refused(self):
        for facts, perspectives in [(dict(demo_facts(), backup=True), list(r.PERSPECTIVES)),
                                    (dict(demo_facts(), failing_tests=True), list(r.PERSPECTIVES)),
                                    (dict(demo_facts(), line_coverage=1.5), list(r.PERSPECTIVES)),
                                    (demo_facts(), ['vibes']), (demo_facts(), [])]:
            request = {'schema_version': 1, 'subject': 'pm-demo', 'facts': facts, 'perspectives': perspectives}
            with self.subTest(perspectives=perspectives), self.assertRaises(ReasoningError):
                r.review_perspectives(request)


class DecisionValidationNegatives(unittest.TestCase):
    def test_decision_without_evidence_is_rejected(self):
        result = r.validate_decision(storage_decision([]), now=NOW)
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['rejected_because'], ['within-budget: missing', 'write-throughput: missing'])
        self.assertEqual([row['claim'] for row in result['missing_evidence']], ['within-budget', 'write-throughput'])

    def test_stale_weak_or_contradicting_critical_evidence_rejects(self):
        good = evidence('pricing-sheet', 'criterion', 'within-budget', 'pricing')
        for name, row, reason in [
                ('stale', evidence('old-load', 'criterion', 'write-throughput', 'load-test', at=NOW - 8 * DAY), 'stale'),
                ('weak', evidence('tiny-load', 'criterion', 'write-throughput', 'load-test', confidence=.3), 'low_confidence'),
                ('contradicts', evidence('slow-load', 'criterion', 'write-throughput', 'load-test',
                                         verdict='contradicts'), 'contradicted'),
                ('wrong-kind', evidence('opinion', 'criterion', 'write-throughput', 'review'), 'missing')]:
            result = r.validate_decision(storage_decision([good, row]), now=NOW)
            with self.subTest(name=name):
                self.assertEqual(result['status'], 'rejected')
                self.assertEqual(result['rejected_because'], [f'write-throughput: {reason}'])

    def test_decisions_need_a_critical_criterion_and_bound_evidence(self):
        request = storage_decision([])
        for row in request['criteria']:
            row['critical'] = False
        with self.assertRaises(ReasoningError):
            r.validate_decision(request, now=NOW)
        request = storage_decision([evidence('stray', 'criterion', 'unknown-criterion', 'pricing')])
        with self.assertRaises(ReasoningError):
            r.validate_decision(request, now=NOW)
        request = storage_decision([])
        request['decision']['basis_sha256'] = 'not-a-digest'
        with self.assertRaises(ReasoningError):
            r.validate_decision(request, now=NOW)


def model_registry():
    return {'schema_version': 1, 'evidence_max_age_seconds': 3600, 'models': [
        {'id': 'synthetic-local', 'provider': 'local', 'status': 'PROJECT_VERIFIED',
         'model_id': 'synthetic-snapshot-20260101', 'revision': 'a' * 40,
         'reviews': {'license': 'approved', 'security': 'approved', 'commercial': 'approved'},
         'tasks': ['review'], 'max_complexity': 5, 'context_tokens': 8192, 'runtime_sha256': 'b' * 64,
         'pricing': {'input_per_million_usd': '0', 'output_per_million_usd': '0', 'verified_at': NOW}}]}


def routing_request(evidence_value='default'):
    receipt = {'revision': 'a' * 40, 'operational': True, 'tested': True, 'project_verified': True, 'at': NOW,
               'receipt_sha256': 'c' * 64, 'quality': .9, 'latency_ms': 800, 'remaining_requests': 10,
               'remaining_tokens': 100000, 'permissions': ['source:read'], 'privacy': ['internal'],
               'runtime_sha256': 'b' * 64, 'cost_approved': True, 'free_allowance_verified': False}
    return {'schema_version': 1, 'step': 'independent-review', 'registry': model_registry(),
            'routing': {'project': 'pm-demo', 'task': 'review', 'complexity': 4, 'input_tokens': 2000,
                        'output_tokens': 500, 'privacy': 'internal', 'permissions': ['source:read'],
                        'max_cost_usd': '0', 'min_quality': .8, 'max_latency_ms': 5000},
            'evidence': ({'schema_version': 1, 'project': 'pm-demo', 'models': {'synthetic-local': receipt}}
                         if evidence_value == 'default' else evidence_value)}


class ModelRoutingHook(unittest.TestCase):
    def test_model_step_returns_the_routing_decision_without_calling_a_model(self):
        request = routing_request()
        with mock.patch('socket.socket', side_effect=AssertionError('no network')):
            result = r.route_model(request, now=NOW)
        sealed(self, result, request, 'route-model')
        self.assertTrue(result['requires_model'])
        self.assertEqual(result['decision'], 'eligible')
        self.assertEqual(result['routing']['selected']['id'], 'synthetic-local')
        self.assertFalse(result['model_called'])
        self.assertEqual(result['invocation'], 'not-performed')
        self.assertEqual(result['routing']['provider_calls'], 0)
        self.assertFalse(result['routing']['quota_reserved'])
        self.assertTrue(r.replay('route-model', request, result))

    def test_without_evidence_the_step_is_blocked_and_says_so(self):
        result = r.route_model(routing_request(None), now=NOW)
        self.assertEqual(result['decision'], 'blocked')
        self.assertIsNone(result['routing']['selected'])
        self.assertIn('no model is eligible', result['reason'])

    def test_hosted_model_needs_attested_credential_names_never_values(self):
        request = routing_request()
        model = request['registry']['models'][0]
        model.update(provider='anthropic', credential_env='SYNTHETIC_PROVIDER_KEY')
        request['evidence']['models']['synthetic-local']['free_allowance_verified'] = True
        with mock.patch.dict('os.environ', {'SYNTHETIC_PROVIDER_KEY': 'synthetic-value'}):
            blocked = r.route_model(request, now=NOW)
        self.assertEqual(blocked['decision'], 'blocked')   # process environment is never read
        self.assertIn('credential_unavailable', blocked['routing']['rejected']['synthetic-local'])
        allowed = r.route_model(request, credentials_present=['SYNTHETIC_PROVIDER_KEY'], now=NOW)
        self.assertEqual(allowed['decision'], 'eligible')
        self.assertEqual(allowed['credentials_considered'], ['SYNTHETIC_PROVIDER_KEY'])
        self.assertNotIn('synthetic-value', json.dumps(allowed))

    def test_deterministic_steps_are_not_routed_and_bad_steps_are_refused(self):
        request = {'schema_version': 1, 'step': 'trade-off', 'registry': None, 'routing': None, 'evidence': None}
        result = r.route_model(request)
        self.assertFalse(result['requires_model'])
        self.assertIsNone(result['routing'])
        for step, registry in [('trade-off', model_registry()), ('telepathy', None), ('route-model', None)]:
            bad = {'schema_version': 1, 'step': step, 'registry': registry, 'routing': None, 'evidence': None}
            with self.subTest(step=step), self.assertRaises(ReasoningError):
                r.route_model(bad)
        for credentials in ['NAME', ['lower_case'], ['sk-' + 'a' * 30]]:
            with self.subTest(credentials=credentials), self.assertRaises(ReasoningError):
                r.route_model(routing_request(), credentials_present=credentials, now=NOW)
        broken = routing_request()
        broken['routing']['api_key'] = 'synthetic'
        with self.assertRaises(ReasoningError):
            r.route_model(broken, now=NOW)


class StrategyDepth(unittest.TestCase):
    def strategy(self, **values):
        request = {'schema_version': 1, 'task': 'change', 'risk': .1, 'complexity': .1, 'novelty': .1,
                   'reversibility': .9, 'evidence_coverage': .9}
        request.update(values)
        return r.select_strategy(request)

    def test_quick_standard_and_deep_follow_the_weighted_score(self):
        self.assertEqual(self.strategy()['depth'], 'quick')
        self.assertEqual(self.strategy()['plan_max_depth'], 2)
        self.assertEqual(self.strategy(risk=.5, complexity=.5, novelty=.5, reversibility=.5)['depth'], 'standard')
        deep = self.strategy(risk=.7, complexity=.9, novelty=.7, reversibility=.2, evidence_coverage=.6)
        self.assertEqual(deep['depth'], 'deep')
        self.assertEqual(deep['score_depth'], 'deep')
        self.assertEqual(deep['plan_max_depth'], 5)

    def test_hard_triggers_only_escalate_and_are_named_in_the_reason(self):
        risky = self.strategy(risk=.85, complexity=0, novelty=0, reversibility=1, evidence_coverage=1)
        self.assertEqual((risky['score_depth'], risky['depth']), ('quick', 'deep'))
        self.assertIn('escalated by high_risk (risk 0.85 >= 0.80)', risky['reason'])
        irreversible = self.strategy(risk=.5, reversibility=.1)
        self.assertEqual(irreversible['depth'], 'deep')
        self.assertIn('irreversible_and_risky', [row['id'] for row in irreversible['triggers']])
        self.assertEqual(self.strategy(novelty=.9)['depth'], 'standard')
        self.assertEqual(self.strategy(evidence_coverage=.2)['depth'], 'standard')

    def test_strategy_rejects_out_of_range_and_unknown_fields(self):
        for change in [{'risk': 1.5}, {'risk': True}, {'novelty': float('nan')}, {'extra': 1},
                       {'schema_version': 2}, {'task': 'Has Spaces'}]:
            request = {'schema_version': 1, 'task': 'change', 'risk': .1, 'complexity': .1, 'novelty': .1,
                       'reversibility': .9, 'evidence_coverage': .9}
            request.update(change)
            with self.subTest(change=change), self.assertRaises(ReasoningError):
                r.select_strategy(request)


class MalformedInputs(unittest.TestCase):
    def test_every_operation_refuses_non_objects_and_unknown_schema(self):
        for action in r.ENGINE_RECORD['actions']:
            if action in ('review', 'root-causes'):
                continue
            for payload in [None, [], 'text', {'schema_version': 2}]:
                with self.subTest(action=action, payload=payload), self.assertRaises(ReasoningError):
                    r.engine(action, payload, {'now': NOW})

    def test_constraint_operands_and_types_are_checked(self):
        for change in ['unknown-op', 'ordering-on-text', 'type-mismatch', 'no-hard', 'zero-weight',
                       'duplicate-constraint', 'nested-attribute']:
            request = storage_options()
            if change == 'unknown-op':
                request['hard'][0]['op'] = '~='
            elif change == 'ordering-on-text':
                request['hard'][0]['value'] = 'cheap'
            elif change == 'type-mismatch':
                request['soft'][2]['value'] = 1
            elif change == 'no-hard':
                request['hard'] = []
            elif change == 'zero-weight':
                request['soft'][0]['weight'] = 0
            elif change == 'duplicate-constraint':
                request['soft'][0]['id'] = 'demo-budget'
            else:
                request['options'][0]['attributes']['monthly_cost_usd'] = {'value': 0}
            with self.subTest(change=change), self.assertRaises(ReasoningError):
                r.evaluate_constraints(request)

    def test_unknown_evidence_reference_in_uncertainty_is_not_ignored(self):
        request = api_claims([evidence('orphan', 'claim', 'nobody', 'benchmark')])
        with self.assertRaises(ReasoningError):
            r.detect_uncertainty(request, now=NOW)
        request = api_claims([])
        request['claims'][0]['evidence_kinds'] = []
        with self.assertRaises(ReasoningError):
            r.detect_uncertainty(request, now=NOW)


class EveryOperation(unittest.TestCase):
    def payloads(self):
        return [('strategy', {'schema_version': 1, 'task': 'pm-demo-storage', 'risk': .3, 'complexity': .3,
                              'novelty': .2, 'reversibility': .5, 'evidence_coverage': .8}),
                ('decompose', launch_goal()),
                ('plan-goal', {'schema_version': 1, 'decomposition': launch_goal(), 'plan': plan_base()}),
                ('constraints', storage_options()),
                ('dependencies', {'schema_version': 1, 'items': [
                    {'id': 'a', 'depends_on': [], 'minutes': 3, 'status': 'todo'},
                    {'id': 'b', 'depends_on': ['a'], 'minutes': 2, 'status': 'todo'}]}),
                ('rca', failing_build()), ('counterfactual', release_model()),
                ('uncertainty', api_claims([ci_run()])), ('perspectives', {
                    'schema_version': 1, 'subject': 'pm-demo', 'facts': demo_facts(),
                    'perspectives': list(r.PERSPECTIVES)}),
                ('validate-decision', storage_decision([])), ('trade-off', storage_trade_off()),
                ('route-model', routing_request())]

    def test_each_operation_is_sealed_replayable_offline_and_leaves_input_untouched(self):
        covered = set()
        for action, payload in self.payloads():
            original = copy.deepcopy(payload)
            with self.subTest(action=action), mock.patch('socket.socket', side_effect=AssertionError('no network')):
                one = r.engine(action, payload, {'now': NOW})
                two = r.engine(action, copy.deepcopy(payload), {'now': NOW})
                self.assertEqual(one, two)
                self.assertEqual(payload, original)
                sealed(self, one, payload, action)
                self.assertTrue(r.replay(action, payload, one))
                covered.add(action)
        self.assertEqual(covered | {'plan', 'review', 'root-causes'}, set(r.ENGINE_RECORD['actions']))

    def test_payload_that_is_not_canonical_json_is_refused(self):
        request = storage_trade_off()
        request['decision'] = {'not', 'json'}
        with self.assertRaises(ReasoningError):
            r.trade_off(request)


if __name__ == '__main__':
    unittest.main()
