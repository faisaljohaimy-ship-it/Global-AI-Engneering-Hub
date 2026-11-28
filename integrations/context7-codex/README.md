# Context7 in Codex

This optional Streamable HTTP profile exposes `resolve-library-id` and
`query-docs` only. It uses the official Context7 endpoint, refers to a
Codex-side environment variable for its bearer token, requests host approval
prompts, and starts disabled. The bundled profile makes no account, installation, or
cost change. [Context7 client documentation](https://context7.com/docs/clients/codex) · [Codex MCP configuration](https://developers.openai.com/codex/mcp/)

Use the fragment in an isolated Codex profile or merge its single
`mcp_servers.context7` table into an authorized trusted project's
`.codex/config.toml`. Preserve an existing server entry for review. In managed
Codex Cloud, configure the connection and secret through the supported
environment settings for that Codex surface. The expected secret name is
`GAIE_CODEX_CONTEXT7_TOKEN`. Keep the value in the Codex-side secret store.

Enable the entry only after the hosted endpoint, an existing free entitlement,
and a credential in the Codex runtime have been approved. Codex can fall back
to an anonymous connection after manual enablement if no credential resolves.
Send only a public library name, its version, and a public documentation
topic. Keep source code, private identifiers, and credentials out of tool
arguments. Review returned snippets as third-party data before use.

Run `python3 -m unittest discover -s tests -p 'test_codex_context7.py'`
for the profile checks. Set `GAIE_CHECK_CODEX_CONTEXT7=1` on a Linux host with
Codex installed and loopback connections permitted. The native checks first
read the disabled profile in a fresh home, then dispatch both tools through a
fresh ephemeral Codex app-server thread to a synthetic loopback HTTP fixture.
The fixture verifies bearer transmission and that Codex rejects a third tool.
These checks run without a model turn, a service credential, or a hosted
Context7 call. Host prompt behavior and hosted MCP activation require separate
evidence.

The repository's existing Context7 evidence concerns an npm/stdio probe and
an anonymous hosted quota restriction. Keep that record separate from
this HTTP client profile. Authenticated Codex tool calls stay pending a
reviewed Codex-side credential and an authorized connection to the hosted
service. This profile does not read or install Claude Code settings.
