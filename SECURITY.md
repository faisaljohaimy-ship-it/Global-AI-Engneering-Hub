# Security policy

Use least privilege and project-isolated credentials, data and deployments. Keep
secrets out of Git, public logs, screenshots and this public hub. Private project
inventories and task/release state belong outside the repository in restricted
storage. The hub is development tooling, never a shared production credential or
runtime authority.

Report suspected vulnerabilities privately through the repository's configured
security-reporting channel when available; do not post credentials or customer
data in public issues. Capture affected immutable revisions, a minimal synthetic
reproducer and observed impact. Do not scan unrelated systems. Never claim RLS,
identity, compliance or production isolation based on a mocked/fixture test.

Required review surfaces: scoped source/permission diff, exact dependency lock,
upstream/license review, secret scan, unit/negative/integration/browser evidence,
performance bounds, exact release identity and rollback. No new tool, model,
provider, webhook or schedule is approved merely by being discoverable.

Continuous discovery is bounded and read-only; it records public metadata as
candidates. API/rate-limit failures stop the batch. Installation and activation
need a separate reviewed PR and verified cost/privacy/permission prerequisites.
