"""GAIE project inventory: read-only discovery and an upgrade coverage matrix.

Walks a project checkout within fixed bounds, classifies files by engineering
surface, reads dependency manifests and reports observable signals. It never
executes project code, follows symlinks, prints file contents or writes into
the project. Counts describe files found, not quality: every matrix row starts
with its evidence pending. Standard library only. SPDX-License-Identifier: MIT.
"""
import argparse
import json
import os
import pathlib
import re
import stat
import sys

MAX_FILES, MAX_MANIFEST = 50000, 2 * 1024 * 1024
SKIP = {".git", "node_modules", ".next", "dist", "build", "out", ".venv", "venv", "__pycache__", ".turbo",
        ".cache", "coverage", ".vercel", "target", "vendor", ".idea", ".pytest_cache"}
EXT = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg", ".ico"},
    "video": {".mp4", ".webm", ".mov", ".m4v", ".mkv"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"},
    "model3d": {".glb", ".gltf", ".obj", ".fbx", ".usdz", ".blend"},
    "code": {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go", ".rs", ".java", ".kt", ".swift", ".dart",
             ".vue", ".svelte", ".php", ".rb", ".cs"},
    "style": {".css", ".scss", ".sass", ".less"},
}
TEST = re.compile(r"(^|/)(tests?|__tests__|e2e|spec|cypress|playwright)(/|$)|\.(test|spec)\.[a-z]+$|(^|/)test_[^/]+\.py$")
SURFACES = [
    ("pages-routes", re.compile(r"(^|/)(pages|routes|app|views|screens)/"), "frontend",
     "Every route renders, is reachable and has no console error", "end-to-end journey test"),
    ("components", re.compile(r"(^|/)(components|ui|widgets)/"), "frontend",
     "Components are consistent, accessible and responsive", "component and visual regression tests"),
    ("api", re.compile(r"(^|/)(api|server|functions|edge-functions|handlers|controllers|services)/"), "backend",
     "Each endpoint validates input, enforces authorization and returns stable contracts", "integration and authorization tests"),
    ("database", re.compile(r"(^|/)(migrations|supabase|prisma|drizzle|db|database|schema)/|\.sql$"), "database",
     "Schema, policies and indexes are verified; migrations are reversible", "migration and access-policy tests"),
    ("ai-agents", re.compile(r"(^|/)(agents?|ai|llm|prompts|rag|tools)/"), "ai-intelligence",
     "Agent outputs are evaluated; tool calls are bounded and approved", "AI evaluation suite"),
    ("motion", re.compile(r"(^|/)(motion|animations?|transitions|remotion|lottie|rive|shaders?|three|scenes?)/"), "motion",
     "Motion honours reduced-motion and stays within the frame budget", "browser motion and performance test"),
    ("i18n", re.compile(r"(^|/)(locales?|i18n|translations?|lang)/"), "frontend",
     "Arabic and English are complete; RTL and LTR layouts are correct", "bilingual layout test"),
    ("integrations", re.compile(r"(^|/)(integrations?|webhooks?|connectors?|adapters?)/"), "integration",
     "Each integration has a working call path or is labelled inactive", "integration contract test"),
    ("deployment", re.compile(r"(^|/)(\.github/workflows|\.gitlab|docker|k8s|infra|terraform)/|(^|/)(Dockerfile|vercel\.json|netlify\.toml|fly\.toml|render\.yaml)$"),
     "devops", "CI is mandatory, preview is verified and rollback is documented", "pipeline run and smoke test"),
]
MEDIA = [("images", "image", "design", "Images are optimized, sized and have alternative text", "asset budget check"),
         ("videos", "video", "cinematic", "Videos play on mobile and desktop with captions and efficient encoding", "playback and encoding check"),
         ("audio", "audio", "voice-audio", "Audio is licensed, normalized and synchronized", "audio review"),
         ("3d-assets", "model3d", "motion", "3D assets load within budget with a static fallback", "render and fallback test")]
STACK = {"next": "Next.js", "react": "React", "vue": "Vue", "svelte": "Svelte", "vite": "Vite", "express": "Express",
         "@supabase/supabase-js": "Supabase", "prisma": "Prisma", "drizzle-orm": "Drizzle", "three": "Three.js",
         "@react-three/fiber": "React Three Fiber", "remotion": "Remotion", "gsap": "GSAP", "motion": "Motion",
         "framer-motion": "Framer Motion", "lottie-web": "Lottie", "@rive-app/canvas": "Rive", "tailwindcss": "Tailwind CSS",
         "@playwright/test": "Playwright", "vitest": "Vitest", "jest": "Jest", "typescript": "TypeScript",
         "@anthropic-ai/sdk": "Anthropic SDK", "openai": "OpenAI SDK", "ai": "Vercel AI SDK", "react-native": "React Native",
         "expo": "Expo", "fastapi": "FastAPI", "django": "Django", "flask": "Flask", "pydantic-ai": "Pydantic AI"}
LOCKS = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock", "poetry.lock", "uv.lock", "Cargo.lock", "go.sum")
ENV = re.compile(r"^\.env(\..+)?$")


class InventoryError(ValueError):
    pass


