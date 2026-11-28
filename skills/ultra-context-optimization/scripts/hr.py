#!/usr/bin/env python3
"""hr: keep the full output on disk, print a compressed view, fetch the original on demand.

    hr run [--intent TEXT] [--kind K] -- COMMAND...   run a command, print a compressed view of its output
    hr put [--intent TEXT] [--kind K] [FILE]          the same for a file or standard input (K: json log search diff plain)
    hr get REF [--lines A:B | --grep RE [-C N] | --head N | --tail N | --all]
    hr verify REF                            have the stored original checked against its SHA-256
    hr ls                                    list what this session stored

The hub has one Headroom integration, and this is its command-line front end. The work is
done by the hub's own tool, tools/headroom_context.py, and its worker:

- the original is kept by that tool, in its private, immutable, checksummed store, and is
  read back through it; this script keeps no copy of its own;
- the SDK is the one version that tool pins, installed from the hub's reviewed lock,
  integrations/headroom/requirements.lock;
- every import of the SDK happens behind that tool's boundary: a kernel filter that
  refuses IP sockets, no new privileges, limits on CPU, memory and file size, an
  environment with no credentials and no proxy settings, and private scratch folders.
  Where the kernel also allows an empty network namespace, that is added on top.

A view is made in two steps. First the hub tool is asked for its verified lossless
result. If it has none, the SDK's transform for that kind of output (JSON, a log, search
results, a patch) is run behind the same boundary. That second view is not verified to
hold the whole content, and its header says so. Prose, listings and source code are not
rewritten: they get a plain head and tail. Whatever the view, the lines that carry errors
are appended word for word if they are missing from it.

The command is started directly from its words, without a shell. This script never starts
a proxy and never touches model requests or credentials. Content the hub tool refuses,
such as JSON with credential fields or anything over 2 MiB, is shown as a plain view and
is not stored.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOL_HOME = Path(os.environ.get("HR_TOOL_HOME", Path.home() / ".gaie-tools" / "headroom"))
STORE = Path(os.environ.get("HR_STORE", Path.home() / ".gaie-store"))
SMALL = int(os.environ.get("HR_SMALL", "1500"))  # characters; shorter output is printed as it is
MIN_GAIN = 0.10  # a view must be at least this much shorter than the original to be used
MARK = "[hr ref="
LEGACY_TOKENIZER = "litellm/litellm_core_utils/tokenizers/anthropic_tokenizer.json"
MAX_STORED = 2 * 1024 * 1024  # the hub tool's bound on one original, in bytes
BOUNDARY = "linux-seccomp-no-ip"  # the name the hub worker gives its kernel boundary

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


# ---- the hub's tool: the one store, the one SDK version, the one boundary -----------------

def hub_tool() -> Path | None:
    """tools/headroom_context.py, in the hub checkout or in a project its pack was installed into."""
    named = os.environ.get("HR_HUB_TOOL")
    candidates = [Path(named)] if named else [parent / "tools" / "headroom_context.py" for parent in Path(__file__).resolve().parents]
    for candidate in candidates:
        if candidate.is_file() and candidate.with_name("headroom_worker.py").is_file():
            return candidate
    return None


def hub_module():
    """The hub tool as a module. It needs only the standard library."""
    tool = hub_tool()
    if tool is None:
        return None
    spec = importlib.util.spec_from_file_location("hub_headroom_context", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def python() -> str:
    """The interpreter that holds the reviewed SDK, or this one when it is not installed."""
    venv = TOOL_HOME / "venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def hub(*arguments: str) -> tuple[dict | None, str]:
    """Run the hub tool. Returns its answer, or None and why there is none."""
    tool = hub_tool()
    if tool is None:
        return None, "the hub's Headroom tool is not installed here"
    env = {key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")}
    try:
        done = subprocess.run([python(), "-I", str(tool), *arguments], capture_output=True, text=True, encoding="utf-8",
                              timeout=int(os.environ.get("HR_TIMEOUT", "90")), env=env)
        result = json.loads(done.stdout)
    except subprocess.TimeoutExpired:
        return None, "the hub's tool timed out"
    except (ValueError, OSError):
        return None, "the hub's tool gave no answer"
    if not isinstance(result, dict) or result.get("status") == "rejected":
        return None, "the hub's tool refused this content"
    return result, ""


def session() -> str:
    raw = os.environ.get("HR_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "default"
    return re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:80] or "default"


def store_dir(name: str | None = None) -> Path:
    """This session's store. Each session has its own, so one cannot read another's."""
    STORE.mkdir(parents=True, exist_ok=True)
    os.chmod(STORE, 0o700)
    path = STORE / (name or session())
    path.mkdir(exist_ok=True)
    os.chmod(path, 0o700)
    return path


def private_folder(name: str) -> Path:
    path = store_dir() / name
    path.mkdir(exist_ok=True)
    os.chmod(path, 0o700)
    return path


def journal(name: str | None = None) -> list[dict]:
    """What this session asked to keep: reference, size, command. The content is not here."""
    path = STORE / (name or session()) / "hr-journal.jsonl"
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(ValueError):
                rows.append(json.loads(line))
    return rows


def record(meta: dict) -> None:
    descriptor = os.open(store_dir() / "hr-journal.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(meta, ensure_ascii=False) + "\n")


def keep(text: str) -> tuple[dict | None, str]:
    """Hand the original to the hub tool. Returns its result, or None and why nothing was stored."""
    if hub_tool() is None:
        return None, "the hub's Headroom tool is not installed here"
    data = text.encode("utf-8", "replace")
    if len(data) > MAX_STORED:
        return None, f"over the store's limit of {MAX_STORED // 2 ** 20} MiB"
    kind = "log"  # the hub tool's name for text; its kind is decided by the content alone, so it never changes
    if text.lstrip()[:1] in "[{":
        with contextlib.suppress(ValueError):
            json.loads(text)
            kind = "tool-json"
    handle, name = tempfile.mkstemp(dir=private_folder("spool"), suffix=".txt")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        result, problem = hub("optimize", "--input", name, "--store", str(store_dir()), "--kind", kind)
    finally:
        os.unlink(name)
    if result is None:
        return None, problem
    if result.get("status") not in ("optimized", "passthrough", "fallback") or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("id"))):
        return None, "the hub's tool refused this content"
    return result, ""


def find(ref: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{8,64}", ref):
        raise SystemExit(f"hr: not a reference: {ref}")
    hits = {row["sha256"]: row for row in journal() if str(row.get("sha256", "")).startswith(ref)}
    if len(hits) != 1:
        raise SystemExit(f"hr: {'no' if not hits else 'more than one'} stored output matches {ref} in this session")
    return next(iter(hits.values()))


def fetch(meta: dict) -> str | None:
    """The original, from the hub tool, which checks it against its SHA-256 before answering."""
    result, _ = hub("retrieve", "--store", str(STORE / session()), "--id", meta["sha256"], "--full")
    if not result or result.get("source_hash_verified") is not True or result.get("complete") is not True:
        return None
    return result.get("content")


def load(ref: str) -> tuple[str, dict]:
    meta = find(ref)
    text = fetch(meta)
    if text is None:
        raise SystemExit(f"hr: the stored original of {meta['ref']} is missing or no longer matches its checksum")
    return text, meta


# ---- views ------------------------------------------------------------------------------

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
    """The transform worker: the SDK's interpreter, this file, and the hub worker whose boundary it enters."""
    tool = hub_tool()
    venv = TOOL_HOME / "venv" / "bin" / "python"
    if tool is None or not venv.exists():
        return None
    command = [str(venv), "-I", str(Path(__file__).resolve()), "_worker", str(tool.with_name("headroom_worker.py"))]
    unshare = shutil.which("unshare")
    if unshare and os.environ.get("HR_NETNS", "1") != "0" and subprocess.run([unshare, "-n", "true"], capture_output=True).returncode == 0:
        return [unshare, "-n", *command]
    return command


