"""SYNTHETIC Scenario G fixture: a throw-away Git repository and the release engine's acceptance cases.

Nothing here is a real release. The repository, CI receipts, owner authorizations and
review gate results are built in a temporary directory with fixed names, dates and
bytes, so the commit SHAs are identical on every host. Each case of
docs/specs/gaie-20-layers/RELEASE_ENGINE.md runs the engine against a fresh copy.
Git *write* commands (init, add, commit, tag, config) appear only in this fixture,
before the engine runs; while the engine runs, a recording `git` wrapper on PATH and a
Python audit hook (active only inside `call`) log every process and socket it starts.

Regenerate the committed evidence (run from the repository root):

    python3 tests/fixtures/release/scenario_g.py --out docs/evidence/gaie-20-layers/scenario-g.json
"""
import argparse
import contextlib
import copy
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import release_engine as engine  # noqa: E402

EVIDENCE = ROOT / "docs/evidence/gaie-20-layers/scenario-g.json"
COMMAND = "python3 tests/fixtures/release/scenario_g.py --out docs/evidence/gaie-20-layers/scenario-g.json"
SOURCES = ("engineering_os/release_engine.py", "tests/fixtures/release/scenario_g.py")
NOW = "2026-01-02T12:00:00Z"
VERSION = "1.1.0"
REPOSITORY = "example/synthetic"
REQUIRED = {".github/workflows/ci.yml": ["lint", "test"], ".github/workflows/security.yml": ["scan"]}
PROFILE = {
    "schema": engine.PROFILE_SCHEMA, "product": "synthetic", "title": "Synthetic", "tag_prefix": "synthetic-v",
    "changelog": "CHANGELOG.md", "changelog_heading": "Synthetic", "version_file": "VERSION",
    "components": [{"id": "synthetic", "path": "VERSION", "key": None},
                   {"id": "synthetic-pkg", "path": "pkg/package.json", "key": ["version"]}],
    "required_jobs": REQUIRED,
}
READ_ONLY = frozenset({"rev-parse", "status", "ls-tree", "merge-base", "tag", "cat-file", "config", "ls-files"})
WORKFLOW = "on: push\njobs:\n{jobs}"


def _files(version, package, entries):
    changelog = "# Changelog\n\n" + "".join(f"## Synthetic {v} — {d}\n\n- {text}\n\n" for v, d, text in entries)
    jobs = {path: "".join(f"  {name}:\n    runs-on: ubuntu-24.04\n    steps: [{{run: 'true'}}]\n" for name in names)
            for path, names in REQUIRED.items()}
    return {"README.md": "Synthetic repository for release engine tests. Not a product.\n",
            "VERSION": f"{version}\n", "CHANGELOG.md": changelog,
            "pkg/package.json": json.dumps({"name": "synthetic-pkg", "version": package}, indent=2) + "\n",
            **{path: WORKFLOW.format(jobs=body) for path, body in jobs.items()}}


def fixture_git(cwd, *args, date="2026-01-01T00:00:00+00:00"):
    """Fixture-only Git with a fixed identity, dates and no user or system configuration."""
    env = {"PATH": os.defpath, "LC_ALL": "C", "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "Synthetic", "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
           "GIT_COMMITTER_NAME": "Synthetic", "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
           "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True, env=env,
                          timeout=60).stdout


def _write(repo, files):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def build(directory):
    """Two commits: 1.0.0 (tagged synthetic-v1.0.0) then 1.1.0, the tested commit; an empty bare origin."""
    directory = pathlib.Path(directory)
    origin, repo = directory / "origin.git", directory / "repo"
    origin.mkdir(parents=True)
    repo.mkdir()
    fixture_git(origin, "init", "-q", "--bare", "-b", "main")
    fixture_git(repo, "init", "-q", "-b", "main")
    fixture_git(repo, "remote", "add", "origin", str(origin))
    _write(repo, _files("1.0.0", "3.2.0", [("1.0.0", "2026-01-01", "first release")]))
    fixture_git(repo, "add", "-A")
    fixture_git(repo, "commit", "-q", "-m", "release 1.0.0")
    base = fixture_git(repo, "rev-parse", "HEAD").strip()
    fixture_git(repo, "tag", "synthetic-v1.0.0")
    _write(repo, _files(VERSION, "3.2.1", [(VERSION, "2026-01-02", "second release"), ("1.0.0", "2026-01-01", "first release")]))
    fixture_git(repo, "add", "-A")
    fixture_git(repo, "commit", "-q", "-m", "release 1.1.0", date="2026-01-02T00:00:00+00:00")
    tested = fixture_git(repo, "rev-parse", "HEAD").strip()
    return {"directory": directory, "repo": repo, "origin": origin, "base": base, "tested": tested}


