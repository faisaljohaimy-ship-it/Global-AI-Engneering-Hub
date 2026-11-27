#!/usr/bin/env python3
"""Keep MOTION_CATALOG.json honest. Standard library only.

An entry is "implemented" and "runtime_verified" only while browser evidence exists for
the exact content now in the repository: the CSS its specification compiles to, and the
runtime that plays it. Change either without re-running the browser verification and
this tool returns the entry to "specification".

    python3 motion-library/catalog_status.py           check; exit 1 when out of date
    python3 motion-library/catalog_status.py --write   rewrite the catalog
"""

import argparse
import hashlib
import importlib.util
import json
import pathlib

LIBRARY = pathlib.Path(__file__).resolve().parent
ROOT = LIBRARY.parent
CATALOG = LIBRARY / "MOTION_CATALOG.json"
EVIDENCE = "motion-library/evidence/chromium.json"
NOTES = (
    "An entry is a specification unless its status is implemented. status, runtime_verified, spec, "
    "implementation and evidence are written by motion-library/catalog_status.py from browser evidence; "
    "do not edit them by hand. Twelve recovered entries; additions are engineering candidates, not a "
    "claim of exhaustive worldwide coverage or novelty."
)
PROOF_KEYS = ("spec", "implementation", "evidence")


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _compiler():
    spec = importlib.util.spec_from_file_location("hub_motion_compiler", LIBRARY / "compiler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verified(evidence):
    """Evidence rows that still describe the files in the repository, keyed by motion id."""
    inputs = evidence["inputs"]
    current = (
        _sha256((LIBRARY / "runtime/hub-motion.mjs").read_bytes()) == inputs["runtime_sha256"]
        and _sha256((LIBRARY / "runtime/hub-motion-base.css").read_bytes()) == inputs["base_css_sha256"]
    )
    if not current:
        return {}
    compiler, rows = _compiler(), {}
    for row in evidence["results"]:
        if not row.get("pass"):
            continue
        if row["kind"] == "spec":
            path = ROOT / row["source"]
            if path.is_file():
                css = compiler.compile_css(json.loads(path.read_text(encoding="utf-8")))
                if _sha256(css.encode("utf-8")) == row["css_sha256"]:
                    rows[row["id"]] = {"spec": row["source"]}
        elif row["kind"] == "runtime":
            rows[row["id"]] = {"implementation": row["implementation"]}
    return rows


def synced(catalog, evidence):
    """The catalog as the evidence supports it."""
    proof = verified(evidence)
    missing = sorted(set(proof) - {entry["id"] for entry in catalog["entries"]})
    if missing:
        raise ValueError("Evidence exists for ids that are not in the catalog: " + ", ".join(missing))
    entries = []
    for entry in catalog["entries"]:
        entry = {key: value for key, value in entry.items() if key not in PROOF_KEYS}
        entry["status"] = "implemented" if entry["id"] in proof else "specification"
        entry["runtime_verified"] = entry["id"] in proof
        if entry["id"] in proof:
            entry.update(proof[entry["id"]], evidence=EVIDENCE)
        entries.append(entry)
    return {**catalog, "notes": NOTES, "entries": entries}


def load():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    evidence = json.loads((ROOT / EVIDENCE).read_text(encoding="utf-8"))
    return catalog, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    catalog, evidence = load()
    expected = synced(catalog, evidence)
    count = sum(entry["runtime_verified"] for entry in expected["entries"])
    if args.write:
        CATALOG.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    elif expected != catalog:
        raise SystemExit(
            "MOTION_CATALOG.json does not match the browser evidence. Re-run "
            "`node motion-library/verify/browser.mjs --write`, then `python3 motion-library/catalog_status.py --write`."
        )
    print(f"{count} of {len(expected['entries'])} catalog entries are implemented with current browser evidence")


if __name__ == "__main__":
    main()
