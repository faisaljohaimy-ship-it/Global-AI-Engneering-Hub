# Bounded security and dependency checks

Acceptance: malicious fixtures must fail while safe hashes, runtime credential
references, explicit argument-array subprocess calls and exact safe YAML loaders
pass. All three tracked npm lock scopes must be audited; high/critical findings,
missing locks, unsupported sources and unavailable registry responses block the
check. A passing check is evidence for these rules, not a claim of general safety.

Two independent GitHub Actions run on pull requests and `main`: **Security audit**
and **Dependency audit**. They use read-only permissions, SHA-pinned Actions,
checkout without persisted credentials, fixed timeouts and per-ref concurrency.
Dependency auditing also has a bounded weekly schedule and manual trigger.
Dependabot covers all three isolated tool environments and groups their shared
Playwright driver proposals; approval and new runtime receipts remain mandatory.
No paid security product, hosted scan provider, auto-fix, auto-merge or production
service is enabled. This public repository's standard runner
jobs use GitHub's included public-repository allowance; private adoption must
verify its own allowance and billing controls before enabling workflows.

```sh
python3 -m unittest discover -s tests -p test_security_scan.py -v
python3 scripts/security_scan.py scan
python3 scripts/security_scan.py scan --base FULL_IMMUTABLE_COMMIT_SHA
python3 scripts/security_scan.py dependencies
```

## Index secret and syntax checks

The scanner reads regular stage-zero **Git index blobs**, including newly staged
files. It does not scan untracked files, follow worktree symlinks, scan deleted
history or contact a provider. With `--base`, only changed candidate index blobs
relative to that full commit are scanned; CI scans the entire index.

Limits fail closed: 10,000 files; 2 MiB per file; 32 MiB total; local Git commands
have a 20-second timeout; the security job has a five-minute timeout. Binary blobs
containing NUL are counted and skipped. Non-UTF-8 text is decoded with replacement
so ASCII credential signatures remain detectable. Non-regular/unmerged entries
are refused. Oversized media needs a separately reviewed policy rather than an
unbounded scan or silent exclusion.

Rules cover private key markers; known OpenAI/Anthropic, GitHub, AWS, Google,
Stripe, Slack, Supabase, ElevenLabs and Resend key shapes; literal credential URLs;
long sensitive-name assignments and authentication/share query values; and JWTs
whose decoded role is `service_role` or `supabase_admin`. Real environment/key
files are forbidden, except explicitly named example/sample/template environment
files whose contents are still scanned. Explicit placeholder/runtime references
are allowed. Ordinary commit hashes, SHA-256 values and lockfile integrity hashes
do not trigger generic entropy heuristics. Diagnostics include only a redacted
path, line number and fixed rule ID, never source lines or matched values.
Literal Bearer tokens are covered as well; template-based Authorization headers
do not count as literal token values.

Python SAST parses AST without executing source. Import-aware checks cover
`subprocess` with a truthy or dynamic `shell` argument (including literal keyword
dicts), implicit OS/subprocess shell helpers, pickle loading, unsafe YAML loading
unless an explicit SafeLoader/CSafeLoader is selected, and `tempfile.mktemp`.
Syntax/complexity failures block the check. It is not whole-program taint,
scope/rebinding or interprocedural analysis. Dynamic aliases/keyword dicts,
arbitrary `eval`/`exec`, JavaScript/browser sinks, encoded/split credentials,
unknown key formats and private-data classification are outside this bounded
coverage. The hub's intentional pinned motion compiler execution remains subject
to its existing provenance checks and review, rather than a blanket claim that
all dynamic execution is safe.

## Exact lock dependency audit

The dependency job discovers all tracked `package-lock.json` scopes, with an
eight-scope cap. `motion-library/verify` and `motion-library/chromium-stack` are
mandatory; future quality-tool locks are included automatically. Each scope must
have a tracked package manifest, exact matching root versions, supported lock
format, exact package versions, npm registry URLs and SHA-512 integrity entries.
Unknown/file/git sources and loose ranges require review and fail closed.

For each scope it writes only its index `package.json` and lockfile into a fresh
temporary directory, then runs `npm audit --package-lock-only --ignore-scripts
--json --audit-level=high` against the public npm registry. There is no install,
package lifecycle execution or `npm audit fix`. Development dependencies are
included because these tools execute in engineering/CI. Authentication variables,
user npm configuration and repository npm configuration are not passed; only
transport proxy/CA settings and PATH are retained. Each request has a 60-second
timeout and the workflow has a ten-minute timeout. Output reports scope and
severity counts only, with child output capped at 2 MiB before collection.
Lower-severity findings remain visible; high/critical, invalid responses and
registry/network failures block the job.

The advisory feed is time-dependent; record the actual run rather than treating
an old green badge as permanent approval. npm registry auditing is read-only and
free of provider model/render calls. Other ecosystems, vendored binaries and
upstream license review remain separate checks. These jobs do not configure
branch protection; repository administrators must include them in existing
required-check rules if technical merge enforcement is desired.

## Local verification, 2026-11-27

The scanner's 22 adversarial/safe-fixture tests and the 134-test Python suite
passed against the isolated implementation. The staged index scan covered 176
text files, with no findings and no binary skips. Live read-only npm audits of
the two mandatory lock scopes returned zero findings at every severity. Future
quality-lock scopes are covered by the discovery regression; they need their
own actual audit after integration. These results do not claim a completed
GitHub Actions run, branch-protection enforcement or private-project assessment.
