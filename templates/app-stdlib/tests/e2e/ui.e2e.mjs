// Browser end-to-end test: real server, real Chromium via Playwright for Node.
// Creates, edits and deletes records through the UI in every configured locale
// (Arabic RTL and English LTR), checks labels, keyboard reachability, security
// headers and that the page makes no request outside its own origin.
// Prints one JSON report on stdout; exit code 0 only when every case passed.
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const schema = JSON.parse(readFileSync(path.join(ROOT, 'app', 'schema.json'), 'utf8'));
const i18n = JSON.parse(readFileSync(path.join(ROOT, 'static', 'i18n.json'), 'utf8'));
const results = [];
const external = [];
const problems = [];

function report(extra) {
  const ok = results.length > 0 && results.every((row) => row.status === 'passed');
  process.stdout.write(JSON.stringify({ schema: 'app.e2e-report/1', ok, cases: results, ...extra }) + '\n');
  return ok;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function step(id, fn) {
  try {
    await fn();
    results.push({ id, status: 'passed' });
  } catch (error) {
    results.push({ id, status: 'failed', error: String((error && error.message) || error).slice(0, 400) });
  }
}

function startServer(dbPath) {
  return new Promise((resolve, reject) => {
    const python = process.env.APP_PYTHON || 'python3';
    const child = spawn(python, ['-I', path.join(ROOT, 'manage.py'), 'serve', '--host', '127.0.0.1', '--port', '0', '--db', dbPath],
      { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] });
    let buffer = '';
    const timer = setTimeout(() => reject(new Error('server did not start within 20 s')), 20000);
    child.stdout.on('data', (chunk) => {
      buffer += chunk;
      const match = buffer.match(/listening on (http:\/\/127\.0\.0\.1:\d+)/);
      if (match) {
        clearTimeout(timer);
        resolve({ child, base: match[1] });
      }
    });
    child.stderr.on('data', () => {});
    child.on('exit', (code) => { clearTimeout(timer); reject(new Error('server exited with ' + code)); });
  });
}

function textValue(entity, field, locale, tag) {
  const base = locale === 'ar' ? `اختبار ${i18n.ar.entities[entity.name].singular} ${tag}` : `E2E ${entity.name} ${tag}`;
  return base.slice(0, field.max || 200);
}

async function fillForm(page, entity, locale, tag, created) {
  const L = i18n[locale];
  let label = null;
  for (const field of entity.fields) {
    const control = page.getByLabel(L.fields[entity.name][field.name], { exact: true });
    if (field.type === 'text') {
      const value = textValue(entity, field, locale, tag);
      await control.fill(value);
      if (field.name === entity.label_field) label = value;
    } else if (field.type === 'email') {
      await control.fill(`e2e-${locale}-${tag}@example.invalid`.slice(0, field.max || 254));
    } else if (field.type === 'enum') {
      const choice = field.values[tag.endsWith('2') && field.values.length > 1 ? 1 : 0];
      const shown = (L.values[entity.name] && L.values[entity.name][field.name] && L.values[entity.name][field.name][choice]) || choice;
      await control.selectOption({ label: shown });
    } else if (field.type === 'bool') {
      await control.setChecked(!tag.endsWith('2'));
    } else if (field.type === 'int' || field.type === 'number') {
      const low = field.min ?? 0;
      const value = Math.min(field.max ?? 1000, Math.max(low, 3));
      await control.fill(String(value));
    } else if (field.type === 'date') {
      await control.fill('2026-12-01');
    } else if (field.type === 'datetime') {
      await control.fill('2026-12-01T10:30');
    }
  }
  for (const ref of entity.references) {
    const control = page.getByLabel(L.fields[entity.name][ref.field], { exact: true });
    if (created[ref.entity]) await control.selectOption({ label: created[ref.entity] });
    else if (ref.required) await control.selectOption({ index: 1 });
  }
  for (const link of entity.links) {
    const control = page.getByLabel(L.fields[entity.name][link.field], { exact: true });
    const count = await control.locator('option').count();
    if (count > 0) await control.selectOption([{ index: 0 }]);
  }
  return label;
}

