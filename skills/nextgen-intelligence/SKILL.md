---
name: nextgen-intelligence
description: Invoke the hub's local reasoning, private memory, artifact factory, repair analysis, cinematic proof and engineering economics engines from Codex or Claude Code.
---

Read the project's instructions, `docs/specs/nextgen-intelligence/` and the selected
module's docstring. Use an approved immutable hub revision after review. This
skill is an invocation contract, not proof of native host activation.

1. Claim a separate branch/path lease through `engineering_os.orchestration`.
   Reuse `engineering_os.model_router.select_model` for model eligibility; no
   model call or paid service is authorized by an engine recommendation.
2. Store requests, operational knowledge, receipts and checkpoints in a private
   user-owned directory outside every Git repository. Do not ingest customer
   data or secrets. Credential-pattern rejection is defense in depth, not a
   guarantee of personal-data detection. Only generic synthetic evidence belongs
   in the public hub.
3. Invoke the same entry point from either agent's terminal, from the pinned hub
   checkout. For example:

   ```sh
   python3 -m engineering_os.intelligence reasoning-plan --input /private/request.json
   python3 -m engineering_os.intelligence memory-put --state-dir /private/memory --input /private/record.json
   python3 -m engineering_os.intelligence memory-search --state-dir /private/memory --input /private/query.json
   python3 -m engineering_os.intelligence factory-plan --input /private/requirements.json
   python3 -m engineering_os.intelligence factory-evaluate --artifact-root /private/project --input /private/stage-evidence.json
   python3 -m engineering_os.intelligence factory-generate --artifact-root /private/new-app --input /private/resources.json
   python3 -m engineering_os.intelligence healing-analyze --input /private/diagnostics.json
   python3 -m engineering_os.intelligence healing-repair --input /private/sqlite-settings.json
   python3 -m engineering_os.intelligence economics --input /private/ledger.json
   python3 -m engineering_os.intelligence economics-measure --input /private/local-timing.json
   python3 -m engineering_os.layer_checks
   ```

   Paths above are illustrative. Create private directories outside Git with
   mode 0700. Use `--help` for all operation names. JSON request schemas and
   executable examples live in each module and its tests. Imports load only the
   selected engine. No extra dependency, daemon or provider connection is needed.
4. Start with a reasoning plan and relevant project memory. Record decisions with
   source provenance; checkpoint to a new private destination before handoff.
   The receiving Codex/Claude session opens the same store, or restores the
   checkpoint into a new empty store. Never merge private memory into public Git.
5. Treat plans and supplied evaluator receipts as assertions, not authenticated
   model execution. Reasoning acceptance requires distinct pinned model-review
   identities and deterministic checks bound to the plan/source. Obtain real
   reviews independently; never fabricate their records to clear a gate.
6. Factory artifacts must pass source-bound checks before stage advancement.
   `factory-generate` builds a typed SQLite CRUD application, tests it through
   HTTP over a private Unix socket and publishes to a new private directory.
   `healing-repair` exercises actual SQLite behavior before, after and after
   rollback for the supported settings. Existing declarative repair checks and
   the runtime repair both require project review before adopting a candidate.
7. Check response status fields. CLI exit 0 means a valid request was processed;
   it does not mean a plan was accepted, a stage passed, a motion ran, or a
   release was authorized. Failed gates/unknown costs remain explicit in JSON.
8. Include coordinator and every worker/retry in economics inputs. Input tokens
   include their cache subset. Proxy counts, estimates, actual charges and
   subscription allowance are different quantities; unavailable data stays
   unavailable. This session's token bill is not visible to this skill.
9. Cinematic results must bind actual renderer/core sources to real proof.
   Browser viewport emulation is not physical mobile/device performance proof.
   Keep PR16's original 200 separate from the existing 400 reference recipes.
10. In Claude Code, review and approve the `gaie` project MCP server through
    the host's usual workflow. Use `claude mcp list` to check the connection.
    Use the structured `gaie_*` tools advertised by the server. Private memory,
    artifact verification, evidence directories and generation output are scoped
    at server startup. Use the terminal CLI when an operator supplies private
    paths directly. Check actual tool calls separately from native discovery.
11. For a request to build or upgrade a project, start with `gaie_master_status`.
    If the verified master routes are enabled, pass the owner's original words
    to `gaie_master_route`. Follow the accepted route using the existing
    `gaie-build` or `gaie-upgrade` skill and its approved master prompt. Use
    `gaie_master_execute` for the supported local profile once its scoped inputs
    are available. Carry forward the route restrictions and inspect the step
    receipts. If the approval is pending, use the appropriate standalone local
    operations within their scope and report the master dependency. See
    [master integration acceptance](../../docs/specs/nextgen-intelligence/master-mcp.md).

Run module and integration tests, the tracked secret/AST scan, dependency scan
and hub audit. Existing mandatory CI and independent approval remain required.
No engine auto-merges, installs models, sends messages, deploys production, or
grants authority across project boundaries.
