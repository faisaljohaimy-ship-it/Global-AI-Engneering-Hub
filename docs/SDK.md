# Engineering SDK 1.0.0

Python standard library only. Install selected capabilities through existing
registration after the release commit has merged:

```sh
python3 hub.py register /absolute/project --revision FULL_MERGED_SHA \
  --capability skill:hub-capabilities --capability pack:engineering-sdk --apply
python3 hub.py verify /absolute/project --strict
cd /absolute/project
python3 .engineering/sdk/engineering_sdk.py verify
python3 .engineering/sdk/engineering_sdk.py discover --query motion
```

`verify` works offline, comparing vendored bytes against the project's reviewed
manifest. It intentionally does not claim upstream authenticity. The existing
hub-link check proves provenance on updates. Ordinary application CI uses the
local verifier and has no network dependency on the public hub.

The SDK does not install Chromium, Remotion, WebGPU, AI providers or arbitrary MCP
servers. Chromium's reviewed test dependency remains locked in the hub's existing
lockfile. The Remotion adapter is implemented but engine execution and company
licensing must be reviewed per project. WebGPU remains a candidate. The shared
motion runtime is dependency-free and can be explicitly selected as a separate pack.

## Optional read-only MCP

Configure the SDK only in the host's existing project-scoped configuration. For
Claude Code merge this entry into `mcpServers` in `.mcp.json`; for Codex use the
equivalent `mcp_servers.engineering` entry in `.codex/config.toml`. Preserve any
other servers and use the absolute project path for `--project` and the script.

```json
{
  "engineering": {
    "command": "python3",
    "args": ["/absolute/project/.engineering/sdk/engineering_sdk.py", "mcp", "--project", "/absolute/project"]
  }
}
```

Tools: `engineering_discover(query)` and `engineering_verify()`. Newline-delimited
JSON-RPC stdio; no HTTP listener, credentials, installation or write tools. Wire
protocol is tested locally; availability in each agent host must be verified there.

## Private central registry and release governance

Maintain a private operations repository or access-controlled local registry with
`schema_version: 1` and a `projects` list. Each project records `repository`,
`visibility: private`, and `vercel: {team_id, project_id, root_directory: "."}`.
`registry --registry /private/registry.json` rejects duplicate repositories/targets.
Do not publish that file here. Project-local `.engineering/project.json` also records
`identity_verified` and `required_checks`. Leave identity false until the actual
Vercel Git connection, build settings and exact source have been read and verified.

`target` requires a clean checkout of the exact tested SHA and the exact contract.
`release --evidence /private/release.json` additionally requires success receipts
for every mandatory check, review approval at the same SHA, a verified rollback,
configuration preservation, zero additional cost and a smoke-tested staged
Production artifact without domain assignment. It validates supplied receipts;
the release operator must authenticate them against provider APIs. It never deploys.

Use one serialized release path per project. Capture domains, environment metadata
(never values), access policy, integrations, build settings and current production
ID before relinking. Keep existing Vercel project IDs. Fail closed when the connector
omits Git/build settings. Re-read all settings after a change. Preserve Rollback.

Dependabot proposes existing dependency/Action updates in bounded weekly batches;
new tool candidates are manual proposals. Review license, upstream identity, exact
lockfile revision, advisories, compatibility, tests and cost before adoption. Public
hub CI is enabled; private Actions and paid monitoring require verified allowance.
Use existing monitors and write-free smoke endpoints; do not enable a paid service.
