"""Read-only preflight for MASTER write scopes on the local host."""

import os
import pathlib
import re
import shutil
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass


class WorkspacePolicyError(ValueError):
    """The proposed scope could not be verified."""


class WorkspaceTaintedError(WorkspacePolicyError):
    """The child ran, then left Git metadata, a link or a special file in its writable root.

    `result` is the governor's run result. Nothing is removed: the operator inspects the tree
    before any host-side Git runs there, and the next launch of that agent is refused.
    """

    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class WorkspaceScope:
    root: pathlib.Path
    branch: str | None
    checkout: pathlib.Path


REPO = re.compile(r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]*)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?")
REMOTE = re.compile(
    r"(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:"
    r"|https?://local_proxy@(?:127\.0\.0\.1|localhost):[0-9]+/git/)(?P<path>.+)"
)
BRANCH = re.compile(r"(?:codex|claude)/[A-Za-z0-9][A-Za-z0-9._/-]{0,119}")
REPO_INTENTS = frozenset({"upgrade", "accelerate", "repair", "cinematic"})
AGENT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
ASSIGNMENT_KEYS = frozenset({"path", "intent", "expected_repository", "registered_path"})


def _repo_id(value):
    if not isinstance(value, str):
        return None
    remote = REMOTE.fullmatch(value)
    match = REPO.fullmatch(remote["path"] if remote else value)
    if not match or not match["repo"].strip("."):
        return None
    return f"{match['owner']}/{match['repo']}".casefold()


def _plain_path(value):
    if not isinstance(value, (str, os.PathLike)):
        raise WorkspacePolicyError("A workspace path is required.")
    value = os.fspath(value)
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise WorkspacePolicyError("A workspace must be a nonempty path without control characters.")
    path = pathlib.Path(value)
    if ".." in path.parts:
        raise WorkspacePolicyError("Workspace path traversal is refused.")
    return _canonical(path.absolute())


def _canonical(path):
    """Reject symbolic links in every component of a known absolute path."""
    if not path.is_absolute():
        raise WorkspacePolicyError("Workspace paths must be absolute after normalization.")
    if path != path.resolve(strict=True):
        raise WorkspacePolicyError("Symlinked workspace paths are refused.")
    return path


def _owned(path, *, file=False, private=False):
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    expected = stat.S_ISREG if file else stat.S_ISDIR
    if (not expected(info.st_mode) or info.st_uid != os.geteuid()
            or (mode != 0o700 if private else mode & 0o022)):
        raise WorkspacePolicyError("Workspace and its Git identity must be owned and protected from other users.")
    if file and info.st_nlink != 1:
        raise WorkspacePolicyError("Hard-linked Git identity files are refused.")
    return info


def _read_pointer(path, *, prefix=""):
    _owned(path, file=True)
    with path.open("rb") as stream:
        data = stream.read(4097)
    if len(data) > 4096:
        raise WorkspacePolicyError("Git worktree identity pointer is too long.")
    value = data.decode("utf-8").rstrip("\n")
    if not value.startswith(prefix) or any(ord(char) < 32 for char in value):
        raise WorkspacePolicyError("Invalid Git worktree identity pointer.")
    value = value[len(prefix):]
    if not value:
        raise WorkspacePolicyError("Empty Git worktree identity pointer.")
    return _canonical(pathlib.Path(os.path.abspath(path.parent / value)))


def _git_checkout_marker(directory):
    marker = directory / ".git"
    return marker.is_symlink() or marker.is_file() or (marker.is_dir() and any(marker.iterdir()))


def _bare_repository(directory):
    return (directory / "HEAD").is_file() and (directory / "objects").is_dir() and (directory / "refs").is_dir()


def _new_workspace(path, *, initial=True):
    _owned(path, private=True)
    if any(_git_checkout_marker(directory) or _bare_repository(directory) for directory in (path, *path.parents)):
        raise WorkspacePolicyError("A new build workspace must be outside existing Git repositories.")
    if initial and any(path.iterdir()):
        raise WorkspacePolicyError("A new build workspace must be empty.")
    return WorkspaceScope(path, None, path)


# Every checkout Git call runs offline: a partial-clone lazy fetch would start the transport (and the
# upload-pack, ssh or remote-helper program) that the checkout's own config names. GIT_ALLOW_PROTOCOL set to
# an empty list overrides any protocol.<name>.allow in that config; GIT_NO_LAZY_FETCH is honoured by Git
# releases that carry it (2.43.0-1ubuntu7.4 here does; the --no-lazy-fetch option it lacks is not used).
GIT_FLAGS = ("--no-pager", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
             "-c", "core.hooksPath=/dev/null", "-c", "protocol.allow=never")
