import {createMotionSystem} from '../packages/motion-sdk/index.mjs';
import * as catalog from '../motion-library/expansion/catalog.mjs';

const words = {
  ar: {skip:'تجاوز إلى مساحة العمل',studio:'استوديو الحركة',language:'اللغة',theme:'المظهر',existingLab:'المختبر السابق ↗',title:'من الفكرة إلى الحركة.',lead:'اختر مشهدًا، حرّك خطّه الزمني، واختبره قبل أن تستورده إلى مشروعك.',recipes:'مشهد محلي',engine:'المحرك',installation:'التثبيت',zeroDependencies:'بلا تبعيات',loading:'جارٍ تحميل الفهرس المحلي المثبّت…',library:'مكتبة المشاهد',search:'ابحث باسم أو فكرة',searchPlaceholder:'مدار، حروف، شبكة…',category:'الفئة',allCategories:'كل الفئات',tier:'المستوى',allTiers:'الكل',basic:'أساسي',advanced:'متقدم',empty:'لا توجد مشاهد تطابق هذا البحث.',previous:'السابق',next:'التالي',pointerHint:'حرّك المؤشر داخل المشهد لاختبار التفاعل',timeline:'الخط الزمني',play:'تشغيل',pause:'إيقاف مؤقت',resume:'استئناف',reverse:'عكس',stop:'إعادة ضبط',direction:'اتجاه المشهد',motionPreference:'الحركة',systemPreference:'تفضيل النظام',reduced:'حركة مخففة',full:'حركة كاملة',profile:'جودة الرسم',balanced:'متوازنة',mobile:'مناسبة للجوال',quality:'تفاصيل عالية',intensity:'شدة التأثير',exportSvg:'تصدير إطار SVG',exportJson:'تصدير المشهد JSON',benchmark:'قياس زمن الرسم',integration:'استيراد انتقائي إلى مشروعك',scope:'هذه معاينة محلية بـCanvas2D. تصدير الإطار ليس فيديو؛ محركات WebGPU وThree.js وRemotion لا تُفعَّل من هذه الواجهة. قياس زمن الرسم ليس قياس FPS أو أداء إنتاجي.',footer:'قدرات مثبتة، استخدام انتقائي، ونتائج قابلة للفحص.',idle:'جاهز',playing:'قيد التشغيل',paused:'متوقف مؤقتًا',finished:'انتهى',downloaded:'تم تصدير الإطار المحلي.',failed:'تعذّر تشغيل المعاينة. راجع الفهرس المحلي.',measurement:'زمن الرسم P95',milliseconds:'مللي ثانية',notFps:'قياس CPU محلي، وليس FPS إنتاجيًا.'},
  en: {skip:'Skip to workspace',studio:'Motion Studio',language:'Language',theme:'Theme',existingLab:'Existing Motion Lab ↗',title:'From an idea to motion.',lead:'Choose a scene, seek its timeline, and inspect it before importing it into your project.',recipes:'Local scenes',engine:'Engine',installation:'Installation',zeroDependencies:'Zero dependencies',loading:'Loading the pinned local catalog…',library:'Scene library',search:'Find a name or idea',searchPlaceholder:'Orbit, type, network…',category:'Category',allCategories:'All categories',tier:'Level',allTiers:'All levels',basic:'Basic',advanced:'Advanced',empty:'No scenes match this search.',previous:'Previous',next:'Next',pointerHint:'Move the pointer inside the scene to inspect interaction',timeline:'Timeline',play:'Play',pause:'Pause',resume:'Resume',reverse:'Reverse',stop:'Reset',direction:'Scene direction',motionPreference:'Motion',systemPreference:'System preference',reduced:'Reduced motion',full:'Full motion',profile:'Drawing profile',balanced:'Balanced',mobile:'Mobile',quality:'High detail',intensity:'Intensity',exportSvg:'Export SVG frame',exportJson:'Export scene JSON',benchmark:'Measure drawing time',integration:'Selective project import',scope:'This is a local Canvas2D preview. Frame export is not video. WebGPU, Three.js and Remotion are not enabled here. Drawing time is not production FPS or Web Vitals.',footer:'Pinned capabilities, selective use, inspectable results.',idle:'Ready',playing:'Playing',paused:'Paused',finished:'Finished',downloaded:'Exported the local frame.',failed:'Preview failed. Inspect the local catalog.',measurement:'Drawing P95',milliseconds:'ms',notFps:'Local CPU timing, not production FPS.'},
};
const $ = (selector) => document.querySelector(selector);
const sdk = createMotionSystem();
let language = 'ar', clip, selected, pageNumber = 0, uiFrame, pointerFrame, filtered = [];
let parameters = {rtl: true, reducedMotion: 'auto', intensity: 1, detail: 12, pixelRatio: Math.min(devicePixelRatio || 1, 2), interaction: {x: 0, y: 0}};
const L = (key) => words[language][key] ?? key;
const categoryId = (row) => typeof row.category === 'object' ? row.category.id : row.category_id ?? row.category;
const title = (row) => row[`name_${language}`] ?? row.name_en ?? row.id;
const secondary = (row) => row[language === 'ar' ? 'name_en' : 'name_ar'] ?? '';

