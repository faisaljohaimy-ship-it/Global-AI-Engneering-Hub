# MASTER BUILD and MASTER UPGRADE over project MCP

This extension continues [PR #25](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/25) from `c4e9c85998b95b98a060af78c49904fcb22e3d1b`. The twenty local architecture contracts and the existing intelligence commands remain in scope. The two master definitions, bilingual router, and routing skills belong to [PR #26](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/26), inspected read-only at `d0c0419a3f6d22389ad235bc8b9057fffb8d6fa3`. That revision is a draft outside `main`. Its connection stays disabled pending reviewed adoption and owner approval.

## Scope and execution path

One project-scoped GAIE stdio server exposes the registered local engineering operations. The CLI and MCP server share the same engine implementations. The server assigns private state, source, evidence and output locations at startup. A request carries structured values and scoped identifiers. A catalog entry, a route response and an upstream prompt each have their own verification requirements.

1. In a new Claude Code session, enable the reviewed server through its usual project approval. Use the `gaie_master_status` tool to inspect availability.
2. When the owner asks to build or upgrade a project, pass the original sentence to `gaie_master_route` when advertised. The verified router from the adopted revision classifies Arabic and English imperatives. It resolves exact registered targets, records prohibited actions, and returns clarification when it cannot resolve the command or target unambiguously. The caller retains the route status, target and restrictions.
3. For an accepted route, follow the existing `gaie-build` or `gaie-upgrade` skill and its pinned `prompts/MASTER_BUILD.md` or `prompts/MASTER_UPGRADE.md`. Pass the same sentence and validated project input to `gaie_master_execute`. That tool resolves the route again against the approved source. The request cannot assert its own engine or repository match. Use `preview` to inspect the bounded workflow. Use `execute` with explicit structured inputs and the required startup scopes.
4. Inspect stage receipts and actual outcomes. A route can recommend workstreams, repository verification and independent review. The execution profile uses local registered operations and has authority only for the configured private output and evidence. Repository creation, default-branch mutation, product changes, deployment and additional spending remain outside this integration.

| Capability | Reused surface | MASTER BUILD | MASTER UPGRADE |
|---|---|---|---|
| Reasoning | `reasoning-plan`, `reasoning-review`, `root-causes` | Bounded requirements and plan evidence | Reuse, risk analysis and plan evidence |
| Knowledge | `memory-search`, `memory-graph`, `memory-put`, `memory-index`, `memory-checkpoint`, `memory-restore`, `memory-verify` | Retrieve scoped context and record reviewed decisions | Recover project history and checkpoints |
| Software factory | `factory-plan`, `factory-evaluate`, `factory-generate` | Generate and verify the supported typed SQLite application in a new private destination | Evaluate artifacts and their evidence under the configured project root |
| Healing | `healing-analyze`, `healing-verify`, `healing-repair`, `healing-replay` | Check applicable local diagnostics and evidence | Reproduce and repair supported SQLite settings, then verify exact rollback |
| Economics | `economics`, `economics-measure` | Reconcile supplied usage or measure supported local operations | Capture comparable measurements and independent cost fields |
| Cinematic evidence | `cinematic` | Inspect eligible motions and browser proofs | Review current proof before selecting or replacing motion |
| Architecture | `architecture` and the twenty-layer acceptance runner | Inspect current local layer coverage | Check the same contracts after changes |

`gaie_capabilities` describes all 22 local operations and their required scopes. With `--browser-cache` pointing to the existing reviewed runtime, `gaie_browser_qa` runs the fixed localhost Chromium fixture. It verifies three cases at 30 frames each against the existing 20 ms budget. Provider integrations and catalog candidates keep their own lifecycle. The current Headroom approval explicitly covers its local CLI and excludes MCP.

## Enable the master connection after approval

Review `PR #26` on the exact intended source revision and adopt it through the repository's normal approval and merge process. Keep the existing router, policies, project aliases, skills and prompts on their reviewed branch. Use the original upstream identifiers and instructions. The MCP adapter adds the execution bridge without maintaining a second router or prompt corpus.

Check the trusted source checkout's `origin` and refresh its `refs/remotes/origin/main` through the normal fetch. Select an immutable revision contained in that ref. Keep the owner-approved source manifest outside Git in a directory with mode `0700` and a file with mode `0600`. Its JSON fields are `schema_version` with value `1`, `repository` with the hub's canonical GitHub HTTPS URL, `revision` with the full commit SHA, `approved_engines` containing `MASTER_BUILD` and `MASTER_UPGRADE`, and `source_sha256` with a digest for each of these six paths.

- `engineering_os/gaie_router.py`
- `governance/policies/gaie-routes.json`
- `projects/aliases.json`
- `projects/registry.json`
- `prompts/MASTER_BUILD.md`
- `prompts/MASTER_UPGRADE.md`

For each file use its bytes at the reviewed revision, such as `git show "$reviewed_revision:engineering_os/gaie_router.py" | sha256sum`. The startup digest binds the manifest bytes. Produce and review the manifest against the approved Git objects during adoption. The adapter routes using the pinned source and registry, with no implicit private project overlay. Skill discovery and installation remain a separate check on the adopted skills. A draft head, local branch label or MCP response cannot substitute for approval evidence.

Prepare one reviewable local server configuration in the authorized checkout. Private paths below are examples. Pass only the arguments needed for the current project. The public project registration continues to start the bounded server without the master approval arguments.

```sh
python3 -m engineering_os.claude_bridge --project approved-project \
  --master-approval /private/gaie/master-approval.json \
  --master-approval-sha256 APPROVED_RECEIPT_SHA256 \
  --master-source-root /absolute/reviewed-hub \
  --master-workspace /absolute/isolated-project-checkout
```

The master source checkout establishes provenance. The separately configured workspace is the existing project's isolated checkout. For upgrade execution the router must identify one allowed project and match its origin to that workspace. A local match is only one prerequisite to an authorized project operation. For build, supply a new private destination with `--destination`. `--memory-dir`, `--artifact-root`, `--checkpoint-dir` and `--receipt-dir` add the corresponding operator-scoped tools. Keep these paths and private receipts in the operator's local configuration.

`gaie_memory_checkpoint` and `gaie_memory_restore` take `{"request":{"project":"approved-project","id":"checkpoint-id"}}` with private memory and checkpoint directories configured. The identifier resolves to a JSON file in the configured checkpoint directory. Checkpoint refuses an existing file and restore requires an empty store. Both enforce the configured project's boundary. `gaie_memory_verify` needs the memory, artifact and receipt directories. Its request contains `project`, the solution digest `id`, a scoped `receipt_id` and `receipt_sha256`. Take file paths and digests from verified local evidence.

Use the MCP request wrapper and stable tool names below. Examples use a synthetic build command. Replace the inputs only with supported typed values for the same project.

```json
{"name":"gaie_master_status","arguments":{"request":{}}}
```

```json
{"name":"gaie_master_route","arguments":{"request":{"command":"Build a new issue tracker"}}}
```

```json
{
  "name": "gaie_master_execute",
  "arguments": {
    "request": {
      "command": "Build a new issue tracker",
      "workflow": {
        "schema_version": 1,
        "project": "approved-project",
        "mode": "preview",
        "inputs": {}
      }
    }
  }
}
```

The local profile accepts optional `reasoning`, `memory`, `economics` and `cinematic` inputs using the corresponding reasoning plan, memory search, economics ledger and cinematic schemas. Build also accepts `factory_plan` and uses the generator's structured request in `generation`. Upgrade accepts `factory_evaluation` and uses the healing engine's structured SQLite settings request in `repair`. Its repair stage runs a separate rollback replay. The master-status result and `tools/list` distinguish a disabled bridge from a valid configured workflow. When the upstream approval is absent or invalid, continue independent scoped work through the existing local tools and report the activation gate.

## Acceptance and evidence

| Criterion | Evidence required |
|---|---|
| Source approval | Default and draft-only configurations omit master execution tools. An independently approved pin on trusted `origin/main` exposes the scoped master tools. Wrong SHA, source drift, a malformed receipt and mismatched origin are rejected. |
| Routing | Exact build and upgrade phrases in Arabic and English are routed by the upstream code. Negative and ambiguous cases produce a bounded clarification. The adapter refuses unsupported actions, cross-project requests and paths supplied through the tool request. |
| Execution | A scoped build generates the expected artifacts in a private new destination and checks the actual service. A scoped upgrade checks SQLite behavior and rollback without mutating project files. A preview performs no operation writes. Per-step inputs and outcomes bind to receipt digests. |
| Native host | A fresh Claude Code process discovers the server and exercises MCP calls for the test prompts. Capture the tool names, route outcome and source-bound receipts. A loopback test provider supplies scripted model responses while the actual Claude Code host and local engines run. Independent live model selection and operator activation require separate evidence. |
| Layer and release | The fixed acceptance contracts for all twenty layers pass, including the source, approval, project scope and protocol controls. Run all required CI on the exact integration head. Mark it ready for review after the required results are verified. |

From the reviewed checkout, use `claude mcp list` to check native discovery and `python3 -m engineering_os.layer_checks` to replay the local layer checks. Review `python3 -m engineering_os.claude_bridge --help` for the startup options and consult the callable implementation and tests for exact payloads. Keep native harness fixtures and temporary app artifacts in isolated directories outside Git. Public evidence records generic scope, versions, outcomes and digests. Keep live credentials, private names, prompts, timestamps that expose active agent work and operator paths private.

Run the native test with the already reviewed Claude Code binary. It starts a new private configuration and a loopback Messages fixture for each scenario. It records observed native MCP results and performs zero hosted model calls.

```sh
python3 -m scripts.verify_claude_master_mcp --claude /absolute/path/to/reviewed/claude
```

The stable release verifier now requires the exact successful main workflows and all four Next generation intelligence jobs. This includes the three original-motion browser jobs and the twenty-layer job. PR checks prepare the code for review. Release provenance is evaluated at the merged main commit and a reviewed release tag.
