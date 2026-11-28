# Tools: what was reviewed, and how far each one got

Tested on 2026-11-28 in a Claude Code cloud session: Linux x86_64, 4 cores, 15.7 GB,
Python 3.13.18, Node 22.23.5, uv 0.11.32, ripgrep 14.1.0. Network access there is limited
by policy: PyPI, the npm registry and nodejs.org answer; GitHub pages of other owners,
Context7, HuggingFace and OSV do not.

Each tool carries only the labels it earned. "Usable in the host" means it could be
called from that session as it was; "actually used" means it was used for real work
there, not only in a test.

| Tool | Pinned version | Licence | Reviewed | Installed | Tested | Usable in the host | Actually used | Blocked or limited by |
|---|---|---|---|---|---|---|---|---|
| Headroom (`headroom-ai`) | 0.44.0 | Apache-2.0 | yes | yes | yes | yes, in-process through `hr` | yes | proxy, wrap and MCP modes deliberately not used |
| ast-grep (`ast-grep-cli`) | 0.51.2 | MIT | yes | yes, with Headroom's lock | yes | yes | yes | none |
| Serena (`serena-agent`) | 2.1.0 | GPL-3.0-or-later | yes | yes | yes, Python and JavaScript | yes, one question per run through `sym` | yes | cannot be attached to a running session as a server |
| Repomix | 1.19.0 | MIT | yes | yes | yes | yes | no | none |
| Context Mode | 2.1.10 | Elastic-2.0 | yes | yes, with its own Node 24 | yes, as a standalone server | no | no | needs Node 24.15+, a plugin install and a restart |
| Context7 (`@upstash/context7-mcp`) | 4.9.1 seen, not installed | MIT | registry data only | no | no | no | no | its hosts are not reachable under the network policy |
| jCodeMunch (`jcodemunch-mcp`) | 1.108.497 seen, not installed | LicenseRef-jCodeMunch-Dual-Use-1 | licence field only | no | no | no | no | commercial use needs the owner's approval of its licence |
| tree-sitter CLI | not installed | MIT | no | no | no | no | no | not needed: ast-grep and Repomix embed the parsers |
| Superpowers | not installed | not reviewed | no | no | no | no | no | a plugin; needs a restart; its method is covered by the rules in SKILL.md |
| ripgrep | 14.1.0, preinstalled | MIT or Unlicense | preinstalled | preinstalled | yes | yes | yes | none |

Versions were chosen with a fourteen-day wait: each lock was resolved with
`--exclude-newer 2026-11-14`, so no package in a Python lock was published after that
date. Newer releases existed (Headroom 0.45.0 from 2026-11-22, Context Mode 2.2.4 from
2026-11-25) and were left for a later review.

## Headroom

- Source: `https://github.com/headroomlabs-ai/headroom`; PyPI `headroom-ai`. The PyPI
  project links to that repository. A different package named `headroom` also exists on
  PyPI and is not this tool.
- Installed from `locks/headroom.lock`: 68 packages with hashes. PyPI's advisory data
  lists no known vulnerability for any of the 68 at the pinned versions
  (`evidence/headroom-lock-audit.json`). OSV could not be reached for a second opinion.
- Used as a library inside its own Python environment. `hr` calls `headroom.compress()`
  for JSON and the `LogCompressor`, `SearchCompressor` and `DiffCompressor` transforms
  for logs, search results and patches.
- What the package can also do, and is not used here: a local proxy that sits between
  the agent and the model provider, wrappers that reroute agent traffic, durable
  installs, an MCP server, a telemetry beacon and an update check. The worker sets
  `HEADROOM_OFFLINE=1`, `HEADROOM_TELEMETRY=off`, `HEADROOM_UPDATE_CHECK=0` and
  `DO_NOT_TRACK=1`, and runs under `unshare -n` when the kernel permits, so it has no
  network at all.
- Measured limit: through `compress()` alone, only JSON was shortened. Logs, search
  results, prose and code came back unchanged until the dedicated transforms were called
  directly. Its model-based text compressor needs a download from HuggingFace and was not
  used.
- Headroom keeps its own small state folder in `~/.headroom`. The retrievable original
  that `hr` promises is `hr`'s own store, not that folder.

## Serena

- Source: `https://github.com/oraios/serena`; PyPI `serena-agent`. 74 packages in
  `locks/serena.lock`.
- GPL-3.0-or-later: it is run as a separate local program. Do not copy its code into a
  project under another licence.
- Run with `--agent-interface tools`, the dashboard and log window off, and
  `SERENA_USAGE_REPORTING=false`. Its home is `~/.gaie-tools/serena/home`.
- It writes `.serena/` into the project. `sym` adds that folder to the repository's
  private exclude file so it cannot be committed. Each project has its own index.
- The Python and TypeScript language servers are fetched from the npm registry on first
  use (pyright and typescript-language-server). JavaScript modules are served by the
  TypeScript server.

## Context Mode

- Source: `https://github.com/mksglu/context-mode`; npm `context-mode`. One package, no
  dependencies, no install script. A different package named `context-mode` on PyPI is
  not this tool.
- Elastic-2.0 is a source-available licence: using it locally is allowed; offering it to
  others as a hosted service is not. It is not copied into this repository.
- Every 2.x release requires Node 24.15 or newer. The bootstrap installs Node 24.22.3
  beside it, verified against a SHA-256 written in the script.
- As a standalone server it indexed files, returned exact lines for a search and ran
  code. `ctx_index` refuses paths outside the project.
- Its normal form is a plugin with hooks on session start, on every prompt and before and
  after nearly every tool call. That could not be attached to the managed session used
  for the test, so it is not adopted there. On a machine where it can be installed, use
  it for a large body of text that will be searched many times, and use `hr` for
  one-off command output. Do not pass one tool's output to the other.

## Context7

- Source: `https://github.com/upstash/context7`; npm `@upstash/context7-mcp`.
- Not installed: `mcp.context7.com` and `context7.com` did not answer from the test
  machine. To use it, the environment's owner has to allow those hosts.
- When it is available: read the project's lock file first, ask for the documentation of
  that exact version, and send library names and topics only.

## What the host does itself

These were observed in the test session and are not controlled by this skill:

- Tool definitions are loaded on demand by the host. Load a tool's definition only when
  you are about to call it.
- Prompt caching is managed by the host. The agent cannot switch it on or measure it.
  What helps is leaving the start of the conversation stable: do not rewrite instruction
  files or reshuffle tools in the middle of a task.
- The host compacts the conversation on its own. Manual compaction and clearing are user
  commands.
- No native language-server tool and no native programmatic tool calling were exposed.
  `sym` and plain local scripts stand in for them, and that is what they are: local
  scripts, not host features.
- Hooks: none are installed by this skill. A hook that rewrote every command's output
  would run on every call; calling `hr` when the output is expected to be large costs
  nothing otherwise.
