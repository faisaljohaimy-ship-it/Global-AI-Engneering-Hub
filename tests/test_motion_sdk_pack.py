"""Accept a locally vendored SDK only when registration, invocation and integrity work.

Only main ancestry is mocked for the unmerged commit under test, matching test_link.
The resolver, copied source, Node runtime and offline verifier are real.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import hub
import hublink

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = ".engineering/vendor/os-motion"

# Executes from an isolated project containing only the files registration copied.
# Network entry points fail closed before importing the real vendored modules.
NODE_PROBE = r"""
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
let networkRequests = 0;
const rejectNetwork = () => { networkRequests++; throw new Error('Network forbidden in motion pack test'); };
globalThis.fetch = rejectNetwork;
globalThis.WebSocket = rejectNetwork;
globalThis.XMLHttpRequest = rejectNetwork;
for (const [name, methods] of [
  ['http', ['get', 'request']], ['https', ['get', 'request']],
  ['net', ['connect', 'createConnection']], ['tls', ['connect']],
  ['dgram', ['createSocket']], ['dns', ['lookup', 'resolve']],
]) {
  const module = (await import(`node:${name}`)).default;
  for (const method of methods) module[method] = rejectNetwork;
  if (name === 'net') module.Socket.prototype.connect = rejectNetwork;
}
syncBuiltinESMExports();
const sdk = await import('./.engineering/vendor/os-motion/packages/motion-sdk/index.mjs');
const sdkExamples = await import('./.engineering/vendor/os-motion/packages/motion-sdk/examples.mjs');
const catalog = await import('./.engineering/vendor/os-motion/motion-library/expansion/catalog.mjs');
const {exampleFor} = await import('./.engineering/vendor/os-motion/motion-library/expansion/examples.mjs');
const metadata = JSON.parse(readFileSync('./.engineering/vendor/os-motion/motion-library/expansion/definitions.json'));
const motion = sdk.createMotionSystem();
assert.deepEqual(await motion.loadCatalog(), {registered: 400, total: 400});
assert.deepEqual(metadata.definitions.map(x => x.id), motion.definitions().map(x => x.id));
assert.equal(catalog.getCapabilities().basic, 200);
assert.equal(catalog.getCapabilities().advanced, 200);
assert.equal(catalog.getCapabilities().categories, 20);
let sampled = 0, maxPrimitives = 0;
for (const [index, definition] of motion.definitions().entries()) {
  const options = {width: 320, height: 180, detail: 6, rtl: index % 2 === 1, reducedMotion: 'full'};
  const clip = motion.create(definition.id, options);
  const scene = sdk.validateScene(clip.render(.37));
  assert.equal(scene.meta.id, definition.id);
  assert.equal(scene.meta.engine, 'canvas2d');
  assert(scene.primitives.length > 0 && scene.primitives.length <= catalog.MAX_PRIMITIVES);
  // The SDK's documented JSON copy normalizes IEEE negative zero in RTL geometry.
  const example = exampleFor(definition.id).sample(.37, {...options, reducedMotion: false});
  assert(JSON.stringify(scene) === JSON.stringify(example), `Vendored example mismatch: ${definition.id}`);
  assert.deepEqual(JSON.parse(clip.export('json')).scene, scene);
  assert(clip.export('svg').startsWith('<svg '));
  assert.equal(sdkExamples.frameSequence(clip, {frames: 3}).length, 3);
  clip.configure({reducedMotion: 'reduce'});
  assert.deepEqual(clip.render(.1), clip.render(.9));
  assert.equal(clip.getCapabilities().webgpu, 'not-enabled');
  assert.equal(clip.getCapabilities().remotion, 'not-installed');
  assert.equal(clip.getCapabilities().encoded_video, false);
  maxPrimitives = Math.max(maxPrimitives, scene.primitives.length);
  clip.destroy(); sampled++;
}
assert.equal(motion.getCapabilities().live_instances, 0);
await assert.rejects(motion.loadCatalog('https://example.invalid/catalog.mjs'), /local or same-origin/);
assert.equal(networkRequests, 0);
console.log(JSON.stringify({sampled, maxPrimitives, network_requests: networkRequests,
  engine: 'canvas2d', browser_rendering_tested: false, production_fps_verified: false}));