def worker_env(directory: Path) -> dict:
    """The hub tool's own worker environment, plus the SDK's remaining offline switches."""
    module = hub_module()
    if module is None:
        raise RuntimeError("the hub's Headroom tool is not installed here")
    env = dict(module._worker_environment(directory))  # noqa: SLF001 - one definition of the environment, the hub's
    env.update(HEADROOM_UPDATE_CHECK="0", HEADROOM_BINARIES_OFFLINE="1", NO_COLOR="1")
    return env


def transform(text: str, intent: str, command: str, kind: str) -> dict:
    """Ask the SDK's transform for this kind of output, behind the hub's boundary. Any failure returns {'error': ...}."""
    call = worker_command()
    if call is None:
        return {"error": "Headroom is not installed"}
    request = json.dumps({"text": text, "intent": intent, "command": command, "kind": kind})
    try:
        with tempfile.TemporaryDirectory(prefix="sdk-", dir=private_folder("hr-jobs")) as scratch:
            done = subprocess.run(call, input=request, capture_output=True, text=True, encoding="utf-8", cwd=scratch,
                                  timeout=int(os.environ.get("HR_TIMEOUT", "90")), env=worker_env(Path(scratch)))
        result = json.loads(done.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "Headroom timed out"}
    except (OSError, ValueError, RuntimeError):
        return {"error": "Headroom returned no result"}
    if not isinstance(result, dict) or result.get("ok") is not True:
        return {"error": "Headroom failed behind its boundary"}
    if result.get("network_boundary") != BOUNDARY or result.get("sdk_version") != hub_module().VERSION:
        return {"error": "an unreviewed runtime answered"}
    return result


