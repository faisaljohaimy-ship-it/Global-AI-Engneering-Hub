"""GAIE master router: owner commands in Arabic or English to a verifiable plan.

Deterministic and offline. It classifies the task, resolves the project against
the registries (`project_registry`), and selects the engine, the control-plane
engine id, agent roles, capabilities, a least-privilege grant template, the
execution scope, tests and evidence. It never guesses a repository, URL or
deployment target: an unknown, ambiguous, unregistered or conflicting target stops
with `needs-clarification`. Hard rules are enforced here, not by text: audit is
read-only, performance and repair stay on an isolated branch, a new system gets a
workspace grant (creating its repository is a separate approved step), and a
release always needs approval. A route is a plan: it executes nothing and proves
nothing about execution. Standard library only so the file can be vendored.
SPDX-License-Identifier: MIT.
"""
import argparse
import difflib
import json
import os
import pathlib
import re
import sys
import unicodedata

if __name__ == "__main__":
    sys.dont_write_bytecode = True

try:
    from . import contracts as _contracts
except ImportError:  # vendored or run as a script: the same values, checked by tests
    _contracts = None

try:
    from . import workspace_policy as _workspace_policy
except ImportError:  # an older vendored router can plan, but cannot authorize writes
    if not __package__ and pathlib.Path(__file__).resolve().with_name("workspace_policy.py").is_file():
        import workspace_policy as _workspace_policy
    else:
        _workspace_policy = None

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MAX_TEXT = 2000
SIDE_EFFECTS = _contracts.SIDE_EFFECTS if _contracts else (
    "none", "state-write", "workspace-write", "repo-write", "network", "external-write", "production")
GATED = _contracts.GATED if _contracts else frozenset({"external-write", "production"})
PERMISSIONS = _contracts.PERMISSIONS if _contracts else frozenset({
    "read:repo", "read:registry", "read:state", "write:state", "write:workspace", "write:repo-branch", "exec:sandbox",
    "net:fetch", "ext:github", "ext:deploy", "prod:deploy", "secrets:none"})
# Hard rules live in code so that editing the policy file cannot relax them.
HARD_CEILING = {"audit": "none", "accelerate": "repo-write", "repair": "repo-write", "upgrade": "repo-write",
                "cinematic": "repo-write", "build": "workspace-write"}
HARD_EXECUTION = {"audit": ("read-only",), "accelerate": ("workspace", "repo-branch"), "repair": ("workspace", "repo-branch"),
                  "upgrade": ("workspace", "repo-branch"), "cinematic": ("workspace", "repo-branch"), "build": ("workspace",),
                  "release": ("release-gated",)}
PERMISSION_FLOOR = {"write:state": "state-write", "write:workspace": "workspace-write", "exec:sandbox": "workspace-write",
                    "write:repo-branch": "repo-write", "net:fetch": "network", "ext:github": "external-write",
                    "ext:deploy": "external-write", "prod:deploy": "production"}
