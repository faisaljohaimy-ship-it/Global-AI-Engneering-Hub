// Motion orchestrator: given what is known about a project, its audience and the device
// in front of the user, choose motions and the settings to create them with. It is a
// pure function over the registry, so an agent, a build script and a page all get the
// same answer for the same input, and every choice comes with its reasons.
//
//   const { motions } = JSON.parse(readFileSync('packages/motion-engines/registry.json'));
//   const picks = recommend({ projectType: 'dashboard', goal: 'operational', language: 'ar', device }, { motions });
//   const instance = await motion.create(picks[0].id, { container, ...picks[0].options });

const TIERS = ['low', 'medium', 'high'];
const COST = { low: 0, medium: 1, high: 2 };

/** What each kind of project usually needs: modules it draws on and the tags that fit it. */
const PROJECTS = {
  marketing: { modules: ['camera', 'glass', 'lighting', 'particles', 'typography', 'product', 'atmosphere', 'quantum', 'compositions'], tags: ['hero', 'reveal', 'headline', 'background', 'cinematic', 'brand'] },
  product: { modules: ['product', 'glass', 'icons', 'camera', 'lighting', 'transitions', 'micro'], tags: ['product', 'reveal', 'feature', 'hero', 'showcase'] },
  dashboard: { modules: ['dashboard', 'micro', 'networks', 'neural', 'twin', 'transitions', 'story'], tags: ['chart', 'data', 'status', 'indicator', 'kpi', 'alert', 'diagram'] },
  app: { modules: ['micro', 'transitions', 'icons', 'typography', 'dashboard'], tags: ['button', 'transition', 'feedback', 'navigation', 'loading', 'interaction'] },
  documentation: { modules: ['neural', 'networks', 'twin', 'physics', 'shaders', 'story'], tags: ['diagram', 'explainer', 'science', 'process'] },
  presentation: { modules: ['story', 'dashboard', 'typography', 'camera', 'product', 'compositions'], tags: ['timeline', 'title', 'headline', 'reveal', 'kpi', 'executive'] },
  film: { modules: ['compositions', 'camera', 'lighting', 'atmosphere', 'particles', 'glass', 'quantum', 'hologram'], tags: ['cinematic', 'film', 'sequence', 'hero', 'opening'] },
  'digital-twin': { modules: ['twin', 'networks', 'hologram', 'camera', 'dashboard'], tags: ['spatial', 'model', 'sensor', 'asset', 'diagram'] },
};
const AUDIENCES = {
  executive: { tags: ['executive', 'kpi', 'timeline', 'hero', 'title'], calm: true },
  technical: { tags: ['diagram', 'science', 'gpu', 'process', 'explainer'] },
  operator: { tags: ['status', 'alert', 'indicator', 'data'], calm: true },
  public: { tags: ['hero', 'reveal', 'brand', 'cinematic'] },
};
const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

function deviceOf(context) {
  const device = context.device ?? {};
  const viewport = context.viewport ?? device.viewport ?? null;
  const small = Boolean(viewport && viewport.width && Math.min(viewport.width, viewport.height) < 500);
  let tier = TIERS.includes(device.tier) ? device.tier : 'high';
  const memory = device.deviceMemory ?? device.memory;
  if (memory !== undefined && memory !== null) tier = TIERS[Math.min(TIERS.indexOf(tier), memory <= 2 ? 0 : memory <= 4 ? 1 : 2)];
  if (device.saveData) tier = 'low';
  return {
    tier, small,
    webgl2: device.webgl2 !== false,
    webgpu: device.webgpu === true,
    browser: device.engine ?? device.browser ?? 'unknown',
    coarse: Boolean(device.coarsePointer),
    saveData: Boolean(device.saveData),
    reducedMotion: Boolean(context.accessibility?.reducedMotion ?? device.reducedMotion),
  };
}

/** The settings to create a motion with on this device: the plan never refuses a motion, it scales it. */
export function plan(entry, context = {}) {
  const device = deviceOf(context);
  const arabic = String(context.language ?? '').toLowerCase().startsWith('ar');
  const options = { quality: 'auto', direction: arabic ? 'rtl' : 'ltr', locale: arabic ? 'ar' : 'en' };
  const notes = [];
  if (device.reducedMotion) {
    options.reducedMotion = true;
    notes.push('Reduced motion: one still frame is shown and nothing is scheduled.');
  }
  // A weak device starts lower instead of discovering the problem on screen; the governor can still raise it.
  const budgetMs = context.budget?.frameMs;
  const heavy = COST[entry.requirements.cost] === 2;
  if (device.tier === 'low' || device.saveData) options.quality = 'low';
  else if (device.tier === 'medium' && heavy) options.quality = 'low';
  else if ((device.tier === 'medium' || device.small) && COST[entry.requirements.cost] >= 1) options.quality = 'medium';
  if (options.quality !== 'auto') notes.push(`Starts at the ${options.quality} tier for this device; call optimize({ targetFrameMs }) to let it adapt while it runs.`);
  if (Number.isFinite(budgetMs)) options.targetFrameMs = budgetMs;
  if (entry.requirements.gpu === 'webgl2' && !device.webgl2) notes.push('No WebGL2 on this device: the motion shows its still poster.');
  if (entry.requirements.gpu === 'webgpu' && !device.webgpu) notes.push('No WebGPU on this device: the motion runs its WebGL2 fallback.');
  if (entry.controls.input && context.interaction && context.interaction !== 'none') options.interactive = true;
  const brand = (context.brand?.colors ?? []).filter((colour) => HEX.test(String(colour)));
  if (brand.length) {
    // The brand palette replaces the motion's palette position by position: background first.
    options.colors = entry.controls.colors.map((fallback, index) => brand[index] ?? brand[brand.length - 1] ?? fallback);
  }
  return { options, notes };
}

