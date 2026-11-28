"""GAIE master router: owner commands in Arabic or English to a verifiable plan.

Deterministic and offline. It classifies the task, resolves the project against
the registries, and selects the engine, skills, workstreams and gates. It never
guesses a repository: an unknown, ambiguous or conflicting target stops with
`needs-clarification`. A route is a plan; it proves nothing about execution.
Standard library only so the file can be vendored. SPDX-License-Identifier: MIT.
"""
import argparse
import difflib
import json
import os
import pathlib
import re
import subprocess
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MAX_TEXT = 2000
_NAME = r"(?!\.+(?:\.git)?/?$)([A-Za-z0-9_.-]+)"
_REPO = r"(?!\.+(?:\.git)?/?$)([A-Za-z0-9_.-]+?)(?:\.git)?/?"
REPOSITORY = re.compile(r"https://github\.com/" + _NAME + "/" + _REPO)
REMOTES = (re.compile(r"(?:https://(?:[^/@\s]+@)?github\.com/|ssh://git@github\.com/|git@github\.com:)" + _NAME + "/" + _REPO),
           re.compile(r"https?://(?:[^/@\s]+@)?(?:127\.0\.0\.1|localhost)(?::\d+)?/git/" + _NAME + "/" + _REPO))
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_DIACRITICS = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه"})
_APOSTROPHES = re.compile("['\u2018\u2019\u02bc\u00b4`\uff07]")
_CLAUSE = re.compile(r"[,\u060c.;\u061b!?\u061f:()\n]+")
_WORD = re.compile(r"[^\W_]+(?:-[^\W_]+)*")
_PHRASE_PREFIX = re.compile("^(?:و|ف)?(?:ب|ل|ك)?(?:ال)?")
_ALIAS_PREFIX = re.compile("^(?:و|ف)?(?:ب|ل)?")
_ARABIC = re.compile("[\u0621-\u064a]")


class RouteError(ValueError):
    pass


def _fold(text):
    if not isinstance(text, str):
        raise RouteError("command must be text")
    text = unicodedata.normalize("NFKC", text)
    return _APOSTROPHES.sub("", _DIACRITICS.sub("", text).translate(_FOLD).casefold())


def normalize(text):
    """Fold case, Arabic diacritics and letter variants; return word tokens."""
    return _WORD.findall(_fold(text))


def clauses(text):
    """Token lists per punctuation-delimited clause."""
    return [tokens for tokens in (_WORD.findall(part) for part in _CLAUSE.split(_fold(text))) if tokens]


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise RouteError("duplicate JSON key")
        result[key] = value
    return result


