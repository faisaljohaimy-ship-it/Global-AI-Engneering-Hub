import sys

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import json
import os
import pathlib
import re
import stat

import hublink
from engineering_os import control, gaie_inventory, gaie_router

ROOT = pathlib.Path(__file__).resolve().parent
HUB_URL = "https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub"
SHA_RE = re.compile(r"[a-f0-9]{40}")


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path):
    return json.loads(
        pathlib.Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_no_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"Invalid JSON number: {value}")
        ),
    )


def registry():
    rows = load_json(ROOT / "catalog/registry.json")
    if not isinstance(rows, list):
        raise ValueError("Catalog must be a list")
    ids = [item.get("id") for item in rows]
    if any(not isinstance(value, str) or not value for value in ids):
        raise ValueError("Catalog IDs must be non-empty strings")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate catalog IDs")
    for item in rows:
        if not item.get("source", "").startswith("https://github.com/"):
            raise ValueError("Invalid source")
        if item.get("status") not in {"discovered", "reviewed", "approved"}:
            raise ValueError("Invalid catalog status")
        if item["status"] == "approved" and (
            not SHA_RE.fullmatch(item.get("revision") or "")
            or any(
                item.get(key) != "approved"
                for key in ("license_review", "security_review", "commercial_review")
            )
        ):
            raise ValueError("Unreviewed approval")
    return rows


def motion_catalog():
    document = load_json(ROOT / "motion-library/MOTION_CATALOG.json")
    rows = document.get("entries")
    if document.get("schema_version") != 1 or not isinstance(rows, list):
        raise ValueError("Invalid motion catalog")
    ids = [item.get("id") for item in rows]
    if len(ids) != len(set(ids)) or any(not isinstance(value, str) for value in ids):
        raise ValueError("Invalid or duplicate motion IDs")
    return rows


def motion_components():
    path = ROOT / "motion-library/components.json"
    if not path.exists():
        return []
    document = load_json(path)
    rows = document.get("components")
    if document.get("schema_version") != 1 or not isinstance(rows, list):
        raise ValueError("Invalid motion component manifest")
    catalog_ids = {item["id"] for item in motion_catalog()}
    ids = [item.get("id") for item in rows]
    if len(ids) != len(set(ids)) or any(value not in catalog_ids for value in ids):
        raise ValueError("Motion components must map uniquely to the catalog")
    for item in rows:
        if item.get("implementation_status") != "implemented":
            raise ValueError("Invalid motion implementation status")
        if item.get("test_status") not in {"automated", "pending"}:
            raise ValueError("Invalid motion test status")
        if item.get("runtime_status") not in {
            "pending-browser",
            "browser-verified",
            "adapter-tested",
        }:
            raise ValueError("Invalid motion runtime status")
        if not isinstance(item.get("used_by"), list):
            raise ValueError("Invalid motion usage evidence")
    return rows


def integration_evidence():
    path = ROOT / "integrations/EVIDENCE.json"
    return load_json(path).get("programs", []) if path.exists() else []


def audit():
    rows = registry()
    motions = motion_catalog()
    components = motion_components()
    integrations = integration_evidence()
    catalog_implemented = {
        item["id"] for item in motions if item.get("status") == "implemented"
    }
    component_ids = {item["id"] for item in components}
    automated_components = {
        item["id"]
        for item in components
        if item.get("tested") is True or item.get("test_status") == "automated"
    }
    browser_verified = {
        item["id"] for item in motions if item.get("runtime_verified") is True
    }
    expansion=control.motions()['expansion']
    scoped=control.capabilities(state='TESTED')
    return {
        "catalog_entries": len(rows),
        "approved": sum(item["status"] == "approved" for item in rows),
        "local_skills": len(list((ROOT / "skills").glob("*/SKILL.md"))),
        "motions_indexed": len(motions),
        "motions_implemented": len(catalog_implemented | component_ids),
        "motions_tested": len(catalog_implemented | automated_components),
        "motions_runtime_verified": len(browser_verified),
        "motions_used": len(catalog_implemented | component_ids),
        "motion_lab_components": len(component_ids),
        "integrations_indexed": len(
            load_json(ROOT / "integrations/PROGRAMS.json").get("programs", [])
        ),
        "integrations_probed": len(integrations),
        "integrations_available": sum(
            item.get("result") == "success" for item in integrations
        ),
        "registered_public_projects": len(hublink.projects()),
        "scoped_tools_tested": len([r for r in scoped if r['kind']=='external-tool']),
        "motion_expansion": expansion,
        "motion_totals": {"indexed":len(motions)+expansion['indexed'],
                          "implemented":len(catalog_implemented | component_ids)+expansion['implemented'],
                          "tested":len(catalog_implemented | automated_components)+expansion['tested'],
                          "runtime_verified":len(browser_verified)+expansion['runtime_verified']},
    }


