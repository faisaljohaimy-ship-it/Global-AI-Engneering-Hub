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
| Headroom (`headroom-ai`) | 0.45.0 | Apache-2.0 | yes | yes | yes | yes, through the hub's tool and `hr` | yes | proxy, wrap and MCP modes deliberately not used |
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
date. Context Mode 2.2.4 from 2026-11-25 existed and was left for a later review.
Headroom is the exception to the wait: the hub has one Headroom, pinned by its own reviewed
lock at 0.45.0, which was published on 2026-11-22. This skill uses that one and brings no
second, older copy.

## Headroom

- Source: `https://github.com/headroomlabs-ai/headroom`; PyPI `headroom-ai`. The PyPI
  project links to that repository. A different package named `headroom` also exists on
  PyPI and is not this tool.
- One integration for the whole hub. The hub's tool, `tools/headroom_context.py`, owns the
  private store of originals, the pinned version and the boundary the SDK runs behind.
  `hr` is a command-line front end to it and keeps nothing of its own.
- Installed from the hub's reviewed lock, `integrations/headroom/requirements.lock`: 68
  wheels for CPython 3.12 on Linux x86_64, each with its hash. The provenance, licence and
  advisory review of that closure is the hub's and is recorded in
  `integrations/headroom/README.md`. `scripts/bootstrap.sh headroom` installs exactly that
  file and refuses anything that would have to be built.
- A view is made in two steps. The hub tool is asked first: it returns a result only when
  the SDK reports it lossless, a round trip gives the original back, and the identifiers,
  paths and counts of the original are all still in it. When it has none, `hr` runs the
  SDK's transform for that kind of output: `compress()` for JSON, `LogCompressor`,
  `SearchCompressor` and `DiffCompressor` for logs, search results and patches. Those
  views are not verified lossless and their header says so.
- The boundary is the hub worker's, entered through its own code before any SDK import: a
  kernel filter that refuses IP sockets, no new privileges, limits on CPU time, memory and
  file size, an environment with no credentials, no proxy settings and no home folder, and
  private scratch folders. `hr` adds an empty network namespace on top where the kernel
  allows one, and sets `HEADROOM_UPDATE_CHECK=0` beside the hub's offline settings.
- What the hub tool refuses is not stored by `hr` either: JSON with credential fields, and
  anything over 2 MiB. Such output is shown as a plain head and tail with a note.
- What the package can also do, and is not used here: a local proxy that sits between
  the agent and the model provider, wrappers that reroute agent traffic, durable
  installs, an MCP server, a telemetry beacon and an update check.
- Measured limit: the hub tool's lossless path shortened two of four JSON samples and no
  log or search output. The transforms did the rest. The SDK's model-based text
  compressor needs a download from HuggingFace and was not used.

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
