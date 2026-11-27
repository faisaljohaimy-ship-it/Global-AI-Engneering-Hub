# Delivery plan

1. Preserve SDK1.0.0 checkpoint and audit live Git/provider state; reconcile Claude
   source provenance before reusing code. P0 product isolation remains first.
2. Implement orchestration/router, Chromium recovery, motion algorithms and
   Universal SDK/Studio in separate owned worktrees; root integrates CLI/governance.
3. Run module-specific checks before integration. Cherry-pick reviewed commits
   sequentially; preserve all existing APIs/catalogs. Re-run cross-module tests.
4. Review final branch with independent QA/security, publish separate reviewable
   PRs and merge only successful current-head checks. Release a pinned hub version.
5. Update project manifests selectively from a reviewed merged SHA. Verify local
   invocation separately from real Codex/Claude host invocation. Release products
   only after provider permissions, target/preview/rollback/budget gates are met.
6. Save public generic evidence and private deployment/project receipts separately.
   Record uncompleted criteria, source gaps and actual permissions without scores.
