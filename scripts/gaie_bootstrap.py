#!/usr/bin/env python3
"""Install, verify or remove the GAIE skills for Claude Code. Dry-run by default.

`--scope user` targets ~/.claude (persists on a workstation; cloud sessions start
from a fresh clone, so commit a project install or use the hub pack there).
`--scope project --target DIR` targets DIR/.claude; a symlinked DIR is refused. Only
files recorded in the install manifest are ever updated or removed; any other existing
file, a locally edited file, or a symlink is preserved and reported. The manifest sits
in the target directory and is trusted as that directory's owner's record: it is limited
to the paths GAIE installs, but whoever can edit it can mark those paths as ours. Copying files does not prove
a host discovered or invoked a skill.

What is installed is data, not code: the `gaie-factory` pack in catalog/packs.json is
the one list. Its skills go to skills/<name>/SKILL.md, a `.claude/agents/<name>.md`
destination goes to agents/<name>.md, a MASTER prompt goes beside the skill that reads
it, and every other `.engineering/gaie/<name>` file goes to
skills/gaie-master-router/engine/<name>, so that directory mirrors the registered
project's .engineering/gaie/. Shipping one more file is one line in that pack, e.g.
"engineering_os/agent_team.py": ".engineering/gaie/agent_team.py" or
"agents/gaie-specialist.md": ".claude/agents/gaie-specialist.md" (see
docs/specs/gaie-20-layers/INSTALL.md). SPDX-License-Identifier: MIT.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKS, PACK = "catalog/packs.json", "gaie-factory"
VENDOR, AGENTS, ENGINE_DIR = ".engineering/gaie/", ".claude/agents/", "skills/gaie-master-router/engine/"
PROMPTS = {"MASTER_BUILD.md": "gaie-build", "MASTER_UPGRADE.md": "gaie-upgrade"}  # prompt -> the skill it sits beside
MANIFEST = "gaie-install.json"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_SKILL = re.compile(r"gaie-[a-z0-9]+(?:-[a-z0-9]+)*")
# Where each install mode puts what the gaie-* skills name; the skills name these exact strings.
# ${CLAUDE_SKILL_DIR} is the directory of the SKILL.md naming the path (Claude Code fills it in);
# other paths are relative to the session's project directory (the hub, or the registered project).
LOCATIONS = {
    "bootstrap": {"router": "${CLAUDE_SKILL_DIR}/engine/gaie_router.py", "build": "${CLAUDE_SKILL_DIR}/MASTER_BUILD.md",
                  "upgrade": "${CLAUDE_SKILL_DIR}/MASTER_UPGRADE.md",
                  "inventory": "${CLAUDE_SKILL_DIR}/../gaie-master-router/engine/gaie_inventory.py"},
    "plugin": {"router": "${CLAUDE_SKILL_DIR}/../../hub.py", "build": "${CLAUDE_SKILL_DIR}/../../prompts/MASTER_BUILD.md",
               "upgrade": "${CLAUDE_SKILL_DIR}/../../prompts/MASTER_UPGRADE.md",
               "inventory": "${CLAUDE_SKILL_DIR}/../../hub.py"},
    "hub-checkout": {"router": "hub.py", "build": "prompts/MASTER_BUILD.md", "upgrade": "prompts/MASTER_UPGRADE.md",
                     "inventory": "hub.py"},
    "pack": {"router": ".engineering/gaie/gaie_router.py", "build": ".engineering/gaie/MASTER_BUILD.md",
             "upgrade": ".engineering/gaie/MASTER_UPGRADE.md", "inventory": ".engineering/gaie/gaie_inventory.py"},
}
LOCATION_SKILL = {"router": "gaie-master-router", "build": "gaie-build", "upgrade": "gaie-upgrade", "inventory": "gaie-upgrade"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pack():
    """The gaie-factory pack: the one list of what an install ships (also read by `hub.py register`)."""
    data = json.loads((ROOT / PACKS).read_text(encoding="utf-8"))["packs"][PACK]
    if not isinstance(data.get("skills"), list) or not isinstance(data.get("files"), dict) \
            or not all(isinstance(name, str) and _SKILL.fullmatch(name) for name in data["skills"]):
        raise ValueError(f"{PACKS}: {PACK} needs a skills list and a files map")
    return data


def _layout(source, destination):
    """Where a pack file goes under .claude: (relative path, needed in a hub checkout)."""
    if not isinstance(source, str) or not isinstance(destination, str):
        raise ValueError(f"{PACKS}: {PACK} files must map paths to paths")
    for prefix, name in ((AGENTS, destination[len(AGENTS):]), (VENDOR, destination[len(VENDOR):])):
        if destination.startswith(prefix) and _NAME.fullmatch(name):
            if prefix == AGENTS and name.endswith(".md"):
                return f"agents/{name}", True
            if prefix == VENDOR:
                return (f"skills/{PROMPTS[name]}/{name}" if name in PROMPTS else ENGINE_DIR + name), False
    raise ValueError(f"{PACKS}: {PACK} destination {destination!r} is neither {VENDOR}<file> nor {AGENTS}<name>.md")


def plan(hub_checkout=False):
    """Destination (relative to .claude) -> hub source path. A hub checkout already has the engine and prompts."""
    data = pack()
    files = {f"skills/{name}/SKILL.md": f"skills/{name}/SKILL.md" for name in data["skills"]}
    for source, destination in sorted(data["files"].items()):
        relative, everywhere = _layout(source, destination)
        if relative in files:
            raise ValueError(f"{PACKS}: {PACK} installs {relative} twice")
        if everywhere or not hub_checkout:
            files[relative] = source
    return files


def base(scope, target):
    if scope == "user":
        return pathlib.Path.home() / ".claude", False
    if not target:
        raise ValueError("--target is required with --scope project")
    if pathlib.Path(target).is_symlink():
        raise ValueError("symlinked target directory refused")
    root = pathlib.Path(target).resolve()
    if not root.is_dir():
        raise ValueError("existing project directory required")
    return root / ".claude", root == ROOT


def _safe(directory, relative):
    parts = pathlib.PurePosixPath(relative).parts
    if not isinstance(relative, str) or not parts or relative.startswith("/") or "\\" in relative or ".." in parts:
        raise ValueError("unsafe install path")
    path = directory
    if directory.is_symlink():
        raise ValueError("symlinked .claude directory refused")
    for part in pathlib.PurePosixPath(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"symlink refused: {relative}")
    return path


def _manifest(directory):
    path = directory / MANIFEST
    if path.is_symlink():
        raise ValueError("symlinked install manifest refused")
    if not path.is_file():
        return {"schema_version": 1, "files": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("files"), dict):
        raise ValueError("invalid install manifest")
    allowed = set(plan(False))
    for relative, digest in data["files"].items():
        if relative not in allowed or not isinstance(digest, str):
            raise ValueError("install manifest lists a path GAIE never installs; refusing to act on it")
    return data


def _replace(path, data):
    """Write through a fresh exclusive temporary file; never through a symlink."""
    temporary = path.with_name(path.name + ".gaie-tmp")
    if temporary.is_symlink() or temporary.exists():
        raise ValueError(f"stale or symlinked temporary file: {temporary.name}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    temporary.replace(path)


def _revision():
    result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _write(directory, manifest):
    manifest["hub_revision"] = None if directory.parent == ROOT else _revision()
    directory.mkdir(parents=True, exist_ok=True)
    _replace(_safe(directory, MANIFEST), (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def install(directory, hub_checkout, apply):
    manifest, result = _manifest(directory), {}
    files = plan(hub_checkout)
    for relative in files:  # refuse a symlinked path before writing anything, not after a partial install
        _safe(directory, relative)
    for relative, source in sorted(files.items()):
        data = (ROOT / source).read_bytes()
        path = _safe(directory, relative)
        recorded = manifest["files"].get(relative)
        if path.exists():
            current = sha(path.read_bytes())
            if current == sha(data):
                result[relative] = "unchanged" if recorded == current else "unchanged: identical file was already present and stays yours"
                continue
            if recorded is None:
                result[relative] = "preserved: existing file was not installed by GAIE"
                continue
            if current != recorded:
                result[relative] = "preserved: locally modified since install"
                continue
        result[relative] = ("updated" if path.exists() else "created") if apply else ("would update" if path.exists() else "would create")
        if apply:
            path.parent.mkdir(parents=True, exist_ok=True)
            _replace(path, data)
            manifest["files"][relative] = sha(data)
    if apply:
        _write(directory, manifest)
    return result


def verify(directory, hub_checkout):
    manifest, result = _manifest(directory), {}
    for relative, source in sorted(plan(hub_checkout).items()):
        path = _safe(directory, relative)
        if not path.is_file():
            result[relative] = "missing"
        elif sha(path.read_bytes()) == sha((ROOT / source).read_bytes()):
            result[relative] = "current"
        elif manifest["files"].get(relative) == sha(path.read_bytes()):
            result[relative] = "outdated"
        else:
            result[relative] = "modified"
    return result


def _drop_bytecode(path):
    """Remove the interpreter's cache of one removed module (__pycache__/<stem>.<tag>.pyc), nothing else."""
    cache = path.parent / "__pycache__"
    if path.suffix != ".py" or cache.is_symlink() or not cache.is_dir():
        return
    pattern = re.compile(re.escape(path.stem) + r"\.[a-z0-9_-]+(?:\.opt-[12])?\.pyc")
    for compiled in cache.iterdir():
        if pattern.fullmatch(compiled.name) and compiled.is_file() and not compiled.is_symlink():
            compiled.unlink()
    if not any(cache.iterdir()):
        cache.rmdir()


