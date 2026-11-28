"""Scenario I: the GAIE install, proved in a fresh HOME and a brand-new independent Git project.

The steps run real subprocesses: scripts/gaie_bootstrap.py (project and user scope), the
router and memory engine it installed, and, when the `claude` binary is on PATH, the
Claude Code plugin commands `--version`, `plugin validate|marketplace add|install|list|
details`. No model is called and no session is started: `claude` runs only through
`cli()`, which refuses any other argument list, with a scrubbed environment, the
temporary HOME, and HTTP(S)_PROXY pointing at a refused local port, so it reaches no
host. Without the binary (CI runners) the CLI test skips and says why.

One runner feeds both the tests and the evidence file, and one `failures()` judges both:
  python3 tests/test_gaie_install_scenario_i.py record        # writes docs/evidence/gaie-20-layers/scenario-i.json
The model-backed fresh-session check is separate and run once, by the integrator:
  python3 tests/test_gaie_install_scenario_i.py prepare-session --root DIR   # prints the one session command
  python3 tests/test_gaie_install_scenario_i.py record-session --root DIR     # files its output under fresh_session
See docs/specs/gaie-20-layers/INSTALL.md. SPDX-License-Identifier: MIT.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gaie_bootstrap  # noqa: E402

EVIDENCE = ROOT / "docs/evidence/gaie-20-layers/scenario-i.json"
SCHEMA = "gaie.scenario-i/1"
BOOTSTRAP = ROOT / "scripts/gaie_bootstrap.py"
RECORD = "python3 tests/test_gaie_install_scenario_i.py record"
CHECK = "python3 -m unittest tests.test_gaie_install_scenario_i"
ROUTES = {"طور فيديوهات سديد": ("CINEMATIC", "biz-pulse-ar"), "upgrade Sadeed": ("MASTER_UPGRADE", "biz-pulse-ar")}
CLI_COMMANDS = (("--version",), ("plugin", "validate"), ("plugin", "marketplace", "add"), ("plugin", "install"),
                ("plugin", "list"), ("plugin", "details"))
REFUSED_PROXY = "http://127.0.0.1:9"
# --strict warnings accepted for now, with the reason in INSTALL.md: the plugin root is the
# repository root (root CLAUDE.md), and agents/orchestrator/README.md is a document, not an agent.
ACCEPTED_WARNINGS = {"CLAUDE.md", "agents/orchestrator/README.md"}
NO_CLI = "the claude binary is not on PATH (CI runners have no Claude Code CLI); plugin steps not run"


def skills():
    return tuple(gaie_bootstrap.pack()["skills"])


def agents():
    return sorted(pathlib.PurePosixPath(path).stem for path in gaie_bootstrap.plan(True) if path.startswith("agents/"))


def sources():
    """Every file whose bytes define what Scenario I installs and runs, with its SHA-256."""
    paths = {"scripts/gaie_bootstrap.py", "catalog/packs.json", ".claude-plugin/plugin.json",
             ".claude-plugin/marketplace.json", "tests/test_gaie_install_scenario_i.py", "hub.py",
             *gaie_bootstrap.plan(False).values()}
    files = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sorted(paths)}
    digest = hashlib.sha256("".join(f"{path}\0{value}\n" for path, value in files.items()).encode()).hexdigest()
    return {"digest": digest, "files": files}


def _hub_revision():
    run = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    return (run.stdout.strip() or None), not dirty


class Lab:
    """A short temporary root holding fresh HOMEs, GAIE_HOME and independent Git projects."""

    def __init__(self, root=None):
        if root is None:
            base = "/tmp" if os.path.isdir("/tmp") and os.access("/tmp", os.W_OK) else None
            root = tempfile.mkdtemp(prefix="gi-", dir=base)
        self.root = pathlib.Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "tmp").mkdir(exist_ok=True)
        self.gaie_home = self.root / "gaie"
        self.claude = shutil.which("claude")

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def env(self, home, cli=False):
        path = [str(pathlib.Path(sys.executable).parent)] + ([str(pathlib.Path(self.claude).parent)] if self.claude else [])
        env = {"PATH": os.pathsep.join(dict.fromkeys(path + ["/usr/bin", "/bin"])), "HOME": str(home), "LANG": "C.UTF-8",
               "GAIE_HOME": str(self.gaie_home), "TMPDIR": str(self.root / "tmp"), "GIT_CONFIG_NOSYSTEM": "1"}
        if cli:  # no host is reachable: these steps prove the install needs no network and no account
            env.update({"HTTPS_PROXY": REFUSED_PROXY, "HTTP_PROXY": REFUSED_PROXY, "https_proxy": REFUSED_PROXY,
                        "http_proxy": REFUSED_PROXY, "NO_PROXY": "", "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1",
                        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
        return env

    def directory(self, name):
        path = self.root / name
        path.mkdir(parents=True)
        return path

    def project(self, name):
        path = self.directory(name)
        git = ["git", "-C", str(path), "-c", "user.name=scenario-i", "-c", "user.email=scenario-i@example.invalid",
               "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false"]
        env = self.env(self.root / "git-home")
        subprocess.run(git + ["init", "-q"], check=True, env=env, capture_output=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "independent project"], check=True, env=env, capture_output=True)
        return path

    def run(self, argv, cwd, home, cli=False, timeout=300):
        run = subprocess.run([str(part) for part in argv], capture_output=True, text=True, cwd=cwd,
                             env=self.env(home, cli), timeout=timeout)
        return run.returncode, run.stdout, run.stderr

    def cli(self, *args, cwd, home):
        if not self.claude:
            raise unittest.SkipTest(NO_CLI)
        if not any(tuple(args[:len(prefix)]) == prefix for prefix in CLI_COMMANDS) or {"-p", "--print"} & set(args):
            raise ValueError(f"refusing to run claude {' '.join(args)}: only no-model plugin commands are allowed")
        return self.run([self.claude, *args], cwd, home, cli=True)

    def scrub(self, value):
        """Public-safe copy: lab, hub and interpreter paths become placeholders."""
        pairs = [(str(self.root), "<lab>"), (str(ROOT), "<hub>"), (sys.executable, "python3")]
        if self.claude:
            pairs.append((self.claude, "claude"))
        pairs += [(os.path.realpath(old), new) for old, new in pairs if os.path.realpath(old) != old]
        if isinstance(value, str):
            for old, new in sorted(pairs, key=lambda pair: -len(pair[0])):
                value = value.replace(old, new)
            return value
        if isinstance(value, dict):
            return {self.scrub(key): self.scrub(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.scrub(item) for item in value]
        return value


def _json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _bootstrap(lab, steps, key, home, *args, cwd=None):
    rc, out, err = lab.run([sys.executable, BOOTSTRAP, *args], cwd or lab.root, home)
    data = _json(out) or {}
    steps[key] = {"argv": ["python3", "<hub>/scripts/gaie_bootstrap.py", *args], "rc": rc, "ok": data.get("ok"),
                  "error": data.get("error"), "files": data.get("files"), "stderr": err.strip()[-400:] or None}
    return steps[key]


def _locations(mode, skill_root, project_root):
    rows = {}
    for name, template in gaie_bootstrap.LOCATIONS[mode].items():
        skill_dir = skill_root / gaie_bootstrap.LOCATION_SKILL[name]
        path = template.replace("${CLAUDE_SKILL_DIR}", str(skill_dir))
        path = pathlib.Path(os.path.normpath(path if os.path.isabs(path) else project_root / path))
        rows[name] = {"named_as": template, "path": str(path), "exists": path.is_file()}
    return rows


def _route(lab, script, words, cwd, home, *prefix):
    rc, out, err = lab.run([sys.executable, "-s", script, *prefix, "route", words], cwd, home)
    plan = _json(out) or {}
    return {"argv": ["python3", "-s", str(script), *prefix, "route", words], "cwd": str(cwd), "rc": rc, "status": plan.get("status"),
            "engine": plan.get("engine"), "targets": [row.get("id") for row in plan.get("targets", [])],
            "write_allowed": plan.get("write_allowed"), "read_only": plan.get("read_only"),
            "gaie_skills_available": all(row.get("available") for row in plan.get("skills", []) if str(row.get("skill")).startswith("gaie-"))
            if plan.get("skills") else None, "stderr": err.strip()[-400:] or None}


def _memory(lab, engine, project, cwd, home):
    memory = engine / "gaie_memory.py"
    rc_add, out, _ = lab.run([sys.executable, "-s", memory, "--project", project, "add", "--kind", "lesson",
                              "--title", "scenario i", "--body", "installed memory engine"], cwd, home)
    rc_brief, brief, _ = lab.run([sys.executable, "-s", memory, "--project", project, "brief"], cwd, home)
    probe = f"import sys; sys.path.insert(0, {str(engine)!r}); import gaie_memory; print(gaie_memory.Memory({project!r}).backend)"
    _, backend, _ = lab.run([sys.executable, "-s", "-c", probe], cwd, home)
    store = lab.gaie_home / "memory" / project
    return {"argv": ["python3", "-s", str(memory), "--project", project, "add|brief"], "add_rc": rc_add,
            "add_status": (_json(out) or {}).get("status"), "brief_rc": rc_brief, "brief_entries": (_json(brief) or {}).get("entries"),
            "backend": backend.strip(), "store_files": sorted(p.name for p in store.iterdir()) if store.is_dir() else []}


def _registry(lab, engine, cwd, home):
    rc, out, _ = lab.run([sys.executable, "-s", engine / "gaie_router.py", "projects"], cwd, home)
    return {"argv": ["python3", "-s", str(engine / "gaie_router.py"), "projects"], "rc": rc,
            "sources": sorted({row.get("source") for row in (_json(out) or [])})}


def run_bootstrap(lab):
    """Project scope, user scope, hub checkout and plugin layout: everything that needs no Claude Code binary."""
    steps = {}
    project, home = lab.project("project"), lab.directory("home-project")
    claude = project / ".claude"
    engine = claude / "skills/gaie-master-router/engine"
    scope = ("--scope", "project", "--target", str(project))
    _bootstrap(lab, steps, "project.install.dry-run", home, "install", *scope)
    steps["project.install.dry-run"]["claude_dir_created"] = claude.exists()
    _bootstrap(lab, steps, "project.install.apply", home, "install", *scope, "--apply")
    _bootstrap(lab, steps, "project.verify", home, "verify", *scope)
    _bootstrap(lab, steps, "project.install.rerun", home, "install", *scope, "--apply")
    steps["project.locations"] = _locations("bootstrap", claude / "skills", project)
    for index, words in enumerate(ROUTES):
        steps[f"project.router.{index}"] = _route(lab, engine / "gaie_router.py", words, project, home)
    steps["project.memory"] = _memory(lab, engine, "scenario-i-project", project, home)
    steps["project.registry"] = _registry(lab, engine, project, home)
    steps["project.git-status"] = {"argv": ["git", "status", "--porcelain"], "entries": subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"], capture_output=True, text=True,
        env=lab.env(lab.root / "git-home")).stdout.splitlines()}

    link = lab.root / "project-link"
    link.symlink_to(project, target_is_directory=True)
    _bootstrap(lab, steps, "project.refuse.symlinked-target", home, "install", "--scope", "project", "--target", str(link), "--apply")
    outside = lab.directory("outside")
    linked = lab.project("project-linked-claude")
    (linked / ".claude").symlink_to(outside, target_is_directory=True)
    _bootstrap(lab, steps, "project.refuse.symlinked-claude", home, "install", "--scope", "project", "--target", str(linked), "--apply")
    steps["project.refuse.symlinked-claude"]["outside_untouched"] = not any(outside.iterdir())
    escaping = lab.project("project-escaping-skills")
    (escaping / ".claude").mkdir()
    (escaping / ".claude/skills").symlink_to(outside, target_is_directory=True)
    _bootstrap(lab, steps, "project.refuse.escaping-link", home, "install", "--scope", "project", "--target", str(escaping), "--apply")
    steps["project.refuse.escaping-link"]["outside_untouched"] = not any(outside.iterdir())
    steps["project.refuse.escaping-link"]["claude_entries"] = sorted(str(p.relative_to(escaping)) for p in (escaping / ".claude").rglob("*"))

    _bootstrap(lab, steps, "project.uninstall.dry-run", home, "uninstall", *scope)
    _bootstrap(lab, steps, "project.uninstall.apply", home, "uninstall", *scope, "--apply")
    steps["project.uninstall.apply"]["left_behind"] = sorted(str(p.relative_to(claude)) for p in claude.rglob("*")) if claude.exists() else []
    _bootstrap(lab, steps, "project.uninstall.rerun", home, "uninstall", *scope, "--apply")
    _bootstrap(lab, steps, "project.reinstall.apply", home, "install", *scope, "--apply")
    _bootstrap(lab, steps, "project.reinstall.rerun", home, "install", *scope, "--apply")

    user_home, empty = lab.directory("home-user"), lab.directory("empty")
    user_claude = user_home / ".claude"
    _bootstrap(lab, steps, "user.install.dry-run", user_home, "install", "--scope", "user")
    steps["user.install.dry-run"]["claude_dir_created"] = user_claude.exists()
    _bootstrap(lab, steps, "user.install.apply", user_home, "install", "--scope", "user", "--apply")
    _bootstrap(lab, steps, "user.verify", user_home, "verify", "--scope", "user")
    _bootstrap(lab, steps, "user.install.rerun", user_home, "install", "--scope", "user", "--apply")
    steps["user.locations"] = _locations("bootstrap", user_claude / "skills", empty)
    for index, words in enumerate(ROUTES):
        steps[f"user.router.{index}"] = _route(lab, user_claude / "skills/gaie-master-router/engine/gaie_router.py", words, empty, user_home)
    steps["user.memory"] = _memory(lab, user_claude / "skills/gaie-master-router/engine", "scenario-i-user", empty, user_home)
    linked_home = lab.directory("home-linked")
    (linked_home / ".claude").symlink_to(outside, target_is_directory=True)
    _bootstrap(lab, steps, "user.refuse.symlinked-claude", linked_home, "install", "--scope", "user", "--apply")
    _bootstrap(lab, steps, "user.uninstall.apply", user_home, "uninstall", "--scope", "user", "--apply")
    _bootstrap(lab, steps, "user.uninstall.rerun", user_home, "uninstall", "--scope", "user", "--apply")
    _bootstrap(lab, steps, "user.reinstall.apply", user_home, "install", "--scope", "user", "--apply")

    steps["hub-checkout.locations"] = _locations("hub-checkout", ROOT / ".claude/skills", ROOT)
    steps["hub-checkout.router"] = _route(lab, ROOT / "hub.py", "upgrade Sadeed", ROOT, home)
    steps["plugin-layout.locations"] = _locations("plugin", ROOT / "skills", project)
    steps["plugin-layout.router"] = _route(lab, ROOT / "skills/gaie-master-router/../../hub.py", "طور فيديوهات سديد", project, home)
    return steps


def _details(text):
    rows = {}
    for line in text.splitlines():
        match = re.match(r"\s+(Skills|Agents) \((\d+)\)\s*(.*)$", line)
        if match:
            rows[match.group(1).lower()] = [name.strip() for name in match.group(3).split(",") if name.strip()]
    return rows


def _report_files(report):
    rows = []
    for content in [report.get("manifest") or {}] + list(report.get("contents") or []):
        for kind in ("errors", "warnings"):
            for item in content.get(kind) or []:
                rows.append({"kind": kind, "file": content.get("file"), "message": item.get("message")})
    return rows


def run_cli(lab, project=None, home=None):
    """The Claude Code plugin path in a fresh HOME and an independent project; no model, no session, no network."""
    if not lab.claude:
        return {"status": "not-run", "reason": NO_CLI}
    project = project or lab.project("plugin-project")
    home = home or lab.directory("home-plugin")
    steps = {"status": "run"}
    rc, out, _ = lab.cli("--version", cwd=project, home=home)
    steps["cli.version"] = {"argv": ["claude", "--version"], "rc": rc, "version": out.strip()}
    for key, extra in (("cli.validate", ()), ("cli.validate.strict", ("--strict",))):
        rc, out, _ = lab.cli("plugin", "validate", *extra, "--json", str(ROOT), cwd=project, home=home)
        report = _json(out) or {}
        steps[key] = {"argv": ["claude", "plugin", "validate", *extra, "--json", "<hub>"], "rc": rc, "success": report.get("success"),
                      "skills": (report.get("provides") or {}).get("skills"), "agents": (report.get("provides") or {}).get("agents"),
                      "findings": _report_files(report),
                      "directory_checks": sorted(set(re.findall(r'"code": "([A-Z_]+)"', json.dumps(report.get("directory") or {}))))}
    rc, out, _ = lab.cli("plugin", "marketplace", "add", "--scope", "project", "--json", str(ROOT), cwd=project, home=home)
    steps["cli.marketplace.add"] = {"argv": ["claude", "plugin", "marketplace", "add", "--scope", "project", "--json", "<hub>"],
                                    "rc": rc, "result": _json(out.strip().splitlines()[-1] if out.strip() else "")}
    rc, out, _ = lab.cli("plugin", "install", "gaie@gaie-hub", "--scope", "project", "--json", cwd=project, home=home)
    steps["cli.install"] = {"argv": ["claude", "plugin", "install", "gaie@gaie-hub", "--scope", "project", "--json"], "rc": rc,
                            "result": _json(out.strip().splitlines()[-1] if out.strip() else "")}
    rc, out, _ = lab.cli("plugin", "list", "--json", cwd=project, home=home)
    listed = [row for row in (_json(out) or []) if row.get("id") == "gaie@gaie-hub"]
    steps["cli.list"] = {"argv": ["claude", "plugin", "list", "--json"], "rc": rc,
                         "gaie": {key: listed[0].get(key) for key in ("version", "scope", "enabled", "projectPath", "installPath")}
                         if listed else None}
    rc, out, _ = lab.cli("plugin", "details", "gaie@gaie-hub", cwd=project, home=home)
    steps["cli.details"] = {"argv": ["claude", "plugin", "details", "gaie@gaie-hub"], "rc": rc, **_details(out)}
    settings = project / ".claude/settings.json"
    steps["cli.project-settings"] = _json(settings.read_text(encoding="utf-8")) if settings.is_file() else None
    install = pathlib.Path(listed[0]["installPath"]) if listed and listed[0].get("installPath") else None
    if install and install.is_dir():
        steps["cli.plugin-root.locations"] = _locations("plugin", install / "skills", project)
        steps["cli.plugin-root.router"] = _route(lab, install / "skills/gaie-master-router/../../hub.py", "upgrade Sadeed", project, home)
        files = [path for path in install.rglob("*") if path.is_file() and not path.is_symlink()]
        steps["cli.cache"] = {"files": len(files), "bytes": sum(path.stat().st_size for path in files),
                              "has_pycache": any(path.parent.name == "__pycache__" for path in files)}
    # Files the CLI writes when it reaches the account API; their absence shows no host was reached.
    steps["cli.home"] = sorted(path.name for path in (home / ".claude").iterdir()) if (home / ".claude").is_dir() else []
    return steps


def failures(steps, cli):
    """Every expectation of Scenario I; an empty list means the recorded or live run passed."""
    found = []

    def need(condition, key, what):
        if not condition:
            found.append(f"{key}: {what}")

    planned = len(gaie_bootstrap.plan(False))
    for prefix in ("project", "user"):
        for key, state in (("install.dry-run", "would create"), ("install.apply", "created"), ("verify", "current"),
                           ("install.rerun", "unchanged"), ("reinstall.apply", "created")):
            row = steps.get(f"{prefix}.{key}") or {}
            values = list((row.get("files") or {}).values())
            need(row.get("rc") == 0 and row.get("ok") is True and len(values) == planned and set(values) == {state},
                 f"{prefix}.{key}", f"{planned} files {state}")
        need((steps.get(f"{prefix}.install.dry-run") or {}).get("claude_dir_created") is False, f"{prefix}.install.dry-run", "wrote nothing")
        need(all(row.get("exists") for row in (steps.get(f"{prefix}.locations") or {"-": {}}).values()), f"{prefix}.locations",
             "every path the skills name exists")
        for index, (words, (engine, target)) in enumerate(ROUTES.items()):
            row = steps.get(f"{prefix}.router.{index}") or {}
            need(row.get("rc") == 0 and row.get("status") == "routed" and row.get("engine") == engine
                 and row.get("targets") == [target] and row.get("write_allowed") is False and row.get("gaie_skills_available") is True,
                 f"{prefix}.router.{index}", f"installed router routes {words!r} to {engine}/{target}, no write grant")
        memory = steps.get(f"{prefix}.memory") or {}
        need(memory.get("backend") == "engine" and memory.get("add_status") == "stored" and memory.get("brief_rc") == 0
             and memory.get("brief_entries") == 1 and "memory.jsonl" in memory.get("store_files", [])
             and "entries.jsonl" not in memory.get("store_files", []), f"{prefix}.memory", "unified engine, not the journal")
        rerun = steps.get(f"{prefix}.uninstall.rerun") or {}
        need(rerun.get("rc") == 0 and rerun.get("files") == {}, f"{prefix}.uninstall.rerun", "second uninstall is a no-op")
        refused = steps.get(f"{prefix}.refuse.symlinked-claude") or {}
        need(refused.get("rc") == 1 and refused.get("error") == "symlinked .claude directory refused",
             f"{prefix}.refuse.symlinked-claude", "refused")
    user = steps.get("user.uninstall.apply") or {}
    need(user.get("rc") == 0 and set((user.get("files") or {}).values()) == {"removed"}, "user.uninstall.apply", "all removed")
    need("public-catalog" in (steps.get("project.registry") or {}).get("sources", []), "project.registry", "project registry module")
    need((steps.get("project.git-status") or {}).get("entries") == ["?? .claude/"], "project.git-status", "only .claude/ was written")
    for key, error in (("symlinked-target", "symlinked target directory refused"), ("escaping-link", "symlink refused: ")):
        row = steps.get(f"project.refuse.{key}") or {}
        need(row.get("rc") == 1 and str(row.get("error")).startswith(error), f"project.refuse.{key}", f"refused: {error}")
    for key in ("symlinked-claude", "escaping-link"):
        need((steps.get(f"project.refuse.{key}") or {}).get("outside_untouched") is True, f"project.refuse.{key}", "outside untouched")
    need((steps.get("project.refuse.escaping-link") or {}).get("claude_entries") == [".claude/skills"], "project.refuse.escaping-link",
         "refused before writing anything")
    for key, state in (("uninstall.dry-run", "would remove"), ("uninstall.apply", "removed"), ("reinstall.rerun", "unchanged")):
        row = steps.get(f"project.{key}") or {}
        values = list((row.get("files") or {}).values())
        need(row.get("rc") == 0 and len(values) == planned and set(values) == {state}, f"project.{key}", f"{planned} files {state}")
    need((steps.get("project.uninstall.apply") or {}).get("left_behind") == ["agents", "skills"], "project.uninstall.apply",
         "only the shared agents/ and skills/ directories stay (kept by design), with no GAIE file or bytecode cache")
    for mode in ("hub-checkout", "plugin-layout"):
        need(all(row.get("exists") for row in (steps.get(f"{mode}.locations") or {"-": {}}).values()), f"{mode}.locations", "paths exist")
        row = steps.get(f"{mode}.router") or {}
        need(row.get("rc") == 0 and row.get("status") == "routed", f"{mode}.router", "routes")

    if cli.get("status") == "not-run":
        need(cli.get("reason") == NO_CLI, "cli", "states why it did not run")
        return found
    need(re.fullmatch(r"\d+\.\d+\.\d+ \(Claude Code\)", (cli.get("cli.version") or {}).get("version", "")), "cli.version", "a version")
    gaie = {f"gaie:{name}" for name in skills()}
    for key, success in (("cli.validate", True), ("cli.validate.strict", None)):
        row = cli.get(key) or {}
        need(gaie <= set(row.get("skills") or []) and "gaie:gaie-verifier" in (row.get("agents") or []), key, "lists the gaie skills and agent")
        files = {re.sub(r"^(?:<hub>|" + re.escape(str(ROOT)) + r")/", "", str(item["file"])) for item in row.get("findings", [])}
        need(files <= ACCEPTED_WARNINGS, key, f"no findings beyond the accepted ones: {sorted(files - ACCEPTED_WARNINGS)}")
        if success:
            need(row.get("rc") == 0 and row.get("success") is True, key, "passes")
    for key in ("cli.marketplace.add", "cli.install"):
        row = cli.get(key) or {}
        need(row.get("rc") == 0 and (row.get("result") or {}).get("outcome") == "ok", key, "ok")
    listed = (cli.get("cli.list") or {}).get("gaie") or {}
    version = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
    need(listed.get("enabled") is True and listed.get("scope") == "project" and listed.get("version") == version, "cli.list",
         f"gaie@gaie-hub {version} enabled in the project")
    details = cli.get("cli.details") or {}
    need(set(skills()) <= set(details.get("skills", [])) and details.get("agents") == agents(), "cli.details",
         f"skills include the six gaie skills and agents are exactly {agents()}")
    settings = cli.get("cli.project-settings") or {}
    need(settings.get("enabledPlugins") == {"gaie@gaie-hub": True}, "cli.project-settings", "enabled in committable project settings")
    need(all(row.get("exists") for row in (cli.get("cli.plugin-root.locations") or {"-": {}}).values()), "cli.plugin-root.locations",
         "paths the skills name exist in the installed plugin root")
    row = cli.get("cli.plugin-root.router") or {}
    need(row.get("rc") == 0 and row.get("status") == "routed" and row.get("engine") == "MASTER_UPGRADE", "cli.plugin-root.router", "routes")
    need(not {"policy-limits.json", "remote-settings.json"} & set(cli.get("cli.home") or ["?"]) and "plugins" in (cli.get("cli.home") or []),
         "cli.home", "the CLI reached no account API (no policy-limits.json or remote-settings.json in the fresh HOME)")
    return found


FRESH_PROMPT = ("Reply with two lists and nothing else: the names of the skills you can invoke whose names contain "
                "'gaie', and the names of the agents (subagent types) you can delegate to. Do not call any tool.")
FRESH_FLAGS = ("--output-format", "stream-json", "--verbose", "--strict-mcp-config", "--no-session-persistence",
               "--max-budget-usd", "0.25", "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch")


def session_command(root):
    root = pathlib.Path(root)
    return (f"cd {shlex.quote(str(root / 'project'))} && env -i PATH=\"$PATH\" HOME={shlex.quote(str(root / 'home'))} LANG=C.UTF-8 "
            f"claude -p {shlex.quote(FRESH_PROMPT)} {' '.join(shlex.quote(flag) for flag in FRESH_FLAGS)} "
            f"> {shlex.quote(str(root / 'session.jsonl'))}")


def fresh_session_pending():
    return {"status": "pending",
            "reason": "Model-backed: it starts one billed Claude Code session. Lane agents never start one; the integrator runs it "
                      "once on the final head, after re-recording the no-model steps there.",
            "prepare": "python3 tests/test_gaie_install_scenario_i.py prepare-session --root <empty short dir>",
            "command": session_command("<root>"),
            "record": "python3 tests/test_gaie_install_scenario_i.py record-session --root <root>",
            "proves": "that a new Claude Code process started in an independent project, with a fresh HOME, discovers the six gaie-* "
                      "skills and gaie-verifier from a project-scope bootstrap (un-namespaced) and from a project-scope plugin "
                      "install (gaie: prefix), as listed by the harness's own init event",
            "does_not_prove": ["that a model follows the skills correctly", "user-scope persistence across sessions",
                               "interactive /plugin install or trust prompts", "an install from the GitHub default branch"]}


def prepare_session(root):
    """Fresh HOME + independent project with a project-scope bootstrap and a project-scope plugin install, both no-model."""
    lab = Lab(root)
    if any(path.name in ("home", "project") for path in lab.root.iterdir()):
        raise SystemExit(f"{lab.root} already holds home/ or project/: use an empty directory")
    if not lab.claude:
        raise SystemExit(NO_CLI)
    project, home = lab.project("project"), lab.directory("home")
    steps = {}
    _bootstrap(lab, steps, "bootstrap", home, "install", "--scope", "project", "--target", str(project), "--apply")
    cli = run_cli(lab, project=project, home=home)
    problems = [key for key in ("cli.marketplace.add", "cli.install") if (cli.get(key) or {}).get("rc") != 0]
    if steps["bootstrap"]["rc"] != 0 or problems:
        raise SystemExit(f"preparation failed: {steps['bootstrap'].get('error') or problems}")
    (lab.root / "prepared.json").write_text(json.dumps({"sources": sources()["digest"], "hub_revision": _hub_revision()[0]}) + "\n")
    print(session_command(lab.root))


def record_session(root, out=EVIDENCE, stream=None):
    """File one headless session's stream-json output under fresh_session of the evidence file."""
    lab = Lab(root)
    stream = pathlib.Path(stream or lab.root / "session.jsonl")
    prepared = json.loads((lab.root / "prepared.json").read_text())
    doc = json.loads(pathlib.Path(out).read_text(encoding="utf-8"))
    current = sources()["digest"]
    if not (prepared["sources"] == doc["sources"]["digest"] == current):
        raise SystemExit(f"sources changed since the no-model record or the preparation: run `{RECORD}` and prepare again")
    events = [json.loads(line) for line in stream.read_text(encoding="utf-8").splitlines() if line.strip().startswith("{")]
    init = next(event for event in events if event.get("type") == "system" and event.get("subtype") == "init")
    result = next((event for event in reversed(events) if event.get("type") == "result"), {})
    seen = {"skills": sorted(init.get("skills") or []), "slash_commands": sorted(init.get("slash_commands") or []),
            "agents": sorted(init.get("agents") or [])}
    names = set(seen["skills"]) | set(seen["slash_commands"])
    checks = {"bootstrap_skills": sorted(set(skills()) & names), "plugin_skills": sorted({f"gaie:{n}" for n in skills()} & names),
              "bootstrap_agent": "gaie-verifier" in seen["agents"], "plugin_agent": "gaie:gaie-verifier" in seen["agents"]}
    doc["fresh_session"] = lab.scrub({
        "status": "recorded", "recorded_on": datetime.date.today().isoformat(), "hub_revision": prepared["hub_revision"],
        "sources_digest": current, "command": session_command(lab.root), "claude_code_version": init.get("claude_code_version"),
        "cwd": init.get("cwd"), **seen, "plugins": init.get("plugins"), "plugin_errors": init.get("plugin_errors"),
        "checks": checks, "passed": checks["bootstrap_skills"] == sorted(skills()) and len(checks["plugin_skills"]) == len(skills())
        and checks["bootstrap_agent"] and checks["plugin_agent"],
        "result": {key: result.get(key) for key in ("subtype", "is_error", "num_turns", "total_cost_usd", "duration_ms")},
        "reply": str(result.get("result") or "")[:2000]})
    pathlib.Path(out).write_text(json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps(doc["fresh_session"]["checks"]))


