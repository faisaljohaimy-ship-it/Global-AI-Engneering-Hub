// Frame-exact export of any motion, whatever draws it: each frame is asked for by time,
// awaited, and captured from a real browser, then encoded by ffmpeg. The film is written
// outside the repository: generated video does not belong in git.
import { spawn } from 'node:child_process';
import { mkdirSync, statSync, writeFileSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { serve } from '../verify/serve.mjs';
import { CHROMIUM_ARGS, loadPlaywright } from './playwright.mjs';
import { scan } from './build_registry.mjs';

const sdk = resolve(fileURLToPath(new URL('..', import.meta.url)));
const repository = resolve(sdk, '..', '..');

export async function exportMotion({ id, out, fps = 30, width = 1280, height = 720, seconds, direction = 'ltr', format = 'mp4', options = {} }) {
  const [found] = await scan({ id });
  if (!found) throw new Error(`Unknown motion: ${id}`);
  const directory = resolve(out ?? '');
  if (!out || directory === repository || directory.startsWith(repository + sep)) throw new Error('--out must be a directory outside the repository');
  if (!['mp4', 'webm', 'png'].includes(format)) throw new Error('--format must be mp4, webm or png');
  const duration = Number.isFinite(seconds) ? seconds * 1000 : found.definition.duration;
  const frames = Math.max(1, Math.round((duration / 1000) * fps));
  mkdirSync(directory, { recursive: true });
  const { playwright } = loadPlaywright();
  const server = await serve(sdk);
  const browser = await playwright.chromium.launch({ args: CHROMIUM_ARGS });
  const target = join(directory, format === 'png' ? `${id}-%04d.png` : `${id}.${format}`);
  let encoder = null;
  let encoded = Promise.resolve();
  if (format !== 'png') {
    const codec = format === 'mp4' ? ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'] : ['-c:v', 'libvpx-vp9', '-pix_fmt', 'yuv420p', '-b:v', '0', '-crf', '32'];
    encoder = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'png', '-i', '-', ...codec, target], { stdio: ['pipe', 'inherit', 'inherit'] });
    encoded = new Promise((done, fail) => {
      encoder.on('error', () => fail(new Error('ffmpeg is needed to encode video and was not found')));
      encoder.on('close', (code) => (code === 0 ? done() : fail(new Error(`ffmpeg exited with ${code}`))));
    });
  }
  try {
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(`${server.origin}/verify/harness.html`);
    await page.waitForFunction(() => window.h);
    await page.addStyleTag({ content: 'body{margin:0;overflow:hidden}' });
    await page.evaluate(([motionId, create]) => window.h.create('film', motionId, create), [id, {
      width, height, direction, quality: 'high', reducedMotion: false,
      ...(found.definition.engine === 'webgpu-wgsl' ? { gpu: 'readback' } : {}), ...options,
    }]);
    for (let index = 0; index < frames; index += 1) {
      await page.evaluate(async (time) => {
        await window.h.frame('film', { time }, 'export');
        await new Promise((painted) => requestAnimationFrame(() => requestAnimationFrame(painted)));
      }, (index * 1000) / fps);
      const png = await page.locator('#stage-film').screenshot({ type: 'png' });
      if (encoder) {
        if (!encoder.stdin.write(png)) await new Promise((drained) => encoder.stdin.once('drain', drained));
      } else writeFileSync(join(directory, `${id}-${String(index).padStart(4, '0')}.png`), png);
    }
    encoder?.stdin.end();
    await encoded;
  } finally {
    await browser.close();
    server.close();
  }
  return { id, frames, fps, width, height, format, path: target, bytes: format === 'png' ? null : statSync(target).size };
}
