#!/usr/bin/env python3
"""Deterministic damped-spring sampling for motion specifications. Standard library only.

A spring cannot be written as one CSS easing keyword, so its curve is sampled into
evenly spaced keyframes played with linear easing. The committed specifications are
this module's output; tests regenerate them and fail on any hand edit.
"""

import argparse
import json
import math
import pathlib

SPECS = pathlib.Path(__file__).resolve().parent / "specs"


def spring(seconds, stiffness, damping, mass=1.0):
    """Unit step response of a damped spring: 0 at release, settling at 1."""
    natural = math.sqrt(stiffness / mass)
    ratio = damping / (2 * math.sqrt(stiffness * mass))
    if ratio < 1:
        damped = natural * math.sqrt(1 - ratio * ratio)
        decay = math.exp(-ratio * natural * seconds)
        return 1 - decay * (math.cos(damped * seconds) + ratio * natural / damped * math.sin(damped * seconds))
    if ratio == 1:
        return 1 - math.exp(-natural * seconds) * (1 + natural * seconds)
    spread = natural * math.sqrt(ratio * ratio - 1)
    fast, slow = -ratio * natural - spread, -ratio * natural + spread
    return 1 - (slow * math.exp(fast * seconds) - fast * math.exp(slow * seconds)) / (slow - fast)


def samples(duration_ms, stiffness, damping, mass=1.0, steps=20):
    """(offset, progress) pairs; the last sample is exactly 1 so the motion ends at rest."""
    rows = []
    for index in range(steps + 1):
        offset = index / steps
        value = 1.0 if index == steps else spring(offset * duration_ms / 1000, stiffness, damping, mass)
        rows.append((round(offset, 4), round(value, 4)))
    return rows


def number(value):
    return f"{round(value, 3):g}"


def spring_card():
    frames = [
        {"offset": offset, "opacity": round(min(1.0, offset * 5), 3), "transform": f"scale({number(0.9 + 0.1 * value)})"}
        for offset, value in samples(700, 180, 12)
    ]
    return {
        "schema_version": 1, "id": "ui-spring-card", "name": "Spring card", "duration_ms": 700, "easing": "linear",
        "spring": {"stiffness": 180, "damping": 12, "mass": 1, "steps": 20},
        "keyframes": frames, "reduced_motion": {"opacity": 1, "transform": "none"},
    }


def elastic_orb_bounce():
    frames = [
        {"offset": offset, "transform": f"translateY({number(-64 * (1 - value))}px)"}
        for offset, value in samples(900, 220, 9, steps=24)
    ]
    return {
        "schema_version": 1, "id": "legacy-4", "name": "Elastic Orb Bounce", "duration_ms": 900, "easing": "linear",
        "spring": {"stiffness": 220, "damping": 9, "mass": 1, "steps": 24},
        "keyframes": frames, "reduced_motion": {"transform": "none"},
    }


GENERATED = {"ui-spring-card.json": spring_card, "legacy-4.json": elastic_orb_bounce}


def dump(spec):
    """Stable layout: one top-level key per line and one keyframe per line."""
    lines = ["{"]
    keys = list(spec)
    for key in keys:
        comma = "" if key == keys[-1] else ","
        if key == "keyframes":
            lines.append('  "keyframes": [')
            rows = [json.dumps(frame, ensure_ascii=False) for frame in spec[key]]
            lines.extend(f"    {row}{'' if row is rows[-1] else ','}" for row in rows)
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(spec[key], ensure_ascii=False)}{comma}")
    return "\n".join(lines + ["}"]) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite the generated specifications")
    args = parser.parse_args()
    stale = []
    for name, build in GENERATED.items():
        text, path = dump(build()), SPECS / name
        if args.write:
            path.write_text(text, encoding="utf-8")
        elif not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(name)
    if stale:
        raise SystemExit("Stale generated specifications: " + ", ".join(stale))


if __name__ == "__main__":
    main()
