#!/usr/bin/env python3
"""Keep motion-library/components.json honest. Standard library only.

A component's runtime_status is "browser-verified" only while browser evidence exists
for the exact content now in the repository: the CSS its specification compiles to and
the runtime that plays it (or, for the shader, the Motion Lab that draws it). Change
either without re-running the browser verification and this tool returns the component
to "pending-browser". It also writes the Motion Lab rules for CSS components that have
no hand-written one, so the lab plays exactly what the specification says.

    python3 motion-library/component_status.py           check; exit 1 when out of date
    python3 motion-library/component_status.py --write   rewrite components.json and motions.css
"""

import argparse
import hashlib
import importlib.util
import json
import pathlib

LIBRARY = pathlib.Path(__file__).resolve().parent
ROOT = LIBRARY.parent
COMPONENTS = LIBRARY / "components.json"
EVIDENCE = "evidence/chromium.json"
LAB_CSS = ROOT / "motion-lab/motions.css"
LAB_FILES = ("index.html", "styles.css", "motions.css", "app.mjs")
MARK = "/* Generated from motion-library/specs by motion-library/component_status.py. Do not edit below this line. */"
BROWSER_ENGINES = ("css", "waapi")


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _compiler():
    spec = importlib.util.spec_from_file_location("hub_motion_compiler", LIBRARY / "compiler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lab_sha256():
    return _sha256(b"".join((ROOT / "motion-lab" / name).read_bytes() for name in LAB_FILES))


def verified(evidence):
    """Ids whose evidence still describes the files in the repository, mapped to the engines it covers."""
    inputs = evidence["inputs"]
    runtime_current = all(
        _sha256((LIBRARY / "runtime" / name).read_bytes()) == inputs.get(key)
        for name, key in (("hub-motion.mjs", "runtime_sha256"), ("core.mjs", "core_sha256"))
    )
    lab_current = lab_sha256() == inputs.get("lab_sha256")
    compiler, rows = _compiler(), {}
    for row in evidence["results"]:
        if not row.get("pass"):
            continue
        if row["kind"] == "spec" and runtime_current:
            path = ROOT / row["source"]
            if path.is_file():
                css = compiler.compile_css(compiler.load_spec(path))
                if _sha256(css.encode("utf-8")) == row["css_sha256"]:
                    rows[row["id"]] = BROWSER_ENGINES
        elif row["kind"] == "lab-engine" and lab_current:
            source = ROOT / row["source"]
            if source.is_file() and _sha256(source.read_bytes()) == row["source_sha256"]:
                rows[row["id"]] = (row["engine"],)
    return rows


def synced(document, evidence):
    """The component manifest as the evidence supports it."""
    proof = verified(evidence)
    rows = []
    for row in document["components"]:
        row = dict(row)
        if row["engine"] in proof.get(row["id"], ()):
            row["runtime_status"] = "browser-verified"
            row["evidence"] = EVIDENCE
        elif row.get("runtime_status") == "browser-verified":
            row["runtime_status"] = "pending-browser"
            row.pop("evidence", None)
        rows.append(row)
    return {**document, "components": rows}


def dump(document):
    """The manifest's own layout: one component per line."""
    head = {key: value for key, value in document.items() if key != "components"}
    lines = [json.dumps(row, separators=(",", ":"), ensure_ascii=False) for row in document["components"]]
    return json.dumps(head, indent=2, ensure_ascii=False)[:-2] + ',\n  "components": [\n' + ",\n".join(
        "    " + line for line in lines
    ) + "\n  ]\n}\n"


def lab_css(document, current):
    """motions.css with a generated rule for every CSS component the hand-written part lacks."""
    hand_written = current.split(MARK)[0].rstrip("\n") + "\n"
    compiler, lines = _compiler(), []
    for row in document["components"]:
        if row["engine"] != "css" or f".run-{row['id']} " in hand_written:
            continue
        spec = compiler.validate(compiler.load_spec(LIBRARY / row["spec"]))
        name = f"lab-{spec['id']}"
        lines.append(" ".join(line.strip() for line in compiler._keyframes(name, spec["keyframes"])))
        lines.append(f".run-{spec['id']} {{ animation: {name} {spec['duration_ms']}ms {spec['easing']} both; }}")
        if spec.get("rtl_mirror"):
            mirrored = compiler._keyframes(name + "-rtl", spec["keyframes"], compiler.mirrored)
            lines.append(" ".join(line.strip() for line in mirrored))
            lines.append(f'[dir="rtl"] .run-{spec["id"]} {{ animation-name: {name}-rtl; }}')
    return hand_written + ("\n".join([MARK] + lines) + "\n" if lines else "")


def load():
    return json.loads(COMPONENTS.read_text(encoding="utf-8")), json.loads((LIBRARY / EVIDENCE).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    document, evidence = load()
    css = lab_css(document, LAB_CSS.read_text(encoding="utf-8"))
    if args.write:
        LAB_CSS.write_text(css, encoding="utf-8")
    expected = synced(document, evidence)
    if args.write:
        COMPONENTS.write_text(dump(expected), encoding="utf-8")
    elif dump(expected) != COMPONENTS.read_text(encoding="utf-8") or css != LAB_CSS.read_text(encoding="utf-8"):
        raise SystemExit(
            "components.json or motion-lab/motions.css is out of date. Run "
            "`python3 motion-library/component_status.py --write`, then `node motion-library/verify/browser.mjs --write`, "
            "then the first command once more."
        )
    count = sum(row["runtime_status"] == "browser-verified" for row in expected["components"])
    print(f"{count} of {len(expected['components'])} components are browser-verified with current evidence")


if __name__ == "__main__":
    main()
