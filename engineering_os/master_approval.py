"""Owner approval and source pinning for the existing GAIE MASTER router.

Approval is a launch-time trust input. The local tracking ref establishes the
ancestry visible in the checkout. Refresh it through the normal review workflow
before approving a release. No network or checkout mutation is needed here.
SPDX-License-Identifier: MIT
"""

import hashlib
import os
import pathlib
import re
import subprocess
import sys
import tempfile

from scripts.security_scan import bounded_run, secret_findings

from .orchestration import DIGEST, SECRET, _open_private, _safe_directory, load_json


HUB_URL = "https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub"
MAIN_REF = "refs/remotes/origin/main"
REVISION = re.compile(r"[a-f0-9]{40}")
GITHUB_PROJECT = re.compile(r"https://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?")
ENGINES = ("MASTER_BUILD", "MASTER_UPGRADE")
ROUTER = "engineering_os/gaie_router.py"
SOURCE_PATHS = (
    ROUTER,
    "governance/policies/gaie-routes.json",
    "projects/aliases.json",
    "projects/registry.json",
    "prompts/MASTER_BUILD.md",
    "prompts/MASTER_UPGRADE.md",
)
MAX_APPROVAL_SIZE = 16 * 1024
MAX_SOURCE_SIZE = 128 * 1024
ROOT = pathlib.Path(__file__).absolute().parents[1]
_ROUTER_LAUNCHER = """
import pathlib
import runpy
import sys

script, *options = sys.argv[1:]
command = pathlib.Path(".route-request").read_text(encoding="utf-8")
sys.argv = [script, "route", *options, "--", command]
runpy.run_path(script, run_name="__main__")
"""


class MasterApprovalError(ValueError):
    """An approved, merged MASTER router or a bound launch input is unavailable."""


def _directory(value):
    directory = pathlib.Path(value).absolute()
    if (".." in directory.parts or not directory.is_dir()
            or any(path.is_symlink() for path in (directory, *directory.parents))):
        raise MasterApprovalError("A canonical existing launch directory is required")
    return directory


def _approval(path, expected_sha256):
    if not isinstance(expected_sha256, str) or not DIGEST.fullmatch(expected_sha256):
        raise MasterApprovalError("Exact launch approval SHA256 is required")
    path = pathlib.Path(path).absolute()
    parent = _safe_directory(_directory(path.parent))
    fd = _open_private(parent / path.name, os.O_RDONLY)
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read(MAX_APPROVAL_SIZE + 1)
    if len(raw) > MAX_APPROVAL_SIZE or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise MasterApprovalError("Private owner approval bytes do not match the launch pin")
    value = load_json(raw)
    keys = {"schema_version", "repository", "revision", "approved_engines", "source_sha256"}
    if not isinstance(value, dict) or set(value) != keys:
        raise MasterApprovalError("Invalid MASTER approval fields")
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["repository"] != HUB_URL
            or value["approved_engines"] != list(ENGINES)
            or not isinstance(value["revision"], str) or not REVISION.fullmatch(value["revision"])):
        raise MasterApprovalError("Approval must name both MASTER engines at one exact hub revision")
    sources = value["source_sha256"]
    if (not isinstance(sources, dict) or set(sources) != set(SOURCE_PATHS)
            or any(not isinstance(digest, str) or not DIGEST.fullmatch(digest)
                   for digest in sources.values())):
        raise MasterApprovalError("Approval must pin the complete MASTER router source closure")
    return value


def _git(root, *args, limit=MAX_SOURCE_SIZE):
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_GRAFT_FILE": os.devnull,
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_TERMINAL_PROMPT": "0",
    }
    result = bounded_run(["git", "-C", str(root), *args], env=env, limit=limit, timeout=12)
    if result.returncode:
        raise MasterApprovalError("Tracked main or pinned MASTER source is unavailable")
    return result.stdout


def _merged_main(root, revision):
    top = pathlib.Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel").rstrip(b"\n")))
    if top != root:
        raise MasterApprovalError("The source root must be the hub checkout root")
    origin = _git(root, "config", "--local", "--no-includes", "--get-all", "remote.origin.url").splitlines()
    if origin not in ([HUB_URL.encode()], [(HUB_URL + ".git").encode()]):
        raise MasterApprovalError("The hub checkout must have the expected GitHub origin")
    main = _git(root, "rev-parse", "--verify", MAIN_REF + "^{commit}").decode("ascii").strip()
    if not REVISION.fullmatch(main):
        raise MasterApprovalError("The tracked main ref must resolve to an exact commit")
    if _git(root, "cat-file", "-t", revision).strip() != b"commit":
        raise MasterApprovalError("The approved source revision must be a commit object")
    _git(root, "merge-base", "--is-ancestor", revision, main)
    return main


def _project_slug(url):
    match = GITHUB_PROJECT.fullmatch(url) if isinstance(url, str) else None
    if match is None or any(part in (".", "..") for part in match.groups()):
        return None
    return "/".join(match.groups()).casefold()


