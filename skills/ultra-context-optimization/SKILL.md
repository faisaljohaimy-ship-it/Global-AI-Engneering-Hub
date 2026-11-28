---
name: ultra-context-optimization
description: Keep an agent's context small without losing facts. Compress large tool output while the original stays retrievable, read code by symbol instead of by whole file, and send each kind of content to the one tool measured to handle it. Use when a command prints a lot, when exploring unfamiliar code, when a session grows long, or before starting a large task.
---

Read the project's own instructions first. This skill changes how you work, not what the
project requires: every mandatory test, review and security rule still applies.

## Rules that apply from the first step

1. Read the part you need. Search first, then open the lines around the hit. Do not read
   a whole large file or a whole repository to answer a narrow question.
2. Do not read again what has not changed. Use a checksum or `git diff --stat` to decide.
3. Long output goes to a file, not into the conversation. Print the result, the errors
   and where the full text is.
4. If a script can answer, do not ask the model. Counting, filtering, comparing and
   formatting are script work.
5. One tool per job (table below). Do not run two tools that do the same thing.
6. One agent by default. Two when two tasks are independent and both gain from running at
   once. More only when you can show the gain and the machine has room. Give each agent
   its scope, files, acceptance test and limits, and a separate worktree if it edits.
7. Do not redo finished work or re-plan a settled plan. Save a checkpoint after each unit.
8. Never skip a mandatory check to save tokens. Run the narrow test while you work and
   every required check before a merge.

## Set up

```bash
skills/ultra-context-optimization/scripts/bootstrap.sh            # Headroom, from the hub's reviewed lock
skills/ultra-context-optimization/scripts/bootstrap.sh serena     # add symbol queries
export PATH="$HOME/.gaie-tools/bin:$PATH"
python3 skills/ultra-context-optimization/scripts/detect_env.py   # what this machine supports
```

Tools install into `~/.gaie-tools`, outside every repository, from the lock files in
`locks/`. Nothing is installed globally and no proxy, server or credential is involved.

## Which tool for which content

| Content | Use | Why |
|---|---|---|
| JSON from a command or file | `hr run -- CMD` or `hr put FILE` | the hub's Headroom tool gives a verified lossless table when it can |
| Test and build output | `hr run -- CMD` | Headroom's log transform keeps failures and the summary |
| A large set of search hits | the host's search tool with a limit; else `hr run -- rg ...` | grouped by file |
| A patch | `hr run -- git diff ...` | Headroom's diff transform |
| A specific question about data | a short script that prints only the answer | smaller than any compression |
| Where a function is defined, who calls it | `sym def NAME FILE`, `sym refs NAME FILE` | the language server knows; a text match guesses |
| What a file contains | `sym overview FILE` | names only, about 2% of the file in the test |
| A code shape (every call of `f(...)`, every empty `except`) | `ast-grep run -p 'PATTERN' -l LANG` | matches syntax, not text |
| Plain text match | ripgrep or the host's search tool | fastest; already there |
| A scoped overview of several files for review | `repomix --include 'GLOB' --compress` | signatures without bodies |
| Prose, listings, source code you must act on | read the lines you need | never rewritten by `hr` |
| Library documentation for a pinned version | Context7, only when the lock file's version matters and the host allows it | see `references/tools.md` |

`hr` prints a view and a reference. The original is kept under `~/.gaie-store`, per
session, addressed by its SHA-256:

```bash
hr get REF --grep 'Error|FAIL' -C 2     # exact lines from the original
hr get REF --lines 120:160
hr verify REF                           # the stored original still matches its checksum
```

Every line of the original that looks like an error is in the view word for word, or is
appended to it. Output shorter than 1,500 characters is printed unchanged.

## Never compress twice

A view starts with `[hr ref=`. `hr` passes such text through untouched. Do not feed a
view, a Context Mode reply or a Repomix pack to another compressor. If you need more, go
back to the original with `hr get`.

## What is never shortened

- Protected: requirements, acceptance criteria, security rules, licence terms, error
  messages, failing test names, commit SHAs, version numbers, file paths, the code you
  are about to edit, and anything the owner wrote. Keep these exact.
- May be shortened: passing test lines, repeated records, progress bars, long listings,
  search hits beyond the ones you use.
- Throwaway: installer chatter, colour codes, timing noise. Leave it in the log file.

Correctness comes first, then security, then keeping information intact, then saving
resources, then speed.

## When the session is long

Use the host's real context figure if it shows one. Do not invent a percentage. The
bands below are this skill's working rule:

- up to half: work normally with the rules above;
- half to three quarters: views and symbol queries only, no whole-file reads over a few
  hundred lines;
- three quarters to nine tenths: finish the current unit, save a checkpoint, drop detail
  you no longer need;
- above nine tenths, or right after the host compacts the conversation: write the resume
  point before anything else and start no new unit.

Compaction, clearing and context reports are host features. Say when the user has to run
one; do not claim to have run it.

## Checkpoints

After each unit, record what is done, what is next, the branch and commit, and the test
evidence. In the hub, use `python3 -m engineering_os.orchestration --state-dir DIR`
(`create`, `claim`, `checkpoint`, `handover`) with a private state folder outside Git,
and put the public-safe handover in the pull request. Never commit private project
memory, customer data or the `~/.gaie-store` contents.

## Security

- No tool here changes where model requests go or how the account signs in. Headroom's
  `proxy`, `wrap`, `init`, `install` and `deploy` commands are not used.
- The hub has one Headroom integration, and `hr` is its front end. The SDK runs only
  behind the hub tool's kernel boundary, which refuses IP sockets, with telemetry off and
  offline mode on. Originals live in that tool's private store; what it refuses to take,
  such as JSON with credential fields, is not stored.
- Private code is not sent to outside services. Context7 receives library names and
  topics only.
- Versions are pinned and hash-checked. No floating version, no unreviewed install script.
- This does not raise a subscription or model limit and is not a way around one.

## What is proven, and for which host

`references/tools.md` lists each tool with its version, licence and exactly how far it
got: reviewed, installed, tested, usable in the host, actually used, or blocked.
`references/measurements.md` holds the numbers and how they were taken. `evidence/`
holds the raw results. `tests/test_context_optimization.py` in the hub checks the
wrapper without needing the external tools.

The scripts are plain Python and Bash, so Claude Code and Codex can both run them. That
they are in the repository proves nothing about a host: run `detect_env.py` and
`measure.py` there before relying on them.