def receipts(commit, jobs=None):
    rows = [{"workflow": path, "job": name, "commit": commit, "status": "completed", "conclusion": "success",
             "run_id": 100 + index, "job_id": 1000 + index, "url": f"https://github.com/{REPOSITORY}/actions/runs/{100 + index}"}
            for index, (path, name) in enumerate((p, n) for p, names in REQUIRED.items() for n in names)]
    return {"schema": engine.RECEIPTS_SCHEMA, "commit": commit, "repository": REPOSITORY, "jobs": rows if jobs is None else jobs}


def authorization(commit, version=VERSION):
    return {"schema": engine.AUTHORIZATION_SCHEMA, "commit": commit, "version": version,
            "tag": f"synthetic-v{version}", "authorized_by": "owner",
            "reference": "SYNTHETIC owner instruction for the fixture", "at": "2026-01-02T10:00:00Z"}


def gate(commit, **change):
    result = {"passed": True, "commit": commit, "reviewer": "independent-assurance-engineer",
              "producer": "github-integration-release-engineer", "failed": []}
    result.update(change)
    return {key: value for key, value in result.items() if value is not None}


def inputs(fixture, commit=None, version=VERSION):
    commit = commit or fixture["tested"]
    return {"version": version, "commit": commit, "receipts": receipts(commit), "authorization": authorization(commit, version),
            "review_gate": gate(commit), "repository": REPOSITORY}


def _edit(path, old, new):
    data = path.read_bytes()
    assert data.count(old) == 1, (path.name, old)
    path.write_bytes(data.replace(old, new))


def _job(field, value, index=0):
    def change(f, args):
        args["receipts"]["jobs"][index][field] = value
    return change


def _set(key, value):
    def change(f, args):
        args[key] = value(f) if callable(value) else value
    return change


def _rows(function):
    def change(f, args):
        args["receipts"]["jobs"] = function(args["receipts"]["jobs"])
    return change


def _all(*changes):
    def change(f, args):
        for one in changes:
            one(f, args)
    return change


def _filter_program(f, args):
    fixture_git(f["repo"], "config", "filter.synthetic.clean", "cat")


def _higher_tag(f, args):
    fixture_git(f["repo"], "tag", "synthetic-v2.0.0", f["base"])


def _short(f, args):
    short = f["tested"][:12]
    args.update(inputs(f, commit=short), commit=short)


def _base_commit(f, args):
    args.update(inputs(f, commit=f["base"]))


def _version(version):
    def change(f, args):
        args.update(version=version, authorization=authorization(f["tested"], version))
    return change


def _not_a_repository(f, args):
    shutil.rmtree(f["repo"] / ".git")


