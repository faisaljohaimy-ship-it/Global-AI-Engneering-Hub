# Unsafe schema SQL (synthetic attack fixture, finding W2-UP-01)

Schema files a target system could ship. A read-only audit once ran them with `executescript`, so
`ATTACH` (or `VACUUM INTO`) created and filled a database file outside the target while the audit
reported `files_written 0`. `tests/test_upgrade_fixes_sql.py` renders each template into a copy of
`../taskapp`, replacing `{outside}` with a private temporary directory, and proves that nothing is
created there and that the audit reports the statement as refused (`unsafe-schema-sql`).

- `attach.sql.tmpl`: `ATTACH DATABASE` + `CREATE TABLE side.planted` + `INSERT` (the reviewer's PoC).
- `vacuum-into.sql.tmpl`: `VACUUM INTO` a file.
- `load-extension.sql.tmpl`: a `load_extension()` call.
- `view-attach.sql.tmpl`: `ATTACH` without any `CREATE TABLE`; only the upgrade manifest's `schema`
  list names it, so the upgrade engine's own query audit (not the detectors' discovery) loads it.

The `.tmpl` suffix keeps these files out of every `*.sql` schema discovery.
