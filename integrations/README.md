# Integration evidence

`PROGRAMS.json` is the 22-program discovery index. `EVIDENCE.json` records the
sanitized result of a harmless availability probe in one managed environment.

Evidence meanings:

- `official_mcp` + `authenticated_read`: the official connector answered a
  non-mutating metadata request. It does not prove write, generation, quota or cost.
- `local_executable`: a local version command succeeded. It does not prove a full
  production pipeline.
- `unavailable`: no callable official connector, executable or resolved package was
  present. No credential guessing or browser login was attempted.

Never store raw connector responses, emails, account/workspace identifiers, balances,
tokens or client file names here. Re-run probes per environment and keep mutations,
generation and deployments behind project-specific approval.
