"""Write the public activation receipt: what ran on this host, with exit status and digests.

Regenerate it on the final commit with ONE command, from the hub root, on a host where
`activation/activate.sh all` installed the priority tools and the Headroom venv exists
(see integrations/headroom/README.md; this generator looks for it at
${GAIE_TOOLS:-~/.gaie-tools}/headroom-venv):

    python3 scripts/activation_receipt.py --out docs/evidence/gaie-20-layers/activation.json

On CI, or on a host without the tools (they are then reported not-installed, never ran-here):

    python3 scripts/activation_receipt.py --no-tools --out docs/evidence/gaie-20-layers/activation.json

Check a written receipt against the schema without running anything:

    python3 scripts/activation_receipt.py --validate docs/evidence/gaie-20-layers/activation.json

What one run does, in this order, all locally:

* host facts: CPU count, OS, and the versions of python, node, npm, ffmpeg, ffprobe, ripgrep,
  git and uv, and the browser builds present (names and versions, no paths);
* each priority tool in activation/tools.json: if its install exists, the repository's own
  functional test through `activation/activate.sh <tool>` (which installs nothing when the
  install exists), plus a comparison of the installed packages with the committed lock.
  This generator never installs: a missing tool is reported not-installed. Context7 is
  never started (it has no committed lock and its probe needs an API key);
* Headroom: the reviewed launcher `tools/headroom_context.py` run with the reviewed venv on a
  real tool output (`python3 hub.py capabilities`), then a full retrieval whose SHA-256
  must match the original. The limits that docs/headroom-context-engineering.md requires
  are copied into the receipt;
* every registered engine through the governed CLI `python3 hub.py invoke` with a grant
  minted for that one call (the activation scout's list of cheap payloads), plus three
  calls that must be refused with exit 3;
* each wave-2 engine through its own entry point (module CLI, or Python import where it has
  no CLI) on scratch copies of the repository's fixtures;
* the six GAIE skills: the first command a skill names is run where it is runnable alone.

No model or provider is called, no paid service, no key is read, nothing is deployed, and
nothing outside a private temporary directory is written except the --out file. The receipt
holds repository-relative paths only: host paths, the user name and temporary folders are
replaced before writing, and the write is refused if any remains.

Statuses: ran-here (ran during this generation with exit status and a digest of the lock or
source it ran against), installed-test-blocked (installed, but its functional test needs a
key or a host that is not reachable here), not-installed, catalog-only (recorded in the
repository but not run by this generator), failed-here (ran and failed; never hidden).

Values that `hub.py capabilities` and `hub.py motions` print (installed, operational,
runtime_verified, live_recheck_performed) are recorded catalogue values, not host detection.
This receipt does not use them as evidence that anything runs here.
Standard library only.
"""
import argparse
import datetime
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "gaie.activation-receipt/1"
RECEIPT = "docs/evidence/gaie-20-layers/activation.json"
COMMAND = "python3 scripts/activation_receipt.py --out " + RECEIPT
STATUSES = ("ran-here", "installed-test-blocked", "not-installed", "catalog-only", "failed-here")
SHA = re.compile(r"^[0-9a-f]{64}$")
GIT = ("git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
HOST_PATH = re.compile(r"(?<![\w.-])/(?:home|root|tmp|Users|var|private|opt|run|mnt|srv|usr|etc|proc|dev)(?:/[^\s\"'`,;:()<>\[\]{}]*)?")
PRIVATE_MARKERS = ("/home/", "/root/", "/Users/", "/tmp/", "/var/folders/", "session_0", "@gmail")
NETWORK_HINTS = ("ConnectionError", "ConnectError", "Name or service not known", "Temporary failure in name resolution",
                 "ENOTFOUND", "ECONNREFUSED", "ETIMEDOUT", "Network is unreachable", "HTTP Error 403", "403 Forbidden",
                 "ProxyError", "API key", "api key", "Unauthorized")
TIMEOUT = 600
# Result fields that repeat recorded catalogue values; they are left out of `observed` so that
# no row reads as if those values were measured here.
CATALOGUE_KEY = re.compile(r"runtime_verified|operational|live_recheck|^motions_|^installed$|^approved$")
ACTIVATE = "activation/activate.sh"
TOOLS_RECORD = "activation/tools.json"
# Where activate.sh runs its test with no network (its `offline` helper uses unshare -n when allowed).
OFFLINE_IN_SCRIPT = {"pydantic-ai"}
NETWORK_NOTES = {
    "inspect-ai": "activate.sh runs this test with the network available. Inspect AI reads a tokenizer file through "
                  "tiktoken's cache in the temporary folder and downloads it once from its public host when the cache "
                  "is empty; no provider is called.",
    "promptfoo": "telemetry and the update check are switched off by environment variables; the provider is echo.",
    "playwright-mcp": "the page is a data: URL and the browser is the one already on the host; nothing is downloaded.",
    "chrome-devtools-mcp": "the page is a data: URL; usage statistics and CrUX lookups are switched off.",
}
HEADROOM_LOCK = "integrations/headroom/requirements.lock"
HEADROOM_LAUNCHER = ("tools/headroom_context.py", "tools/headroom_worker.py")
HEADROOM_INSTALL = ("python3.12 -m venv <private>/headroom-venv && <private>/headroom-venv/bin/python -m pip --isolated "
                    "install --disable-pip-version-check --only-binary=:all: --require-hashes --no-compile "
                    "-r integrations/headroom/requirements.lock")
HEADROOM_LIMITS = [
    "Byte counts are UTF-8 bytes of this one sample (the JSON printed by `python3 hub.py capabilities`); they are not "
    "a compression promise for other content.",
    "exact_tokens stays null: no exact tokenizer count was made. estimated_tokens are the SDK's own sentinel-inclusive "
    "estimates, not provider token counts.",
    "context_usage and billing stay null: no model-context share, provider bill or monetary saving was measured.",
    "network_boundary is reported by the worker for its own process; it does not establish account-wide network isolation.",
    "Native Claude or Codex interception, MCP registration, proxy and wrapper modes were not activated or tested.",
    "compression_latency_ms is one sample on a shared host, not a latency percentile.",
    "Answer or task equivalence after compression was not measured; the full original was retrieved and its SHA-256 checked.",
]
CATALOGUE_NOTE = ("`hub.py capabilities` and `hub.py motions` print recorded catalogue values (for example installed:true, "
                  "operational:true, runtime_verified, live_recheck_performed:false); they are not host detection and "
                  "this receipt never cites them as evidence that something runs here.")
HISTORY = [
    {"path": "docs/evidence/capability-activation-2026-11-28.json",
     "status": "dated history",
     "note": "The priority-tool run of an earlier session on 2026-11-28, on another host. Its content is kept as measured. "
             "Current host results are the tools section of this receipt."},
    {"path": "docs/evidence/2026-11-28-operational-capability-validation.json",
     "status": "dated history",
     "note": "Validation recorded for release tag engineering-os-v0.1.3 in an earlier session. Several tool versions it "
             "names match neither the committed locks nor this host; it is kept as measured and is not current state."},
]


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(relative):
    path = ROOT / relative
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def files_digest(paths):
    files = {path: sha256_file(path) for path in paths}
    return files, sha256_bytes(json.dumps(files, sort_keys=True).encode())


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(argv, cwd=ROOT, env=None, timeout=TIMEOUT, data=None):
    """(exit, stdout, stderr, seconds); a missing program or a timeout is an exit, not an exception."""
    started = time.monotonic()
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, input=data, capture_output=True, text=True, timeout=timeout)
        result = done.returncode, done.stdout, done.stderr
    except FileNotFoundError:
        result = 127, "", f"{argv[0]}: not found"
    except subprocess.TimeoutExpired as error:
        result = 124, error.stdout or "", f"timed out after {timeout} s"
    return (*result, round(time.monotonic() - started, 2))


