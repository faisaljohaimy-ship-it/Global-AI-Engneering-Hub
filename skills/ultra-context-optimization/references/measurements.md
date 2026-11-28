# Measurements

Taken on 2026-11-28 in the session described in `tools.md`. Raw results are in
`evidence/`. Rerun them on your own machine with:

```bash
python3 scripts/measure.py SAMPLES_DIR evidence/headroom.json
```

## What the numbers are, and are not

- Characters are exact.
- Tokens are counted with the legacy Claude tokenizer that ships inside litellm. It is a
  real tokenizer, so it is a better guide than bytes, but the current models count
  differently. No official token counter was called, because that needs API access the
  session was not allowed to spend.
- Nothing here measures subscription quota, prompt-cache hits, CPU or memory. Fewer
  tokens in a tool result is not the same thing as a smaller bill or a larger allowance.
- The samples are small on purpose: twelve outputs, 373,308 characters in total. Eleven
  are real outputs from that session (test runs, a browser evidence file, a lock file,
  search results, a git log, a listing, a report, a source file, package metadata). One,
  shaped like a GitHub pull-request list, is synthetic and named so.

## `hr` on twelve outputs

| Sample | Characters | View | Tokens | View | Saved | Error lines lost | Seconds | Method |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| browser-diagnostics.json | 19,034 | 13,269 | 6,244 | 4,180 | 33.1% | 0 of 1 | 0.49 | Headroom, JSON table |
| dependency-list.json | 2,709 | 1,412 | 1,003 | 794 | 20.8% | 0 of 0 | 0.38 | Headroom, JSON table |
| github-response-synthetic.json | 63,863 | 20,678 | 20,028 | 8,248 | 58.8% | 0 of 0 | 0.45 | Headroom, JSON table |
| package-metadata.json | 15,898 | 9,384 | 6,302 | 3,370 | 46.5% | 0 of 1 | 0.41 | Headroom, JSON table |
| search-results.txt | 15,823 | 5,779 | 4,847 | 1,730 | 64.3% | 0 of 2 | 0.16 | Headroom, search |
| test-log-fail.log | 15,635 | 2,640 | 5,844 | 788 | 86.5% | 0 of 7 | 0.16 | Headroom, log |
| test-log-pass.log | 23,598 | 623 | 7,511 | 193 | 97.4% | 0 of 0 | 0.19 | Headroom, log |
| dependency-lock.txt | 165,664 | 4,973 | 88,232 | 2,570 | 97.1% | 0 of 0 | 0.43 | plain head and tail |
| engineering-report.md | 7,524 | 5,994 | 1,599 | 1,268 | 20.7% | 0 of 0 | 0.29 | plain head and tail |
| git-log-stat.txt | 17,218 | 3,171 | 5,413 | 897 | 83.4% | 0 of 0 | 0.36 | plain head and tail |
| source-code.mjs | 20,252 | 3,848 | 5,399 | 1,091 | 79.8% | 0 of 13 | 0.40 | plain head and tail |
| terminal-listing.txt | 6,090 | 2,770 | 2,470 | 1,127 | 54.4% | 0 of 0 | 0.38 | plain head and tail |

Read the two halves separately:

- Seven samples were handled by Headroom: 51,779 tokens became 19,303, a saving of
  62.7%. For the JSON samples the result is a table holding every row; for logs and
  search results it is a selection, with every error line kept.
- Five samples have no Headroom transform in this setup and got the plain view: the first
  and last thirty lines and a count of what is between. That saves 93.3% on these five,
  but by leaving the middle out, not by compressing it. It is only acceptable because the
  original is one `hr get` away. The overall figure of 83.0% is mostly this lock file and
  should not be quoted as Headroom's saving.

Checks that passed in the same run (`evidence/headroom.json`, `checks`):

- the stored original of every sample came back byte for byte and matched its SHA-256;
- a second session could not read the first session's store;
- a view passed in again was returned untouched;
- output under 1,500 characters was printed unchanged and not stored;
- with Headroom missing, and with its worker timing out, the plain view was used and the
  error line was still there;
- the wrapped command's exit status was passed on and shown;
- `hr get REF --lines 1999:2001` returned exactly those three lines.

The worker ran inside a network namespace with no interfaces, so these results needed no
network.

## Serena on the hub's code

| Question | Reply | Whole file | Seconds |
|---|---:|---:|---:|
| Symbols in `hublink.py` | 479 chars | 22,025 chars | 0.7 |
| Definition of `register` with its body | 6,366 | 22,025 | 0.1 |
| References to `register` | 2,463 | several files | 2.3 |
| Symbols in `packages/motion-sdk/index.mjs` | 378 | 21,507 | 0.7 |
| Definition of `validateScene` with its body | 2,029 | 21,507 | 0.1 |
| References to `validateScene` | 1,009 | several files | 5.2 |

Those times are inside one warm session of six questions, which took 10.2 seconds in all
including start-up. A single cold question through `sym` took 3.2 seconds. That cost is
worth paying for a large file or a reference search, and not for a file of fifty lines.

## Context Mode as a standalone server

Run with its own Node 24, no network, in a scratch project (`evidence/context-mode.json`).

- It started in 0.3 seconds and listed nine tools.
- Indexing four files took 10 to 30 milliseconds each. A search for the failing test's
  message returned 721 characters containing the exact error line; a search for a
  dependency returned 3,984 characters containing its pinned version.
- `ctx_execute` on a 63,863-byte JSON file returned 2,559 characters: the end of the
  output, which did not contain the one record the question was about. A four-line script
  run through the same tool printed the answer in 5 characters. For a specific question,
  compute the answer; do not ask for the output to be shortened.
- It could not be attached to the managed session, so there is no figure for it in real
  use there.

## Other tools

- ast-grep found the 14 `defineMotion(...)` calls in 14 files; a text search for the same
  name returned 28 lines, because it also matched the imports.
- Repomix packed one folder of ten modules with `--compress`: 52,490 characters became
  16,059 in 0.6 seconds, keeping signatures and dropping bodies.

## The five configurations

| Configuration | What was measured |
|---|---|
| A. Nothing added | the twelve outputs as they are: 154,892 tokens |
| B. With Headroom through `hr` | 26,256 tokens for the same twelve; 62.7% saved on the seven Headroom handled; 0.16 to 0.49 seconds added per command; no error line lost |
| C. With Context Mode | standalone only: search replies of 700 to 4,000 characters with exact lines; not usable in that session |
| D. With Serena | a symbol overview at about 2% of the file; a definition at 9% to 29%; 3 seconds for a cold question |
| E. All together, routed by content | not measured as one run. It is B for command output, D for code questions, ripgrep and ast-grep for search, and a script when the question is specific |

Configuration E is the one adopted, on the strength of the separate results above. An
end-to-end comparison on a whole task was not run, to keep the test itself from costing
more than it could save.
