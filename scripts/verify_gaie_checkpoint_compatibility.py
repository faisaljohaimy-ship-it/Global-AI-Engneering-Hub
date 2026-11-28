"""Exercise Scenario O across the hub and the installed Claude Code memory CLI.

All fixture state is private and outside Git. Use --temp-dir if the host's
default temporary location has a .git marker in an ancestor directory.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory, gettempdir


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "checkpoint-compatibility-fixture"
TASK = "checkpoint-handoff"
TITLE = "Check a synthetic release handoff"
HUB_MEMORY = ROOT / "engineering_os/gaie_memory.py"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def invoke(script, args, cwd, lab, state, expected=0):
    env = {
        "HOME": str(lab / "home"),
        "GAIE_HOME": str(state),
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    run = subprocess.run([sys.executable, "-B", str(script), *args], cwd=cwd,
                         env=env, capture_output=True, encoding="utf-8", timeout=30)
    if run.returncode != expected:
        raise ValueError(f"{script.name} returned {run.returncode}: {run.stdout or run.stderr}")
    return json.loads(run.stdout)


def memory(script, cwd, lab, state, engine, *args, project=PROJECT, expected=0):
    return invoke(script, ["--project", project, "--engine", engine, *args], cwd, lab, state, expected)


def verify(lab):
    (lab / "home").mkdir(mode=0o700)
    project = lab / "independent-project"
    project.mkdir(mode=0o700)
    first, second, third = (lab / f"state-{index}" for index in range(3))
    bootstrap = ROOT / "scripts/gaie_bootstrap.py"
    install_args = ["--scope", "project", "--target", str(project)]
    installed = invoke(bootstrap, ["install", *install_args, "--apply"], project, lab, second)
    require(installed["ok"], "Claude Code project install failed")
    verified = invoke(bootstrap, ["verify", *install_args], project, lab, second)
    require(verified["ok"] and verified["files"] and all(value == "current" for value in verified["files"].values()),
            "Claude Code project install is incomplete or has drifted")
    portable = project / ".claude/skills/gaie-master-router/engine/gaie_memory.py"
    require(portable.read_bytes() == HUB_MEMORY.read_bytes(), "installed memory CLI differs from its source")

    task = memory(HUB_MEMORY, project, lab, first, "codex", "task", "--id", TASK, "--title", TITLE,
                  "--done", "record the plan", "--remaining", "review the fixture", "--remaining", "record the review")
    require(task["version"] == 1, "first task revision was not recorded")
    outbound = lab / "outbound.json"
    sealed = memory(HUB_MEMORY, project, lab, first, "codex", "checkpoint", "--to", str(outbound))
    digest = sealed["checkpoint_sha256"]
    require(digest == hashlib.sha256(outbound.read_bytes()).hexdigest(), "outbound checkpoint digest mismatch")

    restore = ["restore", "--from", str(outbound), "--sha256"]
    wrong_digest = "f" * 64 if digest == "0" * 64 else "0" * 64
    wrong = memory(portable, project, lab, second, "claude-code", *restore, wrong_digest, expected=1)
    foreign = memory(portable, project, lab, second, "claude-code", *restore, digest,
                     project="different-fixture", expected=1)
    require(wrong == {"status": "error", "error": "Checkpoint differs from the expected SHA-256"},
            "restore did not report the incorrect checkpoint digest")
    require(foreign == {"status": "error", "error": "This memory belongs to another project"},
            "restore did not report the different project")
    restored = memory(portable, project, lab, second, "claude-code", *restore, digest)
    require(restored == sealed, "installed CLI did not recover the outbound checkpoint")
    next_task, = memory(portable, project, lab, second, "claude-code", "next", "--task", TASK)
    require(next_task["version"] == 1 and next_task["next"] == "review the fixture",
            "installed CLI could not resume the pending step")

    continued = memory(portable, project, lab, second, "claude-code", "task", "--id", TASK, "--title", TITLE,
                       "--done", "record the plan", "--done", "review the fixture", "--remaining", "record the review")
    require(continued["version"] == 2, "installed CLI did not persist its continuation")
    returned = lab / "returned.json"
    resealed = memory(portable, project, lab, second, "claude-code", "checkpoint", "--to", str(returned))
    return_digest = resealed["checkpoint_sha256"]
    require(return_digest != digest and return_digest == hashlib.sha256(returned.read_bytes()).hexdigest(),
            "return checkpoint did not seal the new revision")
    recovered = memory(HUB_MEMORY, project, lab, third, "codex", "restore", "--from", str(returned),
                       "--sha256", return_digest)
    require(recovered == resealed, "hub CLI did not recover the return checkpoint")
    final_task, = memory(HUB_MEMORY, project, lab, third, "codex", "next", "--task", TASK)
    require(final_task["version"] == 2 and final_task["done"] == ["record the plan", "review the fixture"]
            and final_task["remaining"] == ["record the review"], "restored task progress disagrees with the handoff")
    records = json.loads(returned.read_bytes())["state"]["records"].values()
    engines = {item["engine"] for row in records for item in row["provenances"]}
    require(engines == {"claude-code", "codex"}, "checkpoint did not preserve both provenance labels")

    return {
        "scenario": "O",
        "status": "passed",
        "scope": "hub memory CLI and installed Claude Code memory CLI in fresh Python processes",
        "synthetic": True,
        "model_calls": 0,
        "checkpoint_handoffs": 2,
        "wrong_digest_refused": True,
        "different_project_refused": True,
        "task_version": final_task["version"],
        "next_step": final_task["next"],
        "provenance_labels": sorted(engines),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp-dir", type=Path, default=Path(gettempdir()),
                        help="scratch root outside Git (default: the system temporary directory)")
    args = parser.parse_args()
    try:
        scratch = args.temp_dir.resolve(strict=True)
        require(not any((path / ".git").exists() for path in (scratch, *scratch.parents)),
                "scratch directory has a .git ancestor; choose a Git-free directory with --temp-dir")
        with TemporaryDirectory(prefix="gaie-checkpoint-", dir=scratch) as directory:
            result = verify(Path(directory))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"scenario": "O", "status": "failed", "error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