class Redactor:
    """Replace host paths and the user name; a receipt is written only when none remains."""

    def __init__(self, *private):
        user = ""
        try:
            user = getpass.getuser()
        except (KeyError, OSError):
            pass
        pairs = [(str(Path(value).resolve()), label) for value, label in private if value]
        pairs += [(str(ROOT), "<hub>"), (str(Path.home()), "~")]
        self.pairs = sorted({(value, label) for value, label in pairs if len(value) > 1}, key=lambda pair: -len(pair[0]))
        self.user = user

    def text(self, value):
        for raw, label in self.pairs:
            value = value.replace(raw, label)
        value = HOST_PATH.sub("<host-path>", value)
        # "root" is also an ordinary word here (the root-causes action); its home is already replaced above.
        if len(self.user) > 2 and self.user != "root":
            value = re.sub(rf"(?<![\w-]){re.escape(self.user)}(?![\w-])", "<user>", value)
        return value

    def tree(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.tree(item) for item in value]
        if isinstance(value, dict):
            return {self.text(key): self.tree(item) for key, item in value.items()}
        return value


def head(text, lines=8, width=160):
    rows = [ANSI.sub("", line).rstrip() for line in text.splitlines()]
    return [row[:width] for row in rows if row.strip()][:lines]


def observed(value, limit=8):
    """A few scalar fields of a result, so the receipt shows what came back without copying it."""
    if not isinstance(value, dict):
        return {"type": type(value).__name__}
    picked = {}
    for key, item in value.items():
        if CATALOGUE_KEY.search(key):
            continue
        if isinstance(item, bool) or isinstance(item, (int, float)) or item is None:
            picked[key] = item
        elif isinstance(item, str) and len(item) <= 80:
            picked[key] = item
        elif isinstance(item, (list, dict)):
            picked[key + "#len"] = len(item)
        if len(picked) >= limit:
            break
    return picked


# ---------------------------------------------------------------- host

def version_of(argv, pattern=r"\d+(?:\.\d+)+[\w.-]*"):
    if not shutil.which(argv[0]):
        return None
    code, out, err, _ = run(argv, timeout=30)
    match = re.search(pattern, (out or err).splitlines()[0] if (out or err) else "")
    return match.group(0) if code == 0 and match else None


def browsers():
    found = {}
    folder = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "/opt/pw-browsers")
    if folder.is_dir():
        found["playwright_builds"] = sorted(entry.name for entry in folder.iterdir()
                                            if entry.is_dir() and re.match(r"^[a-z_]+-\d+$", entry.name))
        chromium = folder / "chromium"
        if chromium.exists():
            found["playwright_chromium_version"] = version_of([str(chromium), "--version"])
    for name in ("google-chrome", "chromium", "firefox"):
        if shutil.which(name):
            found[name] = version_of([name, "--version"])
    return found


def host_facts():
    release = {}
    os_release = Path("/etc/os-release")
    if os_release.is_file():
        for line in os_release.read_text(errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key in ("NAME", "VERSION_ID"):
                release[key.lower()] = value.strip('"')
    try:
        load = [round(value, 2) for value in os.getloadavg()]
    except OSError:
        load = None
    return {
        "cpu_count": os.cpu_count(),
        "load_average_at_start": load,
        "os": {"system": platform.system(), "kernel": platform.release(), "machine": platform.machine(), **release},
        "python": platform.python_version(),
        "python3.12": version_of(["python3.12", "--version"]),
        "node": version_of(["node", "--version"]),
        "npm": version_of(["npm", "--version"]),
        "ffmpeg": version_of(["ffmpeg", "-version"]),
        "ffprobe": version_of(["ffprobe", "-version"]),
        "ripgrep": version_of(["rg", "--version"]),
        "git": version_of(["git", "--version"]),
        "uv": version_of(["uv", "--version"]),
        "unshare_network_namespace": run(["unshare", "-n", "true"], timeout=10)[0] == 0 if shutil.which("unshare") else False,
        "browsers": browsers(),
    }


def git_facts(out):
    code, sha, _, _ = run([*GIT, "rev-parse", "HEAD"], timeout=30)
    excluded = {out.resolve()} if out else set()
    code2, status, _, _ = run([*GIT, "status", "--porcelain", "--untracked-files=normal"], timeout=60)
    changed = []
    for line in status.splitlines():
        name = line[3:].strip().strip('"')
        if (ROOT / name).resolve() not in excluded:
            changed.append(name)
    return {"head": sha.strip() if code == 0 else None, "worktree_clean": code2 == 0 and not changed,
            "changed_paths": len(changed) if code2 == 0 else None}


# ---------------------------------------------------------------- priority tools

def tool_name(tool):
    return Path(tool["lock"]).parent.name if tool.get("lock") else tool["package"].rsplit("/", 1)[-1].replace("-mcp", "")


def lock_pins(text):
    return {re.sub(r"[-_.]+", "-", name).lower(): version
            for name, version in re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\;]+)", text, re.M)}


