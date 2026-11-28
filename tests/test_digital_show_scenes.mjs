// Digital show kit (packages/digital-shows): every scene type is proven in headless Chromium.
// Frames change over time, a second run gives identical frame hashes, reduced motion is the
// settled frame, the settled state means what the scene claims, and labels stay readable.
// CPU Canvas2D only: no GPU, real-device or FPS claim.   node tests/test_digital_show_scenes.mjs
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as kit from '../packages/digital-shows/kit.mjs';
import { registryDocument } from '../packages/digital-shows/tools/build_registry.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pack = join(root, 'packages/digital-shows');
const registry = JSON.parse(readFileSync(join(pack, 'registry.json'), 'utf8'));
const ARABIC = /[؀-ۿ]/;

// Parameters for the scenes whose text has no default (plain typography supplied by a storyboard).
const SAMPLE = {
  'title-card': {
    ar: { kicker: 'التحول الرقمي في خدمة', heading: 'رؤية المملكة 2030', chips: ['مجتمع حيوي', 'اقتصاد مزدهر', 'وطن طموح'] },
    en: { kicker: 'Digital transformation in service of', heading: 'Saudi Vision 2030', chips: ['A vibrant society', 'A thriving economy', 'An ambitious nation'] },
  },
  'call-to-action': {
    ar: { heading: 'ابدأ بأمرٍ واحد', points: ['مواصفة', 'بناء', 'تحقّق'], action_label: 'ابدأ الآن', footer: 'تحوّل رقمي يمكن التحقق منه' },
    en: { heading: 'Start with one command', points: ['Specify', 'Build', 'Verify'], action_label: 'Start now', footer: 'Digital transformation you can verify' },
  },
  'kpi-gauge': { ar: { numerator: 6175, denominator: 6500 }, en: { numerator: 6175, denominator: 6500 } },
};
const paramsFor = (id, lang) => (SAMPLE[id] || {})[lang] || {};
const steps = Array.from({ length: 201 }, (_, i) => i / 200);

// ------------------------------------------------------------------ registry and source hygiene

assert.equal(readFileSync(join(pack, 'registry.json'), 'utf8'), registryDocument(), 'registry.json is stale: node packages/digital-shows/tools/build_registry.mjs');
assert.equal(registry.schema, 'gaie.digital-shows/1');
assert.equal(registry.kit_sha256, createHash('sha256').update(readFileSync(join(pack, 'kit.mjs'))).digest('hex'));
const REQUIRED = ['paper-to-digital', 'service-journey', 'data-pipeline', 'integration-mesh', 'approval-gate', 'kpi-gauge', 'audit-trail',
  'zero-trust-shield', 'command-to-spec', 'layer-stack', 'test-matrix', 'checkpoint-resume', 'call-to-action'];
assert.deepEqual(registry.scenes.map((scene) => scene.id), kit.SCENE_IDS);
for (const id of REQUIRED) assert(kit.SCENE_IDS.includes(id), `missing scene type ${id}`);
assert.equal(new Set(kit.SCENE_IDS).size, kit.SCENE_IDS.length);
for (const scene of registry.scenes) {
  assert.match(scene.id, /^[a-z][a-z0-9-]{2,40}$/);
  for (const lang of ['ar', 'en']) {
    const meaning = scene.meaning[lang];
    assert(typeof meaning === 'string' && meaning.length >= 30 && meaning.length <= 160, `${scene.id}: meaning.${lang}`);
    assert.equal((meaning.match(/[.!?؟]/g) || []).length, 1, `${scene.id}: meaning.${lang} must be one sentence`);
    assert(/[.]$/.test(meaning), `${scene.id}: meaning.${lang} ends with a full stop`);
    assert.equal(ARABIC.test(meaning), lang === 'ar', `${scene.id}: meaning.${lang} script`);
  }
  assert(Object.keys(scene.params).length >= 3, `${scene.id}: parameter schema`);
  for (const [name, spec] of Object.entries(scene.params)) {
    assert(['label', 'labels', 'int', 'code'].includes(spec.type), `${scene.id}.${name}: type`);
    if (spec.type === 'int') { assert(Number.isInteger(spec.min) && Number.isInteger(spec.max) && spec.min <= spec.default && spec.default <= spec.max); continue; }
    const times = [].concat(spec.label_in);
    assert(times.every((value) => value > 0 && value <= 0.9), `${scene.id}.${name}: labels are fully visible by 90 % of the shot`);
    assert(spec.max_chars >= 4 && spec.max_chars <= 40, `${scene.id}.${name}: max_chars`);
  }
  for (const lang of ['ar', 'en']) assert.deepEqual(Object.keys(scene.defaults[lang]).sort(), Object.keys(scene.params).sort(), `${scene.id}: defaults.${lang}`);
}
assert.deepEqual(registry.themes['digital-transformation'].excluded, ['flags', 'emblems', 'logos', 'maps', 'portraits']);
assert.equal(registry.fonts.files.length, 8);
for (const font of registry.fonts.files) {
  assert.equal(createHash('sha256').update(readFileSync(join(pack, 'fonts', font.file))).digest('hex'), font.sha256, font.file);
}
assert.match(readFileSync(join(pack, 'fonts', registry.fonts.notice), 'utf8'), /SIL Open Font License 1\.1/);

