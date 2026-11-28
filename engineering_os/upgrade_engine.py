"""Master Upgrade Engine (GAIE L16 with L06 and L17): upgrade an EXISTING system, never from scratch, never in place.

``upgrade(target, *, command, workdir)`` runs ROUTE -> BASELINE -> AUDIT -> PLAN -> APPLY ->
REGRESSION -> REPORT and reuses the hub's engines instead of duplicating them: the master
router (``gaie_router``) classifies the Arabic or English command, ``gaie_inventory`` maps the
components, ``detectors.run_all`` finds defects and ``healing.heal`` repairs them,
``requirements`` supplies the system's specification and the requested changes, ``reasoning``
orders the plan (``decompose``), chooses between alternatives (``trade_off``) and accepts or
rejects the result (``validate_decision``), ``memory`` keeps stage checkpoints and the ADR, and
``economics`` types the usage figures.

Every change happens in a copy of the target inside ``workdir``; the target is never written
(its SHA-256 snapshot is compared before and after). The target's own test suite runs in
disposable copies through ``detectors.Sandbox`` (child process, fixed driver, loopback-only
socket guard; not an OS sandbox). A step is kept only when every test that passed at baseline
still passes, its new tests fail before it and pass after it, every pre-existing table keeps its
rows (count and SHA-256 over the original columns) and nothing is deleted without proof of
non-use and a recoverable backup; otherwise it is rolled back and the rollback is verified.
Audit mode («افحص») reads only and writes nothing, not even ``workdir``. Production,
deployment, network access and building from scratch are refused. No model, provider or
shell is used. SPDX-License-Identifier: MIT
"""

import ast
import datetime
import difflib
import fnmatch
import hashlib
import html
import html.parser
import pathlib
import pprint
import re
import shutil
import sqlite3
import tempfile
import time
import urllib.parse

from . import detectors, economics, gaie_inventory, gaie_router, healing, reasoning, requirements, workspace_policy
from .memory import MemoryError as _MemoryError, MemoryStore
from .orchestration import SLUG, CoordinationError, canonical, sha

VERSION = 1
ENGINE = "master-upgrade-engine"
LAYERS = ("L16", "L06", "L17")
STAGES = ("ROUTE", "BASELINE", "AUDIT", "PLAN", "APPLY", "REGRESSION", "REPORT")
AREAS = ("code", "architecture", "database", "performance", "security", "ui", "assets", "tests", "docs")
MANIFEST = "gaie-upgrade.json"
SPEC_FILE = "gaie-spec.json"
POLICY = {"network": False, "deploy": False, "environment": "isolated-copy", "test_timeout_s": 120, "max_steps": 24,
          "asset_backup": True}
FOCUS_AREAS = {"performance": {"performance", "database"}, "database": {"database", "performance"}, "security": {"security"},
               "interface": {"ui"}, "defects": {"code"}, "ai": set(), "media": set(), "motion": set()}
INTENT_AREAS = {"accelerate": {"performance", "database"}, "repair": {"code"}}
PRODUCTION_WORDS = frozenset({"production", "prod", "انتاج", "الانتاج", "للانتاج", "بالانتاج", "والانتاج"})
ASSET_SUFFIXES = frozenset(gaie_inventory.EXT["image"] | gaie_inventory.EXT["video"] | gaie_inventory.EXT["audio"]
                           | gaie_inventory.EXT["model3d"] | gaie_inventory.EXT["style"] | {".woff", ".woff2", ".ttf", ".otf"})
SCAN_SUFFIXES = frozenset(detectors.TEXT_SUFFIXES | {".css", ".scss", ".sass", ".less", ".svg", ".md", ".jsx", ".tsx", ".vue",
                                                     ".svelte", ".xml", ".webmanifest"})
SQLITE_MAGIC = b"SQLite format 3\x00"
PASSING = healing.PASSING
CONTROLS = frozenset({"input", "select", "textarea"})
UNLABELLED_INPUTS = frozenset({"hidden", "submit", "button", "reset", "image"})
STEP_COST = {"code": (30, .4, .3, .7), "architecture": (20, .4, .3, .7), "database": (15, .3, .2, .85),
             "performance": (15, .3, .2, .85), "security": (20, .3, .2, .8), "ui": (15, .2, .2, .85), "assets": (5, .2, .1, .9),
             "tests": (10, .2, .2, .85), "docs": (5, .05, .05, .95)}
MIGRATION_ALLOWED = (
    ("create-index", re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?[\w\"]+\s+ON\s+[\w\"]+\s*\([\w\s\",]+\)", re.I | re.S)),
    ("drop-index", re.compile(r"DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?[\w\"]+", re.I)),
    ("create-table", re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\w\"]+\s*\(.*\)", re.I | re.S)),
    ("create-view", re.compile(r"CREATE\s+VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?[\w\"]+\s+AS\s+SELECT\b.*", re.I | re.S)),
    ("drop-view", re.compile(r"DROP\s+VIEW\s+(?:IF\s+EXISTS\s+)?[\w\"]+", re.I)),
    ("add-column", re.compile(r"ALTER\s+TABLE\s+[\w\"]+\s+ADD\s+(?:COLUMN\s+)?[\w\"]+\b.*", re.I | re.S)),
    ("user-version", re.compile(r"PRAGMA\s+user_version\s*=\s*\d{1,9}", re.I)),
)
MIGRATION_REFUSED = (
    (re.compile(r"^DROP\s+TABLE\b", re.I), "drops a table and its rows"),
    (re.compile(r"^DELETE\b", re.I), "deletes rows"),
    (re.compile(r"^(?:UPDATE|REPLACE|INSERT|UPSERT)\b", re.I), "rewrites or adds rows; data changes are not schema migrations"),
    (re.compile(r"^ALTER\s+TABLE\b.*\b(?:DROP|RENAME)\b", re.I | re.S), "drops or renames a table or column"),
    (re.compile(r"^(?:VACUUM|REINDEX|ATTACH|DETACH)\b", re.I), "rewrites the file or reaches another database"),
    (re.compile(r"^PRAGMA\b", re.I), "only PRAGMA user_version may change"),
    (re.compile(r"^CREATE\s+(?:TEMP\w*\s+)?TRIGGER\b", re.I), "a trigger changes future writes"),
)
RTL_LANGUAGES = ("ar", "fa", "he", "ur")
NFR_TRACE = (("input validation", "step", "security-input-validation"), ("index", "step", "performance-query-indexes"),
             ("label", "step", "ui-accessibility-rtl"), ("rtl", "step", "ui-accessibility-rtl"), ("ltr", "step", "ui-accessibility-rtl"),
             ("secret", "detector", "security"))
_ARABIC = re.compile("[ء-ي]")
_LATIN = re.compile("[A-Za-z]")
_ZERO = "0" * 64
_NO_SANDBOX = object()  # passed to detectors.run_all with runtime=False: no sandbox (and no temp dir) is ever created


class UpgradeError(ValueError):
    """The upgrade was refused or its declared inputs are malformed; the target was never changed."""


class _NotApplicable(Exception):
    """A step generator found nothing it can change safely (the reason is reported)."""


def _need(condition, message):
    if not condition:
        raise UpgradeError(message)


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _finite(value):
    _need(not isinstance(value, bool) and isinstance(value, (int, float)) and 0 <= value < 1e11, "now must be epoch seconds")
    return float(value)


def _slugify(text, limit=60):
    value = re.sub(r"[^a-z0-9]+", "-", str(text).casefold()).strip("-")[:limit].strip("-")
    return value if value and SLUG.fullmatch(value) else "system"


def _passed(outcome):
    return outcome in PASSING


def _under(rel, directory):
    return bool(directory) and (rel == directory or rel.startswith(directory.rstrip("/") + "/"))


def _text_of(data):
    if data is None or b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# --------------------------------------------------------------------------- ROUTE

def _policy(policy):
    merged = dict(POLICY)
    if policy is not None:
        _need(isinstance(policy, dict) and set(policy) <= set(POLICY), "Unknown policy field")
        merged.update(policy)
    _need(merged["network"] is False, "Network access refused: upgrades run offline in an isolated copy")
    _need(merged["deploy"] is False, "Deployment refused: the upgrade engine never deploys; a release needs the owner's approval")
    _need(merged["environment"] == "isolated-copy", "Production or in-place upgrade refused: only an isolated copy is ever upgraded")
    for key, (low, high) in (("test_timeout_s", (1, 900)), ("max_steps", (1, 64))):
        _need(type(merged[key]) is int and low <= merged[key] <= high, f"{key} must be an integer in {low}..{high}")
    _need(type(merged["asset_backup"]) is bool, "asset_backup must be a boolean")
    return merged


def _verified_checkout(plan, workspace):
    """True when ``workspace`` is the verified isolated checkout of the one registered project a routed plan names.

    The router validates the workspace of a writing intent itself (``workspace_matches``: a clean, private linked
    worktree of the registered repository on an isolated branch). An audit plan carries no workspace verdict, so
    the same read-only validator confirms the checkout's identity here; a dirty tree is acceptable to a reader.
    """
    targets = plan.get("targets") or []
    if len(targets) != 1:
        return False
    if plan.get("intent") != "audit":
        return targets[0].get("workspace_matches") is True
    try:
        workspace_policy.validate_workspace(workspace, intent="upgrade", expected_repository=targets[0].get("repository"),
                                            registered_path=targets[0].get("path"), require_clean=False)
    except workspace_policy.WorkspacePolicyError:
        return False
    return True


def _near_misses(command, environ):
    """Registered projects that a word of the command resembles (a typo, a look-alike letter, a split or a
    shortened name), by the router's own matching. The router's command and focus words are left out:
    "upgrade the security of ..." names a focus, not the "security-lab" project."""
    rules = gaie_router.policy()
    words = [*(w for group in rules["verbs"].values() for w in group), *(w for group in rules["focus"].values() for w in group),
             *(w for key in ("negations", "all_projects", "new_system", "fillers", "coordinators", "clause_breaks",
                             "noun_followers") for w in rules[key])]
    vocabulary = {token for word in words for token in gaie_router.normalize(word)}
    matched, suggestions = gaie_router.resolve([t for t in gaie_router.normalize(command) if t not in vocabulary],
                                               gaie_router.projects(environ))
    return sorted({row["id"] for row in matched} | set(suggestions))


def _registered_origin(workspace, environ):
    """The registered project whose repository is a Git remote of ``workspace`` (read with the hardened Git of
    workspace_policy), whatever the command says; None outside any Git checkout or for unregistered remotes."""
    path = pathlib.Path(workspace).absolute()
    try:
        in_git = any(workspace_policy._git_checkout_marker(directory) or workspace_policy._bare_repository(directory)
                     for directory in (path, *path.parents))
        remotes = workspace_policy._git(path, "remote", "-v") if in_git else ""
    except (OSError, workspace_policy.WorkspacePolicyError):
        raise UpgradeError("The target's Git remotes cannot be read, so its project cannot be ruled out; refused") from None
    ids = {workspace_policy._repo_id(line.split("\t", 1)[1].rsplit(" (", 1)[0]) for line in remotes.splitlines() if "\t" in line}
    owners = [row for row in gaie_router.projects(environ).values() if row.get("slug") and row["slug"] in ids]
    _need(len(owners) <= 1, "The target's Git remotes belong to several registered projects; refused")
    return owners[0] if owners else None


def _verified_origin_checkout(row, workspace, intent):
    """True when ``workspace`` is the verified linked worktree of registered ``row`` (a reader may be dirty)."""
    try:
        workspace_policy.validate_workspace(workspace, intent="upgrade" if intent == "audit" else intent,
                                            expected_repository=row.get("repository"), registered_path=row.get("path"),
                                            require_clean=intent != "audit")
    except workspace_policy.WorkspacePolicyError:
        return False
    return True


def route_command(command, *, environ=None, workspace=None):
    """Classify an owner command with the master router; refuse what the upgrade engine must never do.

    Returns the mode (``upgrade`` or the read-only ``audit``), scope, focus, the areas a run may
    touch and the router's decision. Raises UpgradeError for build-from-scratch, release or
    deployment, production, media scope, all-project runs and unroutable commands.
    """
    _need(isinstance(command, str) and command.strip() and len(command) <= gaie_router.MAX_TEXT, "command must be 1-2000 characters")
    tokens = gaie_router.normalize(command)
    _need(not any(token in PRODUCTION_WORDS or token.endswith("انتاج") for token in tokens),
          "Production target refused: the upgrade engine works only on an isolated copy and never touches production")
    try:
        plan = gaie_router.route(command, environ=environ, workspace_path=workspace)
        # classify() also returns the negation flags. route() consumes them: no-change or read-only wording next to
        # a mutation verb comes back as a clarification without an intent, refused below as not routable.
        verbs, prohibited, focus, everything = gaie_router.classify(command, gaie_router.policy())[:4]
    except (gaie_router.RouteError, OSError, ValueError) as error:
        raise UpgradeError(f"Router refused the command: {error}") from None
    intent, reason = plan.get("intent"), plan.get("reason", "")
    if "release" in (plan.get("candidates") or []) or intent == "release":
        raise UpgradeError("Deployment refused: the upgrade engine never releases or deploys; a release is a separate, approved step")
    _need(intent is not None, f"Command not routable: {reason}")
    _need(intent != "build", "Building from scratch refused: the Master Upgrade Engine only upgrades an existing system")
    _need(intent != "cinematic", "Media scope refused here: films, voice and music go through skills/gaie-cinematic and the video pipeline")
    _need(not everything, "One explicit target per run: an all-projects upgrade is refused")
    if plan["status"] == "routed":
        project, resolution = plan.get("project"), "registered-project"
        if workspace is not None:
            _need(project is not None, "One explicit target per run: the command names several registered projects")
            _need(_verified_checkout(plan, workspace),
                  f"The command names the registered project {project!r}, but the target is not its verified isolated checkout"
                  + "".join(f" ({blocker})" for blocker in plan.get("blockers") or []))
        focus = plan.get("focus", [])
    else:
        _need("known_projects" in plan, f"Command needs clarification: {reason}")
        near = _near_misses(command, environ) if plan.get("suggestions") else []
        _need(not near, f"The command resembles the registered project {', '.join(map(repr, near))}: name it "
              "exactly and use its verified isolated checkout; a project is never guessed")
        project, resolution = None, "explicit-local-target"
        if workspace is not None:
            owner = _registered_origin(workspace, environ)
            if owner is not None:
                _need(_verified_origin_checkout(owner, workspace, intent),
                      f"The target is a checkout of the registered project {owner['id']!r} but not its verified isolated "
                      "checkout; name the project and use its linked worktree")
                project, resolution = owner["id"], "registered-project-origin"
        focus = [] if len(verbs) > 1 else focus
    mode = "audit" if intent == "audit" else "upgrade"
    if mode == "audit":
        areas, scope = set(AREAS), "read-only"
    elif intent in INTENT_AREAS:
        areas, scope = INTENT_AREAS[intent] | {"tests", "docs"}, {"accelerate": "performance", "repair": "self-healing"}[intent]
    elif focus:
        areas, scope = set().union(*(FOCUS_AREAS.get(name, set()) for name in focus)) | {"tests", "docs"}, "focused"
    else:
        areas, scope = set(AREAS), "comprehensive"
    return {"mode": mode, "intent": intent, "scope": scope, "focus": sorted(focus), "areas": [a for a in AREAS if a in areas],
            "language": "ar" if _ARABIC.search(command) else "en", "project": project, "target_resolution": resolution,
            "prohibited": sorted(prohibited), "router": {"status": plan["status"], "reason": reason or None,
                                                         "engine": plan.get("engine"), "engine_id": plan.get("engine_id"),
                                                         "route_sha256": sha(plan)}}


# --------------------------------------------------------------------------- declared inputs

