"""Read the fixture's declared pins and its lock file (nothing is installed)."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read_requirements(path=HERE / "requirements.txt"):
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            pins[name.strip().lower()] = version.strip()
    return pins


def read_lock(path=HERE / "requirements.lock.json"):
    packages = json.loads(path.read_text(encoding="utf-8"))["packages"]
    return {name.lower(): entry["version"] for name, entry in packages.items()}


def lock_hashes(path=HERE / "requirements.lock.json"):
    packages = json.loads(path.read_text(encoding="utf-8"))["packages"]
    return {name.lower(): entry.get("sha256", "") for name, entry in packages.items()}
