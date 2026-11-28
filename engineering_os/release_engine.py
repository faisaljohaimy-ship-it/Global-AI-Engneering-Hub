"""Release engine (GAIE layer L11, acceptance Scenario G): eligibility, plan and a source-bound record.

The engine decides whether one exact commit of a Git checkout may be released as one
version, and writes a record of that decision. It never deploys, pushes, tags or
publishes. Every Git call is a read-only subcommand (allow-list in `READ_ONLY_GIT`) run
with the SDK's hardening flags and more (`_run`: hooks, fsmonitor and the untracked cache
off, no system or global config, no inherited GIT_* variables, no optional locks, no
transport and no lazy fetch), after `sdk.engineering_sdk.checkout_guard` has refused
checkouts that would run filter programs or hide changes; each call re-checks that the
checkout's config names no filter program, and `status` never enters a submodule (the
flags of `sdk.engineering_sdk.target`). The output is a record plus the exact commands
the owner would run; the engine runs none of them.

A release is ELIGIBLE only when all of these hold (docs/specs/gaie-20-layers/RELEASE_ENGINE.md):
the checkout is safe and clean; HEAD is the exact 40-hex tested commit; every required
CI job has exactly one completed, successful receipt for that commit; an owner
authorization names that commit, version and tag; the version is MAJOR.MINOR.PATCH,
greater than every recorded version (tags with the product prefix, older changelog
headings, an explicit previous version) and equal to the top changelog heading and the
version file; and an independent review gate result bound to that commit has passed.

Receipts, authorizations and gate results are caller-supplied data. The engine checks
that they are complete and consistent with the checkout; it cannot authenticate who
produced them, and a record proves content and intent, not publication. Until the
owner publishes the GitHub Release the truthful status is "recorded, tag pending".
Standard library only. SPDX-License-Identifier: MIT.
"""
import argparse
import copy
import datetime
import json
import os
import pathlib
import re
import stat
import subprocess
import sys

from .contracts import sha256 as digest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE = "release-engine"
MODE = "deterministic"
SCHEMA = "gaie.release-record/1"
PROFILE_SCHEMA = "gaie.release-profile/1"
RECEIPTS_SCHEMA = "gaie.ci-receipts/1"
AUTHORIZATION_SCHEMA = "gaie.release-authorization/1"
STATUS = "recorded, tag pending"
VERSION_FILE = "engineering_os/VERSION"
HUB_TAG = re.compile(r"engineering-os-v[0-9]+\.[0-9]+\.[0-9]+")  # the shape scripts/verify_release.py accepts
SHA = re.compile(r"[0-9a-f]{40}")
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
TAG_PREFIX = re.compile(r"(?:[a-z][a-z0-9]*(?:-[a-z0-9]+)*-)?v")
WORKFLOW = re.compile(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
MAX_TEXT = 500
MAX_JOBS = 200
MAX_JSON = 1024 * 1024
READ_ONLY_GIT = frozenset({"rev-parse", "status", "ls-tree", "merge-base", "tag", "cat-file"})
# Added to sdk.engineering_sdk.GIT_HARDENING on every call. GIT_ALLOW_PROTOCOL="" overrides any protocol.*
# setting of the checkout, so no transport (and no lazy fetch of a partial clone) can start a program.
GIT_FLAGS = ("-c", "core.untrackedCache=false", "-c", "protocol.allow=never")
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_OPTIONAL_LOCKS": "0",
           "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": ""}
# The only status the engine runs. checkout_guard checks the recorded commit of every populated submodule but
# not the configs of submodules nested inside them; a plain `git status` recursed into one and ran its filter
# program during the read-only eligibility check (recheck-authz F1).
CLEAN_STATUS = ("status", "--porcelain=v1", "--untracked-files=normal", "--ignore-submodules=all")
PERFORMED = {"tag_created": False, "pushed": False, "published": False, "deployed": False, "network_requests": 0}
PASS = frozenset({"pass", "passed", "approve", "approved"})
FAIL = frozenset({"fail", "failed", "block", "blocked", "unverified", "refused"})
HUB_FILES = (  # (component id, version-declaring file, JSON key path or None for a one-line text file)
    ("engineering-os", VERSION_FILE, None),
    ("engineering-sdk", "sdk/VERSION", None),
    ("engineering-sdk-capabilities", "sdk/capabilities.json", ("sdk_version",)),
    ("gaie-plugin", ".claude-plugin/plugin.json", ("version",)),
    ("app-stdlib-template", "templates/app-stdlib/manifest.json", ("version",)),
    ("motion-engines", "packages/motion-engines/package.json", ("version",)),
    ("digital-shows", "packages/digital-shows/package.json", ("version",)),
    ("gaie-routes-policy", "governance/policies/gaie-routes.json", ("policy_version",)),
    ("orchestration-policy", "governance/policies/orchestration.json", ("policy_version",)),
)


class ReleaseError(ValueError):
    """A payload, profile or path does not fit the release engine's data contract."""


def _sdk():
    from sdk import engineering_sdk
    return engineering_sdk


def _need(condition, message):
    if not condition:
        raise ReleaseError(message)


def _text(value, field, limit=MAX_TEXT):
    _need(isinstance(value, str) and value.strip() and len(value) <= limit and "\x00" not in value,
          f"{field}: non-empty text up to {limit} characters")
    return value


def _relative(value, field):
    _text(value, field, 300)
    path = pathlib.PurePosixPath(value)
    _need(not path.is_absolute() and ".." not in path.parts and ".git" not in path.parts and str(path) == value,
          f"{field}: a plain relative path inside the repository")
    return value


def _key(version):
    return tuple(int(part) for part in version.split("."))


def _refuse(refusals, code, detail):
    refusals.append({"code": code, "detail": detail})


