"""Deterministic defect detectors over a target directory (L17 Self-Healing, stdlib only).

Static detectors read files and never execute them: broken routes, dead code,
duplicate components, dependency conflicts, security regressions, SQLite schema and
query smoke checks (in-memory database, ``EXPLAIN`` only) and media checks.
Runtime detectors (broken APIs, failed integrations, memory growth, performance)
execute target code only through :class:`Sandbox`: a child process with a fixed
driver, a minimal environment, a loopback-only socket guard and timeouts. The guard
is a Python-level check, not an OS sandbox, so ``run_all`` only runs them when the
caller passes ``runtime=True`` (``heal`` does so on a disposable copy).
Every finding is ``{id, key, detector, kind, location, evidence, severity}``;
evidence never contains a matched secret value.
SPDX-License-Identifier: MIT
"""

import ast
import contextlib
import copy
import html.parser
import http.client
import json
import math
import os
import pathlib
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse

from .orchestration import SECRET, sha
from scripts.security_scan import python_findings, secret_findings

SEVERITIES = ("info", "low", "medium", "high", "critical")
DETECTORS = ("broken-routes", "broken-apis", "dead-code", "duplicates", "dependencies", "memory",
             "performance", "security", "database", "media", "integrations")
RUNTIME = frozenset({"broken-apis", "integrations", "memory", "performance"})
MANIFEST = "healing.json"
MAX_FILES = 5000
MAX_FILE_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024 * 1024
SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"})
TEXT_SUFFIXES = frozenset({".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".toml", ".cfg", ".ini", ".yml",
                           ".yaml", ".env", ".sh", ".txt", ".html", ".htm", ".sql", ".npmrc"})
MEDIA_SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"), ".webm": (b"\x1a\x45\xdf\xa3",), ".mkv": (b"\x1a\x45\xdf\xa3",),
    ".ogg": (b"OggS",), ".flac": (b"fLaC",), ".mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    ".wav": (b"RIFF",), ".webp": (b"RIFF",), ".mp4": (), ".mov": (), ".m4a": (),
}
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"})
SHAPE_TYPES = {"str": (str,), "int": (int,), "float": (float,), "number": (int, float), "bool": (bool,),
               "list": (list,), "dict": (dict,), "null": (type(None),), "any": (object,)}
TEMPLATES = frozenset({"sql-scalar", "sql-rows", "static-json"})
CONVENTION = "conn-query->status-type-body"
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
ROUTE_PATH = re.compile(r"/[A-Za-z0-9_./~-]{0,200}")
PROBE_PATH = re.compile(r"/[A-Za-z0-9_./~-]{0,200}(?:\?[A-Za-z0-9_.~%=&-]{0,200})?")
SQL_START = re.compile(r"^\s*(?:SELECT|INSERT|UPDATE|DELETE|REPLACE|WITH)\b", re.I)
TLS_TEXT = re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED[\"']?\]?\s*[:=]\s*[\"']?0\b|PYTHONHTTPSVERIFY[\"']?\]?\s*[:=]\s*[\"']?0\b"
                      r"|rejectUnauthorized\s*:\s*false\b|strict-ssl\s*=\s*false\b|\bcurl\b[^\n]*\s(?:-k|--insecure)\b"
                      r"|\bwget\b[^\n]*--no-check-certificate", re.I)
JS_EVAL = re.compile(r"(?<![\w.])eval\s*\(|\bnew\s+Function\s*\(")
SECURITY_KINDS = {"subprocess-shell": ("shell-execution", "high"), "implicit-shell": ("shell-execution", "high"),
                  "pickle-deserialization": ("unsafe-deserialization", "high"),
                  "unsafe-yaml-loader": ("unsafe-deserialization", "high"),
                  "insecure-temporary-name": ("insecure-temp-file", "medium")}


class DetectorError(ValueError):
    """Malformed manifest or spec, unsafe path, or unusable target."""


# --------------------------------------------------------------------------- helpers

def _need(condition, message):
    if not condition:
        raise DetectorError(message)


