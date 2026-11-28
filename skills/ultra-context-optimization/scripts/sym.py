#!/usr/bin/env python3
"""sym: ask the language server about code instead of reading whole files.

    sym overview FILE            the symbols a file defines
    sym def NAME [FILE]          where NAME is defined, with its body
    sym refs NAME FILE           who refers to the NAME defined in FILE
    sym check FILE               the language server's diagnostics for FILE

It starts Serena for the repository that contains the current directory, asks one
question and stops it. Serena runs locally: it starts language servers on this machine
and sends no code anywhere. Its dashboard is switched off, and its per-project folder
(.serena/) is added to the repository's private exclude list so it cannot be committed.

A cold start costs a few seconds. Use it when the alternative is reading a large file or
guessing at references; for a plain text match use ripgrep.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(os.environ.get("GAIE_TOOLS", Path.home() / ".gaie-tools"))
SERENA = TOOLS / "serena" / "venv" / "bin" / "serena"
LANGUAGES = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "typescript",
             ".mjs": "typescript", ".jsx": "typescript", ".cjs": "typescript"}


def probe_module():
    spec = importlib.util.spec_from_file_location("mcp_probe", Path(__file__).resolve().parent / "mcp_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repository(start: Path) -> Path:
    done = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(done.stdout.strip()) if done.returncode == 0 else start


def exclude_privately(root: Path) -> None:
    done = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-path", "info/exclude"], capture_output=True, text=True)
    if done.returncode != 0:
        return
    path = Path(done.stdout.strip())
    path = path if path.is_absolute() else root / path
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if ".serena/" not in current.split():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(current + ("" if current.endswith("\n") or not current else "\n") + ".serena/\n", encoding="utf-8")


def environment() -> dict:
    return {**os.environ, "SERENA_HOME": str(TOOLS / "serena" / "home"), "SERENA_USAGE_REPORTING": "false"}


def prepare(root: Path) -> None:
    """Create the Serena project once, for the languages this repository contains."""
    exclude_privately(root)
    if (root / ".serena" / "project.yml").exists():
        return
    listed = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True).stdout.splitlines()
    found = sorted({LANGUAGES[Path(name).suffix] for name in listed if Path(name).suffix in LANGUAGES})
    if not found:
        raise SystemExit("sym: no Python, TypeScript or JavaScript files here")
    command = [str(SERENA), "project", "create", "--log-level", "ERROR"]
    for language in found:
        command += ["--language", language]
    done = subprocess.run([*command, str(root)], capture_output=True, text=True, env=environment())
    if done.returncode != 0:
        raise SystemExit(f"sym: could not create the project: {(done.stderr or done.stdout).strip()[-200:]}")


def show(text: str, with_body: bool) -> str:
    """Print definitions as plain code with their location instead of escaped JSON."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if not (with_body and isinstance(data, list)):
        return text
    parts = []
    for item in data:
        where = item.get("body_location", {})
        parts.append(f"{item.get('relative_path')}:{where.get('start_line', 0) + 1}-{where.get('end_line', 0) + 1} "
                     f"{item.get('kind')} {item.get('name_path')}")
        if item.get("body"):
            parts.append(item["body"])
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sym", description=__doc__.split("\n\n")[0])
    parser.add_argument("--timeout", type=float, default=180)
    commands = parser.add_subparsers(dest="name", required=True)
    commands.add_parser("overview").add_argument("file")
    definition = commands.add_parser("def")
    definition.add_argument("symbol")
    definition.add_argument("file", nargs="?")
    definition.add_argument("--no-body", action="store_true")
    references = commands.add_parser("refs")
    references.add_argument("symbol")
    references.add_argument("file")
    commands.add_parser("check").add_argument("file")
    args = parser.parse_args(argv)
    if not SERENA.exists():
        raise SystemExit(f"sym: Serena is not installed at {SERENA}; run scripts/bootstrap.sh serena")
    root = repository(Path.cwd())
    prepare(root)

    def relative(name: str | None) -> str | None:
        return None if name is None else str(Path(name).resolve().relative_to(root))

    if args.name == "overview":
        tool, arguments = "get_symbols_overview", {"relative_path": relative(args.file)}
    elif args.name == "def":
        tool, arguments = "find_symbol", {"name_path_pattern": args.symbol, "include_body": not args.no_body}
        if args.file:
            arguments["relative_path"] = relative(args.file)
    elif args.name == "refs":
        tool, arguments = "find_referencing_symbols", {"name_path": args.symbol, "relative_path": relative(args.file)}
    else:
        tool, arguments = "get_diagnostics_for_file", {"relative_path": relative(args.file)}
    probe = probe_module()
    command = [str(SERENA), "start-mcp-server", "--project", str(root), "--context", "ide-assistant",
               "--agent-interface", "tools", "--enable-web-dashboard", "false", "--open-web-dashboard", "false",
               "--enable-gui-log-window", "false", "--transport", "stdio", "--log-level", "ERROR"]
    try:
        with probe.Server(command, args.timeout, env=environment(), cwd=str(root)) as server:
            text, failed = server.call(tool, arguments)
    except probe.ServerError as problem:
        raise SystemExit(f"sym: {problem}") from problem
    print(show(text, args.name == "def" and not args.no_body))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
