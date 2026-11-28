#!/usr/bin/env node
// A read-only Model Context Protocol server for the engine-native motions, over stdio.
// It lets a coding agent find a motion, read its controls and get the code and the
// install command for it. It reads registry.json and nothing else: no network, no file
// writes, no code execution on behalf of the caller.
//
//   { "mcpServers": { "hub-motion-engines": { "command": "node", "args": ["packages/motion-engines/mcp/server.mjs"] } } }
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { recommend, VOCABULARY } from '../orchestrator.mjs';

const sdk = resolve(fileURLToPath(new URL('..', import.meta.url)));
const registry = JSON.parse(readFileSync(join(sdk, 'registry.json'), 'utf8'));
const byId = new Map(registry.motions.map((entry) => [entry.id, entry]));
const brief = (entry) => ({ id: entry.id, number: entry.number, name: entry.name, module: entry.category.key, engine: entry.engine, kind: entry.kind, status: entry.status, tags: entry.tags });
const text = (value) => ({ content: [{ type: 'text', text: JSON.stringify(value, null, 2) }] });
const string = (description, values) => ({ type: 'string', description, ...(values ? { enum: values } : {}) });

const TOOLS = [
  {
    name: 'motion_list',
    description: 'List the engine-native motions of the hub, optionally filtered. Status "operational" means current browser evidence exists for the exact source.',
    inputSchema: { type: 'object', properties: { module: string('Module key, for example "glass" or "dashboard"'), engine: string('Rendering engine'), status: string('operational, failing or implemented-unverified'), query: string('Words to look for in the id, names, summary and tags') }, additionalProperties: false },
    call({ module, engine, status, query } = {}) {
      const words = String(query ?? '').toLowerCase().split(/\s+/).filter(Boolean);
      const rows = registry.motions.filter((entry) => (!module || entry.category.key === module) && (!engine || entry.engine === engine) && (!status || entry.status === status)
        && words.every((word) => [entry.id, entry.name.en, entry.name.ar, entry.summary.en, entry.summary.ar, ...entry.tags].join(' ').toLowerCase().includes(word)));
      return text({ count: rows.length, motions: rows.map(brief) });
    },
  },
  {
    name: 'motion_get',
    description: 'Everything recorded about one motion: names in Arabic and English, engine, controls (duration, easing, colours, parameters, camera, text, input), requirements, compatibility, benchmark, licence, test command and evidence.',
    inputSchema: { type: 'object', properties: { id: string('Motion id, for example "quantum-light-tunnel"') }, required: ['id'], additionalProperties: false },
    call({ id }) {
      const entry = byId.get(id);
      if (!entry) throw new Error(`Unknown motion: ${id}`);
      return text(entry);
    },
  },
  {
    name: 'motion_recommend',
    description: 'Choose motions for a project and a device, with the reasons for each choice and the options to create it with (quality tier, direction, reduced motion, brand colours).',
    inputSchema: {
      type: 'object',
      properties: {
        projectType: string('Kind of project', VOCABULARY.projectType), audience: string('Who watches', VOCABULARY.audience), goal: string('Cinematic or operational', VOCABULARY.goal),
        language: string('ar or en'), interaction: string('How the user interacts', VOCABULARY.interaction), module: string('Restrict to one module'),
        tags: { type: 'array', items: { type: 'string' }, description: 'What the motion is for: hero, loading, chart, transition, headline…' },
        device: { type: 'object', description: 'tier (low|medium|high), webgl2, webgpu, deviceMemory, saveData, reducedMotion, engine (browser)' },
        viewport: { type: 'object', description: '{ width, height } in CSS pixels' },
        budget: { type: 'object', description: '{ maxCost: low|medium|high, frameMs }' },
        brand: { type: 'object', description: '{ colors: ["#rrggbb", …] } background first' },
        limit: { type: 'number' }, includeUnverified: { type: 'boolean' },
      },
      additionalProperties: false,
    },
    call({ limit, includeUnverified, ...context } = {}) {
      return text(recommend(context, { motions: registry.motions, limit: Math.min(25, Math.max(1, Number(limit) || 8)), includeUnverified: includeUnverified === true }));
    },
  },
  {
    name: 'motion_usage',
    description: 'The code to use one motion and the command that installs only that motion into a registered project.',
    inputSchema: { type: 'object', properties: { id: string('Motion id') }, required: ['id'], additionalProperties: false },
    call({ id }) {
      const entry = byId.get(id);
      if (!entry) throw new Error(`Unknown motion: ${id}`);
      return text({ id, status: entry.status, usage: entry.usage, install: entry.integration, test: entry.test, source: entry.source, preview: entry.preview, license: entry.license });
    },
  },
];

function handle(message) {
  const { id, method, params } = message;
  const reply = (result) => ({ jsonrpc: '2.0', id, result });
  const fail = (code, text) => ({ jsonrpc: '2.0', id, error: { code, message: text } });
  if (method === 'initialize') {
    return reply({ protocolVersion: params?.protocolVersion ?? '2024-11-05', capabilities: { tools: {} }, serverInfo: { name: 'hub-motion-engines', version: registry.sdk_version }, instructions: 'Read-only catalogue of browser-verified motions. Use motion_recommend to choose, motion_get for controls, motion_usage for code.' });
  }
  if (method === 'ping') return reply({});
  if (method === 'tools/list') return reply({ tools: TOOLS.map(({ name, description, inputSchema }) => ({ name, description, inputSchema, annotations: { readOnlyHint: true } })) });
  if (method === 'tools/call') {
    const tool = TOOLS.find((item) => item.name === params?.name);
    if (!tool) return fail(-32602, `Unknown tool: ${params?.name}`);
    try {
      return reply(tool.call(params.arguments ?? {}));
    } catch (error) {
      return reply({ content: [{ type: 'text', text: String(error.message ?? error) }], isError: true });
    }
  }
  if (id === undefined) return null; // a notification: nothing to answer
  return fail(-32601, `Method not found: ${method}`);
}

createInterface({ input: process.stdin }).on('line', (line) => {
  if (!line.trim()) return;
  let answer;
  try {
    answer = handle(JSON.parse(line));
  } catch {
    answer = { jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } };
  }
  if (answer) process.stdout.write(JSON.stringify(answer) + '\n');
});
