"""recheck-authz L7 / merge-quality F3: MEMORY.md matches the shipped pack and the memory engine record.

MEMORY.md still said the vendored gaie_memory.py copies lack the engine (the gaie-factory pack has shipped
memory.py, orchestration.py and security_scan.py since e652601) and listed 7 actions for the engines.json
memory record (there are 22). These checks tie the corrected text to the sources it describes.
"""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import control_plane, memory  # noqa: E402
from scripts import gaie_bootstrap  # noqa: E402

DOC = (ROOT / "docs/specs/gaie-20-layers/MEMORY.md").read_text(encoding="utf-8")
DOC_ENGINE = ("memory.py", "orchestration.py", "security_scan.py", "gaie_memory.py")


class MemoryDocMatchesSources(unittest.TestCase):
    def test_the_pack_vendors_the_engine_the_doc_says_it_vendors(self):
        files, installed = gaie_bootstrap.pack()["files"], gaie_bootstrap.plan(False)
        for name in DOC_ENGINE:
            self.assertIn(f".engineering/gaie/{name}", files.values(), name)  # the pack copy
            self.assertIn(f"skills/gaie-master-router/engine/{name}", installed, name)  # the bootstrap copy
        self.assertNotIn("until the pack and the bootstrap vendor them", DOC)
        self.assertNotIn("Until the integrator vendors the engine", DOC)

    def test_the_documented_memory_actions_are_the_engine_record_and_the_control_plane(self):
        actions = memory.ENGINE_RECORD["actions"]
        described = control_plane.describe("memory")["actions"]
        self.assertEqual(set(described), set(actions))
        reads = sorted(name for name, spec in described.items() if spec["side_effect"] == "none")
        writes = sorted(name for name, spec in described.items() if spec["side_effect"] == "state-write")
        self.assertEqual(len(reads) + len(writes), len(actions))
        self.assertIn(f"lists all {len(actions)} `memory.ENGINE_RECORD` actions", DOC)
        bullet = DOC[DOC.index("The control plane reaches memory only"):]
        bullet = bullet[:bullet.index("\n- ")]
        reads_text = re.search(r"(\d+) reads with\s+side_effect none \(([^)]*)\)", bullet)
        writes_text = re.search(r"(\d+) writes under a\s+state-write grant \(([^)]*)\)", bullet)
        self.assertEqual((int(reads_text[1]), sorted(re.split(r",\s*", reads_text[2]))), (len(reads), reads))
        self.assertEqual((int(writes_text[1]), sorted(re.split(r",\s*", writes_text[2]))), (len(writes), writes))
        self.assertNotIn("means adding them to the engines.json", DOC)


if __name__ == "__main__":
    unittest.main()