OBSERVATIONS = [
    {"label": "observation, not a new-session proof",
     "text": "In the cloud Claude Code session that ran this recovery (cwd = the hub checkout), the six gaie-* skills and the "
             "gaie-verifier agent were discovered from the committed .claude/ directory after the checkout put them on disk, "
             "as reported by the session that orchestrated the recovery; the six skills also appear un-namespaced in the "
             "skill list of the lane session that recorded this file. That session began on main, which has no GAIE files, "
             "so this shows discovery from a committed .claude/ directory, not discovery by a new process in an "
             "independent project."}]
NOT_PROVEN = [
    "User-scope persistence across cloud sessions: a cloud container starts with a fresh ~/.claude, so only a workstation or a "
    "second session on the same machine can show it.",
    "Interactive /plugin install, marketplace trust prompts and plugin enablement on a claude.ai account: interactive or "
    "account-level, not reachable from a no-model test.",
    "Anything installed from the GitHub default branch: main does not contain these files before the integration branch is "
    "merged; see the post-merge checklist in docs/specs/gaie-20-layers/INSTALL.md.",
    "That a model follows the skills: the fresh_session section covers discovery only.",
    "A local-folder marketplace reads the plugin from the hub checkout; it says nothing about the GitHub source or network "
    "allowlists."]


