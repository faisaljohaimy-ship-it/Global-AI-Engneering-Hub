#!/usr/bin/env node
// Deterministic frame renderer for scenes built on the hub motion runtime.
// A scene exposes window.scene = { duration, seek(ms), palette }. Each frame is produced
// by seeking, never by waiting, so the same scene always yields the same frames. Frames
// are piped straight to ffmpeg; the film is written outside the repository.
//
//   node motion-library/render/render.mjs --out /path/outside/the/repo [--fps 30] [--width 1280] [--height 720]
//
// Playwright and ffmpeg are tools of the machine running this script, not hub dependencies.

import { spawn, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, statSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { serve } from '../verify/serve.mjs';

const library = resolve(fileURLToPath(new URL('..', import.meta.url)));
const option = (name, fallback) => {
  const index = process.argv.indexOf(`--${name}`);
  return index > 0 ? process.argv[index + 1] : fallback;
};
const out = option('out');
if (!out) {
  console.error('Usage: render.mjs --out <directory outside the repository> [--fps 30] [--width 1280] [--height 720]');
  process.exit(2);
}
const [fps, width, height] = [Number(option('fps', 30)), Number(option('width', 1280)), Number(option('height', 720))];
const scenePath = option('scene', 'render/scene.html');
const digest = (data) => createHash('sha256').update(data).digest('hex');
mkdirSync(out, { recursive: true });
const film = join(resolve(out), 'hub-motion-sample.mp4');

// Playbook checks that can be measured in the page: safe area, clipping, direction, contrast.
function inspectLayout() {
  const luminance = (hex) => {
    const channel = (offset) => {
      const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
      return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
  };
  const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + 0.05) / (Math.min(luminance(a), luminance(b)) + 0.05);
  const { palette, duration } = window.scene;
  const margin = { x: innerWidth * 0.05, y: innerHeight * 0.05 };
  const outside = new Set();
  const clipped = new Set();
  for (let time = 0; time <= duration; time += 100) {
    window.scene.seek(time);
    for (const element of document.querySelectorAll('[data-text]')) {
      if (!element.textContent.trim() || Number(getComputedStyle(element).opacity) === 0) continue;
      const range = document.createRange();
      range.selectNodeContents(element);
      const box = range.getBoundingClientRect();
      if (box.left < margin.x || box.top < margin.y || box.right > innerWidth - margin.x || box.bottom > innerHeight - margin.y) outside.add(element.id);
      if (element.scrollWidth > element.clientWidth + 1) clipped.add(element.id);
    }
  }
  const arabic = [...document.querySelectorAll('[lang="ar"]')];
  return {
    textOutsideSafeArea: [...outside],
    clippedText: [...clipped],
    arabicLines: arabic.length,
    arabicIsRightToLeft: arabic.every((element) => getComputedStyle(element).direction === 'rtl'),
    arabicFontRequested: arabic.length ? getComputedStyle(arabic[0]).fontFamily : null,
    minimumTextContrast: Math.min(...palette.background.flatMap((background) => [contrast(palette.text, background), contrast(palette.accent, background)])),
    effects: window.scene.effects,
    durationMs: duration,
  };
}

const playwright = createRequire(import.meta.url)('playwright');
const server = await serve(library);
const browser = await playwright.chromium.launch();
let layout;
let frames;
const hashes = [];
let repeatable = true;
let resettled = 0;
try {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto(`${server.origin}/${scenePath}`);
  await page.waitForFunction(() => window.scene);
  layout = await page.evaluate(inspectLayout);
  frames = Math.round((layout.durationMs / 1000) * fps);
  // A capture taken straight after a seek can show a frame the compositor has not finished
  // (seen on the frame where new text first appears). Wait for two animation frames, then
  // accept a capture only when the next one is identical.
  const shot = async (index) => {
    await page.evaluate((time) => new Promise((painted) => {
      window.scene.seek(time);
      requestAnimationFrame(() => requestAnimationFrame(painted));
    }), (index * 1000) / fps);
    let png = await page.screenshot({ type: 'png' });
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const again = await page.screenshot({ type: 'png' });
      if (again.equals(png)) return png;
      png = again;
      resettled += 1;
    }
    throw new Error(`Frame ${index} did not settle`);
  };
  const encoder = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'png', '-i', '-',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', film], { stdio: ['pipe', 'inherit', 'inherit'] });
  const encoded = new Promise((done, fail) => encoder.on('close', (code) => (code === 0 ? done() : fail(new Error(`ffmpeg exited with ${code}`)))));
  for (let index = 0; index < frames; index += 1) {
    const png = await shot(index);
    hashes.push(digest(png));
    if (!encoder.stdin.write(png)) await new Promise((drained) => encoder.stdin.once('drain', drained));
  }
  encoder.stdin.end();
  await encoded;
  // Determinism: seek back to a spread of frames, out of order, and compare with the first pass.
  for (const index of [frames - 1, 0, ...Array.from({ length: 10 }, (_, step) => Math.floor(((step + 1) * frames) / 11))]) {
    repeatable &&= digest(await shot(index)) === hashes[index];
  }
} finally {
  await browser.close();
  server.close();
}

