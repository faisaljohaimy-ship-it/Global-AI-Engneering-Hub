// The orchestrator is a pure function: the same context gives the same choice, every
// choice is explained, and a weak device is given a plan instead of a refusal.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { plan, recommend, VOCABULARY } from '../orchestrator.mjs';

const { motions } = JSON.parse(readFileSync(new URL('../registry.json', import.meta.url), 'utf8'));
const entry = (overrides = {}) => ({
  id: 'x-a', name: { en: 'A', ar: 'أ' }, category: { key: 'glass', en: 'Glass' }, engine: 'webgl2-glsl', kind: 'loop', tags: ['hero'], status: 'operational',
  controls: { duration: { default: 4000 }, colors: ['#000000', '#111111', '#222222'], camera: {}, input: null },
  requirements: { gpu: 'webgl2', cost: 'high' }, compatibility: { rtl: 'neutral' }, ...overrides,
});

test('the same context always gives the same ranked answer, with reasons', () => {
  const context = { projectType: 'film', goal: 'cinematic', language: 'ar', device: { tier: 'high', webgl2: true } };
  // Evidence comes and goes with the core; ranking is tested on everything that exists.
  const first = recommend(context, { motions, includeUnverified: true });
  assert.deepEqual(first, recommend(context, { motions, includeUnverified: true }));
  assert.ok(first.length > 0);
  assert.ok(first.every((pick) => pick.reasons.length > 0 && pick.options.direction === 'rtl' && pick.options.locale === 'ar'));
  assert.ok(first.every((pick, index) => index === 0 || first[index - 1].score >= pick.score));
});

test('only motions with browser evidence are offered unless asked otherwise', () => {
  const pool = [entry(), entry({ id: 'x-b', status: 'implemented-unverified' }), entry({ id: 'x-c', status: 'failing' })];
  assert.deepEqual(recommend({}, { motions: pool }).map((pick) => pick.id), ['x-a']);
  assert.equal(recommend({}, { motions: pool, includeUnverified: true }).length, 3);
});

test('a weak device gets a lower starting tier, not a refusal', () => {
  const heavy = entry();
  assert.equal(plan(heavy, { device: { tier: 'high' } }).options.quality, 'auto');
  assert.equal(plan(heavy, { device: { tier: 'medium' } }).options.quality, 'low');
  assert.equal(plan(heavy, { device: { tier: 'high', deviceMemory: 2 } }).options.quality, 'low');
  assert.equal(plan(heavy, { device: { tier: 'high', saveData: true } }).options.quality, 'low');
  assert.equal(plan(entry({ requirements: { gpu: 'none', cost: 'medium' } }), { viewport: { width: 390, height: 844 } }).options.quality, 'medium');
  const picks = recommend({ device: { tier: 'low' } }, { motions: [heavy] });
  assert.equal(picks.length, 1, 'still offered');
  assert.match(picks[0].reasons.join(' '), /reduced quality/);
});

test('missing GPU features are explained and cost the motion its rank', () => {
  const gl = entry();
  const cpu = entry({ id: 'x-cpu', engine: 'canvas2d', requirements: { gpu: 'none', cost: 'low' } });
  const picks = recommend({ device: { webgl2: false } }, { motions: [gl, cpu] });
  assert.equal(picks[0].id, 'x-cpu');
  assert.match(picks[1].reasons.join(' '), /WebGL2/);
  const gpu = entry({ id: 'x-gpu', engine: 'webgpu-wgsl', requirements: { gpu: 'webgpu', cost: 'high' } });
  assert.match(plan(gpu, { device: { webgpu: false } }).notes.join(' '), /fallback/);
  assert.match(recommend({ device: { webgpu: true } }, { motions: [gpu] })[0].reasons.join(' '), /WebGPU/);
});

