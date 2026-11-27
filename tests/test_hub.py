import json
import unittest,tempfile,pathlib
import hub
class HubTests(unittest.TestCase):
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
  self.assertEqual(result['motions_indexed'],142)
  self.assertEqual(result['motions_implemented'],26)
  self.assertEqual(result['motions_tested'],26)
  self.assertEqual(result['motions_runtime_verified'],24)
  self.assertEqual(result['motions_used'],26)
  self.assertEqual(result['integrations_indexed'],22)
  self.assertEqual(result['integrations_probed'],22)
  self.assertEqual(result['integrations_available'],12)
if __name__=='__main__':unittest.main()
