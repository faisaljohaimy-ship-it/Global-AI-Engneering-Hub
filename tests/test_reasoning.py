"""Synthetic offline planning fixtures; no model/provider readiness claims."""
import copy
import math
import unittest
from unittest import mock

from engineering_os.orchestration import sha
from engineering_os.reasoning import ReasoningError, plan, review_decision, root_causes

NOW = 1800000000
SOURCE = 'a' * 64


def request():
    return {'schema_version': 1, 'project': 'synthetic-project', 'task': 'feature',
            'source_sha256': SOURCE,
            'nodes': [{'id': 'design', 'parent': None, 'depends_on': [], 'minutes': 5,
                       'risk': .2, 'novelty': .1, 'confidence': .9},
                      {'id': 'build', 'parent': 'design', 'depends_on': [], 'minutes': 10,
                       'risk': .4, 'novelty': .2, 'confidence': .7},
                      {'id': 'verify', 'parent': None, 'depends_on': ['build'], 'minutes': 5,
                       'risk': .1, 'novelty': .1, 'confidence': .9}],
            'constraints': {'max_minutes': 30, 'max_parallel': 2, 'max_depth': 5,
                            'max_cost_units': 10, 'max_latency_ms': 100,
                            'min_quality': .7, 'required_checks': ['tests', 'security']},
            'alternatives': [{'id': 'modular', 'cost_units': 1, 'latency_ms': 10,
                              'quality': .95, 'evidence_ids': ['benchmark']},
                             {'id': 'distributed', 'cost_units': 20, 'latency_ms': 20,
                              'quality': .99, 'evidence_ids': ['benchmark']}],
            'evidence': [{'id': 'benchmark', 'project': 'synthetic-project',
                          'source_sha256': SOURCE, 'at': NOW, 'kind': 'benchmark',
                          'sha256': 'b' * 64, 'confidence': .95}]}


def reviews(planned):
    return [{'reviewer': 'reviewer-' + str(i), 'model': 'synthetic-model-' + str(i),
             'revision': str(i) * 40, 'decision': 'approved',
             'plan_sha256': planned['plan_sha256'], 'source_sha256': SOURCE,
             'evidence_sha256': str(i) * 64, 'at': NOW} for i in [1, 2]]


def verification():
    return [{'id': name, 'status': 'passed', 'source_sha256': SOURCE,
             'at': NOW, 'sha256': str(i) * 64}
            for i, name in enumerate(['security', 'tests'], 3)]


