import json
import copy
import hashlib
import pathlib
import subprocess
import tempfile
import unittest

from engineering_os import control


def unit_only_native_receipt():
    """Synthetic positive unit fixture; never written/published as runtime proof."""
    policy=control.read(control.ROOT/'catalog/capabilities/playwright.json')
    record=copy.deepcopy(policy)
    record['runtime_receipt']=policy['historical_reviews'][0]['native_receipt']['path']
    receipt=copy.deepcopy(control.read(control.ROOT/record['runtime_receipt']))
    receipt['toolchain']['playwright']=record['version']
    receipt['inputs']={name:hashlib.sha256((control.ROOT/'motion-library/chromium-stack'/name).read_bytes()).hexdigest()
                       for name in receipt['inputs']}
    return record,receipt


class ControlTests(unittest.TestCase):
    def test_twelve_layers_are_targets_not_fabricated_installations(self):
        report=control.architecture()
        self.assertEqual([r['id'] for r in report['layers']],[f'L{i:02}' for i in range(1,13)])
        self.assertFalse(report['runtime_dependency_on_hub'])
        self.assertTrue(all(r['target'] for r in report['layers']))

    def test_unreviewed_catalog_never_becomes_operational(self):
        tools=[r for r in control.capabilities() if r['kind']=='external-tool']
        self.assertGreaterEqual(len(tools),114)
        self.assertTrue(all(not r['operational'] and not r['installed'] for r in tools if r['state']=='DISCOVERED'))
        self.assertTrue(control.capabilities('spec-kit','DISCOVERED'))
        with self.assertRaises(ValueError):control.capabilities(state='RUNNING')

    def test_runtime_claim_withdraws_when_receipt_inputs_change(self):
        from unittest import mock
        import datetime
        policy=control.read(control.ROOT/'catalog/capabilities/playwright.json')
        self.assertIsNone(control.runtime_review(policy), 'A reviewed installation is not current runtime evidence')
        record,receipt=unit_only_native_receipt()
        recorded=datetime.datetime.fromisoformat(receipt['recorded_at_utc'].replace('Z','+00:00'))
        # Explicit unit-only dependency injection exercises the positive validator;
        # actual policy.runtime_receipt remains null, so no catalog promotion occurs.
        with mock.patch.object(control,'read',return_value=receipt):
            self.assertEqual(control.runtime_review(record,recorded)['revision'],record['revision'])
            self.assertIsNone(control.runtime_review(record,recorded+datetime.timedelta(days=2)))
            unsafe=copy.deepcopy(record);unsafe['module_root']='../outside'
            self.assertIsNone(control.runtime_review(unsafe,recorded))
            with mock.patch.object(control.hashlib,'sha256') as digest:
                digest.return_value.hexdigest.return_value='0'*64
                self.assertIsNone(control.runtime_review(record,recorded))

    def test_provider_probe_is_historical_not_live_authentication(self):
        report=control.integrations()
        self.assertFalse(report['live_recheck_performed'])
        self.assertEqual(len(report['programs']),22)
        self.assertIn('not implemented',report['protocols']['a2a'])

    def test_partial_or_failed_browser_evidence_never_advances_lifecycle(self):
        import copy
        import datetime
        from unittest import mock
        record,receipt=unit_only_native_receipt()
        recorded=datetime.datetime.fromisoformat(receipt['recorded_at_utc'].replace('Z','+00:00'))
        broken=[]
        item=copy.deepcopy(receipt);item['inputs'].pop('native-probes.mjs');broken.append(item)
        item=copy.deepcopy(receipt);item['cases'][0]['checks']['webgl_shader_pixels']=False;broken.append(item)
        item=copy.deepcopy(receipt);item['cases']=item['cases'][:1];broken.append(item)
        item=copy.deepcopy(receipt);item['cases'][0]['benchmark']['p95_interval_ms']=float('inf');broken.append(item)
        item=copy.deepcopy(receipt);item['network']['external_requests']=1;broken.append(item)
        item=copy.deepcopy(receipt);item['cases'][0]['direction']='rtl';broken.append(item)
        item=copy.deepcopy(receipt);item['cases'][2]['rendered']['waapi']=True;broken.append(item)
        item=copy.deepcopy(receipt);item['cases'][0]['benchmark']['intervals']=[];broken.append(item)
        for item in broken:
            with self.subTest(item=item.keys()),mock.patch.object(control,'read',return_value=item):
                self.assertIsNone(control.runtime_review(record,recorded))

    def test_evidence_json_rejects_duplicate_and_overflowed_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            target=pathlib.Path(folder)/'receipt.json'
            for text in ('{"a":1,"a":2}','{"a":1e9999}','{"a":NaN}'):
                target.write_text(text)
                with self.assertRaises(ValueError):control.read(target)

    def test_motion_proof_withdraws_for_partial_sources_duplicate_profiles_or_failed_budgets(self):
        import copy
        from unittest import mock
        real_read=control.read
        path=control.ROOT/'docs/evidence/motion-expansion-2026-11-27.json'
        receipt=real_read(path)
        expansion=control.motions()['expansion']
        self.assertEqual((expansion['implemented'],expansion['tested']), (400,400))
        self.assertEqual(expansion['runtime_verified'],0)
        self.assertEqual(expansion['historical_tested_toolchain']['playwright'],'1.63.0')
        self.assertEqual(expansion['current_runtime']['state'],'evidence-required')
        broken=[]
        item=copy.deepcopy(receipt);item['source_sha256'].pop('packages/motion-sdk/index.mjs');broken.append(item)
        item=copy.deepcopy(receipt);item['profiles'][1]=item['profiles'][0];broken.append(item)
        item=copy.deepcopy(receipt);item['profiles'][0]['definitions'][0]['distinct_sampled_frames']=1;broken.append(item)
        item=copy.deepcopy(receipt);item['profiles'][0]['definitions'][0]['cpu_p95_ms']=20;broken.append(item)
        item=copy.deepcopy(receipt);item['profiles'][0]['definitions'][0]['benchmark_frames']=1;broken.append(item)
        item=copy.deepcopy(receipt);item['profiles'][0]['definitions'][0].update(cpu_p95_ms=0,cpu_budget_ms=0);broken.append(item)
        item=copy.deepcopy(receipt);item['profiles'][0]['definitions'][0].update(cpu_p95_ms=.5,cpu_budget_ms=True);broken.append(item)
        item=copy.deepcopy(receipt);item['profiles'][0]['definitions'][0]['distinct_sampled_frames']=99;broken.append(item)
        item=copy.deepcopy(receipt);item['profiles'][0]['viewport']['height']=0;broken.append(item)
        item=copy.deepcopy(receipt);item['recorded_at_utc']='not-a-timestamp';broken.append(item)
        item=copy.deepcopy(receipt);item['playwright_version']='0.0.1';broken.append(item)
        for item in broken:
            def amended(target):return item if pathlib.Path(target)==path else real_read(target)
            with mock.patch.object(control,'read',side_effect=amended):
                result=control.motions()['expansion']
                self.assertEqual((result['implemented'],result['tested'],result['runtime_verified']), (0,0,0))

    def test_reviewed_history_is_required_and_cannot_relabel_the_old_driver(self):
        from unittest import mock
        real_read=control.read
        policy_path=control.ROOT/'catalog/capabilities/playwright.json'
        policy=real_read(policy_path)
        for changed in ('missing-review','unapproved-review','arbitrary-pin'):
            amended=copy.deepcopy(policy)
            if changed=='missing-review':amended['historical_reviews']=[]
            elif changed=='unapproved-review':amended['historical_reviews'][0]['review_status']='pending'
            else:amended['historical_reviews'][0]['hub_revision']='main'
            with mock.patch.object(control,'read',side_effect=lambda path: amended if pathlib.Path(path)==policy_path else real_read(path)):
                self.assertEqual(control.motions()['expansion']['implemented'],0)
        path=control.ROOT/policy['historical_reviews'][0]['motion_receipt']['path']
        relabeled=copy.deepcopy(real_read(path));relabeled['playwright_version']=policy['version']
        with mock.patch.object(control,'read',side_effect=lambda target: relabeled if pathlib.Path(target)==path else real_read(target)):
            result=control.motions()['expansion']
            self.assertEqual((result['implemented'],result['tested'],result['runtime_verified']), (0,0,0))

    def test_unit_only_current_receipt_requires_reviewed_bytes_and_stays_isolated(self):
        """Synthetic temporary fixture, never a published current-driver proof."""
        import datetime
        import shutil
        from unittest import mock
        actual_root=control.ROOT
        policy=control.read(actual_root/'catalog/capabilities/playwright.json')
        historical=policy['historical_reviews'][0]['motion_receipt']['path']
        receipt=copy.deepcopy(control.read(actual_root/historical))
        receipt.update(playwright_version=policy['version'],scope='UNIT ONLY synthetic current-receipt validator fixture',
                       recorded_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        sources=list(receipt['source_sha256'])+['catalog/registry.json','motion-library/MOTION_CATALOG.json',historical]
        sources.extend(f'motion-library/{scope}/package.json' for scope in ('verify','chromium-stack','quality'))
        sources.extend(f'motion-library/{scope}/package-lock.json' for scope in ('verify','chromium-stack','quality'))
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            for name in sources:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(actual_root/name,target)
            policy=copy.deepcopy(policy)
            policy['motion_runtime_receipt']='docs/evidence/unit-only-current.json'
            current=root/policy['motion_runtime_receipt']
            current.write_text(json.dumps(receipt))
            policy['motion_runtime_receipt_sha256']=hashlib.sha256(current.read_bytes()).hexdigest()
            path=root/'catalog/capabilities/playwright.json';path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(policy))
            with mock.patch.object(control,'ROOT',root):
                result=control.motions()['expansion']
                self.assertEqual((result['implemented'],result['tested'],result['runtime_verified']), (400,400,400))
                self.assertEqual(result['receipt'],policy['motion_runtime_receipt'])
                self.assertEqual(result['recorded_at_utc'],receipt['recorded_at_utc'])
                self.assertEqual(result['historical_tested_toolchain']['playwright'],'1.63.0')
                lock=root/'motion-library/verify/package-lock.json';original=lock.read_bytes()
                changed=json.loads(original);changed['packages']['node_modules/playwright-core']['integrity']='unreviewed'
                lock.write_text(json.dumps(changed))
                self.assertEqual(control.motions()['expansion']['runtime_verified'],0)
                lock.write_bytes(original)
                # Approved bytes are mandatory; a modified file cannot inherit green status.
                current.write_text(json.dumps({**receipt,'playwright_version':'9.9.9'}))
                self.assertEqual(control.motions()['expansion']['runtime_verified'],0)
                self.assertEqual(control.motions()['expansion']['implemented'],400)
        self.assertEqual(control.motions()['expansion']['runtime_verified'],0)

    def test_unknown_project_health_cannot_approve_release(self):
        with tempfile.TemporaryDirectory() as directory:
            report=control.health(directory)
            self.assertFalse(report['release_eligible'])
            self.assertEqual(sum(x['status']=='missing' for x in report['findings']),3)
            root=pathlib.Path(directory);(root/'.engineering').mkdir()
            (root/'.engineering/capabilities.json').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):control.health(directory)

    def test_health_executes_real_offline_integrity_not_manifest_presence(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);(root/'.engineering').mkdir()
            (root/'capability.py').write_bytes(b'print("example")')
            manifest={'schema_version':1,'hub_revision':'a'*40,'budget_additional_sar':0,
                      'production_runtime_dependency':False,
                      'capabilities':[{'id':'pack:example','files':[{'path':'capability.py','sha256':hashlib.sha256((root/'capability.py').read_bytes()).hexdigest()}]}]}
            (root/'.engineering/capabilities.json').write_text(json.dumps(manifest))
            self.assertEqual(control.health(root)['findings'][0]['status'],'passed')
            (root/'capability.py').write_text('tampered')
            self.assertEqual(control.health(root)['findings'][0]['status'],'failed')

    def test_new_cli_commands_preserve_old_cli(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        for args in [('architecture',),('capabilities','--query','spec-kit'),('health',),('motions',),('integrations',),('audit',),('search','motion')]:
            result=subprocess.run(['python3',str(root/'hub.py'),*args],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            json.loads(result.stdout)