def _bound_targets(route, workspace):
    """Upgrade can use only a raw local GitHub origin, never a rewrite or proxy."""
    targets = route.get("targets", [])
    if workspace is None or not targets:
        return
    origin_slug = None
    try:
        top = pathlib.Path(os.fsdecode(_git(workspace, "rev-parse", "--show-toplevel").rstrip(b"\n")))
        origin = _git(workspace, "config", "--local", "--no-includes", "--get-all", "remote.origin.url").splitlines()
        if top == workspace and len(origin) == 1:
            origin_slug = _project_slug(origin[0].decode("ascii"))
    except (MasterApprovalError, OSError, ValueError, subprocess.SubprocessError):
        pass
    for target in targets:
        target["workspace_matches"] = (target.get("workspace_matches") is True
                                       and origin_slug is not None
                                       and origin_slug == _project_slug(target.get("repository")))
    if not all(target["workspace_matches"] for target in targets):
        route["write_allowed"] = False


def _sources(root, approved):
    revision = approved["revision"]
    tree = _git(root, "ls-tree", "-rz", revision, "--", *SOURCE_PATHS)
    blobs = {}
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split(" ")
        path = name.decode("ascii")
        if (path not in SOURCE_PATHS or path in blobs or mode not in ("100644", "100755")
                or kind != "blob" or not REVISION.fullmatch(oid)):
            raise MasterApprovalError("MASTER source must be a regular pinned Git blob")
        data = _git(root, "cat-file", "blob", oid)
        if hashlib.sha256(data).hexdigest() != approved["source_sha256"][path]:
            raise MasterApprovalError("MASTER source differs from the owner approval")
        blobs[path] = data
    if set(blobs) != set(SOURCE_PATHS):
        raise MasterApprovalError("Incomplete MASTER router source closure")
    return blobs


def _verify(approval_file, approval_sha256, source_root):
    try:
        approved = _approval(approval_file, approval_sha256)
        root = _directory(ROOT if source_root is None else source_root)
        main = _merged_main(root, approved["revision"])
        blobs = _sources(root, approved)
    except MasterApprovalError:
        raise
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, subprocess.SubprocessError):
        raise MasterApprovalError("MASTER approval or pinned source could not be verified") from None
    return {
        "revision": approved["revision"],
        "main_revision": main,
        "approval_sha256": approval_sha256,
        "source_sha256": approved["source_sha256"],
    }, blobs


def verify_master_approval(*, approval_file, approval_sha256, source_root=None):
    """Check the private approval and immutable reviewed source without running it."""
    proof, _ = _verify(approval_file, approval_sha256, source_root)
    return proof


def approved_route(command, *, approval_file, approval_sha256, source_root=None, workspace_root=None):
    """Run the approved upstream router from checked Git blobs in a private snapshot.

    The optional upgrade checkout is selected at startup, never by the MCP
    request. The snapshot uses the pinned public registry and an empty private
    overlay. Skill discovery in the consuming host is a separate observation.
    """
    if (not isinstance(command, str) or not command.strip() or len(command) > 2000
            or "\x00" in command or SECRET.search(command) or secret_findings("route-request.txt", command)):
        raise MasterApprovalError("A bounded credential-free routing command is required")
    proof, blobs = _verify(approval_file, approval_sha256, source_root)
    try:
        with tempfile.TemporaryDirectory(prefix="gaie-master-source-") as temporary:
            directory = pathlib.Path(temporary)
            for relative, data in blobs.items():
                file = directory / relative
                file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                file.write_bytes(data)
            workspace = None if workspace_root is None else _directory(workspace_root)
            target = [] if workspace is None else ["--workspace", str(workspace)]
            (directory / ".route-request").write_text(command, encoding="utf-8")
            result = bounded_run(
                [sys.executable, "-I", "-B", "-c", _ROUTER_LAUNCHER, str(directory / ROUTER), *target],
                cwd=directory,
                # The router only reads GAIE_HOME/projects.json. A fixed
                # non-directory disables overlays even in Git-mapped sandboxes.
                env={"PATH": os.environ.get("PATH", os.defpath), "GAIE_HOME": os.devnull,
                     "LC_ALL": "C.UTF-8"},
                timeout=20,
                limit=MAX_SOURCE_SIZE,
            )
            if result.returncode not in (0, 2):
                raise MasterApprovalError("Approved MASTER router rejected its inputs")
            route = load_json(result.stdout)
            if (not isinstance(route, dict) or type(route.get("schema_version")) is not int
                    or route["schema_version"] != 1
                    or route.get("status") != ("routed" if result.returncode == 0 else "needs-clarification")):
                raise MasterApprovalError("Approved MASTER router returned invalid output")
            _bound_targets(route, workspace)
    except MasterApprovalError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, OverflowError, RecursionError, subprocess.SubprocessError):
        raise MasterApprovalError("Approved MASTER router could not run in its local scope") from None
    route.pop("command", None)
    route["master_approval"] = proof
    return route
