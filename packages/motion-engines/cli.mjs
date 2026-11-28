#!/usr/bin/env node
// Command line for the engine-native motions.
//
//   node packages/motion-engines/cli.mjs list [--module m] [--engine e] [--status s] [--json]
//   node packages/motion-engines/cli.mjs info <id>
//   node packages/motion-engines/cli.mjs recommend --project dashboard --goal operational --language ar [--tier low] [--tags a,b] [--no-webgl2]
//   node packages/motion-engines/cli.mjs brief                     which of the 200 requested motions exist and are proven
//   node packages/motion-engines/cli.mjs verify [--module m] [--id id] [--browser firefox] [--write]
//   node packages/motion-engines/cli.mjs sheet --module m --out FILE.png
//   node packages/motion-engines/cli.mjs export <id> --out DIR [--format mp4|webm|png] [--fps 30] [--width 1280] [--height 720] [--seconds n] [--direction rtl]
//   node packages/motion-engines/cli.mjs registry [--check]
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { recommend, VOCABULARY } from './orchestrator.mjs';

const sdk = resolve(fileURLToPath(new URL('.', import.meta.url)));
const [command, ...rest] = process.argv.slice(2);
const flag = (name) => rest.includes(`--${name}`);
const option = (name, fallback) => {
  const index = rest.indexOf(`--${name}`);
  return index >= 0 && rest[index + 1] && !rest[index + 1].startsWith('--') ? rest[index + 1] : fallback;
};
const positional = rest.find((value, index) => !value.startsWith('--') && (index === 0 || !rest[index - 1].startsWith('--') || ['json', 'write', 'check', 'no-webgl2', 'webgpu', 'reduced-motion', 'unverified'].includes(rest[index - 1].slice(2))));
const registry = () => JSON.parse(readFileSync(join(sdk, 'registry.json'), 'utf8'));
const run = (script, args) => process.exit(spawnSync(process.execPath, [join(sdk, script), ...args], { stdio: 'inherit' }).status ?? 1);
const print = (value) => console.log(typeof value === 'string' ? value : JSON.stringify(value, null, 2));

switch (command) {
  case 'list': {
    const rows = registry().motions.filter((entry) => (!option('module') || entry.category.key === option('module'))
      && (!option('engine') || entry.engine === option('engine')) && (!option('status') || entry.status === option('status')));
    if (flag('json')) print(rows.map((entry) => ({ id: entry.id, number: entry.number, name: entry.name, module: entry.category.key, engine: entry.engine, kind: entry.kind, status: entry.status })));
    else for (const entry of rows) console.log(`${String(entry.number).padStart(3)}  ${entry.id.padEnd(44)} ${entry.engine.padEnd(14)} ${entry.status.padEnd(22)} ${entry.name.en}`);
    if (!flag('json')) console.log(`${rows.length} motions`);
    break;
  }
  case 'info': {
    const entry = registry().motions.find((item) => item.id === positional);
    if (!entry) {
      console.error(`Unknown motion: ${positional ?? '(none given)'}`);
      process.exit(2);
    }
    print(entry);
    break;
  }
  case 'recommend': {
    const context = {
      projectType: option('project'), audience: option('audience'), goal: option('goal'), language: option('language'),
      interaction: option('interaction'), module: option('module'), engine: option('engine'),
      tags: (option('tags') ?? '').split(',').filter(Boolean),
      budget: { maxCost: option('max-cost'), frameMs: option('frame-ms') ? Number(option('frame-ms')) : undefined },
      accessibility: { reducedMotion: flag('reduced-motion') },
      viewport: option('viewport') ? { width: Number(option('viewport').split('x')[0]), height: Number(option('viewport').split('x')[1]) } : undefined,
      device: { tier: option('tier'), webgl2: !flag('no-webgl2'), webgpu: flag('webgpu'), deviceMemory: option('memory') ? Number(option('memory')) : undefined, engine: option('browser') },
      brand: { colors: (option('colors') ?? '').split(',').filter(Boolean) },
    };
    const unknown = Object.entries({ projectType: context.projectType, audience: context.audience, goal: context.goal }).filter(([key, value]) => value && !VOCABULARY[key].includes(value));
    if (unknown.length) {
      console.error(unknown.map(([key, value]) => `Unknown ${key} "${value}". Use one of: ${VOCABULARY[key].join(', ')}`).join('\n'));
      process.exit(2);
    }
    const picks = recommend(context, { motions: registry().motions, limit: Number(option('limit', 8)), includeUnverified: flag('unverified') });
    if (flag('json')) print(picks);
    else if (!picks.length) console.log('No verified motion fits. Add --unverified to include motions without browser evidence.');
    else for (const pick of picks) console.log(`${String(pick.score).padStart(6)}  ${pick.id.padEnd(44)} ${pick.engine.padEnd(14)} ${pick.reasons.join('; ')}\n        create options: ${JSON.stringify(pick.options)}`);
    break;
  }
  case 'brief': {
    const { brief, counts } = registry();
    print({ requested: brief.requested, implemented: brief.implemented, operational: brief.operational, not_implemented: brief.not_implemented.length, by_status: counts.by_status, by_engine: counts.by_engine });
    break;
  }
  case 'verify': run('verify/browser.mjs', rest); break;
  case 'sheet': run('verify/sheet.mjs', rest); break;
  case 'registry': run('tools/build_registry.mjs', rest); break;
  case 'export': {
    const { exportMotion } = await import('./tools/export.mjs');
    try {
      print(await exportMotion({
        id: positional, out: option('out'), format: option('format', 'mp4'), fps: Number(option('fps', 30)),
        width: Number(option('width', 1280)), height: Number(option('height', 720)),
        seconds: option('seconds') ? Number(option('seconds')) : undefined, direction: option('direction', 'ltr'),
      }));
    } catch (error) {
      console.error(String(error.message ?? error));
      process.exit(1);
    }
    break;
  }
  default:
    console.error(readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').filter((line) => line.startsWith('//   ')).map((line) => line.slice(5)).join('\n'));
    process.exit(command ? 2 : 0);
}
