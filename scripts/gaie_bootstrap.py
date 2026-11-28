#!/usr/bin/env python3
"""Install, verify or remove the GAIE skills for Claude Code. Dry-run by default.

`--scope user` targets ~/.claude (persists on a workstation; cloud sessions start
from a fresh clone, so commit a project install or use the hub pack there).
`--scope project --target DIR` targets DIR/.claude. Only files recorded in the
install manifest are ever updated or removed; any other existing file, a locally
edited file, or a symlink is preserved and reported. The manifest sits in the
target directory and is trusted as that directory's owner's record: it is limited
to the paths GAIE installs, but whoever can edit it can mark those paths as ours. Copying files does not prove
a host discovered or invoked a skill. SPDX-License-Identifier: MIT.
"""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ("gaie-master-router", "gaie-build", "gaie-upgrade", "gaie-audit", "gaie-cinematic", "gaie-release")
ENGINE = {"engineering_os/gaie_router.py": "gaie_router.py", "engineering_os/gaie_memory.py": "gaie_memory.py",
          "engineering_os/workspace_policy.py": "workspace_policy.py",
          "engineering_os/gaie_inventory.py": "gaie_inventory.py", "governance/policies/gaie-routes.json": "gaie-routes.json",
          "projects/registry.json": "projects.json", "projects/aliases.json": "aliases.json"}
MANIFEST = "gaie-install.json"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def plan(hub_checkout=False):
    """Destination (relative to .claude) -> hub source path."""
    files = {f"skills/{name}/SKILL.md": f"skills/{name}/SKILL.md" for name in SKILLS}
    files["agents/gaie-verifier.md"] = "agents/gaie-verifier.md"
    if not hub_checkout:  # a hub checkout already has the engine and prompts at its root
        files["skills/gaie-build/MASTER_BUILD.md"] = "prompts/MASTER_BUILD.md"
        files["skills/gaie-upgrade/MASTER_UPGRADE.md"] = "prompts/MASTER_UPGRADE.md"
        files.update({f"skills/gaie-master-router/engine/{name}": source for source, name in ENGINE.items()})
    return files


def base(scope, target):
    if scope == "user":
        return pathlib.Path.home() / ".claude", False
    if not target:
        raise ValueError("--target is required with --scope project")
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
    for relative, source in sorted(plan(hub_checkout).items()):
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