# (id, criterion, change, expected decision, expected refusal codes, sorted)
CASES = (
    ("eligible", "G1-G8", None, "ELIGIBLE", []),
    ("dirty-tracked-file", "G1", lambda f, a: _edit(f["repo"] / "README.md", b"Not a product.", b"Not a product!"),
     "REFUSED", ["dirty-tree"]),
    ("dirty-untracked-file", "G1", lambda f, a: (f["repo"] / "notes.txt").write_text("x"), "REFUSED", ["dirty-tree"]),
    ("checkout-defines-filter-program", "G1", _filter_program, "REFUSED", ["checkout-unsafe"]),
    ("not-a-repository", "G1", _not_a_repository, "REFUSED", ["checkout-unsafe"]),
    ("commit-not-head", "G2", _base_commit, "REFUSED", ["commit-not-head"]),
    ("abbreviated-commit", "G2", _short, "REFUSED", ["commit-invalid"]),
    ("base-not-ancestor", "G2", _set("base", "f" * 40), "REFUSED", ["base-not-ancestor"]),
    ("receipt-for-another-sha", "G3", _job("commit", "BASE"), "REFUSED", ["job-receipt-other-commit"]),
    ("receipts-document-for-another-sha", "G3", _set("receipts", lambda f: receipts(f["base"])), "REFUSED",
     ["job-receipt-other-commit", "job-receipt-other-commit", "job-receipt-other-commit", "receipts-commit"]),
    ("required-job-missing", "G3", _rows(lambda rows: rows[:-1]), "REFUSED", ["job-receipt-missing"]),
    ("required-job-failed", "G3", _job("conclusion", "failure", 1), "REFUSED", ["job-failed"]),
    ("required-job-pending", "G3", _all(_job("status", "in_progress"), _job("conclusion", None)), "REFUSED", ["job-failed"]),
    ("required-job-ambiguous", "G3", _rows(lambda rows: rows + [dict(rows[0], run_id=999, job_id=9999)]), "REFUSED",
     ["job-receipt-ambiguous"]),
    ("receipts-missing", "G3", _set("receipts", None), "REFUSED", ["receipts-missing"]),
    ("authorization-missing", "G4", _set("authorization", None), "REFUSED", ["authorization-missing"]),
    ("authorization-for-another-sha", "G4", _set("authorization", lambda f: authorization(f["base"])), "REFUSED",
     ["authorization-commit"]),
    ("authorization-for-another-version", "G4", _set("authorization", lambda f: authorization(f["tested"], "1.2.0")),
     "REFUSED", ["authorization-tag", "authorization-version"]),
    ("version-invalid", "G5", _version("1.1.0-rc.1"), "REFUSED", ["authorization-tag", "version-invalid"]),
    ("version-not-greater-than-tag", "G5", _higher_tag, "REFUSED", ["version-not-increasing"]),
    ("version-not-greater-than-previous", "G5", _set("previous_version", "1.1.0"), "REFUSED", ["version-not-increasing"]),
    ("version-not-in-changelog", "G5", _version("1.2.0"), "REFUSED", ["version-changelog-mismatch", "version-source-mismatch"]),
    ("review-gate-missing", "G6", _set("review_gate", None), "REFUSED", ["review-gate-missing"]),
    ("review-gate-failed", "G6", _set("review_gate", lambda f: gate(f["tested"], passed=False)), "REFUSED",
     ["review-gate-failed"]),
    ("review-gate-blocked-item", "G6", _set("review_gate", lambda f: gate(f["tested"], blocked=["L11"])), "REFUSED",
     ["review-gate-failed"]),
    ("review-gate-verdict-block", "G6", _set("review_gate", lambda f: {"verdict": "block", "commit": f["tested"]}),
     "REFUSED", ["review-gate-failed"]),
    ("review-gate-for-another-sha", "G6", _set("review_gate", lambda f: gate(f["base"])), "REFUSED", ["review-gate-commit"]),
    ("review-gate-unbound", "G6", _set("review_gate", lambda f: gate(None)), "REFUSED", ["review-gate-unbound"]),
    ("review-gate-self-review", "G6", _set("review_gate", lambda f: gate(f["tested"], reviewer="github-integration-release-engineer")),
     "REFUSED", ["review-gate-self-review"]),
    ("review-gate-without-signal", "G6", _set("review_gate", lambda f: {"commit": f["tested"]}), "REFUSED",
     ["review-gate-invalid"]),
)


def _materialize(args, f):
    """Placeholders: a receipt commit of 'BASE' means the base commit."""
    for job in (args.get("receipts") or {}).get("jobs", []):
        if job.get("commit") == "BASE":
            job["commit"] = f["base"]
    return args


# ---------------------------------------------------------------- recording

_AUDIT = {"events": None}


def _hook(event, args):
    events = _AUDIT["events"]
    if events is None:
        return
    if event == "subprocess.Popen":
        events.append(("process", os.path.basename(str(args[0]))))
    elif event.startswith(("socket.", "urllib.", "http.")) or event in ("os.system", "os.posix_spawn", "os.exec", "os.spawn"):
        events.append(("network-or-exec", event))


if not getattr(sys, "_gaie_release_fixture_hook", False):
    sys.addaudithook(_hook)
    sys._gaie_release_fixture_hook = True


def subcommand(argv):
    index = 0
    while index < len(argv) and argv[index] in ("-c", "-C"):
        index += 2
    while index < len(argv) and argv[index].startswith("--"):
        index += 1
    return argv[index] if index < len(argv) else ""


