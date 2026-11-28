#!/usr/bin/env python3
"""Install, verify or remove portable GAIE skills in independent Codex directories.

The gaie-factory pack controls the file list. Both hosts use the same verified
MASTER bytes and portable tools. Codex receives host-specific entry instructions
plus the original skill as reference. No user config, MCP credentials, Git state,
or native permissions are changed. Install and uninstall default to a dry run.
The Hub's tracked projection has its own read-only bootstrap check.
SPDX-License-Identifier: MIT.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
import pathlib
import stat
import sys
from uuid import uuid4

if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engineering_os import master_docs
from scripts import gaie_bootstrap

ROOT = gaie_bootstrap.ROOT
ENGINE = gaie_bootstrap.ENGINE_DIR
MANIFEST = "gaie-codex-install.json"
LIMIT = 1024 * 1024
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
PROTECTED_AUDIT = (
    "Use the governed master-audit result or a host with independently enforced "
    "read-only tools and approved path scope. Stop and report the blocker if "
    "that boundary is unavailable. Do not run tests, write files or memory, "
    "or issue a checkpoint during an audit. Codex skill metadata grants no permissions."
)


def _source(relative):
    if not isinstance(relative, str) or relative.startswith("/") or any(
        part in {"", ".", ".."} or "\\" in part for part in relative.split("/")
    ):
        raise ValueError("unsafe source path")
    state, detail, content = master_docs._read(ROOT, relative, LIMIT)
    if state != "present":
        raise ValueError(f"source refused: {detail}")
    return content


def _skill(name, source, documents):
    parts = source.decode("utf-8").split("\n---\n", 1)
    if len(parts) != 2 or not parts[0].startswith("---\n"):
        raise ValueError(f"missing skill metadata for {name}")
    metadata = parts[0].splitlines()[1:]
    declared_names = [line[6:].strip() for line in metadata if line.startswith("name: ")]
    descriptions = [line[13:].strip() for line in metadata if line.startswith("description: ")]
    if declared_names != [name] or len(descriptions) != 1 or not descriptions[0]:
        raise ValueError(f"invalid skill metadata for {name}")

    engine = "../gaie-master-router/engine/"
    instructions = [
        "Read the [shared instructions](REFERENCE.md). Its Claude-specific",
        "agent, plugin and directory conventions describe the other host. In Codex,",
        "resolve the paths below against the installed skill directory from discovery.",
        "A route is an offline plan. Verify project and host grants before any execution.",
        "",
        f"Canonical skill SHA-256: `{gaie_bootstrap.sha(source)}`.",
    ]
    if name == "gaie-audit":
        instructions += ["", PROTECTED_AUDIT]
    else:
        instructions += [
            "",
            "For routing use `python3 -B <router> route <owner-command>`, passing the exact",
            f"owner command as one argument. The router path is `{engine}gaie_router.py`.",
        ]
    if name in {"gaie-build", "gaie-upgrade", "gaie-cinematic"}:
        document = "MASTER_BUILD" if name == "gaie-build" else "MASTER_UPGRADE"
        instructions += [
            "",
            f"Read the pinned MASTER document with `python3 -B <loader> show {document}`.",
            f"The loader is `{engine}master_docs.py`. Stop if it reports drift.",
            f"The canonical document version is `{documents[document]['version']}`.",
            "For team policy use `agent_team.py` beside the loader. Assign",
            "roles under the actual Codex concurrency and independent review limits.",
        ]
    if name == "gaie-cinematic":
        instructions += [
            "",
            f"Read the central policy at `{engine}motion-purpose.json`. Use only reviewed",
            "motions whose purpose and runtime evidence meet that policy.",
        ]
    header = "---\nname: " + name + "\ndescription: " + json.dumps(descriptions[0], ensure_ascii=False) + "\n---\n"
    return (header + "\n".join(instructions) + "\n").encode("utf-8")


def plan():
    """Return the planned bytes, keyed by paths relative to .agents."""
    master = master_docs.verify(ROOT)
    if not master["ok"]:
        raise ValueError("canonical MASTER prompt verification failed")
    manifest = master_docs.load_manifest(ROOT)
    documents = manifest["documents"]
    files = {}
    for relative, source in gaie_bootstrap.plan().items():
        if relative.startswith("agents/"):
            continue  # Codex roles come from the shared registry, not Claude's agent frontmatter.
        content = _source(source)
        if relative.endswith("/SKILL.md"):
            name = pathlib.PurePosixPath(relative).parent.name
            files[relative] = _skill(name, content, documents)
            files[relative.replace("/SKILL.md", "/REFERENCE.md")] = content
        else:
            files[relative] = content
    files[ENGINE + "master_docs.py"] = _source(manifest["implementation"])
    files[ENGINE + "master-prompts.json"] = _source(master["manifest"])
    files[ENGINE + "motion-purpose.json"] = _source("governance/policies/motion-purpose.json")
    for record in documents.values():
        files[record["installed_as"]["claude"]] = _source(record["path"])
    return files


def base(scope, target):
    if scope == "user" and target is None:
        root = pathlib.Path.home()
    elif scope == "project" and target:
        root = pathlib.Path(os.path.abspath(target))
    else:
        raise ValueError("--target is required only for project scope")
    if root != root.resolve() or not root.is_dir() or root.stat().st_uid != os.geteuid():
        raise ValueError("target must be an existing canonical directory owned by the operator")
    if root == ROOT or all((root / marker).is_file() for marker in (
        "catalog/packs.json", "engineering_os/master_docs.py", "scripts/gaie_codex_bootstrap.py",
    )):
        raise ValueError("Hub projection is tracked; use python3 scripts/gaie_codex_bootstrap.py check")
    return root / ".agents"


@contextmanager
def parent_at(root_fd, relative, *, create=False):
    parts = relative.split("/")
    if any(part in {"", ".", ".."} or "\\" in part for part in parts):
        raise ValueError("unsafe install path")
    descriptor = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, DIR_FLAGS, dir_fd=descriptor)
            info = os.fstat(child)
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                os.close(child)
                raise ValueError("installation subdirectory must not be writable by another user")
            os.close(descriptor)
            descriptor = child
        yield descriptor, parts[-1]
    finally:
        os.close(descriptor)


def _read_at(root_fd, relative):
    if root_fd is None:
        return None
    try:
        with parent_at(root_fd, relative) as (directory, name):
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT
                    or info.st_uid != os.geteuid() or info.st_mode & 0o022):
                raise ValueError(f"unsafe or oversized file: {relative}")
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if not os.path.samestat(info, opened) or opened.st_nlink != 1:
                    raise ValueError(f"file changed before read: {relative}")
                content = stream.read(LIMIT + 1)
            if len(content) > LIMIT:
                raise ValueError(f"oversized file: {relative}")
            return content
    except FileNotFoundError:
        return None


def _write_at(root_fd, relative, content, before):
    if _read_at(root_fd, relative) != before:
        raise ValueError(f"file was modified during installation: {relative}")
    with parent_at(root_fd, relative, create=True) as (directory, name):
        temp = f".gaie-{uuid4().hex}.tmp"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
            if before is None:
                os.link(temp, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            else:
                os.replace(temp, name, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temp, dir_fd=directory)
            except FileNotFoundError:
                pass


def _read_manifest(raw, desired):
    if raw is None:
        return {}
    data = json.loads(raw, object_pairs_hook=master_docs._pairs)
    if not isinstance(data, dict) or data.keys() != {"schema_version", "files"} or data["schema_version"] != 1:
        raise ValueError("invalid Codex installation manifest")
    files = data["files"]
    if not isinstance(files, dict) or any(path not in desired or not isinstance(digest, str)
                                          or not master_docs.DIGEST.fullmatch(digest)
                                          for path, digest in files.items()):
        raise ValueError("installation manifest contains an unmanaged path or invalid digest")
    return files


def _operation(root_fd, desired, command, write):
    raw = _read_at(root_fd, MANIFEST)
    owned = _read_manifest(raw, desired)
    paths = sorted(owned if command == "uninstall" else desired,
                   key=lambda path: (command == "install" and path.endswith("/SKILL.md"), path))
    actual = {path: _read_at(root_fd, path) for path in paths}
    result = {}
    sha = gaie_bootstrap.sha
    if command == "install":
        conflicts = {
            path for path, present in actual.items()
            if present is not None and present != desired[path] and owned.get(path) != sha(present)
        }
        if conflicts:
            return {
                path: "preserved: unowned or locally modified" if path in conflicts else "blocked: installation conflict"
                for path in paths
            }
    for path, present in actual.items():
        matches = present is not None and owned.get(path) == sha(present)
        if command == "verify":
            result[path] = "missing" if present is None else "current" if present == desired[path] else "outdated" if matches else "modified"
        elif command == "uninstall":
            if present is None:
                result[path] = "already absent"
            elif not matches:
                result[path] = "preserved: locally modified"
                continue
            else:
                result[path] = "removed" if write else "would remove"
                if write:
                    if _read_at(root_fd, path) != present:
                        raise ValueError(f"file was modified during uninstall: {path}")
                    with parent_at(root_fd, path) as (directory, name):
                        os.unlink(name, dir_fd=directory)
            if write:
                owned.pop(path, None)
        elif present == desired[path]:
            result[path] = "unchanged"
        else:
            result[path] = ("created" if write else "would create") if present is None else ("updated" if write else "would update")
            if write:
                _write_at(root_fd, path, desired[path], present)
                owned[path] = sha(desired[path])
    if write and owned:
        data = (json.dumps({"schema_version": 1, "files": owned}, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if raw != data:
            _write_at(root_fd, MANIFEST, data, raw)
    elif write and raw is not None:
        os.unlink(MANIFEST, dir_fd=root_fd)
    return result


def apply(directory, command, write=False):
    """Apply only to one operator-owned .agents directory. Read-only commands leave it absent."""
    if command not in {"install", "verify", "uninstall"} or command == "verify" and write:
        raise ValueError("unsupported installation operation")
    directory = pathlib.Path(directory)
    if directory != base("project", directory.parent):
        raise ValueError("install directory must be a canonical .agents directory")
    desired = plan()
    if write and command == "install":
        directory.mkdir(mode=0o700, exist_ok=True)
    try:
        fd = os.open(directory, DIR_FLAGS)
    except FileNotFoundError:
        return _operation(None, desired, command, False)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError("installation directory must not be writable by another user")
        fcntl.flock(fd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        return _operation(fd, desired, command, write)
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("install", "verify", "uninstall"))
    parser.add_argument("--scope", required=True, choices=("project", "user"))
    parser.add_argument("--target")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        directory = base(args.scope, args.target)
        files = apply(directory, args.command, args.apply)
    except (KeyError, ValueError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 1
    good = {"unchanged", "current", "created", "updated", "would create", "would update", "removed",
            "would remove", "already absent"}
    ok = all(state in good for state in files.values())
    print(json.dumps({"command": args.command, "directory": str(directory), "applied": args.apply, "ok": ok,
                      "files": files, "scope": "installation bytes only; Codex host discovery is measured separately"}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
