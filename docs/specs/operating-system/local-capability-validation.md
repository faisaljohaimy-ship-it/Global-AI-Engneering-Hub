# Local capability validation

A reviewer or factory can call `python3 scripts/verify_operational_capabilities.py --only engineering-sdk` and read a JSON result. Omitting `--only` runs all five checks. Repeating it selects multiple checks. Exit status 1 identifies a blocked or failed check. The command accepts capability IDs from a fixed list. It does not accept commands, project paths, provider keys or prompts.

| Check | Acceptance |
| --- | --- |
| Engineering SDK | Start the stdio server, negotiate MCP, list its read-only tools, verify a synthetic file, and discover the reviewed Headroom entry. |
| Task coordination | Reopen a synthetic task store, reclaim its handover with a second actor label, and verify the journal and receipt. |
| Model routing | Return a blocked decision for the current registry without project evidence. |
| Motion SDK | Sample an existing motion twice at the same progress, compare two points in time, test reduced motion, export SVG, and close both instances. |
| Ripgrep | Return the expected Arabic line from a UTF-8 input using a literal query and the executable's normal CLI. |

The report records wall time and source digests for the files used by each check. `TESTED` applies to the fixture and its named local surface. A tested routing check can return a blocked model decision. The SDK check covers its stdio protocol and file verification. Native host discovery, provider access, GPU rendering, production readiness and dependency approval require their own evidence.

This extends the existing operating-system specification. Approved revisions, project registration, source provenance and deployment policies remain governed by the existing commands and release gates.