def python_installed(venv_python):
    script = ("import importlib.metadata as m, json\n"
              "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions()}))")
    code, out, _, _ = run([str(venv_python), "-I", "-c", script], timeout=60)
    if code != 0:
        return None
    return {re.sub(r"[-_.]+", "-", name).lower(): version for name, version in json.loads(out).items()}


def compare_python(tool, home):
    pins = lock_pins((ROOT / tool["lock"]).read_text())
    installed = python_installed(home / "venv" / "bin" / "python")
    if installed is None:
        return None, {"error": "the venv interpreter did not report its packages"}
    for helper in ("pip", "setuptools", "wheel"):
        if helper not in pins:
            installed.pop(helper, None)
    missing = sorted(set(pins) - set(installed))
    extra = sorted(set(installed) - set(pins))
    different = sorted(name for name in pins if name in installed and installed[name] != pins[name])
    version = installed.get(re.sub(r"[-_.]+", "-", tool["package"]).lower())
    return version, {"locked_packages": len(pins), "installed_packages": len(installed), "missing": missing,
                     "extra": extra, "different_version": different,
                     "matches_lock": not (missing or extra or different)}


def compare_npm(tool, home):
    lock = json.loads((ROOT / tool["lock"]).read_text())["packages"]
    record = home / "node_modules" / ".package-lock.json"
    if not record.is_file():
        return None, {"error": "node_modules/.package-lock.json is absent"}
    installed = {path: entry for path, entry in json.loads(record.read_text()).get("packages", {}).items() if path}
    wanted = {path: entry for path, entry in lock.items() if path}
    missing = sorted(path for path in wanted if path not in installed)
    skipped_optional = [path for path in missing if wanted[path].get("optional")]
    missing = [path for path in missing if not wanted[path].get("optional")]
    extra = sorted(path for path in installed if path not in wanted)
    different = sorted(path for path in wanted if path in installed
                       and (wanted[path].get("version"), wanted[path].get("integrity"))
                       != (installed[path].get("version"), installed[path].get("integrity")))
    manifest = home / "node_modules" / tool["package"] / "package.json"
    version = json.loads(manifest.read_text()).get("version") if manifest.is_file() else None
    return version, {"locked_packages": len(wanted), "installed_packages": len(installed),
                     "optional_platform_packages_not_installed": len(skipped_optional),
                     "missing": missing[:20], "extra": extra[:20], "different_version_or_integrity": different[:20],
                     "matches_lock": not (missing or extra or different)}


def installed_at(tool, home):
    if tool["ecosystem"] == "pypi":
        return (home / "venv" / "bin" / "python").exists()
    return (home / "node_modules").is_dir()


def tool_summary(name, output_dir):
    """Status and pass counts from the JSON the tool's own test wrote."""
    path = output_dir / f"{name}.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return {"output": "not JSON"}
    if name == "promptfoo":
        stats = data.get("results", {}).get("stats", {})
        return {"stats": {key: stats.get(key) for key in ("successes", "failures", "errors")},
                "expected": {"successes": 1, "failures": 1, "errors": 0}}
    rows = data.get("cases") or data.get("checks") or {}
    summary = {"status": data.get("status"), "passed": f"{sum(1 for row in rows.values() if row.get('passed'))}/{len(rows)}"}
    if data.get("reported"):
        summary["server_reported"] = data["reported"]
    if "version" in data:
        summary["test_reported_version"] = data["version"]
    if "provider_requests_allowed" in data:
        summary["provider_requests_allowed"] = data["provider_requests_allowed"]
    return summary


def tool_row(tool, activation_dir, no_tools, scratch):
    name = tool_name(tool)
    row = {"id": tool["id"], "name": name, "package": tool["package"], "ecosystem": tool["ecosystem"],
           "version_locked": tool["version"], "lock": tool.get("lock"),
           "lock_sha256": sha256_file(tool["lock"]) if tool.get("lock") else None,
           "test": tool.get("test"), "test_sha256": sha256_file(tool["test"]) if tool.get("test") else None,
           "script": ACTIVATE, "script_sha256": sha256_file(ACTIVATE), "probed": not no_tools,
           "not_proven": tool.get("not_proven", [])}
    if not tool.get("lock"):
        row.update(status="not-installed", command=None, exit=None, digest=None,
                   reason="no lock is committed for this tool, so activation/activate.sh has no target for it and this "
                          "generator does not start it; its probe also needs an API key the owner has not provided",
                   blocked_by=tool.get("blocked_by"))
        home = activation_dir / name
        if not no_tools and home.exists():
            row.update(status="installed-test-blocked",
                       reason="an install exists, but its probe sends a request to the vendor service and needs an "
                              "API key the owner has not provided; it was not run")
        return row
    command = f"{ACTIVATE} {name}"
    row["command"] = command
    if no_tools:
        row.update(status="not-installed", exit=None, digest=None,
                   reason="--no-tools mode: the tool was not looked for and not run")
        return row
    home = activation_dir / name
    if not installed_at(tool, home):
        row.update(status="not-installed", exit=None, digest=None,
                   reason="no install under the activation folder; this generator never installs (run activation/activate.sh)")
        return row
    compare = compare_python if tool["ecosystem"] == "pypi" else compare_npm
    version, lock_check = compare(tool, home)
    output_dir = scratch / f"out-{name}"
    output_dir.mkdir(mode=0o700)
    env = {**os.environ, "GAIE_TOOLS": str(activation_dir.parent), "ACTIVATION_OUT": str(output_dir)}
    code, out, err, seconds = run(["bash", str(ROOT / ACTIVATE), name], env=env)
    log = output_dir / "promptfoo.log"
    lines = head(out + err) + (head(log.read_text(errors="replace"), 30)[-5:] if name == "promptfoo" and log.is_file() else [])
    row.update(version_installed=version, lock_check=lock_check, exit=code, duration_s=seconds,
               network_isolated_by_script=name in OFFLINE_IN_SCRIPT, network_note=NETWORK_NOTES.get(name),
               output_head=lines,
               result=tool_summary(name, output_dir), digest=row["lock_sha256"], digest_of=tool["lock"])
    passed = code == 0 and re.search(rf"^passed +{re.escape(name)}$", out, re.M) is not None
    if passed and lock_check.get("matches_lock") and version == tool["version"]:
        row["status"] = "ran-here"
    elif passed:
        row.update(status="failed-here", reason="the test passed but the install does not match the committed lock")
    else:
        text = out + err + (log.read_text(errors="replace") if log.is_file() else "")
        hint = next((line.strip() for line in text.splitlines() if any(word in line for word in NETWORK_HINTS)), None)
        row.update(status="installed-test-blocked" if hint else "failed-here",
                   reason=(hint[:200] if hint else "the functional test failed; see output_head"))
    return row


