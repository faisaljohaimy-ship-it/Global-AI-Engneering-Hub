"""Purposeful-motion policy: every motion states a digital meaning, and none is random.

`governance/policies/motion-purpose.json` is the one editable statement of the owner's rule of
2026-11-28. This module loads it (duplicate JSON keys are refused), gives every record of the
covered motion registries one class, and lists what breaks the rule:

- `load_policy(root)`  the policy, shape-checked; `MotionPolicyError` when it cannot be trusted.
- `classify(registry, entry, policy)`  the class of one record, or `MotionPolicyError`.
- `validate(root, policy)`  the violations, each `{code, registry, id, detail}`; empty when clean.
- `report(root)`  counts per class and per registry, the violations and `ok`; it never raises.

Hard rules live in this file so that editing the policy file cannot relax them: the legacy ids
are the motions that existed before the rule and the list may only shrink, the withdrawn list
may only grow, the pinned counts may only fall, the meaning limits may only tighten, and every
source set keeps its roots and still refuses the probes below.

Limits: these are record and text checks. No browser is run, a stated meaning is not judged for
truth or quality, and the source scan is a screen for forbidden names, not a sandbox. The native
registry is trusted only while each row's `source_sha256` matches the file on disk; the camera
scene ids are read from the source text. Standard library only. SPDX-License-Identifier: MIT
"""
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY = "governance/policies/motion-purpose.json"
IMPLEMENTATION = "engineering_os/motion_policy.py"
CLASSES = ("purposeful", "legacy-unclassified", "reference-illustrative", "specification-index", "withdrawn")
REGISTRIES = ("native-engine", "nextgen-camera", "digital-shows", "reference-recipes", "catalog", "ported-sdk")
MAX_BYTES = 8 * 1024 * 1024
MAX_SOURCE_FILES = 2000
SOURCE_SUFFIX = ".mjs"

# The motions that existed before the rule (PR #16 engine motions and PR #25 camera scenes).
# `legacy_ids` in the policy must be a subset: the owner removes ids, nobody adds one.
BASELINE_LEGACY = {
    "native-engine": frozenset({
        "quantum-field-distortion", "quantum-energy-collapse", "quantum-particle-entanglement", "quantum-wave-propagation",
        "quantum-orbital-matrix", "quantum-light-tunnel", "quantum-singularity-reveal", "quantum-probability-cloud",
        "quantum-fractal-expansion", "quantum-energy-pulse", "glass-liquid-refraction", "glass-dynamic-dispersion",
        "glass-surface-ripple", "glass-card-elevation", "glass-metallic-flow", "glass-titanium-sweep",
        "glass-crystal-transformation", "glass-iridescent-morphing", "glass-frosted-focus", "glass-lens-distortion",
        "typography-bilingual-transition", "micro-magnetic-button", "shaders-wgsl-compute-particles",
        "atmosphere-procedural-fog", "atmosphere-electric-arc", "atmosphere-plasma-flow", "atmosphere-solar-flare",
        "atmosphere-aurora-wave", "atmosphere-energy-shield", "atmosphere-electromagnetic-field",
        "atmosphere-volumetric-clouds", "atmosphere-core-ignition", "atmosphere-shockwave",
        "compositions-quantum-master-sequence"}),
    "nextgen-camera": frozenset({"camera-drone-approach", "camera-infinite-flythrough", "camera-macro-to-micro"}),
}
# Drafted, found decorative and removed on 2026-11-28. `withdrawn_ids` must stay a superset.
BASELINE_WITHDRAWN = {
    "native-engine": frozenset({"lighting-lens-flare", "lighting-studio-spotlight", "lighting-volumetric-beams",
                                "shaders-raymarched-geometry", "shaders-sdf-morph"}),
    "nextgen-camera": frozenset(),
}
PIN_CEILING = {"reference-recipes": 400, "catalog": 156}
PINNED_CLASS = {"reference-recipes": "reference-illustrative", "catalog": "specification-index"}
MEANING_KEYS = ("ar", "en")
MIN_CHARS = 12
MAX_CHARS = 240
# Source roots every set must keep scanning; True where the scan must also descend.
REQUIRED_ROOTS = {
    "pure": {"packages/motion-engines/motions": True, "motion-library/expansion": False, "packages/digital-shows/kit.mjs": False},
    "runtime": {"packages/motion-engines": False, "packages/motion-engines/core": False, "packages/motion-engines/engines": False,
                "packages/motion-engines/shaders": False, "packages/motion-engines/adapters": False,
                "packages/motion-sdk": False, "motion-library/runtime": False},
}
REQUIRED_GROUPS = {"pure": ("unseeded-randomness", "wall-clock", "timer"), "runtime": ("unseeded-randomness", "clock-as-seed")}
# Each pattern group must still refuse these lines, whatever the policy file says.
PROBES = {
    "unseeded-randomness": ("x = Math.random();", "x = Math . random ();", "crypto.getRandomValues(buffer);", "id = crypto.randomUUID();"),
    "wall-clock": ("t = Date.now();", "t = new Date();", "t = performance.now();"),
    "timer": ("requestAnimationFrame(tick);", "setTimeout(tick, 16);", "setInterval(tick, 16);"),
    "clock-as-seed": ("const seed = Date.now();", "const next = mulberry32(performance.now());",
                      "const next = seeded(Date.now() >>> 0);", "options.seed = new Date().getTime();"),
}