def _load(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"), object_pairs_hook=_pairs)


def _first(*candidates):
    for path in candidates:
        if path.is_file():
            return path
    raise RouteError(f"missing routing data: {candidates[0].name}")


def policy():
    return _load(_first(HERE / "gaie-routes.json", ROOT / "governance/policies/gaie-routes.json"))


def gaie_home(environ=None):
    """Private state directory. It must not live inside a Git work tree."""
    environ = os.environ if environ is None else environ
    home = pathlib.Path(environ.get("GAIE_HOME") or pathlib.Path.home() / ".gaie").expanduser().resolve()
    for parent in (home, *home.parents):
        if (parent / ".git").exists():
            raise RouteError("GAIE_HOME must be outside every Git repository")
    return home


def _slug_of(repository):
    match = REPOSITORY.fullmatch(repository or "")
    if not match:
        raise RouteError("project repository must be an https://github.com/owner/name URL")
    return f"{match.group(1)}/{match.group(2)}".casefold()


def projects(environ=None):
    """Public registry rows plus the private overlay, with normalized aliases."""
    rows = {}
    public = _first(HERE / "projects.json", ROOT / "projects/registry.json")
    aliases = _load(_first(HERE / "aliases.json", ROOT / "projects/aliases.json")).get("aliases", {})
    for row in _load(public).get("projects", []):
        rows[row["id"]] = {"id": row["id"], "repository": row["repository"], "visibility": "public",
                           "source": "public-registry", "aliases": [row["id"], *aliases.get(row["id"], [])]}
    unknown = set(aliases) - set(rows)
    if unknown:
        raise RouteError(f"alias for unregistered project: {sorted(unknown)[0]}")
    overlay = gaie_home(environ) / "projects.json"
    if overlay.is_symlink():
        raise RouteError("private registry symlink refused")
    if overlay.is_file():
        data = _load(overlay)
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1 \
                or not isinstance(data.get("projects"), list):
            raise RouteError("invalid private project registry")
        for row in data["projects"]:
            if not isinstance(row, dict):
                raise RouteError("private project rows must be objects")
            key = row.get("id")
            if not isinstance(key, str) or not SLUG.fullmatch(key) or key in rows:
                raise RouteError("private project id invalid or already registered")
            names = row.get("aliases", [])
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                raise RouteError("private project aliases must be a list of text")
            if row.get("visibility", "private") not in ("private", "public"):
                raise RouteError("private project visibility must be private or public")
            rows[key] = {"id": key, "repository": row.get("repository"), "visibility": row.get("visibility", "private"),
                         "source": "private-overlay", "aliases": [key, *names]}
    rules = policy()
    reserved = _words([w for group in rules["verbs"].values() for w in group]) | _words(rules["negations"]) \
        | _words(rules["coordinators"]) | _words(rules["clause_breaks"]) | _words(rules["fillers"])
    for row in rows.values():
        row["slug"] = _slug_of(row["repository"])
        row["_keys"] = sorted({tuple(normalize(a)) for a in row["aliases"] if normalize(a)})
        for key in row["_keys"]:
            if any(token in reserved or _strip(token, _ALIAS_PREFIX) in reserved for token in key):
                raise RouteError("a project alias contains a command word; rename it")
    keyed = [(key, row["id"]) for row in rows.values() for key in row["_keys"]]
    for key, owner in keyed:
        for other, other_owner in keyed:
            if owner != other_owner and _find(list(other), list(key), _ALIAS_PREFIX):
                raise RouteError("one project alias matches inside another project's alias; fix the registry before routing")
    slugs = [row["slug"] for row in rows.values()]
    if len(slugs) != len(set(slugs)):
        raise RouteError("one repository is registered under two projects")
    return rows


def _strip(token, pattern=_PHRASE_PREFIX):
    if not _ARABIC.search(token):
        return token
    rest = pattern.sub("", token, count=1)
    return rest if len(rest) >= 2 else token


def _find(tokens, phrase, pattern=_PHRASE_PREFIX):
    """Start indexes of a normalized phrase. Only the spoken token may carry a prefix."""
    size = len(phrase)
    return [index for index in range(len(tokens) - size + 1)
            if all(token == word or _strip(token, pattern) == word
                   for token, word in zip(tokens[index:index + size], phrase))]


def _lexicon(groups):
    return {name: [normalize(word) for word in words if normalize(word)] for name, words in groups.items()}


def _words(values):
    return {token for value in values for token in normalize(value)}


def _conjoined(token):
    """(bare token, had a conjunction prefix) for Arabic و/ف."""
    if _ARABIC.search(token) and token[:1] in "وف" and len(token) > 2:
        return token[1:], True
    return token, False


def _verb(token, verbs):
    """(verb class, is imperative) for one token, or (None, False)."""
    for name, words in verbs.items():
        for word in words:
            if token == word:
                return name, True
            if _ARABIC.search(word):
                for suffix in ("ه", "ها", "هم", "وا", "ي"):
                    if token == word + suffix:
                        return name, True
                stem = word[1:] if word.startswith("ا") else word
                for prefix in "تين":
                    if token in (prefix + stem, *(prefix + stem + suffix for suffix in ("ه", "ها", "هم", "وا"))):
                        return name, False
    return None, False


def classify(text, rules):
    """(commanded verbs in order, prohibited verbs, focus, all-projects, any negation).

    A verb is a command only as an imperative at the start of a clause or after a
    coordinator. Any verb form after a negation in its clause is prohibited.
    Other mentions (questions, statements, nouns) are ignored.
    """
    verbs = {name: {word for phrase in normalize_all(words) for word in phrase} for name, words in rules["verbs"].items()}
    negations, fillers = _words(rules["negations"]), _words(rules["fillers"])
    coordinators, breaks = _words(rules["coordinators"]), _words(rules["clause_breaks"])
    nouns = _words(rules["noun_followers"])
    wanted, prohibited, negated = [], [], False
    for clause in clauses(text):
        blocked, position = False, True
        for index, token in enumerate(clause):
            bare, joined = _conjoined(token)
            if token in breaks or bare in breaks:
                blocked, position = False, True
                continue
            if token in negations or bare in negations:
                blocked = negated = True
                continue
            if token in fillers:
                continue
            if token in coordinators:
                position = True
                continue
            name, imperative = _verb(token, verbs)
            if name is None and joined:
                name, imperative = _verb(bare, verbs)
            following = clause[index + 1] if index + 1 < len(clause) else None
            if name is not None and following not in nouns:
                if blocked:
                    if name not in prohibited:
                        prohibited.append(name)
                elif imperative and (position or joined) and name not in wanted:
                    wanted.append(name)
            position = False
    wanted = [name for name in wanted if name not in prohibited]
    tokens = normalize(text)
    focus = sorted(name for name, phrases in _lexicon(rules["focus"]).items()
                   if any(_find(tokens, phrase) for phrase in phrases))
    everything = any(_find(tokens, normalize(phrase)) for phrase in rules["all_projects"])
    return wanted, prohibited, focus, everything, negated


def normalize_all(words):
    return [normalize(word) for word in words if normalize(word)]


def resolve(tokens, registry):
    matched = [row for row in registry.values() if any(_find(tokens, list(key), _ALIAS_PREFIX) for key in row["_keys"])]
    suggestions = []
    if not matched:
        names = {" ".join(key): row["id"] for row in registry.values() for key in row["_keys"]}
        for token in {_strip(t, _ALIAS_PREFIX) for t in tokens} | set(tokens):
            for close in difflib.get_close_matches(token, list(names), n=2, cutoff=0.8):
                suggestions.append(names[close])
    return matched, sorted(set(suggestions))


def remote_slug(url):
    """owner/name for a GitHub remote or the local Git proxy; None for any other host."""
    for pattern in REMOTES:
        match = pattern.fullmatch(url.strip())
        if match:
            return f"{match.group(1)}/{match.group(2)}".casefold()
    return None


def workspace(path):
    """owner/name of a checkout's origin remote, or None. Read-only."""
    environ = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        result = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"],
                                capture_output=True, text=True, timeout=10, check=False, env=environ)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return remote_slug(result.stdout) if result.returncode == 0 else None


