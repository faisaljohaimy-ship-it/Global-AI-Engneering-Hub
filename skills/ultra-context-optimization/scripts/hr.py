#!/usr/bin/env python3
"""hr: keep the full output on disk, print a compressed view, fetch the original on demand.

    hr run [--intent TEXT] [--kind K] -- COMMAND...   run a command, print a compressed view of its output
    hr put [--intent TEXT] [--kind K] [FILE]          the same for a file or standard input (K: json log search diff plain)
    hr get REF [--lines A:B | --grep RE [-C N] | --head N | --tail N | --all]
    hr verify REF                            recompute the checksum of the stored original
    hr ls                                    list what this session stored

The command is started directly from its words, without a shell. The original always
stays in a private store outside any repository, addressed by its
SHA-256, so nothing is lost when the view is short. Compression is done by Headroom
running in-process in its own Python environment, with telemetry off, offline mode on
and, where the kernel allows it, no network at all. This script never starts a proxy and
never touches model requests or credentials.

Headroom is used where it was measured to help: its pipeline for JSON (a lossless
table), its log transform for test and build output, its search transform for grep-style
results and its diff transform for patches. Prose, listings and source code are not
rewritten: they get a plain head and tail, because for those the right move is to read
the part you need. If Headroom is missing, fails or does not make the output smaller,
the view also falls back to the plain head, tail and error lines, and says so.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOL_HOME = Path(os.environ.get("HR_TOOL_HOME", Path.home() / ".gaie-tools" / "headroom"))
STORE = Path(os.environ.get("HR_STORE", Path.home() / ".gaie-store"))
SMALL = int(os.environ.get("HR_SMALL", "1500"))  # characters; shorter output is printed as it is
MIN_GAIN = 0.10  # a view must be at least this much shorter than the original to be used
MARK = "[hr ref="
LEGACY_TOKENIZER = "litellm/litellm_core_utils/tokenizers/anthropic_tokenizer.json"

# Lines that must reach the reader word for word.
ERROR = re.compile(
    r"Traceback \(most recent call last\)|[A-Za-z_.]*(?:Error|Exception)\b|\bFAIL(?:ED|URE|S)?\b"
    r"|\bfailed\b|\bfatal\b|\bpanic(?:ked)?\b|Segmentation fault|^not ok\b|\bERR!|\berror(?:\[[A-Z0-9]+\])?:"
    r"|\bdenied\b|\btimed? ?out\b|✗|✘|^E {3}",
    re.M,
)
ERROR_SPAN = re.compile(r"[A-Za-z_.]*(?:Error|Exception)\b[^\"\n\\]{0,160}")
LONG_LINE = 500
KEEP_CAP = 60

# What kind of output a command produces, so the matching transform is used.
KINDS = ("json", "log", "search", "diff", "plain")
LOG_COMMAND = re.compile(
    r"\b(pytest|unittest|vitest|jest|mocha|playwright|tsc|eslint|ruff|mypy|make|gradle|mvn|tox|nox)\b"
    r"|\bnode\s+--test\b|\b(npm|pnpm|yarn|bun)\s+(run\s+)?(test|build|lint|check|install|ci)\b"
    r"|\b(cargo|go)\s+(test|build|check|vet)\b|\b(pip|uv)\s+(pip\s+)?(install|sync|compile)\b"
    r"|\bdocker\s+build\b|verify/browser\.mjs")
SEARCH_COMMAND = re.compile(r"(^|[|;&]\s*|\s)(rg|grep|ag|ack)\s|\bgit\s+grep\b")
DIFF_COMMAND = re.compile(r"\bgit\s+(diff|show)\b|(^|\s)diff\s")
HEADROOM_HINT = re.compile(r"\. Retrieve more: hash=[0-9a-f]+")


def kind_of(command: str, text: str) -> str:
    """Decide by the command first, then by the file name, then by the shape of the text."""
    if DIFF_COMMAND.search(command) or re.search(r"\.(diff|patch)\b", command):
        return "diff"
    if SEARCH_COMMAND.search(command):
        return "search"
    if LOG_COMMAND.search(command) or re.search(r"\.log\b", command):
        return "log"
    if text.lstrip()[:1] in "[{":
        return "json"
    return ""


def session() -> str:
    raw = os.environ.get("HR_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "default"
    return re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:80] or "default"


def store_dir(name: str | None = None) -> Path:
    path = STORE / (name or session())
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(STORE, 0o700)
    os.chmod(path, 0o700)
    return path


def save(text: str, meta: dict) -> dict:
    data = text.encode("utf-8", "surrogatepass")
    digest = hashlib.sha256(data).hexdigest()
    ref = digest[:16]
    folder = store_dir()
    raw = folder / f"{ref}.raw"
    if not raw.exists():
        raw.write_bytes(data)
        os.chmod(raw, 0o600)
    meta = {"ref": ref, "sha256": digest, "bytes": len(data), "chars": len(text),
            "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **meta}
    info = folder / f"{ref}.json"
    info.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(info, 0o600)
    return meta


def load(ref: str) -> tuple[str, dict]:
    if not re.fullmatch(r"[0-9a-f]{8,64}", ref):
        raise SystemExit(f"hr: not a reference: {ref}")
    hits = sorted(store_dir().glob(f"{ref}*.raw"))
    if len(hits) != 1:
        raise SystemExit(f"hr: {'no' if not hits else 'more than one'} stored output matches {ref} in this session")
    raw = hits[0]
    info = raw.with_suffix(".json")
    meta = json.loads(info.read_text(encoding="utf-8")) if info.exists() else {}
    return raw.read_bytes().decode("utf-8", "surrogatepass"), meta


def must_keep(text: str) -> list[tuple[int, str]]:
    """The lines, or for very long lines the error phrases, that a view may not lose."""
    kept: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not ERROR.search(line):
            continue
        if len(line) <= LONG_LINE:
            kept.append((number, line.strip()))
        else:
            kept.extend((number, span.strip()) for span in ERROR_SPAN.findall(line))
    seen: set[str] = set()
    unique = []
    for number, line in kept:
        if line and line not in seen:
            seen.add(line)
            unique.append((number, line))
    return unique


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def clip(line: str) -> str:
    """Shorten one very long line to its start and end."""
    if len(line) <= LONG_LINE + 200:
        return line
    return f"{line[:LONG_LINE - 200]} …[{len(line) - LONG_LINE} chars cut]… {line[-200:]}"


def plain_view(text: str, head: int = 30, tail: int = 30) -> str:
    lines = text.splitlines()
    if len(lines) > head + tail + 5:
        lines = lines[:head] + [f"… {len(lines) - head - tail} lines not shown …"] + lines[-tail:]
    return "\n".join(clip(line) for line in lines)


def worker_command() -> list[str] | None:
    python = TOOL_HOME / "venv" / "bin" / "python"
    if not python.exists():
        return None
    command = [str(python), "-I", str(Path(__file__).resolve()), "_worker"]
    unshare = shutil.which("unshare")
    if unshare and os.environ.get("HR_NETNS", "1") != "0":
        probe = subprocess.run([unshare, "-n", "true"], capture_output=True)
        if probe.returncode == 0:
            return [unshare, "-n", *command]
    return command


def worker_env() -> dict:
    env = {key: value for key, value in os.environ.items()
           if key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")}
    env.update(HEADROOM_OFFLINE="1", HEADROOM_TELEMETRY="off", HEADROOM_UPDATE_CHECK="0",
               HEADROOM_BINARIES_OFFLINE="1", DO_NOT_TRACK="1", HF_HUB_OFFLINE="1",
               TRANSFORMERS_OFFLINE="1", LITELLM_LOCAL_MODEL_COST_MAP="True", NO_COLOR="1")
    return env


def compress(text: str, raw_path: Path, intent: str, command: str, kind: str) -> dict:
    """Ask the Headroom worker for a view. Any failure returns {'error': ...}."""
    if kind == "plain":
        return {"error": "plain view asked for"}
    call = worker_command()
    if call is None:
        return {"error": "Headroom is not installed"}
    request = json.dumps({"path": str(raw_path), "intent": intent, "command": command, "kind": kind})
    try:
        done = subprocess.run(call, input=request, capture_output=True, text=True,
                              timeout=int(os.environ.get("HR_TIMEOUT", "90")), env=worker_env())
    except subprocess.TimeoutExpired:
        return {"error": "Headroom timed out"}
    if done.returncode != 0:
        last = (done.stderr.strip().splitlines() or ["no message"])[-1]
        return {"error": f"Headroom failed: {last[:160]}"}
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"error": "Headroom returned no result"}


def view(text: str, intent: str, command: str, rc: int | None = None, kind: str = "") -> tuple[str, dict]:
    """Return what to print and the facts about it."""
    if text.startswith(MARK):  # already a view: never compress twice
        return text, {"via": "already a view"}
    if len(text) < SMALL:
        return text, {"via": "as it is"}
    meta = save(text, {"command": command, "intent": intent, "rc": rc})
    raw_path = store_dir() / f"{meta['ref']}.raw"
    kind = kind or kind_of(command, text)
    result = compress(text, raw_path, intent, command, kind)
    body, via, note = "", "", ""
    if "error" not in result and result.get("text") and len(result["text"]) <= len(text) * (1 - MIN_GAIN):
        body = HEADROOM_HINT.sub("", result["text"])
        via = "headroom " + "+".join(result.get("transforms", [])) + (" lossless" if result.get("lossless") else "")
        if kind == "log":  # the closing summary of a run always reaches the reader
            tail = [line for line in text.splitlines() if line.strip()][-3:]
            lost_tail = [line for line in tail if squash(line.strip()) not in squash(body)]
            if lost_tail:
                body += "\n[hr last lines of the original]\n" + "\n".join(lost_tail)
    else:
        note = result.get("error") or ("Headroom did not shorten it" if result.get("text") else "no Headroom transform for this kind of output")
        body = plain_view(text)
        via = f"plain head and tail ({note})"
        if len(body) > len(text) * (1 - MIN_GAIN):
            # Nothing gained: print the output unchanged, with no header, and keep no copy.
            for leftover in (raw_path, raw_path.with_suffix(".json")):
                leftover.unlink(missing_ok=True)
            return text, {"via": "as it is", "kind": kind or "unknown"}
    flat = squash(body)
    missing = [(number, line) for number, line in must_keep(text) if squash(line) not in flat]
    if missing:
        shown = missing if len(missing) <= KEEP_CAP else missing[: KEEP_CAP // 2] + missing[-KEEP_CAP // 2:]
        body += "\n[hr exact lines from the original, as line:text]\n" + "\n".join(f"{n}:{line}" for n, line in shown)
        if len(missing) > len(shown):
            body += f"\n[hr {len(missing) - len(shown)} more: hr get {meta['ref']} --grep 'Error|FAIL|failed']"
    facts = {**meta, "kind": kind or "unknown", "via": via, "view_chars": len(body), "appended": len(missing),
             "seconds": result.get("seconds")}
    share = 100 * (1 - len(body) / len(text))
    head = (f"{MARK}{meta['ref']} raw={meta['chars']}ch/{meta['lines']}ln view={len(body)}ch ({share:.0f}% shorter)"
            + (f" rc={rc}" if rc is not None else "") + f" via {via}]")
    foot = f"[hr original: hr get {meta['ref']} --lines A:B | --grep RE | --all]"
    return f"{head}\n{body}\n{foot}", facts


# ---- the worker: runs inside Headroom's own environment ---------------------------------

def worker() -> None:
    started = time.perf_counter()
    request = json.loads(sys.stdin.read())
    text = Path(request["path"]).read_bytes().decode("utf-8", "replace")
    intent = request.get("intent") or "Report the result. Keep every error, failure and anomaly exactly."
    kind = request.get("kind") or ""
    out, transforms, lossless = "", [], False
    if kind in ("", "json"):
        from headroom import compress as headroom_compress  # noqa: PLC0415

        messages = [
            {"role": "user", "content": intent},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "hr1", "name": "bash",
                                               "input": {"command": request.get("command") or "cat output"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "hr1", "content": text}]},
        ]
        result = headroom_compress(messages)
        content = result.messages[-1]["content"]
        if isinstance(content, list):
            content = content[0].get("content", content[0].get("text", ""))
        if isinstance(content, list):
            content = "\n".join(block.get("text", "") for block in content if isinstance(block, dict))
        if isinstance(content, str) and len(content) < len(text):
            out = content
            transforms = [name.split(":")[-1] for name in result.transforms_applied if "tool_result" in name]
            lossless = bool(getattr(result, "lossless", False))
    if not out and kind == "":
        from headroom.transforms.content_detector import detect_content_type  # noqa: PLC0415

        detected = detect_content_type(text).content_type.name
        kind = {"SEARCH_RESULTS": "search", "BUILD_OUTPUT": "log", "GIT_DIFF": "diff"}.get(detected, "")
    if not out and kind == "log":
        from headroom.transforms.log_compressor import LogCompressor  # noqa: PLC0415

        out, transforms = LogCompressor().compress(text, context=intent).compressed, ["log_compressor"]
    elif not out and kind == "search":
        from headroom.transforms.search_compressor import SearchCompressor  # noqa: PLC0415

        out, transforms = SearchCompressor().compress(text, context=intent).compressed, ["search_compressor"]
    elif not out and kind == "diff":
        from headroom.transforms.diff_compressor import DiffCompressor  # noqa: PLC0415

        out, transforms = DiffCompressor().compress(text, context=intent).compressed, ["diff_compressor"]
    json.dump({"text": out, "transforms": transforms, "lossless": lossless,
               "seconds": round(time.perf_counter() - started, 3)}, sys.stdout)


def count_tokens(texts: list[str]) -> list[int] | None:
    """Token counts from the legacy Claude tokenizer that ships inside litellm. A proxy:
    it is a real tokenizer, but not the one the current models use."""
    python = TOOL_HOME / "venv" / "bin" / "python"
    if not python.exists():
        return None
    code = ("import sys,json,glob,tokenizers,sysconfig\n"
            f"f=glob.glob(sysconfig.get_paths()['purelib']+'/{LEGACY_TOKENIZER}')\n"
            "t=tokenizers.Tokenizer.from_file(f[0])\n"
            "print(json.dumps([len(t.encode(x).ids) for x in json.load(sys.stdin)]))")
    done = subprocess.run([str(python), "-I", "-c", code], input=json.dumps(texts), capture_output=True, text=True)
    return json.loads(done.stdout) if done.returncode == 0 else None


# ---- commands ---------------------------------------------------------------------------

def command_run(args: argparse.Namespace) -> int:
    if not args.command:
        raise SystemExit("hr run: give a command after --")
    try:
        done = subprocess.run(args.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        raise SystemExit(f"hr run: cannot start {args.command[0]!r}. Give the command as separate words; "
                         "for a pipeline write: hr run -- bash -c '...'") from None
    text = done.stdout.decode("utf-8", "replace")
    shown, _ = view(text, args.intent or "", " ".join(args.command), done.returncode, args.kind or "")
    sys.stdout.write(shown if shown.endswith("\n") else shown + "\n")
    return done.returncode


def command_put(args: argparse.Namespace) -> int:
    text = Path(args.file).read_bytes().decode("utf-8", "replace") if args.file else sys.stdin.read()
    shown, _ = view(text, args.intent or "", f"cat {args.file}" if args.file else "", None, args.kind or "")
    sys.stdout.write(shown if shown.endswith("\n") else shown + "\n")
    return 0


def command_get(args: argparse.Namespace) -> int:
    text, meta = load(args.ref)
    lines = text.splitlines()
    if args.all:
        sys.stdout.write(text)
    elif args.lines:
        first, _, last = args.lines.partition(":")
        start = max(int(first or 1), 1)
        end = min(int(last or len(lines)), len(lines))
        print("\n".join(f"{n}:{lines[n - 1]}" for n in range(start, end + 1)))
    elif args.grep:
        pattern = re.compile(args.grep)
        wanted: set[int] = set()
        for index, line in enumerate(lines):
            if pattern.search(line):
                wanted.update(range(max(0, index - args.context), min(len(lines), index + args.context + 1)))
        print("\n".join(f"{n + 1}:{lines[n]}" for n in sorted(wanted)) or "hr: no line matches")
    elif args.head:
        print("\n".join(lines[: args.head]))
    elif args.tail:
        print("\n".join(lines[-args.tail:]))
    else:
        print(json.dumps({k: meta.get(k) for k in ("ref", "sha256", "bytes", "lines", "created", "command", "rc")}, ensure_ascii=False))
    return 0


def command_verify(args: argparse.Namespace) -> int:
    text, meta = load(args.ref)
    digest = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
    intact = digest == meta.get("sha256") and digest.startswith(args.ref)
    print(f"{meta.get('ref', args.ref)} {'intact' if intact else 'CHANGED'} {digest}")
    return 0 if intact else 1


def command_ls(_: argparse.Namespace) -> int:
    for info in sorted(store_dir().glob("*.json"), key=lambda p: p.stat().st_mtime):
        meta = json.loads(info.read_text(encoding="utf-8"))
        print(f"{meta['ref']} {meta['created']} {meta['chars']}ch {meta['lines']}ln {str(meta.get('command') or '')[:70]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_worker"]:
        worker()
        return 0
    parser = argparse.ArgumentParser(prog="hr", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="name", required=True)
    run = commands.add_parser("run")
    run.add_argument("--intent")
    run.add_argument("--kind", choices=KINDS)
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(call=command_run)
    put = commands.add_parser("put")
    put.add_argument("--intent")
    put.add_argument("--kind", choices=KINDS)
    put.add_argument("file", nargs="?")
    put.set_defaults(call=command_put)
    get = commands.add_parser("get")
    get.add_argument("ref")
    get.add_argument("--lines")
    get.add_argument("--grep")
    get.add_argument("-C", "--context", type=int, default=0)
    get.add_argument("--head", type=int)
    get.add_argument("--tail", type=int)
    get.add_argument("--all", action="store_true")
    get.set_defaults(call=command_get)
    verify = commands.add_parser("verify")
    verify.add_argument("ref")
    verify.set_defaults(call=command_verify)
    commands.add_parser("ls").set_defaults(call=command_ls)
    args = parser.parse_args(argv)
    if args.name == "run" and args.command[:1] == ["--"]:
        args.command = args.command[1:]
    return args.call(args)


if __name__ == "__main__":
    sys.exit(main())