def tool_rows(activation_dir, no_tools, scratch):
    record = json.loads((ROOT / TOOLS_RECORD).read_text())
    return [tool_row(tool, activation_dir, no_tools, scratch) for tool in record["tools"]]


# ---------------------------------------------------------------- headroom

def headroom_row(venv_python, no_tools, scratch):
    lock_text = (ROOT / HEADROOM_LOCK).read_text()
    launcher, launcher_digest = files_digest(HEADROOM_LAUNCHER)
    row = {"id": "headroomlabs-ai/headroom", "package": "headroom-ai", "version_locked": lock_pins(lock_text).get("headroom-ai"),
           "lock": HEADROOM_LOCK, "lock_sha256": sha256_file(HEADROOM_LOCK), "locked_artifacts": lock_text.count("--hash=sha256:"),
           "install_command": HEADROOM_INSTALL, "launcher": launcher, "probed": not no_tools}
    if no_tools:
        row.update(status="not-installed", exit=None, digest=None, reason="--no-tools mode: the SDK venv was not looked for")
        return row
    if not venv_python.exists():
        row.update(status="not-installed", exit=None, digest=None,
                   reason="no reviewed Headroom venv; this generator never installs (see integrations/headroom/README.md)")
        return row
    installed = python_installed(venv_python) or {}
    pins = lock_pins(lock_text)
    row["version_installed"] = installed.get("headroom-ai")
    row["lock_check"] = {"locked_packages": len(pins),
                         "different_or_missing": sorted(name for name in pins if installed.get(name) != pins[name]),
                         "matches_lock": all(installed.get(name) == pins[name] for name in pins)}
    code, out, err, seconds = run([str(venv_python), "tools/headroom_context.py", "status"], timeout=120)
    try:
        status = observed(json.loads(out), 12)
    except ValueError:
        status = head(out + err)
    row["status_command"] = {"command": "<venv>/bin/python tools/headroom_context.py status", "exit": code, "result": status}
    sample = scratch / "headroom-input" / "capabilities.json"
    sample.parent.mkdir(mode=0o700)
    code, out, err, _ = run([sys.executable, "hub.py", "capabilities"], timeout=120)
    if code != 0:
        row.update(status="failed-here", exit=code, digest=None, reason="the sample tool output could not be produced")
        return row
    sample.write_text(out)
    store = scratch / "headroom-store"
    command = ["tools/headroom_context.py", "optimize", "--input", str(sample), "--store", str(store), "--kind", "tool-json"]
    code, out, err, seconds = run([str(venv_python), *command], timeout=300)
    result = json.loads(out) if code == 0 and out.strip().startswith("{") else None
    row.update(command="<venv>/bin/python tools/headroom_context.py optimize --input <private sample> "
                       "--store <private store> --kind tool-json",
               sample={"produced_by": "python3 hub.py capabilities", "bytes": sample.stat().st_size,
                       "sha256": sha256_bytes(sample.read_bytes()),
                       "note": "the sample's content is catalogue data used only as real tool output to compress"},
               exit=code, duration_s=seconds, digest=row["lock_sha256"], digest_of=HEADROOM_LOCK,
               launcher_sha256=launcher_digest)
    if result is None:
        row.update(status="failed-here", reason="optimize did not return a JSON result", output_head=head(err))
        return row
    keep = ("status", "reason", "input_bytes", "output_bytes", "byte_reduction", "sdk_version", "lossless", "ccr_roundtrip",
            "protected_messages_unchanged", "network_boundary", "exact_tokens", "estimated_tokens",
            "compression_latency_ms", "context_usage", "billing", "native_agent_interception", "original_sha256", "output_sha256")
    measured = {key: result.get(key) for key in keep}
    if measured.get("input_bytes"):
        measured["byte_reduction_percent"] = round(100 * measured["byte_reduction"] / measured["input_bytes"], 2)
    if isinstance(measured.get("compression_latency_ms"), float):
        measured["compression_latency_ms"] = round(measured["compression_latency_ms"], 1)
    code, out, err, _ = run([str(venv_python), "tools/headroom_context.py", "retrieve", "--store", str(store),
                             "--id", result["original_sha256"], "--full"], timeout=120)
    retrieved = json.loads(out) if code == 0 and out.strip().startswith("{") else {}
    content = retrieved.get("content")
    measured["full_retrieval"] = {"exit": code, "complete": retrieved.get("complete"),
                                  "sha256_matches_original": isinstance(content, str)
                                  and sha256_bytes(content.encode()) == result["original_sha256"]}
    row["measurement"] = measured
    row["limits"] = HEADROOM_LIMITS
    ok = measured["status"] in ("optimized", "passthrough", "fallback") and measured["full_retrieval"]["sha256_matches_original"]
    row["status"] = "ran-here" if ok and row["lock_check"]["matches_lock"] else "failed-here"
    if row["status"] == "failed-here":
        row["reason"] = "the launcher result, its retrieval or the venv's match with the lock failed"
    return row


# ---------------------------------------------------------------- engines through hub.py invoke