def _run(root, *args):
    """Git with the SDK's hardening flags plus GIT_FLAGS and GIT_ENV; nothing inherited from GIT_* variables."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_ENV)
    try:
        return subprocess.run(["git", *_sdk().GIT_HARDENING, *GIT_FLAGS, "-C", str(root), "--no-pager", *args],
                              capture_output=True, check=True, env=env,
                              timeout=120).stdout.decode("utf-8", "surrogateescape")
    except subprocess.TimeoutExpired:
        raise ReleaseError("Git did not finish in time") from None


def _git(root, *args):
    """Run one read-only Git subcommand hardened; `tag` may only list and `status` is exactly CLEAN_STATUS.

    Before every call the checkout's config, includes followed, must name no filter program: `status` runs
    one on a changed file whatever the flags, so this holds even if the call is not preceded by
    checkout_guard or the config changed after it."""
    command = args[0] if args else ""
    if (command not in READ_ONLY_GIT or (command == "tag" and args[1:2] != ("--list",))
            or (command == "status" and args != CLEAN_STATUS)):
        raise ReleaseError(f"git {' '.join(args[:2])!r} is not a read-only command of the release engine")
    try:
        names = _run(root, "config", "--list", "--includes", "--name-only", "-z").split("\0")
    except subprocess.CalledProcessError:
        raise ReleaseError("the checkout's Git config cannot be read") from None
    if any(_sdk().FILTER_SETTING.fullmatch(name) for name in names):
        raise ReleaseError("the checkout's Git config defines filter programs; inspect its .git/config")
    return _run(root, *args)


def _probe(root, *args):
    """A read-only query whose non-zero exit means 'no' (missing ref, not an ancestor)."""
    try:
        return _git(root, *args)
    except subprocess.CalledProcessError:
        return None


def _read(root, name):
    return _sdk().read_audit_file(root, name)  # regular file, no symlink anywhere on the path, no hard-link alias


def _json(data, field):
    try:
        return _sdk().decode_json(data.decode("utf-8") if isinstance(data, bytes) else data)
    except (ValueError, UnicodeDecodeError) as error:
        raise ReleaseError(f"{field}: strict JSON required ({error})") from None


def read_json_file(path, field="input"):
    """Read a bounded caller JSON file without following a symlink; duplicate keys are refused."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except OSError as error:
        raise ReleaseError(f"{field}: cannot open {pathlib.Path(path).name} ({error.strerror})") from None
    with os.fdopen(fd, "rb") as handle:
        _need(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), f"{field}: a regular file is required")
        data = handle.read(MAX_JSON + 1)
    _need(len(data) <= MAX_JSON, f"{field}: larger than {MAX_JSON} bytes")
    return _json(data, field)


# ---------------------------------------------------------------- profiles

def validate_profile(profile):
    """A release profile names what a release of one product binds. Returns a normalised copy."""
    _need(isinstance(profile, dict), "profile: object required")
    keys = {"schema", "product", "title", "tag_prefix", "changelog", "changelog_heading", "version_file",
            "components", "required_jobs"}
    _need(set(profile) == keys, f"profile: fields must be exactly {sorted(keys)}")
    _need(profile["schema"] == PROFILE_SCHEMA, f"profile: schema must be {PROFILE_SCHEMA}")
    _need(isinstance(profile["product"], str) and SLUG.fullmatch(profile["product"]), "profile.product: kebab-case id")
    _text(profile["title"], "profile.title", 80)
    _need(isinstance(profile["tag_prefix"], str) and TAG_PREFIX.fullmatch(profile["tag_prefix"]),
          "profile.tag_prefix: 'v' or '<kebab-id>-v'")
    _relative(profile["changelog"], "profile.changelog")
    heading = profile["changelog_heading"]
    _need(isinstance(heading, str) and len(heading) <= 80 and "\n" not in heading, "profile.changelog_heading: one line")
    if profile["version_file"] is not None:
        _relative(profile["version_file"], "profile.version_file")
    components = profile["components"]
    _need(isinstance(components, list) and len(components) <= 64, "profile.components: list of up to 64")
    seen = set()
    for row in components:
        _need(isinstance(row, dict) and set(row) == {"id", "path", "key"}, "profile component: id, path, key")
        _need(isinstance(row["id"], str) and SLUG.fullmatch(row["id"]) and row["id"] not in seen,
              f"profile component id {row.get('id')!r}: unique kebab-case")
        seen.add(row["id"])
        _relative(row["path"], f"component {row['id']}.path")
        key = row["key"]
        _need(key is None or (isinstance(key, list) and 0 < len(key) <= 8 and all(isinstance(k, str) and k for k in key)),
              f"component {row['id']}.key: null (one-line text file) or a list of JSON keys")
    jobs = profile["required_jobs"]
    _need(isinstance(jobs, dict) and 0 < len(jobs) <= 32, "profile.required_jobs: 1-32 workflows")
    for workflow, names in jobs.items():
        _need(isinstance(workflow, str) and WORKFLOW.fullmatch(workflow), f"required workflow path {workflow!r}")
        _need(isinstance(names, list) and 0 < len(names) <= 32 and len(set(names)) == len(names),
              f"{workflow}: 1-32 distinct job names")
        for name in names:
            _text(name, f"{workflow} job", 200)
    result = copy.deepcopy(profile)
    result["required_jobs"] = {workflow: sorted(names) for workflow, names in sorted(jobs.items())}
    return result


def _verify_release():
    from scripts import verify_release
    return verify_release