// The kit is a pure function of time and parameters: nothing in its code can read a clock, a random
// source, the network or an image (comments are not code).
const code = readFileSync(join(pack, 'kit.mjs'), 'utf8').split('\n').filter((line) => !line.trim().startsWith('//')).join('\n');
for (const banned of ['Math.random', 'Date', 'performance', 'setTimeout', 'setInterval', 'requestAnimationFrame', 'fetch(', 'XMLHttpRequest',
  'new Image', 'drawImage', 'import(', 'localStorage', 'navigator', 'document.', 'window.', 'eval(', 'Function(']) {
  assert(!code.includes(banned), `kit.mjs must not use ${banned}`);
}

// ------------------------------------------------------------------ meaning-level state (no browser needed)

const states = (id, params, lang = 'ar') => steps.map((t) => kit.sceneState(id, t, params, lang));
const never = (rows, predicate, message) => rows.forEach((row, i) => assert(!predicate(row), `${message} at t=${steps[i]}`));
const rising = (rows, key) => rows.reduce((previous, row) => { assert(row[key] >= previous, `${key} must never fall`); return row[key]; }, -Infinity);
const fnv = (text, previous) => { let h = previous >>> 0; for (const ch of text) { h ^= ch.codePointAt(0); h = Math.imul(h, 0x01000193) >>> 0; } return h >>> 0; };