_REL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@+-]*(?:/[A-Za-z0-9_.@+-]+)*$")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_ARABIC = re.compile("[\u0600-\u06ff]")
_CAMERA_BLOCK = re.compile(r"const\s+specs\s*=\s*\[(.*?)\n\];", re.S)
_CAMERA_ROW = re.compile(r"^\s*\[", re.M)
_CAMERA_ID = re.compile(r"""^\s*\[\s*(['"])([^'"\n]*)\1""", re.M)
_TOP = frozenset({"schema_version", "policy_version", "implementation", "effective_from", "authority", "rule", "meaning",
                  "classes", "registries", "owner_decisions", "sources", "invariants", "enforcement"})
_REGISTRY_KEYS = {
    "native-engine": frozenset({"what", "record", "sources", "legacy_ids", "withdrawn_ids"}),
    "nextgen-camera": frozenset({"what", "source", "legacy_ids", "withdrawn_ids"}),
    "digital-shows": frozenset({"what", "record", "source"}),
    "reference-recipes": frozenset({"what", "record", "list", "class", "pinned_count"}),
    "catalog": frozenset({"what", "record", "list", "components", "class", "pinned_count"}),
    "ported-sdk": frozenset({"what", "record", "receipt"}),
}
_PATH_KEYS = ("record", "sources", "source", "components", "receipt")


class MotionPolicyError(ValueError):
    pass


def _need(condition, message):
    if not condition:
        raise MotionPolicyError(message)