def recommend(query):
    needle = query.casefold()
    candidates = []
    for item in registry():
        if needle in json.dumps(item, ensure_ascii=False).casefold():
            candidates.append({"kind": "capability", **item})
    implemented = {item["id"]: item for item in motion_components()}
    for item in motion_catalog():
        if needle in json.dumps(item, ensure_ascii=False).casefold():
            candidates.append(
                {
                    "kind": "motion",
                    **item,
                    "implementation": implemented.get(item["id"]),
                }
            )
    for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        if needle in text.casefold():
            candidates.append(
                {"kind": "skill", "id": path.parent.name, "path": str(path.relative_to(ROOT))}
            )
    return candidates


def onboard(target, revision, apply=False):
    if not SHA_RE.fullmatch(revision) or not hublink.reviewed_commit(revision):
        raise ValueError("Full reviewed commit SHA on hub main required")
    target = pathlib.Path(target).resolve()
    if not target.is_dir():
        raise ValueError("Existing directory required")
    dest = target / ".engineering"
    if dest.is_symlink():
        raise ValueError("Symlink refused")
    files = {
        "capabilities.json": json.dumps(
            {
                "schema_version": 1,
                "hub_url": HUB_URL,
                "hub_revision": revision,
                "capabilities": [],
                "discovery_skill": "hub-capabilities",
                "budget_additional_sar": 0,
                "production_runtime_dependency": False,
            },
            indent=2,
        )
        + "\n",
        "README.md": (ROOT / "docs/ONBOARDING.md").read_text(encoding="utf-8"),
    }
    result = {}
    for name, data in files.items():
        path = dest / name
        if path.exists() or path.is_symlink():
            result[name] = "preserved"
            continue
        result[name] = "created" if apply else "would create"
        if apply:
            dest.mkdir(exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(data)
    skill_source = (ROOT / "skills/hub-capabilities/SKILL.md").read_text(encoding="utf-8")
    for relative in (
        pathlib.Path(".agents/skills/hub-capabilities/SKILL.md"),
        pathlib.Path(".claude/skills/hub-capabilities/SKILL.md"),
    ):
        path = target / relative
        key = relative.as_posix()
        if any(parent.is_symlink() for parent in path.parents if parent != target.parent):
            raise ValueError(f"Symlink parent refused: {key}")
        if path.exists() or path.is_symlink():
            result[key] = "preserved"
            continue
        result[key] = "created" if apply else "would create"
        if apply:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(skill_source)
    return result


def update_pin(target, revision, expected, apply=False):
    if not SHA_RE.fullmatch(revision) or not SHA_RE.fullmatch(expected):
        raise ValueError("Full reviewed current and target SHAs required")
    if not hublink.reviewed_commit(revision) or not hublink.reviewed_commit(expected):
        raise ValueError("Current and target revisions must be reviewed hub main commits")
    manifest = pathlib.Path(target).resolve() / ".engineering/capabilities.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("Existing non-symlink capability manifest required")
    data = load_json(manifest)
    if data.get("hub_revision") != expected:
        raise ValueError("Current revision does not match --expected")
    if data.get("budget_additional_sar") != 0:
        raise ValueError("Non-zero budget manifest refused")
    if data.get("production_runtime_dependency") is True:
        raise ValueError("Production runtime dependency manifest refused")
    if data.get("capabilities"):
        raise ValueError("Registered capabilities must be re-pinned with hub.py register")
    result = {"from": expected, "to": revision, "status": "would update"}
    if apply:
        data["hub_revision"] = revision
        temporary = manifest.with_suffix(".json.tmp")
        if temporary.exists() or temporary.is_symlink():
            raise ValueError("Temporary update path already exists")
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(data, indent=2) + "\n")
        temporary.replace(manifest)
        result["status"] = "updated"
    return result


def engine_table(rows):
    """Plain-text table of the control plane's engines: id, layer, actions, side effects."""
    header = ("ID", "LAYER", "ACTIONS", "SIDE EFFECTS")
    lines = [(row["id"], row["layer"], ", ".join(row["actions"]), ", ".join(row["side_effects"])) for row in rows]
    widths = [max(len(item[i]) for item in [header, *lines]) for i in range(3)]
    return "\n".join(
        "  ".join(cell.ljust(widths[i]) if i < 3 else cell for i, cell in enumerate(item)).rstrip()
        for item in [header, *lines]
    )


