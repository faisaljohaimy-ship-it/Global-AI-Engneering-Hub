# Master Upgrade Engine fixture: an existing system (synthetic)

`taskapp/` is a small task management web app built only on the Python standard library
(`http.server` + `sqlite3`). It is the "existing system" of Acceptance Scenario B
(`tests/test_upgrade_engine.py`): `engineering_os.upgrade_engine.upgrade` must upgrade an
isolated copy of it and never write the fixture itself.

- `app.py`, `store.py`, `schema.sql`: routes (`ROUTES` + `dispatch(method, target, conn, body)`),
  storage and schema.
- `data/tasks.db`: 300 synthetic tasks (generated deterministically; no real data).
- `templates/index.html`, `static/`: the Arabic task form, its stylesheet and logo.
- `tests/case_*.py`: the app's own unittest suite (11 tests). The `case_` prefix keeps it out
  of the repository's `test*.py` discovery, as in the self-healing fixture.
- `gaie-spec.json`: the system's existing specification (`gaie.spec/1`, Task entity only).
- `gaie-upgrade.json`: the upgrade manifest (test suite, spec, app convention, schema,
  databases, templates, assets).

Deliberate weaknesses the upgrade must find and fix:

1. Missing input validation: `POST /api/tasks` stores any title, status or priority (an empty
   or missing title even fails with 500) although the spec declares required fields, a maximum
   length and allowed values.
2. Accessibility and RTL gap: `<html>` has no `lang`/`dir`, the title input and the priority
   select have no `<label>`, and there is no viewport meta.
3. Slow query: `store.list_tasks(conn, status)` filters and sorts by columns without an index
   (`SCAN tasks` + `USE TEMP B-TREE FOR ORDER BY`).
4. Unused asset: `static/old-banner.png` is referenced nowhere.

The fixture must stay byte-for-byte unchanged by every test that upgrades it.
