---
name: chromium-engineering
description: Run reviewed native Chromium rendering probes with offline localhost isolation, honest GPU availability and bounded lab benchmarks.
---

Read project instructions, pin and budget first. This stack is development tooling,
not a product runtime service, a browser agent, or approval to attach to an
authenticated browser/CDP profile.

1. Install the exact reviewed lockfile in `motion-library/chromium-stack` with
   `npm ci --ignore-scripts --no-audit --no-fund`; install its matching Chromium only
   when the existing environment lacks it. Never bulk install the historical
   18-dependency `latest` manifest from the old candidate branch.
2. Run `node motion-library/chromium-stack/smoke.mjs`. Optional `--out` must be a
   new absolute directory under `/tmp` or `/workspace`, with existing nonsymlink
   parents. It preserves previous evidence instead of overwriting it.
3. Review actual pixel/interpolation checks, runtime errors, renderer identity,
   RTL/mobile/reduced-motion cases, finite frame budgets and input hashes. Match
   the recorded hashes to the source before reusing evidence.
4. A WebGPU API or adapter is availability only. The stack does not render WebGPU,
   install Three/Remotion/GSAP/Rive, or prove a physical GPU/mobile/Safari run.
   Do not promote those candidates or claim production FPS from a lab benchmark.
5. Keep browser binaries, node_modules, generated PNG/video and private project
   evidence outside Git. Re-run relevant tests after engine/lockfile/source changes.
