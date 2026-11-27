"""Unified project registration and link verification for the engineering hub.

Python standard library and git only. A project is linked when its manifest pins an
immutable hub commit and every declared capability file can be reproduced byte for
byte from that commit. A manifest on its own is a declaration, not evidence.
"""

import hashlib
import json
import pathlib
import re
import subprocess
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parent
HUB_URL = "https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub"
MANIFEST = ".engineering/capabilities.json"
MOTION_DIR = ".engineering/vendor/hub-motion"
SKILL_ROOTS = (".claude/skills", ".agents/skills")
SHA = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"[a-f0-9]{64}")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
REPOSITORY = re.compile(r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
CANONICAL_KEYS = ("schema_version", "hub_url", "hub_revision", "project", "capabilities")


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def head():
    return _git("rev-parse", "HEAD").stdout.decode().strip()


def has_commit(revision):
    if not SHA.fullmatch(revision or ""):
        return False
    return _git("cat-file", "-e", revision + "^{commit}").returncode == 0


def on_main(revision):
    """True or False when main history is available, None when it cannot be proven."""
    for ref in ("refs/remotes/origin/main", "refs/heads/main"):
        if _git("rev-parse", "--verify", "--quiet", ref).returncode:
            continue
        if _git("merge-base", "--is-ancestor", revision, ref).returncode == 0:
            return True
        shallow = _git("rev-parse", "--is-shallow-repository").stdout.strip() == b"true"
        return None if shallow else False
    return None


def read(revision, path):
    result = _git("show", f"{revision}:{path}")
    if result.returncode:
        raise ValueError(f"{path} is not in the hub at {revision[:12]}")
    return result.stdout


def tree(revision, prefix):
    listing = _git("ls-tree", "-r", "--name-only", "-z", revision, "--", prefix).stdout
    return [path for path in listing.decode().split("\0") if path]


def _skill_files(revision, name):
    prefix = f"skills/{name}/"
    sources = tree(revision, prefix)
    if prefix + "SKILL.md" not in sources:
        raise ValueError(f"Skill {name} is not in the hub at {revision[:12]}")
    return [
        {"path": f"{root}/{name}/{source[len(prefix):]}", "source": source, "mode": "copy"}
        for source in sources
        for root in SKILL_ROOTS
    ]


def motion_specs(revision):
    """Map motion id to its specification path at a hub revision."""
    specs = {}
    for source in tree(revision, "motion-library/specs/"):
        if source.endswith(".json"):
            specs[json.loads(read(revision, source))["id"]] = source
    return specs


def _compiler(revision):
    module = types.ModuleType("hub_motion_compiler")
    source = read(revision, "motion-library/compiler.py")
    exec(compile(source, "motion-library/compiler.py", "exec"), module.__dict__)
    return module


def resolve(revision, capability_id):
    """Return the project files a capability provides, reproduced from one hub revision."""
    kind, _, name = str(capability_id).partition(":")
    if not NAME.fullmatch(name):
        raise ValueError(f"Invalid capability id: {capability_id}")
    if kind == "skill":
        files = _skill_files(revision, name)
    elif kind == "motion":
        source = motion_specs(revision).get(name)
        if source is None:
            raise ValueError(f"Motion {name} has no specification at {revision[:12]}")
        files = [
            {"path": f"{MOTION_DIR}/{name}.json", "source": source, "mode": "copy"},
            {"path": f"{MOTION_DIR}/{name}.css", "source": source, "mode": "css"},
        ]
    elif kind == "pack":
        pack = json.loads(read(revision, "catalog/packs.json"))["packs"].get(name)
        if pack is None:
            raise ValueError(f"Pack {name} is not in the hub at {revision[:12]}")
        files = [row for skill in pack.get("skills", []) for row in _skill_files(revision, skill)]
        files += [
            {"path": path, "source": source, "mode": "copy"}
            for source, path in sorted(pack.get("files", {}).items())
        ]
    else:
        raise ValueError(f"Unknown capability kind: {capability_id}")
    compiler = None
    for row in files:
        data = read(revision, row["source"])
        if row["mode"] == "css":
            compiler = compiler or _compiler(revision)
            data = compiler.compile_css(json.loads(data)).encode("utf-8")
        row["data"] = data
    return files


def _destination(target, relative):
    parts = pathlib.PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or ".." in parts or parts[0] == ".git":
        raise ValueError(f"Unsafe project path: {relative}")
    current = target
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Symlink refused: {relative}")
    return current


def validate_manifest(manifest):
    """Return a list of problems; an empty list means the manifest is well formed."""
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    errors = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not SHA.fullmatch(str(manifest.get("hub_revision") or "")):
        errors.append("hub_revision must be a full commit SHA")
    if manifest.get("hub_url", HUB_URL) != HUB_URL:
        errors.append("hub_url must be the shared hub")
    budget = manifest.get("budget_additional_sar")
    if isinstance(budget, bool) or budget != 0:
        errors.append("budget_additional_sar must be 0 without explicit approval")
    if manifest.get("production_runtime_dependency", False) is not False:
        errors.append("production_runtime_dependency must be false")
    project = manifest.get("project", {})
    if not isinstance(project, dict):
        errors.append("project must be an object")
    else:
        if "id" in project and not NAME.fullmatch(str(project["id"])):
            errors.append("project.id must be a lowercase slug")
        if "repository" in project and not REPOSITORY.fullmatch(str(project["repository"])):
            errors.append("project.repository must be a GitHub repository URL")
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list):
        return errors + ["capabilities must be a list"]
    seen = set()
    for capability in capabilities:
        if not isinstance(capability, dict) or not isinstance(capability.get("id"), str):
            errors.append("each capability needs an id")
            continue
        if capability["id"] in seen:
            errors.append(f"duplicate capability {capability['id']}")
        seen.add(capability["id"])
        files = capability.get("files")
        if not isinstance(files, list) or not files:
            errors.append(f"{capability['id']} needs a file list")
            continue
        for row in files:
            valid = (
                isinstance(row, dict)
                and isinstance(row.get("path"), str)
                and isinstance(row.get("source"), str)
                and row.get("mode") in ("copy", "css")
                and DIGEST.fullmatch(str(row.get("sha256")))
            )
            if not valid:
                errors.append(f"{capability['id']} has an invalid file entry")
    return errors