def hub_profile(root=ROOT):
    """The hub's own release: tag engineering-os-v<version> on the merge commit, created only when the owner
    publishes a GitHub Release. Required jobs are scripts/verify_release.WORKFLOWS of the running tree, the
    jobs release.yml checks after publication; run the engine from the commit being released."""
    try:
        packs = _json(_read(pathlib.Path(root), "catalog/packs.json"), "catalog/packs.json")
    except OSError as error:
        raise ReleaseError(f"hub profile: catalog/packs.json unreadable ({error.strerror})") from None
    _need(isinstance(packs, dict) and isinstance(packs.get("packs"), dict), "catalog/packs.json: packs object")
    components = [{"id": name, "path": path, "key": list(key) if key else None} for name, path, key in HUB_FILES]
    components += [{"id": f"pack-{name}", "path": "catalog/packs.json", "key": ["packs", name, "version"]}
                   for name in sorted(packs["packs"])
                   if isinstance(packs["packs"][name], dict) and "version" in packs["packs"][name]]  # unversioned packs declare nothing
    return validate_profile({
        "schema": PROFILE_SCHEMA, "product": "engineering-os", "title": "Engineering OS",
        "tag_prefix": "engineering-os-v", "changelog": "CHANGELOG.md", "changelog_heading": "Engineering OS",
        "version_file": VERSION_FILE, "components": components,
        "required_jobs": {path: sorted(names) for path, names in _verify_release().WORKFLOWS.items()},
    })


def _profile(profile, root):
    return hub_profile(root) if profile == "hub" else validate_profile(profile)


# ---------------------------------------------------------------- repository facts

def parse_changelog(text, heading):
    """Top `## <heading>X.Y.Z ...` entry, its notes, and the versions of the older entries."""
    pattern = re.compile(r"## " + re.escape(heading) + r" ?v?(?P<version>\S+)(?P<rest>(?: .*)?)")
    entries = []
    for number, line in enumerate(text.splitlines()):
        match = pattern.fullmatch(line.rstrip())
        if match:
            entries.append((number, line.rstrip(), match["version"]))
    if not entries:
        return {"top": None, "heading": None, "notes": "", "older": []}
    lines = text.splitlines()
    start = entries[0][0] + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return {"top": entries[0][2], "heading": entries[0][1], "notes": "\n".join(lines[start:end]).strip(),
            "older": [version for _, _, version in entries[1:] if SEMVER.fullmatch(version)]}


def _component_value(data, key, field):
    if key is None:
        text = data.decode("utf-8").strip()
        _need(text and "\n" not in text and len(text) <= 64, f"{field}: one line of text")
        return text
    value = _json(data, field)
    for part in key:
        _need(isinstance(value, dict) and part in value, f"{field}: key {'.'.join(key)} missing")
        value = value[part]
    _need(isinstance(value, str) and 0 < len(value) <= 64, f"{field}: version text")
    return value


def file_facts(root, profile):
    """Changelog, version file and component declarations read from the working tree (no Git needed)."""
    refusals, facts = [], {}
    root = pathlib.Path(root)
    try:
        data = _read(root, profile["changelog"])
        changelog = parse_changelog(data.decode("utf-8"), profile["changelog_heading"])
        facts["changelog"] = {"path": profile["changelog"], "sha256": digest(data), "heading": changelog["heading"],
                              "version": changelog["top"], "notes_sha256": digest(changelog["notes"].encode("utf-8"))}
        facts["release_notes"] = changelog["notes"]
        facts["older_versions"] = changelog["older"]
    except (OSError, ValueError) as error:
        _refuse(refusals, "changelog-unreadable", f"{profile['changelog']}: {error}")
        facts["changelog"], facts["release_notes"], facts["older_versions"] = None, "", []
    facts["version_source"] = None
    if profile["version_file"] is not None:
        try:
            data = _read(root, profile["version_file"])
            facts["version_source"] = {"path": profile["version_file"], "sha256": digest(data),
                                       "version": _component_value(data, None, profile["version_file"])}
        except (OSError, ValueError) as error:
            _refuse(refusals, "version-source-unreadable", f"{profile['version_file']}: {error}")
    facts["components"] = []
    for row in profile["components"]:
        try:
            data = _read(root, row["path"])
            facts["components"].append({**row, "version": _component_value(data, row["key"], row["id"]),
                                        "sha256": digest(data)})
        except (OSError, ValueError) as error:
            _refuse(refusals, "component-unreadable", f"{row['id']} ({row['path']}): {error}")
    return refusals, facts


def _tree(root, commit):
    listing = _git(root, "ls-tree", "-r", "-z", "--full-tree", commit).encode("utf-8", "surrogateescape")
    return {"object_format": _git(root, "rev-parse", "--show-object-format").strip(),
            "git_tree": _git(root, "rev-parse", "--verify", f"{commit}^{{tree}}").strip(),
            "listing_sha256": digest(listing)}


def _checkout(root, refusals):
    """Safe checkout and HEAD, or None after a refusal."""
    try:
        _sdk().checkout_guard(root)
        return _git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        _refuse(refusals, "checkout-unsafe", f"not a safe Git work tree root with a commit: {error}")
        return None


# ---------------------------------------------------------------- caller evidence

