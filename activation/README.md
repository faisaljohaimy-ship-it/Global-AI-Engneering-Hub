# Priority tools: what was installed and tested

Six tools are named as priorities in `catalog/priority-capability-packs.json`. This folder
holds, for each one, a pinned lock, a functional test that needs no provider key, and the
record of how far it got. `tools.json` is the record; the run that backs it is in
`docs/evidence/capability-activation-2026-11-28.json`.

| Tool | Pinned | Result on 2026-11-28 |
|---|---|---|
| Pydantic AI | `pydantic-ai-slim` 2.68.0 | six cases passed with a scripted model and no network |
| Promptfoo | 0.125.1 | offline evaluation ran: one assertion passed, one failed as written |
| Playwright MCP | `@playwright/mcp` 0.0.85 | six checks passed through a stdio probe |
| Chrome DevTools MCP | 1.13.0 | six checks passed through a stdio probe |
| Inspect AI | 0.3.289 | three cases passed against its mock model, after the owner allowed the tokenizer host |
| Context7 | `@upstash/context7-mcp` 4.7.0, no lock committed | started once in the session; the service asks for an API key (quota message) |

Run it again:

```bash
activation/activate.sh all          # installs under ~/.gaie-tools/activation, results in its out/ folder
```

Limits of this evidence:

- Context7's lock is not in this folder. `scripts/security_scan.py dependencies` accepts at most eight npm locks and the
  repository already has eight with this branch. `tools.json` records the package version and checksum instead.

- Everything ran in one Linux cloud session, with scripted, mock or echo models. Nothing
  here called a real model provider.
- The two MCP servers were started and driven by `mcp_probe.py`. They were not attached
  to an agent session, so whether a host discovers them is not shown.
- `catalog/registry.json` is unchanged: all six are still `discovered` there. Approving
  them, and recording the upstream git revision where `tools.json` has none, is for the
  coordinator who reviews this.
- Promptfoo's dependency tree had five moderate advisories at install time and none high
  or critical. The hub's dependency scan passes it, because that scan fails on high and
  critical findings only. It installs 691 packages and takes 758 MB.
