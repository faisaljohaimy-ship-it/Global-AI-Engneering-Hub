import unittest,tempfile,pathlib
import hub
class HubTests(unittest.TestCase):
 def test_registry(self): self.assertGreater(len(hub.registry()),40)
 def test_dry_run(self):
  with tempfile.TemporaryDirectory() as t:
   hub.onboard(t,'a'*40);self.assertFalse((pathlib.Path(t)/'.engineering').exists())
 def test_preserve(self):
  with tempfile.TemporaryDirectory() as t:
   hub.onboard(t,'a'*40,True);r=hub.onboard(t,'b'*40,True);self.assertEqual(r['capabilities.json'],'preserved');self.assertIn('a'*40,(pathlib.Path(t)/'.engineering/capabilities.json').read_text())
 def test_bad_revision(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(ValueError):hub.onboard(t,'main',True)
 def test_skills(self):self.assertGreaterEqual(len(list((hub.ROOT/'skills').glob('*/SKILL.md'))),8)
if __name__=='__main__':unittest.main()