def check_receipts(document, required, commit):
    """One completed, successful receipt per required (workflow, job) for exactly `commit`."""
    refusals, rows = [], []
    if document is None:
        _refuse(refusals, "receipts-missing", "no CI job receipts were supplied")
        return refusals, rows
    try:
        _need(isinstance(document, dict) and {"schema", "jobs"} <= set(document) <= {"schema", "commit", "repository", "jobs"},
              "receipts: schema, jobs and optionally commit, repository")
        _need(document["schema"] == RECEIPTS_SCHEMA, f"receipts: schema must be {RECEIPTS_SCHEMA}")
        _need(isinstance(document["jobs"], list) and len(document["jobs"]) <= MAX_JOBS, f"receipts.jobs: up to {MAX_JOBS}")
        base = {"workflow", "job", "commit", "status", "conclusion", "run_id", "job_id"}
        for job in document["jobs"]:
            _need(isinstance(job, dict) and base <= set(job) <= base | {"url", "run_attempt"},
                  f"receipt: fields {sorted(base)} and optionally url, run_attempt")
            for field in ("workflow", "job", "commit", "status"):
                _text(job[field], f"receipt.{field}", 200)
            _need(job["conclusion"] is None or isinstance(job["conclusion"], str), "receipt.conclusion: text or null")
            for field in ("run_id", "job_id"):
                _need(type(job[field]) is int and job[field] > 0, f"receipt.{field}: positive integer")
            if "url" in job:
                _need(isinstance(job["url"], str) and job["url"].startswith("https://") and len(job["url"]) <= MAX_TEXT,
                      "receipt.url: https URL")
    except ReleaseError as error:
        _refuse(refusals, "receipts-invalid", str(error))
        return refusals, rows
    if document.get("commit") not in (None, commit):
        _refuse(refusals, "receipts-commit", "the receipts document names another commit")
    for workflow, names in required.items():
        for name in names:
            pair = f"{workflow} / {name}"
            found = [job for job in document["jobs"] if job["workflow"] == workflow and job["job"] == name]
            exact = [job for job in found if job["commit"] == commit]
            if not found:
                _refuse(refusals, "job-receipt-missing", f"{pair}: no receipt")
            elif not exact:
                _refuse(refusals, "job-receipt-other-commit", f"{pair}: receipts exist only for other commits")
            elif len(exact) > 1:
                _refuse(refusals, "job-receipt-ambiguous", f"{pair}: {len(exact)} receipts for this commit")
            elif (exact[0]["status"], exact[0]["conclusion"]) != ("completed", "success"):
                _refuse(refusals, "job-failed", f"{pair}: {exact[0]['status']} / {exact[0]['conclusion']}")
            else:
                job = exact[0]
                rows.append({"workflow": workflow, "job": name, "commit": commit, "conclusion": "success",
                             "run_id": job["run_id"], "job_id": job["job_id"], "url": job.get("url")})
    return refusals, rows


def check_authorization(document, commit, version, tag):
    refusals = []
    if document is None:
        _refuse(refusals, "authorization-missing", "no owner authorization record was supplied")
        return refusals, None
    keys = {"schema", "commit", "version", "tag", "authorized_by", "reference", "at"}
    try:
        _need(isinstance(document, dict) and set(document) == keys, f"authorization: fields must be exactly {sorted(keys)}")
        _need(document["schema"] == AUTHORIZATION_SCHEMA, f"authorization: schema must be {AUTHORIZATION_SCHEMA}")
        _need(document["authorized_by"] == "owner", "authorization.authorized_by must be 'owner'")
        _text(document["reference"], "authorization.reference")
        _need(isinstance(document["at"], str) and STAMP.fullmatch(document["at"]), "authorization.at: YYYY-MM-DDTHH:MM:SSZ")
        for field in ("commit", "version", "tag"):
            _text(document[field], f"authorization.{field}", 100)
    except ReleaseError as error:
        _refuse(refusals, "authorization-invalid", str(error))
        return refusals, None
    if document["commit"] != commit:
        _refuse(refusals, "authorization-commit", "the authorization is for another commit")
    if document["version"] != version:
        _refuse(refusals, "authorization-version", "the authorization is for another version")
    if document["tag"] != tag:
        _refuse(refusals, "authorization-tag", "the authorization is for another tag")
    return refusals, {"authorized_by": "owner", "reference": document["reference"], "at": document["at"],
                      "sha256": digest(document)}


def check_review_gate(result, commit, tree=None):
    """Read an independent review gate result (for example the L20 assurance gate) as data.

    It must name the tested commit (`commit`, `subject_commit`, `subject` or `head`) or its
    Git tree (`tree`, `subject_tree`), and every pass/fail signal it carries must pass:
    `passed` / `ok` booleans, `gate` / `status` / `verdict` words, and empty `failed` /
    `blocked` / `unverified` lists. A result whose reviewer equals its producer fails."""
    refusals = []
    if result is None:
        _refuse(refusals, "review-gate-missing", "no independent review gate result was supplied")
        return refusals, None
    if not isinstance(result, dict):
        _refuse(refusals, "review-gate-invalid", "the review gate result must be an object")
        return refusals, None
    subjects = [result[key] for key in ("commit", "subject_commit", "subject", "head") if key in result]
    trees = [result[key] for key in ("tree", "subject_tree") if key in result]
    if not subjects and not trees:
        _refuse(refusals, "review-gate-unbound", "the review gate result names no commit or tree")
    elif any(value != commit for value in subjects) or any(value != tree for value in trees):
        _refuse(refusals, "review-gate-commit", "the review gate result is for another commit or tree")
    signals = []
    for key in ("passed", "ok"):
        if key in result:
            signals.append(result[key] is True if isinstance(result[key], bool) else None)
    for key in ("gate", "status", "verdict"):
        if key in result:
            word = result[key].casefold() if isinstance(result[key], str) else None
            signals.append(True if word in PASS else False if word in FAIL else None)
    for key in ("failed", "blocked", "unverified"):
        if key in result:
            signals.append(result[key] in ([], {}) if isinstance(result[key], (list, dict)) else None)
    if not signals or None in signals:
        _refuse(refusals, "review-gate-invalid", "no recognised pass/fail signal, or a signal of the wrong type")
    elif not all(signals):
        _refuse(refusals, "review-gate-failed", "the independent review gate did not pass")
    reviewer, producer = result.get("reviewer"), result.get("producer")
    if reviewer is not None and reviewer == producer:
        _refuse(refusals, "review-gate-self-review", "the reviewer is the producer")
    return refusals, {"sha256": digest(result), "reviewer": reviewer if isinstance(reviewer, str) else None}


