# Changelog

## Engineering OS0.2.0 — 2026-11-28

Adds the GAIE software factory: a deterministic Arabic/English master router
(`hub.py route`), master build and upgrade prompts, six `gaie-*` skills, a
read-only verifier agent, private per-project engineering memory, read-only project
inventory with a coverage matrix (`hub.py inventory`), public project aliases with
a private overlay, the `gaie-factory` registration pack, an idempotent Claude Code
bootstrap and a plugin manifest. Existing motion sources are unchanged; motion
files are only added. Changed existing interfaces include: `hub.py architecture`
output comes from engineering_os/layers.py; `hub.py health` and SDK `verify` read
project files only as single-link regular files; SDK `target` runs Git with the
checkout's fsmonitor and hooks off and inherited GIT_* ignored, and refuses a
checkout with filter programs or hidden index entries. The SDK bytes differ from
engineering-sdk-v1.0.0, so its label moves to 1.0.1 (sdk/VERSION and the
engineering-sdk pack); it ships in this OS release with no engineering-sdk tag.
No product was modified, no repository created and nothing deployed; host
evidence is limited to skill discovery and invocation in clean sessions. See
docs/GAIE_FACTORY.md and docs/evidence/2026-11-28-gaie-factory.md.

## Engineering OS0.1.4 — 2026-11-28

Adds `python3 scripts/verify_operational_capabilities.py`: five fixed local fixtures
for callable surfaces (Engineering SDK stdio MCP and file verification, a task
handover reclaimed through a reopened TaskStore, a blocked model-router decision
without project evidence, Motion SDK sampling with reduced motion and SVG export,
literal UTF-8 search with Ripgrep). It accepts only capability IDs from a fixed list
and prints JSON with wall time and source digests; verify.yml runs the first four.
Evidence: docs/evidence/2026-11-28-operational-capability-validation.json. Files and
one CI step are added, nothing is removed; SDK1.0.0, packs and motion sources are
unchanged from OS0.1.3. Tag at a0dca9a969a8e8a65a2ad58768ada645cc0dbd65.

## Engineering OS0.1.3 — 2026-11-28

Moves the three isolated browser/quality locks (motion-library/chromium-stack, verify
and quality) from Playwright 1.63.0 to 1.65.1. catalog/capabilities/playwright.json
pins the version, upstream revision and npm integrities, and the workflows read the
version from it. A native Chromium runtime claim requires the approved receipt SHA256,
hashed and parsed from the same bytes (engineering_os/control.py); the CI native smoke
frame budget drops from 100 to 20 ms. Adds seven dated evidence files
docs/evidence/playwright-1.65.1-*.json and tests for missing or malformed digests,
changed receipt bytes, expired proof and receipt replacement during reading. SDK1.0.0
and packs are unchanged from OS0.1.2; historical 1.63.0 evidence keeps its dates.
Tag at 6d6501566b61ea9a01137c93c2811c9c10522943.

## Engineering OS0.1.2 — 2026-11-28

Adds optional local Headroom 0.45.0 context preparation: tools/headroom_context.py,
a bounded worker (tools/headroom_worker.py) that denies IP sockets, the
headroom-context-engineering skill, the headroom-context pack 0.1.0 and a hash-locked
68-package closure in integrations/headroom/requirements.lock. Originals are kept with
their SHA256 for exact retrieval; protected, short and code inputs pass through.
verify.yml installs the lock and runs tests/test_headroom*.py; Dependabot checks
integrations/headroom weekly and only opens pull requests. sdk/capabilities.json
gains a headroom-context entry; sdk_version stays 1.0.0 and sdk/engineering_sdk.py
is unchanged. No provider call, native host interception or product runtime
dependency.
Tag at 81b2374aaf8aa7c04d38ed122a9b92e12afc483e.

## Engineering OS0.1.1 — 2026-11-27

Extends reviewed dependency proposals to all three isolated browser/quality
lockfiles and adds bounded weekly/manual advisory audits. Shared driver proposals
stay grouped; no installation or merge is automatic. SDK1.0.0 and all motion/runtime
source bytes remain unchanged from OS0.1.0, so existing approved product pins remain
supported without a forced update.
Release validation follows later scheduled/manual advisory failures as well as
main CI and requires a successful advisory audit within24hours.
Preserves the concurrent reviewed discovery work: eight unapproved candidates,
one first-party selection instruction and ten non-installable pack proposals.

## Engineering OS0.1.0 — 2026-11-27

Adopts the owner's L01–L12 target, preserving SDK1.0.0 and all existing motion/CLI
interfaces. Adds evidence-aware CLI projections and bounded upstream discovery.
Orchestration, policy routing, recovered Chromium runtime and additive Motion SDK
are independently reviewed modules; consult exact test receipts before adoption.
Adds400new Canvas2D motions, Universal Motion SDK/Studio, selective offline
registration, fresh Chromium/Lighthouse/axe gates, bounded secret/AST/dependency
audits and release-provenance validation. Preserves legacy motions and SDK1.0.0.
No product isolation, real model access or production deployment is implied by
this hub change. Private project/source recovery evidence remains restricted.

## Engineering SDK1.0.0

Released at12f067d42c2bcad4256e3aa130503044af16e5b3. Adds checksummed offline
registration/integrity, private-target and release-receipt validation, selective
skills/tool discovery and local read-only MCP. Existing product runtimes unchanged.