def _target(target):
    try:
        root = pathlib.Path(target).resolve(strict=True)
    except (OSError, TypeError, RuntimeError):
        raise UpgradeError("Target must be an existing system directory (never built from scratch)") from None
    _need(root.is_dir(), "Target must be an existing system directory (never built from scratch)")
    _need(any(root.iterdir()), "Target is empty: the upgrade engine never builds from scratch")
    return root


def _outside_git(path):
    for ancestor in (path, *path.parents):
        marker = ancestor / ".git"
        _need(not (marker.is_file() or (marker.is_dir() and (marker / "HEAD").exists())),
              "workdir must be outside every Git repository (the upgraded copy and private memory are never committed by accident)")
        _need(not ancestor.is_symlink(), "workdir must not pass through a symlink")


def _workdir(workdir, root):
    try:
        path = pathlib.Path(workdir).absolute()
    except TypeError:
        raise UpgradeError("workdir path required") from None
    resolved = path.resolve()
    _need(resolved != root and root not in resolved.parents, "workdir inside the target would upgrade it in place; refused")
    _outside_git(resolved)
    return resolved


def load_manifest(root):
    """Optional ``gaie-upgrade.json``: tests, spec, app convention, schema, databases, templates and assets."""
    root = pathlib.Path(root)
    if not (root / MANIFEST).exists():
        return {}
    try:
        data = detectors._load_json(root, MANIFEST)
        detectors._obj(data, {"schema_version"}, {"name", "tests", "spec", "app", "schema", "databases", "templates", "assets"}, "manifest")
        _need(data["schema_version"] == 1 and type(data["schema_version"]) is int, "manifest: unknown schema_version")
        if "name" in data:
            _need(isinstance(data["name"], str) and SLUG.fullmatch(data["name"]), "manifest.name: slug")
        if "spec" in data:
            _need(detectors.rel_path(data["spec"], "spec").endswith(".json"), "manifest.spec: JSON file")
        for key in ("schema", "databases", "templates", "assets"):
            if key in data:
                _need(isinstance(data[key], list) and len(data[key]) <= 20, f"manifest.{key}: bounded list")
                for item in data[key]:
                    detectors.rel_path(item, key)
        if "app" in data:
            app = detectors._obj(data["app"], {"module", "dispatch"}, {"routes_variable", "connection"}, "manifest.app")
            name = re.compile(r"[A-Za-z_]\w{0,63}")
            _need(isinstance(app["module"], str) and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*){0,4}", app["module"])
                  and isinstance(app["dispatch"], str) and name.fullmatch(app["dispatch"]), "manifest.app: module and dispatch names")
            _need(isinstance(app.get("routes_variable", "ROUTES"), str) and name.fullmatch(app.get("routes_variable", "ROUTES")),
                  "manifest.app.routes_variable: identifier")
            if "connection" in app:
                conn = detectors._obj(app["connection"], {"module", "connect", "init"}, {"memory"}, "manifest.app.connection")
                _need(all(isinstance(conn[k], str) and name.fullmatch(conn[k]) for k in ("module", "connect", "init")), "manifest.app.connection: names")
                _need(isinstance(conn.get("memory", ":memory:"), str) and len(conn.get("memory", ":memory:")) <= 64, "connection.memory")
    except detectors.DetectorError as error:
        raise UpgradeError(f"Invalid {MANIFEST}: {error}") from None
    return data


def _test_spec(tests, root):
    if tests is None:
        start = root / "tests"
        if start.is_dir() and any(start.glob("test*.py")):
            tests = {"start": "tests", "pattern": "test*.py"}
        else:
            return None
    try:
        return healing._test_spec(tests, root)
    except healing.HealingError as error:
        raise UpgradeError(f"Invalid test suite: {error}") from None


def _load_spec(root, manifest):
    rel = manifest.get("spec") or (SPEC_FILE if (root / SPEC_FILE).is_file() else None)
    if rel is None:
        return None, None
    try:
        spec = detectors._load_json(root, rel)
        requirements.validate_spec(spec)
    except (detectors.DetectorError, requirements.SpecError) as error:
        raise UpgradeError(f"Invalid specification {rel}: {error}") from None
    _need(not spec["open_questions"], f"Specification {rel} still has open questions")
    return rel, spec


def requested_changes(command, spec):
    """What the command asks to change in the existing specification (requirements.parse with base= and diff_specs).

    ``status`` is ``refused-breaking`` when the change would remove an entity, field, relation,
    feature, role or locale or tighten a field (data or function loss); ``unmet`` lists the
    non-breaking structural additions, which the deterministic generators do not implement.
    """
    if spec is None:
        return {"status": "no-specification", "unmet": [],
                "detail": "no gaie-spec.json: requested changes cannot be derived; only audit findings drive the plan"}
    try:
        target = requirements.parse(command, base=spec)
    except requirements.SpecError as error:
        return {"status": "unparsed", "errors": error.errors, "unmet": []}
    if target["open_questions"]:
        return {"status": "open-questions", "open_questions": [q["id"] for q in target["open_questions"]], "unmet": [],
                "detail": "the requested change is not settled; nothing structural is generated"}
    diff = requirements.diff_specs(spec, target)
    unmet = [f"entity {name}" for name in diff["entities"]["added"]]
    unmet += [f"field {change['name']}.{field}" for change in diff["entities"]["changed"] for field in change["fields"]["added"]]
    unmet += [f"feature {fid}" for fid in diff["features"]["added"]] + [f"role {rid}" for rid in diff["roles"]["added"]]
    unmet += [f"relation {row['from']}->{row['to']}" for row in diff["relations"]["added"]]
    unmet += [f"integration {iid}" for iid in diff["integrations"]["added"]]
    structural = {key: diff[key] for key in ("entities", "relations", "features", "roles", "integrations")}
    return {"status": "refused-breaking" if diff["breaking"] else "ok", "breaking": diff["breaking"], "summary": diff["summary"],
            "structural": structural, "spec_sha256": diff["new_sha256"], "unmet": [] if diff["breaking"] else unmet,
            "detail": ("breaking changes would lose data or functions; they need an owner-designed migration and approval" if diff["breaking"] else
                       "structural additions are reported as unmet: their application code is outside the deterministic generators" if unmet else
                       "non-structural: the upgrade raises quality against the existing specification")}


def _extra_steps(steps):
    if steps is None:
        return []
    _need(isinstance(steps, list) and len(steps) <= 16, "extra_steps: list of at most 16 steps")
    out, seen = [], set()
    for step in steps:
        _need(isinstance(step, dict) and {"id", "area", "title", "changes"} <= set(step) <= {"id", "area", "title", "changes", "tests"},
              "extra step: id, area, title, changes (tests optional)")
        _need(isinstance(step["id"], str) and SLUG.fullmatch(step["id"]) and len(step["id"]) <= 60 and step["id"] not in seen,
              "extra step id: unique slug")
        seen.add(step["id"])
        _need(step["area"] in AREAS, f"extra step area: one of {list(AREAS)}")
        _need(isinstance(step["title"], str) and 0 < len(step["title"]) <= 200, "extra step title")
        _need(isinstance(step["changes"], list) and 0 < len(step["changes"]) <= 20, "extra step changes: 1-20")
        for change in step["changes"]:
            _need(isinstance(change, dict) and change.get("op") in ("replace", "add-file", "migration"), "change op: replace, add-file, migration")
            shapes = {"replace": {"op", "path", "old", "new"}, "add-file": {"op", "path", "text"},
                      "migration": {"op", "database", "name", "up", "down"}}
            _need(set(change) == shapes[change["op"]], f"{change['op']} change fields: {sorted(shapes[change['op']])}")
            _need(all(isinstance(v, str) and len(v) <= 200000 for v in change.values()), "change values: bounded text")
            if change["op"] == "migration":
                _need(SLUG.fullmatch(change["name"]) and len(change["name"]) <= 60, "migration name: slug")
        for row in step.get("tests", []):
            _need(isinstance(row, dict) and set(row) == {"path", "text"} and all(isinstance(v, str) for v in row.values()),
                  "extra step tests: [{path, text}]")
        out.append(step)
    return out


# --------------------------------------------------------------------------- data: SQLite manifests and migrations

def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _cell(value):
    if isinstance(value, bytes):
        return {"blob": value.hex()}
    if isinstance(value, float):
        return {"real": repr(value)}
    return value


def _open_ro(path):
    return sqlite3.connect(f"file:{urllib.parse.quote(str(path))}?mode=ro&immutable=1", uri=True)


def _table_checksum(conn, table, columns):
    selected = ", ".join(_quote(c) for c in columns)
    try:
        cursor = conn.execute(f"SELECT {selected} FROM {_quote(table)} ORDER BY rowid")
    except sqlite3.OperationalError:  # WITHOUT ROWID: order by every column
        cursor = conn.execute(f"SELECT {selected} FROM {_quote(table)} ORDER BY " + ", ".join(str(i + 1) for i in range(len(columns))))
    digest, rows = hashlib.sha256(), 0
    for row in cursor:
        digest.update(sha([_cell(v) for v in row]).encode())
        rows += 1
    return rows, digest.hexdigest()


