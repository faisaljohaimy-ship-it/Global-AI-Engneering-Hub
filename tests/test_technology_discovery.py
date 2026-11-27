import importlib.util
import io
import pathlib
import unittest
from urllib.error import HTTPError

spec=importlib.util.spec_from_file_location('discovery',pathlib.Path(__file__).resolve().parents[1]/'scripts/discover_technology.py')
discovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(discovery)


class DiscoveryTests(unittest.TestCase):
    def test_candidates_are_never_installed_or_approved(self):
        rows=[{'id':str(i),'source':'https://github.com/example/tool'} for i in range(8)]
        result=discovery.discover(rows,5,2,probe_fn=lambda entry,token:{'id':entry['id'],'status':'fixture-only'})
        self.assertEqual([r['id'] for r in result['findings']],['2','3','4','5','6'])
        self.assertFalse(result['automatic_installation'])
        self.assertFalse(result['automatic_approval'])

    def test_auth_and_rate_limits_stop_after_current_bounded_batch(self):
        rows=[{'id':str(i)} for i in range(9)]
        result=discovery.discover(rows,9,probe_fn=lambda entry,token:{'id':entry['id'],'http_status':403})
        self.assertEqual(result['attempted'],4)
        self.assertTrue(result['stopped_on_authorization_or_rate_limit'])

    def test_canonical_sources_and_budgets_are_validated(self):
        for url in ['http://github.com/a/b','https://evil.invalid/a/b','https://github.com/a/b/../../private','https://github.com/a/b?token=x']:
            with self.assertRaises(ValueError):discovery.probe({'source':url})
        for value in [True,0,129,float('nan')]:
            with self.assertRaises(ValueError):discovery.discover([],value)

    def test_private_upstream_and_raw_errors_are_not_disclosed(self):
        class Response(io.BytesIO):
            status=200
        class Client:
            def open(self,*args,**kwargs):return Response(b'{"private":true,"name":"private-value"}')
        result=discovery.probe({'id':'a','source':'https://github.com/example/tool'},opener=Client())
        self.assertEqual(result['status'],'probe-failed')
        self.assertNotIn('private-value',str(result))
