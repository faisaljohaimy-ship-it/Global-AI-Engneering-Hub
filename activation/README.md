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
| Context7 | remote `https://mcp.context7.com/mcp`; npm `@upstash/context7-mcp` 4.7.0 not used | `resolve-library-id` and `query-docs` returned documentation through `integrations/context7/probe.py` with the owner's key as an environment network secret (`docs/evidence/gaie-20-layers/context7.json`) |

Run it again:

```bash
activation/activate.sh all          # installs under ~/.gaie-tools/activation, results in its out/ folder
```

Limits of this evidence:

- Context7 has no lock in this folder and needs none. `scripts/security_scan.py dependencies` accepts at most eight npm
  locks and the repository has eight. Context7 is used as a remote MCP endpoint (`.mcp.json`,
  `integrations/context7/README.md`), so nothing is installed and the scan limit is unchanged. `tools.json` keeps the
  npm package record as measured, with a `remote` field for the route in use.

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
