// Finds Playwright without making it a dependency of this package. A machine or a CI job
// that has a reviewed, locked install elsewhere points to it with MOTION_PLAYWRIGHT_PACKAGE
// (the folder holding that package.json); otherwise Node's normal resolution is used.
import { createRequire } from 'node:module';
import { join } from 'node:path';

export function loadPlaywright() {
  const from = process.env.MOTION_PLAYWRIGHT_PACKAGE ? join(process.env.MOTION_PLAYWRIGHT_PACKAGE, 'package.json') : import.meta.url;
  const require = createRequire(from);
  try {
    return { playwright: require('playwright'), version: require('playwright/package.json').version };
  } catch {
    throw new Error('Playwright is needed for browser work and is not installed here. Install it outside the repository, or set MOTION_PLAYWRIGHT_PACKAGE to a folder whose node_modules has it.');
  }
}

/** Chromium flags that turn on WebGPU with the software adapter, plus precise memory figures for the leak check. */
export const CHROMIUM_ARGS = ['--enable-unsafe-webgpu', '--enable-features=Vulkan,WebGPU', '--use-webgpu-adapter=swiftshader', '--ignore-gpu-blocklist', '--enable-precise-memory-info', '--js-flags=--expose-gc'];