def load_manifest(target):
    path = pathlib.Path(target) / MANIFEST
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Symlink refused")
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def register(target, revision, project_id=None, repository=None, capabilities=(), apply=False, remove=()):
    """Install capabilities from one hub revision and record them in the manifest.

    Dry-run unless apply is set. Capabilities already declared are reinstalled from the
    new revision, so the same command re-pins a project. A project file the hub does not
    manage is never overwritten: identical content is adopted, different content stops.
    Removing a capability deletes only files that still match their recorded checksum.
    """
    if not has_commit(revision):
        raise ValueError("Full commit SHA from this hub required")
    target = pathlib.Path(target).resolve()
    if not target.is_dir():
        raise ValueError("Existing directory required")
    old = load_manifest(target) or {}
    if old:
        problems = validate_manifest(old)
        if problems:
            raise ValueError("Existing manifest is invalid: " + "; ".join(problems))
    managed = {row["path"] for item in old.get("capabilities", []) for row in item["files"]}
    wanted = list(dict.fromkeys([item["id"] for item in old.get("capabilities", [])] + list(capabilities)))
    removing = set(remove)
    if removing - set(wanted):
        raise ValueError("Cannot remove what is not registered: " + ", ".join(sorted(removing - set(wanted))))
    wanted = [capability_id for capability_id in wanted if capability_id not in removing]
    plan, contents, entries = {}, {}, []
    for capability_id in wanted:
        rows = []
        for row in resolve(revision, capability_id):
            destination = _destination(target, row["path"])
            digest = sha256(row["data"])
            if contents.setdefault(row["path"], row["data"]) != row["data"]:
                raise ValueError(f"Two capabilities provide different content for {row['path']}")
            if not destination.exists():
                plan[row["path"]] = "create"
            elif destination.is_file() and sha256(destination.read_bytes()) == digest:
                plan[row["path"]] = "unchanged"
            else:
                plan[row["path"]] = "update" if row["path"] in managed else "conflict"
            rows.append({"path": row["path"], "source": row["source"], "mode": row["mode"], "sha256": digest})
        entries.append({"id": capability_id, "files": rows})
    conflicts = sorted(path for path, state in plan.items() if state == "conflict")
    if conflicts:
        raise ValueError("Refusing to overwrite project files the hub does not manage: " + ", ".join(conflicts))
    # Files of a removed capability, and files a newer pin no longer provides, are deleted
    # only while they still match the checksum recorded when the hub installed them.
    for item in old.get("capabilities", []):
        for row in item["files"]:
            if row["path"] in plan:
                continue
            destination = _destination(target, row["path"])
            if not destination.is_file():
                plan[row["path"]] = "already absent"
            elif sha256(destination.read_bytes()) == row["sha256"]:
                plan[row["path"]] = "delete"
            else:
                plan[row["path"]] = "kept: edited in the project"
    project = dict(old.get("project") or {})
    if project_id:
        project["id"] = project_id
    if repository:
        project["repository"] = repository
    manifest = {"schema_version": 1, "hub_url": HUB_URL, "hub_revision": revision}
    if project:
        manifest["project"] = project
    manifest["capabilities"] = entries
    manifest.update({key: value for key, value in old.items() if key not in CANONICAL_KEYS})
    manifest.update(budget_additional_sar=0, production_runtime_dependency=False)
    problems = validate_manifest(manifest)
    if problems:
        raise ValueError("; ".join(problems))
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    manifest_path = _destination(target, MANIFEST)
    current = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else None
    plan[MANIFEST] = "unchanged" if current == text else ("update" if current else "create")
    if apply:
        for path, data in contents.items():
            if plan[path] in ("create", "update"):
                destination = _destination(target, path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        for path, state in plan.items():
            if state == "delete":
                destination = _destination(target, path)
                destination.unlink()
                for parent in list(destination.parents)[:2]:
                    if parent != target and not any(parent.iterdir()):
                        parent.rmdir()
        if plan[MANIFEST] != "unchanged":
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(text, encoding="utf-8")
    return {
        "applied": bool(apply),
        "hub_revision": revision,
        "capabilities": wanted,
        "files": plan,
    }


def verify(target, strict=False):
    """Check a project's link against the pinned hub revision.

    Normal mode fails on any integrity problem. Strict mode also requires at least one
    verified capability and a pin that is proven to be on the hub's main history.
    """
    target = pathlib.Path(target).resolve()
    checks, warnings = [], []
    report = {"ok": False, "level": "broken", "strict": bool(strict), "project": None, "hub_revision": None,
              "pin_on_main": None, "verified_files": 0, "checks": checks, "warnings": warnings}

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    try:
        manifest = load_manifest(target)
    except ValueError as error:
        check("manifest-readable", False, str(error))
        return report
    if not check("manifest-present", manifest is not None, MANIFEST):
        return report
    problems = validate_manifest(manifest)
    if not check("manifest-schema", not problems, "; ".join(problems)):
        return report
    revision = manifest["hub_revision"]
    report.update(project=manifest.get("project"), hub_revision=revision)
    if not check("pinned-revision-in-hub", has_commit(revision), revision):
        return report
    reviewed = report["pin_on_main"] = on_main(revision)
    if reviewed is None:
        warnings.append("main history is unavailable here; whether the pin is a merged revision was not checked")
    elif not reviewed:
        warnings.append("the pinned revision is not on the hub's main history; re-pin after it is merged")
    declared, verified = set(), 0
    for capability in manifest["capabilities"]:
        name = "capability " + capability["id"]
        try:
            expected = {row["path"]: row for row in resolve(revision, capability["id"])}
        except ValueError as error:
            check(name, False, str(error))
            continue
        listed = {row["path"] for row in capability["files"]}
        declared |= listed
        bad = sorted(set(expected) ^ listed)
        for row in capability["files"]:
            wanted = expected.get(row["path"])
            if wanted is None:
                continue
            try:
                destination = _destination(target, row["path"])
            except ValueError:
                bad.append(row["path"])
                continue
            actual = sha256(destination.read_bytes()) if destination.is_file() else None
            if actual == row["sha256"] == sha256(wanted["data"]):
                verified += 1
            else:
                bad.append(row["path"])
        detail = f"{len(listed) - len(set(bad) & listed)}/{len(listed)} files match the hub at the pin"
        check(name, not bad, detail + ("; mismatch: " + ", ".join(sorted(set(bad))) if bad else ""))
    undeclared = []
    for source in tree(revision, "skills/"):
        if source.endswith("/SKILL.md"):
            for root in SKILL_ROOTS:
                relative = f"{root}/{source.split('/')[1]}/SKILL.md"
                path = target / relative
                if relative not in declared and path.is_file():
                    same = sha256(path.read_bytes()) == sha256(read(revision, source))
                    undeclared.append(f"{relative} ({'identical to' if same else 'differs from'} the hub)")
    if undeclared:
        warnings.append("hub skills present but not declared in the manifest: " + ", ".join(undeclared))
    if not manifest["capabilities"]:
        warnings.append("no capability is declared: this manifest is a declaration, not evidence of a working link")
    intact = all(row["ok"] for row in checks)
    linked = intact and verified > 0
    report.update(
        verified_files=verified,
        level="verified" if linked else ("declared-only" if intact else "broken"),
        ok=intact and (not strict or (linked and reviewed is True)),
    )
    return report


def projects():
    """Validated public project registry. Private repositories are never listed here."""
    rows = json.loads((ROOT / "projects/registry.json").read_text(encoding="utf-8"))["projects"]
    return validate_projects(rows)


def validate_projects(rows):
    ids = [row.get("id") for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate project IDs")
    for row in rows:
        if not NAME.fullmatch(str(row.get("id") or "")):
            raise ValueError("Invalid project ID")
        if not REPOSITORY.fullmatch(str(row.get("repository") or "")):
            raise ValueError("Invalid project repository")
        if row.get("visibility") != "public":
            raise ValueError("Only public repositories may be listed in the public registry")
        if row.get("manifest") != MANIFEST or not NAME.fullmatch(str(row.get("default_branch") or "")):
            raise ValueError("Invalid project entry")
    return rows


def audit_projects():
    """Clone each registered public project and verify its link. Network access required."""
    results = []
    for row in projects():
        with tempfile.TemporaryDirectory() as workdir:
            clone = subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1", "--branch", row["default_branch"],
                 row["repository"], workdir + "/project"],
                capture_output=True,
            )
            if clone.returncode:
                results.append({"id": row["id"], "ok": False, "level": "unreachable", "verified_files": 0})
                continue
            report = verify(workdir + "/project")
            results.append({key: report[key] for key in ("ok", "level", "hub_revision", "pin_on_main", "verified_files")}
                           | {"id": row["id"], "warnings": report["warnings"]})
    return results