def _pairs(rows):
    result = {}
    for key, value in rows:
        _need(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(name):
    raise MotionPolicyError(f"invalid JSON number: {name}")


def load_json(data):
    """Parse JSON bytes or text; a duplicate key or a non-finite number is refused."""
    try:
        if isinstance(data, (bytes, bytearray)):
            data = bytes(data).decode("utf-8")
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MotionPolicyError(f"invalid JSON: {error}") from None
    except RecursionError:
        raise MotionPolicyError("invalid JSON: nested too deeply") from None


def _file(root, relative):
    """A regular file inside the tree: no traversal and no symlink in any component."""
    _need(isinstance(relative, str) and bool(_REL.fullmatch(relative)), f"unsafe repository path: {relative!r}")
    parts = pathlib.PurePosixPath(relative).parts
    _need(".." not in parts and ".git" not in parts, f"unsafe repository path: {relative!r}")
    result = pathlib.Path(root)
    for part in parts:
        result = result / part
        _need(not result.is_symlink(), f"{relative}: symlink refused")
    return result


def _read(root, relative):
    path = _file(root, relative)
    _need(path.is_file(), f"{relative}: missing")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    except OSError as error:
        raise MotionPolicyError(f"{relative}: unreadable ({error.strerror or error.__class__.__name__})") from None
    _need(len(data) <= MAX_BYTES, f"{relative}: larger than {MAX_BYTES} bytes")
    return data


def _text(root, relative):
    try:
        return _read(root, relative).decode("utf-8")
    except UnicodeError:
        raise MotionPolicyError(f"{relative}: not UTF-8") from None


def _sentence(value, field, limit=1200):
    _need(isinstance(value, str) and value.strip() == value and 0 < len(value) <= limit, f"policy: {field} must be plain text")
    return value


def _bilingual(value, field):
    _need(isinstance(value, dict) and sorted(value) == ["ar", "en"], f"policy: {field} needs exactly ar and en")
    _sentence(value["en"], f"{field}.en")
    _need(bool(_ARABIC.search(_sentence(value["ar"], f"{field}.ar"))), f"policy: {field}.ar must be Arabic")


def _ids(value, field):
    _need(isinstance(value, list) and all(isinstance(item, str) and _ID.fullmatch(item) for item in value),
          f"policy: {field} must list motion ids")
    _need(len(set(value)) == len(value), f"policy: {field} repeats an id")
    return value


def _count(value, field):
    _need(type(value) is int and 0 <= value <= 100000, f"policy: {field} must be a count")
    return value


def _check(policy):
    """Shape only. What the policy may not relax is reported by `validate`, not raised here."""
    _need(isinstance(policy, dict) and set(policy) == _TOP, "policy: unexpected or missing top-level keys")
    _need(policy["schema_version"] == 1 and type(policy["schema_version"]) is int, "policy: schema_version must be 1")
    _need(isinstance(policy["policy_version"], str) and bool(_VERSION.fullmatch(policy["policy_version"])), "policy: policy_version must be x.y.z")
    _need(policy["implementation"] == IMPLEMENTATION, f"policy: implementation must be {IMPLEMENTATION}")
    _need(isinstance(policy["effective_from"], str) and bool(_DATE.fullmatch(policy["effective_from"])), "policy: effective_from must be YYYY-MM-DD")
    _sentence(policy["authority"], "authority")
    _bilingual(policy["rule"], "rule")

    meaning = policy["meaning"]
    _need(isinstance(meaning, dict) and set(meaning) == {"keys", "min_chars", "max_chars", "arabic_script_in", "description"},
          "policy: meaning has unexpected or missing keys")
    _need(meaning["keys"] == list(MEANING_KEYS) and meaning["arabic_script_in"] == "ar", "policy: a meaning is exactly ar and en, with Arabic script in ar")
    _need(0 < _count(meaning["min_chars"], "meaning.min_chars") < _count(meaning["max_chars"], "meaning.max_chars"), "policy: meaning.min_chars must be below max_chars")
    _sentence(meaning["description"], "meaning.description")

    classes = policy["classes"]
    _need(isinstance(classes, dict) and set(classes) == set(CLASSES), f"policy: classes must be {', '.join(CLASSES)}")
    for name in CLASSES:
        _bilingual(classes[name], f"classes.{name}")

    registries = policy["registries"]
    _need(isinstance(registries, dict) and set(registries) == set(REGISTRIES), f"policy: registries must be {', '.join(REGISTRIES)}")
    for name in REGISTRIES:
        spec = registries[name]
        _need(isinstance(spec, dict) and set(spec) == _REGISTRY_KEYS[name], f"policy: registries.{name} has unexpected or missing keys")
        _sentence(spec["what"], f"registries.{name}.what")
        for key in _PATH_KEYS:
            if key in spec:
                _need(isinstance(spec[key], str) and bool(_REL.fullmatch(spec[key])) and ".." not in spec[key].split("/"),
                      f"policy: registries.{name}.{key} must be a repository path")
        if "legacy_ids" in spec:
            legacy = _ids(spec["legacy_ids"], f"registries.{name}.legacy_ids")
            withdrawn = _ids(spec["withdrawn_ids"], f"registries.{name}.withdrawn_ids")
            _need(not set(legacy) & set(withdrawn), f"policy: registries.{name} lists an id as both legacy and withdrawn")
        if "pinned_count" in spec:
            _count(spec["pinned_count"], f"registries.{name}.pinned_count")
            _need(spec["class"] == PINNED_CLASS[name], f"policy: registries.{name}.class must be {PINNED_CLASS[name]}")
            _need(isinstance(spec["list"], str) and bool(_ID.fullmatch(spec["list"])), f"policy: registries.{name}.list must name the list")

    decisions = policy["owner_decisions"]
    _need(isinstance(decisions, dict) and set(decisions) == {"how", "records"} and isinstance(decisions["records"], list),
          "policy: owner_decisions needs how and records")
    _sentence(decisions["how"], "owner_decisions.how")
    seen = set()
    for index, record in enumerate(decisions["records"]):
        field = f"owner_decisions.records[{index}]"
        _need(isinstance(record, dict) and set(record) == {"registry", "id", "decision", "date", "note"}, f"policy: {field} needs registry, id, decision, date and note")
        _need(record["registry"] in BASELINE_LEGACY, f"policy: {field}.registry must be one of {', '.join(sorted(BASELINE_LEGACY))}")
        _need(isinstance(record["id"], str) and bool(_ID.fullmatch(record["id"])), f"policy: {field}.id must be a motion id")
        _need(record["decision"] in ("promoted", "withdrawn"), f"policy: {field}.decision must be promoted or withdrawn")
        _need(isinstance(record["date"], str) and bool(_DATE.fullmatch(record["date"])), f"policy: {field}.date must be YYYY-MM-DD")
        _sentence(record["note"], f"{field}.note", 400)
        _need((record["registry"], record["id"]) not in seen, f"policy: {field} repeats a decision")
        seen.add((record["registry"], record["id"]))

    sources = policy["sources"]
    _need(isinstance(sources, dict) and set(sources) == {"comment_lines", "seeded_randomness", "patterns", "sets", "not_covered"},
          "policy: sources has unexpected or missing keys")
    _sentence(sources["comment_lines"], "sources.comment_lines")
    _sentence(sources["not_covered"], "sources.not_covered")
    _bilingual(sources["seeded_randomness"], "sources.seeded_randomness")
    patterns = sources["patterns"]
    _need(isinstance(patterns, dict) and bool(patterns), "policy: sources.patterns must name pattern groups")
    for group, rows in patterns.items():
        _need(bool(_ID.fullmatch(group)) and isinstance(rows, list) and bool(rows), f"policy: sources.patterns.{group} must list patterns")
        for pattern in rows:
            _need(isinstance(pattern, str) and 0 < len(pattern) <= 300, f"policy: sources.patterns.{group} has an invalid pattern")
            try:
                re.compile(pattern)
            except re.error:
                raise MotionPolicyError(f"policy: sources.patterns.{group} has a pattern that does not compile") from None
    sets = sources["sets"]
    _need(isinstance(sets, dict) and set(sets) == set(REQUIRED_ROOTS), f"policy: sources.sets must be {', '.join(REQUIRED_ROOTS)}")
    for name, spec in sets.items():
        _need(isinstance(spec, dict) and set(spec) == {"what", "roots", "forbidden"}, f"policy: sources.sets.{name} needs what, roots and forbidden")
        _sentence(spec["what"], f"sources.sets.{name}.what")
        _need(isinstance(spec["roots"], list) and bool(spec["roots"]), f"policy: sources.sets.{name}.roots must list paths")
        for root in spec["roots"]:
            _need(isinstance(root, dict) and set(root) == {"path", "recursive"} and type(root["recursive"]) is bool
                  and isinstance(root["path"], str) and bool(_REL.fullmatch(root["path"])) and ".." not in root["path"].split("/"),
                  f"policy: sources.sets.{name}.roots needs path and recursive")
        _need(isinstance(spec["forbidden"], list) and bool(spec["forbidden"]) and all(group in patterns for group in spec["forbidden"]),
              f"policy: sources.sets.{name}.forbidden must name pattern groups")

    _need(isinstance(policy["invariants"], list) and bool(policy["invariants"]), "policy: invariants must be listed")
    for index, line in enumerate(policy["invariants"]):
        _sentence(line, f"invariants[{index}]")
    _need(isinstance(policy["enforcement"], list) and bool(policy["enforcement"]), "policy: enforcement must be listed")
    for index, row in enumerate(policy["enforcement"]):
        _need(isinstance(row, dict) and set(row) == {"path", "what"} and isinstance(row["path"], str) and bool(_REL.fullmatch(row["path"])),
              f"policy: enforcement[{index}] needs path and what")
        _sentence(row["what"], f"enforcement[{index}].what")
    return policy


def load_policy(root=ROOT):
    """The policy file of a tree, parsed without duplicate keys and shape-checked."""
    return _check(load_json(_read(root, POLICY)))


def _bounds(policy):
    # A policy that loosens the limits is a violation; the fixed limits still apply to every meaning.
    return max(MIN_CHARS, policy["meaning"]["min_chars"]), min(MAX_CHARS, policy["meaning"]["max_chars"])


def valid_meaning(meaning, policy):
    """One Arabic and one English sentence and nothing else (validMeaning in tools/build_registry.mjs)."""
    low, high = _bounds(policy)
    if not isinstance(meaning, dict) or sorted(meaning) != list(MEANING_KEYS):
        return False
    if not all(isinstance(value, str) and len(value.strip()) >= low and len(value) <= high for value in meaning.values()):
        return False
    return bool(_ARABIC.search(meaning["ar"]))


def _class_of(registry, entry, policy):
    """(class, None) for a record that fits the policy, or (None, (code, detail)) for one that does not."""
    _need(registry in REGISTRIES, f"unknown registry: {registry!r}")
    _need(isinstance(entry, dict) and isinstance(entry.get("id"), str) and bool(entry["id"]), f"{registry}: a record needs an id")
    spec = policy["registries"][registry]
    if registry in PINNED_CLASS:
        return spec["class"], None
    identifier, meaning = entry["id"], entry.get("meaning")
    if identifier in spec.get("withdrawn_ids", ()):
        return "withdrawn", None
    pinned = identifier in spec.get("legacy_ids", ())
    if registry == "nextgen-camera":
        if pinned:
            return "legacy-unclassified", None
        return None, ("missing-meaning", "a camera scene source has no meaning field: a new scene is a native motion with a meaning, or it is not added")
    if meaning is None:
        if pinned:
            return "legacy-unclassified", None
        return None, ("missing-meaning", "states no digital meaning and is not a pinned legacy id")
    if not valid_meaning(meaning, policy):
        return None, ("invalid-meaning", "meaning must be exactly one English and one Arabic sentence (en, ar) within the policy limits")
    if pinned:
        return None, ("legacy-stale", "pinned as legacy but now states a meaning: record the promotion in owner_decisions and remove the id from legacy_ids")
    return "purposeful", None


def classify(registry, entry, policy=None):
    """The policy class of one record of a covered registry.

    Raises `MotionPolicyError` for a record that fits no class, so a motion without a valid
    meaning is never answered as purposeful.
    """
    policy = load_policy() if policy is None else _check(policy)
    cls, problem = _class_of(registry, entry, policy)
    if problem:
        raise MotionPolicyError(f"{registry}/{entry['id']}: {problem[0]}: {problem[1]}")
    return cls


def _violation(out, code, registry, identifier, detail):
    out.append({"code": code, "registry": registry, "id": identifier, "detail": detail})


def _hard_rules(policy, out):
    for name, baseline in BASELINE_LEGACY.items():
        spec = policy["registries"][name]
        for identifier in sorted(set(spec["legacy_ids"]) - baseline):
            _violation(out, "legacy-list-grew", name, identifier, "not one of the motions that existed before the rule: legacy_ids may only shrink")
        for identifier in sorted(BASELINE_WITHDRAWN[name] - set(spec["withdrawn_ids"])):
            _violation(out, "withdrawn-list-shrank", name, identifier, "a withdrawn id may not be removed from withdrawn_ids")
    for name, ceiling in PIN_CEILING.items():
        if policy["registries"][name]["pinned_count"] > ceiling:
            _violation(out, "pin-raised", name, None, f"pinned_count may only fall from {ceiling}")
    meaning = policy["meaning"]
    if meaning["min_chars"] < MIN_CHARS or meaning["max_chars"] > MAX_CHARS:
        _violation(out, "rule-relaxed", None, "meaning", f"meaning limits may only tighten from {MIN_CHARS}..{MAX_CHARS} characters")
    compiled = {group: [re.compile(pattern) for pattern in rows] for group, rows in policy["sources"]["patterns"].items()}
    for group, probes in PROBES.items():
        for probe in probes:
            if not any(pattern.search(probe) for pattern in compiled.get(group, ())):
                _violation(out, "rule-relaxed", None, group, f"the {group} patterns no longer refuse: {probe}")
    for name, roots in REQUIRED_ROOTS.items():
        spec = policy["sources"]["sets"][name]
        listed = {row["path"]: row["recursive"] for row in spec["roots"]}
        for root, descend in roots.items():
            if root not in listed or (descend and not listed[root]):
                _violation(out, "rule-relaxed", None, name, f"source set {name} must keep scanning {root}")
        for group in REQUIRED_GROUPS[name]:
            if group not in spec["forbidden"]:
                _violation(out, "rule-relaxed", None, name, f"source set {name} must keep refusing {group}")
    return compiled


def _rows(root, relative, key):
    record = load_json(_read(root, relative))
    rows = record.get(key) if isinstance(record, dict) else None
    _need(isinstance(rows, list) and all(isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] for row in rows),
          f"{relative}: {key} must be a list of records with ids")
    return record, rows