async function openEntity(page, entity, locale) {
  await page.getByRole('button', { name: i18n[locale].entities[entity.name].plural, exact: true }).click();
  await page.waitForFunction((name) => document.querySelector(`#entity-nav button[data-entity="${name}"]`)?.getAttribute('aria-current') === 'page'
    && !document.getElementById('main').hasAttribute('aria-busy'), entity.name);
}

async function rows(page) {
  return page.locator('#records tbody tr').count();
}

async function main() {
  let playwright;
  try {
    playwright = require('playwright');
  } catch (error) {
    report({ error: 'playwright is not available: ' + error.message });
    return 2;
  }
  const tmp = mkdtempSync(path.join(tmpdir(), 'app-e2e-'));
  let server = null;
  let browser = null;
  try {
    server = await startServer(path.join(tmp, 'e2e.sqlite3'));
    const executablePath = process.env.APP_CHROMIUM_EXECUTABLE;
    browser = await playwright.chromium.launch(executablePath ? { executablePath } : {});
    const context = await browser.newContext();
    await context.route('**/*', (route) => {
      const url = new URL(route.request().url());
      if (url.origin === server.base) return route.continue();
      external.push(url.origin);
      return route.abort();
    });
    await context.addInitScript(() => {
      window.__csp = [];
      document.addEventListener('securitypolicyviolation', (event) => window.__csp.push(event.violatedDirective));
    });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', (error) => problems.push('pageerror: ' + error.message));
    page.on('console', (msg) => { if (msg.type() === 'error') problems.push('console: ' + msg.text()); });

    let firstResponse = null;
    for (const locale of schema.app.locales) {
      const L = i18n[locale];
      const created = {};
      const response = await page.goto(server.base + '/');
      firstResponse = firstResponse || response;
      await page.waitForSelector('body[data-ready="true"]');
      await step(`e2e:${locale}:language`, async () => {
        await page.getByRole('button', { name: L.name, exact: true }).click();
        await page.waitForFunction(([lang, dir]) => document.documentElement.lang === lang && document.documentElement.dir === dir, [locale, L.dir]);
        assert((await page.textContent('#app-title')).trim() === L.app.title, 'title is not localized');
        assert((await page.getByRole('button', { name: L.ui.save, exact: true }).count()) === 1, 'save button is not localized');
      });
      for (const entity of schema.entities) {
        await step(`e2e:${locale}:${entity.table}:create`, async () => {
          await openEntity(page, entity, locale);
          const before = await rows(page);
          const label = await fillForm(page, entity, locale, `${locale}-1`, created);
          await page.getByRole('button', { name: L.ui.save, exact: true }).click();
          await page.waitForFunction((count) => document.querySelectorAll('#records tbody tr').length === count, before + 1);
          if (label) await page.locator('#records tbody tr', { hasText: label }).first().waitFor();
          assert((await page.textContent('#status')).trim().length > 0, 'no status message after saving');
          created[entity.name] = label;
        });
      }
      for (const entity of schema.entities) {
        await step(`e2e:${locale}:${entity.table}:update`, async () => {
          await openEntity(page, entity, locale);
          const row = created[entity.name]
            ? page.locator('#records tbody tr', { hasText: created[entity.name] }).first()
            : page.locator('#records tbody tr').last();
          await row.getByRole('button', { name: L.ui.edit }).click();
          const label = await fillForm(page, entity, locale, `${locale}-2`, created);
          await page.getByRole('button', { name: L.ui.save, exact: true }).click();
          await page.waitForFunction(() => !document.getElementById('main').hasAttribute('aria-busy'));
          if (label) {
            await page.locator('#records tbody tr', { hasText: label }).first().waitFor();
            created[entity.name] = label;
          } else {
            await page.waitForFunction(() => document.querySelector('#status').textContent.trim().length > 0);
          }
        });
      }
      for (const entity of [...schema.entities].reverse()) {
        await step(`e2e:${locale}:${entity.table}:delete`, async () => {
          await openEntity(page, entity, locale);
          const before = await rows(page);
          const row = created[entity.name]
            ? page.locator('#records tbody tr', { hasText: created[entity.name] }).first()
            : page.locator('#records tbody tr').last();
          await row.getByRole('button', { name: L.ui.delete }).click();
          await page.getByRole('button', { name: L.ui.confirmDelete }).click();
          await page.waitForFunction((count) => document.querySelectorAll('#records tbody tr').length === count, before - 1);
        });
      }
    }

    await step('e2e:labels', async () => {
      const current = await page.evaluate(() => document.documentElement.lang);
      for (const entity of schema.entities) {
        await openEntity(page, entity, current);
        const missing = await page.evaluate(() => {
          const bad = [];
          for (const node of document.querySelectorAll('#record-form input, #record-form select, #record-form textarea')) {
            const text = Array.from(node.labels || []).map((label) => label.textContent.trim()).join('');
            if (!text) bad.push(node.id || node.name);
          }
          for (const node of document.querySelectorAll('button, a[href]')) {
            const name = (node.getAttribute('aria-label') || node.textContent || '').trim();
            if (!name) bad.push('unnamed ' + node.tagName);
          }
          if (!document.querySelector('main') || !document.querySelector('h1') || !document.documentElement.lang) bad.push('landmarks');
          return bad;
        });
        assert(missing.length === 0, 'controls without labels: ' + missing.join(', '));
      }
    });

    await step('e2e:keyboard', async () => {
      await page.goto(server.base + '/');
      await page.waitForSelector('body[data-ready="true"]');
      const seen = [];
      for (let i = 0; i < 80; i += 1) {
        await page.keyboard.press('Tab');
        seen.push(await page.evaluate(() => {
          const node = document.activeElement;
          return node ? (node.id || node.getAttribute('data-locale') || node.getAttribute('data-entity') || node.tagName) : '';
        }));
      }
      assert(seen[0] === 'skip-link', 'the first Tab stop is not the skip link: ' + seen[0]);
      for (const locale of schema.app.locales) assert(seen.includes(locale), 'language button not reachable: ' + locale);
      for (const entity of schema.entities) assert(seen.includes(entity.name), 'navigation not reachable: ' + entity.name);
      const firstField = 'f-' + schema.entities[0].fields[0].name;
      assert(seen.includes(firstField), 'first form field not reachable by keyboard');
      const second = schema.entities[schema.entities.length - 1];
      await page.focus(`#entity-nav button[data-entity="${second.name}"]`);
      await page.keyboard.press('Enter');
      await page.waitForFunction((name) => document.querySelector(`#entity-nav button[data-entity="${name}"]`)?.getAttribute('aria-current') === 'page', second.name);
      await page.focus('#skip-link');
      await page.keyboard.press('Enter');
      assert(await page.evaluate(() => document.activeElement && document.activeElement.id === 'main'), 'skip link does not move focus to main');
    });

    await step('e2e:headers', async () => {
      const headers = firstResponse.headers();
      assert((headers['content-security-policy'] || '').includes("frame-ancestors 'none'"), 'CSP frame-ancestors missing');
      assert(!(headers['content-security-policy'] || '').includes('unsafe-inline'), 'CSP allows inline code');
      assert(headers['x-content-type-options'] === 'nosniff', 'nosniff missing');
    });

    await step('e2e:csp', async () => {
      const violations = await page.evaluate(() => window.__csp || []);
      assert(violations.length === 0, 'CSP violations: ' + violations.join(', '));
      assert(problems.filter((text) => !text.includes('409') && !text.includes('Failed to load resource')).length === 0,
        'page errors: ' + problems.join(' | '));
    });

    await step('e2e:no-external-requests', async () => {
      assert(external.length === 0, 'requests outside the application origin: ' + [...new Set(external)].join(', '));
    });

    const browserVersion = browser.version();
    let playwrightVersion = 'unknown';
    try { playwrightVersion = require('playwright/package.json').version; } catch (_) { /* version is informational */ }
    return report({ runner: 'playwright', playwright_version: playwrightVersion, browser: 'chromium ' + browserVersion }) ? 0 : 1;
  } catch (error) {
    report({ error: String((error && error.message) || error).slice(0, 400) });
    return 1;
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) server.child.kill('SIGTERM');
    rmSync(tmp, { recursive: true, force: true });
  }
}

process.exitCode = await main();
