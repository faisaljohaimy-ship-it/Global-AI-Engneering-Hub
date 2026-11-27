# Motion Lab phase 2 specification

## Goal

Turn a bounded first batch of the 142 indexed motion specifications into reusable,
dependency-free components and expose all catalog entries in a safe interactive lab.

## Acceptance scenarios

1. The lab lists exactly 142 catalog entries and clearly distinguishes indexed,
   implemented, automated-tested, browser-runtime-verified, and used states.
2. At least 10 entries run locally across CSS, WAAPI, WebGL/GLSL, and deterministic
   adapters for Remotion and Three.js without installing unreviewed packages.
3. Motion starts only after user input, supports replay/stop, RTL/LTR, and a
   reduced-motion mode. No external asset or network request is required.
4. Claude Code and Codex can query the same pinned registry with `hub.py recommend`.
5. A central pin update is dry-run by default, compare-and-swap guarded, and changes
   only `.engineering/capabilities.json` after an explicit `--apply`.
6. All 22 program integrations receive a harmless availability probe; evidence must
   not contain account identifiers, credentials, balances, or customer data.
7. Unit, security, manifest, browser-smoke, and static performance-budget checks pass
   before the branch is merged.

## Boundaries

- No production deployments, paid generation, subscription changes, or GPU jobs.
- Remotion and Three.js remain optional adapters until their packages, licenses, and
  pinned versions are separately approved and installed.
- Private/branded cinematic assets are not copied into this public repository.
- “Runtime verified” means an observed target-runtime check, not merely a source file
  or unit test. “Used” identifies a named consumer; it does not mean production use.