def engine_cases(project, hub_root):
    """The activation scout's cheap payloads, one or more per registered engine (smoke list of 2026-11-28)."""
    moment = int(time.time())
    heal = {"schema_version": 1, "project": "synthetic", "source_sha256": "b" * 64, "baseline_sha256": "a" * 64,
            "baseline_tests": {"smoke": "passed", "legacy": "passed"}, "current_tests": {"smoke": "failed", "new": "failed"},
            "failures": [{"id": "storage", "component": "db", "kind": "runtime", "error_sha256": "e" * 64, "depends_on": []},
                         {"id": "api", "component": "backend", "kind": "test", "error_sha256": "f" * 64,
                          "depends_on": ["storage"]}],
            "performance": [{"id": "p95", "baseline_ms": 100, "current_ms": 150, "max_ratio": 1.2}],
            "dependencies": [{"package": "library", "required": ["1.0.0", "2.0.0"], "installed": "1.0.0"}],
            "evidence": {"project": "synthetic", "source_sha256": "b" * 64, "baseline_sha256": "a" * 64,
                         "at": moment - 5, "sha256": "c" * 64}}
    plan = {"schema_version": 1, "project": "activation-proj", "source_revision": "a" * 40,
            "requirements": [{"id": "r1", "summary": "Synthetic requirement.", "acceptance": ["unit"]}], "targets": ["api"]}
    memory = {"project": "activation-proj", "kind": "decision", "title": "Activation decision",
              "summary": "Activation receipt smoke record.", "tags": ["activation"], "symbols": [], "links": [],
              "provenance": {"engine": "claude-code", "source_sha256": "c" * 64}}
    causes = {"observations": [{"id": "storage", "status": "failed", "evidence_sha256": "a" * 64},
                               {"id": "api", "status": "failed", "evidence_sha256": "b" * 64}],
              "dependencies": {"storage": [], "api": ["storage"]}}
    cases = [
        ("security-governor", "validate-grant", {"grant": grant_for("memory", ["put"])}, "none", ()),
        ("security-governor", "check", {"grant": grant_for("memory", ["put"]), "engine": "memory", "action": "put"}, "none", ()),
        ("context-intelligence", "status", {}, "none", ()),
        ("context-intelligence", "view", {"text": "\n".join(["ok"] * 100 + ["ValueError: boom"]), "head": 2, "tail": 2},
         "none", ()),
        ("master-router", "route", {"text": "audit wow-bus"}, "none", ()),
        ("master-router", "route", {"text": "افحص سديد"}, "none", ()),
        ("master-router", "projects", {}, "none", ()),
        ("agent-swarm", "simulate", {"limit": 4, "agents": 8}, "none", ()),
        ("adaptive-scheduler", "next-wave", {"history": [], "limits": {"start": 4, "max_agents": 8}}, "none", ()),
        ("capability-registry", "search", {"query": "playwright"}, "none", ()),
        ("capability-registry", "recommend", {"query": "browser testing"}, "none", ()),
        ("layers", "status", {"layers": ["L01"]}, "none", ()),
        ("master-upgrade", "spec", {"scope": "comprehensive"}, "none", ()),
        ("master-upgrade", "plan", plan, "none", ()),
        ("motion-sdk", "catalog", {"query": "fade"}, "none", ()),
        ("motion-sdk", "runtime", {}, "none", ()),
        ("quality-assurance", "contracts", {}, "none", ()),
        # Since the PR #30 hardening the adapter always reads the Hub checkout, so the grant names it.
        ("quality-assurance", "run-tests", {"modules": ["tests.test_contracts"], "timeout": 300}, "workspace-write",
         (str(hub_root),)),
        ("master-release", "spec", {}, "none", ()),
        ("master-audit", "spec", {}, "none", ()),
        ("master-audit", "inventory", {"target": str(project)}, "none", (str(project),)),
        ("master-audit", "health", {}, "none", ()),
        ("master-audit", "hub-audit", {}, "none", ()),
        ("reasoning", "root-causes", causes, "none", ()),
        ("memory", "put", memory, "state-write", ()),
        ("memory", "search", {"project": "activation-proj", "query": "activation"}, "none", ()),
        ("memory", "graph", {"project": "activation-proj"}, "none", ()),
        ("master-build", "spec", {}, "none", ()),
        ("master-build", "plan", plan, "none", ()),
        ("self-healing", "analyze", heal, "none", ()),
        ("master-cinematic", "spec", {}, "none", ()),
        ("master-cinematic", "audit", {}, "none", ()),
        ("economics", "ledger", {}, "none", ()),
    ]
    denials = [  # must exit 3 with this reason: nothing runs
        ("memory", "put", memory, grant_for("memory", ["search"]), "action-not-granted"),
        ("master-audit", "inventory", {"target": str(hub_root)}, grant_for("master-audit", ["inventory"], paths=(str(project),)),
         "path-outside-grant"),
        ("quality-assurance", "run-tests", {"modules": ["tests.test_contracts"]}, grant_for("quality-assurance", ["run-tests"]),
         "side-effect-exceeds-grant"),
    ]
    return cases, denials


def grant_for(engine, actions, side="none", paths=()):
    expires = stamp(now_utc() + datetime.timedelta(hours=2))
    return {"grant_id": f"g-activation-{engine}", "role": "quality-assurance-engineer", "engines": {engine: list(actions)},
            "paths": list(paths), "max_side_effect": side, "expires_at": expires, "approvals": []}


