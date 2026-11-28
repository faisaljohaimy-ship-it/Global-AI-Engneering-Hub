// SPDX-License-Identifier: MIT
import * as camera from './nextgen-camera.mjs';
import * as originals from './nextgen-originals.mjs';

import * as systems from './nextgen-motion-systems.mjs';
import * as scenes from './nextgen-motion-scenes.mjs';
import * as ui from './nextgen-motion-ui.mjs';

import * as light from './nextgen-motion-light.mjs';
import * as physics from './nextgen-motion-physics.mjs';
import * as symbols from './nextgen-motion-symbols.mjs';
import * as particles from './nextgen-motion-particles.mjs';
import * as compositions from './nextgen-motion-compositions.mjs';

const catalogs = [camera, originals, systems, scenes, ui, light, physics, symbols, particles, compositions];
const entries = new Map();
for (const catalog of catalogs) {
  for (const definition of catalog.definitions) {
    if (entries.has(definition.id)) throw new Error('Duplicate original motion identity');
    entries.set(definition.id, {definition, sample: catalog.sampleMotion});
  }
}

export const definitions = Object.freeze([...entries.values()].map(entry => entry.definition));

export function sampleMotion(value, progress, options) {
  const id = typeof value === 'string' ? value : value?.id;
  const entry = entries.get(id);
  if (!entry) throw new RangeError('Unknown original motion');
  return entry.sample(id, progress, options);
}
