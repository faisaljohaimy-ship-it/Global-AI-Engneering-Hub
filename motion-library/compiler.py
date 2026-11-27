"""Compile portable motion specifications into dependency-free CSS."""

import json
import math
import pathlib
import re

SAFE_ID = re.compile(r"[a-z][a-z0-9-]{1,63}")
SAFE_EASING = {"linear", "ease", "ease-in", "ease-out", "ease-in-out"}
SAFE_PROPERTIES = {"opacity", "transform", "filter", "color", "background-color"}
TRANSFORM_VALUE = re.compile(
    r"(?:none|(?:(?:translate[XYZ]?\(-?\d+(?:\.\d+)?(?:px|%|rem|em)?\)|"
    r"scale[XYZ]?\(\d+(?:\.\d+)?\)|rotate[XYZ]?\(-?\d+(?:\.\d+)?deg\))\s*)+)"
)
FILTER_VALUE = re.compile(
    r"(?:none|(?:(?:blur\(\d+(?:\.\d+)?px\)|"
    r"(?:brightness|contrast|opacity|saturate)\(\d+(?:\.\d+)?(?:%?)\))\s*)+)"
)
COLOR_VALUE = re.compile(
    r"(?:transparent|#[0-9a-fA-F]{3,8}|rgba?\([\d.,%\s]+\)|hsla?\([\d.,%\s]+\))"
)


def load_spec(path):
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        pathlib.Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"Invalid JSON number: {value}")
        ),
    )


def validate(spec):
    if spec.get("schema_version") != 1:
        raise ValueError("Unsupported schema version")
    if not SAFE_ID.fullmatch(spec.get("id", "")):
        raise ValueError("Invalid motion id")
    if (
        isinstance(spec.get("duration_ms"), bool)
        or not isinstance(spec.get("duration_ms"), int)
        or not 0 < spec["duration_ms"] <= 10000
    ):
        raise ValueError("duration_ms must be an integer from 1 to 10000")
    if spec.get("easing") not in SAFE_EASING:
        raise ValueError("Unsupported easing")
    frames = spec.get("keyframes")
    if not isinstance(frames, list) or not 2 <= len(frames) <= 64:
        raise ValueError("Two to 64 keyframes are required")
    offsets = []
    for frame in frames:
        offset = frame.get("offset")
        if (
            isinstance(offset, bool)
            or not isinstance(offset, (int, float))
            or not math.isfinite(offset)
            or not 0 <= offset <= 1
        ):
            raise ValueError("Keyframe offsets must be between 0 and 1")
        offsets.append(offset)
        properties = set(frame) - {"offset"}
        if not properties or len(properties) > 5 or not properties <= SAFE_PROPERTIES:
            raise ValueError("Unsupported or empty keyframe properties")
        for name in properties:
            _declaration(name, frame[name])
    if offsets != sorted(offsets) or offsets[0] != 0 or offsets[-1] != 1:
        raise ValueError("Keyframes must be ordered from offset 0 to 1")
    reduced = spec.get("reduced_motion")
    if not isinstance(reduced, dict) or not reduced or not set(reduced) <= SAFE_PROPERTIES:
        raise ValueError("A safe reduced_motion state is required")
    for name, value in reduced.items():
        _declaration(name, value)
    return spec


def _declaration(name, value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Property values must be strings or numbers")
    text = str(value).strip()
    if any(token in text.casefold() for token in (";", "{", "}", "url(", "var(", "@", "\\")):
        raise ValueError("Unsafe CSS value")
    if any(ord(character) < 32 for character in text):
        raise ValueError("Control characters are not allowed")
    if name == "opacity":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError("Opacity must be a number from 0 to 1")
    elif name == "transform" and not TRANSFORM_VALUE.fullmatch(text):
        raise ValueError("Unsupported transform value")
    elif name == "filter" and not FILTER_VALUE.fullmatch(text):
        raise ValueError("Unsupported filter value")
    elif name in {"color", "background-color"} and not COLOR_VALUE.fullmatch(text):
        raise ValueError("Unsupported color value")
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