def _classify_rows(name, rows, policy, items, out):
    seen = set()
    for row in rows:
        if row["id"] in seen:
            _violation(out, "duplicate-id", name, row["id"], "listed twice")
            continue
        seen.add(row["id"])
        cls, problem = _class_of(name, row, policy)
        if problem:
            _violation(out, problem[0], name, row["id"], problem[1])
        items.append({"registry": name, "id": row["id"], "class": cls, "status": row.get("status")})
    return seen


def _native(root, policy, name, items, out):
    spec = policy["registries"][name]
    _, rows = _rows(root, spec["record"], "motions")
    on_disk = {}
    directory = _file(root, spec["sources"])
    _need(directory.is_dir(), f"{spec['sources']}: missing")
    for module in sorted(path for path in directory.iterdir() if path.is_dir() and not path.is_symlink()):
        for path in sorted(module.glob(f"*{SOURCE_SUFFIX}")):
            on_disk[f"{module.name}-{path.name[:-len(SOURCE_SUFFIX)]}"] = f"{spec['sources']}/{module.name}/{path.name}"
    withdrawn = set(spec["withdrawn_ids"])
    for row in rows:
        # A withdrawn id must not come back; its class is still answered so the count stays honest.
        if row["id"] in withdrawn:
            _violation(out, "withdrawn-present", name, row["id"], "a withdrawn motion has a registry row")
    registered = _classify_rows(name, [row for row in rows if row["id"] not in withdrawn], policy, items, out)
    for row in rows:
        identifier, source = row["id"], on_disk.get(row["id"])
        if identifier in withdrawn:
            continue
        if source is None or row.get("source") != source:
            _violation(out, "registry-stale", name, identifier, "the registry row has no matching source file: rebuild the registry")
        elif not isinstance(row.get("source_sha256"), str) or hashlib.sha256(_read(root, source)).hexdigest() != row["source_sha256"]:
            _violation(out, "registry-stale", name, identifier, "the source changed since the registry was built: its meaning is not trusted until the registry is rebuilt")
    for identifier in sorted(set(on_disk) - registered):
        if identifier in withdrawn:
            _violation(out, "withdrawn-present", name, identifier, f"a withdrawn motion has a source on disk: {on_disk[identifier]}")
        else:
            _violation(out, "unregistered-source", name, identifier, f"{on_disk[identifier]} is not in the registry, so its meaning was never checked")
    for identifier in sorted(set(spec["legacy_ids"]) - registered):
        _violation(out, "legacy-stale", name, identifier, "pinned as legacy but not in the registry: record the withdrawal in owner_decisions and move the id to withdrawn_ids")