class ReasoningTests(unittest.TestCase):
    def setUp(self):
        self.request = request()

    def planned(self):
        return plan(self.request, now=NOW)

    def test_plan_is_deterministic_without_network_or_mutation(self):
        original = copy.deepcopy(self.request)
        with mock.patch('socket.socket', side_effect=AssertionError('no network')):
            one, two = self.planned(), self.planned()
        self.assertEqual(one, two)
        self.assertEqual(self.request, original)
        self.assertEqual(one['provider_calls'], 0)
        self.assertEqual(one['executed_tasks'], 0)
        self.assertEqual(one['status'], 'provisional')
        self.assertEqual(one['selected'], 'modular')

    def test_parent_and_dependency_edges_drive_hierarchical_schedule(self):
        result = self.planned()
        self.assertEqual(result['waves'], [['design'], ['build'], ['verify']])
        self.assertEqual(result['hierarchy_levels'], {'build': 2, 'design': 1, 'verify': 1})
        self.assertEqual(result['elapsed_minutes'], 20)
        self.assertEqual(result['uncertain_nodes'], ['build'])
        self.assertEqual(result['dependency_edges']['build'], ['design'])

    def test_capacity_bounds_wave_schedule_and_elapsed_budget(self):
        for node in self.request['nodes']:
            node.update(parent=None, depends_on=[])
        self.request['constraints']['max_parallel'] = 2
        result = self.planned()
        self.assertEqual(result['waves'], [['build', 'design'], ['verify']])
        self.assertEqual(result['elapsed_minutes'], 15)
        self.request['constraints']['max_minutes'] = 14
        self.assertIn('elapsed_minutes_budget', self.planned()['blockers'])
        self.assertIsNone(self.planned()['selected'])

    def test_adaptive_depth_rises_for_risk_novelty_and_uncertainty(self):
        simple = self.planned()['complexity']
        for node in self.request['nodes']:
            node.update(risk=1, novelty=1, confidence=0)
        complex_plan = self.planned()
        self.assertGreater(complex_plan['complexity'], simple)
        self.request['constraints']['max_depth'] = 1
        result = self.planned()
        self.assertEqual(result['reasoning_depth'], 1)
        self.assertIn('reasoning_depth_budget', result['blockers'])

    def test_counterfactuals_report_exact_constraint_failure(self):
        result = self.planned()
        alternative = result['counterfactuals'][0]
        self.assertEqual(alternative['alternative'], 'distributed')
        self.assertEqual(alternative['constraints_to_resolve'], ['cost_units_budget'])
        self.request['constraints']['max_cost_units'] = 25
        result = self.planned()
        self.assertEqual(result['alternatives'][1]['rejected'], [])

    def test_evidence_adjusted_quality_can_block_both_alternatives(self):
        self.request['evidence'][0]['confidence'] = .2
        result = self.planned()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('no_evidenced_feasible_alternative', result['blockers'])
        self.assertTrue(all('evidence_adjusted_quality_floor' in row['rejected'] for row in result['alternatives']))

    def test_evidence_source_project_and_time_do_not_cross_boundaries(self):
        for field, value, reason in [('project', 'other', 'project_mismatch'),
                                      ('source_sha256', 'c' * 64, 'source_mismatch'),
                                      ('at', NOW - 86401, 'stale_or_future'),
                                      ('at', NOW + 1, 'stale_or_future')]:
            self.request = request()
            self.request['evidence'][0][field] = value
            with self.subTest(field=field, value=value):
                result = self.planned()
                self.assertEqual(result['status'], 'blocked')
                self.assertIn(reason, result['evidence_rejected']['benchmark'])

    def test_unknown_evidence_and_dependency_are_not_silently_ignored(self):
        self.request['alternatives'][0]['evidence_ids'] = ['missing']
        with self.assertRaises(ReasoningError):
            self.planned()
        self.request = request()
        self.request['nodes'][1]['depends_on'] = ['missing']
        with self.assertRaises(ReasoningError):
            self.planned()

    def test_cycles_including_parent_cycles_fail_before_planning(self):
        self.request['nodes'][0]['depends_on'] = ['verify']
        with self.assertRaises(ReasoningError):
            self.planned()
        self.request = request()
        self.request['nodes'][0]['parent'] = 'build'
        with self.assertRaises(ReasoningError):
            self.planned()

    def test_missing_or_unknown_fields_cannot_weaken_constraints(self):
        for field in list(self.request['constraints']):
            changed = request()
            changed['constraints'].pop(field)
            with self.subTest(field=field), self.assertRaises(ReasoningError):
                plan(changed, now=NOW)
        self.request['api_key'] = 'not-accepted'
        with self.assertRaises(ReasoningError):
            self.planned()

    def test_required_checks_cannot_be_empty(self):
        self.request['constraints']['required_checks'] = []
        with self.assertRaises(ReasoningError):
            self.planned()

    def test_numeric_and_list_bounds_reject_nonfinite_bool_and_duplicates(self):
        for value in [True, float('nan'), float('inf'), -1, '1']:
            self.request = request()
            self.request['nodes'][0]['risk'] = value
            with self.subTest(value=value), self.assertRaises(ReasoningError):
                self.planned()
        self.request = request()
        self.request['nodes'].append(copy.deepcopy(self.request['nodes'][0]))
        with self.assertRaises(ReasoningError):
            self.planned()
        self.request = request()
        self.request['nodes'][1]['depends_on'] = ['design', 'design']
        with self.assertRaises(ReasoningError):
            self.planned()
        self.request = request()
        self.request['constraints']['max_parallel'] = 129
        with self.assertRaises(ReasoningError):
            self.planned()

    def test_raw_freeform_and_secret_shaped_identifiers_are_refused(self):
        for value in ['customer@example.test', 'a\nline', 'sk-' + 'a' * 30]:
            self.request = request()
            self.request['project'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.planned()

    def test_two_independent_reviews_and_all_checks_allow_metadata_acceptance(self):
        p = self.planned()
        original = copy.deepcopy(p)
        result = review_decision(p, reviews(p), verification(), now=NOW)
        self.assertEqual(result['decision'], 'accepted')
        self.assertEqual(result['provider_calls'], 0)
        self.assertEqual(p, original)

    def test_no_reviews_or_missing_required_check_blocks(self):
        p = self.planned()
        result = review_decision(p, [], [], now=NOW)
        self.assertIn('insufficient_distinct_model_reviews', result['blockers'])
        self.assertIn('missing_required_verification', result['blockers'])
        result = review_decision(p, reviews(p), verification()[:1], now=NOW)
        self.assertEqual(result['decision'], 'blocked')

    def test_duplicate_models_or_reviewer_cannot_count_twice(self):
        p = self.planned()
        for field in ['model', 'reviewer']:
            r = reviews(p)
            r[1][field] = r[0][field]
            with self.subTest(field=field), self.assertRaises(ReasoningError):
                review_decision(p, r, verification(), now=NOW)

    def test_unpinned_model_review_is_refused(self):
        p = self.planned()
        r = reviews(p)
        r[0]['revision'] = 'latest'
        with self.assertRaises(ReasoningError):
            review_decision(p, r, verification(), now=NOW)

    def test_review_rejection_and_wrong_plan_or_source_block(self):
        p = self.planned()
        for field, value in [('decision', 'rejected'), ('plan_sha256', 'c' * 64),
                             ('source_sha256', 'c' * 64), ('at', NOW + 1), ('at', NOW - 1)]:
            r = reviews(p)
            r[0][field] = value
            with self.subTest(field=field):
                self.assertEqual(review_decision(p, r, verification(), now=NOW)['decision'], 'blocked')

    def test_changed_expired_and_infeasible_plans_do_not_pass_gate(self):
        p = self.planned()
        p['selected'] = 'distributed'
        with self.assertRaises(ReasoningError):
            review_decision(p, reviews(p), verification(), now=NOW)
        p = self.planned()
        self.assertIn('plan_expired', review_decision(p, reviews(p), verification(), now=NOW + 86401)['blockers'])
        self.request['constraints']['max_minutes'] = 1
        p = self.planned()
        self.assertIn('plan_not_provisional', review_decision(p, reviews(p), verification(), now=NOW)['blockers'])

    def test_rehashed_plan_cannot_relax_checks_models_or_selection(self):
        for change in ['checks', 'models', 'selection', 'blockers']:
            p = self.planned()
            if change == 'checks':
                p['review_requirements']['required_checks'] = []
            elif change == 'models':
                p['review_requirements']['distinct_models'] = 0
            elif change == 'selection':
                p['selected'] = 'distributed'
            else:
                p['blockers'] = ['invented-blocker']
            p['plan_sha256'] = sha({key: value for key, value in p.items() if key != 'plan_sha256'})
            with self.subTest(change=change), self.assertRaises(ReasoningError):
                review_decision(p, reviews(p), verification(), now=NOW)

    def test_failed_unbound_or_old_verification_blocks(self):
        p = self.planned()
        for field, value in [('status', 'failed'), ('source_sha256', 'c' * 64), ('at', NOW - 1), ('at', NOW + 1)]:
            v = verification()
            v[0][field] = value
            with self.subTest(field=field):
                self.assertEqual(review_decision(p, reviews(p), v, now=NOW)['decision'], 'blocked')
        v = verification()
        v.append(copy.deepcopy(v[0]))
        with self.assertRaises(ReasoningError):
            review_decision(p, reviews(p), v, now=NOW)

    def test_root_analysis_finds_upstream_observed_failure_and_uncertainty(self):
        edges = {'storage': [], 'api': ['storage'], 'ui': ['api'], 'unknown': []}
        observations = [{'id': key, 'status': 'failed', 'evidence_sha256': SOURCE}
                        for key in ['storage', 'api', 'ui']]
        result = root_causes(observations, edges)
        self.assertEqual(result['candidate_roots'], ['storage'])
        self.assertEqual(result['affected'], {'storage': ['api', 'ui']})
        self.assertEqual(result['uncertain_nodes'], ['unknown'])
        self.assertFalse(result['causality_proven'])

    def test_root_analysis_refuses_cycles_and_unbound_observations(self):
        with self.assertRaises(ReasoningError):
            root_causes([], {'a': ['b'], 'b': ['a']})
        with self.assertRaises(ReasoningError):
            root_causes([{'id': 'missing', 'status': 'failed', 'evidence_sha256': SOURCE}], {'a': []})
        with self.assertRaises(ReasoningError):
            root_causes([], {'a': ['missing']})


if __name__ == '__main__':
    unittest.main()
