"""Generated artifact/evaluator fixtures; these tests do not build a real product."""
import copy
import hashlib
import json
import os
import pathlib
import tempfile
import unittest

from engineering_os.factory import (FactoryError, CONTRACTS, evaluate_factory,
                                    plan_factory, validate_stage)
from engineering_os.orchestration import sha


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.request = {'schema_version': 1, 'project': 'example',
                        'source_revision': 'a' * 40,
                        'requirements': [{'id': 'access', 'summary': 'An isolated generated example',
                                          'acceptance': ['authorized', 'denied']}],
                        'targets': ['web', 'backend', 'mobile', 'database', 'api', 'ai']}
        self.plan = plan_factory(self.request)

    def write(self, path, document):
        raw = json.dumps(document, sort_keys=True).encode()
        (self.root / path).write_bytes(raw)
        return {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}

    def fixtures(self, plan=None):
        plan = self.plan if plan is None else plan
        receipts = []
        dependencies = {}
        for stage in plan['stages']:
            traces = {row['id']: row['acceptance'] for row in plan['request']['requirements']}
            document = {'schema_version': 1, 'project': plan['request']['project'],
                        'source_revision': plan['request']['source_revision'],
                        'kind': stage['artifact_kind'], 'traces': traces,
                        'content': {field: ['synthetic-example'] for field in stage['required_fields']}}
            artifact = self.write(stage['id'] + '.json', document)
            checks = []
            for check in stage['required_checks']:
                proof = {'schema_version': 1, 'project': plan['request']['project'],
                         'source_revision': plan['request']['source_revision'],
                         'plan_sha256': plan['plan_sha256'], 'stage': stage['id'], 'check': check,
                         'status': 'passed', 'artifact_sha256': artifact['sha256'], 'acceptance': traces}
                checks.append({'id': check, 'status': 'passed',
                               'evidence': self.write(stage['id'] + '-' + check + '.json', proof)})
            receipt = {'schema_version': 1, 'project': plan['request']['project'],
                       'source_revision': plan['request']['source_revision'],
                       'plan_sha256': plan['plan_sha256'], 'stage': stage['id'],
                       'dependencies': {key: dependencies[key] for key in stage['depends_on']},
                       'artifact': artifact, 'checks': checks, 'reviewer': 'fixture-evaluator'}
            dependencies[stage['id']] = sha(receipt)
            receipts.append(receipt)
        return receipts

    def evaluate(self, receipts):
        return evaluate_factory(self.plan, receipts, artifact_root=self.root)

    def test_plan_covers_every_requested_engineering_stage_and_never_deploys(self):
        self.assertEqual({stage['id'] for stage in self.plan['stages']}, set(CONTRACTS))
        seen = set()
        for stage in self.plan['stages']:
            self.assertTrue(set(stage['depends_on']) <= seen)
            self.assertTrue(stage['required_fields'])
            self.assertTrue(stage['required_checks'])
            seen.add(stage['id'])
        self.assertFalse(self.plan['deployment_authorized'])
        self.assertEqual(self.plan['provider_calls'], 0)

    def test_deterministic_plan_and_minimum_target(self):
        request = copy.deepcopy(self.request)
        request['targets'].reverse()
        self.assertEqual(self.plan, plan_factory(request))
        request['targets'] = ['web']
        stages = {stage['id'] for stage in plan_factory(request)['stages']}
        self.assertEqual(stages, {'requirements', 'architecture', 'frontend', 'testing',
                                  'security', 'documentation', 'release'})

    def test_complete_generated_workflow_has_bound_artifacts_and_checks(self):
        receipts = self.fixtures()
        result = self.evaluate(list(reversed(receipts)))
        self.assertTrue(result['delivery_review_ready'])
        self.assertEqual(result['verified_count'], 12)
        self.assertFalse(result['deployment_authorized'])
        self.assertEqual(result['provider_calls'], 0)
        self.assertEqual(validate_stage(self.plan, 'release', receipts,
                                       artifact_root=self.root)['status'], 'verified')

    def test_empty_workflow_only_requirements_ready(self):
        result = self.evaluate([])
        self.assertEqual(result['ready'], ['requirements'])
        self.assertEqual(result['verified_count'], 0)
        self.assertFalse(result['delivery_review_ready'])

    def test_missing_predecessor_blocks_evidenced_stage(self):
        result = self.evaluate(self.fixtures()[1:])
        self.assertEqual(result['verified_count'], 0)
        self.assertEqual(result['stages'][1]['reason'], 'dependencies_unverified')

    def test_changed_artifact_withdraws_all_downstream_verification(self):
        receipts = self.fixtures()
        (self.root / 'requirements.json').write_text('{"changed":true}')
        result = self.evaluate(receipts)
        self.assertEqual(result['verified_count'], 0)
        self.assertTrue(all(stage['status'] == 'blocked' for stage in result['stages']))

    def test_wrong_project_source_or_plan_never_advances(self):
        for key, value in [('project', 'another'), ('source_revision', 'b' * 40),
                           ('plan_sha256', 'c' * 64)]:
            with self.subTest(key=key):
                receipts = self.fixtures()
                receipts[0][key] = value
                self.assertEqual(self.evaluate(receipts)['verified_count'], 0)

    def test_stale_dependency_hash_blocks_reused_output(self):
        receipts = self.fixtures()
        receipts[1]['dependencies']['requirements'] = 'c' * 64
        result = self.evaluate(receipts)
        self.assertEqual(result['verified_count'], 1)
        self.assertEqual(result['stages'][1]['status'], 'blocked')

    def test_failed_or_missing_mandatory_check_blocks(self):
        for change in ['failed', 'missing', 'duplicate']:
            with self.subTest(change=change):
                receipts = self.fixtures()
                if change == 'failed':
                    receipts[0]['checks'][0]['status'] = 'failed'
                elif change == 'missing':
                    receipts[0]['checks'] = []
                else:
                    receipts[0]['checks'].append(copy.deepcopy(receipts[0]['checks'][0]))
                self.assertEqual(self.evaluate(receipts)['verified_count'], 0)

    def test_check_report_bound_to_artifact_and_acceptance(self):
        for key, value in [('status', 'failed'), ('artifact_sha256', 'b' * 64),
                           ('acceptance', {}), ('stage', 'security')]:
            with self.subTest(key=key):
                receipts = self.fixtures()
                reference = receipts[0]['checks'][0]['evidence']
                proof = json.loads((self.root / reference['path']).read_text())
                proof[key] = value
                receipts[0]['checks'][0]['evidence'] = self.write(reference['path'], proof)
                self.assertEqual(self.evaluate(receipts)['verified_count'], 0)

    def test_stage_document_needs_trace_and_real_deliverable_fields(self):
        for key, value in [('traces', {}), ('content', {'requirements': [], 'data_boundaries': []}),
                           ('kind', 'wrong')]:
            with self.subTest(key=key):
                receipts = self.fixtures()
                reference = receipts[0]['artifact']
                document = json.loads((self.root / reference['path']).read_text())
                document[key] = value
                receipts[0]['artifact'] = self.write(reference['path'], document)
                self.assertEqual(self.evaluate(receipts)['verified_count'], 0)

    def test_traversal_absolute_and_symlink_artifact_paths_rejected(self):
        receipts = self.fixtures()
        for path in ['../requirements.json', '/etc/passwd', './requirements.json',
                     'dir//file.json', '.git/config', 'dir\\file.json']:
            with self.subTest(path=path):
                modified = copy.deepcopy(receipts)
                modified[0]['artifact']['path'] = path
                self.assertEqual(self.evaluate(modified)['verified_count'], 0)
        os.symlink(self.root / 'requirements.json', self.root / 'linked.json')
        receipts[0]['artifact']['path'] = 'linked.json'
        self.assertEqual(self.evaluate(receipts)['verified_count'], 0)

    def test_missing_invalid_duplicate_json_and_oversized_bytes_rejected(self):
        for raw in [b'', b'bad', b'{"a":1,"a":2}', b' ' * (2 * 1024 * 1024 + 1)]:
            with self.subTest(size=len(raw)):
                receipts = self.fixtures()
                path = self.root / receipts[0]['artifact']['path']
                path.write_bytes(raw)
                receipts[0]['artifact']['sha256'] = hashlib.sha256(raw).hexdigest()
                self.assertEqual(self.evaluate(receipts)['verified_count'], 0)
        path.unlink()
        self.assertEqual(self.evaluate(receipts)['verified_count'], 0)

    def test_unknown_duplicate_receipts_and_mutated_plan_rejected(self):
        receipts = self.fixtures()
        with self.assertRaises(FactoryError):
            self.evaluate(receipts + [receipts[0]])
        receipts[0]['stage'] = 'unknown'
        with self.assertRaises(FactoryError):
            self.evaluate(receipts)
        plan = copy.deepcopy(self.plan)
        plan['deployment_authorized'] = True
        with self.assertRaises(FactoryError):
            evaluate_factory(plan, [], artifact_root=self.root)
        with self.assertRaises(FactoryError):
            validate_stage(self.plan, 'unknown', [], artifact_root=self.root)

    def test_malformed_unbounded_and_secret_shaped_requirements_rejected(self):
        changes = [({'targets': []}), ({'targets': ['quantum']}), ({'targets': ['web', 'web']}),
                   ({'source_revision': 'main'}), ({'schema_version': True}),
                   ({'requirements': []}), ({'requirements': self.request['requirements'] * 2})]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(FactoryError):
                    plan_factory({**self.request, **change})
        request = copy.deepcopy(self.request)
        request['requirements'][0]['summary'] = 'sk-' + 'x' * 32
        with self.assertRaises(FactoryError):
            plan_factory(request)
        with self.assertRaises(FactoryError):
            plan_factory({**self.request, 'deploy': True})


if __name__ == '__main__':
    unittest.main()