test('accessibility, language, interaction, brand and budget shape the plan', () => {
  const text = entry({ id: 'x-text', compatibility: { rtl: 'text' }, requirements: { gpu: 'none', cost: 'low' } });
  const button = entry({ id: 'x-button', controls: { ...entry().controls, input: { en: 'pointer', ar: 'مؤشر' } }, requirements: { gpu: 'none', cost: 'low' } });
  assert.equal(plan(text, { accessibility: { reducedMotion: true } }).options.reducedMotion, true);
  assert.equal(recommend({ language: 'ar' }, { motions: [entry(), text] })[0].id, 'x-text');
  assert.equal(recommend({ interaction: 'pointer' }, { motions: [entry(), button] })[0].id, 'x-button');
  assert.equal(plan(button, { interaction: 'pointer' }).options.interactive, true);
  assert.equal(plan(button, { interaction: 'none' }).options.interactive, undefined);
  assert.deepEqual(plan(text, { brand: { colors: ['#ffffff', '#0a0a0a', 'not-a-colour'] } }).options.colors, ['#ffffff', '#0a0a0a', '#0a0a0a']);
  assert.equal(plan(text, { budget: { frameMs: 8 } }).options.targetFrameMs, 8);
  assert.deepEqual(recommend({ budget: { maxCost: 'low' } }, { motions: [entry(), text] }).map((pick) => pick.id), ['x-text']);
});

test('an operational goal prefers light, short motion and a cinematic goal prefers compositions', () => {
  const light = entry({ id: 'x-light', kind: 'oneshot', controls: { ...entry().controls, duration: { default: 800 } }, requirements: { gpu: 'none', cost: 'low' } });
  const film = entry({ id: 'x-film', engine: 'composition' });
  assert.equal(recommend({ goal: 'operational' }, { motions: [film, light] })[0].id, 'x-light');
  assert.equal(recommend({ goal: 'cinematic' }, { motions: [light, film] })[0].id, 'x-film');
  assert.ok(VOCABULARY.projectType.includes('dashboard') && VOCABULARY.goal.length === 2);
  assert.throws(() => recommend({}, {}), TypeError);
});

test('the MCP server answers the protocol, lists read-only tools and refuses unknown ones', async () => {
  const server = spawn(process.execPath, [fileURLToPath(new URL('../mcp/server.mjs', import.meta.url))], { stdio: ['pipe', 'pipe', 'inherit'] });
  const answers = [];
  let buffer = '';
  server.stdout.on('data', (chunk) => {
    buffer += chunk;
    const lines = buffer.split('\n');
    buffer = lines.pop();
    answers.push(...lines.filter(Boolean).map((line) => JSON.parse(line)));
  });
  const send = (message) => server.stdin.write(JSON.stringify(message) + '\n');
  send({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'test', version: '0' } } });
  send({ jsonrpc: '2.0', method: 'notifications/initialized' });
  send({ jsonrpc: '2.0', id: 2, method: 'tools/list' });
  send({ jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'motion_get', arguments: { id: motions[0].id } } });
  send({ jsonrpc: '2.0', id: 4, method: 'tools/call', params: { name: 'motion_get', arguments: { id: 'no-such-motion' } } });
  send({ jsonrpc: '2.0', id: 5, method: 'tools/call', params: { name: 'delete_everything', arguments: {} } });
  send({ jsonrpc: '2.0', id: 6, method: 'tools/call', params: { name: 'motion_recommend', arguments: { projectType: 'film', limit: 3 } } });
  server.stdin.write('not json\n');
  send({ jsonrpc: '2.0', id: 7, method: 'resources/list' });
  server.stdin.end();
  await new Promise((closed) => server.on('close', closed));
  const by = (id) => answers.find((answer) => answer.id === id);
  assert.equal(by(1).result.serverInfo.name, 'hub-motion-engines');
  assert.deepEqual(by(2).result.tools.map((tool) => tool.name), ['motion_list', 'motion_get', 'motion_recommend', 'motion_usage']);
  assert.ok(by(2).result.tools.every((tool) => tool.annotations.readOnlyHint === true && tool.inputSchema.additionalProperties === false));
  assert.equal(JSON.parse(by(3).result.content[0].text).id, motions[0].id);
  assert.equal(by(4).result.isError, true);
  assert.equal(by(5).error.code, -32602);
  assert.ok(JSON.parse(by(6).result.content[0].text).length <= 3);
  assert.equal(by(7).error.code, -32601);
  assert.ok(answers.some((answer) => answer.id === null && answer.error.code === -32700), 'malformed input is answered, not fatal');
  assert.equal(answers.length, 8, 'the notification got no answer');
});