def data_manifest(path, columns=None):
    """Logical manifest of one SQLite file, read-only and immutable: tables (rows, columns, SHA-256), indexes, version.

    ``columns`` restricts each table's checksum to the given columns (the baseline columns),
    so a migration that only adds a column still proves the original data unchanged.
    """
    conn = _open_ro(path)
    try:
        names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        tables = {}
        for name in names:
            present = [row[1] for row in conn.execute(f"PRAGMA table_info({_quote(name)})")]
            wanted = present if columns is None or name not in columns else [c for c in columns[name] if c in present]
            rows, checksum = _table_checksum(conn, name, wanted) if wanted else (conn.execute(f"SELECT COUNT(*) FROM {_quote(name)}").fetchone()[0], None)
            tables[name] = {"rows": rows, "columns": present, "sha256": checksum, "checked_columns": wanted}
        schema = [list(row) for row in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name")]
        return {"tables": tables, "indexes": sorted(row[1] for row in schema if row[0] == "index"),
                "user_version": conn.execute("PRAGMA user_version").fetchone()[0],
                "integrity": conn.execute("PRAGMA quick_check").fetchone()[0], "schema_sha256": sha(schema)}
    finally:
        conn.close()


def data_preserved(before, after_path):
    """Problems (empty when none): every baseline table keeps its rows and the SHA-256 over its baseline columns."""
    after = data_manifest(after_path, {name: row["columns"] for name, row in before["tables"].items()})
    problems = []
    for name, row in sorted(before["tables"].items()):
        now = after["tables"].get(name)
        if now is None:
            problems.append(f"table {name} missing")
        elif set(row["columns"]) - set(now["columns"]):
            problems.append(f"table {name} lost columns {sorted(set(row['columns']) - set(now['columns']))}")
        elif now["rows"] != row["rows"]:
            problems.append(f"table {name}: {row['rows']} rows before, {now['rows']} after")
        elif now["sha256"] != row["sha256"]:
            problems.append(f"table {name}: row checksum changed")
    if after["integrity"] != "ok":
        problems.append("integrity check failed")
    return problems, after


def split_sql(sql):
    """Statements of a migration script with comments removed (sqlite3.complete_statement boundaries)."""
    text = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    text = "\n".join(line.split("--", 1)[0] if "'" not in line.split("--", 1)[0] else line for line in text.splitlines())
    statements, buffer = [], ""
    for piece in text.split(";"):
        buffer += piece + ";"
        if sqlite3.complete_statement(buffer):
            if buffer.strip(" \t\r\n;"):
                statements.append(buffer.strip().rstrip(";").strip())
            buffer = ""
    _need(not buffer.strip(" \t\r\n;"), "migration: incomplete SQL statement")
    return statements


def classify_migration(sql):
    """Statement verdicts for a schema migration; raises UpgradeError when any statement could lose or rewrite data."""
    _need(isinstance(sql, str) and len(sql) <= 100000, "migration SQL: bounded text")
    rows = []
    for statement in split_sql(sql):
        kind = next((name for name, pattern in MIGRATION_ALLOWED if pattern.fullmatch(statement)), None)
        if kind is None:
            reason = next((why for pattern, why in MIGRATION_REFUSED if pattern.search(statement)), "not in the allowed schema-migration statement set")
            raise UpgradeError(f"Migration refused: {statement.split()[0].upper() if statement.split() else 'statement'} {reason}")
        rows.append({"statement": statement, "kind": kind})
    _need(rows, "Migration refused: no statement")
    return rows


def _execute_migration(path, statements):
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for row in statements:
                conn.execute(row["statement"])
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def migrate_database(path, up, down, scratch):
    """Apply ``up`` to a scratch copy of ``path``, prove data preservation and that ``down`` restores the schema.

    Returns ``(migrated bytes, proof)``; the file at ``path`` is never written here. Raises
    UpgradeError when the SQL is refused, fails, or any baseline row is lost or changed.
    """
    statements = classify_migration(up)
    reverse = classify_migration(down) if down and split_sql(down) else []
    scratch = pathlib.Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    work, back = scratch / "up.db", scratch / "down.db"
    shutil.copyfile(path, work)
    before = data_manifest(work)
    try:
        _execute_migration(work, statements)
    except sqlite3.Error as error:
        raise UpgradeError(f"Migration failed and was rolled back: {type(error).__name__}: {str(error)[:200]}") from None
    problems, after = data_preserved(before, work)
    _need(not problems, "Migration refused: it would lose or change data (" + "; ".join(problems) + ")")
    proof = {"before": before, "after": after, "statements": [r["kind"] for r in statements], "data_preserved": True,
             "down_verified": None, "down_statements": [r["kind"] for r in reverse]}
    if reverse:
        shutil.copyfile(work, back)
        try:
            _execute_migration(back, reverse)
        except sqlite3.Error as error:
            raise UpgradeError(f"Down migration failed: {type(error).__name__}: {str(error)[:200]}") from None
        undone_problems, undone = data_preserved(before, back)
        proof["down_verified"] = not undone_problems and undone["schema_sha256"] == before["schema_sha256"] \
            and undone["user_version"] == before["user_version"]
        _need(proof["down_verified"], "Migration refused: the down migration does not restore the original schema and data")
    data = work.read_bytes()
    shutil.rmtree(scratch, ignore_errors=True)
    return data, proof


def sqlite_files(root, files, tests_dir=None):
    out = []
    for rel in files:
        if _under(rel, tests_dir):
            continue
        try:
            with (pathlib.Path(root) / rel).open("rb") as stream:
                if stream.read(16) == SQLITE_MAGIC:
                    out.append(rel)
        except OSError:
            continue
    return out


# --------------------------------------------------------------------------- assets

def asset_files(root, files, manifest, tests_dir):
    dirs = manifest.get("assets")
    return sorted(rel for rel in files if pathlib.PurePosixPath(rel).suffix.casefold() in ASSET_SUFFIXES and not _under(rel, tests_dir)
                  and (dirs is None or any(_under(rel, d) for d in dirs)))


_LISTING = re.compile(r"\b(?:os\.listdir|os\.scandir|os\.walk|glob\.glob|glob\.iglob|\.iterdir\(|\.glob\(|\.rglob\(|readdirSync|readdir\()")


def asset_references(root, rel, files):
    """Static proof of use or non-use of one asset: every text file is scanned for its name and stem.

    ``proof`` is ``no-internal-reference`` only when nothing mentions the file and no source
    lists directories; otherwise ``referenced`` or ``unproven-dynamic-access``. External links
    (bookmarks, other sites) to a served file can never be ruled out statically.
    """
    name = pathlib.PurePosixPath(rel).name
    stem = pathlib.PurePosixPath(rel).stem
    needles = sorted({name, rel, stem} if len(stem) >= 4 else {name, rel})
    hits, scanned, listing = [], 0, []
    for other in files:
        if other == rel:
            continue
        suffix = pathlib.PurePosixPath(other).suffix.casefold()
        if suffix not in SCAN_SUFFIXES and pathlib.PurePosixPath(other).name not in ("Dockerfile", "Makefile"):
            continue
        text = detectors.read_text(root, other)
        if text is None:
            continue
        scanned += 1
        found = sorted(n for n in needles if n in text)
        if found:
            hits.append({"file": other, "needles": found})
        if suffix in (".py", ".js", ".mjs", ".cjs", ".ts") and _LISTING.search(text):
            listing.append(other)
    proof = "referenced" if hits else "unproven-dynamic-access" if listing else "no-internal-reference"
    return {"asset": rel, "proof": proof, "needles": needles, "files_scanned": scanned, "references": hits[:20],
            "directory_listing_sources": listing, "method": "static text scan of every text file (names and stems)"}


# --------------------------------------------------------------------------- UI: accessibility and RTL

class _Markup(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.label_for, self.text, self.label_depth = [], set(), [], 0

    def handle_starttag(self, tag, attrs):
        line, col = self.getpos()
        values = {key: value for key, value in attrs}
        self.tags.append({"tag": tag, "attrs": values, "line": line, "col": col, "raw": self.get_starttag_text(),
                          "in_label": self.label_depth > 0})
        if tag == "label":
            self.label_depth += 1
            if values.get("for"):
                self.label_for.add(values["for"])

    def handle_endtag(self, tag):
        if tag == "label" and self.label_depth:
            self.label_depth -= 1

    def handle_data(self, data):
        self.text.append(data)


def _markup(text):
    parser = _Markup()
    parser.feed(text)
    parser.close()
    return parser


def _labelled(tag, markup):
    attrs = tag["attrs"]
    return bool(tag["in_label"] or attrs.get("aria-label") or attrs.get("aria-labelledby") or attrs.get("id") in markup.label_for)


def _control(tag):
    return tag["tag"] in CONTROLS and not (tag["tag"] == "input" and (tag["attrs"].get("type") or "text").casefold() in UNLABELLED_INPUTS)


def audit_html(root, rel):
    """Accessibility, RTL and responsive findings for one HTML template (static)."""
    text = detectors.read_text(root, rel)
    if text is None:
        return []
    markup = _markup(text)
    out = []
    for tag in markup.tags:
        if tag["tag"] == "html" and not (tag["attrs"].get("lang") and tag["attrs"].get("dir")):
            out.append({"kind": "html-missing-lang-dir", "line": tag["line"], "symbol": "html", "severity": "medium",
                        "evidence": {"lang": tag["attrs"].get("lang"), "dir": tag["attrs"].get("dir")}})
        elif _control(tag) and not _labelled(tag, markup):
            out.append({"kind": "unlabelled-control", "line": tag["line"], "symbol": tag["attrs"].get("name") or tag["attrs"].get("id") or tag["tag"],
                        "severity": "medium", "evidence": {"tag": tag["tag"], "id": tag["attrs"].get("id"), "name": tag["attrs"].get("name")}})
        elif tag["tag"] == "img" and "alt" not in tag["attrs"]:
            out.append({"kind": "image-missing-alt", "line": tag["line"], "symbol": tag["attrs"].get("src") or "img", "severity": "medium",
                        "evidence": {"src": tag["attrs"].get("src"), "repair": "needs owner-written text; never invented"}})
    if any(t["tag"] == "html" for t in markup.tags) and not any(t["tag"] == "meta" and (t["attrs"].get("name") or "").casefold() == "viewport"
                                                              for t in markup.tags):
        out.append({"kind": "missing-viewport", "line": None, "symbol": "meta", "severity": "low", "evidence": {}})
    return [{**row, "path": rel} for row in out]


def _page_language(text, spec):
    visible = " ".join(_markup(text).text)
    if _ARABIC.search(visible):
        return "ar"
    if _LATIN.search(visible):
        return "en"
    return spec["locales"][0] if spec else "en"


def _field_index(spec):
    out = {}
    for entity in (spec or {}).get("entities", []):
        for field in entity["fields"]:
            out.setdefault(field["name"], field)
    return out


def _with_attributes(raw, extra):
    closing = "/>" if raw.endswith("/>") else ">"
    return raw[:-len(closing)].rstrip() + "".join(f' {name}="{html.escape(value)}"' if value is not None else f" {name}"
                                                  for name, value in extra) + closing


def fix_html(text, spec):
    """Deterministic edits: lang/dir on <html>, a viewport meta, labels for unlabelled controls (spec labels),
    required/maxlength from the spec. Returns (new text, changes); images without alt are never invented."""
    markup = _markup(text)
    starts = [0] + [index + 1 for index, char in enumerate(text) if char == "\n"]
    lang = _page_language(text, spec)
    fields = _field_index(spec)
    ids = {t["attrs"].get("id") for t in markup.tags if t["attrs"].get("id")}
    edits, changes = [], []

    def at(tag):
        offset = starts[tag["line"] - 1] + tag["col"]
        if text[offset:offset + len(tag["raw"])] != tag["raw"]:
            raise _NotApplicable("template positions are ambiguous; no edit made")
        return offset

    def indent(offset):
        line_start = text.rfind("\n", 0, offset) + 1
        prefix = text[line_start:offset]
        return prefix if not prefix.strip() else None

    for tag in markup.tags:
        attrs, extra = tag["attrs"], []
        if tag["tag"] == "html":
            if not attrs.get("lang"):
                extra.append(("lang", lang))
            if not attrs.get("dir"):
                effective = (attrs.get("lang") or lang).split("-")[0].casefold()
                extra.append(("dir", "rtl" if effective in RTL_LANGUAGES else "ltr"))
            if extra:
                changes.append({"kind": "html-lang-dir", "added": dict(extra)})
        elif _control(tag):
            name = attrs.get("name")
            field = fields.get(name)
            if not _labelled(tag, markup):
                control_id = attrs.get("id")
                if not control_id and name and name not in ids:
                    control_id = name
                    extra.append(("id", name))
                    ids.add(name)
                if control_id:
                    label = (field or {}).get("label", {}).get(lang) or (name or control_id).replace("_", " ").replace("-", " ").title()
                    offset = at(tag)
                    pad = indent(offset)
                    snippet = f'<label for="{html.escape(control_id)}">{html.escape(label)}</label>' + (f"\n{pad}" if pad is not None else " ")
                    edits.append((offset, offset, snippet))
                    changes.append({"kind": "label-added", "control": control_id, "label": label})
            if field:
                if field["required"] and "default" not in field and "required" not in attrs:
                    extra.append(("required", None))
                if field["type"] in ("text", "email") and "max" in field and tag["tag"] in ("input", "textarea") and "maxlength" not in attrs:
                    extra.append(("maxlength", str(field["max"])))
                if any(k in ("required", "maxlength") for k, _ in extra):
                    changes.append({"kind": "constraints-from-spec", "control": name, "added": [k for k, _ in extra if k in ("required", "maxlength")]})
        if extra:
            offset = at(tag)
            edits.append((offset, offset + len(tag["raw"]), _with_attributes(tag["raw"], extra)))
    if any(t["tag"] == "html" for t in markup.tags) and not any(t["tag"] == "meta" and (t["attrs"].get("name") or "").casefold() == "viewport"
                                                              for t in markup.tags):
        anchor = next((t for t in markup.tags if t["tag"] == "meta" and "charset" in t["attrs"]), None) or \
            next((t for t in markup.tags if t["tag"] == "head"), None)
        if anchor is not None:
            offset = at(anchor) + len(anchor["raw"])
            pad = indent(at(anchor)) or ""
            pad = pad if anchor["tag"] == "meta" else pad + "  "
            edits.append((offset, offset, f'\n{pad}<meta name="viewport" content="width=device-width, initial-scale=1">'))
            changes.append({"kind": "viewport-added"})
    result = text
    for start, end, replacement in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        result = result[:start] + replacement + result[end:]
    return result, changes


# --------------------------------------------------------------------------- performance: query plans and indexes

_WHERE = re.compile(r"\bWHERE\b(.*?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|$)", re.I | re.S)
_ORDER = re.compile(r"\bORDER\s+BY\b(.*?)(?:\bLIMIT\b|$)", re.I | re.S)
_EQUAL = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*=\s*(?:\?\d*|:\w+|@\w+|\$\w+)")
_FROM = re.compile(r"\bFROM\s+([A-Za-z_]\w*)\b", re.I)


def _plan(conn, query):
    return [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + query, detectors._bindings(query))]


def _schema_db(root, schemas):
    conn = sqlite3.connect(":memory:")
    for rel in schemas:
        conn.executescript(detectors.read_text(root, rel) or "")
    return conn


def _index_effect(conn, table, columns, query):
    name = "gaie_probe_index"
    conn.execute(f"CREATE INDEX {name} ON {_quote(table)} (" + ", ".join(_quote(c) for c in columns) + ")")
    try:
        details = _plan(conn, query)
    finally:
        conn.execute(f"DROP INDEX {name}")
    return {"scan_avoided": not any(re.match(rf"SCAN {re.escape(table)}\b(?! USING)", d) for d in details),
            "sort_avoided": not any("TEMP B-TREE" in d for d in details), "plan": details}


def audit_queries(root, files, schemas, tests_dir):
    """Full-table scans in filtered SQL literals, with the index chosen by a reasoning.trade_off over measured plans."""
    if not schemas:
        return []
    try:
        conn = _schema_db(root, schemas)
    except sqlite3.Error:
        return []
    out, seen = [], set()
    try:
        for rel, line, query in detectors.sql_queries(root, files, tests_dir=tests_dir):
            if not re.match(r"\s*(?:SELECT|WITH)\b", query, re.I):
                continue
            try:
                details = _plan(conn, query)
            except (sqlite3.Error, ValueError):
                continue
            scans = [m[1] for m in (re.match(r"SCAN (\w+)$", d) for d in details) if m]
            tables = _FROM.findall(query)
            if not scans or len(set(tables)) != 1 or scans[0] != tables[0]:
                continue
            table = scans[0]
            info = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
            columns = {row[1] for row in info}
            primary = {row[1] for row in info if row[5]}
            where = _WHERE.search(query)
            equal = [c for c in dict.fromkeys(_EQUAL.findall(where[1] if where else "")) if c in columns]
            if not equal:
                continue
            order_text = _ORDER.search(query)
            order = [part.split()[0].strip('"') for part in (order_text[1].split(",") if order_text else []) if part.split()]
            order = [c for c in dict.fromkeys(order) if c in columns and c not in primary and c not in equal]
            options = {"equality-index": equal}
            if order:
                options["composite-index"] = equal + order
            values, effects = {"no-index": {"scan-avoided": 0, "sort-avoided": 0 if any("TEMP B-TREE" in d for d in details) else 1,
                                            "write-overhead": 0}}, {}
            for option, cols in options.items():
                effect = _index_effect(conn, table, cols, query)
                effects[option] = effect
                values[option] = {"scan-avoided": int(effect["scan_avoided"]), "sort-avoided": int(effect["sort_avoided"]),
                                  "write-overhead": len(cols)}
            decision = reasoning.trade_off({
                "schema_version": 1, "decision": _slugify(f"index-{table}-{rel}-{line}", 80),
                "options": sorted(values), "robustness_margin": 0.1, "values": values,
                "criteria": [{"id": "scan-avoided", "weight": 0.5, "direction": "higher"},
                             {"id": "sort-avoided", "weight": 0.3, "direction": "higher"},
                             {"id": "write-overhead", "weight": 0.2, "direction": "lower"}]})
            winner = decision["winner"]
            if winner == "no-index":
                continue
            chosen = options[winner]
            key = (table, tuple(chosen))
            if key in seen:
                continue
            seen.add(key)
            out.append({"kind": "unindexed-filter", "path": rel, "line": line, "symbol": f"{table}({', '.join(equal)})", "severity": "medium",
                        "evidence": {"table": table, "query": query, "plan_before": details, "equality": equal, "order": order,
                                     "chosen": winner, "columns": chosen, "effects": effects,
                                     "trade_off": {"winner": winner, "ranking": decision["ranking"], "totals": decision["totals"],
                                                   "robust": decision["robust"], "receipt": decision["receipt"]}}})
    finally:
        conn.close()
    return out


# --------------------------------------------------------------------------- security: input validation from the spec

def _rejects(handler):
    for node in ast.walk(handler):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple) and node.value.elts:
            first = node.value.elts[0]
            if isinstance(first, ast.Constant) and type(first.value) is int and 400 <= first.value < 500:
                return True
    return False


def _content_type(handler):
    found = []
    for node in ast.walk(handler):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple) and len(node.value.elts) >= 2:
            second = node.value.elts[1]
            if isinstance(second, ast.Constant) and isinstance(second.value, str):
                found.append(second.value)
    return next((c for c in found if "json" in c), found[0] if found else None)


