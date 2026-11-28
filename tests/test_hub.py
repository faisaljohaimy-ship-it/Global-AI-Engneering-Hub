import json
import unittest,tempfile,pathlib
from unittest import mock
import hub
class HubTests(unittest.TestCase):
 def setUp(self):
  patcher=mock.patch('hub.hublink.reviewed_commit',return_value=True)
  patcher.start();self.addCleanup(patcher.stop)
 def test_registry(self): self.assertGreater(len(hub.registry()),40)
 def test_dry_run(self):
  with tempfile.TemporaryDirectory() as t:
   hub.onboard(t,'a'*40);self.assertFalse((pathlib.Path(t)/'.engineering').exists())
   self.assertFalse((pathlib.Path(t)/'.agents').exists())
   self.assertFalse((pathlib.Path(t)/'.claude').exists())
 def test_preserve(self):
  with tempfile.TemporaryDirectory() as t:
   hub.onboard(t,'a'*40,True);r=hub.onboard(t,'b'*40,True);self.assertEqual(r['capabilities.json'],'preserved');self.assertIn('a'*40,(pathlib.Path(t)/'.engineering/capabilities.json').read_text())
 def test_bad_revision(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(ValueError):hub.onboard(t,'main',True)
 def test_skills(self):self.assertGreaterEqual(len(list((hub.ROOT/'skills').glob('*/SKILL.md'))),8)
 def test_onboard_has_safe_discovery_contract(self):
  with tempfile.TemporaryDirectory() as t:
   hub.onboard(t,'a'*40,True)
   data=json.loads((pathlib.Path(t)/'.engineering/capabilities.json').read_text())
   self.assertEqual(data['hub_url'],hub.HUB_URL)
   self.assertEqual(data['budget_additional_sar'],0)
   self.assertFalse(data['production_runtime_dependency'])
   self.assertTrue((pathlib.Path(t)/'.agents/skills/hub-capabilities/SKILL.md').is_file())
   self.assertTrue((pathlib.Path(t)/'.claude/skills/hub-capabilities/SKILL.md').is_file())
 def test_update_pin_is_dry_run_and_compare_and_swap(self):
  with tempfile.TemporaryDirectory() as t:
   hub.onboard(t,'a'*40,True)
   result=hub.update_pin(t,'b'*40,'a'*40)
   self.assertEqual(result['status'],'would update')
   manifest=pathlib.Path(t)/'.engineering/capabilities.json'
   self.assertIn('a'*40,manifest.read_text())
   hub.update_pin(t,'b'*40,'a'*40,True)
   self.assertIn('b'*40,manifest.read_text())
   with self.assertRaises(ValueError):hub.update_pin(t,'c'*40,'a'*40,True)
 def test_update_pin_refuses_registered_capabilities(self):
  with tempfile.TemporaryDirectory() as t:
   hub.onboard(t,'a'*40,True)
   manifest=pathlib.Path(t)/'.engineering/capabilities.json'
   data=json.loads(manifest.read_text())
   data['capabilities']=[{'id':'skill:hub-capabilities','files':[]}]
   manifest.write_text(json.dumps(data))
   with self.assertRaisesRegex(ValueError,'re-pinned with hub.py register'):
    hub.update_pin(t,'b'*40,'a'*40,True)
 def test_duplicate_json_keys_are_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   path=pathlib.Path(t)/'duplicate.json'
   path.write_text('{"id": 1, "id": 2}')
   with self.assertRaises(ValueError):hub.load_json(path)
 def test_recommend_discovers_motion_and_skill(self):
  kinds={item['kind'] for item in hub.recommend('motion')}
  self.assertIn('skill',kinds)
  self.assertIn('motion',kinds)
 def test_audit_uses_evidence_manifests(self):
  result=hub.audit()
  self.assertEqual(result['motions_indexed'],156)  # main bf96921 indexed 14 documented specifications
  self.assertEqual(result['motions_implemented'],30)
  self.assertEqual(result['motions_tested'],30)
  self.assertEqual(result['motions_runtime_verified'],29)
  self.assertEqual(result['motions_used'],30)
  self.assertEqual(result['motion_lab_components'],30)
  self.assertEqual(result['integrations_indexed'],22)
  self.assertEqual(result['integrations_probed'],22)
  self.assertEqual(result['integrations_available'],12)
  self.assertEqual(result['registered_public_projects'],3)
  purpose=result['motion_purpose']
  self.assertTrue(purpose['ok'])
  self.assertEqual(purpose['policy'],'governance/policies/motion-purpose.json')
  self.assertEqual(purpose['classes']['purposeful'],107)
  self.assertEqual(purpose['classes']['legacy-unclassified'],37)
  self.assertEqual((purpose['unclassified'],purpose['violations']),(0,0))
 def test_audit_reports_a_broken_motion_policy_without_failing(self):
  from engineering_os import motion_policy
  broken=dict(motion_policy.report(),ok=False,violations=[{'code':'policy-invalid'}])
  with mock.patch.object(motion_policy,'report',return_value=broken):
   purpose=hub.audit()['motion_purpose']
  self.assertEqual((purpose['ok'],purpose['violations']),(False,1))
class HubCliTests(unittest.TestCase):
 """hub.py subcommands run as the owner runs them: a subprocess, no mocks, private temporary state."""
 def run_hub(self,*argv,cwd=None):
  import os,subprocess,sys
  env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
  return subprocess.run([sys.executable,str(hub.ROOT/'hub.py'),*argv],capture_output=True,text=True,cwd=cwd or hub.ROOT,env=env,timeout=120)
 def private(self):
  import os
  directory=tempfile.TemporaryDirectory(prefix='hub-');self.addCleanup(directory.cleanup)
  os.chmod(directory.name,0o700);return pathlib.Path(directory.name)
 def test_register_refusal_is_one_json_error_line(self):
  project=self.private()
  run=self.run_hub('register',str(project),'--revision','0'*40,'--capability','pack:gaie-factory')
  self.assertEqual(run.returncode,1)
  self.assertNotIn('Traceback',run.stderr)
  self.assertEqual(len(run.stdout.strip().splitlines()),1)
  self.assertEqual(json.loads(run.stdout)['status'],'error')
  self.assertEqual(list(project.iterdir()),[])
 def test_audit_anchor_detects_truncation_and_removal(self):
  import os,stat
  from engineering_os import governor
  base=self.private();state=base/'state';state.mkdir(mode=0o700)
  for number in range(3):governor.audit(str(state),{'decision':'allow','reason':f'record {number}'})
  run=self.run_hub('audit-anchor','--state-dir',str(state),'--out',str(state/'anchor.json'))
  self.assertEqual((run.returncode,json.loads(run.stdout)['status']),(1,'error'))
  self.assertFalse((state/'anchor.json').exists())
  anchor=base/'anchor.json'
  run=self.run_hub('audit-anchor','--state-dir',str(state),'--out',str(anchor))
  self.assertEqual(run.returncode,0,run.stdout+run.stderr)
  self.assertEqual(json.loads(run.stdout)['records'],3)
  self.assertEqual(stat.S_IMODE(anchor.stat().st_mode),0o600)
  self.assertEqual(set(json.loads(anchor.read_text())),{'records','record_sha256'})
  run=self.run_hub('audit-anchor','--state-dir',str(state),'--out',str(anchor))
  self.assertEqual(run.returncode,1,'an existing anchor is never overwritten')
  run=self.run_hub('audit-anchor','--state-dir',str(state),'--verify',str(anchor))
  self.assertEqual((run.returncode,json.loads(run.stdout)),(0,{'status':'intact','records':3}))
  log=state/governor.AUDIT_FILE
  lines=log.read_bytes().splitlines(keepends=True);log.write_bytes(b''.join(lines[:-1]))
  run=self.run_hub('audit-anchor','--state-dir',str(state),'--verify',str(anchor))
  self.assertEqual(run.returncode,1);self.assertIn('audit-tampered',run.stdout)
  log.unlink()
  run=self.run_hub('audit-anchor','--state-dir',str(state),'--verify',str(anchor))
  self.assertEqual(run.returncode,1);self.assertIn('audit-tampered',run.stdout)
  fifo=base/'fifo';os.mkfifo(fifo)
  run=self.run_hub('audit-anchor','--state-dir',str(state),'--verify',str(fifo))
  self.assertEqual(run.returncode,1,'a FIFO is refused without blocking')
  link=base/'link.json';link.symlink_to(anchor)
  run=self.run_hub('audit-anchor','--state-dir',str(state),'--verify',str(link))
  self.assertEqual(run.returncode,1,'a symlinked anchor is refused')
 def test_assurance_delegates_to_the_module_cli(self):
  run=self.run_hub('assurance','assign','--producer','master-build-engine-engineer','--json')
  self.assertEqual(run.returncode,0,run.stderr)
  self.assertEqual(json.loads(run.stdout)['reviewer'],'independent-assurance-engineer')
  run=self.run_hub('assurance','assign','--producer','master-build-engine-engineer','--reviewer','master-build-engine-engineer')
  self.assertEqual(run.returncode,2,'a producer never reviews its own work')
if __name__=='__main__':unittest.main()