def _pairs(rows):
    result = {}
    for key, value in rows:
        _need(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def _load_json(root, rel):
    path = _inside(root, rel)
    _need(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_FILE_BYTES, f"{rel}: bounded regular file required")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(DetectorError("Invalid JSON number")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DetectorError(f"{rel}: invalid JSON") from error


def rel_path(value, field="path"):
    """Validate a POSIX path relative to the target (no '..', no absolute, no backslash)."""
    _need(isinstance(value, str) and 0 < len(value) <= 255 and "\\" not in value and "\0" not in value, f"{field}: unsafe relative path")
    _need(not value.startswith("/") and all(part not in ("", ".", "..") for part in value.split("/")), f"{field}: unsafe relative path")
    return value


def _inside(root, rel):
    root = pathlib.Path(root).resolve()
    path = (root / rel_path(rel)).resolve()
    _need(path == root or root in path.parents, f"{rel}: path escapes the target")
    return path


def _obj(value, required, optional=(), field="object"):
    _need(isinstance(value, dict), f"{field}: object required")
    keys = set(value)
    _need(set(required) <= keys <= set(required) | set(optional), f"{field}: fields must be {sorted(required)} plus optional {sorted(optional)}")
    return value


def _int(value, low, high, field):
    _need(type(value) is int and low <= value <= high, f"{field}: integer {low}..{high} required")
    return value


def _number(value, low, high, field):
    _need(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and low <= value <= high,
          f"{field}: finite number {low}..{high} required")
    return value


def _redact(text, limit=400):
    text = (text or "")[-limit:]
    if SECRET.search(text) or secret_findings("output.txt", text):
        return "[redacted: credential-shaped output]"
    return "".join(char if char >= " " or char in "\n\t" else "?" for char in text)


def list_files(root):
    """Regular files under root (sorted, POSIX relative); symlinks and caches are skipped."""
    root = pathlib.Path(root).resolve()
    _need(root.is_dir(), "target must be a directory")
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or name.endswith((".pyc", ".pyo")):
                continue
            out.append(pathlib.Path(full).relative_to(root).as_posix())
            _need(len(out) <= MAX_FILES, "target has too many files")
    return sorted(out)


def read_text(root, rel):
    path = pathlib.Path(root) / rel
    try:
        if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _under(rel, directory):
    return bool(directory) and (rel == directory or rel.startswith(directory.rstrip("/") + "/"))


def finding(detector, kind, path, line, symbol, evidence, severity):
    """Build one finding; ``key`` is stable across line moves, ``id`` is unique per location."""
    _need(severity in SEVERITIES and detector in DETECTORS, "Unknown severity or detector")
    location = {"path": path, "line": line, "symbol": symbol}
    key = sha({"detector": detector, "kind": kind, "path": path, "symbol": symbol})[:16]
    return {"id": f"{kind}-{sha({'key': key, 'line': line, 'evidence': evidence})[:12]}", "key": key, "detector": detector,
            "kind": kind, "location": location, "evidence": evidence, "severity": severity}


def _report(detector, status, findings=(), reason=None, method="", extra=None):
    unique = {row["id"]: row for row in findings}
    rows = sorted(unique.values(), key=lambda row: (row["location"]["path"], row["location"]["line"] or 0, row["kind"], row["id"]))
    report = {"detector": detector, "status": status, "reason": reason, "method": method, "findings": rows}
    if extra:
        report.update(extra)
    return report


def _parse(source):
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None


def _python_modules(root, files, exclude=None):
    modules = {}
    for rel in files:
        if rel.endswith(".py") and not _under(rel, exclude):
            source = read_text(root, rel)
            tree = _parse(source) if source is not None else None
            if tree is not None:
                modules[rel] = (source, tree)
    return modules


# --------------------------------------------------------------------------- manifest and specs

def load_manifest(root):
    """Read and validate ``healing.json`` (optional); returns {} when absent."""
    root = pathlib.Path(root).resolve()
    if not (root / MANIFEST).exists():
        return {}
    return validate_manifest(_load_json(root, MANIFEST), root)


def validate_manifest(manifest, root):
    optional = {"name", "app", "route_spec", "links", "contracts", "dependencies", "database", "memory",
                "performance", "security_baseline", "entrypoints"}
    _obj(manifest, {"schema_version"}, optional, "manifest")
    _need(manifest["schema_version"] == 1 and type(manifest["schema_version"]) is int, "manifest: unknown schema_version")
    if "name" in manifest:
        _need(isinstance(manifest["name"], str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", manifest["name"]), "manifest.name: slug required")
    if "app" in manifest:
        app = _obj(manifest["app"], {"script"}, {"args", "ready_path", "routes_module", "routes_variable", "startup_timeout_s"}, "manifest.app")
        _need(rel_path(app["script"], "app.script").endswith(".py"), "app.script: Python file required")
        args = app.get("args", [])
        _need(isinstance(args, list) and len(args) <= 20 and all(isinstance(a, str) and len(a) <= 200 for a in args), "app.args: bounded strings")
        for arg in args:
            _need(set(re.findall(r"\{([^}]*)\}", arg)) <= {"port", "db"}, "app.args: only {port} and {db} placeholders")
        _need(ROUTE_PATH.fullmatch(app.get("ready_path", "/")) is not None, "app.ready_path: absolute route path")
        _need(rel_path(app.get("routes_module", app["script"]), "app.routes_module").endswith(".py"), "app.routes_module: Python file")
        _need(IDENTIFIER.fullmatch(app.get("routes_variable", "ROUTES")) is not None, "app.routes_variable: identifier")
        _number(app.get("startup_timeout_s", 10), 1, 60, "app.startup_timeout_s")
    for field in ("route_spec", "contracts", "security_baseline"):
        if field in manifest:
            _need(rel_path(manifest[field], field).endswith(".json"), f"{field}: JSON file")
    if "links" in manifest:
        _need(isinstance(manifest["links"], list) and len(manifest["links"]) <= 20, "links: bounded list")
        for item in manifest["links"]:
            rel_path(item, "links")
    if "dependencies" in manifest:
        deps = _obj(manifest["dependencies"], {"requirements"}, {"lock"}, "manifest.dependencies")
        _need(isinstance(deps["requirements"], list) and 0 < len(deps["requirements"]) <= 20, "dependencies.requirements: list")
        for item in deps["requirements"] + ([deps["lock"]] if "lock" in deps else []):
            rel_path(item, "dependencies")
    if "database" in manifest:
        database = _obj(manifest["database"], {"schema"}, (), "manifest.database")
        _need(isinstance(database["schema"], list) and len(database["schema"]) <= 20, "database.schema: list")
        for item in database["schema"]:
            rel_path(item, "database.schema")
    if "memory" in manifest:
        _need(isinstance(manifest["memory"], list) and len(manifest["memory"]) <= 20, "memory: bounded list")
        for row in manifest["memory"]:
            _callable_spec(row, {"calls", "threshold_bytes"}, "memory")
            _int(row["calls"], 10, 100000, "memory.calls")
            _int(row["threshold_bytes"], 1024, 10 ** 9, "memory.threshold_bytes")
    if "performance" in manifest:
        _obj(manifest["performance"], {"baseline"}, (), "manifest.performance")
        _need(rel_path(manifest["performance"]["baseline"], "performance.baseline").endswith(".json"), "performance.baseline: JSON")
    if "entrypoints" in manifest:
        _need(isinstance(manifest["entrypoints"], list) and len(manifest["entrypoints"]) <= 100
              and all(isinstance(e, str) and IDENTIFIER.fullmatch(e) for e in manifest["entrypoints"]), "entrypoints: identifiers")
    return manifest


def _callable_spec(row, extra, field):
    _obj(row, {"module", "function"} | set(extra), {"args"}, field)
    _need(isinstance(row["module"], str) and re.fullmatch(r"[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*){0,5}", row["module"]), f"{field}.module: dotted name")
    _need(isinstance(row["function"], str) and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?", row["function"]), f"{field}.function: name")
    args = row.get("args", [])
    _need(isinstance(args, list) and len(args) <= 16 and len(json.dumps(args)) <= 4096, f"{field}.args: bounded JSON list")
    return row


def load_route_spec(root, rel):
    """Validate a declared route spec (``routes.json``)."""
    spec = _obj(_load_json(root, rel), {"schema_version", "routes"}, {"module", "table", "handler_convention"}, "route spec")
    _need(spec["schema_version"] == 1 and type(spec["schema_version"]) is int, "route spec: unknown schema_version")
    _need(isinstance(spec["routes"], list) and len(spec["routes"]) <= 200, "route spec: bounded routes list")
    seen = set()
    for row in spec["routes"]:
        _obj(row, {"method", "path", "handler", "response"}, {"implementation", "probe"}, "route")
        _need(row["method"] in METHODS and ROUTE_PATH.fullmatch(row["path"] or "") is not None, "route: method and path")
        _need(IDENTIFIER.fullmatch(row["handler"]) is not None, "route.handler: identifier")
        _need((row["method"], row["path"]) not in seen, "route spec: duplicate route")
        seen.add((row["method"], row["path"]))
        response = _obj(row["response"], set(), {"status", "type", "shape", "content_type"}, "route.response")
        _int(response.get("status", 200), 100, 599, "route.response.status")
        _need(response.get("type", "json") in ("json", "html", "text"), "route.response.type")
        _shape(response.get("shape", {}))
        if "probe" in row:
            _need(PROBE_PATH.fullmatch(row["probe"]) is not None and row["probe"].split("?")[0] == row["path"], "route.probe: path with query")
        if "implementation" in row:
            impl = _obj(row["implementation"], {"template"}, {"query", "field", "body"}, "route.implementation")
            _need(impl["template"] in TEMPLATES, "route.implementation.template: unknown template")
    return spec


def _shape(shape):
    _need(isinstance(shape, dict) and len(shape) <= 50, "shape: object")
    for key, kind in shape.items():
        _need(isinstance(key, str) and 0 < len(key) <= 64 and kind in SHAPE_TYPES, "shape: key -> known type")
    return shape


def shape_mismatches(value, shape):
    if not isinstance(value, dict):
        return ["body-not-object"] if shape else []
    out = []
    for key, kind in sorted(shape.items()):
        if key not in value:
            out.append(f"missing:{key}")
        elif kind != "any" and (not isinstance(value[key], SHAPE_TYPES[kind]) or isinstance(value[key], bool) and kind in ("int", "float", "number")):
            out.append(f"type:{key}")
    return out


# --------------------------------------------------------------------------- broken routes

def route_table(source, variable="ROUTES"):
    """Return (table node, entries) for a module-level literal dict route table, else (None, [])."""
    tree = _parse(source)
    if tree is None:
        return None, []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == variable for t in targets) and isinstance(node.value, ast.Dict):
            entries = []
            for key, value in zip(node.value.keys, node.value.values):
                method, path = "GET", None
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    path = key.value
                elif isinstance(key, ast.Tuple) and len(key.elts) == 2 and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in key.elts):
                    method, path = key.elts[0].value.upper(), key.elts[1].value
                handler = value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else value.id if isinstance(value, ast.Name) else None
                if path is not None:
                    entries.append({"method": method, "path": path, "handler": handler, "line": key.lineno})
            return node, entries
    return None, []


def _module_names(tree):
    defined, imported = set(), set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                defined.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imported.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return defined, imported


class _Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src", "action") and isinstance(value, str):
                self.links.append((value, self.getpos()[0]))


def internal_links(root, files, scopes=None):
    links = []
    for rel in files:
        if not rel.endswith((".html", ".htm")) or scopes and not any(_under(rel, scope) for scope in scopes):
            continue
        parser = _Links()
        try:
            parser.feed(read_text(root, rel) or "")
            parser.close()
        except (ValueError, AssertionError):
            continue
        for value, line in parser.links:
            if value.startswith("/") and not value.startswith("//"):
                links.append({"path": urllib.parse.urlsplit(value).path, "file": rel, "line": line})
    return links


def detect_broken_routes(root, files=None, manifest=None):
    """Route table vs handler definitions vs declared spec vs internal links (static)."""
    root, manifest = pathlib.Path(root).resolve(), manifest or {}
    files = list_files(root) if files is None else files
    app = manifest.get("app", {})
    module = app.get("routes_module", app.get("script", "app.py"))
    variable = app.get("routes_variable", "ROUTES")
    source = read_text(root, module) if module in files else None
    table, entries = route_table(source, variable) if source is not None else (None, [])
    if table is None:
        return _report("broken-routes", "not-configured", reason=f"no literal route table {variable} in {module}", method="static-ast")
    defined, imported = _module_names(ast.parse(source))
    spec = load_route_spec(root, manifest["route_spec"]) if manifest.get("route_spec") else None
    links = internal_links(root, files, manifest.get("links"))
    routed = {(row["method"], row["path"]) for row in entries}
    paths = {row["path"] for row in entries}
    out, seen = [], {}
    for row in entries:
        key = (row["method"], row["path"])
        if key in seen:
            out.append(finding("broken-routes", "duplicate-route", module, row["line"], f"{key[0]} {key[1]}", {"route": row["path"], "method": row["method"], "first_line": seen[key]}, "medium"))
        seen.setdefault(key, row["line"])
        handler = row["handler"]
        if handler is None or handler not in defined | imported:
            declared = spec is not None and any(r["method"] == row["method"] and r["path"] == row["path"] for r in spec["routes"])
            linked = sorted({link["file"] for link in links if link["path"] == row["path"]})
            out.append(finding("broken-routes", "missing-route-handler", module, row["line"], handler or "<non-literal>",
                               {"route": row["path"], "method": row["method"], "handler": handler, "spec_declares": declared, "linked_from": linked}, "high"))
    if spec is not None:
        spec_routes = {(r["method"], r["path"]) for r in spec["routes"]}
        for row in spec["routes"]:
            if (row["method"], row["path"]) not in routed:
                out.append(finding("broken-routes", "route-missing-from-table", manifest["route_spec"], None, f"{row['method']} {row['path']}",
                                   {"route": row["path"], "method": row["method"], "handler": row["handler"]}, "high"))
        for row in entries:
            if (row["method"], row["path"]) not in spec_routes:
                out.append(finding("broken-routes", "undeclared-route", module, row["line"], f"{row['method']} {row['path']}", {"route": row["path"], "method": row["method"]}, "low"))
    for link in links:
        if link["path"] not in paths and not (root / link["path"].lstrip("/")).is_file():
            out.append(finding("broken-routes", "broken-internal-link", link["file"], link["line"], link["path"], {"route": link["path"]}, "medium"))
    return _report("broken-routes", "ran", out, method="static-ast+html", extra={"routes": len(entries), "links_checked": len(links)})


# --------------------------------------------------------------------------- dead code and duplicates

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def detect_dead_code(root, files=None, *, tests_dir=None, entrypoints=()):
    """Top-level definitions with no static reference anywhere (code, strings, text files).

    ``proof`` is ``no-static-reference`` only when no module uses dynamic name access
    (``globals()``, ``vars()``, ``getattr`` with a computed name, ``eval``/``exec``,
    computed imports); otherwise the candidate is ``unproven-dynamic-access``.
    """
    root = pathlib.Path(root).resolve()
    files = list_files(root) if files is None else files
    modules = _python_modules(root, files)
    refs, dynamic_local, dynamic_global = set(), set(), False
    words = set()
    for rel in files:
        if not rel.endswith(".py") and pathlib.PurePosixPath(rel).suffix in TEXT_SUFFIXES:
            words.update(IDENT.findall(read_text(root, rel) or ""))
    exported = {}
    for rel, (_, tree) in modules.items():
        for top in tree.body:
            owner = top.name if isinstance(top, _DEFS) else None
            for node in ast.walk(top):
                if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
                    refs.add((node.id, rel, owner))
                elif isinstance(node, ast.Attribute):
                    refs.add((node.attr, rel, owner))
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    refs.update((word, rel, owner) for word in IDENT.findall(node.value[:4000]))
                elif isinstance(node, ast.ImportFrom):
                    refs.update((alias.name, rel, None) for alias in node.names)
                elif isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    computed = len(node.args) < 2 or not isinstance(node.args[1], ast.Constant)
                    if name in ("globals", "locals", "vars"):
                        dynamic_local.add(rel)
                    elif name in ("eval", "exec") or name == "getattr" and computed or name in ("__import__", "import_module") and node.args and not isinstance(node.args[0], ast.Constant):
                        dynamic_global = True
            if isinstance(top, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in top.targets):
                exported[rel] = {n.value for n in ast.walk(top.value) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    out = []
    for rel, (_, tree) in modules.items():
        if _under(rel, tests_dir):
            continue
        for node in tree.body:
            if not isinstance(node, _DEFS):
                continue
            name = node.name
            if (name.startswith("__") and name.endswith("__") or name.startswith(("test", "setUp", "tearDown")) or name in entrypoints
                    or node.decorator_list or name in exported.get(rel, ()) or name in words):
                continue
            if any(ref_name == name and not (module == rel and owner == name) for ref_name, module, owner in refs):
                continue
            proof = "unproven-dynamic-access" if dynamic_global or rel in dynamic_local else "no-static-reference"
            out.append(finding("dead-code", "dead-code", rel, node.lineno, name,
                               {"definition": "class" if isinstance(node, ast.ClassDef) else "function",
                                "lines": [node.lineno, node.end_lineno], "references": 0, "proof": proof}, "low"))
    return _report("dead-code", "ran", out, method="static-ast-reference-scan",
                   extra={"dynamic_access": sorted(dynamic_local) + (["<global>"] if dynamic_global else [])})


def normalized_hash(node):
    """SHA-256 of a definition with its name, docstring and local names alpha-renamed."""
    node = copy.deepcopy(node)
    body = getattr(node, "body", [])
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        node.body = body[1:] or [ast.Pass()]
    local = {n.arg for n in ast.walk(node) if isinstance(n, ast.arg)}
    local |= {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
    mapping = {}
    for sub in ast.walk(node):
        if isinstance(sub, ast.arg):
            sub.arg, sub.annotation = mapping.setdefault(sub.arg, f"_{len(mapping)}"), None
        elif isinstance(sub, ast.Name) and sub.id in local:
            sub.id = mapping.setdefault(sub.id, f"_{len(mapping)}")
    node.name, node.decorator_list = "_", []
    if hasattr(node, "returns"):
        node.returns = None
    dump = ast.dump(node, annotate_fields=False, include_attributes=False)
    return sha(dump), sum(1 for _ in ast.walk(node))


def detect_duplicates(root, files=None, *, tests_dir=None, min_nodes=24):
    """Groups of functions/methods whose normalized AST is identical."""
    root = pathlib.Path(root).resolve()
    files = list_files(root) if files is None else files
    groups = {}
    for rel, (_, tree) in _python_modules(root, files, exclude=tests_dir).items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                digest, size = normalized_hash(node)
                if size >= min_nodes:
                    groups.setdefault(digest, []).append({"path": rel, "line": node.lineno, "symbol": node.name})
    out = []
    for digest, members in sorted(groups.items()):
        if len(members) > 1:
            members.sort(key=lambda row: (row["path"], row["line"]))
            first = members[0]
            out.append(finding("duplicates", "duplicate-component", first["path"], first["line"], first["symbol"],
                               {"normalized_sha256": digest, "members": members}, "low"))
    return _report("duplicates", "ran", out, method="normalized-ast-sha256")


# --------------------------------------------------------------------------- dependencies

_VERSION = re.compile(r"v?(\d+(?:\.\d+){0,5})(?:[-_.]?(a|b|rc|c|alpha|beta|pre|preview)[-_.]?(\d*))?"
                      r"(?:[-_.]?(post|rev|r)[-_.]?(\d*))?(?:[-_.]?(dev)[-_.]?(\d*))?(?:\+[a-z0-9.]+)?", re.I)
_REQUIREMENT = re.compile(r"([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(?:\[[^\]]*\])?\s*(.*)")
_SPECIFIER = re.compile(r"(===|==|!=|~=|>=|<=|>|<)\s*([A-Za-z0-9*+!._-]+)")


def canonical_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def version_key(text):
    """Comparable key for a PEP 440-style version (release, pre, post, dev); None if unparseable."""
    match = _VERSION.fullmatch(text.strip()) if isinstance(text, str) else None
    if not match:
        return None
    release = [int(part) for part in match[1].split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    pre = ({"a": 0, "alpha": 0, "b": 1, "beta": 1}.get(match[2].lower(), 2), int(match[3] or 0)) if match[2] else (3, 0)
    if match[6] and not match[2] and not match[4]:
        pre = (-1, 0)
    return (tuple(release), pre, int(match[5] or 0) if match[4] else -1, int(match[7] or 0) if match[6] else math.inf)


def satisfies(version, operator, target):
    """True/False when decidable, None when either side is unparseable."""
    if operator == "===":
        return version.strip() == target.strip()
    if operator in ("==", "!=") and target.endswith(".*"):
        prefix, match = target[:-2].split("."), _VERSION.fullmatch(version.strip())
        if not match or not all(part.isdigit() for part in prefix):
            return None
        release = [int(part) for part in match[1].split(".")] + [0] * len(prefix)
        same = release[:len(prefix)] == [int(part) for part in prefix]
        return same if operator == "==" else not same
    left, right = version_key(version), version_key(target)
    if left is None or right is None:
        return None
    if operator == "~=":
        parts = target.split(".")
        if len(parts) < 2:
            return None
        return left >= right and satisfies(version, "==", ".".join(parts[:-1]) + ".*")
    return {"==": left == right, "!=": left != right, ">=": left >= right, "<=": left <= right, ">": left > right, "<": left < right}[operator]


def parse_requirements(root, rel, depth=0, seen=None):
    """Requirement rows {package, name, specs, path, line} from a pip requirements file."""
    seen = set() if seen is None else seen
    if rel in seen or depth > 3:
        return []
    seen.add(rel)
    text = read_text(root, rel)
    _need(text is not None, f"{rel}: readable text required")
    rows, logical, start = [], "", 1
    for number, raw in enumerate(text.splitlines() + [""], 1):
        if not logical:
            start = number
        if raw.rstrip().endswith("\\"):
            logical += raw.rstrip()[:-1] + " "
            continue
        line, logical = (logical + raw), ""
        line = re.sub(r"(^|\s)#.*$", "", line).strip()
        if not line:
            continue
        if re.match(r"(-r|--requirement|-c|--constraint)[\s=]", line):
            include = re.split(r"[\s=]+", line, maxsplit=1)[1].strip()
            nested = str(pathlib.PurePosixPath(rel).parent / include) if "/" in rel else include
            rows.extend(parse_requirements(root, rel_path(os.path.normpath(nested), "requirements include"), depth + 1, seen))
            continue
        if line.startswith("-"):
            continue
        line = re.sub(r"\s--hash[=\s]\S+", "", line.split(";", 1)[0]).strip()
        match = _REQUIREMENT.fullmatch(line)
        if not match or "://" in line or "@" in line:
            rows.append({"package": None, "name": line[:80], "specs": [], "path": rel, "line": start, "unparsed": True})
            continue
        specs, ok = [], True
        for part in filter(None, (piece.strip() for piece in match[2].split(","))):
            spec = _SPECIFIER.fullmatch(part)
            if spec is None:
                ok = False
            else:
                specs.append([spec[1], spec[2]])
        rows.append({"package": canonical_name(match[1]), "name": match[1], "specs": specs, "path": rel, "line": start, "unparsed": not ok})
    return rows


def parse_lock(root, rel):
    """{package: {version, hashed}} from a JSON lock ({packages: ...} or Pipfile.lock) or a hashed text lock."""
    out = {}
    if rel.endswith(".json") or rel.endswith("Pipfile.lock"):
        data = _load_json(root, rel)
        _need(isinstance(data, dict), f"{rel}: lock object required")
        sections = [data["packages"]] if isinstance(data.get("packages"), dict) else [data.get(k) for k in ("default", "develop") if isinstance(data.get(k), dict)]
        for section in sections:
            for name, entry in section.items():
                version = entry.get("version") if isinstance(entry, dict) else entry
                if isinstance(version, str):
                    hashed = isinstance(entry, dict) and any(isinstance(entry.get(k), (str, list)) and entry.get(k) for k in ("sha256", "hashes", "integrity"))
                    out[canonical_name(name)] = {"version": version.lstrip("="), "hashed": bool(hashed)}
        return out
    for row in parse_requirements(root, rel):
        exact = [value for op, value in row["specs"] if op in ("==", "===")]
        if row["package"] and exact:
            out[row["package"]] = {"version": exact[0], "hashed": "--hash" in (read_text(root, rel) or "")}
    return out


def detect_dependencies(root, files=None, manifest=None):
    """Requirement pins vs other pins vs the lock file (no install, no network)."""
    root, manifest = pathlib.Path(root).resolve(), manifest or {}
    files = list_files(root) if files is None else files
    config = manifest.get("dependencies")
    if config is None:
        requirements = [f for f in files if re.fullmatch(r"(?:.*/)?requirements[\w.-]*\.txt", f) and "lock" not in f]
        locks = [f for f in ("requirements.lock.json", "Pipfile.lock", "requirements.lock", "requirements-lock.txt") if f in files]
        config = {"requirements": requirements, **({"lock": locks[0]} if locks else {})}
    if not config["requirements"]:
        return _report("dependencies", "not-configured", reason="no requirements files", method="static-parse")
    rows = [row for rel in config["requirements"] for row in parse_requirements(root, rel)]
    lock = parse_lock(root, config["lock"]) if config.get("lock") else None
    out, pins = [], {}
    for row in rows:
        if row["unparsed"]:
            out.append(finding("dependencies", "unparsed-requirement", row["path"], row["line"], row["name"], {"package": row["package"]}, "low"))
            continue
        if row["package"] is None:
            continue
        for op, value in row["specs"]:
            if op in ("==", "===") and not value.endswith(".*"):
                pins.setdefault(row["package"], []).append((value, row))
        if not row["specs"]:
            out.append(finding("dependencies", "unpinned-requirement", row["path"], row["line"], row["package"], {"package": row["package"]}, "low"))
        if lock is None:
            continue
        locked = lock.get(row["package"])
        if locked is None:
            out.append(finding("dependencies", "unlocked-requirement", row["path"], row["line"], row["package"], {"package": row["package"], "lock": config["lock"]}, "medium"))
            continue
        verdicts = [satisfies(locked["version"], op, value) for op, value in row["specs"]]
        if False in verdicts:
            exact = len(row["specs"]) == 1 and row["specs"][0][0] in ("==", "===") and not row["specs"][0][1].endswith(".*")
            out.append(finding("dependencies", "pin-lock-mismatch" if exact else "range-violation", row["path"], row["line"], row["package"],
                               {"package": row["package"], "required": ",".join(op + value for op, value in row["specs"]),
                                "locked": locked["version"], "lock": config["lock"], "lock_has_integrity": locked["hashed"]}, "high"))
    for package, values in sorted(pins.items()):
        if len({version_key(value) or value for value, _ in values}) > 1:
            first = values[0][1]
            out.append(finding("dependencies", "conflicting-pins", first["path"], first["line"], package,
                               {"package": package, "pins": sorted({f"{row['path']}:{row['line']}=={value}" for value, row in values})}, "high"))
    return _report("dependencies", "ran", out, method="static-parse+pep440-subset", extra={"requirements": len(rows), "locked": None if lock is None else len(lock)})


# --------------------------------------------------------------------------- security

def _fingerprint(kind, rel, rule, line_text):
    return sha({"kind": kind, "path": rel, "rule": rule, "text": sha(line_text.strip())})[:24]


def _python_security(source):
    tree = _parse(source)
    if tree is None:
        return []
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "builtins" else None
            if name in ("eval", "exec"):
                hits.append(("dynamic-code-execution", "high", node.lineno, name))
            for keyword in node.keywords:
                if keyword.arg == "verify" and isinstance(keyword.value, ast.Constant) and keyword.value.value in (False, 0):
                    hits.append(("tls-verification-disabled", "high", node.lineno, "verify-false"))
        elif isinstance(node, (ast.Attribute, ast.Name)):
            name = node.attr if isinstance(node, ast.Attribute) else node.id
            if name in ("_create_unverified_context", "CERT_NONE") and (isinstance(node, ast.Name) or isinstance(node.value, ast.Name) and node.value.id == "ssl"):
                hits.append(("tls-verification-disabled", "high", node.lineno, name))
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value is False:
            if any(isinstance(t, ast.Attribute) and t.attr == "check_hostname" for t in node.targets):
                hits.append(("tls-verification-disabled", "high", node.lineno, "check-hostname-false"))
    return hits


def detect_security(root, files=None, *, baseline=None):
    """eval/exec, shell execution, unsafe loaders, credential look-alikes and disabled TLS checks.

    ``baseline`` is an optional collection of fingerprints; findings outside it are
    marked ``"baseline": "new"`` (a regression), inside it ``"known"``. Matched
    values are never reported, only the rule, line and a fingerprint.
    """
    root = pathlib.Path(root).resolve()
    files = list_files(root) if files is None else files
    known = None if baseline is None else set(baseline)
    out = []
    for rel in files:
        suffix = pathlib.PurePosixPath(rel).suffix.lower()
        if suffix not in TEXT_SUFFIXES and not pathlib.PurePosixPath(rel).name.startswith(".env"):
            continue
        source = read_text(root, rel)
        if source is None:
            continue
        lines = source.splitlines() or [""]
        hits = [("hard-coded-secret", "critical", row.line, row.rule) for row in secret_findings(rel, source)]
        if suffix == ".py":
            hits += [SECURITY_KINDS[row.rule] + (row.line, row.rule) for row in python_findings(rel, source) if row.rule in SECURITY_KINDS]
            hits += _python_security(source)
        if suffix in (".js", ".mjs", ".cjs", ".ts", ".html", ".htm"):
            hits += [("dynamic-code-execution", "high", source.count("\n", 0, m.start()) + 1, "js-eval") for m in JS_EVAL.finditer(source)]
        hits += [("tls-verification-disabled", "high", source.count("\n", 0, m.start()) + 1, "tls-text") for m in TLS_TEXT.finditer(source)]
        for kind, severity, line, rule in sorted(set(hits), key=lambda hit: (hit[2], hit[0], hit[3])):
            text = lines[min(max(line, 1), len(lines)) - 1]
            fingerprint = _fingerprint(kind, rel, rule, text)
            state = "no-baseline" if known is None else "known" if fingerprint in known else "new"
            out.append(finding("security", kind, rel, line, rule, {"rule": rule, "fingerprint": fingerprint, "baseline": state}, severity))
    return _report("security", "ran", out, method="static-ast+pattern (values never reported)")


# --------------------------------------------------------------------------- database

def _bindings(query):
    stripped = re.sub(r"'(?:[^']|'')*'", "''", query)
    named = sorted(set(re.findall(r"[:@$]([A-Za-z_]\w*)", stripped)))
    if named:
        return {name: None for name in named}
    numbered = [int(n) for n in re.findall(r"\?(\d+)", stripped)]
    return (None,) * max([stripped.count("?")] + numbered)


def explain_query(root, schemas, query):
    """EXPLAIN one query against the declared schema in a fresh in-memory database; None or the error text."""
    memory = sqlite3.connect(":memory:")
    try:
        for rel in schemas:
            memory.executescript(read_text(root, rel) or "")
        memory.execute("EXPLAIN " + query, _bindings(query))
        return None
    except (sqlite3.Error, ValueError) as error:
        return _redact(str(error), 200)
    finally:
        memory.close()


def sql_queries(root, files, *, tests_dir=None):
    """SQL string literals in Python sources: [(path, line, query)]."""
    out = []
    for rel, (_, tree) in _python_modules(root, files, exclude=tests_dir).items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) <= 4000 and SQL_START.match(node.value):
                out.append((rel, node.lineno, node.value))
    return out


def detect_database(root, files=None, manifest=None, *, tests_dir=None, extra_queries=()):
    """Apply declared schema to an in-memory SQLite database, EXPLAIN every query, check DB files read-only."""
    root, manifest = pathlib.Path(root).resolve(), manifest or {}
    files = list_files(root) if files is None else files
    schemas = manifest.get("database", {}).get("schema")
    if schemas is None:
        schemas = [f for f in files if f.endswith(".sql") and re.search(r"\bCREATE\s+TABLE\b", read_text(root, f) or "", re.I)]
    queries = sql_queries(root, files, tests_dir=tests_dir) + list(extra_queries)
    databases = [f for f in files if f.endswith((".db", ".sqlite", ".sqlite3"))]
    if not schemas and not queries and not databases:
        return _report("database", "not-configured", reason="no schema, SQL literals or database files", method="sqlite-in-memory")
    out = []
    memory = sqlite3.connect(":memory:")
    try:
        for rel in schemas:
            try:
                memory.executescript(read_text(root, rel) or "")
            except sqlite3.Error as error:
                out.append(finding("database", "schema-error", rel, None, rel, {"error": _redact(str(error), 200)}, "high"))
        if schemas:
            for rel, line, query in queries:
                try:
                    memory.execute("EXPLAIN " + query, _bindings(query))
                except (sqlite3.Error, ValueError) as error:
                    out.append(finding("database", "query-error", rel, line, f"sql@{line}",
                                       {"error": _redact(str(error), 200), "query_sha256": sha(query)}, "high"))
    finally:
        memory.close()
    for rel in databases:
        path = _inside(root, rel)
        try:
            conn = sqlite3.connect(f"file:{urllib.parse.quote(str(path))}?mode=ro", uri=True)
            try:
                status = conn.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error as error:
            status = str(error)
        if status != "ok":
            out.append(finding("database", "database-integrity", rel, None, rel, {"result": _redact(str(status), 200)}, "critical"))
    status = "ran" if schemas or databases else "partial"
    reason = None if schemas else "no schema declared; SQL literals were not checked"
    return _report("database", status, out, reason=reason, method="sqlite-in-memory EXPLAIN + read-only quick_check",
                   extra={"schemas": len(schemas), "queries": len(queries) if schemas else 0, "databases": len(databases)})


# --------------------------------------------------------------------------- media

def detect_media(root, files=None, *, ffprobe="auto", timeout=20):
    """Magic-byte signatures always; decoding via ffprobe when available, otherwise reported as skipped."""
    root = pathlib.Path(root).resolve()
    files = list_files(root) if files is None else files
    media = [f for f in files if pathlib.PurePosixPath(f).suffix.lower() in MEDIA_SIGNATURES][:200]
    if not media:
        return _report("media", "ran", reason="no media files", method="magic-bytes", extra={"decode_checked": 0})
    probe = shutil.which("ffprobe") if ffprobe == "auto" else ffprobe
    out, decoded = [], 0
    for rel in media:
        path = _inside(root, rel)
        suffix = pathlib.PurePosixPath(rel).suffix.lower()
        with path.open("rb") as stream:
            head = stream.read(16)
        signatures = MEDIA_SIGNATURES[suffix]
        ok = (head[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free")) if not signatures else any(head.startswith(s) for s in signatures)
        if suffix == ".wav":
            ok = ok and head[8:12] == b"WAVE"
        if suffix == ".webp":
            ok = ok and head[8:12] == b"WEBP"
        if not ok:
            out.append(finding("media", "media-signature-mismatch", rel, None, rel, {"suffix": suffix, "bytes": path.stat().st_size}, "medium"))
        if probe:
            try:
                done = subprocess.run([probe, "-v", "error", "-show_entries", "format=format_name,duration", "-of", "json", str(path)],
                                      stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
                error = done.stderr.decode("utf-8", "replace").strip()
                decoded += 1
                if done.returncode != 0 or error:
                    out.append(finding("media", "broken-media", rel, None, rel, {"ffprobe_exit": done.returncode, "error": _redact(error, 200)}, "high"))
            except (OSError, subprocess.TimeoutExpired) as error:
                out.append(finding("media", "broken-media", rel, None, rel, {"ffprobe_exit": None, "error": type(error).__name__}, "high"))
    if not probe:
        return _report("media", "partial", out, reason="ffprobe not available: decoding was skipped; only magic-byte signatures were checked",
                       method="magic-bytes", extra={"decode_checked": 0})
    return _report("media", "ran", out, method="magic-bytes+ffprobe", extra={"decode_checked": decoded})


# --------------------------------------------------------------------------- sandboxed execution

DRIVER = r'''
import ipaddress, json, os, socket, sys, threading, traceback

REFUSED = "network access outside loopback refused by the GAIE healing guard"


def _loopback(family, address):
    if family == getattr(socket, "AF_UNIX", object()):
        return True
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("ascii", "replace")
    host = str(host)
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _guard():
    connect, connect_ex, sendto, getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto, socket.getaddrinfo

    def guarded_connect(self, address):
        if not _loopback(self.family, address):
            raise PermissionError(REFUSED)
        return connect(self, address)

    def guarded_connect_ex(self, address):
        if not _loopback(self.family, address):
            raise PermissionError(REFUSED)
        return connect_ex(self, address)

    def guarded_sendto(self, data, *rest):
        if rest and not _loopback(self.family, rest[-1]):
            raise PermissionError(REFUSED)
        return sendto(self, data, *rest)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host is not None and not _loopback(socket.AF_INET, (host, 0)):
            raise PermissionError(REFUSED)
        return getaddrinfo(host, *args, **kwargs)

    socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto = guarded_connect, guarded_connect_ex, guarded_sendto
    socket.getaddrinfo = guarded_getaddrinfo


def _tests(request, root):
    import unittest
    start = os.path.realpath(os.path.join(root, request["start"]))
    source_prefix, tests_prefix = root + os.sep, start + os.sep
    state = {"functions": None, "files": None, "busy": False}
    known = {}

    def relative(name):
        value = known.get(name)
        if value is None:
            real = os.path.realpath(name) if name and not name.startswith("<") else ""
            value = known[name] = os.path.relpath(real, root) if real.startswith(source_prefix) and not real.startswith(tests_prefix) else ""
        return value

    def tracer(frame, event, arg):
        functions = state["functions"]
        if event == "call" and functions is not None:
            code = frame.f_code
            rel = relative(code.co_filename)
            if rel and not code.co_name.startswith("<"):
                functions.add((rel, getattr(code, "co_qualname", code.co_name), code.co_firstlineno))
        return None

    def audit(event, args):
        files = state["files"]
        if files is None or state["busy"] or event != "open" or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        state["busy"] = True
        try:
            rel = relative(os.path.abspath(os.fsdecode(args[0])))
            if rel:
                files.add(rel)
        finally:
            state["busy"] = False

    coverage = bool(request.get("coverage"))
    if coverage:
        sys.addaudithook(audit)
    outcomes, details, covered, order = {}, {}, {}, []

    def describe(err):
        kind, value, tb = err
        frames = []
        for frame in traceback.extract_tb(tb):
            real = os.path.realpath(frame.filename)
            if real.startswith(source_prefix):
                frames.append([os.path.relpath(real, root), frame.lineno, frame.name])
        return {"type": kind.__name__, "message": str(value)[:300], "frames": frames[-12:]}

    class Result(unittest.TestResult):
        def startTest(self, test):
            super().startTest(test)
            order.append(test.id())
            if coverage:
                state["functions"], state["files"] = set(), set()
                threading.settrace(tracer)
                sys.settrace(tracer)

        def stopTest(self, test):
            if coverage:
                sys.settrace(None)
                threading.settrace(None)
                covered[test.id()] = {"functions": sorted(list(item) for item in state["functions"]), "files": sorted(state["files"])}
                state["functions"] = state["files"] = None
            super().stopTest(test)

        def addSuccess(self, test):
            outcomes.setdefault(test.id(), "passed")

        def addFailure(self, test, err):
            outcomes[test.id()] = "failed"
            details[test.id()] = describe(err)

        def addError(self, test, err):
            outcomes[test.id()] = "error"
            details[test.id()] = describe(err)

        def addSkip(self, test, reason):
            outcomes[test.id()] = "skipped"

        def addExpectedFailure(self, test, err):
            outcomes[test.id()] = "expected-failure"

        def addUnexpectedSuccess(self, test):
            outcomes[test.id()] = "unexpected-success"

        def addSubTest(self, test, subtest, err):
            if err is not None:
                key = test.id()
                if outcomes.get(key) != "error":
                    outcomes[key] = "failed" if issubclass(err[0], test.failureException) else "error"
                details.setdefault(key, describe(err))

    loader = unittest.TestLoader()
    suite = loader.discover(start, pattern=request["pattern"], top_level_dir=start)
    flat = []

    def flatten(item):
        for test in item:
            if isinstance(test, unittest.TestSuite):
                flatten(test)
            else:
                flat.append(test)

    flatten(suite)
    if request.get("only") is not None:
        wanted = set(request["only"])
        flat = [test for test in flat if test.id() in wanted]
    unittest.TestSuite(flat).run(Result())
    return {"tests": outcomes, "order": order, "details": details, "coverage": covered,
            "loader_errors": [str(error)[:300] for error in loader.errors][:20]}


def _callable(request):
    import importlib
    target = importlib.import_module(request["module"])
    for part in request["function"].split("."):
        target = getattr(target, part)
    return target


def _memory(request, root):
    import gc, tracemalloc
    function, args, calls = _callable(request), request.get("args", []), request["calls"]
    for _ in range(max(1, calls // 10)):
        function(*args)
    gc.collect()
    tracemalloc.start(5)
    before = tracemalloc.take_snapshot()
    samples = []
    for _ in range(4):
        for _ in range(calls):
            function(*args)
        gc.collect()
        samples.append(tracemalloc.get_traced_memory()[0])
    after = tracemalloc.take_snapshot()
    top = []
    for stat in after.compare_to(before, "lineno")[:30]:
        real = os.path.realpath(stat.traceback[0].filename)
        if real.startswith(root + os.sep) and stat.size_diff > 0:
            top.append([os.path.relpath(real, root), stat.traceback[0].lineno, stat.size_diff, stat.count_diff])
    tracemalloc.stop()
    return {"samples_bytes": samples, "top": top[:5]}


def _timing(request, root):
    import statistics, time
    function, args, number = _callable(request), request.get("args", []), request["number"]
    for _ in range(number):
        function(*args)
    samples = []
    for _ in range(request["repeats"]):
        start = time.perf_counter()
        for _ in range(number):
            function(*args)
        samples.append((time.perf_counter() - start) * 1000.0 / number)
    return {"samples_ms": samples, "median_ms": statistics.median(samples)}


def _serve(request, root):
    import runpy
    script = os.path.join(root, request["script"])
    sys.path.insert(0, os.path.dirname(script))
    sys.argv = [script] + list(request["argv"])
    runpy.run_path(script, run_name="__main__")


def _main():
    request = json.loads(sys.argv[1])
    root = os.path.realpath(request["root"])
    _guard()
    os.chdir(root)
    sys.path.insert(0, root)
    if request["mode"] == "serve":
        _serve(request, root)
        return
    result = {"tests": _tests, "memory": _memory, "timing": _timing}[request["mode"]](request, root)
    with open(request["out"], "w", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True)


_main()
'''


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def http_call(port, method, target, *, body=None, timeout=5):
    """One loopback HTTP request; returns (status, content_type, bytes)."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        connection.request(method, target, body=payload, headers={"Content-Type": "application/json"} if payload else {})
        response = connection.getresponse()
        data = response.read(MAX_FILE_BYTES + 1)
        return response.status, response.getheader("Content-Type", ""), data[:MAX_FILE_BYTES]
    finally:
        connection.close()


def _stop(process):
    if process.poll() is None:
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


class Sandbox:
    """Run target code in a child process with a fixed driver (never a shell).

    Environment: PATH plus private HOME/TMPDIR, fixed hash seed, no proxies, no
    user site-packages, no bytecode writes. Sockets may only reach loopback
    addresses (Python-level guard, not an OS sandbox). Every run has a timeout and
    its process group is killed when it expires.
    """

    def __init__(self, scratch, *, timeout=60):
        self.scratch = pathlib.Path(scratch).resolve()
        for name in ("home", "tmp", "results"):
            (self.scratch / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.timeout = _number(timeout, 1, 900, "sandbox timeout")
        self.counter = 0

    def env(self):
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.scratch / "home"), "TMPDIR": str(self.scratch / "tmp"),
                "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1",
                "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "NO_PROXY": "*", "no_proxy": "*"}

    def _next(self, label):
        self.counter += 1
        return self.scratch / "results" / f"{self.counter:04d}-{label}"

    def command(self, request):
        return [sys.executable, "-s", "-B", "-c", DRIVER, json.dumps(request, sort_keys=True)]

    def run(self, root, request, *, timeout=None, label="run"):
        """Run one driver mode; returns its JSON result plus ``status`` (ok/timeout/crashed)."""
        base = self._next(label)
        out, log = base.with_suffix(".json"), base.with_suffix(".log")
        request = {**request, "root": str(pathlib.Path(root).resolve()), "out": str(out)}
        with log.open("wb") as stream:
            process = subprocess.Popen(self.command(request), cwd=str(root), env=self.env(), stdin=subprocess.DEVNULL,
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=timeout or self.timeout)
            except subprocess.TimeoutExpired:
                _stop(process)
                return {"status": "timeout", "exit_code": None, "log_tail": ""}
            finally:
                _stop(process)
        tail = _redact(log.read_bytes()[-2000:].decode("utf-8", "replace"))
        if not out.is_file() or out.stat().st_size > MAX_RESULT_BYTES:
            return {"status": "crashed", "exit_code": code, "log_tail": tail}
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return {"status": "crashed", "exit_code": code, "log_tail": tail}
        data.update(status="ok", exit_code=code, log_tail=tail)
        return data

    def run_tests(self, root, start, pattern, *, only=None, coverage=False, timeout=None):
        request = {"mode": "tests", "start": start, "pattern": pattern, "coverage": coverage, "only": None if only is None else sorted(only)}
        return self.run(root, request, timeout=timeout, label="tests")

    @contextlib.contextmanager
    def app(self, root, script, args, *, ready_path="/", timeout=10):
        """Start the target app on a free loopback port; yields {port, ready, exit_code, log_tail}."""
        port, base = _free_port(), self._next("app")
        argv = [arg.replace("{port}", str(port)).replace("{db}", str(base.with_suffix(".db"))) for arg in args]
        request = {"mode": "serve", "script": script, "argv": argv, "root": str(pathlib.Path(root).resolve()), "out": ""}
        log = base.with_suffix(".log")
        with log.open("wb") as stream:
            process = subprocess.Popen(self.command(request), cwd=str(root), env=self.env(), stdin=subprocess.DEVNULL,
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                ready, deadline = False, time.monotonic() + timeout
                while not ready and time.monotonic() < deadline and process.poll() is None:
                    try:
                        http_call(port, "GET", ready_path, timeout=1)
                        ready = True
                    except OSError:
                        time.sleep(0.05)
                info = {"port": port, "ready": ready, "exit_code": process.poll(), "log_tail": ""}
                if not ready:
                    _stop(process)
                    info.update(exit_code=process.poll(), log_tail=_redact(log.read_bytes()[-2000:].decode("utf-8", "replace")))
                yield info
            finally:
                _stop(process)


@contextlib.contextmanager
def _sandbox(sandbox, timeout=60):
    if sandbox is not None:
        yield sandbox
        return
    with tempfile.TemporaryDirectory(prefix="gaie-detect-") as scratch:
        yield Sandbox(scratch, timeout=timeout)


# --------------------------------------------------------------------------- runtime detectors

def load_contracts(root, rel):
    data = _obj(_load_json(root, rel), {"schema_version", "contracts"}, (), "contracts")
    _need(data["schema_version"] == 1 and type(data["schema_version"]) is int, "contracts: unknown schema_version")
    _need(isinstance(data["contracts"], list) and len(data["contracts"]) <= 100, "contracts: bounded list")
    for contract in data["contracts"]:
        _obj(contract, {"id", "consumer", "interactions"}, (), "contract")
        _need(isinstance(contract["id"], str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", contract["id"]), "contract.id: slug")
        _need(isinstance(contract["consumer"], str) and 0 < len(contract["consumer"]) <= 80, "contract.consumer")
        _need(isinstance(contract["interactions"], list) and 0 < len(contract["interactions"]) <= 50, "contract.interactions")
        for row in contract["interactions"]:
            _obj(row, {"request", "response"}, (), "interaction")
            request = _obj(row["request"], {"method", "path"}, {"body"}, "interaction.request")
            _need(request["method"] in METHODS and PROBE_PATH.fullmatch(request["path"]) is not None, "interaction.request: method/path")
            response = _obj(row["response"], {"status"}, {"shape", "json"}, "interaction.response")
            _int(response["status"], 100, 599, "interaction.response.status")
            _shape(response.get("shape", {}))
    return data


def _probe(port, method, target, expected_status, kind, shape, body=None, exact=None):
    try:
        status, content_type, data = http_call(port, method, target, body=body)
    except OSError as error:
        return {"error": type(error).__name__}
    problems, value = [], None
    if status != expected_status:
        problems.append(f"status:{status}")
    if kind == "json" or shape or exact is not None:
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            problems.append("body-not-json")
        else:
            problems += shape_mismatches(value, shape or {})
            if exact is not None and value != exact:
                problems.append("json-mismatch")
    elif kind == "html" and "html" not in content_type:
        problems.append("content-type")
    return {"status": status, "problems": problems}


def detect_http(root, files=None, manifest=None, *, sandbox=None, only_routes=None):
    """Start the app and probe declared routes (broken APIs) and consumer contracts (integrations)."""
    root, manifest = pathlib.Path(root).resolve(), manifest or {}
    files = list_files(root) if files is None else files
    app = manifest.get("app")
    if app is None:
        reason = "no app declared in healing.json"
        return (_report("broken-apis", "not-configured", reason=reason, method="loopback-http"),
                _report("integrations", "not-configured", reason=reason, method="contract-runner"))
    spec = load_route_spec(root, manifest["route_spec"]) if manifest.get("route_spec") else None
    probes = []
    if spec is not None:
        for row in spec["routes"]:
            if row["method"] == "GET" and (only_routes is None or row["path"] in only_routes):
                response = row["response"]
                probes.append((row["path"], row.get("probe", row["path"]), response.get("status", 200), response.get("type", "json"), response.get("shape", {})))
    else:
        source = read_text(root, app.get("routes_module", app["script"])) or ""
        for row in route_table(source, app.get("routes_variable", "ROUTES"))[1]:
            if row["method"] == "GET" and ROUTE_PATH.fullmatch(row["path"]) and (only_routes is None or row["path"] in only_routes):
                probes.append((row["path"], row["path"], None, "any", {}))
    contracts = load_contracts(root, manifest["contracts"]) if manifest.get("contracts") and only_routes is None else None
    api, integration = [], []
    with _sandbox(sandbox) as box, box.app(root, app["script"], app.get("args", []), ready_path=app.get("ready_path", "/"),
                                           timeout=app.get("startup_timeout_s", 10)) as server:
        if not server["ready"]:
            evidence = {"exit_code": server["exit_code"], "log_tail": server["log_tail"]}
            failed = finding("broken-apis", "app-start-failed", app["script"], None, app["script"], evidence, "critical")
            return (_report("broken-apis", "ran", [failed], method="loopback-http"),
                    _report("integrations", "skipped", reason="app did not start", method="contract-runner"))
        for path, target, status, kind, shape in probes:
            result = _probe(server["port"], "GET", target, status if status is not None else 200, kind, shape)
            if "error" in result:
                api.append(finding("broken-apis", "api-unreachable", app["script"], None, f"GET {path}", {"route": path, "error": result["error"]}, "high"))
            elif status is None and result["status"] < 500:
                continue
            elif result["status"] >= 500:
                api.append(finding("broken-apis", "api-error-status", app["script"], None, f"GET {path}", {"route": path, "status": result["status"], "expected_status": status}, "high"))
            elif result["problems"]:
                kind_name = "api-status-mismatch" if any(p.startswith("status:") for p in result["problems"]) else "api-shape-mismatch"
                api.append(finding("broken-apis", kind_name, app["script"], None, f"GET {path}", {"route": path, "status": result["status"], "problems": result["problems"]}, "medium"))
        for contract in (contracts or {"contracts": []})["contracts"]:
            for index, row in enumerate(contract["interactions"]):
                request, response = row["request"], row["response"]
                result = _probe(server["port"], request["method"], request["path"], response["status"], "json" if "shape" in response or "json" in response else "any",
                                response.get("shape", {}), body=request.get("body"), exact=response.get("json"))
                problems = [result["error"]] if "error" in result else result["problems"]
                if problems:
                    integration.append(finding("integrations", "contract-failed", manifest["contracts"], None, f"{contract['id']}#{index}",
                                               {"contract": contract["id"], "consumer": contract["consumer"], "interaction": index,
                                                "route": request["path"].split("?")[0], "expected_status": response["status"],
                                                "status": result.get("status"), "problems": problems}, "high"))
    integration_report = (_report("integrations", "not-configured", reason="no contracts declared", method="contract-runner") if contracts is None
                          else _report("integrations", "ran", integration, method="contract-runner (loopback http)",
                                       extra={"interactions": sum(len(c["interactions"]) for c in contracts["contracts"])}))
    return _report("broken-apis", "ran", api, method="loopback-http", extra={"probes": len(probes)}), integration_report


def detect_memory(root, manifest=None, *, sandbox=None):
    """tracemalloc growth across repeated calls of declared functions (child process)."""
    root, manifest = pathlib.Path(root).resolve(), manifest or {}
    checks = manifest.get("memory")
    if not checks:
        return _report("memory", "not-configured", reason="no memory checks declared", method="tracemalloc")
    out, measured = [], []
    with _sandbox(sandbox) as box:
        for row in checks:
            result = box.run(root, {"mode": "memory", "module": row["module"], "function": row["function"], "args": row.get("args", []), "calls": row["calls"]}, label="memory")
            symbol = f"{row['module']}:{row['function']}"
            if result["status"] != "ok":
                out.append(finding("memory", "memory-check-failed", row["module"].replace(".", "/") + ".py", None, symbol, {"status": result["status"], "log_tail": result.get("log_tail", "")}, "medium"))
                continue
            samples = result["samples_bytes"]
            deltas = [b - a for a, b in zip(samples, samples[1:])]
            growth = samples[-1] - samples[0]
            measured.append({"function": symbol, "growth_bytes": growth, "calls_per_round": row["calls"]})
            if growth >= row["threshold_bytes"] and all(delta > 0 for delta in deltas):
                top = result["top"][0] if result["top"] else [row["module"].replace(".", "/") + ".py", None, growth, 0]
                out.append(finding("memory", "memory-growth", top[0], top[1], symbol,
                                   {"growth_bytes": growth, "round_deltas": deltas, "calls_per_round": row["calls"], "threshold_bytes": row["threshold_bytes"], "top_sites": result["top"]}, "high"))
    return _report("memory", "ran", out, method="tracemalloc (measured in a child process)", extra={"measured": measured})


def detect_performance(root, manifest=None, *, sandbox=None):
    """Median wall-clock time per call vs a stored baseline with tolerance (measured, noisy)."""
    root, manifest = pathlib.Path(root).resolve(), manifest or {}
    config = manifest.get("performance")
    if not config:
        return _report("performance", "not-configured", reason="no performance baseline declared", method="perf_counter")
    data = _obj(_load_json(root, config["baseline"]), {"schema_version", "functions"}, {"note"}, "performance baseline")
    _need(isinstance(data["functions"], dict) and len(data["functions"]) <= 50, "performance baseline: functions")
    out, measured = [], []
    with _sandbox(sandbox) as box:
        for symbol, row in sorted(data["functions"].items()):
            _need(isinstance(symbol, str) and re.fullmatch(r"[A-Za-z_][\w.]*:[A-Za-z_][\w.]*", symbol), "performance: module:function key")
            _obj(row, {"median_ms", "tolerance"}, {"args", "repeats", "number"}, "performance entry")
            baseline = _number(row["median_ms"], 1e-6, 1e6, "median_ms")
            tolerance = _number(row["tolerance"], 1, 1000, "tolerance")
            module, function = symbol.split(":")
            _callable_spec({"module": module, "function": function, "args": row.get("args", [])}, (), "performance")
            result = box.run(root, {"mode": "timing", "module": module, "function": function, "args": row.get("args", []),
                                    "repeats": _int(row.get("repeats", 5), 3, 50, "repeats"), "number": _int(row.get("number", 100), 1, 100000, "number")}, label="timing")
            path = module.replace(".", "/") + ".py"
            if result["status"] != "ok":
                out.append(finding("performance", "performance-check-failed", path, None, symbol, {"status": result["status"], "log_tail": result.get("log_tail", "")}, "medium"))
                continue
            ratio = result["median_ms"] / baseline
            measured.append({"function": symbol, "median_ms": result["median_ms"], "baseline_ms": baseline, "ratio": ratio})
            if ratio > tolerance:
                out.append(finding("performance", "performance-regression", path, None, symbol,
                                   {"median_ms": result["median_ms"], "baseline_ms": baseline, "ratio": ratio, "tolerance": tolerance, "samples_ms": result["samples_ms"]}, "medium"))
    return _report("performance", "ran", out, method="perf_counter median (measured wall clock, not deterministic)", extra={"measured": measured})


# --------------------------------------------------------------------------- orchestration

def run_all(root, manifest=None, *, tests_dir=None, runtime=False, sandbox=None, ffprobe="auto", only=None, security_baseline=None):
    """Run every detector; runtime ones only when ``runtime=True`` (execute target code)."""
    root = pathlib.Path(root).resolve()
    manifest = load_manifest(root) if manifest is None else validate_manifest(manifest, root)
    files = list_files(root)
    wanted = set(DETECTORS if only is None else only)
    _need(wanted <= set(DETECTORS), "Unknown detector")
    baseline = security_baseline
    if baseline is None and manifest.get("security_baseline"):
        baseline = _load_json(root, manifest["security_baseline"])
        _need(isinstance(baseline, list) and all(isinstance(item, str) for item in baseline), "security baseline: list of fingerprints")
    spec_queries = []
    if manifest.get("route_spec"):
        for row in load_route_spec(root, manifest["route_spec"])["routes"]:
            query = row.get("implementation", {}).get("query")
            if isinstance(query, str):
                spec_queries.append((manifest["route_spec"], None, query))
    reports = {}
    static = {
        "broken-routes": lambda: detect_broken_routes(root, files, manifest),
        "dead-code": lambda: detect_dead_code(root, files, tests_dir=tests_dir, entrypoints=manifest.get("entrypoints", ())),
        "duplicates": lambda: detect_duplicates(root, files, tests_dir=tests_dir),
        "dependencies": lambda: detect_dependencies(root, files, manifest),
        "security": lambda: detect_security(root, files, baseline=baseline),
        "database": lambda: detect_database(root, files, manifest, tests_dir=tests_dir, extra_queries=spec_queries),
        "media": lambda: detect_media(root, files, ffprobe=ffprobe),
    }
    for name, run in static.items():
        if name in wanted:
            reports[name] = _guarded(name, run)
    skipped = "runtime detectors execute target code; pass runtime=True on a disposable copy"
    with _sandbox(sandbox) as box:
        if wanted & {"broken-apis", "integrations"}:
            if runtime:
                pair = _guarded("broken-apis", lambda: detect_http(root, files, manifest, sandbox=box))
                if isinstance(pair, tuple):
                    reports["broken-apis"], reports["integrations"] = pair
                else:
                    reports["broken-apis"], reports["integrations"] = pair, _report("integrations", "error", reason=pair["reason"])
            else:
                for name in ("broken-apis", "integrations"):
                    reports[name] = _report(name, "skipped", reason=skipped)
        for name, run in (("memory", lambda: detect_memory(root, manifest, sandbox=box)), ("performance", lambda: detect_performance(root, manifest, sandbox=box))):
            if name in wanted:
                reports[name] = _guarded(name, run) if runtime else _report(name, "skipped", reason=skipped)
    ordered = [reports[name] for name in DETECTORS if name in reports]
    findings = sorted((row for report in ordered for row in report["findings"]), key=lambda row: (DETECTORS.index(row["detector"]), row["id"]))
    return {"detectors": ordered, "findings": findings, "runtime_executed": bool(runtime),
            "counts": {severity: sum(1 for row in findings if row["severity"] == severity) for severity in SEVERITIES}}


def _guarded(name, run):
    try:
        return run()
    except DetectorError:
        raise
    except Exception as error:  # a detector bug is reported, never read as a pass
        return _report(name, "error", reason=type(error).__name__)
