import {animationOptions, reducedMotionRequested, statusFor, validateComponent, mirroredKeyframes} from "../motion-library/runtime/core.mjs";
import {crossDissolveAtFrame} from "../motion-library/adapters/remotion.mjs";
import {orbitCameraAtProgress} from "../motion-library/adapters/three.mjs";
import {renderCounter, renderTypewriter, stagger} from "../motion-library/runtime/hub-motion.mjs";

const refs = Object.fromEntries([
  "indexedCount", "implementedCount", "testedCount", "usedCount", "filter", "implementedOnly",
  "resultCount", "motionList", "selectedCategory", "selectedTitle", "engineBadge", "indexedStatus",
  "implementedStatus", "testedStatus", "runtimeStatus", "usedStatus", "direction", "motionMode",
  "play", "stop", "stage", "preview", "previewNote",
].map((id) => [id, document.getElementById(id)]));

let catalog = [];
let components = [];
let componentsById = new Map();
let selected = null;
let activeAnimation = null;
let activeFrame = 0;
const report = {ready: false, indexed: 0, implemented: 0, tested: 0, used: 0, lastEngine: null, lastRunMs: null, error: null};
window.__motionLabReport = report;

async function fetchJson(path) {
  const response = await fetch(path, {credentials: "same-origin"});
  if (!response.ok) throw new Error(`Failed to load ${path}: ${response.status}`);
  return response.json();
}

function setText(element, value) {
  element.textContent = String(value);
}

function currentStatus(entry) {
  return statusFor(entry, componentsById);
}

function renderMetrics() {
  const statuses = catalog.map(currentStatus);
  report.indexed = statuses.length;
  report.implemented = statuses.filter((item) => item.implemented).length;
  report.tested = statuses.filter((item) => item.tested).length;
  report.used = statuses.filter((item) => item.used).length;
  setText(refs.indexedCount, report.indexed);
  setText(refs.implementedCount, report.implemented);
  setText(refs.testedCount, report.tested);
  setText(refs.usedCount, report.used);
}

function catalogLabel(entry) {
  const component = componentsById.get(entry.id);
  return component ? `${entry.category} · ${component.engine}` : `${entry.category} · indexed only`;
}

function filteredEntries() {
  const query = refs.filter.value.trim().toLocaleLowerCase();
  return catalog.filter((entry) => {
    const component = componentsById.get(entry.id);
    if (refs.implementedOnly.checked && !component) return false;
    const haystack = `${entry.id} ${entry.name} ${entry.category} ${component?.engine ?? ""}`.toLocaleLowerCase();
    return !query || haystack.includes(query);
  });
}

function renderCatalog() {
  const rows = filteredEntries();
  refs.motionList.replaceChildren();
  for (const entry of rows) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    const name = document.createElement("span");
    const meta = document.createElement("small");
    button.type = "button";
    button.className = "catalog-button";
    button.dataset.id = entry.id;
    button.setAttribute("aria-current", selected?.id === entry.id ? "true" : "false");
    name.textContent = entry.name;
    meta.textContent = catalogLabel(entry);
    button.append(name, meta);
    button.addEventListener("click", () => selectEntry(entry));
    item.append(button);
    refs.motionList.append(item);
  }
  setText(refs.resultCount, `${rows.length} of ${catalog.length} motions`);
}

function resetStage() {
  stopPlayback();
  const target = document.createElement("div");
  target.id = "preview";
  target.className = "motion-target";
  const labels = {
    "typography-word-stagger": "Motion respects words",
    "typography-typewriter": "مَرْحَبًا بِالعَالَم",
    "typography-counter-interpolation": "0",
    "ui-staggered-list": "List",
  };
  target.textContent = labels[selected?.id] ?? "Motion";
  refs.stage.replaceChildren(target);
  refs.preview = target;
}

function selectEntry(entry) {
  selected = entry;
  resetStage();
  const component = componentsById.get(entry.id);
  const status = currentStatus(entry);
  setText(refs.selectedCategory, entry.category);
  setText(refs.selectedTitle, entry.name);
  setText(refs.engineBadge, component?.engine ?? "indexed only");
  setText(refs.indexedStatus, status.indexed ? "yes" : "no");
  setText(refs.implementedStatus, status.implemented ? "yes" : "no");
  setText(refs.testedStatus, status.tested ? "automated" : "no");
  setText(refs.runtimeStatus, status.runtime);
  setText(refs.usedStatus, status.used ? "motion-lab" : "no");
  refs.play.disabled = !component;
  refs.stop.disabled = !component;
  setText(refs.previewNote, component ? "Ready. Playback starts only when Play is pressed." : "Indexed specification; executable source has not been implemented.");
  refs.stage.dir = refs.direction.value;
  renderCatalog();
}