def record(out=EVIDENCE):
    lab = Lab()
    try:
        steps, cli = run_bootstrap(lab), run_cli(lab)
        problems = failures(steps, cli)
        if problems:
            raise SystemExit("Scenario I failed; nothing written:\n" + "\n".join(problems))
        revision, clean = _hub_revision()
        old = _json(pathlib.Path(out).read_text(encoding="utf-8")) if pathlib.Path(out).is_file() else None
        doc = {"schema": SCHEMA, "scenario": "I", "title": "GAIE install in a fresh HOME and an independent Git project",
               "kind": "measured", "simulated": False, "model_calls": 0, "network": "no step reaches a host; the CLI runs with HTTP(S)_PROXY at a refused local port",
               "produced_by": RECORD, "checked_by": CHECK, "recorded_on": datetime.date.today().isoformat(),
               "hub_revision": revision, "hub_worktree_clean": clean, "sources": sources(),
               "host": {"python": platform.python_version(), "system": platform.system().lower(),
                        "git": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip(),
                        "claude_cli": (cli.get("cli.version") or {}).get("version")},
               "isolation": {"lab": "one new short temporary directory, removed afterwards",
                             "homes": "a new empty HOME per mode (project, user, plugin)",
                             "projects": "git init plus one empty commit, outside the hub",
                             "environment": sorted(lab.env(lab.root, cli=True)),
                             "cli": "only --version and plugin validate|marketplace add|install|list|details; HTTP(S)_PROXY "
                                    "point at a refused local port"},
               "steps": lab.scrub(steps), "cli": lab.scrub(cli),
               "fresh_session": (old or {}).get("fresh_session") if (old or {}).get("sources", {}).get("digest") == sources()["digest"]
               and ((old or {}).get("fresh_session") or {}).get("status") == "recorded" else fresh_session_pending(),
               "observations": OBSERVATIONS, "not_proven": NOT_PROVEN}
        pathlib.Path(out).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}: {len(steps)} bootstrap steps, CLI {cli.get('status')}")
    finally:
        lab.cleanup()