"""


class MotionSDKPackTests(unittest.TestCase):
    def setUp(self):
        self.revision = hublink.head()
        ancestry = mock.patch("hublink.on_main", return_value=True)
        ancestry.start()
        self.addCleanup(ancestry.stop)

    def project(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return pathlib.Path(temporary.name)

    def register(self, target, *capabilities, **options):
        return hublink.register(target, self.revision, capabilities=capabilities, **options)

    def test_registration_is_selective_dry_run_then_both_agent_skills_verify(self):
        target = self.project()
        plan = self.register(target, "pack:motion-sdk")
        self.assertFalse(plan["applied"])
        self.assertEqual(list(target.iterdir()), [])
        self.register(target, "pack:motion-sdk", apply=True)
        manifest = hublink.load_manifest(target)
        self.assertEqual([row["id"] for row in manifest["capabilities"]], ["pack:motion-sdk"])
        self.assertEqual(manifest["hub_revision"], self.revision)
        self.assertEqual(manifest["budget_additional_sar"], 0)
        self.assertIs(manifest["production_runtime_dependency"], False)
        paths = {row["path"] for row in manifest["capabilities"][0]["files"]}
        self.assertEqual(len(paths), 14)  # twelve local sources/docs plus both skill copies
        skill = (target / ".agents/skills/universal-motion/SKILL.md").read_bytes()
        self.assertEqual(skill, (target / ".claude/skills/universal-motion/SKILL.md").read_bytes())
        self.assertIn(b"pack:motion-sdk", skill)
        self.assertTrue(hublink.verify(target, strict=True)["ok"])
        self.assertTrue(any(row["kind"] == "skill" and row["id"] == "universal-motion"
                            for row in hub.recommend("Universal Motion SDK")))

    def test_relative_source_imports_and_scoped_licenses_are_complete(self):
        pack = json.loads((ROOT / "catalog/packs.json").read_text())["packs"]["motion-sdk"]
        mapping = pack["files"]
        for source, destination in mapping.items():
            self.assertEqual(destination, f"{VENDOR}/{source}")
            path = ROOT / source
            self.assertTrue(path.is_file())
            if path.suffix == ".mjs":
                for imported in re.findall(r"^import\b[^\n;]*\bfrom\s+['\"]([^'\"]+)['\"]",
                                           path.read_text(), flags=re.MULTILINE):
                    self.assertTrue(imported.startswith("./"), imported)
                    dependency = (path.parent / imported).resolve().relative_to(ROOT).as_posix()
                    self.assertIn(dependency, mapping, source)
        for directory in ("packages/motion-sdk", "motion-library/expansion"):
            self.assertIn(f"{directory}/LICENSE", mapping)
            self.assertIn("MIT License", (ROOT / directory / "LICENSE").read_text())
        self.assertFalse(any("node_modules" in path or "chromium-stack" in path for path in mapping))

    def test_existing_engineering_sdk_and_project_instructions_survive_addition(self):
        target = self.project()
        for name in ("AGENTS.md", "CLAUDE.md"):
            (target / name).write_text(f"Project-owned {name}\n")
        self.register(target, "pack:engineering-sdk", apply=True)
        prior = {path: path.read_bytes() for path in target.rglob("*") if path.is_file()
                 and path != target / hublink.MANIFEST}
        self.register(target, "pack:motion-sdk", apply=True)
        self.assertEqual({row["id"] for row in hublink.load_manifest(target)["capabilities"]},
                         {"pack:engineering-sdk", "pack:motion-sdk"})
        for path, data in prior.items():
            self.assertEqual(path.read_bytes(), data, path)
        self.assertTrue(hublink.verify(target, strict=True)["ok"])

    def test_unmanaged_vendor_and_agent_skill_conflicts_stop_before_mutation(self):
        for relative in (f"{VENDOR}/packages/motion-sdk/index.mjs", ".agents/skills/universal-motion/SKILL.md"):
            with self.subTest(relative=relative):
                target = self.project()
                path = target / relative
                path.parent.mkdir(parents=True)
                path.write_text("project-owned\n")
                with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
                    self.register(target, "pack:motion-sdk", apply=True)
                self.assertEqual(path.read_text(), "project-owned\n")
                self.assertEqual([p for p in target.rglob("*") if p.is_file()], [path])

    def test_unmerged_pin_is_rejected_outside_the_test_ancestry_allowance(self):
        target = self.project()
        with mock.patch("hublink.on_main", return_value=False):
            with self.assertRaisesRegex(ValueError, "reviewed commit on the hub main"):
                self.register(target, "pack:motion-sdk", apply=True)
        self.assertEqual(list(target.iterdir()), [])

    def test_offline_sdk_integrity_detects_tampered_vendored_geometry(self):
        target = self.project()
        self.register(target, "pack:engineering-sdk", "pack:motion-sdk", apply=True)
        command = [sys.executable, str(target / ".engineering/sdk/engineering_sdk.py"), "verify", "--project", str(target)]
        good = subprocess.run(command, cwd=target, capture_output=True, text=True, timeout=20, check=True)
        self.assertEqual(json.loads(good.stdout)["network_requests"], 0)
        geometry = target / VENDOR / "motion-library/expansion/geometry.mjs"
        geometry.write_text(geometry.read_text() + "\n// unreviewed edit\n")
        self.assertFalse(hublink.verify(target, strict=True)["ok"])
        bad = subprocess.run(command, cwd=target, capture_output=True, text=True, timeout=20)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("Engineering check failed", bad.stderr)

    def test_real_vendored_node_sdk_samples_all_400_scenes_without_network(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js 20+ is required for the motion pack invocation gate")
        target = self.project()
        self.register(target, "pack:motion-sdk", apply=True)
        result = subprocess.run([node, "--input-type=module", "-e", NODE_PROBE], cwd=target,
                                env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr[-5000:])
        report = json.loads(result.stdout)
        self.assertEqual(report["sampled"], 400)
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(report["engine"], "canvas2d")
        self.assertFalse(report["browser_rendering_tested"])
        self.assertFalse(report["production_fps_verified"])


if __name__ == "__main__":
    unittest.main()