def camera_ids(text):
    """The scene ids declared in the `specs` table of nextgen-camera.mjs, read from its text."""
    block = _CAMERA_BLOCK.search(text)
    _need(block is not None, "camera source: the specs table was not found")
    ids = [identifier for _, identifier in _CAMERA_ID.findall(block.group(1))]
    _need(bool(ids) and len(ids) == len(_CAMERA_ROW.findall(block.group(1))) and all(_ID.fullmatch(identifier) for identifier in ids),
          "camera source: the specs table could not be read")
    return ids


def _camera(root, policy, name, items, out):
    spec = policy["registries"][name]
    ids = camera_ids(_text(root, spec["source"]))
    withdrawn = set(spec["withdrawn_ids"])
    for identifier in ids:
        if identifier in withdrawn:
            _violation(out, "withdrawn-present", name, identifier, f"a withdrawn scene is still declared in {spec['source']}")
    declared = _classify_rows(name, [{"id": identifier} for identifier in ids if identifier not in withdrawn], policy, items, out)
    for identifier in sorted(set(spec["legacy_ids"]) - declared):
        _violation(out, "legacy-stale", name, identifier, "pinned as legacy but not declared in the camera source: record the withdrawal in owner_decisions")


def _shows(root, policy, name, items, out):
    spec = policy["registries"][name]
    record, rows = _rows(root, spec["record"], "scenes")
    if record.get("kit_sha256") != hashlib.sha256(_read(root, spec["source"])).hexdigest():
        _violation(out, "registry-stale", name, None, "the kit changed since its registry was built: the scene meanings are not trusted until it is rebuilt")
    _classify_rows(name, rows, policy, items, out)


