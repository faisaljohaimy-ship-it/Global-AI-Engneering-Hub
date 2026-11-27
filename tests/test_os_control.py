import json
import pathlib
import subprocess
import tempfile
import unittest

from engineering_os import control


class ControlTests(unittest.TestCase):
    def test_twelve_layers_are_targets_not_fabricated_installations(self):
        report=control.architecture()
        self.assertEqual([r['id'] for r in report['layers']],[f'L{i:02}' for i in range(1,13)])
        self.assertFalse(report['runtime_dependency_on_hub'])
        self.assertTrue(all(r['target'] for r in report['layers']))

    def test_unreviewed_catalog_never_becomes_operational(self):
        tools=[r for r in control.capabilities() if r['kind']=='external-tool']
        self.assertGreaterEqual(len(tools),114)
        self.assertTrue(all(not r['operational'] and not r['installed'] for r in tools))
        self.assertTrue(control.capabilities('spec-kit','DISCOVERED'))
        with self.assertRaises(ValueError):control.capabilities(state='RUNNING')

    def test_provider_probe_is_historical_not_live_authentication(self):
        report=control.integrations()
        self.assertFalse(report['live_recheck_performed'])
        self.assertEqual(len(report['programs']),22)
        self.assertIn('not implemented',report['protocols']['a2a'])

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