for (const lang of ['ar', 'en']) {
  let rows = states('approval-gate', {}, lang);
  never(rows, (s) => s.gate_open && !s.approved, 'the gate opened before approval');
  never(rows, (s) => s.passed && !s.gate_open, 'the request passed a closed gate');
  never(rows, (s) => s.opened_before_approval, 'opened_before_approval');
  assert(rows.some((s) => s.waiting && !s.approved), 'the request waits at the closed gate first');
  assert.deepEqual(rows.at(-1), { waiting: false, approved: true, gate_open: true, passed: true, opened_before_approval: false });

  rows = states('checkpoint-resume', {}, lang);
  never(rows, (s) => s.restarted_from_zero, 'work restarted from zero after the seal');
  assert(rows.some((s) => s.interrupted), 'there is an interruption');
  never(rows, (s) => s.sealed && s.progress < s.checkpoint_at - 1e-9, 'progress fell below the sealed checkpoint');
  assert.deepEqual([rows.at(-1).resumed_from, rows.at(-1).progress, rows.at(-1).complete], [3, 6, true]);
  assert.equal(kit.sceneState('checkpoint-resume', 1, { steps: 4, checkpoint_at: 6 }, lang).checkpoint_at, 3, 'the checkpoint is clamped inside the run');

  for (const [numerator, denominator, value] of [[6175, 6500, 95], [1, 3, 33.3], [0, 10, 0], [50, 50, 100], [70, 50, 100]]) {
    const end = kit.sceneState('kpi-gauge', 1, { numerator, denominator }, lang);
    assert.deepEqual([end.value, end.shown, end.verified], [value, value, true], `kpi ${numerator}/${denominator}`);
    assert.equal(end.value, Math.round(Math.min(numerator, denominator) / denominator * 1000) / 10);
    rising(states('kpi-gauge', { numerator, denominator }, lang), 'shown');
  }

  const entries = kit.SCENES['audit-trail'].defaults[lang].entries;
  let previous = 0x811c9dc5;
  const chain = entries.map((entry) => { previous = fnv(entry, previous); return previous.toString(16).padStart(8, '0'); });
  rows = states('audit-trail', {}, lang);
  assert.deepEqual(rows.at(-1), { entries: entries.length, stamped: entries.length, sealed: true, chain });
  never(rows, (s) => s.sealed && s.stamped < s.entries, 'sealed before every entry was stamped');
  rising(rows, 'stamped');
  const edited = kit.sceneState('audit-trail', 1, { entries: [entries[0], `${entries[1]}!`, ...entries.slice(2)] }, lang).chain;
  assert.equal(edited[0], chain[0]);
  assert(edited.slice(1).every((digest, i) => digest !== chain[i + 1]), 'an edited entry changes every later receipt');

  rows = states('zero-trust-shield', {}, lang);
  never(rows, (s) => s.allowed > 1 || (s.allowed === 1 && s.checks_passed < s.checks), 'a path was allowed without all its checks');
  assert.deepEqual(rows.at(-1), { requests: 5, denied: 4, checks: 3, checks_passed: 3, allowed: 1 });

  rows = states('data-pipeline', {}, lang);
  rising(rows, 'stored');
  never(rows, (s) => s.stored > s.valid_total, 'more records stored than were valid');
  assert.deepEqual(rows.at(-1), { records: 6, stored: 5, quarantined: 1, valid_total: 5 });

  rows = states('test-matrix', {}, lang);
  never(rows, (s) => s.all_green && s.failed > 0, 'all green with a failing test');
  assert(rows.some((s) => s.failed === 1 && !s.all_green), 'the failing test is visible before it is fixed');
  assert.deepEqual(rows.at(-1), { total: 24, passed: 24, failed: 0, all_green: true });

  for (const count of [4, 20, 24]) {
    rows = states('layer-stack', { count }, lang);
    rising(rows, 'lit');
    assert.deepEqual(rows.at(-1), { count, lit: count, verified: count, complete: true });
  }
  assert.deepEqual(states('service-journey', {}, lang).at(-1), { steps: 4, lit: 4, complete: true });
  assert.deepEqual(states('integration-mesh', {}, lang).at(-1), { systems: 4, connected: 4, mesh_ready: true });
  rows = states('paper-to-digital', {}, lang);
  never(rows, (s) => s.submitted && s.fields_valid < s.fields, 'submitted before every field was valid');
  assert.deepEqual(rows.at(-1), { fields: 3, fields_valid: 3, paper_archived: true, submitted: true });
  const spec = states('command-to-spec', {}, lang).at(-1);
  assert.deepEqual([spec.typed, spec.root, spec.branches, spec.leaves], [spec.command_length, true, 3, spec.leaves_total]);
  assert.deepEqual(states('title-card', SAMPLE['title-card'][lang], lang).at(-1), { heading_visible: true, chips: 3, chips_total: 3 });
  assert.deepEqual(states('call-to-action', SAMPLE['call-to-action'][lang], lang).at(-1), { points: 3, points_total: 3, action_ready: true });
}
assert.throws(() => kit.resolveParams('title-card', {}, 'ar'), /required/);
assert.throws(() => kit.resolveParams('service-journey', { speed: 2 }, 'ar'), /unknown parameter/);
assert.throws(() => kit.resolveParams('service-journey', { steps: ['a', 'b'] }, 'ar'), /3-5 labels/);
assert.throws(() => kit.resolveParams('layer-stack', { count: 99 }, 'ar'), /4-24/);
assert.throws(() => kit.resolveParams('layer-stack', { count: '20' }, 'ar'), /integer/);
assert.throws(() => kit.resolveParams('nope', {}, 'ar'), /unknown show scene/);
const a = kit.seeded(7), b = kit.seeded(7);
assert.deepEqual([a(), a(), a()], [b(), b(), b()], 'the seeded generator repeats');

// ------------------------------------------------------------------ headless Chromium

