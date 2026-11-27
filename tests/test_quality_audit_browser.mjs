import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { runAudit } from '../motion-library/quality/audit.mjs';

test('real Lighthouse and axe pass a simple local fixture and reject an inaccessible fixture', { skip: !process.env.QUALITY_AUDIT_CHROME, timeout: 180_000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'quality-fixture-source-'));
  const evidenceRoot = process.env.QUALITY_AUDIT_EVIDENCE || await mkdtemp(join(tmpdir(), 'quality-fixture-evidence-'));
  await mkdir(evidenceRoot, { recursive: true });
  await mkdir(join(root, 'motion-studio'));
  try {
    for (const broken of [false, true]) {
      await writeFile(join(root, 'motion-studio/index.html'), `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Local quality fixture</title></head><body><main><h1>Local quality fixture</h1><p>This synthetic document validates the audit driver only.</p>${broken ? '<button></button><img src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%222%22 height=%222%22/%3E">' : '<button>Start preview</button>'}</main></body></html>`);
      const out = join(evidenceRoot, broken ? 'fixture-failing' : 'fixture-passing');
      const result = await runAudit({ root, out, chrome: process.env.QUALITY_AUDIT_CHROME, entry: '/motion-studio/index.html', profile: 'desktop', fixture: true });
      assert.equal(result.kind, 'synthetic-fixture-quality-audit');
      assert.equal(result.passed, !broken);
      assert.equal(result.metrics.inp_ms, null);
      assert.match(result.metrics.inp_status, /not measured/);
      assert.equal(result.metrics.page_errors, 0);
      assert.ok(JSON.parse(await readFile(join(out, 'lighthouse.json'), 'utf8')).lighthouseVersion);
      assert.ok(JSON.parse(await readFile(join(out, 'axe.json'), 'utf8')).testEngine.version);
      if (broken) {
        assert.ok(result.metrics.critical_axe > 0);
        assert.ok(result.failures.some(item => item.metric === 'critical_axe'));
      }
    }
  } finally {
    await rm(root, { recursive: true, force: true });
    if (!process.env.QUALITY_AUDIT_EVIDENCE) await rm(evidenceRoot, { recursive: true, force: true });
  }
});
