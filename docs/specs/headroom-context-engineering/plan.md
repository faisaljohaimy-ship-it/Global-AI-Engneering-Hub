# Delivery plan

1. Preserve Hub OS0.1.1/PR14 and existing source. Use separate worktrees and private
   TaskStore branch/path leases for runtime, documentation and integration work.
   Reuse the official source audit and isolated core-SDK preflight; do not repeat
   concurrent Claude recovery or priority-tool audits.
2. Implement `tools/headroom_context.py` and `tools/headroom_worker.py` as a
   self-contained pair. Keep the parent standard-library-only and the SDK optional;
   launch the same interpreter with `-I`. Use a controlled private environment,
   bounded fixtures and explicit network-denial results rather than a proxy/service.
3. Persist the original and manifest atomically in a private store, bind result
   metadata to full hashes, and verify retrieval before returning context. Define
   explicit passthrough/fallback and exact-versus-estimated token semantics.
4. Add the selective skill, documentation and one REVIEWED registry row without
   changing the prior entries. Root owns pack/SDK/workflow integration; registration
   must vendor both siblings and preserve existing project files and approvals.
5. Verify standard-library behavior without the SDK, then real pinned SDK behavior
   in the reviewed venv. Cover protected/short/malformed input, original recovery,
   corruption, missing records, path/symlink boundaries, timeout/network denial and
   declared metrics. Test the selected vendored pair in an isolated project too.
6. Record actual Codex tool-session invocation and unavailable native Claude/MCP
   evidence separately. Review current source/tests and exact-head CI before merge;
   update product pins only under their independent reviewed gates. Keep complete
   dependency/host/private inventory evidence outside the public repository.

Source rollback uses an ordinary reviewed revert of the scoped capability change,
followed by required gates. Retain existing originals and earlier source/checkpoints;
never delete other writers' work, change domains or treat SDK cache eviction as a
data-recovery mechanism. This phase has no product deployment to roll back.