def _pinned(root, policy, name, items, out):
    spec = policy["registries"][name]
    _, rows = _rows(root, spec["record"], spec["list"])
    seen = _classify_rows(name, rows, policy, items, out)
    if len(seen) > spec["pinned_count"]:
        _violation(out, "count-above-pin", name, None, f"{len(seen)} rows, pinned at {spec['pinned_count']}: a new row needs a stated meaning and an owner decision, not a larger pin")
    elif len(seen) < spec["pinned_count"]:
        _violation(out, "pin-stale", name, None, f"{len(seen)} rows, pinned at {spec['pinned_count']}: lower pinned_count so that the set cannot grow back")
    if "components" in spec:
        _, components = _rows(root, spec["components"], "components")
        for identifier in sorted({row["id"] for row in components} - seen):
            _violation(out, "unindexed-component", name, identifier, f"a component of {spec['components']} has no catalogue row")


def _ported(root, policy, name, items, out):
    """Universal Motion SDK motions ported from earlier branches: the manifest names each module and its ids,
    the browser receipt (bound to each module's SHA-256) carries the meanings. No legacy allowance."""
    spec = policy["registries"][name]
    manifest = load_json(_read(root, spec["record"]))
    receipt = load_json(_read(root, spec["receipt"]))
    _need(isinstance(manifest, dict) and isinstance(manifest.get("groups"), list), f"{spec['record']}: groups must be a list")
    _need(isinstance(receipt, dict) and isinstance(receipt.get("groups"), dict), f"{spec['receipt']}: groups must be an object")
    rows = []
    for group in manifest["groups"]:
        _need(isinstance(group, dict) and isinstance(group.get("source"), str) and isinstance(group.get("ids"), list),
              f"{spec['record']}: a group needs a source and ids")
        proof = receipt["groups"].get(group["source"])
        if not isinstance(proof, dict) or proof.get("source_sha256") != hashlib.sha256(_read(root, group["source"])).hexdigest():
            _violation(out, "registry-stale", name, group["source"],
                       "the module changed since its browser proof: its meanings are not trusted until it is proven again")
            continue
        motions = proof.get("motions")
        _need(isinstance(motions, list) and all(isinstance(row, dict) for row in motions), f"{spec['receipt']}: motions must be a list")
        if [row.get("id") for row in motions] != group["ids"]:
            _violation(out, "registry-stale", name, group["source"], "the proof covers other motions than the manifest")
        rows.extend(row for row in motions if isinstance(row.get("id"), str) and row["id"])
    _classify_rows(name, rows, policy, items, out)


