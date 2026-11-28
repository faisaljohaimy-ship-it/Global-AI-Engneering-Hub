"""Render a canonical GAIE plan with Codex-owned branch suggestions.

Run from the GAIE hub checkout with `python3 -B -m scripts.gaie_codex_route`.
This adapter plans only. SPDX-License-Identifier: MIT.
"""

import argparse
import json
import sys

from engineering_os import gaie_router


def route(text, *, environ=None, workspace_path=None):
    plan = gaie_router.route(text, environ=environ, workspace_path=workspace_path)
    if plan["status"] != "routed":
        return plan

    for target in plan["targets"]:
        scope = target["execution_scope"]
        if scope["kind"] != "repo-branch":
            continue
        branch = scope["branch"]
        if target.get("workspace_matches") is True:
            if not branch.startswith("codex/"):
                raise gaie_router.RouteError("Use a dedicated codex/ worktree for this Codex write plan.")
            continue

        suffix = f"gaie-{plan['intent']}-{target['id']}"
        if branch != f"claude/{suffix}":
            raise gaie_router.RouteError("Unexpected canonical branch suggestion; review routing before proceeding.")
        scope["branch"] = f"codex/{suffix}"
        if plan["project"] == target["id"]:
            plan["execution_scope"]["branch"] = scope["branch"]

    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("text")
    parser.add_argument("--workspace", help="dedicated new-project workspace or Codex-owned linked checkout")
    args = parser.parse_args(argv)
    try:
        result = route(args.text, workspace_path=args.workspace)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "routed" else 2


if __name__ == "__main__":
    sys.exit(main())
