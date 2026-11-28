# Self-healing fixture (synthetic)

`webapp/` is a tiny stdlib web app (`http.server` + `sqlite3`) with its own unittest
suite (`webapp/suite/case_*.py`, deliberately not matching the repository's `test*.py`
discovery pattern). It carries three injected defects that `engineering_os.healing.heal`
must detect, trace to a root cause and repair in an isolated copy:

1. Broken route: `ROUTES` maps `GET /api/items/count` to `count_items`, which is not
   defined (the route is declared in `routes.json` with a `sql-scalar` template and is
   linked from `templates/index.html`).
2. Logic bug: `pricing.quote` applies the bulk discount for `quantity > 10`; the
   documented rule is ten or more (`test_bulk_discount_starts_at_ten` fails).
3. Dependency pin mismatch: `requirements.txt` pins `fixture-json-schema==1.2.0` while
   the integrity-bearing lock (`requirements.lock.json`) records `1.3.0`.

All package names, versions and hashes are synthetic; nothing is installed or fetched.
The fixture must stay byte-for-byte unchanged by every test that heals it.
