#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtemp, mkdir, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import lighthouse from 'lighthouse';
import desktopConfig from 'lighthouse/core/config/desktop-config.js';
import AxeBuilder from '@axe-core/playwright';
import { chromium } from 'playwright';
import { DEFAULT_BUDGETS, evaluateBudgets, validateAuditUrl } from './budgets.mjs';
import { inside, serveStudio } from './server.mjs';

const require=createRequire(import.meta.url);
const playwrightVersion=require('playwright/package.json').version;

const STUDIO_SOURCES = ['motion-studio/index.html', 'motion-studio/styles.css', 'motion-studio/studio.mjs', 'packages/motion-sdk/index.mjs', 'motion-library/expansion/catalog.mjs', 'motion-library/expansion/families.mjs', 'motion-library/expansion/systems.mjs', 'motion-library/expansion/geometry.mjs'];
async function sourceSnapshot(root, fixture) {
  const hashes = {};
  for (const source of fixture ? ['motion-studio/index.html'] : STUDIO_SOURCES) {
    hashes[source] = createHash('sha256').update(await readFile(join(root, source))).digest('hex');
  }
  let commit = null;
  if (!fixture) {
    try { commit = execFileSync('git', ['-C', root, 'rev-parse', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim(); }
    catch { /* A source archive may lack Git metadata; file hashes still bind evidence. */ }
  }
  return { commit, hashes };
}

async function bounded(task, label, milliseconds) {
  let timer;
  try {
    return await Promise.race([task, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label} exceeded its bounded lab timeout`)), milliseconds); })]);
  } finally { clearTimeout(timer); }
}

export function parseArgs(args) {
  const options = { root: resolve(dirname(fileURLToPath(import.meta.url)), '../..'), entry: '/motion-studio/index.html', profile: 'desktop' };
  const keys = { '--root': 'root', '--out': 'out', '--chrome': 'chrome', '--entry': 'entry', '--profile': 'profile' };
  const seen = new Set();
  for (let i = 0; i < args.length; i += 2) {
    const key = keys[args[i]];
    if (!key || !args[i + 1] || seen.has(key)) throw new Error('Use --root PATH --out PRIVATE_DIRECTORY --chrome EXECUTABLE [--profile desktop|mobile] [--entry /motion-studio/index.html]');
    seen.add(key); options[key] = args[i + 1];
  }
  if (!options.out || !options.chrome || !['desktop', 'mobile'].includes(options.profile)
      || !options.entry.startsWith('/motion-studio/') || options.entry.startsWith('//')) throw new Error('Missing or invalid audit options');
  validateAuditUrl(`http://127.0.0.1:1${options.entry}`);
  return options;
}

export async function runAudit(options) {
  if (!['desktop', 'mobile'].includes(options.profile) || !options.entry?.startsWith('/motion-studio/')) throw new Error('Invalid local audit profile or entry');
  validateAuditUrl(`http://127.0.0.1:1${options.entry}`);
  const root = await realpath(options.root);
  const before = await sourceSnapshot(root, options.fixture === true);
  const out = resolve(options.out);
  // Raw reports stay out of the source tree and must not overwrite earlier evidence.
  const outParent = await realpath(dirname(out));
  if (out === root || inside(root, out) || outParent === root || inside(root, outParent)) throw new Error('Evidence must be outside the audited repository');
  await mkdir(out, { recursive: false });
  const profileDir = await mkdtemp(join(tmpdir(), 'hub-quality-profile-'));
  let context, server;
  try {
    server = await serveStudio(root);
    const url = validateAuditUrl(`${server.origin}${options.entry}`, server.origin);
    context = await chromium.launchPersistentContext(profileDir, {
      executablePath: resolve(options.chrome), headless: true,
      viewport: options.profile === 'desktop' ? { width: 1350, height: 940 } : { width: 412, height: 823 },
      args: ['--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
        '--proxy-server=http://127.0.0.1:9', '--proxy-bypass-list=127.0.0.1;localhost;[::1]',
        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1, EXCLUDE [::1]', '--disable-background-networking'],
    });
    const blockedRequests = [];
    await context.route('**/*', async route => {
      const requestUrl = new URL(route.request().url());
      if (requestUrl.origin !== server.origin) { blockedRequests.push(requestUrl.protocol); await route.abort('blockedbyclient'); }
      else await route.continue();
    });
    const pageErrors = [];
    const observedPages = new WeakSet();
    const observePage = page => {
      if (!observedPages.has(page)) {
        observedPages.add(page);
        page.on('pageerror', () => pageErrors.push('unhandled page error'));
      }
    };
    context.on('page', observePage);
    for (const page of context.pages()) observePage(page);
    const page = context.pages()[0] || await context.newPage();
    const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 20_000 });
    if (response?.status() !== 200 || page.url() !== url) throw new Error('Local Studio page did not load without redirection');
    const axe = await bounded(new AxeBuilder({ page }).analyze(), 'axe', 30_000);
    const debugPort = Number((await readFile(join(profileDir, 'DevToolsActivePort'), 'utf8')).split('\n')[0]);
    if (!Number.isInteger(debugPort) || debugPort < 1 || debugPort > 65535) throw new Error('Invalid local Chromium debugging port');
    const result = await bounded(lighthouse(url, {
      port: debugPort, hostname: '127.0.0.1', logLevel: 'error', output: 'json',
      enableErrorReporting: false,
      onlyCategories: ['performance', 'accessibility'], maxWaitForLoad: 20_000,
    }, options.profile === 'desktop' ? desktopConfig : undefined), 'Lighthouse', 60_000);
    if (!result?.lhr || result.lhr.runtimeError) throw new Error('Lighthouse did not produce a valid audit');
    const lhr = result.lhr;
    const metrics = {
      performance: lhr.categories.performance.score * 100,
      accessibility: lhr.categories.accessibility.score * 100,
      lcp_ms: lhr.audits['largest-contentful-paint'].numericValue,
      cls: lhr.audits['cumulative-layout-shift'].numericValue,
      critical_axe: axe.violations.filter(item => item.impact === 'critical').length,
      axe_violations: axe.violations.length,
      page_errors: pageErrors.length,
      blocked_external_requests: blockedRequests.length,
      inp_ms: null,
      inp_status: 'not measured; navigation-only lab audit is not a production INP measurement',
    };
    const packageLock = await readFile(new URL('./package-lock.json', import.meta.url));
    const after = await sourceSnapshot(root, options.fixture === true);
    if (JSON.stringify(before) !== JSON.stringify(after)) throw new Error('Audited sources changed while the quality audit was running; evidence rejected');
    const summary = {
      schema_version: 1, kind: options.fixture === true ? 'synthetic-fixture-quality-audit' : 'motion-studio-local-lab-quality-audit', audited_at_utc: new Date().toISOString(),
      profile: options.profile, url, metrics, budgets: DEFAULT_BUDGETS,
      ...evaluateBudgets(metrics),
      tool_versions: { lighthouse: lhr.lighthouseVersion, axe: axe.testEngine.version, chromium: context.browser()?.version(), playwright: playwrightVersion, node: process.version },
      package_lock_sha256: createHash('sha256').update(packageLock).digest('hex'),
      source_commit: before.commit, source_sha256: before.hashes,
      limits: ['Single local laboratory run, not a field measurement', 'No FPS or INP claim', 'No production, authenticated profile or external service was used', 'Raw axe incomplete/manual checks require human review'],
    };
    await writeFile(join(out, 'lighthouse.json'), JSON.stringify(lhr, null, 2) + '\n');
    await writeFile(join(out, 'axe.json'), JSON.stringify(axe, null, 2) + '\n');
    await writeFile(join(out, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
    return summary;
  } finally {
    try { await context?.close(); }
    finally {
      try { await server?.close(); }
      finally {
        // Chromium can flush profile files immediately after process exit.
        await delay(50);
        await rm(profileDir, { recursive: true, force: true });
      }
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const summary = await runAudit(parseArgs(process.argv.slice(2)));
    console.log(JSON.stringify(summary, null, 2));
    if (!summary.passed) process.exitCode = 1;
  } catch (error) { console.error(`Quality audit failed: ${error.message}`); process.exitCode = 2; }
}
