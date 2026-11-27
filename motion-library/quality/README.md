# Local Motion Studio quality gate

This optional development tool runs actual Lighthouse and axe against a local
Motion Studio checkout. It does not contact production, deploy, call models or
require an authenticated browser. The audited page must use local assets.

Acceptance: run Lighthouse performance and accessibility plus axe on the real
Studio, keep raw evidence outside Git, fail the process when a measured budget
fails, and prove the gate rejects an inaccessible synthetic fixture. A fixture
result proves the driver; it is not Studio evidence.

## Reproduce

Use Node >=22.19 (the development environment used Node24.22.3). Install this
isolated lockfile with lifecycle scripts disabled; browsers are provisioned
separately from a reviewed Playwright release.

```sh
cd motion-library/quality
npm ci --ignore-scripts --no-fund
npm audit
node audit.mjs --root /path/to/hub --out /private/evidence/new-run \
  --chrome /path/to/reviewed/chrome-headless-shell --profile desktop
```

The output directory must be new and outside the audited source tree. Its parent
must already exist. It receives `lighthouse.json`, `axe.json` and `summary.json`.
Studio evidence requires all eight runtime source files, records their SHA-256
hashes and the Git commit when available, and rejects source changes during a run.
The browser-test fixture is separately labeled and does not satisfy that claim.
Use `--profile mobile` for a separate emulated mobile laboratory run. The only
entry paths are `/motion-studio/` and `/motion-studio/index.html`; optional bounded
`motion` selectors choose a specific preview. The driver serves allowed assets
from the supplied checkout on an ephemeral 127.0.0.1 port. It refuses traversal,
symlinks, oversized files and arbitrary repository paths. No existing server or
browser profile is reused. A fresh temporary Chromium profile is removed at exit.
A restrictive response CSP, Playwright request guard, denied-egress proxy and
hostname rules bound this local audit. These are development controls, not a
general-purpose hostile-browser sandbox or an external-site auditing service.

The gate requires performance >=95, accessibility >=95, LCP <=2500ms,
CLS <=0.1, zero critical axe violations, zero unhandled page errors and zero
observed attempted external requests. Raw axe violations and incomplete/manual
checks remain visible even if their severity is below the critical gate. Full
accessibility compliance requires human review.

Scores and paint/layout values are a single lab observation in the selected
profile. They are not field Core Web Vitals. INP is explicitly `null`/not measured;
there is no FPS, 120 FPS, cross-browser or production-performance claim. Lighthouse
mobile emulation does not prove a physical mobile device. Record repeated field
measurements before asserting production performance.

```sh
node --test tests/test_quality_audit.mjs
QUALITY_AUDIT_CHROME=/path/to/chrome-headless-shell \
  QUALITY_AUDIT_EVIDENCE=/private/evidence \
  node --test tests/test_quality_audit_browser.mjs
```

Run the tests from the repository root. Without `QUALITY_AUDIT_CHROME`, the browser
fixture test explicitly skips. Set an unused evidence directory for a repeat run;
the driver intentionally refuses to overwrite evidence.

## Dependency and license review

Only the manifest and exact npm lockfile are committed. No `node_modules`, browser
binary, proprietary asset, package source or raw browser report is redistributed.
These packages are optional development dependencies, not product runtime imports.

| Direct package | Pinned version | Package license | Review |
|---|---|---|---|
| Lighthouse |13.6.0|Apache-2.0|Unmodified audit tool; upstream license and notices remain in the local package.|
| @axe-core/playwright |4.14.1|MPL-2.0|Unmodified development adapter; no covered package files copied or modified. Preserve MPL obligations if covered files are later redistributed.|
| Playwright |1.63.0|Apache-2.0|Reviewed pinned browser driver; browser binaries are installed outside Git.|

One transitive license differs from the permissive/MPL packages:
`lighthouse -> @sentry/node -> @sentry/bundler-plugins -> sentry@0.50.0` is
`FSL-1.1-Apache-2.0`. Its installed `LICENSE.md` explicitly permits internal use
and restricts competing commercial distribution until the future-license date.
This toolchain is approved here only for local internal development audits. The
Sentry CLI is never invoked and Lighthouse error reporting is explicitly disabled.
No telemetry service, account or commercial redistribution is activated. Review
this exception before publishing a bundled toolchain or offering it as a service;
do not describe the entire dependency graph as open source or Apache-licensed.

The transitive dependency graph is pinned with npm integrity hashes. Review the
current `npm audit` result for that exact lockfile before use; a past clean audit
is not a permanent security guarantee. Discovering a new release does not install
or approve it. Updates require an explicit reviewed lockfile change and rerun.
