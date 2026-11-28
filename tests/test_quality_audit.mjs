import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { DEFAULT_BUDGETS, evaluateBudgets, validateAuditUrl } from '../motion-library/quality/budgets.mjs';
import { parseArgs } from '../motion-library/quality/audit.mjs';
import { serveStudio } from '../motion-library/quality/server.mjs';

const metrics = { performance: 95, accessibility: 95, lcp_ms: 2500, cls: 0.1, critical_axe: 0, page_errors: 0, blocked_external_requests: 0 };
test('quality thresholds accept their exact boundary and reject each measured failure', () => {
  assert.equal(evaluateBudgets(metrics).passed, true);
  for (const [key, value] of Object.entries({ performance: 94.99, accessibility: 94, lcp_ms: 2501, cls: 0.1001, critical_axe: 1, page_errors: 1, blocked_external_requests: 1 })) {
    const result = evaluateBudgets({ ...metrics, [key]: value });
    assert.equal(result.passed, false, key);
    assert.equal(result.failures[0].metric, key);
  }
});
test('missing, negative, non-finite and string measurements cannot pass', () => {
  for (const key of Object.keys(metrics)) for (const value of [undefined, null, NaN, Infinity, '100', -1]) {
    assert.equal(evaluateBudgets({ ...metrics, [key]: value }).passed, false, `${key}: ${String(value)}`);
  }
});
test('budgets are finite, bounded and never permit critical axe violations', () => {
  for (const key of Object.keys(DEFAULT_BUDGETS)) for (const value of [undefined, NaN, Infinity, -1, '95']) {
    assert.throws(() => evaluateBudgets(metrics, { ...DEFAULT_BUDGETS, [key]: value }));
  }
  assert.throws(() => evaluateBudgets(metrics, { ...DEFAULT_BUDGETS, critical_axe_max: 1 }));
  assert.throws(() => evaluateBudgets(metrics, { ...DEFAULT_BUDGETS, lcp_ms_max: 10001 }));
});
test('audit targets must be loopback Motion Studio and match the self-hosted origin', () => {
  for (const host of ['127.0.0.1', 'localhost', '[::1]']) assert.ok(validateAuditUrl(`http://${host}:3210/motion-studio/index.html?motion=os-quantum-b01`));
  for (const url of [
    'https://example.com/motion-studio/', 'http://127.0.0.1.evil/motion-studio/',
    'http://169.254.169.254/motion-studio/', 'http://localhost/admin', 'file:///motion-studio/index.html',
    // Construct the synthetic negative case; keep credential URLs out of the Git index.
    'http://' + ['user','pass'].join(':') + '@localhost/motion-studio/', 'http://localhost/motion-studio/#secret',
    'http://localhost/motion-studio/index.html?url=https://example.com', 'http://localhost/motion-studio/index.html?motion=../../secret',
  ]) assert.throws(() => validateAuditUrl(url), url);
  assert.throws(() => validateAuditUrl('http://localhost:1234/motion-studio/', 'http://127.0.0.1:1234'));
});
test('CLI rejects duplicate or unknown arguments, remote paths and non-finite profiles', () => {
  const args = ['--out', '/tmp/private-evidence', '--chrome', '/tmp/chrome'];
  assert.equal(parseArgs(args).profile, 'desktop');
  for (const extra of [['--profile', '120fps'], ['--entry', 'http://example.com'], ['--out', '/tmp/second'], ['--token', 'value'], ['--root']]) {
    assert.throws(() => parseArgs([...args, ...extra]));
  }
});
test('ephemeral local server bounds files, denies symlinks and returns restrictive CSP', async () => {
  const root = await mkdtemp(join(tmpdir(), 'quality-server-test-'));
  let server;
  try {
    await mkdir(join(root, 'motion-studio'));
    await writeFile(join(root, 'motion-studio/index.html'), '<!doctype html><title>fixture</title>');
    await writeFile(join(root, 'secret.json'), '{"private":true}');
    await symlink(join(root, 'secret.json'), join(root, 'motion-studio/leak.json'));
    server = await serveStudio(root);
    const response = await fetch(`${server.origin}/motion-studio/`);
    assert.equal(response.status, 200);
    assert.match(response.headers.get('content-security-policy'), /connect-src 'none'/);
    for (const path of ['/secret.json', '/motion-studio/leak.json', '/.git/config', '/motion-studio/%2e%2e/secret.json', '/motion-studio/%2e%2e%2Fsecret.json', '/motion-studio/%ZZ', '/motion-studio/%00.json']) {
      assert.equal((await fetch(`${server.origin}${path}`)).status, 404, path);
    }
    assert.equal((await fetch(`${server.origin}/motion-studio/`, { method: 'POST' })).status, 405);
  } finally { await server?.close(); await rm(root, { recursive: true, force: true }); }
});