const require = createRequire(process.env.MOTION_PLAYWRIGHT_PACKAGE ? join(process.env.MOTION_PLAYWRIGHT_PACKAGE, 'package.json') : import.meta.url);
let playwright;
try { playwright = require('playwright'); } catch {
  console.log(JSON.stringify({ status: 'skipped', reason: 'Playwright is not installed here', state_checks: 'passed' }));
  process.exit(0);
}
const launch = async () => {
  if (process.env.MOTION_CHROMIUM_EXECUTABLE) return playwright.chromium.launch({ executablePath: process.env.MOTION_CHROMIUM_EXECUTABLE });
  try { return await playwright.chromium.launch(); } catch (error) {
    const fallback = '/opt/pw-browsers/chromium-1243/chrome-linux64/chrome';
    if (existsSync(fallback)) return playwright.chromium.launch({ executablePath: fallback });
    throw error;
  }
};

const WIDTH = 640, HEIGHT = 360, TIMES = [0.15, 0.4, 0.65, 0.9, 1];
const TYPES = { '.mjs': 'text/javascript', '.ttf': 'font/ttf' };
const browser = await launch();
const errors = [], refused = [];

async function pass() {
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 });
  page.on('pageerror', (error) => errors.push(String(error.message)));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url());
    const name = decodeURIComponent(url.pathname);
    if (url.origin !== 'http://localhost') { refused.push(url.origin); return route.abort(); }
    if (name === '/index.html') return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><meta charset="utf-8"><title>kit</title>' });
    const allowed = name === '/packages/digital-shows/kit.mjs' || /^\/packages\/digital-shows\/fonts\/[A-Za-z0-9.-]+\.ttf$/.test(name);
    if (!allowed) { refused.push(name); return route.fulfill({ status: 404, body: '' }); }
    return route.fulfill({ status: 200, contentType: TYPES[extname(name)], body: readFileSync(join(root, name)) });
  });
  await page.goto('http://localhost/index.html');
  const result = await page.evaluate(async ({ WIDTH, HEIGHT, TIMES, SAMPLE }) => {
    const kit = await import('/packages/digital-shows/kit.mjs');
    const style = document.createElement('style');
    style.textContent = kit.FONT_FILES.map((font) => `@font-face{font-family:"${font.family}";font-weight:${font.weight};src:url("/packages/digital-shows/fonts/${font.file}") format("truetype");}`).join('\n');
    document.head.append(style);
    for (const font of kit.FONT_FILES) await document.fonts.load(`${font.weight} 32px "${font.family}"`, 'عربي Aa 09');
    await document.fonts.ready;
    const fonts = kit.FONT_FILES.map((font) => ({ family: font.family, weight: font.weight, loaded: document.fonts.check(`${font.weight} 32px "${font.family}"`) }));
    const canvas = document.createElement('canvas');
    canvas.width = WIDTH; canvas.height = HEIGHT;
    const g = canvas.getContext('2d', { alpha: false, willReadFrequently: true });
    const probe = (font) => { g.font = font; return g.measureText('التحول الرقمي').width; };
    const arabicFont = Math.abs(probe('700 40px "IBM Plex Sans Arabic",monospace') - probe('700 40px monospace')) > 0.5
      && Math.abs(probe('700 40px "Alexandria",monospace') - probe('700 40px "IBM Plex Sans Arabic",monospace')) > 0.5;
    const hex = async (data) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)), (x) => x.toString(16).padStart(2, '0')).join('');
    const stage = { x0: WIDTH * kit.STAGE.x0, y0: HEIGHT * kit.STAGE.y0, x1: WIDTH * kit.STAGE.x1, y1: HEIGHT * kit.STAGE.y1 };
    const rows = [];
    for (const lang of ['ar', 'en']) for (const id of kit.SCENE_IDS) {
      const params = (SAMPLE[id] || {})[lang] || {};
      const env = { width: WIDTH, height: HEIGHT, lang, stage };
      const frames = [];
      let settled = null;
      for (const t of TIMES) {
        const drawn = kit.drawShowScene(g, id, t, params, env);
        const data = g.getImageData(0, 0, WIDTH, HEIGHT).data;
        let bright = 0;
        for (let i = 0; i < data.length; i += 4) if (data[i] + data[i + 1] + data[i + 2] > 300) bright += 1;
        frames.push({ t, sha256: await hex(data), bright });
        if (t === 1) settled = drawn;
      }
      kit.drawShowScene(g, id, 0.3, params, { ...env, reducedMotion: true });
      const reduced = await hex(g.getImageData(0, 0, WIDTH, HEIGHT).data);
      const quiet = kit.drawShowScene(g, id, 1, params, { ...env, glyphs: false });
      const withoutGlyphs = await hex(g.getImageData(0, 0, WIDTH, HEIGHT).data);
      rows.push({ id, lang, frames, reduced, withoutGlyphs, state: settled.state, labels: settled.labels, labelsWithoutGlyphs: quiet.labels.length });
    }
    return { fonts, arabicFont, rows, stage };
  }, { WIDTH, HEIGHT, TIMES, SAMPLE });
  await page.close();
  return result;
}