# ---------------------------------------------------------------- eligibility and plan

def evaluate(root, profile, version, commit, *, receipts=None, authorization=None, review_gate=None, base=None,
             previous_version=None, repository=None):
    """(refusals, facts) for releasing `commit` of the checkout at `root` as `version`. Read-only."""
    root = pathlib.Path(_text(str(root), "root", 4096)).absolute()
    profile = _profile(profile, root)
    refusals = []
    valid_version = isinstance(version, str) and bool(SEMVER.fullmatch(version))
    if not valid_version:
        _refuse(refusals, "version-invalid", "the version must be MAJOR.MINOR.PATCH with no pre-release or build suffix")
    tag = f"{profile['tag_prefix']}{version}" if valid_version else None
    if repository is not None and not (isinstance(repository, str) and REPOSITORY.fullmatch(repository)):
        _refuse(refusals, "repository-invalid", "repository must be <owner>/<name>")
        repository = None
    exact = isinstance(commit, str) and bool(SHA.fullmatch(commit))
    if not exact:
        _refuse(refusals, "commit-invalid", "the tested commit must be a full 40-character lowercase hexadecimal SHA")
    facts = {"profile": profile, "profile_sha256": digest(profile), "version": version if valid_version else None,
             "planned_tag": tag, "tested_commit": commit if exact else None, "repository": repository}
    head = _checkout(root, refusals)
    if head is None:
        return refusals, facts
    if exact and head != commit:
        _refuse(refusals, "commit-not-head", "the tested commit is not the checkout HEAD")
    if _git(root, *CLEAN_STATUS):
        _refuse(refusals, "dirty-tree", "the checkout has uncommitted or untracked files")
    if exact and head == commit:
        facts["tree"] = _tree(root, commit)
        if base is None:
            parent = _probe(root, "rev-parse", "--verify", "--quiet", f"{commit}^1^{{commit}}")
            facts["base_commit"] = parent.strip() if parent else None
        elif not (isinstance(base, str) and SHA.fullmatch(base)):
            _refuse(refusals, "base-invalid", "the base must be a full 40-character lowercase hexadecimal SHA")
        elif base == commit or _probe(root, "merge-base", "--is-ancestor", base, commit) is None:
            _refuse(refusals, "base-not-ancestor", "the base commit is not a proper ancestor of the tested commit")
        else:
            facts["base_commit"] = base
    missing, files = file_facts(root, profile)
    refusals += missing
    facts.update(files)
    if valid_version and files["changelog"] is not None and files["changelog"]["version"] != version:
        _refuse(refusals, "version-changelog-mismatch", f"the top '{profile['changelog_heading']}' changelog heading "
                f"declares {files['changelog']['version']!r}")
    if valid_version and files["version_source"] is not None and files["version_source"]["version"] != version:
        _refuse(refusals, "version-source-mismatch", f"{profile['version_file']} declares "
                f"{files['version_source']['version']!r}")
    recorded = [(item, "changelog") for item in files["older_versions"]]
    for line in _git(root, "tag", "--list", f"{profile['tag_prefix']}*").splitlines():
        name = line.strip()
        if SEMVER.fullmatch(name[len(profile["tag_prefix"]):]):
            recorded.append((name[len(profile["tag_prefix"]):], "tag"))
    if previous_version is not None:
        if isinstance(previous_version, str) and SEMVER.fullmatch(previous_version):
            recorded.append((previous_version, "payload"))
        else:
            _refuse(refusals, "previous-version-invalid", "previous_version must be MAJOR.MINOR.PATCH")
    facts["previous_version"] = None
    if recorded:
        latest = max(recorded, key=lambda row: _key(row[0]))[0]
        facts["previous_version"] = {"version": latest,
                                     "sources": sorted({source for value, source in recorded if value == latest})}
        if valid_version and _key(version) <= _key(latest):
            _refuse(refusals, "version-not-increasing", f"{version} is not greater than the recorded {latest}")
    problems, facts["required_jobs"] = check_receipts(receipts, profile["required_jobs"], commit)
    refusals += problems
    facts["receipts_sha256"] = digest(receipts) if receipts is not None else None
    problems, facts["authorization"] = check_authorization(authorization, commit, version, tag)
    refusals += problems
    problems, facts["review_gate"] = check_review_gate(review_gate, commit, facts.get("tree", {}).get("git_tree"))
    refusals += problems
    return refusals, facts


