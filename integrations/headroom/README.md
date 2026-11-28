# Optional Headroom SDK environment

The two standard-library launcher files are installed together by
`pack:headroom-context`. The dependency closure is **not** installed by project
registration and never becomes a product runtime requirement.

`requirements.lock` is the reviewed core/no-extras CPython 3.12 Linux x86_64
wheel closure for `headroom-ai==0.45.0`. Each of the 68 artifacts has its own
SHA256. Other Python/platform combinations require a separate compatibility and
artifact review; do not remove hashes to make installation succeed.

```sh
python3.12 -m venv /absolute/private/headroom-venv
/absolute/private/headroom-venv/bin/python -m pip --isolated install \
  --disable-pip-version-check --only-binary=:all: --require-hashes --no-compile \
  -r integrations/headroom/requirements.lock
/absolute/private/headroom-venv/bin/python tools/headroom_context.py status
```

Run the launcher with this interpreter. See
[the operating guide](../../docs/headroom-context-engineering.md) for real
optimization, durable full retrieval, privacy controls and failure handling.
Installation metadata alone is not proof of operation.

The upstream project is Apache-2.0 at reviewed commit
`ce0460cfa8598dc939243dbc7aec4b2d35f4e44a`. Dependencies retain their own terms,
including MPL/CNRI notices; this repository redistributes no wheel or installed
dependency. The initial closure review found no known advisory matches at the
review timestamp; this is not a guarantee against unknown vulnerabilities.
Retain package LICENSE/NOTICE files in an installed environment. A missing
packaged notice in tokenizers 0.23.3 remains a redistribution follow-up.

Dependabot proposes pip changes for review. A changed release, platform or hash
requires renewed provenance, license, advisory and operational tests; discovery
does not authorize installation or automatic approval. CI installs the exact
reviewed closure and executes real SDK positive/fallback and vendored invocation
tests inside the existing mandatory verification job, without model credentials.
