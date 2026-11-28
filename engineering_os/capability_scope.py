"""Fixed local operation policy shared by MCP and engineering workflows.

The discovery catalogue confers no execution rights. These descriptors name
only implemented offline operations. A host must bind any private directories
at launch. RPC input cannot pick a root, run a shell command or select a provider.
SPDX-License-Identifier: MIT
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from scripts.security_scan import secret_findings

from .orchestration import SECRET, SLUG, _safe_directory, _slug, _text, canonical


@dataclass(frozen=True)
class Descriptor:
    engine: str
    description: str
    needs: tuple[str, ...] = ()
    project_at: tuple[str, ...] | None = ()
    writes: bool = False


# `project_at=None` is reserved for pure hub-wide inspection or caller-supplied
# graph analysis. All other operations require an exact bound project label.
DESCRIPTORS = MappingProxyType({
    "architecture": Descriptor("control", "Inspect the twenty architecture layer contracts.", project_at=None),
    "reasoning-plan": Descriptor("reasoning", "Build a bounded engineering plan from constraints and evidence."),
    "reasoning-review": Descriptor("reasoning", "Check a plan against supplied review and verification receipts.",
                                  project_at=("plan", "request")),
    "root-causes": Descriptor("reasoning", "Trace observed failures on a declared dependency graph.", project_at=None),
    "memory-search": Descriptor("memory", "Find knowledge in the configured private project memory.", ("memory_dir",)),
    "memory-graph": Descriptor("memory", "Inspect links in the configured private project memory.", ("memory_dir",)),
    "memory-put": Descriptor("memory", "Record curated knowledge in the configured private project memory.",
                             ("memory_dir",), writes=True),
    "memory-index": Descriptor("memory", "Index Python symbols in the configured project source tree.",
                               ("memory_dir", "artifact_root"), writes=True),
    "memory-checkpoint": Descriptor("memory", "Save a project memory checkpoint using a new ID.",
                                    ("memory_dir", "checkpoint_dir"), writes=True),
    "memory-restore": Descriptor("memory", "Restore a project checkpoint by ID into an empty memory store.",
                                 ("memory_dir", "checkpoint_dir"), writes=True),
    "memory-verify": Descriptor("memory", "Bind a solution to an existing test receipt ID and current sources.",
                                ("memory_dir", "artifact_root", "receipt_dir"), writes=True),
    "factory-plan": Descriptor("factory", "Plan stage gates for structured engineering requirements."),
    "factory-evaluate": Descriptor("factory", "Verify stage evidence in the configured project root.",
                                   ("artifact_root",), project_at=("plan", "request")),
    "factory-generate": Descriptor("factory", "Generate and verify a SQLite service at the configured new destination.",
                                   ("destination",), writes=True),
    "healing-analyze": Descriptor("healing", "Diagnose regressions from source-bound observations."),
    "healing-verify": Descriptor("healing", "Check a candidate and rollback using disposable artifacts."),
    "healing-repair": Descriptor("healing", "Test and repair bounded SQLite settings in disposable storage."),
    "healing-replay": Descriptor("healing", "Replay a SQLite repair report against the supplied settings.",
                                 project_at=("request",)),
    "economics": Descriptor("economics", "Summarize engineering usage and cost evidence for this project."),
    "economics-measure": Descriptor("economics", "Measure fixed offline engineering operations.", project_at=("request",)),
    "cinematic": Descriptor("cinematic", "Inspect original-motion implementation and current browser evidence.",
                            project_at=None),
})

_CHECKPOINT_TOOLS = frozenset({"memory-checkpoint", "memory-restore"})
_PRIVATE_ID = {"type": "string", "pattern": f"^{SLUG.pattern}$"}


def wire_name(operation):
    return "gaie_" + operation.replace("-", "_")


def _absolute_path(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Configured paths must be absolute and canonical")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Symlink directory refused")
    return path


def _relative_path(value, suffix):
    _text(value, 256)
    path = PurePosixPath(value)
    if ("\\" in value or path.is_absolute() or path.as_posix() != value or path.suffix != suffix
            or any(part.startswith(".") for part in path.parts)):
        raise ValueError("Artifact path rejected")
    return path


def _check_secrets(value):
    encoded = canonical(value).decode("utf-8")
    if SECRET.search(encoded) or secret_findings("mcp.json", encoded):
        raise ValueError("Credential-shaped tool data refused")


class CapabilityScope:
    """An immutable-by-convention startup binding for one local project."""

    def __init__(self, project, *, memory_dir=None, artifact_root=None, destination=None,
                 checkpoint_dir=None, receipt_dir=None):
        from .intelligence import OPERATIONS

        self.project = _slug(project)
        self.memory_dir = _safe_directory(_absolute_path(memory_dir)) if memory_dir is not None else None
        self.artifact_root = _absolute_path(artifact_root) if artifact_root is not None else None
        if self.artifact_root is not None and not self.artifact_root.is_dir():
            raise ValueError("Artifact root must be an existing directory")
        self.destination = _absolute_path(destination) if destination is not None else None
        if self.destination is not None:
            if self.destination.exists() or not self.destination.parent.is_dir():
                raise ValueError("Factory destination must be new with a private existing parent")
            _safe_directory(self.destination.parent)
        self.checkpoint_dir = _safe_directory(_absolute_path(checkpoint_dir)) if checkpoint_dir is not None else None
        self.receipt_dir = _safe_directory(_absolute_path(receipt_dir)) if receipt_dir is not None else None
        private = [path for path in (self.memory_dir, self.checkpoint_dir, self.receipt_dir) if path is not None]
        if len(private) != len(set(private)):
            raise ValueError("Memory, checkpoint and receipt directories must be distinct")
        self.tools = MappingProxyType({wire_name(operation): operation for operation, info in DESCRIPTORS.items()
                                       if operation in OPERATIONS and self._enabled(info)})

    def _enabled(self, info):
        return all(getattr(self, requirement) is not None for requirement in info.needs)

    def catalog(self):
        """Describe implemented bindings without revealing startup paths or host claims."""
        return [{"operation": operation, "tool": wire_name(operation), "engine": info.engine,
                 "enabled": wire_name(operation) in self.tools, "startup_scopes": list(info.needs),
                 "read_only": not info.writes}
                for operation, info in DESCRIPTORS.items()]

    @staticmethod
    def external_catalog():
        """Report approved registry evidence without deriving any dispatch rights."""
        from .control import STATES, capabilities

        allowed = STATES[STATES.index("APPROVED"):]
        return [{"id": row["id"], "state": row["state"], "revision": row["revision"],
                 "recorded_evidence_scope": row.get("evidence_scope"),
                 "catalog_claims_operational": row["operational"]}
                for row in capabilities()
                if row["kind"] == "external-tool" and row["state"] in allowed
                and all(review == "approved" for review in row["review"].values())]

    def list_tools(self):
        tools = []
        for name, operation in self.tools.items():
            info = DESCRIPTORS[operation]
            request_schema = {"type": "object"}
            description = info.description + " Input uses the GAIE CLI request schema."
            if operation in _CHECKPOINT_TOOLS or operation == "memory-verify":
                properties = {"project": {"type": "string", "const": self.project}, "id": dict(_PRIVATE_ID)}
                if operation == "memory-verify":
                    digest = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
                    properties.update(id=dict(digest), receipt_id=dict(_PRIVATE_ID), receipt_sha256=dict(digest))
                request_schema.update(properties=properties, required=list(properties), additionalProperties=False)
                description = info.description + " File IDs resolve under the directories bound at startup."
            tools.append({"name": name, "description": description,
                          "inputSchema": {"type": "object", "properties": {"request": request_schema},
                                          "required": ["request"], "additionalProperties": False},
                          "annotations": {"readOnlyHint": not info.writes, "destructiveHint": False,
                                          "openWorldHint": False}})
        return tools

    def prepare(self, operation, request):
        """Validate the MCP envelope and return a local request plus dispatch roots."""
        if self.tools.get(wire_name(operation)) != operation:
            raise ValueError("Operation unavailable in this startup scope")
        if not isinstance(request, dict):
            raise ValueError("Expected a request object")
        if "project" in request and request["project"] != self.project:
            raise ValueError("Call targets another project")
        project_at = DESCRIPTORS[operation].project_at
        if project_at is not None:
            subject = request
            for key in project_at:
                subject = subject[key]
            if not isinstance(subject, dict) or subject.get("project") != self.project:
                raise ValueError("Call targets another project")
        _check_secrets(request)

        if operation == "memory-index":
            _relative_path(request["path"], ".py")
            request = {**request, "engine": "claude-code"}
        elif operation == "memory-put":
            provenance = request["provenance"]
            if not isinstance(provenance, dict) or provenance.get("engine") != "claude-code":
                raise ValueError("Memory writes require Claude Code provenance")
        elif operation in _CHECKPOINT_TOOLS:
            if set(request) != {"project", "id"}:
                raise ValueError("A project and checkpoint ID are required")
            key = "destination" if operation == "memory-checkpoint" else "checkpoint"
            request = {"project": self.project, key: str(self.checkpoint_dir / f"{_slug(request['id'])}.json")}
        elif operation == "memory-verify":
            if set(request) != {"project", "id", "receipt_id", "receipt_sha256"}:
                raise ValueError("A project solution, receipt ID and receipt digest are required")
            request = {"project": self.project, "id": request["id"], "receipt_sha256": request["receipt_sha256"],
                       "receipt_path": str(self.receipt_dir / f"{_slug(request['receipt_id'])}.json")}
        elif operation == "factory-evaluate":
            for receipt in request["receipts"]:
                _relative_path(receipt["artifact"]["path"], ".json")
                for check in receipt["checks"]:
                    _relative_path(check["evidence"]["path"], ".json")

        artifact_root = self.destination if operation == "factory-generate" else self.artifact_root
        return request, {"state_dir": self.memory_dir, "artifact_root": artifact_root}

    def invoke(self, operation, request):
        """Run a scoped operation through the existing local engine dispatcher."""
        from .intelligence import dispatch

        structured, roots = self.prepare(operation, request)
        value = dispatch(operation, structured, **roots)
        _check_secrets(value)
        return value