_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_CAPABILITY = re.compile(r"^gaie\.[a-z][a-z0-9-]*$")
_POSSESSIVE = re.compile(r"(?<=[A-Za-z0-9])['\u2019]s\b")
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
_PREFIX_GROUPS = {_PHRASE_PREFIX: (("و", "ف"), ("ب", "ل", "ك"), ("ال",)), _ALIAS_PREFIX: (("و", "ف"), ("ب", "ل"))}
_ARABIC = re.compile("[\u0621-\u064a]")
_QUESTIONS = frozenset({"?", "؟", "⁇", "⁈", "⁉"})
_QUESTION_PREFIXES = (
    "can you", "could you", "would you", "will you", "should i", "should we", "how", "why", "what",
    "هل", "كيف", "متى", "ماذا", "لماذا", "هل يمكن", "هل تستطيع", "هل ينبغي",
)
_AUDIT_WORDS = (
    "auditing", "inspection", "reviewing", "scanning", "assessment", "checking", "verification",
    "فحص", "تدقيق", "مراجعة", "تقييم", "تحقق", "تفقد",
)
_READ_ONLY_PHRASES = (
    "read-only", "read only", "readonly", "audit-only", "inspection-only", "review-only", "check-only", "dry run", "dry-run",
    "advice only", "analysis only", "report only", "plan only", "planning only",
    "preview only", "preview-only", "for preview", "as an example", "as example", "for example", "example only",
    "for demonstration", "as a demonstration", "for illustration", "for demo", "demo only", "simulation only",
    "no changes", "no writes", "without changes", "without modifications", "without modifying", "for information only",
    "للقراءة فقط", "قراءة فقط", "للاطلاع فقط", "للاستشارة فقط", "للتخطيط فقط", "تحليل فقط", "تقرير فقط",
    "للمعاينة فقط", "للعرض فقط", "لغرض العرض", "كمثال", "على سبيل المثال", "للتوضيح فقط", "للشرح فقط", "محاكاة فقط",
    "دون تعديل", "بدون تعديل", "دون تغيير", "بدون تغيير", "دون كتابة", "بدون كتابة",
)
_GENERIC_CHANGE_WORDS = frozenset({
    "change", "changes", "changing", "edit", "edits", "editing", "modify", "modification", "modifying", "mutate", "write",
    "writes", "writing", "alter", "touch", "commit", "تعدل", "تعديل", "تعديلات", "تغير", "تغيير", "تغييرات",
    "تكتب", "كتابه", "تلمس", "تغييرها", "تعديلها",
})
_AUDIT_ACTIONS = frozenset({"spec", "inventory", "health", "hub-audit"})


class RouteError(ValueError):
    pass


def _fold(text):
    if not isinstance(text, str):
        raise RouteError("command must be text")
    text = _POSSESSIVE.sub("", unicodedata.normalize("NFKC", text))  # "Sadeed's videos" names Sadeed
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


def _registry_module():
    """engineering_os.project_registry, or the copy vendored beside this file; None when absent."""
    try:
        from . import project_registry as module
    except ImportError:
        if not (HERE / "project_registry.py").is_file():
            return None
        import project_registry as module  # run as a script: this file's directory leads sys.path
    return module if pathlib.Path(module.__file__).resolve().parent == HERE else None


def projects(environ=None):
    """Every project row for routing: public registry, public-safe catalog and the private registry."""
    module = _registry_module()
    if module is None:  # a vendored copy installed without project_registry.py
        return _legacy_projects(environ)
    return module.routing_rows(environ)


def _legacy_projects(environ=None):
    """Public registry rows plus the private overlay, with normalized aliases (pre-registry loader)."""
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


def _forms(token, pattern=_PHRASE_PREFIX):
    """The token and every reading of it with attached Arabic prefixes removed.

    «وبلتكس» is «و» + «بلتكس», not «وب» + «لتكس»: each prefix group is optional,
    so a name that itself starts with «ب» or «ل» still matches after «و».
    """
    if not _ARABIC.search(token):
        return {token}
    forms = {token, _strip(token, pattern)}
    for group in _PREFIX_GROUPS[pattern]:
        forms |= {form[len(prefix):] for form in forms for prefix in group
                  if form.startswith(prefix) and len(form) - len(prefix) >= 2}
    return forms