class ScenarioI(unittest.TestCase):
    """No-model install paths, end to end, in a fresh HOME and a brand-new independent Git project."""

    @classmethod
    def setUpClass(cls):
        cls.lab = Lab()
        cls.addClassCleanup(cls.lab.cleanup)
        cls.steps = run_bootstrap(cls.lab)
        cls.problems = failures(cls.steps, {"status": "not-run", "reason": NO_CLI})

    def problems_for(self, *prefixes):
        return [problem for problem in self.problems if problem.startswith(prefixes)]

    def test_lab_is_independent_of_the_hub_and_short(self):
        self.assertFalse(self.lab.root.is_relative_to(ROOT))
        self.assertLess(len(str(self.lab.root)), 60)
        self.assertNotIn("PYTHONPATH", self.lab.env(self.lab.root))

    def test_project_scope_install_verify_and_rerun(self):
        self.assertEqual(self.problems_for("project.install", "project.verify", "project.git-status"), [])

    def test_installed_router_routes_arabic_and_english(self):
        self.assertEqual(self.problems_for("project.router", "user.router", "project.locations", "user.locations"), [])
        self.assertEqual({self.steps[f"project.router.{i}"]["engine"] for i in range(len(ROUTES))}, {"CINEMATIC", "MASTER_UPGRADE"})

    def test_installed_memory_is_the_unified_engine(self):
        self.assertEqual(self.problems_for("project.memory", "user.memory", "project.registry"), [])

    def test_symlinked_or_escaping_targets_are_refused(self):
        self.assertEqual(self.problems_for("project.refuse", "user.refuse"), [])

    def test_uninstall_and_reinstall_are_idempotent(self):
        self.assertEqual(self.problems_for("project.uninstall", "project.reinstall", "user.uninstall", "user.reinstall"), [])

    def test_user_scope_install_verify_and_rerun(self):
        self.assertEqual(self.problems_for("user.install", "user.verify"), [])

    def test_hub_checkout_and_plugin_layout_name_existing_paths(self):
        self.assertEqual(self.problems_for("hub-checkout", "plugin-layout"), [])

    def test_judge_rejects_a_journal_fallback_and_a_missing_route(self):
        broken = json.loads(json.dumps(self.steps))
        broken["project.memory"]["backend"] = "portable-journal"
        broken["user.router.1"]["engine"] = None
        problems = failures(broken, {"status": "not-run", "reason": NO_CLI})
        self.assertTrue(any(p.startswith("project.memory") for p in problems))
        self.assertTrue(any(p.startswith("user.router.1") for p in problems))