def audit_validation(source, app_rel, manifest, spec):
    """Write routes (POST/PUT/PATCH) of a spec entity whose handler has no 4xx rejection path."""
    app = manifest.get("app")
    if not app or not spec or source is None:
        return []
    tree = detectors._parse(source)
    if tree is None:
        return []
    _, entries = detectors.route_table(source, app.get("routes_variable", "ROUTES"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    plurals = {entity.get("plural") or requirements._snake(entity["name"]) + "s": entity for entity in spec["entities"]}
    out = []
    for row in entries:
        match = re.fullmatch(r"/(?:api/)?([a-z][a-z0-9-]*)", row["path"] or "")
        entity = plurals.get(match[1]) if match else None
        handler = functions.get(row["handler"])
        if row["method"] not in ("POST", "PUT", "PATCH") or entity is None or handler is None or _rejects(handler):
            continue
        names = [a.arg for a in handler.args.args]
        body = next((n for n in ("body", "payload", "data", "form", "params") if n in names), None)
        out.append({"kind": "missing-input-validation", "path": app_rel, "line": handler.lineno, "symbol": f"{row['method']} {row['path']}",
                    "severity": "high", "evidence": {"handler": handler.name, "entity": entity["name"], "method": row["method"],
                                                     "route": row["path"], "body_argument": body, "content_type": _content_type(handler),
                                                     "rule": "spec nfr: input validation on every write endpoint"}})
    return out


VALIDATION_TEMPLATE = '''"""Input validation generated by the GAIE Master Upgrade Engine from {spec} (regenerate, do not edit by hand).

One rule set per entity, derived from the specification fields: required fields, types,
maximum lengths and allowed values. ``validate`` returns a sorted list of problems; an empty
list means the body is valid. Fields that are absent but have a default stay valid.
"""

import datetime
import re

RULES = {rules}
_EMAIL = re.compile(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")


def _problem(value, rule):
    kind = rule["type"]
    if kind in ("text", "email"):
        if not isinstance(value, str) or (rule["required"] and not value.strip()):
            return "must be non-empty text" if rule["required"] else "must be text"
        if "max" in rule and len(value) > rule["max"]:
            return "must be at most %d characters" % rule["max"]
        if "min" in rule and len(value) < rule["min"]:
            return "must be at least %d characters" % rule["min"]
        if kind == "email" and not _EMAIL.match(value):
            return "must be an email address"
    elif kind == "enum":
        if value not in rule["values"]:
            return "must be one of " + ", ".join(rule["values"])
    elif kind in ("int", "number"):
        if isinstance(value, bool) or not isinstance(value, int if kind == "int" else (int, float)):
            return "must be an integer" if kind == "int" else "must be a number"
        if "min" in rule and value < rule["min"] or "max" in rule and value > rule["max"]:
            return "is out of range"
    elif kind == "bool":
        if type(value) is not bool:
            return "must be true or false"
    elif kind in ("date", "datetime"):
        try:
            if kind == "date" and len(value) != 10:
                raise ValueError(value)
            (datetime.date if kind == "date" else datetime.datetime).fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            return "must be an ISO-8601 " + kind
    return None


def validate(entity, body, *, partial=False):
    if not isinstance(body, dict):
        return [{{"field": None, "problem": "body must be a JSON object"}}]
    problems = []
    for field, rule in sorted(RULES[entity].items()):
        if body.get(field) is None:
            if rule["required"] and not rule["has_default"] and not partial:
                problems.append({{"field": field, "problem": "is required"}})
            continue
        problem = _problem(body[field], rule)
        if problem:
            problems.append({{"field": field, "problem": problem}})
    return problems
'''


def validation_rules(spec):
    rules = {}
    for entity in spec["entities"]:
        rules[entity["name"]] = {field["name"]: {key: field[key] for key in ("type", "required", "max", "min", "values") if key in field}
                                 | {"has_default": "default" in field} for field in entity["fields"]}
    return rules


def _sample(field):
    if "default" in field:
        return field["default"]
    kind = field["type"]
    if kind == "enum":
        return field["values"][0]
    if kind == "email":
        return "owner@example.com"
    if kind in ("int", "number"):
        return field.get("min", 1)
    if kind == "bool":
        return True
    if kind == "date":
        return "2026-01-15"
    if kind == "datetime":
        return "2026-01-15T09:00:00Z"
    return ("Sample " + field["name"].replace("_", " "))[:field.get("max", 200)]


def _acceptance_cases(spec, route, entity):
    """Executable cases from the spec's acceptance criteria for one write route; unsupported ones are listed."""
    valid = {field["name"]: _sample(field) for field in entity["fields"] if field["required"]}
    names = {field["name"] for field in entity["fields"]}
    cases, skipped = [], []
    for check in requirements.acceptance_checks(spec)["checks"]:
        if check["method"] != route["method"] or check["path"] != route["route"]:
            continue
        condition, body = check["condition"] or "", dict(valid)
        if condition == "with a valid body":
            pass
        elif re.fullmatch(r"without (\w+)", condition) and condition.split()[1] in names:
            body.pop(condition.split()[1], None)
        elif re.fullmatch(r"with (\w+)=(\S+)", condition) and condition[5:].split("=")[0] in names:
            field, value = condition[5:].split("=", 1)
            body[field] = value
        elif re.fullmatch(r"with (\w+) longer than (\d+) characters", condition) and condition.split()[1] in names:
            body[condition.split()[1]] = "x" * (int(condition.split()[4]) + 1)
        else:
            skipped.append(check["criterion"])
            continue
        cases.append({"criterion": check["criterion"], "feature": check["feature"], "body": body, "status": check["status"],
                      "record": check["expect"] == "the record", "origin": "spec"})
    cases.append({"criterion": f"{route['method']} {route['route']} with a non-object body returns 400", "feature": None, "body": [],
                  "status": 400, "record": False, "origin": "engine"})
    return cases, skipped


# --------------------------------------------------------------------------- generated tests

def _test_module(pattern, area):
    prefix = pattern.split("*", 1)[0]
    name = f"{prefix}{'' if prefix.endswith('_') or not prefix else '_'}upgrade_{area}.py"
    if not fnmatch.fnmatch(name, pattern):
        raise _NotApplicable(f"cannot name a new test module that matches the suite pattern {pattern!r}")
    return name


def _header(step_id, source):
    return (f'"""Generated by the GAIE Master Upgrade Engine (step {step_id}) from {source}.\n\n'
            'Deterministic; in-process; synthetic data only. Kept with the upgrade as its regression tests.\n"""\n\n')


def _validation_tests(step_id, app, spec_rel, targets):
    conn = app["connection"]
    lines = [_header(step_id, f"{spec_rel} acceptance criteria"), "import unittest\n\n", f"import {app['module']}\n"]
    if conn["module"] != app["module"]:
        lines.append(f"import {conn['module']}\n")
    lines.append("\n\nclass UpgradeInputValidationTests(unittest.TestCase):\n")
    lines.append(f"    def setUp(self):\n        self.conn = {conn['module']}.{conn['connect']}({conn.get('memory', ':memory:')!r})\n"
                 f"        {conn['module']}.{conn['init']}(self.conn)\n\n")
    lines.append("    def tearDown(self):\n        self.conn.close()\n\n")
    lines.append(f"    def call(self, method, path, body):\n        return {app['module']}.{app['dispatch']}(method, path, self.conn, body)\n")
    number = 0
    for target in targets:
        for case in target["cases"]:
            number += 1
            slug = _slugify(case["criterion"], 64).replace("-", "_")
            lines.append(f"\n    def test_{number:02d}_{slug}(self):\n        {case['criterion']!r}\n")
            lines.append(f"        body = {case['body']!r}\n")
            lines.append(f"        status, _, result = self.call({target['method']!r}, {target['route']!r}, body)\n")
            lines.append(f"        self.assertEqual(status, {case['status']}, result)\n")
            if case["record"]:
                lines.append("        self.assertIsInstance(result, dict)\n        for key, value in body.items():\n"
                             "            self.assertEqual(result.get(key), value)\n")
    lines.append("\n\nif __name__ == \"__main__\":\n    unittest.main()\n")
    return "".join(lines), number


UI_TEST_TEMPLATE = '''import html.parser
import pathlib
import unittest

TEMPLATES = {templates}
RTL = {rtl}
CONTROLS = {{"input", "select", "textarea"}}
UNLABELLED = {{"hidden", "submit", "button", "reset", "image"}}


class Markup(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.label_for, self.depth = [], set(), 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.tags.append((tag, values, self.depth > 0))
        if tag == "label":
            self.depth += 1
            if values.get("for"):
                self.label_for.add(values["for"])

    def handle_endtag(self, tag):
        if tag == "label" and self.depth:
            self.depth -= 1


def parse(text):
    markup = Markup()
    markup.feed(text)
    markup.close()
    return markup


class UpgradeAccessibilityTests(unittest.TestCase):
    def check(self, text):
        markup = parse(text)
        roots = [values for tag, values, _ in markup.tags if tag == "html"]
        if roots:  # a full document; fragments only need labelled controls
            lang, direction = roots[0].get("lang"), roots[0].get("dir")
            self.assertTrue(lang and direction, "html needs lang and dir")
            self.assertEqual(direction, "rtl" if lang.split("-")[0].lower() in RTL else "ltr")
            self.assertTrue(any(tag == "meta" and (values.get("name") or "").lower() == "viewport" for tag, values, _ in markup.tags))
        for tag, values, in_label in markup.tags:
            if tag in CONTROLS and not (tag == "input" and (values.get("type") or "text").lower() in UNLABELLED):
                self.assertTrue(in_label or values.get("aria-label") or values.get("aria-labelledby") or values.get("id") in markup.label_for,
                                "unlabelled %s %s" % (tag, values.get("name")))

    def test_templates_are_accessible_and_directional(self):
        for rel in TEMPLATES:
            with self.subTest(template=rel):
                self.check(pathlib.Path(rel).read_text(encoding="utf-8"))
{page_test}

if __name__ == "__main__":
    unittest.main()
'''


def _ui_tests(step_id, templates, app, page):
    page_test = ""
    if app and page:
        conn = app["connection"]
        page_test = (f"\n    def test_{_slugify(page['criterion'], 50).replace('-', '_')}(self):\n        {page['criterion']!r}\n"
                     f"        import {app['module']}\n        import {conn['module']}\n"
                     f"        conn = {conn['module']}.{conn['connect']}({conn.get('memory', ':memory:')!r})\n"
                     f"        {conn['module']}.{conn['init']}(conn)\n"
                     f"        try:\n            status, _, body = {app['module']}.{app['dispatch']}('GET', {page['path']!r}, conn, None)\n"
                     f"        finally:\n            conn.close()\n"
                     f"        self.assertEqual(status, {page['status']})\n        self.check(body)\n")
    return _header(step_id, "the template audit and spec accessibility criteria") + \
        UI_TEST_TEMPLATE.format(templates=repr(sorted(templates)), rtl=repr(RTL_LANGUAGES), page_test=page_test)


def _performance_tests(step_id, schemas, findings):
    lines = [_header(step_id, "measured SQLite query plans"), "import pathlib\nimport sqlite3\nimport unittest\n\n",
             f"SCHEMAS = {list(schemas)!r}\n\n\n",
             "class UpgradeQueryPlanTests(unittest.TestCase):\n",
             "    def fresh(self):\n        conn = sqlite3.connect(':memory:')\n        for rel in SCHEMAS:\n"
             "            conn.executescript(pathlib.Path(rel).read_text(encoding='utf-8'))\n        return conn\n"]
    for number, row in enumerate(findings, 1):
        evidence = row["evidence"]
        query, index, table = evidence["query"], row["index"], evidence["table"]
        effect = evidence["effects"][evidence["chosen"]]
        lines.append(f"\n    def test_{number:02d}_{index}_serves_the_query(self):\n        conn = self.fresh()\n"
                     f"        query = {query!r}\n        params = {detectors._bindings(query)!r}\n"
                     "        plan = [row[3] for row in conn.execute('EXPLAIN QUERY PLAN ' + query, params)]\n        conn.close()\n"
                     f"        self.assertTrue(any({index!r} in detail for detail in plan), plan)\n"
                     f"        self.assertFalse(any(detail.startswith('SCAN {table}') for detail in plan), plan)\n")
        if effect["sort_avoided"]:
            lines.append("        self.assertFalse(any('TEMP B-TREE' in detail for detail in plan), plan)\n")
        lines.append(f"\n    def test_{number:02d}_{index}_exists_in_shipped_data(self):\n        for rel in {sorted(row['databases'])!r}:\n"
                     "            conn = sqlite3.connect('file:%s?mode=ro&immutable=1' % rel, uri=True)\n            try:\n"
                     "                names = {row[0] for row in conn.execute(\"SELECT name FROM sqlite_master WHERE type = 'index'\")}\n"
                     f"            finally:\n                conn.close()\n            self.assertIn({index!r}, names, rel)\n")
    lines.append("\n\nif __name__ == \"__main__\":\n    unittest.main()\n")
    return "".join(lines)


# --------------------------------------------------------------------------- the run

class _Run:
    def __init__(self, root, workdir, route, manifest, spec_tests, spec_rel, spec, policy, now):
        self.root, self.workdir, self.route, self.manifest, self.tests = root, workdir, route, manifest, spec_tests
        self.spec_rel, self.spec, self.policy, self.now = spec_rel, spec, policy, now
        self.audit_only = route["mode"] == "audit"
        self.project = route["project"] or manifest.get("name") or (spec or {}).get("slug") or _slugify(root.name)
        self.receipts, self.journal, self.backups, self.steps = [], {}, {}, []
        self.durations, self.stage_seconds, self.test_runs, self.counter = [], {}, 0, 0
        self.passing, self.baseline_tests, self.flaky, self.blocked, self.security_baseline = [], {}, [], None, None
        self.patch = self.reverse = ""
        self.changed, self.task_id, self.requested = {}, None, {"unmet": []}
        self.memory, self.memory_report, self.adr = None, {"written": False}, None
        self.run_dir = self.candidate = self.sandbox = None
        self.original = self._snapshot(root)

    # ----- files, snapshots and receipts
    @staticmethod
    def _snapshot(path):
        try:
            return healing._snapshot(path)
        except healing.HealingError as error:
            raise UpgradeError(str(error)) from None

    def base(self):
        return self.root if self.audit_only else self.candidate

    def files(self):
        return detectors.list_files(self.base())

    def read(self, rel):
        path = self.base() / rel
        return path.read_bytes() if path.is_file() and not path.is_symlink() else None

    def tree_sha(self):
        return sha(self.original if self.audit_only or self.candidate is None else self._snapshot(self.candidate))

    def receipt(self, stage, inputs, outputs, status, side_effect="none", step=None):
        row = {"stage": stage, "step": step, "status": status, "input_sha256": sha(inputs), "output_sha256": sha(outputs),
               "source_sha256": self.tree_sha(), "side_effect": side_effect, "at": _iso(self.now),
               "previous_sha256": self.receipts[-1]["receipt_sha256"] if self.receipts else _ZERO}
        row["receipt_sha256"] = sha(row)
        self.receipts.append(row)
        return row

    def checkpoint(self, stage, done, remaining, summary):
        if self.memory is None:
            return
        moment = datetime.datetime.fromtimestamp(self.now, datetime.timezone.utc)
        try:
            self.memory.task_progress(self.project, self.task_id, f"Upgrade {self.project}", done, remaining, summary=summary[:3900], now=moment)
            self.memory_report["checkpoints"] = self.memory_report.get("checkpoints", 0) + 1
        except (_MemoryError, CoordinationError) as error:
            self.memory_report.setdefault("errors", []).append(f"{stage}: {type(error).__name__}")

    # ----- isolated copy and sandboxed test runs
    def prepare(self):
        self.workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.run_dir = pathlib.Path(tempfile.mkdtemp(prefix="upgrade-", dir=self.workdir)).resolve()
        self.candidate = self.run_dir / "upgraded"
        shutil.copytree(self.root, self.candidate, symlinks=True, ignore=shutil.ignore_patterns(*detectors.SKIP_DIRS, "*.pyc", "*.pyo"))
        _need(self._snapshot(self.candidate) == self.original, "Isolated copy does not match the target")
        self.sandbox = detectors.Sandbox(self.run_dir / "sandbox", timeout=self.policy["test_timeout_s"])
        self.task_id = _slugify(self.run_dir.name, 80)
        try:
            self.memory = MemoryStore.for_project(self.run_dir / "memory", self.project)
            self.memory_report = {"written": True, "store": str(self.memory.directory), "project": self.project, "task_id": self.task_id}
        except (_MemoryError, CoordinationError) as error:
            self.memory_report = {"written": False, "reason": f"{type(error).__name__}: {error}"}

    def scratch(self, label):
        self.counter += 1
        path = self.run_dir / "runs" / f"{self.counter:03d}-{label}"
        shutil.copytree(self.candidate, path, symlinks=True)
        return path

    def suite(self, label, extra=None):
        path = self.scratch(label)
        try:
            for rel, data in (extra or {}).items():
                healing._write_bytes(path, rel, data)
            started = time.monotonic()
            result = self.sandbox.run_tests(path, self.tests["start"], self.tests["pattern"])
            self.durations.append(time.monotonic() - started)
            self.test_runs += 1
            return result
        finally:
            shutil.rmtree(path, ignore_errors=True)

    def write(self, rel, data):
        """The only write path into the upgraded copy: healing.safe_destination refuses escapes and symlinks."""
        destination = healing.safe_destination(self.candidate, rel)
        if rel not in self.journal:
            self.journal[rel] = {"original": destination.read_bytes() if destination.is_file() else None}
        if data is None:
            if destination.is_file():
                destination.unlink()
        else:
            healing._write_bytes(self.candidate, rel, data)
        self.journal[rel]["current"] = data

    # ----- BASELINE
    def baseline(self):
        files = self.files()
        tests_dir = self.tests["start"] if self.tests else None
        databases = self.manifest.get("databases") or sqlite_files(self.root, files, tests_dir)
        self.databases = [rel for rel in databases if rel in files]
        self.data = {}
        for rel in self.databases:
            try:
                self.data[rel] = data_manifest(self.root / rel)
            except sqlite3.Error as error:
                raise UpgradeError(f"Database {rel} is unreadable ({type(error).__name__}); its data could not be protected") from None
        self.assets = {rel: self.original[rel] for rel in asset_files(self.root, files, self.manifest, tests_dir)}
        self.definitions = self.defs(self.root, files)
        self.route_entries = self.routes(self.root)
        self.test_files = {rel: digest for rel, digest in self.original.items() if tests_dir and _under(rel, tests_dir)}
        result = {"data": self.data, "assets": self.assets, "definitions": len(self.definitions), "routes": len(self.route_entries),
                  "test_files": sorted(self.test_files)}
        if self.audit_only:
            result["tests"] = {"executed": False, "reason": "audit is read-only: the suite would run in a workspace copy"}
        elif self.tests is None:
            self.blocked = "no existing test suite found: regression cannot be proven, so nothing is changed"
        else:
            first, second = self.suite("baseline-a"), self.suite("baseline-b")
            self.flaky = sorted(t for t in set(first.get("tests", {})) | set(second.get("tests", {}))
                                if first.get("tests", {}).get(t) != second.get("tests", {}).get(t))
            self.baseline_tests = dict(first.get("tests", {}))
            self.passing = sorted(t for t, o in self.baseline_tests.items() if _passed(o) and t not in self.flaky)
            if first["status"] != "ok" or second["status"] != "ok" or not self.passing:
                self.blocked = f"baseline test run did not complete or nothing passed ({first['status']}/{second['status']})"
            result["tests"] = {"executed": True, "status": first["status"], "outcomes": self.baseline_tests, "passing": len(self.passing),
                               "flaky": self.flaky, "loader_errors": first.get("loader_errors", [])}
        self.baseline_report = result
        self.receipt("BASELINE", {"original": sha(self.original), "tests": self.tests}, result, "blocked" if self.blocked else "ok",
                     "none" if self.audit_only else "workspace-write")
        self.checkpoint("BASELINE", ["route", "baseline"], ["audit", "plan", "apply", "regression", "report"],
                        f"Baseline: {len(self.baseline_tests)} tests, {len(self.databases)} database(s), {len(self.assets)} asset(s).")
        return result

    def defs(self, root, files):
        out = set()
        tests_dir = self.tests["start"] if self.tests else None
        for rel, (_, tree) in detectors._python_modules(root, files, exclude=tests_dir).items():
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    out.add(f"{rel}:{node.name}")
                    if isinstance(node, ast.ClassDef):
                        out.update(f"{rel}:{node.name}.{item.name}" for item in node.body
                                   if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)))
        return out

    def app_rel(self):
        app = self.manifest.get("app")
        return app["module"].replace(".", "/") + ".py" if app else "app.py"

    def routes(self, root):
        source = detectors.read_text(root, self.app_rel())
        if source is None:
            return set()
        return {(row["method"], row["path"]) for row in detectors.route_table(source, (self.manifest.get("app") or {}).get("routes_variable", "ROUTES"))[1]}

    # ----- AUDIT
    def audit(self):
        files = self.files()
        tests_dir = self.tests["start"] if self.tests else None
        inventory = gaie_inventory.inventory(self.root)
        try:
            healing_manifest = detectors.load_manifest(self.root)
        except detectors.DetectorError as error:
            raise UpgradeError(f"Invalid healing manifest: {error}") from None
        runtime = bool(healing_manifest.get("app")) and not self.audit_only
        where = self.root if not runtime else self.scratch("audit")
        try:
            detection = detectors.run_all(where, healing_manifest, tests_dir=tests_dir, runtime=runtime,
                                          sandbox=self.sandbox if runtime else _NO_SANDBOX)
        except detectors.DetectorError as error:
            raise UpgradeError(f"Detector configuration error: {error}") from None
        finally:
            if runtime:
                shutil.rmtree(where, ignore_errors=True)
        self.security_baseline = sorted(f["evidence"]["fingerprint"] for f in detection["findings"] if f["detector"] == "security")
        self.defects = [f for f in detection["findings"] if healing.RANK[f["severity"]] >= healing.RANK["medium"]]
        templates = sorted(rel for rel in files if rel.endswith((".html", ".htm")) and not _under(rel, tests_dir)
                           and (not self.manifest.get("templates") or any(_under(rel, d) for d in self.manifest["templates"])))
        self.templates = templates
        schemas = self.manifest.get("schema") or sorted(rel for rel in files if rel.endswith(".sql") and not _under(rel, tests_dir)
                                                        and not _under(rel, "migrations")
                                                        and re.search(r"\bCREATE\s+TABLE\b", detectors.read_text(self.root, rel) or "", re.I))
        self.schemas = [rel for rel in schemas if rel in files]
        opportunities = []
        opportunities += audit_validation(detectors.read_text(self.root, self.app_rel()), self.app_rel(), self.manifest, self.spec)
        for rel in templates:
            opportunities += audit_html(self.root, rel)
        opportunities += audit_queries(self.root, files, self.schemas, tests_dir)
        self.unused = []
        for rel in sorted(self.assets):
            proof = asset_references(self.root, rel, files)
            if proof["proof"] == "no-internal-reference":
                self.unused.append(proof)
                opportunities.append({"kind": "unused-asset", "path": rel, "line": None, "symbol": rel, "severity": "low", "evidence": proof})
        for row in opportunities:
            row["id"] = f"{row['kind']}-{sha([row['path'], row['line'], row['symbol']])[:10]}"
        self.opportunities = opportunities
        result = {"inventory": {key: inventory[key] for key in ("files_scanned", "file_kinds", "surfaces", "stack", "signals", "findings", "boundary")},
                  "coverage_matrix": inventory["coverage_matrix"],
                  "detectors": [{k: r[k] for k in ("detector", "status", "reason", "method")} | {"findings": len(r["findings"])} for r in detection["detectors"]],
                  "defects": self.defects, "findings": detection["findings"], "runtime_detectors": runtime,
                  "opportunities": opportunities, "requirements": self.requested,
                  "counts": {"defects": len(self.defects), "opportunities": len(opportunities)}}
        self.audit_report = result
        self.receipt("AUDIT", {"tree": self.tree_sha()}, {"findings": sorted(f["id"] for f in detection["findings"]),
                                                         "opportunities": sorted(o["id"] for o in opportunities)}, "ok")
        self.checkpoint("AUDIT", ["route", "baseline", "audit"], ["plan", "apply", "regression", "report"],
                        f"Audit: {len(self.defects)} defect(s), {len(opportunities)} upgrade opportunit(ies).")
        return result

    # ----- PLAN
    def plan(self, extra):
        candidates = []
        for kind, generator in (("code", self.gen_code), ("security", self.gen_validation), ("ui", self.gen_ui),
                                ("performance", self.gen_index), ("assets", self.gen_assets)):
            candidates.append(self.preview(kind, kind, generator))
        for step in extra:
            candidates.append({"id": f"requested-{step['id']}", "area": step["area"], "also": [], "title": {"en": step["title"], "ar": step["title"]},
                               "origin": "caller", "status": "planned", "generator": self.gen_extra(step), "findings": [], "reason": None,
                               "changes": [{"op": c["op"], "path": c.get("path") or c.get("database")} for c in step["changes"]]})
        candidates.append({"id": "docs-upgrade-notes", "area": "docs", "also": [], "origin": "engine", "status": "planned",
                           "title": {"en": "Upgrade notes with rollback instructions", "ar": "ملاحظات التطوير وتعليمات التراجع"},
                           "generator": self.gen_docs, "findings": [], "reason": None, "changes": [{"op": "write", "path": "UPGRADE.md"}]})
        selected = set(self.route["areas"])
        for step in candidates:
            if step["status"] == "planned" and step["area"] not in selected:  # primary area only; "also" is descriptive
                step.update(status="not-selected", reason=f"outside the command's scope ({self.route['scope']}: {', '.join(self.route['areas'])})")
        active = [s for s in candidates if s["status"] == "planned"]
        if len(active) > self.policy["max_steps"]:
            for step in active[self.policy["max_steps"]:]:
                step.update(status="not-selected", reason="beyond policy max_steps")
            active = active[:self.policy["max_steps"]]
        milestones, previous = [], None
        groups = [(f"area-{area}", area, [s for s in active if s["area"] == area and s["id"] != "docs-upgrade-notes"]) for area in AREAS]
        groups.append(("upgrade-notes", "docs", [s for s in active if s["id"] == "docs-upgrade-notes"]))
        for milestone, area, rows in groups:
            if rows:  # areas run in AREAS order, each after the previous one; the notes describe everything before them
                minutes, risk, novelty, confidence = STEP_COST[area]
                milestones.append({"id": milestone, "depends_on": [previous] if previous else [],
                                   "tasks": [{"id": s["id"], "depends_on": [], "minutes": minutes, "risk": risk, "novelty": novelty,
                                              "confidence": confidence} for s in rows]})
                previous = milestone
        decomposition = reasoning.decompose({"schema_version": 1, "goal": _slugify(f"upgrade-{self.project}", 80), "milestones": milestones}) \
            if milestones else None
        order = [node["id"] for node in decomposition["plan_nodes"]] if decomposition else []
        by_id = {s["id"]: s for s in candidates}
        self.ordered = [by_id[i] for i in order]
        self.adr = self.record_adr(active)
        areas = {}
        for area in AREAS:
            rows = [s for s in candidates if s["area"] == area or area in s["also"]]
            areas[area] = {"selected": area in selected, "steps": [s["id"] for s in rows if s["status"] == "planned"],
                           "not_applicable": [{"step": s["id"], "reason": s["reason"]} for s in rows if s["status"] != "planned"]}
        areas["architecture"]["decision"] = self.adr
        status = {s["id"]: s["status"] for s in candidates}
        trace = []
        for category, items in sorted(((self.spec or {}).get("nfr") or {}).items()):
            for item in items:
                kind, target = next(((k, t) for word, k, t in NFR_TRACE if word in item.casefold()), (None, None))
                if kind == "step":
                    state = "addressed-by-step" if status.get(target) == "planned" else f"step-{status.get(target, 'absent')}"
                elif kind == "detector":
                    clean = not any(f["kind"] == "hard-coded-secret" for f in self.audit_report["findings"])
                    state = "verified-by-detector" if clean else "violated"
                else:
                    state = "not-addressed-by-a-deterministic-generator"
                trace.append({"category": category, "requirement": item, "status": state, "by": target})
        areas["tests"]["rule"] = "every step with new tests must fail them before and pass them after; every baseline-passing test must keep passing"
        self.candidates = candidates
        result = {"steps": [self.public(s) for s in candidates], "order": order, "areas": areas, "requirements_trace": trace,
                  "reasoning": {"decompose": None if decomposition is None else {"milestones": decomposition["milestones"],
                                                                                 "milestone_waves": decomposition["milestone_waves"],
                                                                                 "total_minutes": decomposition["total_minutes"],
                                                                                 "receipt": decomposition["receipt"]},
                                "trade_offs": [o["evidence"]["trade_off"] | {"finding": o["id"]} for o in self.opportunities if o["kind"] == "unindexed-filter"],
                                "mode": "deterministic", "model_calls": 0}}
        self.plan_report = result
        self.receipt("PLAN", {"opportunities": sorted(o["id"] for o in self.opportunities), "areas": self.route["areas"]},
                     {"order": order, "steps": [[s["id"], s["status"]] for s in candidates]}, "ok")
        self.checkpoint("PLAN", ["route", "baseline", "audit", "plan"], ["apply", "regression", "report"],
                        f"Plan: {len(order)} ordered step(s): {', '.join(order)}"[:3900] if order else "Plan: nothing applicable.")
        return result

    def record_adr(self, active):
        decision = ("Keep the existing architecture (no sound component is replaced). Add only reversible layers: a "
                    "specification-derived validation module, versioned up/down migrations, templates fixed in place, "
                    "assets moved to a recoverable backup instead of deleted.")
        adr = {"title": f"Upgrade {self.project} by preserving and extending the existing system", "decision": decision,
               "context": (f"Existing system with {len(self.baseline_tests)} baseline tests" if self.baseline_tests else
                           "Existing system (test suite not executed in audit mode)") + f" and {len(self.databases)} database(s); "
                          f"{len(self.opportunities)} upgrade opportunities found by static audit.",
               "consequences": "Every step is applied in an isolated copy with a receipt and is rolled back unless all gates pass.",
               "steps": [s["id"] for s in active]}
        if self.memory is not None:
            try:
                result = self.memory.adr_add(self.project, adr["title"], adr["context"], decision, adr["consequences"], status="accepted",
                                             now=datetime.datetime.fromtimestamp(self.now, datetime.timezone.utc))
                adr["adr_id"] = result["adr_id"]
            except (_MemoryError, CoordinationError) as error:
                adr["adr_error"] = type(error).__name__
        return adr

    @staticmethod
    def public(step):
        return {key: value for key, value in step.items() if key != "generator"}

    def preview(self, kind, area, generator):
        ids = {"code": "code-repair-defects", "security": "security-input-validation", "ui": "ui-accessibility-rtl",
               "performance": "performance-query-indexes", "assets": "assets-backup-unused"}
        titles = {"code": ("Repair detected defects with the self-healing loop",
                           "إصلاح العيوب المكتشفة بحلقة الإصلاح الذاتي"),
                  "security": ("Validate input on every write endpoint from the specification",
                               "التحقق من المدخلات في كل نقطة كتابة من المواصفة"),
                  "ui": ("Accessible, right-to-left aware templates",
                         "قوالب متاحة وتدعم الاتجاه من اليمين لليسار"),
                  "performance": ("Index filtered queries with a reversible, data-preserving migration",
                                  "فهرسة الاستعلامات المصفاة بترحيل قابل للتراجع يحفظ البيانات"),
                  "assets": ("Move unreferenced assets to a recoverable backup",
                             "نقل الأصول غير المستخدمة إلى نسخة احتياطية قابلة للاسترجاع")}
        also = {"security": ["architecture", "code", "tests"], "performance": ["database", "tests"], "ui": ["tests"], "code": ["tests"]}
        step = {"id": ids[kind], "area": area, "also": also.get(kind, []), "origin": "engine",
                "title": {"en": titles[kind][0], "ar": titles[kind][1]}, "generator": generator, "status": "planned", "reason": None}
        try:
            proposal = generator(preview=True)
            step.update(findings=proposal.get("findings", []), changes=proposal.get("summary", []))
        except _NotApplicable as reason:
            step.update(status="not-applicable", reason=str(reason), findings=[], changes=[])
        return step

    # ----- generators: each returns {"ops": [...], "tests": {rel: bytes}, "findings": [...], "summary": [...], ...}
    def gen_code(self, preview=False):
        failing = [t for t, o in self.baseline_tests.items() if not _passed(o) and o != "skipped" and t not in self.flaky]
        if not self.defects and not failing:
            raise _NotApplicable("detectors found no medium-or-higher defect and " + (
                "every baseline test passes" if self.baseline_tests else "no baseline test outcome is known (the suite is not run in audit mode)"))
        findings = [f["id"] for f in self.defects] + [f"test:{t}" for t in failing]
        if preview:
            return {"findings": findings, "summary": [{"op": "self-healing", "defects": len(self.defects), "failing_tests": len(failing)}]}
        source = self.scratch("healing-target")
        try:
            result = healing.heal(source, workdir=self.run_dir / "healing", tests=self.tests, now=self.now)
        except healing.HealingError as error:
            shutil.rmtree(source, ignore_errors=True)
            raise _NotApplicable(f"self-healing refused: {error}") from None
        if result["status"] not in ("repaired", "partially-repaired"):
            shutil.rmtree(source, ignore_errors=True)
            raise _NotApplicable(f"self-healing found no validated repair ({result['status']})")
        repaired = pathlib.Path(result["isolated_copy"])
        ops = [{"op": "write", "path": rel, "data": (repaired / rel).read_bytes()} for rel in sorted(result["rollback"]["files"])]
        shutil.rmtree(source, ignore_errors=True)
        return {"ops": ops, "tests": {}, "findings": findings, "summary": [{"op": "write", "path": op["path"]} for op in ops],
                "evidence": {"healing_status": result["status"], "healing_report_sha256": result["report_sha256"],
                             "repairs": [r["description"] for r in result["repairs"]]}}

    def gen_validation(self, preview=False):
        rows = [o for o in self.opportunities if o["kind"] == "missing-input-validation"]
        if self.spec is None:
            raise _NotApplicable("no specification: validation rules are never guessed")
        if not self.tests:
            raise _NotApplicable("no test suite: the validation step could not be proven")
        app = self.manifest.get("app")
        if not app or "connection" not in app:
            raise _NotApplicable("no declared app convention (gaie-upgrade.json app.dispatch and app.connection)")
        if not rows:
            raise _NotApplicable("every write endpoint of a spec entity already has a rejection path")
        app_rel = self.app_rel()
        source = (self.read(app_rel) or b"").decode("utf-8")
        tree = ast.parse(source)
        module = "validation" if not (self.base() / pathlib.PurePosixPath(app_rel).with_name("validation.py")).exists() else "upgrade_validation"
        if module == "upgrade_validation" and (self.base() / pathlib.PurePosixPath(app_rel).with_name("upgrade_validation.py")).exists():
            raise _NotApplicable("validation module names are taken")
        defined = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {a.asname or a.name for n in ast.walk(tree)
                                                                               if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        if module in defined:
            raise _NotApplicable(f"the name {module!r} is already used in {app_rel}")
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        entities = {entity["name"]: entity for entity in self.target_spec["entities"]}
        lines = source.splitlines(keepends=True)
        inserts, targets, findings = [], [], []
        for row in rows:
            evidence = row["evidence"]
            handler = functions.get(evidence["handler"])
            if handler is None or not evidence["body_argument"] or not evidence["content_type"]:
                continue
            first = handler.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str) and len(handler.body) > 1:
                first = handler.body[1]
            pad = lines[first.lineno - 1][:first.col_offset]
            if pad.strip() or "\t" in pad:
                continue
            local = {n.id for n in ast.walk(handler) if isinstance(n, ast.Name)}
            name = "problems" if "problems" not in local else "upgrade_problems"
            partial = ", partial=True" if evidence["method"] != "POST" else ""
            guard = (f"{pad}{name} = {module}.validate({evidence['entity']!r}, {evidence['body_argument']}{partial})\n"
                     f"{pad}if {name}:\n{pad}    return 400, {evidence['content_type']!r}, {{\"error\": \"invalid input\", \"fields\": {name}}}\n")
            inserts.append((first.lineno - 1, guard))
            cases, skipped = _acceptance_cases(self.target_spec, {"method": evidence["method"], "route": evidence["route"]}, entities[evidence["entity"]])
            targets.append({"method": evidence["method"], "route": evidence["route"], "cases": cases, "skipped": skipped})
            findings.append(row["id"])
        if not inserts:
            raise _NotApplicable("no handler with a body argument, a literal content type and space indentation")
        imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        after = imports[-1].end_lineno if imports else 0
        for index, guard in sorted(inserts, reverse=True):
            lines.insert(index, guard)
        lines.insert(after, f"import {module}\n" if after else f"import {module}\n\n")
        module_rel = str(pathlib.PurePosixPath(app_rel).with_name(f"{module}.py"))
        validation_source = VALIDATION_TEMPLATE.format(spec=self.spec_rel, rules=pprint.pformat(validation_rules(self.target_spec), width=110, sort_dicts=True))
        test_rel = f"{self.tests['start']}/{_test_module(self.tests['pattern'], 'security')}"
        test_source, count = _validation_tests("security-input-validation", app, self.spec_rel, targets)
        ops = [{"op": "write", "path": module_rel, "data": validation_source.encode("utf-8"), "create": True},
               {"op": "write", "path": app_rel, "data": "".join(lines).encode("utf-8")}]
        return {"ops": ops, "tests": {test_rel: test_source.encode("utf-8")}, "findings": findings,
                "summary": [{"op": "write", "path": module_rel, "create": True}, {"op": "write", "path": app_rel},
                            {"op": "add-test", "path": test_rel, "cases": count}],
                "evidence": {"routes": [f"{t['method']} {t['route']}" for t in targets], "acceptance_cases": count,
                             "criteria_not_generated": sorted({c for t in targets for c in t["skipped"]}), "rules_from": self.spec_rel}}

    def gen_ui(self, preview=False):
        rows = [o for o in self.opportunities if o["kind"] in ("html-missing-lang-dir", "unlabelled-control", "missing-viewport")]
        manual = [o["id"] for o in self.opportunities if o["kind"] == "image-missing-alt"]
        if not rows:
            raise _NotApplicable("templates already declare lang/dir and viewport and label every control" +
                                 (f"; {len(manual)} image(s) need owner-written alt text" if manual else ""))
        ops, changes = [], []
        for rel in sorted({o["path"] for o in rows}):
            text = (self.read(rel) or b"").decode("utf-8")
            fixed, made = fix_html(text, self.target_spec if self.spec else None)
            if fixed != text:
                ops.append({"op": "write", "path": rel, "data": fixed.encode("utf-8")})
                changes.append({"path": rel, "changes": made})
        if not ops:
            raise _NotApplicable("no deterministic template edit applies")
        app = self.manifest.get("app")
        page = None
        if self.spec and app and "connection" in app and ("GET", "/") in self.route_entries:
            page = next(({"criterion": c["criterion"], "path": c["path"], "status": c["status"]} for c in requirements.acceptance_checks(self.target_spec)["checks"]
                         if c["method"] == "GET" and c["path"] == "/" and "label" in (c["expect"] or "")), None)
        test_rel = f"{self.tests['start']}/{_test_module(self.tests['pattern'], 'ui')}" if self.tests else None
        tests = {test_rel: _ui_tests("ui-accessibility-rtl", self.templates, app if page else None, page).encode("utf-8")} if test_rel else {}
        return {"ops": ops, "tests": tests, "findings": [o["id"] for o in rows],
                "summary": [{"op": "write", "path": c["path"], "edits": len(c["changes"])} for c in changes] + ([{"op": "add-test", "path": test_rel}] if test_rel else []),
                "evidence": {"templates": changes, "manual": manual}}

    def gen_index(self, preview=False):
        rows = [o for o in self.opportunities if o["kind"] == "unindexed-filter"]
        if not rows:
            raise _NotApplicable("no filtered query scans a whole table" if self.schemas else "no SQL schema declared or found")
        existing = [int(m[1]) for m in (re.match(r"migrations/(\d{4})_", rel) for rel in self.files()) if m]
        number = max(existing, default=0)
        ops, summary, schema_add = [], [], {}
        for row in rows:
            evidence = row["evidence"]
            index = f"idx_{evidence['table']}_{'_'.join(evidence['columns'])}"[:60]
            row["index"] = index
            row["databases"] = [d for d in self.databases if evidence["table"] in self.data[d]["tables"]]
            owner = re.compile(rf"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?{re.escape(evidence['table'])}\b", re.I)
            schema = next((rel for rel in self.schemas if owner.search((self.read(rel) or b"").decode("utf-8", "replace"))), self.schemas[0])
            number += 1
            create = f"CREATE INDEX IF NOT EXISTS {index} ON {evidence['table']} ({', '.join(evidence['columns'])});"
            stem = f"migrations/{number:04d}_{index}"
            header = (f"-- Migration {number:04d} (GAIE Master Upgrade Engine): index for {row['path']}:{row['line']}.\n"
                      f"-- Chosen by reasoning.trade_off ({evidence['chosen']}); schema only, no row is read, changed or removed.\n")
            ops.append({"op": "write", "path": f"{stem}.sql", "data": (header + create + "\n").encode("utf-8"), "create": True})
            ops.append({"op": "write", "path": f"{stem}.down.sql", "data": (f"-- Reverses migration {number:04d}.\nDROP INDEX IF EXISTS {index};\n").encode("utf-8"), "create": True})
            schema_add.setdefault(schema, []).append(f"-- Added with migration {number:04d} (GAIE Master Upgrade Engine).\n{create}\n")
            for database in row["databases"]:
                ops.append({"op": "migrate", "database": database, "id": f"{number:04d}_{index}", "up": create, "down": f"DROP INDEX IF EXISTS {index};"})
            summary.append({"op": "migration", "id": f"{number:04d}_{index}", "table": evidence["table"], "columns": evidence["columns"],
                            "schema": schema, "databases": row["databases"]})
        for schema, additions in sorted(schema_add.items()):
            current = (self.read(schema) or b"").decode("utf-8")
            ops.append({"op": "write", "path": schema, "data": (current + ("" if current.endswith("\n") else "\n") + "".join(additions)).encode("utf-8")})
        test_rel = f"{self.tests['start']}/{_test_module(self.tests['pattern'], 'performance')}" if self.tests else None
        tests = {test_rel: _performance_tests("performance-query-indexes", self.schemas, rows).encode("utf-8")} if test_rel else {}
        return {"ops": ops, "tests": tests, "findings": [o["id"] for o in rows], "summary": summary + [{"op": "write", "path": rel} for rel in sorted(schema_add)],
                "evidence": {"indexes": [{"index": r["index"], "query_plan_before": r["evidence"]["plan_before"],
                                          "query_plan_after": r["evidence"]["effects"][r["evidence"]["chosen"]]["plan"]} for r in rows]}}

    def gen_assets(self, preview=False):
        if not self.policy["asset_backup"]:
            raise _NotApplicable("policy asset_backup is false")
        if not self.unused:
            raise _NotApplicable("every asset is referenced (or reference freedom is unproven)")
        files = self.files()
        ops, proofs = [], []
        for row in self.unused:
            again = asset_references(self.base(), row["asset"], files)
            if again["proof"] == "no-internal-reference":
                ops.append({"op": "move-to-backup", "path": row["asset"], "proof": again})
                proofs.append(again)
        if not ops:
            raise _NotApplicable("assets became referenced by earlier steps")
        return {"ops": ops, "tests": {}, "findings": [o["id"] for o in self.opportunities if o["kind"] == "unused-asset"],
                "summary": [{"op": "move-to-backup", "path": op["path"]} for op in ops], "evidence": {"proofs": proofs}}

    def gen_extra(self, step):
        def generate(preview=False):
            ops, tests = [], {}
            for change in step["changes"]:
                if change["op"] == "replace":
                    data = self.read(change["path"]) if not preview else None
                    if not preview:
                        text = _text_of(data)
                        _need(text is not None and text.count(change["old"]) == 1, f"replace: the old text must occur exactly once in {change['path']}")
                        ops.append({"op": "write", "path": change["path"], "data": text.replace(change["old"], change["new"]).encode("utf-8")})
                elif change["op"] == "add-file":
                    ops.append({"op": "write", "path": change["path"], "data": change["text"].encode("utf-8"), "create": True})
                else:
                    ops.append({"op": "migrate", "database": change["database"], "id": change["name"], "up": change["up"], "down": change["down"]})
            for row in step.get("tests", []):
                tests[row["path"]] = row["text"].encode("utf-8")
            return {"ops": ops, "tests": tests, "findings": [], "summary": [{"op": c["op"], "path": c.get("path") or c.get("database")} for c in step["changes"]]}
        return generate

    def gen_docs(self, preview=False):
        applied = [s for s in self.steps if s["status"] == "applied"]
        if not preview and not applied:
            raise _NotApplicable("no step was applied; nothing to document")
        if preview:
            return {"summary": [{"op": "write", "path": "UPGRADE.md"}]}
        current = _text_of(self.read("UPGRADE.md"))
        lines = [f"# Upgrade of {self.project} / تطوير {self.project}\n\n" if current is None else "\n",
                 f"Generated by the GAIE Master Upgrade Engine at {_iso(self.now)} for the command: `{self.route_command}`.\n",
                 "أُنشئ هذا الملف آليًا (بلا نموذج ذكاء اصطناعي) ويصف ما تغيّر وكيف يُتراجع عنه.\n\n",
                 "| Step | Area | Files | New tests |\n|---|---|---|---|\n"]
        for step in applied:
            lines.append(f"| {step['id']} | {step['area']} | {', '.join(step['files'])} | {step['new_tests']['count']} |\n")
        migrations = [m for s in applied for m in s.get("migrations", [])]
        if migrations:
            lines.append("\n## Migrations / الترحيلات\n\n")
            for row in migrations:
                lines.append(f"- `{row['id']}` on `{row['database']}`: rows preserved ({', '.join(f'{t}={v}' for t, v in row['rows'].items())}); "
                             f"down migration verified: {row['down_verified']}.\n")
        moved = [b for s in applied for b in s.get("backups", [])]
        if moved:
            lines.append("\n## Assets moved to the backup / أصول نُقلت إلى النسخة الاحتياطية\n\n")
            lines += [f"- `{row['path']}` (sha256 {row['sha256'][:16]}…): no internal reference; restore from `backup/{row['path']}`.\n" for row in moved]
        if self.requested.get("unmet"):
            lines.append("\n## Requested but not implemented / طُلب ولم يُنفَّذ\n\n")
            lines += [f"- {item}: needs application code beyond the deterministic generators.\n" for item in self.requested["unmet"]]
        lines.append("\n## Rollback / التراجع\n\nApply `rollback.patch` and restore the files under `rollback/` of the upgrade run directory; "
                     "the original system was never modified. / طبّق rollback.patch واسترجع الملفات من rollback/؛ النظام الأصلي لم يُعدَّل.\n")
        return {"ops": [{"op": "write", "path": "UPGRADE.md", "data": ((current or "") + "".join(lines)).encode("utf-8")}], "tests": {},
                "findings": [], "summary": [{"op": "write", "path": "UPGRADE.md"}]}

    # ----- APPLY
    def apply_all(self):
        for step in self.ordered:
            if self.blocked:
                step.update(status="not-run", reason=self.blocked)
                continue
            result = self.apply(step)
            self.steps.append(result)
        self.receipt("APPLY", [s["id"] for s in self.ordered], [[s["id"], s["status"]] for s in self.steps], "ok", "workspace-write")
        self.checkpoint("APPLY", ["route", "baseline", "audit", "plan", "apply"], ["regression", "report"],
                        "Apply: " + ", ".join(f"{s['id']}={s['status']}" for s in self.steps)[:3800])

    def apply(self, step):
        record = {"id": step["id"], "area": step["area"], "title": step["title"], "origin": step["origin"], "files": [],
                  "new_tests": {"files": [], "count": 0, "red_before": [], "green_after": []}, "gates": {}, "reasons": []}
        pre_tree = self.tree_sha()
        try:
            proposal = step["generator"]()
        except _NotApplicable as reason:
            record.update(status="skipped", reason=str(reason))
            self.receipt("APPLY", {"step": step["id"]}, record, "skipped", step=step["id"])
            return record
        except UpgradeError as error:
            record.update(status="refused", reason=str(error))
            self.receipt("APPLY", {"step": step["id"]}, record, "refused", step=step["id"])
            return record
        tests = proposal.get("tests", {})
        record["evidence"] = proposal.get("evidence")
        record["findings"] = proposal.get("findings", [])
        undo = {}
        try:
            self.check_ops(proposal["ops"], tests)
        except (UpgradeError, healing.HealingError) as error:
            record.update(status="refused", reason=str(error))
            self.receipt("APPLY", {"step": step["id"]}, {"status": "refused", "reason": str(error)}, "refused", step=step["id"])
            return record
        new_modules = {pathlib.PurePosixPath(rel).stem for rel in tests}
        red = {}
        if tests:
            pre = self.suite(f"{step['id']}-red", tests)
            red = {t: o for t, o in pre.get("tests", {}).items() if self.is_new(t, new_modules)}
            record["new_tests"]["red_before"] = sorted(t for t, o in red.items() if not _passed(o))
            if pre["status"] == "ok" and red and not record["new_tests"]["red_before"]:
                record.update(status="skipped", reason="already satisfied: every new test already passes before the change")
                self.receipt("APPLY", {"step": step["id"]}, record, "skipped", step=step["id"])
                return record
        try:
            migrations, backups = self.execute(step["id"], proposal["ops"], tests, undo)
        except (UpgradeError, healing.HealingError, OSError, sqlite3.Error, ValueError) as error:
            self.rollback(undo)
            verified = self.tree_sha() == pre_tree
            record.update(status="refused", reason=str(error), rollback_verified=verified)
            self.receipt("APPLY", {"step": step["id"]}, {"status": "refused", "reason": str(error), "rollback_verified": verified},
                         "refused", "workspace-write", step=step["id"])
            return record
        record["files"] = sorted(undo)
        record["migrations"], record["backups"] = migrations, backups
        post = self.suite(f"{step['id']}-green")
        outcomes = post.get("tests", {})
        new_ids = sorted(t for t in outcomes if self.is_new(t, new_modules))
        record["new_tests"].update(files=sorted(tests), count=len(new_ids), green_after=sorted(t for t in new_ids if _passed(outcomes[t])))
        gates = self.gates(post, new_ids, sorted(undo))
        record["gates"] = gates
        reasons = [name for name, ok in gates.items() if ok is False]
        if tests and not record["new_tests"]["red_before"]:
            reasons.append("new-tests-not-red-before")
        if reasons:
            self.rollback(undo)
            verified = self.tree_sha() == pre_tree
            regressions = sorted(t for t in self.passing if not _passed(outcomes.get(t)))
            failing = sorted(t for t in new_ids if not _passed(outcomes[t]))
            record.update(status="rejected", reasons=reasons, regressions=regressions, rollback_verified=verified, failing_new_tests=failing,
                          failure_details={t: post.get("details", {}).get(t) for t in (regressions + failing)[:8]})
            if not verified:
                self.blocked = f"rollback of rejected step {step['id']} could not be verified"
            self.receipt("APPLY", {"step": step["id"]}, {"status": "rejected", "reasons": reasons, "regressions": regressions,
                                                        "rollback_verified": verified}, "rejected", "workspace-write", step=step["id"])
            return record
        record.update(status="applied", rollback_verified=None, tree_sha256=self.tree_sha(),
                      diff=self.step_diff(undo)[:12000])
        self.receipt("APPLY", {"step": step["id"], "ops": proposal.get("summary", [])},
                     {"files": {rel: None if self.journal[rel]["current"] is None else hashlib.sha256(self.journal[rel]["current"]).hexdigest() for rel in undo},
                      "gates": gates, "new_tests": record["new_tests"]}, "applied", "workspace-write", step=step["id"])
        return record

    @staticmethod
    def is_new(test_id, modules):
        return test_id.split(".")[0] in modules or any(test_id == f"unittest.loader._FailedTest.{m}" for m in modules)

    def protected(self):
        return {MANIFEST, self.spec_rel} - {None}

    def check_ops(self, ops, tests):
        tests_dir = self.tests["start"]
        for rel in tests:
            healing.safe_destination(self.candidate, rel)
            _need(_under(rel, tests_dir) and fnmatch.fnmatch(pathlib.PurePosixPath(rel).name, self.tests["pattern"]),
                  f"Refused: new test {rel} must live in {tests_dir}/ and match {self.tests['pattern']}")
            _need(not (self.candidate / rel).exists(), f"Refused: test file {rel} exists; existing tests are the oracle and are never edited")
        for op in ops:
            rel = op.get("path") or op.get("database")
            _need(isinstance(rel, str), "Refused: operation without a path")
            healing.safe_destination(self.candidate, rel)
            _need(rel not in self.protected(), f"Refused: {rel} is the upgrade's declared input and is never edited")
            _need(not _under(rel, tests_dir), f"Refused: {rel} is under the test suite; existing tests are never edited")
            if op["op"] == "write" and op.get("create"):
                _need(not (self.candidate / rel).exists(), f"Refused: {rel} already exists")
            if op["op"] == "migrate":
                _need(rel in self.databases, f"Refused: {rel} is not a baseline SQLite database")
                classify_migration(op["up"])
                if op["down"] and split_sql(op["down"]):
                    classify_migration(op["down"])
            if op["op"] == "move-to-backup":
                _need(rel in self.assets and op["proof"]["proof"] == "no-internal-reference",
                      f"Refused: {rel} would be deleted without proof of non-use")

    def execute(self, step_id, ops, tests, undo):
        migrations, backups = [], []

        def remember(rel):
            if rel not in undo:
                path = healing.safe_destination(self.candidate, rel)
                undo[rel] = path.read_bytes() if path.is_file() else None

        for op in ops:
            rel = op.get("path") or op.get("database")
            remember(rel)
            if op["op"] == "write":
                self.write(rel, op["data"])
            elif op["op"] == "migrate":
                data, proof = migrate_database(self.candidate / rel, op["up"], op["down"], self.run_dir / "scratch" / f"{step_id}-{_slugify(op['id'])}")
                self.write(rel, data)
                migrations.append({"id": op["id"], "database": rel, "statements": proof["statements"], "down_verified": proof["down_verified"],
                                   "rows": {t: r["rows"] for t, r in proof["before"]["tables"].items()},
                                   "checksums": {t: r["sha256"] for t, r in proof["before"]["tables"].items()},
                                   "indexes_after": proof["after"]["indexes"]})
            elif op["op"] == "move-to-backup":
                data = (self.candidate / rel).read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                backup = healing._write_bytes(self.run_dir, f"backup/{rel}", data)
                _need(hashlib.sha256(backup.read_bytes()).hexdigest() == digest == self.assets[rel], f"Refused: backup of {rel} does not verify")
                self.write(rel, None)
                self.backups[rel] = {"path": rel, "sha256": digest, "backup": f"backup/{rel}", "proof": op["proof"]}
                backups.append(self.backups[rel])
        for rel, data in tests.items():
            remember(rel)
            self.write(rel, data)
        return migrations, backups

    def rollback(self, undo):
        for rel, data in undo.items():
            path = healing.safe_destination(self.candidate, rel)
            if data is None:
                if path.is_file():
                    path.unlink()
            else:
                healing._write_bytes(self.candidate, rel, data)
            entry = self.journal.get(rel)
            if entry is not None:
                entry["current"] = data
                if entry["original"] == data:
                    del self.journal[rel]
            if rel in self.backups and data is not None:
                del self.backups[rel]

    def gates(self, post, new_ids, touched):
        outcomes = post.get("tests", {})
        files = detectors.list_files(self.candidate)
        written = [rel for rel in touched if (self.candidate / rel).is_file()]
        data_ok = True
        for rel, manifest in self.data.items():
            problems, _ = data_preserved(manifest, self.candidate / rel)
            data_ok = data_ok and not problems
        security = detectors.detect_security(self.candidate, [r for r in written if pathlib.PurePosixPath(r).suffix in detectors.TEXT_SUFFIXES],
                                             baseline=self.security_baseline)
        syntax = all(detectors._parse((self.candidate / rel).read_text(encoding="utf-8")) is not None for rel in written if rel.endswith(".py"))
        return {"suite-completed": post["status"] == "ok",
                "no-regression": all(_passed(outcomes.get(t)) for t in self.passing),
                "new-tests-pass": all(_passed(outcomes.get(t)) for t in new_ids),
                "data-preserved": data_ok,
                "python-syntax": syntax,
                "no-new-security-finding": not any(f["evidence"]["baseline"] == "new" for f in security["findings"]),
                "functions-preserved": self.definitions <= self.defs(self.candidate, files),
                "routes-preserved": self.route_entries <= self.routes(self.candidate),
                "test-oracle-unchanged": all(self.original[rel] == hashlib.sha256((self.candidate / rel).read_bytes()).hexdigest()
                                             for rel in self.test_files if (self.candidate / rel).is_file())
                and all((self.candidate / rel).is_file() for rel in self.test_files),
                "assets-accounted": all(rel in self.backups or ((self.candidate / rel).is_file()) for rel in self.assets)}

    def step_diff(self, undo):
        out = []
        for rel in sorted(undo):
            before, after = undo[rel], (self.candidate / rel).read_bytes() if (self.candidate / rel).is_file() else None
            if _text_of(before) is not None or before is None:
                if after is None or _text_of(after) is not None:
                    out.append(_diff(rel, before, after))
                    continue
            out.append(f"Binary {rel}: {None if before is None else hashlib.sha256(before).hexdigest()[:16]} -> "
                       f"{None if after is None else hashlib.sha256(after).hexdigest()[:16]}\n")
        return "".join(out)

    # ----- REGRESSION
    def regression(self):
        final = self.suite("final") if self.tests else {"status": "not-run", "tests": {}}
        outcomes = final.get("tests", {})
        added = sorted({rel for s in self.steps if s["status"] == "applied" for rel in s["new_tests"]["files"]})
        modules = {pathlib.PurePosixPath(rel).stem for rel in added}
        new_ids = sorted(t for t in outcomes if self.is_new(t, modules))
        data = {}
        for rel, manifest in self.data.items():
            problems, after = data_preserved(manifest, self.candidate / rel)
            data[rel] = {"preserved": not problems, "problems": problems,
                         "tables": {t: {"rows_before": r["rows"], "rows_after": after["tables"].get(t, {}).get("rows"),
                                        "sha256_before": r["sha256"], "sha256_after": after["tables"].get(t, {}).get("sha256")}
                                    for t, r in manifest["tables"].items()},
                         "indexes_before": manifest["indexes"], "indexes_after": after["indexes"], "integrity": after["integrity"]}
        assets = {}
        for rel, digest in self.assets.items():
            path = self.candidate / rel
            if path.is_file():
                now = hashlib.sha256(path.read_bytes()).hexdigest()
                assets[rel] = {"status": "unchanged" if now == digest else "modified-by-step", "sha256": now}
            elif rel in self.backups:
                backup = self.run_dir / self.backups[rel]["backup"]
                ok = backup.is_file() and hashlib.sha256(backup.read_bytes()).hexdigest() == digest
                assets[rel] = {"status": "moved-to-backup" if ok else "backup-missing", "backup": str(backup),
                               "proof": self.backups[rel]["proof"]["proof"], "sha256": digest}
            else:
                assets[rel] = {"status": "deleted-without-proof"}
        files = detectors.list_files(self.candidate)
        original_now = self._snapshot(self.root)
        changed = {rel: row for rel, row in sorted(self.journal.items()) if row["current"] != row["original"]}
        patch, reverse, binary = self.patches(changed)
        patch_ok = self.check_patch(changed, patch, reverse)
        rollback_ok = self.check_rollback(changed)
        checks = {
            "suite-completed": final["status"] == "ok",
            "no-regression": all(_passed(outcomes.get(t)) for t in self.passing),
            "new-tests-pass": all(_passed(outcomes.get(t)) for t in new_ids),
            "data-preserved": all(row["preserved"] for row in data.values()),
            "assets-accounted": all(row["status"] in ("unchanged", "modified-by-step", "moved-to-backup") for row in assets.values()),
            "functions-preserved": self.definitions <= self.defs(self.candidate, files),
            "routes-preserved": self.route_entries <= self.routes(self.candidate),
            "test-oracle-unchanged": all((self.candidate / rel).is_file() and hashlib.sha256((self.candidate / rel).read_bytes()).hexdigest() == d
                                         for rel, d in self.test_files.items()),
            "original-unchanged": original_now == self.original,
            "isolated-copy": self.run_dir in self.candidate.parents and self.root not in self.candidate.parents,
            "patch-and-reverse-apply": patch_ok,
            "rollback-restores-original": rollback_ok,
            "not-blocked": self.blocked is None,
            "requested-changes-met": not self.requested.get("unmet"),
        }
        regressions = sorted(t for t in self.passing if not _passed(outcomes.get(t)))
        fixed = sorted(t for t, o in self.baseline_tests.items() if not _passed(o) and o != "skipped" and _passed(outcomes.get(t)))
        self.changed, self.patch, self.reverse = changed, patch, reverse
        result = {"passed": all(checks.values()), "checks": checks, "regressions": regressions,
                  "tests": {"baseline_passing": len(self.passing), "final_total": len(outcomes),
                            "final_passing": sum(1 for o in outcomes.values() if _passed(o)), "new_tests": len(new_ids),
                            "baseline_failures_fixed": fixed,
                            "new_test_files": added, "flaky_excluded": self.flaky},
                  "data": data, "assets": assets, "changed_files": sorted(changed), "binary_changes": binary}
        self.decision = self.decide(checks)
        result["decision"] = {k: self.decision[k] for k in ("status", "rejected_because", "warnings", "receipt")}
        self.regression_report = result
        self.receipt("REGRESSION", {"tree": self.tree_sha(), "steps": [[s["id"], s["status"]] for s in self.steps]},
                     {k: v for k, v in result.items() if k != "data"}, "passed" if result["passed"] else "failed")
        self.checkpoint("REGRESSION", ["route", "baseline", "audit", "plan", "apply", "regression"], ["report"],
                        f"Regression proof {'passed' if result['passed'] else 'FAILED'}: {sum(checks.values())}/{len(checks)} checks.")
        return result

    def decide(self, checks):
        mapping = {"no-test-regression": ("test-run", ["suite-completed", "no-regression", "not-blocked"]),
                   "data-preserved": ("data-checksum", ["data-preserved"]),
                   "assets-recoverable": ("asset-proof", ["assets-accounted"]),
                   "functions-preserved": ("static-analysis", ["functions-preserved", "routes-preserved", "test-oracle-unchanged"]),
                   "original-unchanged": ("snapshot", ["original-unchanged", "isolated-copy"]),
                   "rollback-verified": ("rollback-check", ["patch-and-reverse-apply", "rollback-restores-original"]),
                   "improvements-tested": ("test-run", ["new-tests-pass"]),
                   "requested-changes-met": ("requirements-diff", ["requested-changes-met"])}
        criteria = [{"id": key, "critical": key not in ("improvements-tested", "requested-changes-met"), "evidence_kinds": [kind], "max_age_seconds": 86400}
                    for key, (kind, _) in mapping.items()]
        evidence = []
        for key, (kind, names) in mapping.items():
            ok = all(checks[name] for name in names)
            evidence.append({"id": f"e-{key}", "criterion": key, "kind": kind, "verdict": "supports" if ok else "contradicts",
                             "confidence": 1.0, "at": self.now, "sha256": sha({name: checks[name] for name in names})})
        return reasoning.validate_decision({
            "schema_version": 1, "min_confidence": 0.9, "criteria": criteria, "evidence": evidence,
            "decision": {"id": _slugify(f"keep-upgrade-{self.project}", 80), "choice": "keep-upgraded-copy",
                         "basis_sha256": hashlib.sha256(self.patch.encode("utf-8")).hexdigest()}}, now=self.now)

    def patches(self, changed):
        patch, reverse, binary = [], [], []
        for rel, row in changed.items():
            before, after = row["original"], row["current"]
            texts = (before is None or _text_of(before) is not None) and (after is None or _text_of(after) is not None)
            if texts:
                patch.append(_diff(rel, before, after))
                reverse.append(_diff(rel, after, before))
            else:
                binary.append({"path": rel, "before_sha256": None if before is None else hashlib.sha256(before).hexdigest(),
                               "after_sha256": None if after is None else hashlib.sha256(after).hexdigest(),
                               "kind": "moved-to-backup" if after is None and rel in self.backups else
                               "sqlite-migrated" if rel in self.databases else "binary-replaced",
                               "rollback": f"rollback/{rel}"})
        return "".join(patch), "".join(reverse), binary

    def check_patch(self, changed, patch, reverse):
        text = {rel: row for rel, row in changed.items() if (row["original"] is None or _text_of(row["original"]) is not None)
                and (row["current"] is None or _text_of(row["current"]) is not None)}
        if not text:
            return True
        before = {rel: row["original"].decode("utf-8") for rel, row in text.items() if row["original"] is not None}
        after = {rel: None if row["current"] is None else row["current"].decode("utf-8") for rel, row in text.items()}
        try:
            forward = healing.apply_patch(before, patch)
            back = healing.apply_patch({k: v for k, v in after.items() if v is not None}, reverse)
        except healing.HealingError:
            return False
        restored = {k: v for k, v in back.items() if v is not None}
        return all(forward.get(rel) == value for rel, value in after.items()) and restored == before

    def check_rollback(self, changed):
        check = self.run_dir / "rollback-check"
        shutil.copytree(self.candidate, check, symlinks=True)
        try:
            for rel, row in changed.items():
                path = healing.safe_destination(check, rel)
                if row["original"] is None:
                    path.unlink(missing_ok=True)
                else:
                    healing._write_bytes(check, rel, row["original"])
            return self._snapshot(check) == self.original
        finally:
            shutil.rmtree(check, ignore_errors=True)


