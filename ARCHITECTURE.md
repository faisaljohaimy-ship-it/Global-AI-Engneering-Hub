# Global AI Engineering Operating System

The owner's official target is a shared engineering control plane with independent
product repositories, data, permissions and production runtimes. The hub provides
reviewed capabilities during development/build; its availability is never a product
runtime dependency. Preserve the existing modular implementation and API contracts.
Use a modular monolith first. Distributed services, Kubernetes and paid/GPU services
require measured need, actual capacity and budget authorization.

| Layer | Target responsibility | Current evidence boundary |
|---|---|---|
|L01 Owner & governance|Access, policy, budget, approvals, audit|Local policy/receipt validators; provider administration is separate|
|L02 AI intelligence|Models, routing, evaluation|Deterministic policy routing; actual model access must be evidenced|
|L03 Agent orchestration|Specialist ownership, priorities, handovers|Explicit invocations/file-state coordination; no continuous daemon claim|
|L04 Engineering control plane|Registries, SDK, knowledge, discovery|Existing CLI, checksummed SDK and additive operational commands|
|L05 Universal integrations|MCP,A2A,ACP,REST,GraphQL,webhooks,CLI,events|Local MCP/CLI implemented; other protocols remain per-adapter candidates|
|L06 Software engineering|Web/backend/mobile/enterprise/SaaS/reuse|Existing shared skills; project implementations remain private|
|L07 Data & intelligence|SQL,RLS,RAG,vectors,analytics,ML|No shared production database provisioned; project-level verification required|
|L08 Cinematic & motion|Browser,GPU,3D,video,motion,spatial|Preserve verified CSS/WAAPI/WebGL; new engines need their own runtime proof|
|L09 Security & quality|Threat boundaries,scans,tests,budgets|SHA-pinned CI and test/audit evidence; no blanket compliance claim|
|L10 Independent products|Eight current spokes and future products|Private registry outside public Git; local preparation differs from remote completion|
|L11 Cloud & delivery|Independent environments,CI/CD,preview,rollback|Existing provider projects preserved; incomplete permissions block relinking|
|L12 Continuous intelligence|Technology/dependency/security/cost/health discovery|Read-only discovery and reviewed update proposals; no automatic execution|

`python3 hub.py architecture` reports this target and its evidence mapping.
`capabilities`, `integrations`, `motions` and `health` report their own tested
surfaces rather than treating catalog names as installed tools. Operational counts
require receipts tied to current source checksums and actual test results.

Lifecycle:DISCOVERED→REVIEWED→APPROVED→INSTALLED→OPERATIONAL→TESTED→PROJECT_VERIFIED.
Review upstream identity, immutable revision, license/commercial use, security,
dependency compatibility, privacy and cost before advancing. A protocol handshake
is not an agent-host invocation; API presence is not a successful GPU render;
simulated tests are not live data/provider evidence. Details live in the versioned
spec and capability records. Keep confidential inventories out of this public hub.

Existing reference architecture remains in docs/ARCHITECTURE.md. Existing imports,
motion catalog and SDK1.0.0 remain supported; new package facades are additive.