class ScenarioIClaudeCode(unittest.TestCase):
    """Claude Code plugin validation and a local-marketplace install, only when the binary exists."""

    @classmethod
    def setUpClass(cls):
        cls.lab = Lab()
        cls.addClassCleanup(cls.lab.cleanup)
        if not cls.lab.claude:
            raise unittest.SkipTest(NO_CLI)
        cls.cli = run_cli(cls.lab)

    def test_validate_install_and_details_list_the_skills_and_agents(self):
        problems = [p for p in failures({}, self.cli) if p.startswith("cli")]
        self.assertEqual(problems, [])
        self.assertEqual(self.cli["cli.details"]["agents"], agents())

    def test_cli_runner_refuses_model_backed_commands(self):
        for args in (("-p", "hi"), ("plugin", "install", "x", "-p", "hi"), ("--print", "x"), ("auth", "status"), ()):
            with self.assertRaises(ValueError, msg=args):
                self.lab.cli(*args, cwd=self.lab.root, home=self.lab.root)


class ScenarioIEvidence(unittest.TestCase):
    """docs/evidence/gaie-20-layers/scenario-i.json: measured here, bound to the sources, judged by failures()."""

    @classmethod
    def setUpClass(cls):
        cls.text = EVIDENCE.read_text(encoding="utf-8")
        cls.doc = json.loads(cls.text)

    def test_evidence_is_bound_to_the_current_sources(self):
        self.assertEqual(self.doc["sources"], sources(), f"sources changed: re-run `{RECORD}`")

    def test_recorded_steps_pass_the_same_judge(self):
        self.assertEqual((self.doc["schema"], self.doc["simulated"], self.doc["model_calls"]), (SCHEMA, False, 0))
        self.assertEqual(failures(self.doc["steps"], self.doc["cli"]), [])
        self.assertEqual(self.doc["produced_by"], RECORD)

    def test_fresh_session_is_pending_or_a_passing_record_of_these_sources(self):
        session = self.doc["fresh_session"]
        self.assertIn(session["status"], ("pending", "recorded"))
        if session["status"] == "pending":
            self.assertTrue(session["reason"] and "-p" in session["command"] and "record-session" in session["record"])
            for flag in ("stream-json", "--max-budget-usd", "--strict-mcp-config", "--no-session-persistence"):
                self.assertIn(flag, session["command"])
        else:
            self.assertEqual(session["sources_digest"], self.doc["sources"]["digest"])
            self.assertTrue(session["passed"], session["checks"])

    def test_evidence_is_public_safe_and_states_its_limits(self):
        for private in ("/home/", "/root", "/tmp/"):
            self.assertNotIn(private, self.text)
        self.assertTrue(self.doc["not_proven"] and self.doc["observations"])
        self.assertTrue(all(row["label"].startswith("observation, not") for row in self.doc["observations"]))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("record", "prepare-session", "record-session"):
        parser = argparse.ArgumentParser(description="Scenario I evidence")
        parser.add_argument("command", choices=("record", "prepare-session", "record-session"))
        parser.add_argument("--root", help="empty short directory for the fresh-session lab (kept)")
        parser.add_argument("--out", default=str(EVIDENCE))
        parser.add_argument("--stream", help="stream-json output of the session (default <root>/session.jsonl)")
        args = parser.parse_args()
        if args.command == "record":
            record(args.out)
        elif not args.root:
            parser.error("--root is required")
        elif args.command == "prepare-session":
            prepare_session(args.root)
        else:
            record_session(args.root, args.out, args.stream)
    else:
        unittest.main()
