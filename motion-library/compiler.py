"""Compile portable motion specifications into dependency-free CSS."""

import json
import pathlib
import re

SAFE_ID = re.compile(r"[a-z][a-z0-9-]{1,63}")
SAFE_EASING = {"linear", "ease", "ease-in", "ease-out", "ease-in-out"}
SAFE_PROPERTIES = {"opacity", "transform", "filter", "color", "background-color"}


def load_spec(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def validate(spec):
    if spec.get("schema_version") != 1:
        raise ValueError("Unsupported schema version")
    if not SAFE_ID.fullmatch(spec.get("id", "")):
        raise ValueError("Invalid motion id")
    if not isinstance(spec.get("duration_ms"), int) or not 0 < spec["duration_ms"] <= 10000:
        raise ValueError("duration_ms must be an integer from 1 to 10000")
    if spec.get("easing") not in SAFE_EASING:
        raise ValueError("Unsupported easing")
    frames = spec.get("keyframes")
    if not isinstance(frames, list) or len(frames) < 2:
        raise ValueError("At least two keyframes are required")
    offsets = []
    for frame in frames:
        offset = frame.get("offset")
        if not isinstance(offset, (int, float)) or not 0 <= offset <= 1:
            raise ValueError("Keyframe offsets must be between 0 and 1")
        offsets.append(offset)
        properties = set(frame) - {"offset"}
        if not properties or not properties <= SAFE_PROPERTIES:
            raise ValueError("Unsupported or empty keyframe properties")
    if offsets != sorted(offsets) or offsets[0] != 0 or offsets[-1] != 1:
        raise ValueError("Keyframes must be ordered from offset 0 to 1")
    reduced = spec.get("reduced_motion")
    if not isinstance(reduced, dict) or not reduced or not set(reduced) <= SAFE_PROPERTIES:
        raise ValueError("A safe reduced_motion state is required")
    return spec


def _declaration(name, value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Property values must be strings or numbers")
    text = str(value)
    if any(token in text for token in (";", "{", "}")):
        raise ValueError("Unsafe CSS value")
    return f"{name}: {text};"


def compile_css(spec):
    validate(spec)
    motion_id = spec["id"]
    lines = [f"@keyframes hub-{motion_id} {{"]
    for frame in spec["keyframes"]:
        declarations = " ".join(
            _declaration(name, value) for name, value in frame.items() if name != "offset"
        )
        lines.append(f"  {frame['offset'] * 100:g}% {{ {declarations} }}")
    lines.extend([
        "}",
        f".hub-motion-{motion_id} {{",
        f"  animation: hub-{motion_id} {spec['duration_ms']}ms {spec['easing']} both;",
        "}",
        "@media (prefers-reduced-motion: reduce) {",
        f"  .hub-motion-{motion_id} {{",
        "    animation: none;",
    ])
    lines.extend(
        f"    {_declaration(name, value)}" for name, value in spec["reduced_motion"].items()
    )
    lines.extend(["  }", "}"])
    return "\n".join(lines) + "\n"