def _read(directory_fd, name):
    """Bounded text of a regular, non-symlink file; empty on any problem."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return ""
            data = stream.read(MAX_MANIFEST + 1)
            return data.decode("utf-8", "replace") if len(data) <= MAX_MANIFEST else ""
    except OSError:
        return ""


def _manifest(directory_fd, name):
    try:
        data = json.loads(_read(directory_fd, name))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def inventory(target, large_bytes=5 * 1024 * 1024):
    root = pathlib.Path(target).resolve()
    if not root.is_dir():
        raise InventoryError("existing project directory required")
    if not hasattr(os, "fwalk") or not hasattr(os, "O_NOFOLLOW"):
        raise InventoryError("safe descriptor-based inventory is unavailable")
    counts = {name: 0 for name, *_ in SURFACES}
    kinds = {name: 0 for name in EXT}
    kinds.update(test=0, other=0)
    bytes_by = {"image": 0, "video": 0, "audio": 0, "model3d": 0}
    large, manifests, locks, env_files, total, truncated = [], [], [], [], 0, False
    dependencies, scripts = set(), set()
    has_ci = has_agent_instructions = hub_linked = False
    for directory, names, files, directory_fd in os.fwalk(root, follow_symlinks=False):
        names[:] = sorted(name for name in names if name not in SKIP)
        if pathlib.Path(directory).relative_to(root).as_posix() in {".github/workflows", ".gitlab", ".circleci"}:
            has_ci = True
        for name in sorted(files):
            path = pathlib.Path(directory) / name
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                continue
            total += 1
            if total > MAX_FILES:
                truncated = True
                break
            relative = path.relative_to(root).as_posix().encode("utf-8", "replace").decode("utf-8")
            suffix = path.suffix.casefold()
            kind = next((key for key, values in EXT.items() if suffix in values), "other")
            if TEST.search(relative):
                kinds["test"] += 1
            else:
                kinds[kind] += 1
                for surface, pattern, *_ in SURFACES:
                    if pattern.search(relative) and (kind in ("code", "style", "other") or surface in ("database", "deployment")):
                        counts[surface] += 1
            if kind in bytes_by:
                size = info.st_size
                bytes_by[kind] += size
                if size >= large_bytes:
                    large.append({"path": relative, "bytes": size, "kind": kind})
            if name in ("package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod", "pubspec.yaml"):
                manifests.append(relative)
            if name == "package.json":
                data = _manifest(directory_fd, name)
                for key in ("dependencies", "devDependencies", "peerDependencies"):
                    if isinstance(data.get(key), dict):
                        dependencies.update(data[key])
                if isinstance(data.get("scripts"), dict):
                    scripts.update(data["scripts"])
            elif name == "requirements.txt":
                dependencies.update(package.casefold() for package in re.findall(
                    r"^[ \t]*([A-Za-z0-9][A-Za-z0-9._-]*)[ \t]*(?:[=<>~!\[;]|$)",
                    _read(directory_fd, name), re.M))
            if name in LOCKS:
                locks.append(relative)
            if ENV.fullmatch(name) and not name.endswith((".example", ".sample", ".template")):
                env_files.append(relative)
            has_ci |= relative == ".gitlab-ci.yml"
            has_agent_instructions |= relative in {"CLAUDE.md", "AGENTS.md"}
            hub_linked |= relative == ".engineering/capabilities.json"
        if truncated:
            break
    signals = {
        "has_tests": kinds["test"] > 0, "has_ci": has_ci, "has_lockfile": bool(locks),
        "has_agent_instructions": has_agent_instructions, "hub_linked": hub_linked,
        "env_files_present": sorted(env_files), "scripts": sorted(scripts & {"build", "test", "lint", "typecheck", "e2e", "dev"}),
    }
    findings = []
    if env_files:
        findings.append({"severity": "high", "finding": "Environment files exist in the checkout; confirm they are untracked and hold no secrets.", "paths": sorted(env_files)[:10]})
    if not signals["has_tests"]:
        findings.append({"severity": "high", "finding": "No test files found; acceptance cannot be verified automatically."})
    if manifests and not locks:
        findings.append({"severity": "medium", "finding": "Dependency manifest without a lockfile; builds are not reproducible."})
    if not signals["has_ci"]:
        findings.append({"severity": "medium", "finding": "No CI or deployment configuration found."})
    if large:
        findings.append({"severity": "medium", "finding": f"{len(large)} media file(s) at or above {large_bytes} bytes; review encoding and lazy loading."})
    matrix = []

    def row(component, found, owner, acceptance, test):
        matrix.append({"component": component, "current_state": f"{found} item(s) discovered; quality not yet assessed",
                       "problem": "pending audit", "required_upgrade": "pending audit", "owner": owner,
                       "acceptance_criterion": acceptance, "test": test, "evidence": None, "status": "discovered"})
    for name, _, owner, acceptance, test in SURFACES:
        if counts[name]:
            row(name, counts[name], owner, acceptance, test)
    for name, kind, owner, acceptance, test in MEDIA:
        if kinds[kind]:
            row(name, kinds[kind], owner, acceptance, test)
    if dependencies:
        row("dependencies", len(dependencies), "security", "Dependencies are pinned, licensed and free of known critical advisories", "dependency audit")
    row("tests", kinds["test"], "quality-assurance", "Core journeys, permissions and regressions are covered by passing tests", "full suite run")
    return {
        "schema_version": 1, "files_scanned": min(total, MAX_FILES), "truncated": truncated,
        "file_kinds": kinds, "surfaces": counts, "media_bytes": bytes_by,
        "large_media": sorted(large, key=lambda item: -item["bytes"])[:25],
        "manifests": sorted(manifests), "lockfiles": sorted(locks),
        "stack": sorted({label for key, label in STACK.items() if key in dependencies}),
        "dependency_count": len(dependencies), "signals": signals, "findings": findings, "coverage_matrix": matrix,
        "boundary": "Static, path-based discovery. No code executed; counts are not quality, security or runtime evidence.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target")
    parser.add_argument("--matrix-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = inventory(args.target)
    except (InventoryError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 1
    print(json.dumps(result["coverage_matrix"] if args.matrix_only else result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
