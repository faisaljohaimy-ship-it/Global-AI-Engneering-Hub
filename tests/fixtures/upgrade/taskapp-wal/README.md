# WAL-mode database overlay (synthetic, finding W2-UP-02)

An overlay for `../taskapp`: tests copy `taskapp` to a temporary directory and copy these files
over it. Nothing here is ever opened in place; a normal SQLite open would checkpoint the WAL
into the main file and change these bytes.

- `data/tasks.store`: the taskapp's 300 synthetic tasks in WAL journal mode (header bytes
  18-19 = 2).
- `data/tasks.store-wal`: five more committed rows (`Committed in the WAL 1..5`) that were never
  checkpointed, as in the directory of a running app. A complete read sees 305 rows; the main
  file alone holds 300.
- `gaie-upgrade.json`: the taskapp manifest with `data/tasks.store` added to `databases` (the
  name does not end in `.db`, so the detectors' database scan does not open it).

Produced once with the standard library: copy `taskapp/data/tasks.db`, `PRAGMA
journal_mode=WAL`, `PRAGMA wal_autocheckpoint=0`, insert the five rows, commit, then copy the
main file and the `-wal` while the connection is still open. The WAL salts are random, so a
regenerated pair differs in bytes but not in content.

Before the fix the upgrade migrated the main file only, left the stale `-wal` beside it and
reported 300 rows preserved; the upgraded copy then opened as "database disk image is
malformed". `tests/test_upgrade_fixes_wal.py` checks the snapshot, the migration and the full
upgrade.