def invoke_command(args):
    """Governed engine invocation; exit 3 when the Security Governor denies, 1 on error."""
    from engineering_os import control_plane

    try:
        payload = json.loads(
            args.payload,
            object_pairs_hook=_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"Invalid JSON number: {value}")
            ),
        )
        grant = load_json(args.grant)
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "error", "error": f"invalid payload or grant: {error}"}, ensure_ascii=False))
        sys.exit(1)
    ctx = {"state_dir": str(pathlib.Path(args.state).absolute()), "host": args.host}
    if args.task:
        ctx["task_id"] = args.task
    try:
        return control_plane.invoke(args.engine, args.action, payload, grant=grant, ctx=ctx)
    except PermissionError as denial:  # governor.GovernorDenied: nothing ran
        print(json.dumps({"status": "denied", "reason": str(getattr(denial, "reason", denial))}, ensure_ascii=False))
        sys.exit(3)
    except control_plane.ControlPlaneError as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        sys.exit(1)


def workspace_run(args):
    """Launch one local work unit using the operator's private assignment file."""
    from engineering_os import governor, workspace_policy

    try:
        path = pathlib.Path(args.assignments).absolute()
        if path != path.resolve() or any((parent / ".git").exists() for parent in path.parents):
            raise ValueError("The assignment file must be outside Git at a canonical path.")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
                raise ValueError("The assignment file must be private and owned by the operator.")
            data = handle.read(64 * 1024 + 1)
        if len(data) > 64 * 1024:
            raise ValueError("The assignment file exceeds its size limit.")
        assignments = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
        command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        if not command:
            raise ValueError("An explicit child command is required.")
        # Only the selected agent is validated in full; the others are checked for independent roots.
        supervisor = workspace_policy.WorkspaceSupervisor(assignments, selected=args.agent, relaunch=args.relaunch)
        result = supervisor.run(args.agent, command, timeout=args.timeout)
    except workspace_policy.WorkspaceTaintedError as error:  # the child ran; its workspace is not safe for Git
        print(json.dumps({"status": "failed", "reason": str(error), "result": error.result}))
        sys.exit(1)
    except governor.GovernorDenied as error:
        print(json.dumps({"status": "denied", "reason": error.reason}))
        sys.exit(3)
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"status": "denied", "reason": str(error)}))
        sys.exit(3)
    print(json.dumps(result))
    sys.exit(0 if result["returncode"] == 0 else 1)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="cmd", required=True)
    commands.add_parser("audit")
    commands.add_parser("architecture")
    layers_parser = commands.add_parser("layers")
    layers_parser.add_argument("--verify", action="store_true")
    layers_parser.add_argument("--layer", action="append", default=[])
    layers_parser.add_argument("--state")
    layers_parser.add_argument("--json", action="store_true")
    capability_parser = commands.add_parser("capabilities")
    capability_parser.add_argument("--query", default="")
    capability_parser.add_argument("--state", choices=control.STATES)
    health_parser = commands.add_parser("health")
    health_parser.add_argument("--project")
    commands.add_parser("motions")
    commands.add_parser("integrations")
    search = commands.add_parser("search")
    search.add_argument("query")
    recommend_parser = commands.add_parser("recommend")
    recommend_parser.add_argument("query")
    onboard_parser = commands.add_parser("onboard")
    onboard_parser.add_argument("target")
    onboard_parser.add_argument("--revision", required=True)
    onboard_parser.add_argument("--apply", action="store_true")
    update_parser = commands.add_parser("update-pin")
    update_parser.add_argument("target")
    update_parser.add_argument("--revision", required=True)
    update_parser.add_argument("--expected", required=True)
    update_parser.add_argument("--apply", action="store_true")
    register_parser = commands.add_parser("register")
    register_parser.add_argument("target")
    register_parser.add_argument("--revision", required=True)
    register_parser.add_argument("--id")
    register_parser.add_argument("--repository")
    register_parser.add_argument("--capability", action="append", default=[])
    register_parser.add_argument("--remove", action="append", default=[])
    register_parser.add_argument("--apply", action="store_true")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("target")
    verify_parser.add_argument("--strict", action="store_true")
    route_parser = commands.add_parser("route")
    route_parser.add_argument("text")
    route_parser.add_argument("--workspace")
    workspace_parser = commands.add_parser("workspace-run", help="Run a local command in an assigned isolated workspace")
    workspace_parser.add_argument("--assignments", required=True, help="Operator-owned private assignment JSON file")
    workspace_parser.add_argument("--agent", required=True, help="Agent identity selected by the trusted operator")
    workspace_parser.add_argument("--timeout", required=True, type=float)
    workspace_parser.add_argument("--relaunch", action="store_true",
                                  help="The agent's workspace already holds its own work: skip the empty/clean check")
    workspace_parser.add_argument("argv", nargs=argparse.REMAINDER)
    inventory_parser = commands.add_parser("inventory")
    inventory_parser.add_argument("target")
    projects_parser = commands.add_parser("projects")
    projects_parser.add_argument("--audit", action="store_true")
    engines_parser = commands.add_parser("engines")
    engines_parser.add_argument("--json", action="store_true")
    engine_health_parser = commands.add_parser("engine-health")
    engine_health_parser.add_argument("id", nargs="?")
    invoke_parser = commands.add_parser("invoke")
    invoke_parser.add_argument("engine")
    invoke_parser.add_argument("action")
    invoke_parser.add_argument("--payload", required=True, help="JSON object (data, never instructions)")
    invoke_parser.add_argument("--grant", required=True, help="grant JSON file")
    invoke_parser.add_argument("--state", required=True, help="private state directory outside Git")
    invoke_parser.add_argument("--task")
    invoke_parser.add_argument("--host", choices=("claude-code", "codex"), default="claude-code")
    args = parser.parse_args()
    if args.cmd == "audit":
        result = audit()
    elif args.cmd == "architecture":
        from engineering_os import layers as layer_registry
        result = layer_registry.architecture()
    elif args.cmd == "layers":
        from engineering_os import layers as layer_registry
        ids = [part for value in args.layer for part in value.split(",") if part] or None
        try:
            if args.verify:
                report = layer_registry.verify(ids, state_dir=args.state)
                rows, code = report["layers"], 0 if report["ok"] else 1
            else:
                report = rows = layer_registry.status(ids, state_dir=args.state)
                code = 0
        except layer_registry.LayerError as error:
            print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
            sys.exit(2)
        print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else layer_registry.table(rows))
        sys.exit(code)
    elif args.cmd == "capabilities":
        result = control.capabilities(args.query, args.state)
    elif args.cmd == "health":
        result = control.health(args.project)
    elif args.cmd == "motions":
        result = control.motions()
    elif args.cmd == "integrations":
        result = control.integrations()
    elif args.cmd == "search":
        result = [
            item
            for item in registry()
            if args.query.casefold() in json.dumps(item).casefold()
        ]
    elif args.cmd == "recommend":
        result = recommend(args.query)
    elif args.cmd == "onboard":
        result = onboard(args.target, args.revision, args.apply)
    elif args.cmd == "update-pin":
        result = update_pin(args.target, args.revision, args.expected, args.apply)
    elif args.cmd == "register":
        result = hublink.register(
            args.target,
            args.revision,
            args.id,
            args.repository,
            args.capability,
            args.apply,
            args.remove,
        )
    elif args.cmd == "route":
        try:
            result = gaie_router.route(args.text, workspace_path=args.workspace)
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
            sys.exit(1)
        if result["status"] != "routed":
            print(json.dumps(result, indent=2, ensure_ascii=False))
            sys.exit(2)
    elif args.cmd == "workspace-run":
        workspace_run(args)
    elif args.cmd == "inventory":
        result = gaie_inventory.inventory(args.target)
    elif args.cmd == "engines":
        from engineering_os import control_plane

        rows = control_plane.engines()
        if not args.json:
            print(engine_table(rows))
            return
        result = rows
    elif args.cmd == "engine-health":
        from engineering_os import control_plane

        try:
            result = control_plane.health(args.id)
        except control_plane.ControlPlaneError as error:
            print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
            sys.exit(1)
        if not result["ok"]:
            print(json.dumps(result, indent=2, ensure_ascii=False))
            sys.exit(1)
    elif args.cmd == "invoke":
        result = invoke_command(args)
    elif args.cmd == "verify":
        result = hublink.verify(args.target, args.strict)
        if not result["ok"]:
            print(json.dumps(result, indent=2, ensure_ascii=False))
            sys.exit(1)
    else:
        result = hublink.audit_projects() if args.audit else hublink.projects()
        if args.audit and not all(item.get("ok", False) for item in result):
            print(json.dumps(result, indent=2, ensure_ascii=False))
            sys.exit(1)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