const probe = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
  'stream=codec_name,width,height,r_frame_rate,nb_read_frames,pix_fmt:format=duration', '-of', 'json', film], { encoding: 'utf8' }));
const stream = probe.streams[0];
const audio = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'json', film], { encoding: 'utf8' }));
const checks = {
  aspectRatio16by9: stream.width * 9 === stream.height * 16,
  resolutionMatchesRequest: stream.width === width && stream.height === height,
  frameRateMatchesRequest: stream.r_frame_rate === `${fps}/1`,
  frameCountMatchesTimeline: Number(stream.nb_read_frames) === frames,
  durationMatchesTimeline: Math.abs(Number(probe.format.duration) - frames / fps) < 0.05,
  framesAreRepeatable: repeatable,
  motionIsPresent: new Set(hashes).size > frames / 2,
  textInsideSafeArea: layout.textOutsideSafeArea.length === 0,
  noClippedText: layout.clippedText.length === 0,
  arabicIsRightToLeft: layout.arabicLines > 0 && layout.arabicIsRightToLeft,
  textContrastAtLeast4_5: layout.minimumTextContrast >= 4.5,
};
const report = {
  schema_version: 1,
  notes: 'Generated by motion-library/render/render.mjs. The film is kept outside the repository; this report records what was measured.',
  generated_on: new Date().toISOString().slice(0, 10),
  scene: `motion-library/${scenePath}`,
  tools: { browser: 'chromium', playwright: createRequire(import.meta.url)('playwright/package.json').version, ffmpeg: execFileSync('ffmpeg', ['-version'], { encoding: 'utf8' }).split('\n')[0].split(' ')[2] },
  output: { codec: stream.codec_name, pixel_format: stream.pix_fmt, width: stream.width, height: stream.height, frame_rate: stream.r_frame_rate, frames: Number(stream.nb_read_frames), duration_seconds: Number(probe.format.duration), bytes: statSync(film).size, distinct_frames: new Set(hashes).size, captures_repeated_until_settled: resettled, frames_sha256: digest(hashes.join('')) },
  effects: layout.effects,
  measured: { minimum_text_contrast: Number(layout.minimumTextContrast.toFixed(2)), arabic_font_requested: layout.arabicFontRequested, text_outside_safe_area: layout.textOutsideSafeArea, clipped_text: layout.clippedText },
  pass: Object.values(checks).every(Boolean),
  checks,
  not_verified: ['audio: the sample has no audio track' + (audio.streams.length ? ' (unexpected stream found)' : ''), 'playback on phones and other browsers', 'the Arabic typeface: only the system fallback font was available', 'colour management beyond sRGB output'],
};
writeFileSync(join(resolve(out), 'report.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ film, pass: report.pass, output: report.output, failed: Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name) }, null, 2));
process.exit(report.pass ? 0 : 1);