def _skills(names):
    roots = [ROOT / "skills", pathlib.Path.cwd() / ".claude/skills", HERE.parents[1] if HERE.name == "engine" else HERE]
    return [{"skill": name, "available": any((root / name / "SKILL.md").is_file() for root in roots)} for name in names]


def _clarify(reason, **extra):
    return {"schema_version": 1, "status": "needs-clarification", "reason": reason, "write_allowed": False, **extra}


def _public(row):
    return {key: row[key] for key in ("id", "repository", "visibility", "source")}


def route(text, *, environ=None, workspace_path=None):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise RouteError("command must be 1-2000 characters")
    rules = policy()
    tokens = normalize(text)
    verbs, prohibited, focus, everything, negated = classify(text, rules)
    registry = projects(environ)
    matched, suggestions = resolve(tokens, registry)
    if not verbs:
        return _clarify("No command recognized. Start with what to do (build, upgrade, speed up, audit, fix, release); "
                        "questions, statements and negated operations are not executed.", prohibited=prohibited, focus=focus)
    primary = [v for v in verbs if not any(v in rules["subsumes"].get(other, []) for other in verbs if other != v)]
    if len(primary) != 1:
        return _clarify("The command asks for several different operations; run one at a time.", candidates=verbs,
                        prohibited=prohibited)
    verb = primary[0]
    if negated and verb == "release":
        return _clarify("The command mentions a release together with a negation. Confirm in one plain sentence whether to release.",
                        prohibited=prohibited)
    if negated and (len(matched) > 1 or everything):
        return _clarify("The command names several projects together with a negation; say exactly which project to act on.",
                        projects=[_public(row) for row in matched], prohibited=prohibited)
    intent = "cinematic" if verb == "upgrade" and focus and set(focus) <= {"media", "motion"} and "media" in focus else verb
    engine = rules["engines"][intent]
    if intent == "build":
        if matched or everything:
            return _clarify("Build creates a new system, but the command names an existing project. Say upgrade, or name the new system.",
                            projects=[_public(row) for row in matched])
        if suggestions:
            return _clarify("Build creates a new system, but a word resembles a registered project. Say upgrade with the exact "
                            "project name, or confirm this is a new system.", suggestions=suggestions)
        targets, scope = [], "new-project"
    elif everything:
        if matched:
            return _clarify("The command names both one project and all projects.", projects=[_public(r) for r in matched])
        targets, scope = sorted(registry.values(), key=lambda row: row["id"]), "all-registered-projects"
    elif not matched:
        return _clarify("No registered project matches this command. Name the project or register it (private overlay for private work). Nothing is guessed.",
                        suggestions=suggestions, known_projects=sorted(registry))
    else:
        targets, scope = sorted(matched, key=lambda row: row["id"]), "named-projects" if len(matched) > 1 else "single-project"
    if len(verbs) > 1:
        focus = []  # a combined command (upgrade and speed up and fix) is a comprehensive run
    full = intent == "build" or (intent == "upgrade" and not focus)
    streams = list(rules["workstreams"][intent])
    if focus and intent == "upgrade":
        streams = sorted({s for name in focus for s in rules["focus_workstreams"].get(name, [])} | {"quality-assurance"})
    implementers = min(rules["max_agents"] - 1, len(streams))
    checked = workspace_path is not None
    here = workspace(workspace_path) if workspace_path else None
    plan_targets = []
    for row in targets:
        entry = _public(row)
        entry.update(repository_verified=False, branch_policy="isolated claude/ or codex/ branch per project",
                     memory_scope=row["id"])
        if checked:
            entry["workspace_matches"] = here == row["slug"]
        plan_targets.append(entry)
    write = bool(engine["write"])
    if checked and targets and not all(t["workspace_matches"] for t in plan_targets):
        write = False
    gates = [*rules["gates"]["all"], *rules["gates"].get(verb, [])]
    if intent == "cinematic":
        gates += rules["gates"]["upgrade"]
    return {
        "schema_version": 1, "status": "routed", "command": text.strip(), "language": "ar" if _ARABIC.search(text) else "en",
        "intent": intent, "verb": verb, "engine": engine["engine"], "skill": engine["skill"], "prompt": engine["prompt"],
        "scope": engine.get("scope") or ("comprehensive" if full else "focused" if focus else "standard"),
        "focus": focus, "prohibited": prohibited, "target_scope": scope, "targets": plan_targets,
        "write_allowed": write, "read_only": not engine["write"],
        "workspace_note": None if not checked or write or not engine["write"] else
        "This checkout is not the (only) target repository: do not edit it for this task; open each target's own checkout.",
        "complexity": "large" if full or scope == "all-registered-projects" else "small" if intent == "release" else "medium",
        "agents": {"workstreams": streams, "implementers": implementers, "independent_verifiers": 1,
                   "recommended_total": implementers + 1, "maximum": rules["max_agents"], "per_target": scope == "all-registered-projects",
                   "rule": "Use fewer when workstreams are not independent or a smaller team is faster; the verifier never reviews its own work."},
        "skills": _skills([engine["skill"], *rules["supporting_skills"][intent]]),
        "hub_commands": rules["hub_commands"][intent],
        "budget": {"additional_cost": 0, "paid_services": "separate owner approval required",
                   "accounting": "measure orchestrator, reviewers and workers together per verified task"},
        "gates": gates,
        "state": {"memory": "gaie_memory (project-scoped, private)", "checkpoints": "engineering_os.orchestration checkpoint"},
        "evidence_boundary": "Plan only. Repository access, skill invocation, tests and deployment each need their own evidence.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="cmd", required=True)
    route_parser = commands.add_parser("route")
    route_parser.add_argument("text")
    route_parser.add_argument("--workspace", help="checkout whose origin must match the target before writes")
    commands.add_parser("projects")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "route":
            result = route(args.text, workspace_path=args.workspace)
        else:
            result = [_public(row) | {"aliases": row["aliases"]} for row in projects().values()]
    except (RouteError, OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not isinstance(result, dict) or result["status"] == "routed" else 2


if __name__ == "__main__":
    sys.exit(main())