let summary;
try {
  const first = await pass(), second = await pass();
  assert.deepEqual(errors, [], 'page errors');
  assert.deepEqual(refused, [], 'the kit asked for something outside its allowlist');
  assert(first.fonts.every((font) => font.loaded), JSON.stringify(first.fonts));
  assert(first.arabicFont, 'Arabic text is drawn with the shipped fonts, not a fallback');
  assert.equal(first.rows.length, kit.SCENE_IDS.length * 2);
  const safe = { x0: WIDTH * 0.05, x1: WIDTH * 0.95, y0: HEIGHT * 0.05, y1: HEIGHT * 0.95 };
  first.rows.forEach((row, index) => {
    const where = `${row.id} (${row.lang})`, hashes = row.frames.map((frame) => frame.sha256);
    assert.deepEqual(hashes, second.rows[index].frames.map((frame) => frame.sha256), `${where}: a second run must give identical frames`);
    assert.equal(second.rows[index].reduced, row.reduced);
    assert(new Set(hashes).size >= 4, `${where}: frames must change over time`);
    assert.notEqual(hashes[0], hashes.at(-1));
    assert.equal(row.reduced, hashes.at(-1), `${where}: reduced motion is the settled frame`);
    assert(row.frames.every((frame) => frame.bright > 150), `${where}: something is drawn in every frame`);
    assert.deepEqual(row.state, kit.sceneState(row.id, 1, paramsFor(row.id, row.lang), row.lang), `${where}: the drawn state is the settled state`);
    const visible = row.labels.filter((label) => label.alpha > 0);
    assert(visible.length >= 3, `${where}: labels`);
    assert.equal(row.labelsWithoutGlyphs, row.labels.length);
    assert.notEqual(row.withoutGlyphs, hashes.at(-1), `${where}: labels are really drawn`);
    for (const label of visible) {
      assert.equal(label.alpha, 1, `${where}: "${label.text}" is fully visible in the settled state`);
      assert(label.size >= HEIGHT * 0.024, `${where}: "${label.text}" is ${label.size}px, below 2.4 % of the frame height`);
      assert(label.x0 >= safe.x0 && label.x1 <= safe.x1 && label.y0 >= safe.y0 && label.y1 <= safe.y1, `${where}: "${label.text}" leaves the title-safe area`);
      assert(label.y1 <= first.stage.y1 + 1 && label.y0 >= first.stage.y0 - 1, `${where}: "${label.text}" leaves the stage (the caption owns the rest)`);
    }
    if (row.lang === 'ar') assert(visible.some((label) => ARABIC.test(label.text)), `${where}: Arabic labels`);
    else assert(visible.every((label) => !ARABIC.test(label.text)), `${where}: no Arabic in the English cut`);
  });
  for (const id of kit.SCENE_IDS) {
    const ar = first.rows.find((row) => row.id === id && row.lang === 'ar'), en = first.rows.find((row) => row.id === id && row.lang === 'en');
    assert.notEqual(ar.frames.at(-1).sha256, en.frames.at(-1).sha256, `${id}: the Arabic cut is laid out right to left with its own labels`);
  }
  summary = { status: 'passed', scenes: kit.SCENE_IDS.length, languages: 2, frames_hashed: first.rows.length * (TIMES.length + 2) * 2,
    size: [WIDTH, HEIGHT], fonts_loaded: first.fonts.length, browser_version: browser.version(), page_errors: errors.length,
    external_requests: refused.length, gpu_claimed: false, real_devices_verified: false };
} finally {
  await browser.close();
}
console.log(JSON.stringify(summary));
