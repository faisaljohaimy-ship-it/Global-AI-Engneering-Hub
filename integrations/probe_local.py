#!/usr/bin/env python3
"""Non-mutating local availability probe; emits no environment or credential data."""

import json
import shutil
import subprocess


def executable_version(command, flag="--version"):
    path = shutil.which(command)
    if not path:
        return {"result": "unavailable"}
    completed = subprocess.run(
        [path, flag], capture_output=True, text=True, timeout=10, check=False
    )
    first_line = (completed.stdout or completed.stderr).splitlines()
    return {
        "result": "success" if completed.returncode == 0 else "error",
        "version_output": first_line[0][:160] if first_line else "",
    }


def node_package(package):
    node = shutil.which("node")
    if not node:
        return {"result": "unavailable"}
    completed = subprocess.run(
        [node, "-e", "require.resolve(process.argv[1])", package],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return {"result": "success" if completed.returncode == 0 else "unavailable"}


def main():
    result = {
        "Blender": executable_version("blender"),
        "FFmpeg": executable_version("ffmpeg", "-version"),
        "Remotion": node_package("remotion"),
        "Three.js": node_package("three"),
        "Motion": node_package("motion"),
        "GSAP": node_package("gsap"),
        "Rive": node_package("@rive-app/canvas"),
        "Lottie": node_package("lottie-web"),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