def owner_commands(facts, previous_commit=None):
    """The commands the owner would run, as argument vectors. The engine never runs them."""
    tag, commit, profile = facts["planned_tag"], facts["tested_commit"], facts["profile"]
    repo = ["--repo", facts["repository"]] if facts["repository"] else []
    previous = facts["previous_version"]
    previous_tag = f"{profile['tag_prefix']}{previous['version']}" if previous else None
    publish = [
        {"step": "save the record's release_notes field as RELEASE_NOTES.md", "argv": None},
        {"step": "publish the GitHub Release; this creates the tag on the exact tested commit",
         "argv": ["gh", "release", "create", tag, *repo, "--target", commit, "--title",
                  f"{profile['title']} {facts['version']}", "--notes-file", "RELEASE_NOTES.md", "--latest"]},
        {"step": "check the release and the tag commit",
         "argv": ["gh", "release", "view", tag, *repo, "--json", "tagName,targetCommitish,isDraft,isPrerelease"]},
        {"step": "check that the remote tag points at the tested commit",
         "argv": ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"]},
    ]
    rollback = [{"step": "delete the new release and its tag", "argv": ["gh", "release", "delete", tag, *repo,
                                                                         "--cleanup-tag", "--yes"]}]
    if previous_tag:
        rollback.insert(0, {"step": f"mark {previous_tag} as the latest release again",
                            "argv": ["gh", "release", "edit", previous_tag, *repo, "--latest"]})
    return publish, {"previous_version": previous["version"] if previous else None, "previous_tag": previous_tag,
                     "previous_commit": previous_commit, "commands": rollback,
                     "note": "Rollback moves the release label back; commits already on main and product pins "
                             "that adopted the tested commit are not reverted by it."}


def _record_body(root, facts, now):
    previous = facts["previous_version"]
    previous_commit = None
    if previous:
        found = _probe(root, "rev-parse", "--verify", "--quiet",
                       f"refs/tags/{facts['profile']['tag_prefix']}{previous['version']}^{{commit}}")
        previous_commit = found.strip() if found else None
    publish, rollback = owner_commands(facts, previous_commit)
    body = {
        "schema": SCHEMA, "engine": "engineering_os.release_engine", "product": facts["profile"]["product"],
        "version": facts["version"], "planned_tag": facts["planned_tag"], "status": STATUS, **PERFORMED,
        "repository": facts["repository"], "base_commit": facts["base_commit"], "tested_commit": facts["tested_commit"],
        "tree": facts["tree"], "changelog": facts["changelog"], "release_notes": facts["release_notes"],
        "version_source": facts["version_source"], "previous_version": previous, "components": facts["components"],
        "required_jobs": facts["required_jobs"], "receipts_sha256": facts["receipts_sha256"],
        "authorization": facts["authorization"], "review_gate": facts["review_gate"],
        "profile_sha256": facts["profile_sha256"], "owner_commands": publish, "rollback": rollback,
        "recorded_at": now, "claims_not_made": [
            "No tag, push, GitHub Release, deployment or network request was made by the release engine.",
            "CI receipts, the owner authorization and the review gate are caller-supplied data checked for "
            "consistency; their authenticity is not proven by this record.",
            "The release exists only after the owner publishes the GitHub Release for planned_tag."],
    }
    body["record_sha256"] = digest(body)
    return body


def _now(now):
    if now is None:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _need(isinstance(now, str) and STAMP.fullmatch(now), "now: YYYY-MM-DDTHH:MM:SSZ")
    return now


def plan(root, profile, version, commit, *, now=None, **evidence):
    """ELIGIBLE with the record body and owner commands, or REFUSED with every reason. Writes nothing."""
    when = _now(now)
    refusals, facts = evaluate(root, profile, version, commit, **evidence)
    result = {"ok": True, "engine": ENGINE, "decision": "REFUSED" if refusals else "ELIGIBLE",
              "eligible": not refusals, "refusals": refusals, "planned_tag": facts["planned_tag"],
              "tested_commit": facts["tested_commit"], "performed": dict(PERFORMED)}
    if not refusals:
        result["record"] = _record_body(pathlib.Path(root).absolute(), facts, when)
        result["owner_commands"] = result["record"]["owner_commands"]
    return result


def _destination(out, root, refusals):
    path = pathlib.Path(out).absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        _refuse(refusals, "record-path-symlink", "the record path or one of its directories is a symbolic link")
        return None
    inside = [item for item in path.parents if (item / ".git").exists()]
    real_root = pathlib.Path(os.path.realpath(root))
    if inside or real_root == path or real_root in path.parents:
        _refuse(refusals, "record-path-in-repository", "a release record lives outside every Git work tree, "
                "never in the commit it describes")
        return None
    if path.exists() or path.is_symlink():
        _refuse(refusals, "record-exists", "a record is never overwritten")
        return None
    return path


def record(root, profile, version, commit, *, out, now=None, **evidence):
    """Write the record (0600, exclusive create, never through a link) when the release is ELIGIBLE."""
    result = plan(root, profile, version, commit, now=now, **evidence)
    result["written"] = None
    if not result["eligible"]:
        return result
    refusals = []
    path = _destination(_text(str(out), "out", 4096), pathlib.Path(root).absolute(), refusals)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = (json.dumps(result["record"], ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)
        except FileExistsError:
            _refuse(refusals, "record-exists", "a record is never overwritten")
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            result["written"] = {"path": str(path), "sha256": digest(data),
                                 "record_sha256": result["record"]["record_sha256"]}
    if refusals:
        result.update(decision="REFUSED", eligible=False, refusals=refusals)
        result.pop("record"), result.pop("owner_commands")
    return result


# ---------------------------------------------------------------- verification

def verify_record(root, profile, record_path, *, receipts=None, authorization=None, review_gate=None):
    """VERIFIED only while the record is intact and everything it binds is unchanged; otherwise UNVERIFIED."""
    reasons, extra = [], {}

    def outcome(body=None):
        body = body if isinstance(body, dict) else {}
        return {"ok": True, "engine": ENGINE, "status": "UNVERIFIED" if reasons else "VERIFIED", "reasons": reasons,
                "record_sha256": body.get("record_sha256"), "planned_tag": body.get("planned_tag"), **extra}

    try:
        body = read_json_file(record_path, "record")
    except ReleaseError as error:
        _refuse(reasons, "record-unreadable", str(error))
        return outcome()
    if not isinstance(body, dict) or body.get("schema") != SCHEMA or "record_sha256" not in body:
        _refuse(reasons, "record-invalid", f"not a {SCHEMA} document")
        return outcome()
    claimed = body["record_sha256"]
    if claimed != digest({key: value for key, value in body.items() if key != "record_sha256"}):
        _refuse(reasons, "record-digest", "the record's bytes no longer match its own digest")
        return outcome(body)
    if {key: body.get(key) for key in PERFORMED} != PERFORMED or body.get("status") != STATUS:
        _refuse(reasons, "record-claims-action", "the record claims a tag, push, publication or deployment")
    root = pathlib.Path(_text(str(root), "root", 4096)).absolute()
    profile = _profile(profile, root)
    if digest(profile) != body.get("profile_sha256"):
        _refuse(reasons, "profile-changed", "the release profile differs from the recorded one")
    required = {(row["workflow"], row["job"]) for row in body.get("required_jobs") or []}
    if required != {(path, name) for path, names in profile["required_jobs"].items() for name in names}:
        _refuse(reasons, "required-jobs-changed", "the set of required CI jobs differs from the recorded one")
    head = _checkout(root, reasons)
    if head is None:
        return outcome(body)
    commit = body.get("tested_commit")
    if head != commit:
        _refuse(reasons, "commit-not-head", "the checkout HEAD is not the recorded tested commit")
    if _git(root, *CLEAN_STATUS):
        _refuse(reasons, "dirty-tree", "the checkout has uncommitted or untracked files")
    if isinstance(commit, str) and SHA.fullmatch(commit) and _probe(root, "cat-file", "-e", f"{commit}^{{commit}}") is not None:
        if _tree(root, commit) != body.get("tree"):
            _refuse(reasons, "tree-changed", "the tested commit's tree differs from the recorded tree")
    else:
        _refuse(reasons, "commit-unknown", "the recorded tested commit is not in this repository")
    base = body.get("base_commit")
    if base is not None and (not isinstance(base, str) or not SHA.fullmatch(base) or not isinstance(commit, str)
                             or _probe(root, "merge-base", "--is-ancestor", base, commit) is None):
        _refuse(reasons, "base-changed", "the recorded base is no longer an ancestor of the tested commit")
    problems, files = file_facts(root, profile)
    reasons += problems
    for field, code in (("changelog", "changelog-changed"), ("version_source", "version-source-changed"),
                        ("release_notes", "changelog-changed")):
        if not problems and files[field] != body.get(field):
            _refuse(reasons, code, f"{field} differs from the recorded bytes")
    recorded = {row["id"]: row for row in body.get("components") or [] if isinstance(row, dict) and "id" in row}
    for row in files["components"]:
        if recorded.get(row["id"]) != row:
            _refuse(reasons, "component-changed", f"{row['id']} ({row['path']}) differs from the recorded declaration")
    if set(recorded) != {row["id"] for row in profile["components"]}:
        _refuse(reasons, "component-changed", "the recorded component list differs from the profile")
    for value, field, code in ((receipts, "receipts_sha256", "receipts-changed"),
                               (authorization, "authorization", "authorization-changed"),
                               (review_gate, "review_gate", "review-gate-changed")):
        if value is None:
            continue
        recorded_sha = body.get(field) if field == "receipts_sha256" else (body.get(field) or {}).get("sha256")
        if digest(value) != recorded_sha:
            _refuse(reasons, code, f"the supplied {field.split('_sha256')[0]} differs from the recorded one")
    tag = body.get("planned_tag")
    if isinstance(tag, str) and tag.startswith(profile["tag_prefix"]):
        found = _probe(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
        extra["planned_tag_present_locally"] = bool(found)
        if found and found.strip() != commit:
            _refuse(reasons, "tag-on-other-commit", f"{tag} exists locally on another commit")
    return outcome(body)


# ---------------------------------------------------------------- hub release

def hub_record(version, commit, receipts, *, out, authorization=None, review_gate=None, root=ROOT, base=None,
               repository=None, now=None):
    """The hub's own release record: run after PR merge with HEAD at the merge commit. Status stays
    'recorded, tag pending' until the owner publishes the GitHub Release; nothing is tagged here."""
    return record(root, "hub", version, commit, out=out, now=now, receipts=receipts, authorization=authorization,
                  review_gate=review_gate, base=base, repository=repository)


def hub_version_status(root=ROOT):
    """The OS version source against the changelog, without Git: the single number a release must match."""
    profile = hub_profile(root)
    refusals, facts = file_facts(root, profile)
    source = (facts["version_source"] or {}).get("version")
    changelog = (facts["changelog"] or {}).get("version")
    return {"version_file": VERSION_FILE, "version": source, "changelog_top": changelog,
            "consistent": not refusals and source == changelog and bool(source and SEMVER.fullmatch(source)),
            "planned_tag": f"{profile['tag_prefix']}{source}" if source else None, "refusals": refusals,
            "components": [{key: row[key] for key in ("id", "path", "version")} for row in facts["components"]]}


# ---------------------------------------------------------------- control-plane facade

ENGINE_RECORD = {
    "id": ENGINE, "layer": "L11",
    "title": {"en": "Release Engine", "ar": "محرك الإصدار"},
    "entrypoint": "engineering_os.release_engine:engine",
    "health": "engineering_os.release_engine:health",
    "actions": {
        "eligibility": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"],
                        "summary": "ELIGIBLE or REFUSED with every reason for releasing one exact commit as one version."},
        "plan": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"],
                 "summary": "Eligibility plus the source-bound record body and the owner's exact commands; writes nothing."},
        "record": {"side_effect": "state-write", "permissions": ["read:repo", "write:state", "secrets:none"],
                   "summary": "Write the record of an ELIGIBLE release outside Git (0600, exclusive, no links); never tags."},
        "verify-record": {"side_effect": "none", "permissions": ["read:repo", "read:state", "secrets:none"],
                          "summary": "VERIFIED while a record and everything it binds are unchanged, else UNVERIFIED with reasons."},
    },
    "supersedes": [],
}
_EVIDENCE = {"receipts", "authorization", "review_gate"}
_SHAPES = {
    "eligibility": ({"root", "profile", "version", "commit"}, _EVIDENCE | {"base", "previous_version", "repository"}),
    "plan": ({"root", "profile", "version", "commit"}, _EVIDENCE | {"base", "previous_version", "repository", "now"}),
    "record": ({"root", "profile", "version", "commit"}, _EVIDENCE | {"base", "previous_version", "repository", "now", "out"}),
    "verify-record": ({"root", "profile", "record_path"}, _EVIDENCE),
}


def engine(action, payload, ctx=None):
    """Contract entrypoint `(action, payload, ctx) -> dict`; payload is data, never instructions."""
    _need(action in ENGINE_RECORD["actions"], f"unknown action {action!r}; allowed {sorted(ENGINE_RECORD['actions'])}")
    _need(isinstance(payload, dict), "payload must be an object")
    required, optional = _SHAPES[action]
    _need(required <= set(payload) <= required | optional,
          f"{action}: payload keys must include {sorted(required)} and stay within {sorted(required | optional)}")
    arguments = {key: value for key, value in payload.items() if key not in {"root", "profile", "version", "commit"}}
    if action == "verify-record":
        result = verify_record(payload["root"], payload["profile"], arguments.pop("record_path"), **arguments)
    elif action == "eligibility":
        refusals, facts = evaluate(payload["root"], payload["profile"], payload["version"], payload["commit"], **arguments)
        result = {"ok": True, "engine": ENGINE, "decision": "REFUSED" if refusals else "ELIGIBLE",
                  "eligible": not refusals, "refusals": refusals, "planned_tag": facts["planned_tag"],
                  "tested_commit": facts["tested_commit"], "performed": dict(PERFORMED)}
    elif action == "plan":
        result = plan(payload["root"], payload["profile"], payload["version"], payload["commit"], **arguments)
    else:
        if "out" not in arguments:
            state = ctx.get("state_dir") if isinstance(ctx, dict) else None
            _need(state is not None, "record: an out path or a private state directory (ctx.state_dir) is required")
            named = SEMVER.fullmatch(str(payload["version"])) and SHA.fullmatch(str(payload["commit"]))
            name = f"release-{payload['version']}-{payload['commit'][:12]}.json" if named else "release-refused.json"
            arguments["out"] = pathlib.Path(state) / "releases" / name  # written only when ELIGIBLE
        result = record(payload["root"], payload["profile"], payload["version"], payload["commit"], **arguments)
    return {**result, "action": action, "mode": MODE, "request_sha256": digest(payload)}


def health():
    """Loads the hub profile and checks the OS version source against the changelog; no Git, no writes."""
    try:
        status = hub_version_status(ROOT)
        _need(callable(_sdk().git) and callable(_sdk().checkout_guard), "hardened Git runner unavailable")
        profile = hub_profile(ROOT)
    except (ReleaseError, OSError, ImportError, AttributeError) as error:
        return {"ok": False, "detail": str(error)}
    jobs = sum(len(names) for names in profile["required_jobs"].values())
    state = "matches" if status["consistent"] else "does not match"
    return {"ok": True, "detail": f"{len(profile['components'])} components, {jobs} required jobs in "
                                  f"{len(profile['required_jobs'])} workflows; {VERSION_FILE} {status['version']} {state} "
                                  f"the changelog; never tags, pushes or deploys"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m engineering_os.release_engine", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("eligibility", "plan", "record", "hub-record"):
        one = commands.add_parser(name)
        if name != "hub-record":
            one.add_argument("--profile", default="hub", help="'hub' or a gaie.release-profile/1 JSON file")
        one.add_argument("--root", default=str(ROOT))
        one.add_argument("--version", required=True)
        one.add_argument("--commit", required=True)
        one.add_argument("--receipts", required=name == "hub-record", help=f"{RECEIPTS_SCHEMA} JSON file")
        one.add_argument("--authorization", help=f"{AUTHORIZATION_SCHEMA} JSON file")
        one.add_argument("--review-gate", help="independent review gate result JSON file")
        one.add_argument("--base")
        one.add_argument("--previous-version")
        one.add_argument("--repository")
        if name in ("record", "hub-record"):
            one.add_argument("--out", required=True)
            one.add_argument("--now")
    one = commands.add_parser("verify-record")
    one.add_argument("record")
    one.add_argument("--profile", default="hub")
    one.add_argument("--root", default=str(ROOT))
    for flag in ("--receipts", "--authorization", "--review-gate"):
        one.add_argument(flag)
    commands.add_parser("version")
    args = parser.parse_args(argv)
    try:
        if args.command == "version":
            result = hub_version_status(ROOT)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["consistent"] else 1
        profile = "hub" if args.command == "hub-record" or args.profile == "hub" else read_json_file(args.profile, "profile")
        evidence = {key: read_json_file(getattr(args, key), key) if getattr(args, key) else None
                    for key in ("receipts", "authorization", "review_gate")}
        if args.command == "verify-record":
            result = verify_record(args.root, profile, args.record, **evidence)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "VERIFIED" else 1
        options = dict(evidence, base=args.base, previous_version=args.previous_version, repository=args.repository)
        if args.command == "eligibility":
            refusals, facts = evaluate(args.root, profile, args.version, args.commit, **options)
            result = {"decision": "REFUSED" if refusals else "ELIGIBLE", "refusals": refusals,
                      "planned_tag": facts["planned_tag"], "performed": dict(PERFORMED)}
        elif args.command == "plan":
            result = plan(args.root, profile, args.version, args.commit, **options)
        else:
            result = record(args.root, profile, args.version, args.commit, out=args.out, now=args.now, **options)
            if result.get("written"):
                result["summary"] = (f"{result['planned_tag']} {STATUS}: the owner publishes the GitHub Release; "
                                     f"no tag was created")
    except (ReleaseError, OSError) as error:
        print(json.dumps({"ok": False, "error": type(error).__name__, "detail": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["decision"] == "ELIGIBLE" else 1


if __name__ == "__main__":
    sys.exit(main())