def _decisions(policy, items, out):
    by_key = {(item["registry"], item["id"]): item for item in items}
    for name, baseline in BASELINE_LEGACY.items():
        spec = policy["registries"][name]
        gone = baseline - set(spec["legacy_ids"])
        records = {record["id"]: record for record in policy["owner_decisions"]["records"] if record["registry"] == name}
        for identifier in sorted(gone - set(records)):
            _violation(out, "undecided-removal", name, identifier, "left legacy_ids without an owner_decisions record")
        for identifier, record in sorted(records.items()):
            if identifier not in gone:
                _violation(out, "decision-mismatch", name, identifier, "a decision is recorded but the id is still pinned, or was never a legacy id")
            elif record["decision"] == "withdrawn":
                if identifier not in spec["withdrawn_ids"]:
                    _violation(out, "decision-mismatch", name, identifier, "recorded as withdrawn but not listed in withdrawn_ids")
            elif name != "native-engine":
                _violation(out, "decision-mismatch", name, identifier, "a camera scene has no meaning field: it can stay legacy or be withdrawn, not promoted")
            else:
                item = by_key.get((name, identifier))
                if not item or item["class"] != "purposeful" or item["status"] != "operational":
                    _violation(out, "promotion-unproven", name, identifier, "recorded as promoted but not purposeful and operational in the registry")


def _source_files(root, spec, out):
    files = {}
    for row in spec["roots"]:
        base = _file(root, row["path"])
        if base.is_file():
            found = [base]
        elif base.is_dir():
            found = sorted(base.rglob(f"*{SOURCE_SUFFIX}") if row["recursive"] else base.glob(f"*{SOURCE_SUFFIX}"))
        else:
            _violation(out, "unreadable-record", None, row["path"], "a covered source root is missing")
            continue
        for path in found:
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file():
                _violation(out, "unreadable-record", None, relative, "a covered source must be a regular file")
            else:
                files[relative] = path
    _need(len(files) <= MAX_SOURCE_FILES, "too many source files to scan")
    return files


