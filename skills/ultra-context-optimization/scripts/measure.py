#!/usr/bin/env python3
"""Measure the hr view on a folder of sample outputs and write the evidence as JSON.

    python3 measure.py SAMPLES_DIR EVIDENCE.json

For each sample it records the size of the original and of the view in characters and in
tokens of the legacy Claude tokenizer bundled with litellm (a real tokenizer, used as a
proxy: the current models count differently, and no official counter is called here), the
time taken, whether every error line of the original is still there word for word, and
whether the stored original comes back byte for byte.

It also checks that one session cannot read another's store, that a view is not
compressed twice, that short output is left alone, and that a missing or broken Headroom
falls back to the plain view. Exit status is 1 if any check fails.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The command that produced each sample, as `hr run` would have seen it.
COMMANDS = {
    "test-log-pass.log": "python3 -m unittest discover -s tests -v",
    "test-log-fail.log": "python3 -m unittest -v test_sample",
    "search-results.txt": "rg -n 'duration|quality' packages/motion-engines --glob '*.mjs'",
    "git-log-stat.txt": "git log --stat -30",
    "terminal-listing.txt": "ls -laR packages/motion-engines",
    "dependency-list.json": "pip list --format=json",
}


def load_hr(store: str, **env: str):
    os.environ["HR_STORE"] = store
    for key, value in env.items():
        os.environ[key] = value
    spec = importlib.util.spec_from_file_location("hr", HERE / "hr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    samples, evidence_path = Path(sys.argv[1]), Path(sys.argv[2])
    store = tempfile.mkdtemp(prefix="hr-measure-")
    hr = load_hr(store, HR_SESSION="measure-a")
    rows, failures = [], []
    texts, views = [], []
    for sample in sorted(samples.iterdir()):
        text = sample.read_bytes().decode("utf-8", "replace")
        started = time.perf_counter()
        shown, facts = hr.view(text, "Report the result and every failure.", COMMANDS.get(sample.name, f"cat {sample.name}"))
        wall = round(time.perf_counter() - started, 3)
        body = shown
        flat = hr.squash(body)
        lost = [line for _, line in hr.must_keep(text) if hr.squash(line) not in flat]
        intact = None
        if facts.get("ref"):
            back, meta = hr.load(facts["ref"])
            intact = back == text and hashlib.sha256(text.encode("utf-8", "replace")).hexdigest() == meta["sha256"]
            if not intact:
                failures.append(f"{sample.name}: the stored original differs")
        if lost and facts.get("appended", 0) < hr.KEEP_CAP:
            failures.append(f"{sample.name}: {len(lost)} error lines lost")
        rows.append({"sample": sample.name, "chars": len(text), "view_chars": len(body),
                     "error_lines": len(hr.must_keep(text)), "error_lines_missing": len(lost),
                     "error_lines_appended": facts.get("appended", 0), "original_intact": intact,
                     "kind": facts.get("kind"), "via": facts.get("via"), "lossless": facts.get("lossless"), "stored": facts.get("stored"), "wall_seconds": wall, "headroom_seconds": facts.get("seconds")})
        texts.append(text)
        views.append(body)
    counts = hr.count_tokens(texts + views)
    for index, row in enumerate(rows):
        if counts:
            row["tokens"] = counts[index]
            row["view_tokens"] = counts[len(rows) + index]
            row["tokens_saved_percent"] = round(100 * (1 - row["view_tokens"] / max(row["tokens"], 1)), 1)
        row["chars_saved_percent"] = round(100 * (1 - row["view_chars"] / max(row["chars"], 1)), 1)

    checks = {}
    first = next((r for r in rows if r["original_intact"]), None)
    # One session cannot read another session's store.
    ref = hr.journal("measure-a")[0]["ref"]
    other = subprocess.run([sys.executable, str(HERE / "hr.py"), "get", ref, "--head", "1"], capture_output=True, text=True,
                           env={**os.environ, "HR_SESSION": "measure-b"})
    checks["session_isolation"] = other.returncode != 0 and "no stored output" in (other.stderr + other.stdout)
    # A view is never compressed again.
    again, facts = hr.view(views[0] if views[0].startswith(hr.MARK) else hr.MARK + "x]\n" + "y\n" * 2000, "", "")
    checks["no_double_compression"] = facts["via"] == "already a view"
    # Short output is left alone and not stored.
    short, facts = hr.view("ok\n", "", "true")
    checks["short_output_untouched"] = short == "ok\n" and facts["via"] == "as it is"
    # A missing Headroom falls back to the plain view and keeps the errors.
    log = "\n".join(f"step {n} ok" for n in range(900)) + "\nValueError: bad frame 7 at render.py:91\n" + "\n".join(f"step {n} ok" for n in range(900))
    saved_home = hr.TOOL_HOME
    hr.TOOL_HOME = Path(store) / "missing"
    plain, facts = hr.view(log, "", "build")
    hr.TOOL_HOME = saved_home
    checks["fallback_when_missing"] = "plain head and tail" in facts["via"] and "ValueError: bad frame 7 at render.py:91" in plain and len(plain) < len(log)
    # A worker that cannot finish in time falls back the same way.
    os.environ["HR_TIMEOUT"] = "0"
    slow, facts = hr.view(log + "\n", "", "build")
    del os.environ["HR_TIMEOUT"]
    checks["fallback_on_timeout"] = "timed out" in facts["via"] and "ValueError: bad frame 7 at render.py:91" in slow
    # The exit status of the wrapped command is passed on, and the view names it.
    done = subprocess.run([sys.executable, str(HERE / "hr.py"), "run", "--", "bash", "-c", "seq 1 4000; echo 'fatal: boom' >&2; exit 3"],
                          capture_output=True, text=True, env={**os.environ, "HR_SESSION": "measure-a"})
    checks["exit_status_passed_on"] = done.returncode == 3 and "rc=3" in done.stdout and "fatal: boom" in done.stdout
    # Selective retrieval returns exactly the asked lines.
    ref = done.stdout.split(hr.MARK, 1)[1].split()[0]
    got = subprocess.run([sys.executable, str(HERE / "hr.py"), "get", ref, "--lines", "1999:2001"], capture_output=True, text=True,
                         env={**os.environ, "HR_SESSION": "measure-a"})
    checks["selective_retrieval"] = got.stdout.split() == ["1999:1999", "2000:2000", "2001:2001"]
    verified = subprocess.run([sys.executable, str(HERE / "hr.py"), "verify", ref], capture_output=True, text=True,
                              env={**os.environ, "HR_SESSION": "measure-a"})
    checks["checksum_verifies"] = verified.returncode == 0 and "intact" in verified.stdout
    failures.extend(f"check failed: {name}" for name, passed in checks.items() if not passed)

    total = {"chars": sum(r["chars"] for r in rows), "view_chars": sum(r["view_chars"] for r in rows)}
    if counts:
        total.update(tokens=sum(r["tokens"] for r in rows), view_tokens=sum(r["view_tokens"] for r in rows))
        total["tokens_saved_percent"] = round(100 * (1 - total["view_tokens"] / total["tokens"]), 1)
    total["chars_saved_percent"] = round(100 * (1 - total["view_chars"] / total["chars"]), 1)
    evidence = {"measured": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "token_counter": "legacy Claude tokenizer bundled with litellm; a proxy, not the current models' count" if counts else None,
                "worker": " ".join(hr.worker_command() or ["none"]).replace(str(hr.TOOL_HOME), "TOOLS/headroom").replace(str(HERE), "scripts").replace(str(hr.hub_tool().parent), "HUB/tools"),
                "sdk_version": hr.hub_module().VERSION, "boundary": hr.BOUNDARY, "store": "the hub tool's (tools/headroom_context.py)",
                "samples": rows, "total": total, "checks": checks, "failures": failures}
    evidence_path.write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8")
    for row in rows:
        print(f"{row['sample'][:30]:30} {row['chars']:>7}ch -> {row['view_chars']:>6}ch  tok {row.get('tokens', 0):>6} -> {row.get('view_tokens', 0):>5} "
              f"({row.get('tokens_saved_percent', 0):>5}%)  err {row['error_lines']:>3}/{row['error_lines_missing']} lost  {row['wall_seconds']:>5}s  {str(row['via'])[:44]}")
    print("total", total)
    print("checks", checks)
    print("failures", failures or "none")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