def uninstall(directory, apply):
    manifest, result = _manifest(directory), {}
    for relative, recorded in sorted(manifest["files"].items()):
        path = _safe(directory, relative)
        if not path.is_file():
            result[relative] = "already absent"
        elif sha(path.read_bytes()) != recorded:
            result[relative] = "preserved: locally modified since install"
            continue
        else:
            result[relative] = "removed" if apply else "would remove"
            if apply:
                path.unlink()
                _drop_bytecode(path)
                for parent in path.parents:
                    if len(parent.relative_to(directory).parts) < 2 or any(parent.iterdir()):
                        break
                    parent.rmdir()
        if apply:
            manifest["files"].pop(relative)
    if apply:
        if manifest["files"]:
            _write(directory, manifest)
        elif (directory / MANIFEST).is_file():
            (directory / MANIFEST).unlink()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("install", "verify", "uninstall"))
    parser.add_argument("--scope", choices=("user", "project"), required=True)
    parser.add_argument("--target")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        directory, hub_checkout = base(args.scope, args.target)
        if args.command == "install":
            files = install(directory, hub_checkout, args.apply)
        elif args.command == "verify":
            files = verify(directory, hub_checkout)
        else:
            files = uninstall(directory, args.apply)
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 1
    ok = all(state.startswith("unchanged") or state in ("current", "created", "updated", "would create", "would update",
                       "removed", "would remove", "already absent") for state in files.values())
    print(json.dumps({"command": args.command, "directory": str(directory), "applied": args.apply or args.command == "verify",
                      "ok": ok, "files": files,
                      "note": "Files on disk are not proof of host discovery; confirm in a new session."}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