@contextlib.contextmanager
def recording(directory):
    """Put a logging `git` first on PATH and record processes and sockets the engine starts."""
    real = shutil.which("git")
    bin_dir = pathlib.Path(directory) / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = pathlib.Path(directory) / "git.log"
    log.write_bytes(b"")
    wrapper = bin_dir / "git"
    wrapper.write_text("#!/bin/sh\n"
                       f"for a in \"$@\"; do printf '%s\\037' \"$a\" >> {shlex.quote(str(log))}; done\n"
                       f"printf '\\n' >> {shlex.quote(str(log))}\n"
                       f"exec {shlex.quote(real)} \"$@\"\n", encoding="utf-8")
    wrapper.chmod(0o755)
    seen = {"git": [], "events": []}
    saved = os.environ.get("PATH", "")
    os.environ["PATH"] = str(bin_dir) + os.pathsep + saved
    try:
        yield seen
    finally:
        os.environ["PATH"] = saved
        seen["git"] += [line.split("\x1f")[:-1] for line in log.read_text(encoding="utf-8", errors="replace").splitlines()]


def call(seen, action, payload):
    """One engine call with the audit hook on; fixture Git (PATH=os.defpath) stays outside both logs."""
    _AUDIT["events"] = seen["events"]
    try:
        return engine.engine(action, payload, {})
    finally:
        _AUDIT["events"] = None


def summary(seen):
    commands = [subcommand(argv) for argv in seen["git"]]
    writes = [argv for argv in seen["git"] if subcommand(argv) not in READ_ONLY
              or (subcommand(argv) == "tag" and "--list" not in argv)
              or (subcommand(argv) == "config" and "--list" not in argv)]
    return {"git_invocations": len(commands), "git_subcommands": sorted(set(commands)),
            "git_write_or_network_commands": len(writes),
            "processes_started": sum(1 for kind, _ in seen["events"] if kind == "process"),
            "non_git_processes": sum(1 for kind, name in seen["events"] if kind == "process" and name != "git"),
            "socket_exec_or_url_events": sum(1 for kind, _ in seen["events"] if kind == "network-or-exec")}


# ---------------------------------------------------------------- runs

def copy_fixture(template, directory):
    """A fresh working copy of the template repository (the shared origin stays the template's)."""
    target = pathlib.Path(directory)
    shutil.copytree(template["repo"], target / "repo", symlinks=True)
    return dict(template, directory=target, repo=target / "repo")


def run_case(template, case, directory, seen=None):
    name, criterion, change, expected, codes = case
    pathlib.Path(directory).mkdir(parents=True, exist_ok=True)
    f = copy_fixture(template, directory)
    args = inputs(f)
    if change is not None:
        change(f, args)
    args = _materialize(args, f)
    with recording(directory) if seen is None else contextlib.nullcontext(seen) as log:
        result = call(log, "eligibility", {"root": str(f["repo"]), "profile": copy.deepcopy(PROFILE), **args})
    return {"id": name, "criterion": criterion, "expected": expected, "observed": result["decision"],
            "expected_codes": codes, "observed_codes": sorted(row["code"] for row in result["refusals"])}, log


