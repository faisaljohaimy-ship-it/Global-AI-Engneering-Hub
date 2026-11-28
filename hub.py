import argparse
import json
import pathlib
import re
import sys

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


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="cmd", required=True)
    commands.add_parser("audit")
    commands.add_parser("architecture")
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
    inventory_parser = commands.add_parser("inventory")
    inventory_parser.add_argument("target")
    projects_parser = commands.add_parser("projects")
    projects_parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    if args.cmd == "audit":
        result = audit()
    elif args.cmd == "architecture":
        result = control.architecture()
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
        result = gaie_router.route(args.text, workspace_path=args.workspace)
        if result["status"] != "routed":
            print(json.dumps(result, indent=2, ensure_ascii=False))
            sys.exit(2)
    elif args.cmd == "inventory":
        result = gaie_inventory.inventory(args.target)
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