function translate() {
  document.documentElement.lang = language; document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
  $('#language').setAttribute('aria-label', L('language'));
  for (const item of document.querySelectorAll('[data-i18n]')) item.textContent = L(item.dataset.i18n);
  for (const item of document.querySelectorAll('[data-placeholder]')) item.placeholder = L(item.dataset.placeholder);
  renderList(); if (selected) labelScene(); paintTransport();
}
function labelScene() {
  $('#motion-name').textContent = title(selected); $('#motion-secondary').textContent = secondary(selected);
  $('#motion-id').textContent = selected.id; $('#motion-tier').textContent = L(selected.tier === 'advanced' ? 'advanced' : 'basic');
  $('#integration-code').textContent = `import {createMotionSystem} from './packages/motion-sdk/index.mjs';\nimport * as catalog from './motion-library/expansion/catalog.mjs';\nconst motion = createMotionSystem();\nmotion.registerCatalog(catalog);\nconst clip = motion.create('${selected.id}', {\n  container, width: 640, height: 360, rtl: ${parameters.rtl},\n  reducedMotion: 'auto', seed: 1\n});\nclip.play(); // clip.destroy() when the view unmounts`;
}
function paintTransport() {
  if (!clip) return;
  $('#progress').value = String(Math.round(clip.progress * 1000));
  $('#time-label').textContent = `${Math.round(clip.progress * 100)}%`;
  const next = L(clip.state); if ($('#state-label').textContent !== next) $('#state-label').textContent = next;
}
function stopUiFrame() { if (uiFrame != null) cancelAnimationFrame(uiFrame); uiFrame = undefined; }
function animateUi() {
  paintTransport(); if (clip?.state === 'playing') uiFrame = requestAnimationFrame(animateUi); else uiFrame = undefined;
}
function select(id, {autoplay = false, updateUrl = false} = {}) {
  const row = catalog.getDefinition(id); if (!row) throw new Error('Unknown scene');
  stopUiFrame(); clip?.destroy(); selected = row;
  const width = Math.min(960, Math.max(256, Math.floor($('#stage').clientWidth)));
  clip = sdk.create(row.id, {container: $('#stage'), width, height: Math.round(width * 9 / 16), ...parameters});
  labelScene(); renderList(); paintTransport();
  if (updateUrl) { const url = new URL(location.href); url.searchParams.set('motion', id); history.replaceState(null,'',url); }
  if (autoplay) { clip.play(); animateUi(); }
  return snapshot();
}
function snapshot() {
  return {ready: true, id: selected?.id, registered: sdk.getCapabilities().registered,
    state: clip?.state, progress: clip?.progress, live_instances: sdk.getCapabilities().live_instances,
    direction: parameters.rtl ? 'rtl' : 'ltr', reducedMotion: parameters.reducedMotion,
    canvas_count: $('#stage').querySelectorAll('canvas').length};
}
function renderList() {
  const needle = $('#search').value.trim().toLocaleLowerCase();
  filtered = catalog.definitions.filter((row) => ($('#category').value === 'all' || categoryId(row) === $('#category').value) && ($('#tier').value === 'all' || row.tier === $('#tier').value) && JSON.stringify([row.id,row.name_ar,row.name_en,categoryId(row)]).toLocaleLowerCase().includes(needle));
  const pages = Math.max(1, Math.ceil(filtered.length / 30)); pageNumber = Math.min(pageNumber, pages - 1);
  const fragment = document.createDocumentFragment();
  for (const [index, row] of filtered.slice(pageNumber * 30, pageNumber * 30 + 30).entries()) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'scene-button';
    button.dataset.motion = row.id; button.setAttribute('aria-pressed', String(row.id === selected?.id));
    const number = document.createElement('span'); number.className = 'scene-number'; number.textContent = String(pageNumber * 30 + index + 1).padStart(3, '0'); number.setAttribute('aria-hidden','true');
    const text = document.createElement('span'); text.className = 'scene-copy';
    const name = document.createElement('strong'); name.textContent = title(row);
    const english = document.createElement('small'); english.textContent = secondary(row);
    text.append(name,english); button.append(number,text);
    button.addEventListener('click', () => act(() => select(row.id, {autoplay: true, updateUrl: true})));
    fragment.append(button);
  }
  $('#catalog-list').replaceChildren(fragment); $('#match-count').textContent = String(filtered.length);
  $('#empty').hidden = filtered.length > 0; $('#page-label').textContent = `${pageNumber + 1} / ${pages}`;
  $('#previous').disabled = pageNumber === 0; $('#next').disabled = pageNumber >= pages - 1;
}
function act(action) {
  try { $('#operation-result').textContent = ''; action(); paintTransport(); }
  catch (error) { $('#operation-result').textContent = `${L('failed')} ${error.message}`; throw error; }
}
function download(format) {
  clip.pause(); stopUiFrame(); const data = clip.export(format);
  const url = URL.createObjectURL(new Blob([data], {type: format === 'svg' ? 'image/svg+xml' : 'application/json'}));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${selected.id}.${format}`; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000); $('#operation-result').textContent = L('downloaded');
}

try {
  sdk.registerCatalog(catalog);
  $('#recipe-count').textContent = String(catalog.definitions.length);
  const categories = [...new Set(catalog.definitions.map(categoryId))];
  for (const id of categories) {
    const row = catalog.definitions.find((item) => categoryId(item) === id);
    const option = document.createElement('option'); option.value = id;
    option.textContent = row.category_ar ?? row.category?.name_ar ?? id; $('#category').append(option);
  }
  $('#loading').hidden = true; $('#loaded').hidden = false;
  const requested = new URL(location.href).searchParams.get('motion');
  select(catalog.definitions.some((item) => item.id === requested) ? requested : catalog.definitions[0].id); translate();
  $('#language').addEventListener('change', () => { language = $('#language').value; translate(); });
  $('#theme').addEventListener('click', () => { document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'; });
  for (const id of ['search','category','tier']) $( `#${id}`).addEventListener(id === 'search' ? 'input' : 'change', () => { pageNumber = 0; renderList(); });
  $('#previous').addEventListener('click', () => { pageNumber--; renderList(); });
  $('#next').addEventListener('click', () => { pageNumber++; renderList(); });
  $('#play').addEventListener('click', () => act(() => { clip.play(); animateUi(); }));
  $('#resume').addEventListener('click', () => act(() => { clip.resume(); animateUi(); }));
  $('#pause').addEventListener('click', () => act(() => { clip.pause(); stopUiFrame(); }));
  $('#reverse').addEventListener('click', () => act(() => { clip.reverse(); }));
  $('#stop').addEventListener('click', () => act(() => { clip.stop(); stopUiFrame(); }));
  $('#progress').addEventListener('input', () => act(() => { clip.pause(); stopUiFrame(); clip.render(Number($('#progress').value) / 1000); }));
  $('#direction').addEventListener('change', () => act(() => { parameters.rtl = $('#direction').value === 'rtl'; clip.configure({rtl: parameters.rtl}); labelScene(); }));
  $('#reduced').addEventListener('change', () => act(() => { parameters.reducedMotion = $('#reduced').value; clip.configure({reducedMotion: parameters.reducedMotion}); }));
  $('#profile').addEventListener('change', () => act(() => { const result = clip.optimize({profile: $('#profile').value}); parameters.detail = result.detail; parameters.pixelRatio = result.pixelRatio; }));
  $('#intensity').addEventListener('input', () => act(() => { parameters.intensity = Number($('#intensity').value) / 100; clip.configure({intensity: parameters.intensity}); }));
  $('#export-svg').addEventListener('click', () => act(() => download('svg')));
  $('#export-json').addEventListener('click', () => act(() => download('json')));
  $('#benchmark').addEventListener('click', () => act(() => {
    clip.pause(); stopUiFrame(); const result = clip.benchmark({frames: 60});
    $('#operation-result').textContent = `${L('measurement')}: ${result.p95_ms.toFixed(3)} ${L('milliseconds')}. ${L('notFps')}`;
  }));
  $('#stage').addEventListener('pointermove', (event) => {
    const bounds = $('#stage').getBoundingClientRect();
    parameters.interaction = {x: Math.max(-1,Math.min(1,(event.clientX - bounds.left) / bounds.width * 2 - 1)),y: Math.max(-1,Math.min(1,(event.clientY - bounds.top) / bounds.height * 2 - 1))};
    if (pointerFrame == null) pointerFrame = requestAnimationFrame(() => { pointerFrame = undefined; clip.configure({interaction: parameters.interaction}); });
  });
  window.addEventListener('pagehide', () => { stopUiFrame(); if (pointerFrame != null) cancelAnimationFrame(pointerFrame); sdk.destroyAll(); });
  window.__motionStudio = Object.freeze({snapshot, select, definitions: () => sdk.definitions(),
    preview: (progress) => { const scene = clip.render(progress); paintTransport(); return scene; },
    exportFrame: (format) => clip.export(format), benchmark: (frames = 60) => clip.benchmark({frames}),
    capabilities: () => sdk.getCapabilities()});
  document.documentElement.dataset.studioReady = 'true';
} catch (error) {
  $('#loaded').hidden = true; $('#loading').hidden = false; $('#loading').textContent = `${L('failed')} ${error.message}`;
  document.documentElement.dataset.studioReady = 'false'; throw error;
}
