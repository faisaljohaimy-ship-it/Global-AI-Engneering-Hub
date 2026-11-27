# Reference architecture — Global AI Engineering Ecosystem

## Business domains
Enterprise and government solutions, subscription SaaS, cinematic studio, defensive cybersecurity, AI research, cloud engineering.

## Engineering plane
ChatGPT and Claude for planning and analysis; Codex and Claude Code for isolated development and release work. Skills, registry, MCP integrations, project specifications, reusable packages, shared non-sensitive knowledge, project templates. ACP, A2A, model routing and agent orchestration are future optional interfaces, not implemented services. Keep confidential context in access-controlled storage.

## Delivery plane
Independent source repositories, pinned dependencies, isolated environments, tests, security checks, release manifest, preview verification, production approvals, rollback and monitoring. Never bulk merge unreviewed changes. Do not alter existing deployments during onboarding.

## Product runtime reference
Edge/CDN/WAF -> web/mobile/enterprise/AI applications -> API gateway and identity -> business services, AI gateway, workers, events, realtime and integrations, subscription and media processing -> PostgreSQL, cache, object storage, vector search, analytics and event streaming. Use a modular monolith first; distribute services only when measured load and funded operations justify it. Reliability and security apply across all layers.

## Media reference
Storyboard, bilingual scripts, licensed assets, motion design, 3D scenes, render samples, audio QA, browser playback and encoding budgets. Blender/Remotion/Three.js/FFmpeg are candidates pending review; avoid paid renders without approval.

## Roadmap
1. Implemented starter: registry, skills, local CLI and unit tests.
2. Pilot: one sandbox repository, skill discovery in each agent environment, pinned manifest, test evidence.
3. Existing projects: individual reviewed PRs, source identity and release mapping checks.
4. New projects: private templates and reviewed onboarding automation.
5. Funded scale: managed production, SLOs, capacity testing, incident response, backup/restore drills and compliance review.

Zero additional spend is a constraint, not a promise of unlimited compute. No external tool is approved or installed merely by appearing in the catalog. No client-specific source, secrets or commercial private assets in this public repository.