def scan_source(text, patterns):
    """(line, pattern) for every forbidden pattern in a source; `//` comment lines are not code."""
    code = "\n".join("" if line.lstrip().startswith("//") else line for line in text.split("\n"))
    hits = []
    for pattern in patterns:
        for match in pattern.finditer(code):
            hits.append((code.count("\n", 0, match.start()) + 1, pattern.pattern))
    return sorted(set(hits))


def _sources(root, policy, compiled, out):
    scanned = {}
    for name, spec in policy["sources"]["sets"].items():
        files = _source_files(root, spec, out)
        scanned[name] = len(files)
        for relative, path in sorted(files.items()):
            try:
                text = _text(root, relative)
            except MotionPolicyError as error:
                _violation(out, "unreadable-record", None, relative, str(error))
                continue
            for group in spec["forbidden"]:
                for line, pattern in scan_source(text, compiled[group]):
                    _violation(out, "forbidden-source", None, f"{relative}:{line}", f"{group}: matches {pattern} (source set {name})")
    return scanned


def _survey(root, policy):
    root = pathlib.Path(root)
    policy = load_policy(root) if policy is None else _check(policy)
    items, out = [], []
    compiled = _hard_rules(policy, out)
    steps = {"native-engine": _native, "nextgen-camera": _camera, "digital-shows": _shows,
             "reference-recipes": _pinned, "catalog": _pinned, "ported-sdk": _ported}
    for name in REGISTRIES:
        try:
            steps[name](root, policy, name, items, out)
        except MotionPolicyError as error:
            # A record that cannot be read proves nothing: it is a violation, never a pass.
            _violation(out, "unreadable-record", name, None, str(error))
    _decisions(policy, items, out)
    scanned = _sources(root, policy, compiled, out)
    for row in policy["enforcement"]:
        try:
            present = _file(root, row["path"]).is_file()
        except MotionPolicyError:
            present = False
        if not present:
            _violation(out, "enforcement-missing", None, row["path"], "the policy names an enforcement point that is not in the tree")
    out.sort(key=lambda row: (row["code"], row["registry"] or "", row["id"] or "", row["detail"]))
    return policy, items, out, scanned


def validate(root=ROOT, policy=None):
    """Every violation of the policy in a tree; an empty list means the tree complies.

    Raises `MotionPolicyError` only when the policy itself cannot be loaded.
    """
    return _survey(root, policy)[2]


def report(root=ROOT):
    """Counts per class and per registry, the legacy ids, the violations and `ok`. Never raises."""
    result = {"schema_version": 1, "policy": POLICY, "policy_version": None, "policy_sha256": None, "effective_from": None,
              "ok": False, "classes": {name: 0 for name in CLASSES}, "unclassified": 0, "registries": {},
              "legacy_unclassified_ids": {}, "sources_scanned": {}, "violations": [],
              "boundary": "Record and text checks only: no browser is run and a stated meaning is not judged for truth or quality."}
    try:
        policy, items, violations, scanned = _survey(root, None)
        result["policy_sha256"] = hashlib.sha256(_read(root, POLICY)).hexdigest()
    except (MotionPolicyError, OSError) as error:
        result["violations"] = [{"code": "policy-invalid", "registry": None, "id": None, "detail": str(error)}]
        return result
    result.update(policy_version=policy["policy_version"], effective_from=policy["effective_from"], sources_scanned=scanned, violations=violations)
    for name in REGISTRIES:
        rows = [item for item in items if item["registry"] == name]
        counts = {"total": len(rows)}
        for cls in CLASSES:
            number = sum(item["class"] == cls for item in rows)
            if number:
                counts[cls] = number
        unclassified = sum(item["class"] is None for item in rows)
        if unclassified:
            counts["unclassified"] = unclassified
        recorded = len(policy["registries"][name].get("withdrawn_ids", ()))
        if recorded:
            counts["withdrawn"] = recorded
        result["registries"][name] = counts
        if "legacy_ids" in policy["registries"][name]:
            result["legacy_unclassified_ids"][name] = sorted(item["id"] for item in rows if item["class"] == "legacy-unclassified")
    for cls in CLASSES:
        result["classes"][cls] = sum(counts.get(cls, 0) for counts in result["registries"].values())
    result["unclassified"] = sum(counts.get("unclassified", 0) for counts in result["registries"].values())
    result["ok"] = not violations
    return result


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = pathlib.Path(arguments[0]) if arguments else ROOT
    result = report(root)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