def _find(tokens, phrase, pattern=_PHRASE_PREFIX):
    """Start indexes of a normalized phrase. Only the spoken token may carry a prefix."""
    size = len(phrase)
    return [index for index in range(len(tokens) - size + 1)
            if all(token == word or word in _forms(token, pattern)
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


def _operation_words(rules):
    return {name: _words(words) for name, words in rules["verbs"].items()}


def classify(text, rules):
    """Classify operations, including scoped exclusions and unscoped no-change constraints.

    A verb is a command only as an imperative at the start of a clause or after a
    coordinator. Any verb form after a negation in its clause is prohibited.
    Other mentions (questions, statements, nouns) are ignored.
    """
    verbs = _operation_words(rules)
    negations, fillers = _words(rules["negations"]), _words(rules["fillers"])
    coordinators, breaks = _words(rules["coordinators"]), _words(rules["clause_breaks"])
    nouns = _words(rules["noun_followers"])
    wanted, prohibited, negated, uncertain_negation = [], [], False, False
    for clause in clauses(text):
        blocked, position, scoped_negation = False, True, False
        for index, token in enumerate(clause):
            bare, joined = _conjoined(token)
            if token in breaks or bare in breaks:
                uncertain_negation |= blocked and not scoped_negation
                blocked, position, scoped_negation = False, True, False
                continue
            if token in negations or bare in negations:
                uncertain_negation |= blocked and not scoped_negation
                blocked = negated = True
                scoped_negation = False
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
            if blocked and (token in _GENERIC_CHANGE_WORDS or bare in _GENERIC_CHANGE_WORDS):
                uncertain_negation = True
            if name is not None and following not in nouns:
                if blocked:
                    scoped_negation = True
                    if name not in prohibited:
                        prohibited.append(name)
                elif imperative and (position or joined) and name not in wanted:
                    wanted.append(name)
            position = False
        uncertain_negation |= blocked and not scoped_negation
    wanted = [name for name in wanted if name not in prohibited]
    tokens = normalize(text)
    focus = sorted(name for name, phrases in _lexicon(rules["focus"]).items()
                   if any(_find(tokens, phrase) for phrase in phrases))
    everything = any(_find(tokens, normalize(phrase)) for phrase in rules["all_projects"])
    return wanted, prohibited, focus, everything, negated, uncertain_negation


def _audit_scope(tokens, rules):
    audit_words = _words((*_AUDIT_WORDS, *rules["verbs"]["audit"]))
    for token in tokens:
        forms = _forms(token)
        # In Arabic, ل + ال contracts to لل, including after prefixed و or ف.
        contracted = {form[2:] for form in forms if form.startswith("لل")}
        if audit_words.intersection(forms | contracted):
            return True
    return False


def _authorization_boundary(text, tokens, verbs, uncertain_negation, rules):
    """A lexical plan cannot turn a question or read-only scope into write authority."""
    question_prefixes = normalize_all(_QUESTION_PREFIXES)
    if _QUESTIONS.intersection(unicodedata.normalize("NFKC", text)) or any(
        clause[:len(prefix)] == prefix
        for clause in clauses(text)
        for prefix in question_prefixes
    ):
        return "A question cannot authorize a mutation. State the requested operation explicitly."
    if not any(verb != "audit" for verb in verbs):
        return None
    if uncertain_negation or _audit_scope(tokens, rules) or any(
        _find(tokens, phrase) for phrase in normalize_all(_READ_ONLY_PHRASES)
    ):
        return "The request includes a read-only or ambiguous no-change scope. Run a separate explicit request for any mutation."
    fillers = _words(rules["fillers"])
    leading = next((token for token in tokens if token not in fillers), "")
    bare, _ = _conjoined(leading)
    negations = _words(rules["negations"])
    operations = _operation_words(rules)
    if text.lstrip().startswith((">", '"', "'", "`", "«", "“", "‘")) or not (
        _verb(leading, operations)[1] or _verb(bare, operations)[1] or leading in negations or bare in negations
    ):
        return "A write request must begin with an explicit operation or a clearly scoped exclusion."
    return None


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


def _skills(names):
    roots = [ROOT / "skills", pathlib.Path.cwd() / ".claude/skills", HERE.parents[1] if HERE.name == "engine" else HERE]
    return [{"skill": name, "available": any((root / name / "SKILL.md").is_file() for root in roots)} for name in names]


def _clarify(reason, **extra):
    return {"schema_version": 1, "route_version": 2, "status": "needs-clarification", "decision": "needs-clarification",
            "reason": reason, "write_allowed": False, "executable_by_route": False, "grant_template": None, **extra}


def _public(row):
    return {key: row.get(key) for key in ("id", "repository", "visibility", "source", "path")}


def _guard(condition, message):
    if not condition:
        raise RouteError(f"policy violates a hard rule: {message}")


def _rank(name):
    _guard(name in SIDE_EFFECTS, f"unknown side-effect class {name!r}")
    return SIDE_EFFECTS.index(name)


def check_policy(rules):
    """Validate the control-plane section against the hard rules; return its intents."""
    plane = rules.get("control_plane")
    _guard(isinstance(plane, dict) and isinstance(plane.get("intents"), dict), "control_plane.intents is missing")
    intents = plane["intents"]
    _guard(set(intents) == set(rules["engines"]), "every routed intent needs exactly one control-plane entry")
    roles = plane.get("role_ids", {})
    known = set(roles.get("registered", [])) | set(roles.get("provisional", []))
    _guard(known and all(isinstance(role, str) and _ID.match(role) for role in known), "role ids must be kebab-case")
    _guard(isinstance(plane.get("grant_ttl_hours"), int) and 0 < plane["grant_ttl_hours"] <= 24, "grant_ttl_hours 1-24")
    _guard(all(engine["write"] is (intent != "audit") for intent, engine in rules["engines"].items()),
           "only the audit engine is classified as read-only")
    for intent, spec in intents.items():
        where = f"control_plane.{intent}"
        _guard(isinstance(spec, dict) and isinstance(spec.get("engine_id"), str) and _ID.match(spec["engine_id"]),
               f"{where}.engine_id")
        engines = spec.get("engines")
        _guard(isinstance(engines, dict) and spec["engine_id"] in engines, f"{where}.engines must include engine_id")
        for name, actions in engines.items():
            _guard(_ID.match(name) and isinstance(actions, list) and actions and len(set(actions)) == len(actions)
                   and all(isinstance(a, str) and _ID.match(a) for a in actions), f"{where}.engines.{name}")
        granted = {(name, action) for name, actions in engines.items() for action in actions}
        ceiling = spec.get("max_side_effect")
        _rank(ceiling)
        _guard(spec.get("execution") in HARD_EXECUTION[intent], f"{where}.execution must be one of {HARD_EXECUTION[intent]}")
        steps = spec.get("gated_steps")
        _guard(isinstance(steps, list), f"{where}.gated_steps")
        for step in steps:
            _guard(isinstance(step, dict) and set(step) == {"engine", "action", "side_effect", "permissions", "summary"}
                   and step["side_effect"] in GATED and _ID.match(step["action"]) and _ID.match(step["engine"]),
                   f"{where}: gated steps are external-write or production")
            for perm in step["permissions"]:
                _guard(perm in PERMISSIONS and _rank(PERMISSION_FLOOR.get(perm, "none")) <= _rank(step["side_effect"]),
                       f"{where}.{step['action']}: permission {perm!r}")
        if intent == "release":
            _guard(ceiling in GATED and spec.get("approval_required") is True and steps,
                   "release always needs approval and an external-write or production side effect")
            _guard(all((step["engine"], step["action"]) in granted for step in steps), "release gated steps belong to the release grant")
            _guard(any(step["side_effect"] == "production" for step in steps), "release promotion is a production step")
        else:
            _guard(_rank(ceiling) <= _rank(HARD_CEILING[intent]), f"{where}: ceiling {ceiling} exceeds {HARD_CEILING[intent]}")
            _guard(not spec.get("approval_required"), f"{where}: only release is approval-gated as a whole")
            _guard(all((step["engine"], step["action"]) not in granted for step in steps), f"{where}: a gated step never enters the base grant")
        if intent == "build":
            _guard(any(step["action"] == "create-repository" and step["side_effect"] == "external-write" for step in steps),
                   "build marks new-repository creation as an approved external-write step")
        else:
            _guard(intent == "release" or not steps, f"{where}: unexpected gated step")
        if intent == "audit":
            _guard(spec["engine_id"] == "master-audit" and set(engines) == {"master-audit"}
                   and set(engines["master-audit"]) == _AUDIT_ACTIONS,
                   "audit can grant only the read-only actions of master-audit")
        permissions = spec.get("permissions")
        _guard(isinstance(permissions, list) and "secrets:none" in permissions, f"{where}.permissions must include secrets:none")
        if intent == "audit":
            _guard(set(permissions) == {"read:repo", "read:registry", "secrets:none"},
                   "audit can only read repository and registry data")
        for perm in permissions:
            _guard(perm in PERMISSIONS, f"{where}: unknown permission {perm!r}")
            _guard(_rank(PERMISSION_FLOOR.get(perm, "none")) <= _rank(ceiling), f"{where}: {perm} exceeds the {ceiling} ceiling")
        team = spec.get("roles")
        _guard(isinstance(team, dict) and set(team) == {"lead", "support", "verifier"}, f"{where}.roles: lead, support, verifier")
        members = [team["lead"], *team["support"], team["verifier"]]
        _guard(all(role in known for role in members), f"{where}: role ids must be listed in control_plane.role_ids")
        _guard(len(set(members)) == len(members), f"{where}: the verifier never reviews its own work")
        for field in ("capabilities", "tests", "evidence"):
            values = spec.get(field)
            _guard(isinstance(values, list) and values and all(isinstance(v, str) and v.strip() for v in values), f"{where}.{field}")
        _guard(all(_CAPABILITY.match(c) for c in spec["capabilities"]), f"{where}.capabilities are gaie.* ids")
    return intents


def _scope_path(rules, project_id, path):
    root = rules["control_plane"]["workspace_root"]
    return f"{root}/{project_id or 'new-project'}" + (f"/{path}" if path else "")


def _audit_template(spec, rules, project_id, path):
    """Build the read-only template for a validated audit route."""
    return {"grant_id": None, "role": spec["roles"]["lead"], "engines": {name: list(acts) for name, acts in spec["engines"].items()},
            "paths": [_scope_path(rules, project_id, path)], "max_side_effect": spec["max_side_effect"],
            "expires_at": None, "approvals": []}


def _is_read_only_audit_template(template):
    engines = template.get("engines")
    if template.get("max_side_effect") != "none" or not isinstance(engines, dict) or set(engines) != {"master-audit"}:
        return False
    actions = engines["master-audit"]
    return (isinstance(actions, list) and len(actions) == len(_AUDIT_ACTIONS)
            and all(isinstance(action, str) for action in actions) and set(actions) == _AUDIT_ACTIONS)


def grant_from_template(template, *, grant_id, expires_at):
    """Fill a read-only audit template. Writing grants require separate authorization."""
    if not isinstance(template, dict) or template.get("grant_id") is not None or template.get("expires_at") is not None \
            or template.get("approvals") != [] or not _is_read_only_audit_template(template):
        raise RouteError("not an unfilled read-only audit template")
    grant = {**template, "grant_id": grant_id, "expires_at": expires_at,
             "engines": {k: list(v) for k, v in template["engines"].items()}, "paths": list(template["paths"])}
    if _contracts:
        try:
            _contracts.validate_grant(grant)
        except _contracts.ContractError as error:
            raise RouteError(f"grant does not satisfy the contract: {error}") from None
    return grant


def _execution(spec, rules, intent, project_id=None, path=None, *, verified=None):
    kind = spec["execution"]
    scope = {"kind": kind, "paths": [str(verified.root) if verified else _scope_path(rules, project_id, path)],
             "max_side_effect": spec["max_side_effect"],
             "requires_separate_authorization": kind != "read-only",
             "default_branch_writes": False, "network": _rank(spec["max_side_effect"]) >= _rank("network"),
             "production": spec["max_side_effect"] == "production"}
    if kind == "read-only":
        scope["writes"] = "none: no file edit, commit, migration, deployment or provider mutation"
    if kind == "repo-branch":
        scope["branch"] = verified.branch if verified else f"claude/gaie-{intent}-{project_id}"
    if kind == "release-gated":
        scope["writes"] = "only the approved gated actions, through a grant carrying the owner's approval tokens"
    if intent == "build":
        scope["new_repository"] = "separate gated step: external-write, owner approval, private by default"
    return scope


def _approvals(spec):
    return [{"engine": step["engine"], "action": step["action"], "side_effect": step["side_effect"],
             "permissions": list(step["permissions"]), "summary": step["summary"], "needs_approval": True,
             "in_base_grant": False} for step in spec["gated_steps"]]


def _team(spec):
    return {"lead": spec["roles"]["lead"], "support": list(spec["roles"]["support"]), "verifier": spec["roles"]["verifier"]}


def _focus(tokens, rules, matched):
    """Focus words outside the spans of the named projects ("Security Lab" is not a security focus)."""
    masked = list(tokens)
    for row in matched:
        for key in row["_keys"]:
            for start in _find(tokens, list(key), _ALIAS_PREFIX):
                masked[start:start + len(key)] = [""] * len(key)
    return sorted(name for name, phrases in _lexicon(rules["focus"]).items() if any(_find(masked, phrase) for phrase in phrases))


def _registry_check(row):
    return row.get("repository_check") or {
        "status": "registered-private" if row.get("source") == "private-overlay" else "registered-public",
        "repository_known": bool(row.get("repository")), "source": row.get("source"),
        "evidence": "legacy registry loader", "observed": None,
        "reachability": "not checked by the registry; the executing agent verifies access in its environment"}


def _verified_write_scope(intent, path, targets):
    if path is None:
        return None, "No workspace was selected. Provide an isolated workspace with --workspace before editing."
    if _workspace_policy is None:
        return None, "The reviewed workspace validator is unavailable. Open a current engineering pack before editing."
    if intent != "build" and len(targets) != 1:
        return None, "Choose one target project and its isolated linked worktree before editing."
    target = targets[0] if targets else {}
    try:
        return _workspace_policy.validate_workspace(
            path, intent=intent, expected_repository=target.get("slug"), registered_path=target.get("path"),
        ), None
    except _workspace_policy.WorkspacePolicyError as error:
        return None, str(error)


def _enforce(plan):
    """Re-check the hard rules on the finished plan (defence in depth)."""
    _guard(plan["executable_by_route"] is False, "a route never executes")
    _guard(plan["write_allowed"] is False, "a route never authorizes writes")
    templates = [t["grant_template"] for t in plan["targets"] if t["grant_template"] is not None]
    if plan["grant_template"] is not None:
        templates.append(plan["grant_template"])
    if plan["intent"] == "audit":
        _guard(all(_is_read_only_audit_template(t) for t in templates), "audit maps only to read-only audit grants")
    else:
        _guard(not templates and not set(plan["permissions"]).intersection(PERMISSION_FLOOR),
               "a mutation plan carries neither a grant nor writing permissions")
    if plan["intent"] == "release":
        _guard(plan["decision"] == "needs-approval" and plan["side_effect"] in GATED,
               "a release always needs approval")
    return plan


def route(text, *, environ=None, workspace_path=None):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise RouteError("command must be 1-2000 characters")
    rules = policy()
    plane = check_policy(rules)
    tokens = normalize(text)
    verbs, prohibited, _, everything, negated, uncertain_negation = classify(text, rules)
    boundary = _authorization_boundary(text, tokens, verbs, uncertain_negation, rules)
    if boundary:
        return _clarify(boundary, prohibited=prohibited)
    registry = projects(environ)
    matched, suggestions = resolve(tokens, registry)
    focus = _focus(tokens, rules, matched)
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
    spec = plane[intent]
    known = {"intent": intent, "engine": engine["engine"], "engine_id": spec["engine_id"], "roles": _team(spec),
             "capabilities": list(spec["capabilities"]), "side_effect": spec["max_side_effect"], "execution_scope": None,
             "tests": list(spec["tests"]), "evidence": list(spec["evidence"])}
    skipped = []
    if intent == "build":
        if matched or everything:
            return _clarify("Build creates a new system, but the command names an existing project. Say upgrade, or name the new system.",
                            projects=[_public(row) for row in matched], **known)
        if suggestions:
            return _clarify("Build creates a new system, but a word resembles a registered project. Say upgrade with the exact "
                            "project name, or confirm this is a new system.", suggestions=suggestions, **known)
        targets, scope = [], "new-project"
    elif everything:
        if matched:
            return _clarify("The command names both one project and all projects.", projects=[_public(r) for r in matched], **known)
        ordered = sorted(registry.values(), key=lambda row: row["id"])
        targets, scope = [row for row in ordered if row.get("repository")], "all-registered-projects"
        skipped = [{"id": row["id"], "repository_check": _registry_check(row)} for row in ordered if not row.get("repository")]
    elif not matched:
        return _clarify("No registered project matches this command. Name the project or register it (private registry for private work). Nothing is guessed.",
                        suggestions=suggestions, known_projects=sorted(registry), project=None, **known)
    else:
        targets, scope = sorted(matched, key=lambda row: row["id"]), "named-projects" if len(matched) > 1 else "single-project"
        missing = [row for row in targets if not row.get("repository")]
        if missing:
            row = missing[0]
            return _clarify(
                f"The project {row['id']} is known by name, but no repository is registered for it, and a repository is never "
                "guessed. Register the exact repository (and folder) in the private registry, then repeat the command.",
                project=row["id"] if len(targets) == 1 else None, names=row.get("names"),
                repository_check=_registry_check(row), unregistered=[r["id"] for r in missing],
                next_step=f"python3 -m engineering_os.project_registry register {row['id']} "
                          "--repository https://github.com/OWNER/REPO [--path FOLDER] --apply", **known)
    if len(verbs) > 1:
        focus = []  # a combined command (upgrade and speed up and fix) is a comprehensive run
    full = intent == "build" or (intent == "upgrade" and not focus)
    streams = list(rules["workstreams"][intent])
    if focus and intent == "upgrade":
        streams = sorted({s for name in focus for s in rules["focus_workstreams"].get(name, [])} | {"quality-assurance"})
    implementers = min(rules["max_agents"] - 1, len(streams))
    checked = workspace_path is not None
    write_intent = intent not in {"audit", "release"}
    verified, workspace_problem = _verified_write_scope(intent, workspace_path, targets) if write_intent else (None, None)
    plan_targets = []
    for row in targets:
        entry = _public(row)
        entry.update(repository_verified=False, branch_policy="isolated claude/ or codex/ branch per project",
                     memory_scope=row["id"], repository_check=_registry_check(row),
                     grant_template=_audit_template(spec, rules, row["id"], row.get("path")) if intent == "audit" else None,
                     execution_scope=_execution(spec, rules, intent, row["id"], row.get("path"), verified=verified),
                     evidence_location=f"{rules['control_plane']['evidence_root']}/{row['id']}")
        if checked and write_intent:
            entry["workspace_matches"] = verified is not None
        plan_targets.append(entry)
    blockers = [workspace_problem] if workspace_problem else []
    if intent == "release":
        blockers += [f"{row['id']}: no deployment target is registered in the private registry; it is never guessed."
                     for row in targets if not row.get("deployment_target_registered")]
    gates = [*rules["gates"]["all"], *rules["gates"].get(verb, [])]
    if intent == "cinematic":
        gates += rules["gates"]["upgrade"]
    single = plan_targets[0] if len(plan_targets) == 1 else None
    decision = "ready-for-grant" if intent == "audit" else "blocked" if write_intent and blockers else "needs-approval"
    plan = {
        "schema_version": 1, "route_version": 2, "status": "routed", "command": text.strip(),
        "language": "ar" if _ARABIC.search(text) else "en",
        "intent": intent, "verb": verb, "engine": engine["engine"], "engine_id": spec["engine_id"],
        "skill": engine["skill"], "prompt": engine["prompt"],
        "scope": engine.get("scope") or ("comprehensive" if full else "focused" if focus else "standard"),
        "focus": focus, "prohibited": prohibited, "target_scope": scope, "targets": plan_targets,
        "project": single["id"] if single else None,
        "repository_check": single["repository_check"] if single else
        {"status": "not-applicable", "detail": "a new system has no repository until the approved create-repository step"}
        if intent == "build" else None,
        "skipped": skipped,
        "decision": decision, "executable_by_route": False, "blockers": blockers,
        "side_effect": spec["max_side_effect"], "roles": _team(spec), "capabilities": list(spec["capabilities"]),
        "permissions": [p for p in spec["permissions"] if p not in PERMISSION_FLOOR],
        "grant_template": single["grant_template"] if single else None,
        "grant_ttl_hours": rules["control_plane"]["grant_ttl_hours"], "approvals_required": _approvals(spec),
        "execution_scope": single["execution_scope"] if single else
        _execution(spec, rules, intent, verified=verified) if intent == "build" else None,
        "tests": list(spec["tests"]), "evidence": list(spec["evidence"]),
        "evidence_location": single["evidence_location"] if single else
        f"{rules['control_plane']['evidence_root']}/new-project" if intent == "build" else None,
        "write_allowed": False, "read_only": intent == "audit",
        "workspace_note": f"Do not edit this workspace. {workspace_problem}" if workspace_problem else
        "Workspace verified. Start any write separately with explicit authorization." if verified else None,
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
    return _enforce(plan)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="cmd", required=True)
    route_parser = commands.add_parser("route")
    route_parser.add_argument("text")
    route_parser.add_argument("--workspace", help="empty private build workspace or isolated linked checkout for the target")
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