def record_cases(template, directory, seen):
    """Record refusals for unsafe destinations, then the write/verify/one-byte cycle."""
    pathlib.Path(directory).mkdir(parents=True, exist_ok=True)
    f = copy_fixture(template, pathlib.Path(directory) / "w")
    args = dict(inputs(f), now=NOW)
    payload = {"root": str(f["repo"]), "profile": copy.deepcopy(PROFILE), **args}
    outside = pathlib.Path(directory) / "records"
    outside.mkdir()
    target = outside / "real.json"
    target.write_text("{}")
    (outside / "link.json").symlink_to(target)
    (pathlib.Path(directory) / "linked-dir").symlink_to(outside, target_is_directory=True)
    results = []
    for name, out in (("record-path-symlink", outside / "link.json"),
                      ("record-path-parent-symlink", pathlib.Path(directory) / "linked-dir" / "new.json"),
                      ("record-path-in-repository", f["repo"] / "release-record.json"),
                      ("record-exists", target)):
        result = call(seen, "record", dict(payload, out=str(out)))
        results.append({"id": name, "criterion": "G7", "expected": "REFUSED", "observed": result["decision"],
                        "expected_codes": [name.replace("-parent", "")], "observed_codes": sorted(r["code"] for r in result["refusals"]),
                        "written": result["written"] is not None})
    good = outside / "release-1.1.0.json"
    written = call(seen, "record", dict(payload, out=str(good)))
    verify = {"root": str(f["repo"]), "profile": copy.deepcopy(PROFILE), "record_path": str(good)}
    steps = [("written", written["decision"], [r["code"] for r in written["refusals"]])]

    def check(step, **extra):
        outcome = call(seen, "verify-record", dict(verify, **extra))
        steps.append((step, outcome["status"], sorted(r["code"] for r in outcome["reasons"])))
    check("verify")
    original = good.read_bytes()
    good.write_bytes(original.replace(b'"status": "recorded, tag pending"', b'"status": "recorded, tag pendinG"'))
    check("record-one-byte-changed")
    good.write_bytes(original)
    check("record-restored")
    good.write_bytes(original[:-3])
    check("record-truncated")
    good.write_bytes(original)
    package = f["repo"] / "pkg/package.json"
    before = package.read_bytes()
    _edit(package, b'"3.2.1"', b'"3.2.2"')
    check("component-one-byte-changed")
    package.write_bytes(before)
    check("component-restored")
    check("other-receipts-supplied", receipts=receipts(f["base"]))
    check("same-inputs-supplied", receipts=args["receipts"], authorization=args["authorization"], review_gate=args["review_gate"])
    (outside / "via-link.json").symlink_to(good)
    check("record-read-through-symlink", record_path=str(outside / "via-link.json"))
    body = json.loads(original)
    return results, {"steps": [{"step": s, "status": status, "codes": codes} for s, status, codes in steps],
                     "record": {key: body[key] for key in ("schema", "product", "version", "planned_tag", "status",
                                                          "tag_created", "pushed", "published", "deployed", "base_commit",
                                                          "tested_commit", "tree", "required_jobs", "record_sha256")},
                     "owner_commands": [row["argv"] for row in body["owner_commands"]],
                     "rollback": body["rollback"]}


def evidence():
    """The Scenario G evidence document, built from a fresh synthetic repository."""
    with tempfile.TemporaryDirectory(prefix="gaie-g-") as scratch:
        scratch = pathlib.Path(scratch)
        template = build(scratch / "template")
        tags_before = fixture_git(template["repo"], "tag", "--list")
        cases = []
        with recording(scratch) as seen:
            for index, case in enumerate(CASES):
                result, _ = run_case(template, case, scratch / f"c{index}", seen)
                cases.append(result)
            records, cycle = record_cases(template, scratch / "r", seen)
        origin_refs = fixture_git(template["origin"], "for-each-ref")
        tags_after = fixture_git(template["repo"], "tag", "--list")
        executed = summary(seen)
        executed.update(origin_refs_after=len(origin_refs.splitlines()), template_tags_unchanged=tags_before == tags_after)
        return {
            "schema_version": 1, "kind": "scenario-g-acceptance", "layer": "L11", "scenario": "G",
            "synthetic": True, "simulated": False, "network": False, "model_calls": 0,
            "label": "SYNTHETIC: the repository, CI receipts, owner authorizations and review gate results are built by "
                     "tests/fixtures/release/scenario_g.py in a temporary directory. No real CI run, owner "
                     "authorization, tag or GitHub Release is represented, and nothing was deployed.",
            "command": COMMAND, "test": "tests/test_release_engine.py", "spec": "docs/specs/gaie-20-layers/RELEASE_ENGINE.md",
            "sources": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES},
            "synthetic_repository": {"base_commit": template["base"], "tested_commit": template["tested"],
                                     "version": VERSION, "required_jobs": REQUIRED, "repository": REPOSITORY},
            "cases": cases + records, "record_cycle": cycle, "commands_executed": executed,
            "claims_not_made": [
                "The engine was not run against this hub's own merge commit here; that needs the merged SHA and its CI.",
                "Receipt, authorization and review gate authenticity is outside the engine; it checks consistency only.",
                "Owner commands in the record were listed, never executed."],
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--check", action="store_true", help="compare with the committed evidence instead of writing")
    args = parser.parse_args(argv)
    document = evidence()
    text = json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if args.check:
        same = EVIDENCE.read_text(encoding="utf-8") == text
        print(json.dumps({"evidence": str(EVIDENCE.relative_to(ROOT)), "matches": same}))
        return 0 if same else 1
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