function stopPlayback() {
  if (activeAnimation) {
    activeAnimation.cancel();
    activeAnimation = null;
  }
  if (activeFrame) {
    cancelAnimationFrame(activeFrame);
    activeFrame = 0;
  }
  refs.preview?.getAnimations().forEach((animation) => animation.cancel());
  if (refs.preview) refs.preview.className = "motion-target";
  refs.stage.classList.remove("reduce-motion");
}

async function loadSpec(component) {
  return fetchJson(`../motion-library/${component.spec}`);
}

async function loadSourceSpec(component) {
  return fetchJson(`../motion-library/${component.source_spec}`);
}

function isReduced() {
  return reducedMotionRequested(refs.motionMode.value, matchMedia("(prefers-reduced-motion: reduce)").matches);
}

function applyReduced(spec) {
  refs.stage.classList.add("reduce-motion");
  for (const [property, value] of Object.entries(spec.reduced_motion)) refs.preview.style[property] = value;
  setText(refs.previewNote, "Reduced-motion end state applied without animation.");
}

function runCss(component, spec) {
  refs.preview.className = "motion-target";
  refs.preview.getBoundingClientRect();
  refs.preview.classList.add(`run-${component.id}`);
}

function runWaapi(component, spec) {
  const frames = mirroredKeyframes(spec.keyframes, spec.rtl_mirror && refs.direction.value === "rtl");
  if (component.id === "typography-word-stagger") {
    const words = refs.preview.textContent.trim().split(/\s+/);
    refs.preview.replaceChildren();
    const animations = words.map((word, index) => {
      const span = document.createElement("span");
      span.textContent = `${word}${index === words.length - 1 ? "" : " "}`;
      span.style.display = "inline-block";
      refs.preview.append(span);
      return span.animate(frames, {...animationOptions(spec), delay: index * spec.stagger_ms});
    });
    activeAnimation = {cancel: () => animations.forEach((animation) => animation.cancel())};
    return;
  }
  activeAnimation = refs.preview.animate(frames, animationOptions(spec));
}

function runProgress(duration, draw, reduced) {
  if (reduced) {
    draw(1);
    activeAnimation = {cancel() {}};
    return;
  }
  let cancelled = false;
  const started = performance.now();
  const tick = (now) => {
    if (cancelled) return;
    const progress = Math.min(1, (now - started) / duration);
    draw(progress);
    if (progress < 1) activeFrame = requestAnimationFrame(tick);
    else activeFrame = 0;
  };
  activeAnimation = {
    cancel() {
      cancelled = true;
      if (activeFrame) cancelAnimationFrame(activeFrame);
      activeFrame = 0;
    },
  };
  activeFrame = requestAnimationFrame(tick);
}

async function runWaapiBehavior(component, reduced) {
  if (component.id === "ui-staggered-list") {
    const spec = await loadSourceSpec(component);
    const list = document.createElement("ol");
    for (let index = 1; index <= 4; index += 1) {
      const item = document.createElement("li");
      item.textContent = `Item ${index}`;
      list.append(item);
    }
    refs.stage.replaceChildren(list);
    refs.preview = list;
    const animations = stagger(list.children, spec, {each: 80, reducedMotion: reduced});
    activeAnimation = {cancel: () => animations.forEach((animation) => animation?.cancel())};
    return;
  }
  if (component.id === "typography-typewriter") {
    const text = "مَرْحَبًا بِالعَالَم";
    const line = document.createElement("p");
    line.dir = "rtl";
    line.lang = "ar";
    refs.stage.replaceChildren(line);
    refs.preview = line;
    runProgress(1200, (progress) => renderTypewriter(line, text, progress, "ar", "word"), reduced);
    return;
  }
  if (component.id === "typography-counter-interpolation") {
    const counter = document.createElement("span");
    refs.stage.replaceChildren(counter);
    refs.preview = counter;
    const locale = refs.direction.value === "rtl" ? "ar-SA" : "en";
    runProgress(1000, (progress) => renderCounter(counter, 0, 2500, progress, {locale}), reduced);
    return;
  }
  throw new Error(`Unknown runtime behavior: ${component.id}`);
}

function compileShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) || "Shader compile failed");
  return shader;
}

async function runGlsl(spec) {
  const canvas = document.createElement("canvas");
  canvas.width = 900;
  canvas.height = 500;
  refs.stage.replaceChildren(canvas);
  refs.preview = canvas;
  const gl = canvas.getContext("webgl", {alpha: false, antialias: true});
  if (!gl) throw new Error("WebGL is unavailable");
  const fragmentSource = await (await fetch(`../motion-library/${spec.shader}`, {credentials: "same-origin"})).text();
  const vertexSource = "attribute vec2 a_position; void main(){gl_Position=vec4(a_position,0.0,1.0);}";
  const program = gl.createProgram();
  gl.attachShader(program, compileShader(gl, gl.VERTEX_SHADER, vertexSource));
  gl.attachShader(program, compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) || "Shader link failed");
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
  gl.useProgram(program);
  const position = gl.getAttribLocation(program, "a_position");
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  gl.uniform2f(gl.getUniformLocation(program, "u_resolution"), canvas.width, canvas.height);
  const timeLocation = gl.getUniformLocation(program, "u_time");
  const started = performance.now();
  const draw = (now) => {
    gl.uniform1f(timeLocation, (now - started) / 1000);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    if (now - started < spec.duration_ms) activeFrame = requestAnimationFrame(draw);
  };
  activeFrame = requestAnimationFrame(draw);
}