def _diff(rel, before, after):
    a = "" if before is None else before.decode("utf-8")
    b = "" if after is None else after.decode("utf-8")
    lines = difflib.unified_diff(a.splitlines(keepends=True), b.splitlines(keepends=True),
                                 "/dev/null" if before is None else f"a/{rel}", "/dev/null" if after is None else f"b/{rel}")
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)


def verify_receipts(receipts):
    """True when every stage receipt hashes correctly and links to its predecessor."""
    previous = _ZERO
    for row in receipts:
        body = {key: value for key, value in row.items() if key != "receipt_sha256"}
        if row.get("previous_sha256") != previous or sha(body) != row.get("receipt_sha256") or row.get("stage") not in STAGES:
            return False
        previous = row["receipt_sha256"]
    return bool(receipts)


# --------------------------------------------------------------------------- entry point

def upgrade(target, *, command, workdir, now=None, tests=None, policy=None, extra_steps=None, environ=None):
    """Upgrade an existing system in an isolated copy under ``workdir``; never in place, never from scratch.

    ``command`` is the owner's Arabic or English command; the master router decides the mode
    (``«افحص»``/audit reads only and writes nothing, not even ``workdir``), scope and areas.
    ``tests`` overrides the suite (``{"start", "pattern"}``, else ``gaie-upgrade.json`` or
    ``tests/test*.py``). ``policy`` bounds the run (see ``POLICY``); network, deployment and
    production are refused. ``extra_steps`` are caller-declared changes (data, never
    instructions) that pass the same gates. Returns the report; artifacts (patch, rollback
    patch, rollback/ and backup/ copies, receipts, report) are written into the run directory.
    """
    started = time.monotonic()
    now = time.time() if now is None else _finite(now)
    policy = _policy(policy)
    root = _target(target)
    route = route_command(command, environ=environ, workspace=root)
    resolved_workdir = _workdir(workdir, root)
    manifest = load_manifest(root)
    spec_tests = _test_spec(tests if tests is not None else manifest.get("tests"), root)
    spec_rel, spec = _load_spec(root, manifest)
    extra = _extra_steps(extra_steps)
    requested = requested_changes(command, spec)
    _need(route["mode"] == "audit" or requested["status"] != "refused-breaking",
          "Requested change refused: it would remove data or functions (" + ", ".join(
              f"{row['kind']} {row.get('entity', '')}{'.' + row['field'] if row.get('field') else ''}".strip()
              for row in requested.get("breaking", [])) + "); a breaking change needs an owner-designed migration and approval")
    run = _Run(root, resolved_workdir, route, manifest, spec_tests, spec_rel, spec, policy, now)
    run.route_command, run.target_spec, run.requested = command, spec, requested
    if run.audit_only:
        return _audit_report(run, extra, started)
    run.prepare()
    run.receipt("ROUTE", {"command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest()}, route, "ok")
    run.checkpoint("ROUTE", ["route"], ["baseline", "audit", "plan", "apply", "regression", "report"],
                   f"Routed {route['intent']} ({route['scope']}) for {run.project}.")
    stage = time.monotonic()
    run.baseline()
    run.stage_seconds["BASELINE"] = time.monotonic() - stage
    stage = time.monotonic()
    run.audit()
    run.stage_seconds["AUDIT"] = time.monotonic() - stage
    run.plan(extra)
    stage = time.monotonic()
    if run.blocked:
        for step in run.ordered:
            step.update(status="not-run", reason=run.blocked)
    else:
        run.apply_all()
    run.stage_seconds["APPLY"] = time.monotonic() - stage
    stage = time.monotonic()
    run.regression()
    run.stage_seconds["REGRESSION"] = time.monotonic() - stage
    return _final_report(run, started)


def _usage(run, started):
    seconds = economics.total([economics.Seconds(d) for d in run.durations], economics.Seconds)
    return {"model_calls": 0, "provider_calls": 0, "model_tokens": economics.as_json(economics.Tokens(0)),
            "charged": economics.as_json(economics.Money("0")), "test_runs": run.test_runs,
            "sandbox_seconds": economics.as_json(seconds),
            "stage_seconds": {k: economics.as_json(economics.Seconds(round(v, 6))) for k, v in run.stage_seconds.items()},
            "wall_seconds": economics.as_json(economics.Seconds(round(time.monotonic() - started, 6))),
            "basis": "measured wall clock of local test runs; tokens and money are zero because no model or provider is called"}


GUARANTEES = {"applied_in_place": False, "isolated_copy": True, "network": "refused (policy) and loopback-only socket guard for target code",
              "deployment_allowed": False, "production_mutations": 0, "shell_used": False, "model_calls": 0, "os_sandbox_claimed": False,
              "data": "every baseline table keeps its row count and SHA-256 over its original columns after every migration",
              "functions": "every baseline top-level function, class, method and route still exists",
              "assets": "an asset leaves the copy only with a no-internal-reference proof and a verified backup",
              "tests": "existing test files are never edited; every baseline-passing test must still pass after every step",
              "requires_human_review": True}
LIMITS = ("Generators are a bounded deterministic catalogue: spec-derived input validation for apps that declare the "
          "dispatch convention, template accessibility/RTL fixes, SQLite indexes for filtered full scans, asset backups, "
          "self-healing via healing.heal, and caller-declared steps. Anything else is reported, not guessed. Proof of asset "
          "non-use is static (internal references only; external links cannot be ruled out, hence the backup). Data proofs "
          "cover SQLite files only. Tests prove only what they check; a passing run is not a release approval. The socket "
          "guard is Python-level, not an OS sandbox. Timings are measured and noisy; plans are deterministic.")


def _summary(run, status, applied):
    names = ", ".join(s["id"] for s in applied) or "none"
    unmet = run.requested.get("unmet") or []
    return {"en": f"{status}: {len(applied)} step(s) applied in an isolated copy ({names}); the original system is unchanged."
                  + (f" Requested but NOT implemented: {', '.join(unmet)}." if unmet else ""),
            "ar": f"الحالة {status}: طُبّقت {len(applied)} خطوة في نسخة معزولة ({names})؛ النظام الأصلي لم يتغير."
                  + (f" طُلب ولم يُنفَّذ: {', '.join(unmet)}." if unmet else "")}


def _audit_report(run, extra, started):
    before = run.original
    workdir_existed = run.workdir.exists()
    workdir_before = sorted(p.name for p in run.workdir.iterdir()) if workdir_existed else None
    run.receipt("ROUTE", {"command_sha256": hashlib.sha256(run.route_command.encode("utf-8")).hexdigest()}, run.route, "ok")
    run.baseline()
    run.audit()
    run.plan(extra)
    unchanged = run._snapshot(run.root) == before
    workdir_untouched = run.workdir.exists() == workdir_existed and (
        not workdir_existed or sorted(p.name for p in run.workdir.iterdir()) == workdir_before)
    proof = {"target_unchanged": unchanged, "workdir_untouched": workdir_untouched, "files_written": 0, "tests_executed": False,
             "memory_written": False}
    run.receipt("REPORT", {"mode": "audit"}, proof, "audited" if unchanged and workdir_untouched else "failed")
    result = {"schema_version": VERSION, "engine": ENGINE, "layers": list(LAYERS), "mode": "audit",
              "status": "audited" if unchanged and workdir_untouched else "audit-changed-something", "project": run.project,
              "route": run.route, "command": run.route_command, "language": run.route["language"],
              "target": {"original_sha256": sha(before), "files": len(before), "unchanged": unchanged},
              "baseline": run.baseline_report, "audit": run.audit_report, "plan": run.plan_report,
              "steps": [], "applied": [], "changes_made": False, "no_change_proof": proof, "patch": None, "artifacts": {},
              "memory": {"written": False, "reason": "audit is read-only"}, "usage": _usage(run, started),
              "receipts": run.receipts, "receipt_chain_valid": verify_receipts(run.receipts),
              "guarantees": {**GUARANTEES, "read_only": True}, "limits": LIMITS,
              "evidence": {"deterministic": ["route", "inventory", "static detectors", "audit findings", "plan"], "measured": [],
                           "simulated": [], "ai_reasoning": []},
              "summary": {"en": f"Audit only: {len(run.opportunities)} upgrade opportunities and {len(run.defects)} defect(s) found; nothing was changed.",
                          "ar": f"فحص فقط: وُجدت {len(run.opportunities)} فرصة تطوير و{len(run.defects)} عيب؛ لم يتغير شيء."}}
    result["report_sha256"] = sha(result)
    return result


def _final_report(run, started):
    applied = [s for s in run.steps if s["status"] == "applied"]
    troubled = [s for s in run.steps if s["status"] in ("rejected", "refused")]
    regression = run.regression_report
    validated = run.decision["status"] == "validated"
    if run.blocked and not applied:
        status = "blocked"
    elif not validated:
        status = "rejected"
    elif not applied:
        status = "no-change"
    elif run.requested.get("unmet"):
        status = "partially-upgraded"  # quality steps applied, but requested additions were not implemented
    else:
        status = "upgraded-with-rejections" if troubled else "upgraded"
    artifacts = {"upgraded_copy": str(run.candidate)}
    keep = validated and applied
    if run.changed:
        name = "upgrade.patch" if keep else "rejected.patch"
        healing._write_bytes(run.run_dir, name, run.patch.encode("utf-8"))
        healing._write_bytes(run.run_dir, "rollback.patch", run.reverse.encode("utf-8"))
        for rel, row in run.changed.items():
            if row["original"] is not None:
                healing._write_bytes(run.run_dir, f"rollback/{rel}", row["original"])
        artifacts.update({"patch": str(run.run_dir / name), "rollback_patch": str(run.run_dir / "rollback.patch"),
                          "rollback_dir": str(run.run_dir / "rollback"), "backup_dir": str(run.run_dir / "backup") if run.backups else None})
    rollback = {"method": "The target was never written. Apply rollback.patch to the upgraded copy (or never apply upgrade.patch), "
                          "restore every file under rollback/ (databases included) and every asset under backup/.",
                "original_tree_sha256": sha(run.original), "upgraded_tree_sha256": run.tree_sha(),
                "files": {rel: {"original_sha256": None if row["original"] is None else hashlib.sha256(row["original"]).hexdigest(),
                                "upgraded_sha256": None if row["current"] is None else hashlib.sha256(row["current"]).hexdigest(),
                                "restore_from": None if row["original"] is None else (f"backup/{rel}" if rel in run.backups else f"rollback/{rel}")}
                          for rel, row in run.changed.items()},
                "binary": regression["binary_changes"], "reverse_patch_sha256": hashlib.sha256(run.reverse.encode("utf-8")).hexdigest(),
                "verified": regression["checks"]["patch-and-reverse-apply"] and regression["checks"]["rollback-restores-original"]}
    run.checkpoint("REPORT", ["route", "baseline", "audit", "plan", "apply", "regression", "report"], [],
                   _summary(run, status, applied)["en"])
    if run.memory is not None:
        try:
            run.memory_report["final_checkpoint"] = run.memory.checkpoint(run.run_dir / "memory-checkpoint.json")
        except (_MemoryError, CoordinationError) as error:
            run.memory_report.setdefault("errors", []).append(f"checkpoint: {type(error).__name__}")
    run.receipt("REPORT", {"status": status}, {"applied": [s["id"] for s in applied], "patch_sha256": hashlib.sha256(run.patch.encode("utf-8")).hexdigest()},
                status, "workspace-write")
    result = {
        "schema_version": VERSION, "engine": ENGINE, "layers": list(LAYERS), "mode": "upgrade", "status": status, "project": run.project,
        "route": run.route, "command": run.route_command, "language": run.route["language"],
        "target": {"original_sha256": sha(run.original), "files": len(run.original), "unchanged": regression["checks"]["original-unchanged"]},
        "run_dir": str(run.run_dir), "upgraded_copy": str(run.candidate), "tests": run.tests, "policy": run.policy,
        "baseline": run.baseline_report, "audit": run.audit_report, "plan": run.plan_report, "steps": run.steps,
        "applied": [s["id"] for s in applied], "rejected": [s["id"] for s in troubled], "changes_made": bool(run.changed),
        "unmet_requests": run.requested.get("unmet", []),
        "regression": regression, "decision": run.decision, "blocked": run.blocked,
        "patch": run.patch if keep else None, "rejected_patch": None if keep or not run.changed else run.patch,
        "patch_sha256": hashlib.sha256(run.patch.encode("utf-8")).hexdigest(), "rollback": rollback, "artifacts": artifacts,
        "memory": run.memory_report, "usage": _usage(run, started), "receipts": run.receipts, "receipt_chain_valid": verify_receipts(run.receipts),
        "guarantees": {**GUARANTEES, "original_unchanged": regression["checks"]["original-unchanged"]}, "limits": LIMITS,
        "evidence": {"deterministic": ["route", "inventory", "detectors", "audit findings", "plan order", "trade-offs", "test outcomes",
                                       "data checksums", "asset proofs", "patch", "decision"],
                     "measured": ["test run durations"], "simulated": [], "ai_reasoning": []},
        "summary": _summary(run, status, applied),
    }
    result["report_sha256"] = sha(result)
    healing._write_bytes(run.run_dir, "receipts.json", canonical(run.receipts))
    healing._write_bytes(run.run_dir, "report.json", canonical(result))
    return result


# --------------------------------------------------------------------------- engine contract

ENGINE_ACTIONS = {
    "audit": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"],
              "summary": "Read-only audit of an existing system (route, inventory, detectors, upgrade plan); writes nothing."},
    "upgrade": {"side_effect": "workspace-write", "permissions": ["read:repo", "write:workspace", "exec:sandbox", "write:state", "secrets:none"],
                "summary": "Upgrade an existing system in an isolated copy with per-step receipts, regression proof, patch and rollback."},
}


def engine(action, payload, ctx=None):
    """Control-plane entrypoint ``(action, payload, ctx) -> dict``. Payloads are data, never instructions."""
    _need(action in ENGINE_ACTIONS, f"unknown action {action!r}; allowed {sorted(ENGINE_ACTIONS)}")
    _need(isinstance(payload, dict) and {"target", "command", "workdir"} <= set(payload) <= {"target", "command", "workdir", "tests", "policy"},
          "payload: target, command, workdir (tests, policy optional)")
    ctx = ctx or {}
    _need(action == "upgrade" or route_command(payload["command"], environ=ctx.get("environ"))["mode"] == "audit",
          "the audit action accepts only a read-only (audit) command; nothing was run")
    return upgrade(payload["target"], command=payload["command"], workdir=payload["workdir"], tests=payload.get("tests"),
                   policy=payload.get("policy"), now=ctx.get("now"), environ=ctx.get("environ"))


def health():
    """Side-effect-free self check: router classification of both languages and the migration guard."""
    try:
        verbs = [gaie_router.classify(text, gaie_router.policy())[0] for text in ("طور النظام", "upgrade the system", "افحص النظام")]
        guard = classify_migration("CREATE INDEX IF NOT EXISTS i ON t (a);")
        try:
            classify_migration("DROP TABLE t;")
            refused = False
        except UpgradeError:
            refused = True
        ok = verbs == [["upgrade"], ["upgrade"], ["audit"]] and guard[0]["kind"] == "create-index" and refused
    except Exception as error:  # health reports, never raises
        return {"ok": False, "detail": f"upgrade engine self-check failed: {type(error).__name__}"}
    return {"ok": ok, "detail": "router classifies Arabic and English upgrade/audit commands; data-losing migrations are refused"}
