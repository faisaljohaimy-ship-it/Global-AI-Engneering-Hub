# Bootstrap verification — 2026-11-27

This record contains no credentials, customer data, private repository names, or
private assets.

## Verified

- GitHub official connector can enumerate this repository and reports pull/push,
  triage, maintain, and admin permissions.
- HTTPS clone of the hub succeeds in the managed workspace.
- `python3 -m unittest discover -s tests -v` passes 8 tests.
- `python3 hub.py audit` validates 114 discovery records and 9 local skills.
- `motion-library/specs/fade-in.json` compiles to deterministic CSS with a
  reduced-motion fallback.

## Not verified

- Catalog dependencies remain discovery candidates; none is approved or installed.
- Other external programs remain unverified until their official connector performs
  a harmless authenticated read in the target environment.
- Browser rendering and production deployment were not performed.
- Private repositories are intentionally not enumerated in this public evidence.

## Reproduction

```sh
python3 -m unittest discover -s tests -v
python3 hub.py audit
python3 motion-library/compile.py motion-library/specs/fade-in.json --output /tmp/fade-in.css
test -s /tmp/fade-in.css
```