function runRemotionAdapter(spec) {
  const outgoing = document.createElement("div");
  const incoming = document.createElement("div");
  outgoing.className = "dissolve-layer dissolve-out";
  incoming.className = "dissolve-layer dissolve-in";
  outgoing.textContent = "A";
  incoming.textContent = "B";
  refs.stage.replaceChildren(outgoing, incoming);
  refs.preview = incoming;
  const started = performance.now();
  const draw = (now) => {
    const elapsed = Math.min(spec.duration_ms, now - started);
    const frame = Math.round((elapsed / spec.duration_ms) * (spec.duration_frames - 1));
    const state = crossDissolveAtFrame(frame, spec.duration_frames);
    outgoing.style.opacity = state.outgoingOpacity;
    incoming.style.opacity = state.incomingOpacity;
    if (elapsed < spec.duration_ms) activeFrame = requestAnimationFrame(draw);
  };
  activeFrame = requestAnimationFrame(draw);
}

function runThreeAdapter(spec) {
  const canvas = document.createElement("canvas");
  canvas.width = 900;
  canvas.height = 500;
  refs.stage.replaceChildren(canvas);
  refs.preview = canvas;
  const context = canvas.getContext("2d");
  const started = performance.now();
  const draw = (now) => {
    const progress = Math.min(1, (now - started) / spec.duration_ms);
    const camera = orbitCameraAtProgress(progress, {radius: spec.radius, height: spec.height});
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = "#315b7d";
    context.lineWidth = 3;
    context.beginPath();
    context.ellipse(450, 250, 260, 110, 0, 0, Math.PI * 2);
    context.stroke();
    context.fillStyle = "#52d8ff";
    context.beginPath();
    context.arc(450 + camera.position.x / spec.radius * 260, 250 + camera.position.z / spec.radius * 110, 18, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = "#edf6ff";
    context.fillRect(420, 220, 60, 60);
    if (progress < 1) activeFrame = requestAnimationFrame(draw);
  };
  activeFrame = requestAnimationFrame(draw);
}

async function playSelected() {
  const component = componentsById.get(selected?.id);
  if (!component) return;
  resetStage();
  refs.stage.dir = refs.direction.value;
  report.lastEngine = component.engine;
  const started = performance.now();
  const reduced = isReduced();
  if (component.engine === "waapi-behavior") {
    await runWaapiBehavior(component, reduced);
  } else {
    const spec = await loadSpec(component);
    if (reduced) applyReduced(spec);
    else if (component.engine === "css") runCss(component, spec);
    else if (component.engine === "waapi") runWaapi(component, spec);
    else if (component.engine === "glsl-webgl") await runGlsl(spec);
    else if (component.engine === "remotion-adapter") runRemotionAdapter(spec);
    else if (component.engine === "three-adapter") runThreeAdapter(spec);
  }
  report.lastRunMs = performance.now() - started;
  setText(refs.previewNote, reduced
    ? `${component.engine} reduced-motion end state applied without animation.`
    : `${component.engine} playback started by user action.`);
}

async function initialize() {
  try {
    const [catalogData, componentData] = await Promise.all([
      fetchJson("../motion-library/MOTION_CATALOG.json"),
      fetchJson("../motion-library/components.json"),
    ]);
    catalog = catalogData.entries;
    components = componentData.components;
    const catalogIds = new Set(catalog.map((entry) => entry.id));
    components.forEach((component) => validateComponent(component, catalogIds));
    componentsById = new Map(components.map((component) => [component.id, component]));
    renderMetrics();
    renderCatalog();
    const first = catalog.find((entry) => componentsById.has(entry.id));
    if (first) selectEntry(first);
    report.ready = true;
    document.documentElement.dataset.labReady = "true";
  } catch (error) {
    report.error = error instanceof Error ? error.message : String(error);
    setText(refs.previewNote, `Motion Lab failed safely: ${report.error}`);
  }
}

refs.filter.addEventListener("input", renderCatalog);
refs.implementedOnly.addEventListener("change", renderCatalog);
refs.direction.addEventListener("change", () => { document.documentElement.dir = refs.direction.value; refs.stage.dir = refs.direction.value; });
refs.play.addEventListener("click", () => playSelected().catch((error) => { report.error = error.message; setText(refs.previewNote, `Playback failed safely: ${error.message}`); }));
refs.stop.addEventListener("click", () => { resetStage(); setText(refs.previewNote, "Playback stopped."); });
initialize();