def view(text: str, intent: str, command: str, rc: int | None = None, kind: str = "") -> tuple[str, dict]:
    """Return what to print and the facts about it."""
    if text.startswith(MARK):  # already a view: never compress twice
        return text, {"via": "already a view"}
    if len(text) < SMALL:
        return text, {"via": "as it is"}
    kind = kind or kind_of(command, text)
    plain = plain_view(text)
    if kind in ("", "plain") and len(plain) > len(text) * (1 - MIN_GAIN):
        return text, {"via": "as it is", "kind": kind or "unknown"}  # nothing to gain, so nothing is stored
    result, why = keep(text)
    meta = {"ref": None, "sha256": None, "bytes": len(text.encode("utf-8", "replace")), "chars": len(text),
            "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "command": command, "intent": intent, "rc": rc}
    body, via, note, seconds, lossless = "", "", f"{why}; original not kept", None, False
    if result is not None:
        meta.update(ref=result["id"][:16], sha256=result["id"])
        note = str(result.get("reason") or "no lossless result")
        content = result.get("content")
        if kind != "plain" and result["status"] == "optimized" and isinstance(content, str) and len(content) <= len(text) * (1 - MIN_GAIN):
            body, via, lossless = content, "headroom lossless, verified by the hub tool", True
            seconds = round((result.get("compression_latency_ms") or 0) / 1000, 3)
        elif kind != "plain" and not note.startswith("protected"):
            special = transform(text, intent, command, kind)
            if "error" not in special and special.get("text") and len(special["text"]) <= len(text) * (1 - MIN_GAIN):
                body = HEADROOM_HINT.sub("", special["text"])
                via = "headroom " + "+".join(special.get("transforms", [])) + (", lossless by its own report" if special.get("lossless") else ", not verified lossless")
                seconds = special.get("seconds")
                if kind == "log":  # the closing summary of a run always reaches the reader
                    tail = [line for line in text.splitlines() if line.strip()][-3:]
                    lost_tail = [line for line in tail if squash(line.strip()) not in squash(body)]
                    if lost_tail:
                        body += "\n[hr last lines of the original]\n" + "\n".join(lost_tail)
            else:
                note = special.get("error") or ("Headroom did not shorten it" if special.get("text") else "no Headroom transform for this kind of output")
    if not body:
        body, via = plain, f"plain head and tail ({note})"
        if len(body) > len(text) * (1 - MIN_GAIN):
            return text, {"via": "as it is", "kind": kind or "unknown"}  # nothing gained: print it unchanged, with no header
    flat = squash(body)
    missing = [(number, line) for number, line in must_keep(text) if squash(line) not in flat]
    if missing:
        shown = missing if len(missing) <= KEEP_CAP else missing[: KEEP_CAP // 2] + missing[-KEEP_CAP // 2:]
        body += "\n[hr exact lines from the original, as line:text]\n" + "\n".join(f"{n}:{line}" for n, line in shown)
        if len(missing) > len(shown) and meta["ref"]:
            body += f"\n[hr {len(missing) - len(shown)} more: hr get {meta['ref']} --grep 'Error|FAIL|failed']"
    if meta["ref"]:
        record(meta)
    facts = {**meta, "kind": kind or "unknown", "via": via, "view_chars": len(body), "appended": len(missing),
             "seconds": seconds, "lossless": lossless, "stored": bool(meta["ref"])}
    share = 100 * (1 - len(body) / len(text))
    head = (f"{MARK}{meta['ref'] or 'none'} raw={meta['chars']}ch/{meta['lines']}ln view={len(body)}ch ({share:.0f}% shorter)"
            + (f" rc={rc}" if rc is not None else "") + f" via {via}]")
    foot = (f"[hr original: hr get {meta['ref']} --lines A:B | --grep RE | --all]" if meta["ref"]
            else "[hr original was not kept: run the command again, more narrowly, to see more]")
    return f"{head}\n{body}\n{foot}", facts


# ---- the worker: runs in the SDK's environment, behind the hub worker's boundary ---------

def worker(boundary_path: str) -> None:
    started = time.perf_counter()
    request = json.loads(sys.stdin.buffer.read(16 * MAX_STORED))
    spec = importlib.util.spec_from_file_location("hub_headroom_worker", boundary_path)
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
    # The hub worker's own entry point: it checks the offline settings and the private scratch
    # folders, loads the kernel filter that refuses IP sockets, drops the right to gain
    # privileges and sets the CPU, memory and file-size limits. Nothing of the SDK is imported
    # before it has answered.
    if boundary.execute({"operation": "probe"}) != {"ok": True, "network_boundary": BOUNDARY}:
        raise ValueError("the boundary was not established")
    if importlib.metadata.version("headroom-ai") != boundary.VERSION:
        raise ValueError("only the reviewed SDK version is allowed")
    text = request["text"]
    intent = request.get("intent") or "Report the result. Keep every error, failure and anomaly exactly."
    kind = request.get("kind") or ""
    out, transforms, lossless = "", [], False
    with contextlib.redirect_stdout(io.StringIO()):  # the SDK's own messages stay out of the answer
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
    sys.stdout.write(json.dumps({"ok": True, "text": out, "transforms": transforms, "lossless": lossless, "sdk_version": boundary.VERSION,
                                 "network_boundary": BOUNDARY, "seconds": round(time.perf_counter() - started, 3)}))


def count_tokens(texts: list[str]) -> list[int] | None:
    """Token counts from the legacy Claude tokenizer that ships inside litellm. A proxy:
    it is a real tokenizer, but not the one the current models use."""
    venv = TOOL_HOME / "venv" / "bin" / "python"
    if not venv.exists():
        return None
    code = ("import sys,json,glob,tokenizers,sysconfig\n"
            f"f=glob.glob(sysconfig.get_paths()['purelib']+'/{LEGACY_TOKENIZER}')\n"
            "t=tokenizers.Tokenizer.from_file(f[0])\n"
            "print(json.dumps([len(t.encode(x).ids) for x in json.load(sys.stdin)]))")
    done = subprocess.run([str(venv), "-I", "-c", code], input=json.dumps(texts), capture_output=True, text=True)
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
    meta = find(args.ref)
    text = fetch(meta)
    intact = text is not None and hashlib.sha256(text.encode("utf-8", "replace")).hexdigest() == meta["sha256"]
    print(f"{meta['ref']} {'intact' if intact else 'CHANGED'} {meta['sha256']}")
    return 0 if intact else 1


def command_ls(_: argparse.Namespace) -> int:
    seen: set[str] = set()
    for meta in journal():
        if meta.get("sha256") not in seen:
            seen.add(meta.get("sha256"))
            print(f"{meta['ref']} {meta['created']} {meta['chars']}ch {meta['lines']}ln {str(meta.get('command') or '')[:70]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_worker"]:
        try:
            worker(argv[1])
        except Exception:  # noqa: BLE001 - the answer is machine-read, and a failure must not carry content
            sys.stdout.write(json.dumps({"ok": False}))
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
