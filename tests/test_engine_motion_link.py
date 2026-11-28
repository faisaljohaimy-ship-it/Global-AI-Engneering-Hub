"""Selective install of engine-native motions: one motion brings exactly what it imports."""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import hublink  # noqa: E402

LIGHT = "engine-motion:quantum-light-tunnel"
BUTTON = "engine-motion:micro-magnetic-button"
SEQUENCE = "engine-motion:compositions-quantum-master-sequence"


class EngineMotionLink(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.revision = hublink.head()

    def setUp(self):
        self.target = pathlib.Path(tempfile.mkdtemp(prefix="hub-engine-motion-"))
        self.addCleanup(shutil.rmtree, self.target, True)

    def paths(self, capability):
        return [row["path"] for row in hublink.resolve(self.revision, capability)]

    def test_a_shader_motion_brings_its_engine_and_not_the_rest_of_the_library(self):
        paths = self.paths(LIGHT)
        root = hublink.ENGINE_DIR
        self.assertIn(f"{root}/motions/quantum/light-tunnel.mjs", paths)
        self.assertIn(f"{root}/engines/webgl.mjs", paths)
        self.assertIn(f"{root}/core/define.mjs", paths)
        self.assertEqual([path for path in paths if "/motions/" in path], [f"{root}/motions/quantum/light-tunnel.mjs"])
        for absent in ("core/api.mjs", "engines/dom.mjs", "engines/webgpu.mjs", "registry.mjs", "index.mjs", "verify/browser.mjs"):
            self.assertNotIn(f"{root}/{absent}", paths)
        self.assertTrue(all(path.startswith(root + "/") and path.endswith(".mjs") for path in paths))

    def test_a_composition_brings_the_motions_it_is_made_of(self):
        motions = sorted(path.rsplit("/", 1)[1] for path in self.paths(SEQUENCE) if "/motions/quantum/" in path)
        self.assertEqual(motions, ["energy-collapse.mjs", "light-tunnel.mjs", "orbital-matrix.mjs", "probability-cloud.mjs", "singularity-reveal.mjs"])

    def test_unknown_or_malformed_ids_are_refused(self):
        for bad in ("engine-motion:quantum-no-such-motion", "engine-motion:nomodule", "engine-motion:../../hub", "engine-motion:quantum-"):
            with self.assertRaises(ValueError, msg=bad):
                hublink.resolve(self.revision, bad)

    def test_two_motions_register_together_verify_and_run_from_the_installed_copy(self):
        result = hublink.register(self.target, self.revision, capabilities=[LIGHT, BUTTON], apply=True)
        self.assertNotIn("error", result)
        manifest = json.loads((self.target / hublink.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual([row["id"] for row in manifest["capabilities"]], [LIGHT, BUTTON])
        report = hublink.verify(self.target)
        self.assertTrue(all(check["ok"] for check in report["checks"]), report)
        self.assertEqual(report["level"], "verified")
        # The installed copy is self-contained: Node can import the motion and read its definition.
        script = (
            "const light = (await import(process.argv[1] + '/motions/quantum/light-tunnel.mjs')).default;"
            "const button = await import(process.argv[1] + '/motions/micro/magnetic-button.mjs');"
            "const style = button.respond({ x: 0.4, y: 0, down: false }, { strength: 0.5, reach: 2 });"
            "console.log(JSON.stringify({ id: light.id, engine: light.engine, button: button.default.id, moves: style.transform.includes('translate') }));"
        )
        done = subprocess.run(
            ["node", "--input-type=module", "-e", script, "--", str(self.target / hublink.ENGINE_DIR)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"id": "quantum-light-tunnel", "engine": "webgl2-glsl", "button": "micro-magnetic-button", "moves": True})

    def test_an_edited_engine_file_fails_verification(self):
        hublink.register(self.target, self.revision, capabilities=[LIGHT], apply=True)
        edited = self.target / hublink.ENGINE_DIR / "engines" / "webgl.mjs"
        edited.write_text(edited.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
        report = hublink.verify(self.target)
        self.assertEqual(report["level"], "broken")

    def test_removing_one_motion_keeps_the_files_another_still_needs(self):
        hublink.register(self.target, self.revision, capabilities=[LIGHT, BUTTON], apply=True)
        hublink.register(self.target, self.revision, capabilities=[], remove=[BUTTON], apply=True)
        root = self.target / hublink.ENGINE_DIR
        self.assertTrue((root / "motions/quantum/light-tunnel.mjs").exists())
        self.assertTrue((root / "core/define.mjs").exists(), "shared with the remaining motion")
        self.assertFalse((root / "motions/micro/magnetic-button.mjs").exists())
        self.assertFalse((root / "engines/dom.mjs").exists(), "only the removed motion used it")
        self.assertEqual(hublink.verify(self.target)["level"], "verified")


if __name__ == "__main__":
    unittest.main()