/**
 * Ranked motions for a context. Each result has { id, score, reasons, options, notes }.
 * Nothing unverified is offered unless `includeUnverified` is set.
 */
export function recommend(context = {}, { motions, limit = 8, includeUnverified = false } = {}) {
  if (!Array.isArray(motions)) throw new TypeError('recommend needs the registry: { motions }');
  const device = deviceOf(context);
  const project = PROJECTS[context.projectType] ?? null;
  const audience = AUDIENCES[context.audience] ?? null;
  const wanted = new Set([...(context.tags ?? []), ...(context.purpose ? [context.purpose] : [])].map((tag) => String(tag).toLowerCase()));
  const arabic = String(context.language ?? '').toLowerCase().startsWith('ar');
  const operational = context.goal === 'operational';
  const cinematic = context.goal === 'cinematic';
  const maxCost = COST[context.budget?.maxCost] ?? 2;
  const results = [];
  for (const entry of motions) {
    if (!includeUnverified && entry.status !== 'operational') continue;
    if (context.module && entry.category.key !== context.module) continue;
    if (context.engine && entry.engine !== context.engine) continue;
    const cost = COST[entry.requirements.cost];
    if (cost > maxCost) continue;
    const reasons = [];
    let score = 0;
    const tags = new Set(entry.tags.map((tag) => tag.toLowerCase()));
    const hits = [...wanted].filter((tag) => tags.has(tag) || entry.id.includes(tag) || entry.name.en.toLowerCase().includes(tag));
    if (hits.length) {
      score += 6 * hits.length;
      reasons.push(`matches ${hits.join(', ')}`);
    } else if (wanted.size) score -= 4;
    if (project) {
      const rank = project.modules.indexOf(entry.category.key);
      if (rank >= 0) {
        score += 5 - Math.min(4, rank * 0.5);
        reasons.push(`${entry.category.en} suits a ${context.projectType} project`);
      } else score -= 2;
      const shared = project.tags.filter((tag) => tags.has(tag));
      if (shared.length) score += 1.5 * shared.length;
    }
    if (audience) {
      const shared = audience.tags.filter((tag) => tags.has(tag));
      if (shared.length) {
        score += 1.5 * shared.length;
        reasons.push(`fits a ${context.audience} audience`);
      }
      if (audience.calm && cost === 2) score -= 1.5;
    }
    if (operational) {
      // Operational screens want short, cheap, purposeful motion.
      score += (2 - cost) * 1.5 + (entry.kind === 'oneshot' ? 1 : 0) + (entry.controls.duration.default <= 3000 ? 1 : -1);
      if (cost === 0) reasons.push('light enough for a working screen');
    }
    if (cinematic) {
      score += cost * 1.2 + (entry.engine === 'composition' ? 2 : 0) + (entry.controls.camera && Object.keys(entry.controls.camera).length ? 1 : 0);
      if (entry.engine === 'composition') reasons.push('a layered composition');
    }
    if (arabic) {
      if (entry.compatibility.rtl === 'text') {
        score += 2;
        reasons.push('shows Arabic text, laid out right to left');
      } else if (entry.compatibility.rtl === 'mirror') {
        score += 0.5;
        reasons.push('mirrors for right-to-left');
      }
    }
    if (context.interaction && context.interaction !== 'none' && entry.controls.input) {
      score += 3;
      reasons.push('reacts to the pointer');
    }
    // Device fit: prefer what runs at full quality here; never drop a motion that can still degrade.
    const tierIndex = TIERS.indexOf(device.tier);
    if (cost > tierIndex) {
      score -= (cost - tierIndex) * 2.5;
      reasons.push(`heavier than this device's ${device.tier} tier: it will start at reduced quality`);
    }
    if (device.small && cost === 2) score -= 1.5;
    if (entry.requirements.gpu === 'webgl2' && !device.webgl2) {
      score -= 8;
      reasons.push('needs WebGL2, which this device lacks: only its poster would show');
    }
    if (entry.requirements.gpu === 'webgpu') {
      if (device.webgpu) {
        score += 1;
        reasons.push('uses WebGPU on this device');
      } else reasons.push('falls back to WebGL2 here');
    }
    if (device.reducedMotion) reasons.push('shown as one still frame under reduced motion');
    const made = plan(entry, context);
    results.push({ id: entry.id, name: entry.name, module: entry.category.key, engine: entry.engine, score: Number(score.toFixed(2)), reasons, ...made });
  }
  return results.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id)).slice(0, limit);
}

/** The vocabulary recommend() understands, for building a form or a prompt. */
export const VOCABULARY = Object.freeze({
  projectType: Object.keys(PROJECTS), audience: Object.keys(AUDIENCES), goal: ['cinematic', 'operational'],
  interaction: ['none', 'hover', 'pointer', 'touch'], tier: TIERS, cost: Object.keys(COST), language: ['ar', 'en'],
});