def synthetic_project(folder):
    (folder / "src").mkdir(parents=True)
    (folder / "tests").mkdir()
    (folder / "src" / "__init__.py").write_text("")
    (folder / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (folder / "tests" / "__init__.py").write_text("")
    (folder / "tests" / "test_calc.py").write_text(
        "import unittest\nfrom src.calc import add\n\n\nclass T(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n")
    (folder / "README.md").write_text("# activation-proj\nTemporary synthetic project for the activation receipt.\n")
    (folder / "package.json").write_text('{"name":"activation-proj","version":"0.0.1","private":true}\n')
    return folder


def invoke(engine, action, payload, grant, scratch, index, env):
    grant_file = scratch / "grants" / f"{index:02d}-{engine}-{action}.json"
    grant_file.write_text(json.dumps(grant))
    argv = [sys.executable, "hub.py", "invoke", engine, action, "--payload", json.dumps(payload, ensure_ascii=False),
            "--grant", str(grant_file), "--state", str(scratch / "cp-state"), "--host", "claude-code"]
    code, out, err, seconds = run(argv, env=env)
    try:
        parsed = json.loads(out)
    except ValueError:
        parsed = None
    return code, parsed, out, err, seconds


def engine_rows(scratch, redact):
    project = synthetic_project(scratch / "proj")
    (scratch / "grants").mkdir(mode=0o700)
    env = {**os.environ, "GAIE_HOME": str(scratch / "gaie-home")}
    (scratch / "gaie-home").mkdir(mode=0o700)
    cases, denials = engine_cases(project, ROOT)
    template = "python3 hub.py invoke {engine} {action} --payload <payload> --grant <grant> --state <private state> --host claude-code"
    rows = []
    for index, (engine, action, payload, side, paths) in enumerate(cases):
        code, parsed, out, err, seconds = invoke(engine, action, payload, grant_for(engine, [action], side, paths),
                                                 scratch, index, env)
        receipt = (parsed or {}).get("receipt") or {}
        row = {"engine": engine, "action": action, "via": "hub.py invoke",
               "command": template.format(engine=engine, action=action),
               "payload_sha256": sha256_bytes(redact.text(json.dumps(payload, sort_keys=True, ensure_ascii=False)).encode()),
               "grant_side_effect": side, "exit": code, "duration_s": seconds, "ok": (parsed or {}).get("ok"),
               "receipt_side_effect": receipt.get("side_effect"), "result_sha256": receipt.get("result_sha256"),
               "digest": receipt.get("source_sha256"), "digest_of": "engine source files (control-plane receipt source_sha256)"}
        if code == 0 and row["ok"] is True and row["digest"]:
            row.update(status="ran-here", observed=observed((parsed or {}).get("result")))
        else:
            row.update(status="failed-here", output_head=head(out + err, 6))
        rows.append(row)
    refused = []
    deny_files, deny_digest = files_digest(("engineering_os/control_plane.py", "engineering_os/governor.py"))
    for index, (engine, action, payload, grant, reason) in enumerate(denials, start=len(cases)):
        code, parsed, out, err, seconds = invoke(engine, action, payload, grant, scratch, index, env)
        found = (parsed or {}).get("reason")
        refused.append({"engine": engine, "action": action, "via": "hub.py invoke",
                        "command": template.format(engine=engine, action=action), "expected_exit": 3,
                        "expected_reason": reason, "exit": code, "reason": found, "duration_s": seconds,
                        "digest": deny_digest, "digest_of": sorted(deny_files),
                        "status": "ran-here" if code == 3 and found == reason else "failed-here"})
    registered = [record["id"] for record in json.loads((ROOT / "governance/engines.json").read_text())]
    covered = {row["engine"] for row in rows}
    for engine in registered:
        if engine not in covered:
            rows.append({"engine": engine, "action": None, "via": "hub.py invoke", "status": "catalog-only",
                         "command": None, "exit": None, "digest": None,
                         "reason": "registered after this generator's case list was written; no cheap payload is defined here"})
    return rows, refused, registered


# ---------------------------------------------------------------- wave-2 engines through their entry points

UPGRADE_SNIPPET = """import json, sys
from engineering_os import upgrade_engine
report = upgrade_engine.engine("audit", {"target": sys.argv[1], "command": sys.argv[2], "workdir": sys.argv[3]},
                               {"environ": {"GAIE_HOME": sys.argv[4]}})
print(json.dumps({"status": report.get("status"), "mode": report["route"]["mode"], "language": report["route"]["language"],
                  "changes_made": report.get("changes_made"), "report_sha256": report.get("report_sha256")}, ensure_ascii=False))
"""
HEAL_SNIPPET = """import json, sys
from engineering_os import healing
report = healing.heal(sys.argv[1], workdir=sys.argv[2], tests={"start": "suite", "pattern": "case_*.py"})
print(json.dumps({"status": report.get("status"), "findings": len(report.get("findings", [])),
                  "kinds": sorted({row["kind"] for row in report.get("findings", [])}),
                  "receipt_chain_valid": report.get("receipt_chain_valid"), "report_sha256": report.get("report_sha256")}))
"""


def tree_digest(folder):
    rows = {path.relative_to(folder).as_posix(): sha256_bytes(path.read_bytes())
            for path in sorted(folder.rglob("*")) if path.is_file()}
    return sha256_bytes(json.dumps(rows, sort_keys=True).encode())


def wave2_rows(scratch):
    work = scratch / "wave2"
    work.mkdir(mode=0o700)
    home = work / "gaie-home"
    home.mkdir(mode=0o700)
    spec = work / "spec.json"
    taskapp = work / "taskapp"
    webapp = work / "webapp"
    shutil.copytree(ROOT / "tests/fixtures/upgrade/taskapp", taskapp)
    shutil.copytree(ROOT / "tests/fixtures/healing/webapp", webapp)
    before = {"taskapp": tree_digest(taskapp), "webapp": tree_digest(webapp)}
    command = "Build a new CRM system for a small sales team"
    audit_command = "افحص نظام إدارة المهام"
    moment = stamp(now_utc())
    cases = [
        ("requirements", "parse", "module CLI", [sys.executable, "-m", "engineering_os.requirements", "parse", command],
         f'python3 -m engineering_os.requirements parse "{command}"', "engineering_os/requirements.py", None),
        ("build_engine", "plan", "module CLI", [sys.executable, "-m", "engineering_os.build_engine", "plan", "--spec", str(spec)],
         "python3 -m engineering_os.build_engine plan --spec <spec from requirements parse>", "engineering_os/build_engine.py", None),
        ("orchestrator", "plan", "module CLI",
         [sys.executable, "-m", "engineering_os.orchestrator", "plan", "activation-receipt", "--now", moment, "--summary"],
         "python3 -m engineering_os.orchestrator plan activation-receipt --now <generation time> --summary",
         "engineering_os/orchestrator.py", None),
        ("video_pipeline", "validate", "module CLI", [sys.executable, "-m", "engineering_os.video_pipeline", "validate", "sample"],
         "python3 -m engineering_os.video_pipeline validate sample", "engineering_os/video_pipeline.py", None),
        ("upgrade_engine", "audit", "Python import (the module has no command line)",
         [sys.executable, "-c", UPGRADE_SNIPPET, str(taskapp), audit_command, str(work / "upgrade-run"), str(home)],
         f'upgrade_engine.engine("audit", {{target: <copy of tests/fixtures/upgrade/taskapp>, command: "{audit_command}", '
         'workdir: <scratch>})', "engineering_os/upgrade_engine.py", "taskapp"),
        ("healing", "heal", "Python import (the module has no command line)",
         [sys.executable, "-c", HEAL_SNIPPET, str(webapp), str(work / "heal-run")],
         'healing.heal(<copy of tests/fixtures/healing/webapp>, workdir=<scratch>, tests={start: suite, pattern: case_*.py})',
         "engineering_os/healing.py", "webapp"),
    ]
    rows = []
    for module, action, via, argv, shown, source, fixture in cases:
        code, out, err, seconds = run(argv, env={**os.environ, "GAIE_HOME": str(home)})
        try:
            result = json.loads(out)
        except ValueError:
            result = None
        if module == "requirements" and code == 0 and result:
            spec.write_text(out)
        row = {"engine": module, "action": action, "via": via, "command": shown, "exit": code, "duration_s": seconds,
               "digest": sha256_file(source), "digest_of": source, "governed": False}
        ok = code == 0 and isinstance(result, dict)
        if module == "requirements" and ok:
            row["observed"] = {"schema": result.get("schema"), "slug": result.get("slug"), "intent": result.get("intent"),
                               "features": len(result.get("features", [])),
                               "open_questions": len(result.get("open_questions", []))}
        elif ok:
            row["observed"] = observed(result)
        if fixture:
            row["fixture"] = f"tests/fixtures/{'upgrade' if fixture == 'taskapp' else 'healing'}/{fixture}"
            row["fixture_unchanged"] = tree_digest(work / fixture) == before[fixture]
            ok = ok and row["fixture_unchanged"]
        ok = ok and {"requirements": lambda r: r.get("schema") == "gaie.spec/1",
                     "build_engine": lambda r: r.get("ready") is True,
                     "orchestrator": lambda r: all((r.get("checks") or {"x": False}).values()),
                     "video_pipeline": lambda r: r.get("valid") is True,
                     "upgrade_engine": lambda r: r.get("status") == "audited",
                     "healing": lambda r: r.get("status") == "repaired"}[module](result or {})
        row["status"] = "ran-here" if ok else "failed-here"
        if not ok:
            row["output_head"] = head(out + err, 6)
        rows.append(row)
    return rows


# ---------------------------------------------------------------- skills

def skill_rows():
    rows = []
    for folder in sorted((ROOT / "skills").glob("gaie-*")):
        relative = f"skills/{folder.name}/SKILL.md"
        row = {"skill": folder.name, "file": relative, "file_sha256": sha256_file(relative),
               "native_skill_load": "not tested: loading a skill needs an agent host session, which this generator does not start"}
        if folder.name == "gaie-master-router":
            words = "افحص سديد"
            code, out, err, seconds = run([sys.executable, "hub.py", "route", words], timeout=120)
            try:
                result = json.loads(out)
            except ValueError:
                result = {}
            ok = code == 0 and result.get("status") == "routed"
            row.update(status="ran-here" if ok else "failed-here", command=f'python3 hub.py route "{words}"',
                       scope="the first command the skill names, run alone", exit=code, duration_s=seconds,
                       digest=sha256_file("engineering_os/gaie_router.py"), digest_of="engineering_os/gaie_router.py",
                       observed={key: result.get(key) for key in ("status", "engine", "engine_id", "skill", "language")})
        else:
            row.update(status="catalog-only", command=None, exit=None, digest=None,
                       reason="instructions for an agent host; the engines and commands it names are run in the engines "
                              "and wave2 sections, not through the skill")
        rows.append(row)
    return rows


# ---------------------------------------------------------------- receipt

def build(no_tools, tools_home, out):
    started = now_utc()
    activation_dir = Path(tools_home) / "activation"
    venv_python = Path(tools_home) / "headroom-venv" / "bin" / "python"
    with tempfile.TemporaryDirectory(prefix="gaie-act-") as folder:
        scratch = Path(folder)
        redact = Redactor((folder, "<scratch>"), (str(tools_home), "<tools>"), (tempfile.gettempdir(), "<tmp>"))
        host = host_facts()
        git = git_facts(out)
        tools = tool_rows(activation_dir, no_tools, scratch)
        headroom = headroom_row(venv_python, no_tools, scratch)
        engines, refusals, registered = engine_rows(scratch, redact)
        wave2 = wave2_rows(scratch)
        skills = skill_rows()
        receipt = {
            "schema": SCHEMA,
            "title": "Activation receipt: approved tools, Headroom, engines and skills run on this host",
            "mode": "no-tools" if no_tools else "full",
            "generated_at_utc": stamp(started),
            "duration_s": round((now_utc() - started).total_seconds(), 1),
            "generator": {"path": "scripts/activation_receipt.py", "sha256": sha256_file("scripts/activation_receipt.py"),
                          "command": COMMAND + (" --no-tools" if no_tools else ""),
                          "regenerate": COMMAND},
            "git": git,
            "statuses": {"ran-here": "ran during this generation; exit status and a digest of the lock or source it ran "
                                     "against are recorded",
                         "installed-test-blocked": "installed, but its functional test needs a key or an unreachable host",
                         "not-installed": "no install found (or not looked for in --no-tools mode)",
                         "catalog-only": "recorded in the repository; not run by this generator",
                         "failed-here": "ran during this generation and failed"},
            "provider_calls": 0, "paid_services": 0, "keys_read": 0, "deployments": 0,
            "host": host,
            "tools": tools,
            "headroom": headroom,
            "engines": engines,
            "refusals": refusals,
            "registered_engines": registered,
            "wave2": wave2,
            "skills": skills,
            "catalogue_values": CATALOGUE_NOTE,
            "observed_note": "engines[].observed and wave2[].observed hold a few scalar fields of each result, to show "
                             "what came back; counts in them are what an engine read from the repository, not host "
                             "detection, and fields that repeat catalogue values are left out.",
            "history": [{**item, "sha256": sha256_file(item["path"])} for item in HISTORY],
            "not_proven": [
                "attachment of the MCP servers to an agent host session (they are driven by a stdio probe)",
                "any call to a real model provider; the tests use scripted, mock or echo models",
                "native Claude or Codex skill loading; only the first command of the router skill is run",
                "governance of the wave-2 engines: they run through their own entry points with no grant or control-plane receipt",
                "Firefox or WebKit; only the browser builds listed under host.browsers are present",
            ],
        }
        receipt = redact.tree(receipt)
    receipt["summary"] = summarize(receipt)
    return receipt


def summarize(receipt):
    def count(rows):
        result = {}
        for row in rows:
            result[row["status"]] = result.get(row["status"], 0) + 1
        return dict(sorted(result.items()))
    engines = [row for row in receipt["engines"] if row.get("action")]
    return {"tools": count(receipt["tools"]), "headroom": receipt["headroom"]["status"],
            "engine_calls": count(receipt["engines"]), "engines_covered": len({row["engine"] for row in engines}),
            "refusals": count(receipt["refusals"]), "wave2": count(receipt["wave2"]), "skills": count(receipt["skills"])}


def rows_of(receipt):
    for section in ("tools", "engines", "refusals", "wave2", "skills"):
        for row in receipt.get(section) or []:
            yield section, row
    if isinstance(receipt.get("headroom"), dict):
        yield "headroom", receipt["headroom"]


def validate(receipt):
    """Problems with a receipt, as strings; an empty list means it satisfies the schema."""
    problems = []
    if not isinstance(receipt, dict):
        return ["the receipt is not a JSON object"]
    if receipt.get("schema") != SCHEMA:
        problems.append("schema is not " + SCHEMA)
    if receipt.get("mode") not in ("full", "no-tools"):
        problems.append("mode must be full or no-tools")
    generator = receipt.get("generator") or {}
    if generator.get("path") != "scripts/activation_receipt.py" or not SHA.match(str(generator.get("sha256"))):
        problems.append("generator path and sha256 are required")
    for key in ("cpu_count", "os", "python", "node", "npm", "ffmpeg", "browsers"):
        if key not in (receipt.get("host") or {}):
            problems.append(f"host.{key} is missing")
    for section in ("tools", "engines", "refusals", "wave2", "skills"):
        if not isinstance(receipt.get(section), list) or not receipt[section]:
            problems.append(f"{section} must be a non-empty list")
    if not isinstance(receipt.get("headroom"), dict):
        problems.append("headroom must be an object")
    for section, row in rows_of(receipt):
        label = f"{section}:{row.get('id') or row.get('engine') or row.get('skill')}:{row.get('action', '')}"
        status = row.get("status")
        if status not in STATUSES:
            problems.append(f"{label} has an unknown status {status!r}")
            continue
        if status == "ran-here":
            if not isinstance(row.get("exit"), int) or isinstance(row.get("exit"), bool):
                problems.append(f"{label} claims ran-here without an exit status")
            elif row["exit"] != (3 if section == "refusals" else 0):
                problems.append(f"{label} claims ran-here with exit {row['exit']}")
            if not SHA.match(str(row.get("digest"))):
                problems.append(f"{label} claims ran-here without a sha256 digest")
            if not row.get("command"):
                problems.append(f"{label} claims ran-here without a command")
            if not isinstance(row.get("duration_s"), (int, float)):
                problems.append(f"{label} claims ran-here without a duration")
        if section in ("tools", "headroom") and status in ("ran-here", "installed-test-blocked") \
                and receipt.get("mode") == "no-tools":
            problems.append(f"{label} cannot be {status} in --no-tools mode")
        if section in ("tools", "headroom") and status == "ran-here":
            if not (row.get("lock_check") or {}).get("matches_lock"):
                problems.append(f"{label} claims ran-here but its install does not match the lock")
            if row.get("version_installed") != row.get("version_locked"):
                problems.append(f"{label} claims ran-here with a version other than the locked one")
        if status in ("installed-test-blocked", "not-installed", "catalog-only") and not row.get("reason"):
            problems.append(f"{label} is {status} without a reason")
        if status == "failed-here" and not (row.get("reason") or row.get("output_head")):
            problems.append(f"{label} is failed-here without a reason or output")
    text = json.dumps(receipt, ensure_ascii=False)
    for marker in PRIVATE_MARKERS:
        if marker in text:
            problems.append(f"the receipt contains a private marker {marker!r}")
    if re.search(r"(?i)(api[_-]?key|token|secret|password)\"\s*:\s*\"[^\"<]{8,}", text):
        problems.append("the receipt contains a value under a credential-like key")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="write the receipt here (repository-relative or absolute); default: print it")
    parser.add_argument("--no-tools", action="store_true",
                        help="do not look for or run the priority tools or the Headroom SDK (CI, or a host without them)")
    parser.add_argument("--tools-home", default=os.environ.get("GAIE_TOOLS") or str(Path.home() / ".gaie-tools"),
                        help="folder holding activation/ and headroom-venv/ (default: $GAIE_TOOLS or ~/.gaie-tools)")
    parser.add_argument("--validate", metavar="RECEIPT", help="check a written receipt and run nothing")
    args = parser.parse_args(argv)
    if args.validate:
        problems = validate(json.loads(Path(args.validate).read_text()))
        print(json.dumps({"valid": not problems, "problems": problems}, indent=1, ensure_ascii=False))
        return 0 if not problems else 1
    out = (ROOT / args.out) if args.out and not Path(args.out).is_absolute() else (Path(args.out) if args.out else None)
    receipt = build(args.no_tools, args.tools_home, out)
    problems = validate(receipt)
    text = json.dumps(receipt, indent=1, ensure_ascii=False) + "\n"
    if problems:
        print(json.dumps({"written": False, "problems": problems}, indent=1, ensure_ascii=False), file=sys.stderr)
        return 1
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(json.dumps({"written": str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else "outside the hub",
                          "mode": receipt["mode"], "summary": receipt["summary"]}, indent=1))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