GIT_OFFLINE_ENV = {"GIT_ALLOW_PROTOCOL": "", "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}
# Canonical config names (section and key lower case) that name a program, a hook, a fetch source or a
# protocol policy. extensions.worktreeConfig and extensions.objectFormat are the only repository
# extensions a write scope accepts; extensions.partialClone and remote.<x>.promisor or
# .partialCloneFilter make object lookups fetch.
DENIED_CONFIG = re.compile(
    r"(include|includeif|url|filter|protocol)\..*|core\.(hookspath|sshcommand|gitproxy)"
    r"|remote\..+\.(promisor|partialclonefilter|uploadpack|receivepack|vcs)"
    r"|extensions\.(?!(worktreeconfig|objectformat)$).*",
    re.DOTALL,
)


def _git(path, *args, absent=False):
    executable = shutil.which("git", path=os.defpath)
    if executable is None:
        raise WorkspacePolicyError("Local Git is unavailable for workspace verification.")
    env = {"PATH": os.defpath, "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_OPTIONAL_LOCKS": "0", **GIT_OFFLINE_ENV}
    result = subprocess.run(
        [executable, GIT_FLAGS[0], "-C", str(path), *GIT_FLAGS[1:], *args],
        capture_output=True, text=True, encoding="utf-8", timeout=10, check=False, env=env,
    )
    if absent and result.returncode == 1 and not result.stdout:
        return ""
    if result.returncode:
        raise WorkspacePolicyError("Git could not verify the proposed workspace.")
    return result.stdout


def _registry_scope(path, registered_path):
    if registered_path is None:
        return path
    if not isinstance(registered_path, str) or not registered_path or "\\" in registered_path:
        raise WorkspacePolicyError("The registered project path must be relative and explicit.")
    parts = registered_path.split("/")
    if any(part in {"", ".", "..", ".git"} or any(ord(char) < 32 for char in part) for part in parts):
        raise WorkspacePolicyError("The registered project path is unsafe.")
    root = path
    for part in parts:
        root = _plain_path(root / part)
        _owned(root)
        if _git_checkout_marker(root) or _bare_repository(root):
            raise WorkspacePolicyError("The registered scope is itself a nested repository.")
    return root


def _linked_git_identity(path):
    marker = path / ".git"
    if not marker.is_file():
        raise WorkspacePolicyError("Use the exact root of a dedicated linked Git worktree.")
    metadata = _read_pointer(marker, prefix="gitdir: ")
    common = _read_pointer(metadata / "commondir")
    _owned(metadata)
    _owned(common)
    if metadata.parent != common / "worktrees" or _read_pointer(metadata / "gitdir") != marker:
        raise WorkspacePolicyError("Git's linked worktree registration does not match this checkout.")
    for config in (common / "config", metadata / "config.worktree"):
        if config.exists() or config.is_symlink():
            _owned(config, file=True)
            names = _git(pathlib.Path("/"), "config", "--file", str(config), "--no-includes",
                         "--name-only", "--null", "--list").split("\0")
            if any(DENIED_CONFIG.fullmatch(name) for name in names):
                raise WorkspacePolicyError("Git includes, URL rewrites, filters and hooks, remote programs, "
                                           "partial-clone and protocol settings are refused for write scopes.")
    actual = _git(path, "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-dir",
                  "--git-common-dir").splitlines()
    if actual != [str(path), str(metadata), str(common)]:
        raise WorkspacePolicyError("Git reported a different checkout or worktree identity.")
    return common


def _linked_workspace(path, expected_repository, registered_path, require_clean):
    expected = _repo_id(expected_repository)
    if expected is None:
        raise WorkspacePolicyError("The expected repository must be registered before requesting writes.")
    _owned(path)
    common = _linked_git_identity(path)
    branch = _git(path, "symbolic-ref", "--quiet", "HEAD").removeprefix("refs/heads/").strip()
    if not BRANCH.fullmatch(branch) or any(part in {"", ".", ".."} for part in branch.split("/")):
        raise WorkspacePolicyError("Use an isolated codex/ or claude/ branch for the linked worktree.")
    # The origin is checked before any command that reads objects (rev-parse --verify, status).
    for args in [("remote", "get-url", "--all", "origin"), ("remote", "get-url", "--push", "--all", "origin")]:
        urls = _git(path, *args).splitlines()
        if len(urls) != 1 or not REMOTE.fullmatch(urls[0]) or _repo_id(urls[0]) != expected:
            raise WorkspacePolicyError("The worktree must have a single matching registered fetch and push origin.")
    default = _git(path, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", absent=True).strip()
    if not default.startswith("refs/remotes/origin/") or default == "refs/remotes/origin/HEAD":
        raise WorkspacePolicyError("The locally recorded origin default branch must be verified before writes.")
    _git(path, "rev-parse", "--verify", f"{default}^{{commit}}")
    if default == f"refs/remotes/origin/{branch}":
        raise WorkspacePolicyError("The repository default branch is not a write workspace.")
    worktrees = _git(path, "worktree", "list", "--porcelain", "-z").split("\0\0")
    participants = [row.split("\0") for row in worktrees if row]
    matches = [row for row in participants if f"branch refs/heads/{branch}" in row]
    if len(matches) != 1 or matches[0][0] != f"worktree {path}" or common.is_relative_to(path):
        raise WorkspacePolicyError("The branch is not exclusively checked out in this isolated worktree.")
    if require_clean and _git(path, "status", "--porcelain=v1", "--untracked-files=normal", "--ignore-submodules=all"):
        raise WorkspacePolicyError("Use a clean dedicated worktree before requesting write permission.")
    root = _registry_scope(path, registered_path)
    _owned(root, private=True)
    return WorkspaceScope(root, branch, path)


def validate_workspace(path, *, intent, expected_repository=None, registered_path=None, require_clean=True):
    """Inspect one proposed MASTER write scope without creating or changing files.

    A successful result binds the path in a trusted grant. Only the executing
    sandbox or host can enforce that grant against changes.
    """
    try:
        if type(require_clean) is not bool:
            raise WorkspacePolicyError("Workspace cleanliness verification must be a boolean.")
        requested = _plain_path(path)
        if intent == "build":
            return _new_workspace(requested)
        if intent in REPO_INTENTS:
            return _linked_workspace(requested, expected_repository, registered_path, require_clean)
        raise WorkspacePolicyError("This command does not have a workspace write scope.")
    except WorkspacePolicyError:
        raise
    except (OSError, UnicodeError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        raise WorkspacePolicyError("Workspace or Git identity could not be verified.") from error


# Git treats a directory as a repository when it holds HEAD and either objects/ and refs/ or a
# commondir file (setup.c is_git_directory); any of these next to HEAD is refused.
GIT_DIRECTORY_SIGNS = frozenset({"objects", "refs", "commondir"})


def _writable_tree(scope):
    """Do not mount aliases to other files or a second Git repository as writable."""
    root = scope.root
    identity = _owned(root, private=True)
    dirs = [root]
    inspected = 0

    def refuse(message, path):
        raise WorkspacePolicyError(f"{message} ({ascii(str(path.relative_to(root)))[1:-1] or '.'})")

    while dirs:
        directory = dirs.pop()
        names = set()
        with os.scandir(directory) as entries:
            for entry in entries:
                inspected += 1
                if inspected > 100_000:
                    raise WorkspacePolicyError("Workspace exceeds the bounded writable file inventory.")
                path = pathlib.Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                names.add(entry.name.casefold())
                if (scope.branch is not None and path == scope.checkout / ".git"
                        and stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
                    continue  # The strict governor overlays the linked metadata pointer read-only.
                if entry.name.casefold() == ".git" or info.st_uid != os.geteuid() or info.st_dev != identity.st_dev:
                    refuse("Nested Git metadata, foreign files and nested filesystems are refused.", path)
                if stat.S_ISDIR(info.st_mode):
                    dirs.append(path)
                elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    refuse("Writable workspaces cannot contain symlinks, hard links or special files.", path)
        if "head" in names and names & GIT_DIRECTORY_SIGNS:
            refuse("A directory shaped like a Git repository is refused in a writable workspace.", directory)
    return identity.st_dev, identity.st_ino


def _relaunch_scope(settings):
    """The full identity check of a workspace that already holds its agent's own work."""
    if settings["intent"] != "build":
        return validate_workspace(**{**settings, "require_clean": False})
    try:
        return _new_workspace(_plain_path(settings["path"]), initial=False)
    except WorkspacePolicyError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise WorkspacePolicyError("Workspace or Git identity could not be verified.") from error


def _peer_scope(settings):
    """Canonical private roots of an assignment that is not launched now: no Git and no content walk."""
    try:
        path = _plain_path(settings["path"])
        if settings["intent"] == "build":
            return WorkspaceScope(path, None, path), _owned(path, private=True)
        if settings["intent"] not in REPO_INTENTS:
            raise WorkspacePolicyError("This command does not have a workspace write scope.")
        _owned(path)
        marker = path / ".git"
        if marker.is_symlink() or not marker.is_file():
            raise WorkspacePolicyError("Use the exact root of a dedicated linked Git worktree.")
        root = _registry_scope(path, settings.get("registered_path"))
        return WorkspaceScope(root, None, path), _owned(root, private=True)
    except WorkspacePolicyError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise WorkspacePolicyError("Workspace or Git identity could not be verified.") from error


class WorkspaceSupervisor:
    """Give an authenticated local dispatcher one isolated write root per assigned agent.

    Construct with trusted bindings. The dispatcher, rather than a worker payload,
    supplies the caller's agent ID. Use a single active assignment registry per
    dispatcher. The checker neither authenticates host sessions nor coordinates
    assignments made by other processes.

    By default every assignment is validated as fresh (empty build directory, clean
    worktree). With `selected`, only that agent is validated in full and can run:
    fresh, or with relaunch=True as a workspace that already holds its own work. The
    other assignments are checked only for canonical, private and independent roots,
    so one agent's writes never lock out another.
    """

    def __init__(self, assignments, *, selected=None, relaunch=False):
        if not isinstance(assignments, Mapping) or not 1 <= len(assignments) <= 20:
            raise WorkspacePolicyError("Supply one to twenty explicit agent workspace assignments.")
        if type(relaunch) is not bool or (relaunch and selected is None):
            raise WorkspacePolicyError("A relaunch names exactly one selected agent.")
        if selected is not None and (not isinstance(selected, str) or selected not in assignments):
            raise WorkspacePolicyError("The agent has no assigned write workspace.")
        self._assignments = {}
        seen = []
        for agent, settings in assignments.items():
            if not isinstance(agent, str) or not AGENT_ID.fullmatch(agent):
                raise WorkspacePolicyError("An assigned agent needs a valid local ID.")
            if (not isinstance(settings, Mapping) or not {"path", "intent"} <= settings.keys()
                    or not settings.keys() <= ASSIGNMENT_KEYS):
                raise WorkspacePolicyError("Assignments require path and intent and can include the registered target.")
            settings = dict(settings)
            if selected is None or agent == selected:
                scope = _relaunch_scope(settings) if relaunch else validate_workspace(**settings)
                identity = _writable_tree(scope)
            else:
                scope, info = _peer_scope(settings)
                identity = info.st_dev, info.st_ino
            for other, other_identity in seen:
                if (identity == other_identity or scope.checkout == other.checkout or scope.root.is_relative_to(other.root)
                        or other.root.is_relative_to(scope.root)):
                    raise WorkspacePolicyError("An agent workspace must be independent of all other assignments.")
            seen.append((scope, identity))
            if selected is None or agent == selected:
                settings["path"] = scope.checkout
                self._assignments[agent] = (scope, identity, settings)

    def run(self, agent, cmd, *, timeout):
        from . import governor

        if not isinstance(agent, str) or agent not in self._assignments:
            raise WorkspacePolicyError("The agent has no assigned write workspace.")
        assignment, identity, settings = self._assignments[agent]
        candidate = _plain_path(assignment.checkout)
        if settings["intent"] == "build":
            current = _new_workspace(candidate, initial=False)
        else:
            current = validate_workspace(**{**settings, "require_clean": False})
        if current != assignment or _writable_tree(current) != identity:
            raise WorkspacePolicyError("The assigned workspace changed identity.")
        result = governor.sandbox_run(
            cmd, cwd=current.root, timeout=timeout, network=False, env_allow=(),
            allowed_paths=(current.root,), require_fs_isolation=True,
        )
        if result.get("fs_isolated") is not True or result.get("network_isolated") is not True:
            raise WorkspacePolicyError("The workspace launch did not establish the required isolation.")
        # Only an existing .git pointer is overlaid read-only: re-inspect what the child left, because
        # host-side Git there would run a planted core.fsmonitor, hook or filter outside the sandbox.
        try:
            after = _writable_tree(current)
        except (WorkspacePolicyError, OSError) as error:
            raise WorkspaceTaintedError(f"The run is failed: its workspace now holds content that is unsafe for "
                                        f"host-side Git; inspect it before running Git there. {error}", result) from error
        if after != identity:
            raise WorkspaceTaintedError("The run is failed: the assigned workspace changed identity.", result)
        return result
