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
| browser-diagnostics.json | 19,034 | 13,292 | 6,244 | 4,185 | 33.0% | 0 of 1 | 0.97 | Headroom JSON transform |
| dependency-list.json | 2,709 | 1,433 | 1,003 | 798 | 20.4% | 0 of 0 | 0.47 | hub tool: lossless, verified |
| github-response-synthetic.json | 63,863 | 14,562 | 20,028 | 6,376 | 68.2% | 0 of 0 | 0.69 | hub tool: lossless, verified |
| package-metadata.json | 15,898 | 9,407 | 6,302 | 3,375 | 46.4% | 0 of 1 | 1.18 | Headroom JSON transform |
| search-results.txt | 15,823 | 5,802 | 4,847 | 1,735 | 64.2% | 0 of 2 | 0.56 | Headroom search transform |
| test-log-fail.log | 15,635 | 2,663 | 5,844 | 793 | 86.4% | 0 of 7 | 0.62 | Headroom log transform |
| test-log-pass.log | 23,598 | 646 | 7,511 | 198 | 97.4% | 0 of 0 | 0.78 | Headroom log transform |
| dependency-lock.txt | 165,664 | 4,973 | 88,232 | 2,570 | 97.1% | 0 of 0 | 1.02 | plain head and tail |
| engineering-report.md | 7,524 | 5,994 | 1,599 | 1,268 | 20.7% | 0 of 0 | 0.71 | plain head and tail |
| git-log-stat.txt | 17,218 | 3,171 | 5,413 | 897 | 83.4% | 0 of 0 | 1.01 | plain head and tail |
| source-code.mjs | 20,252 | 3,848 | 5,399 | 1,091 | 79.8% | 0 of 13 | 0.78 | plain head and tail |
| terminal-listing.txt | 6,090 | 2,770 | 2,470 | 1,127 | 54.4% | 0 of 0 | 0.80 | plain head and tail |

Read the two halves separately:

- Seven samples were handled by Headroom: 51,779 tokens became 17,460, a saving of
  66.3%. For 2 of them (`dependency-list.json`, `github-response-synthetic.json`) the view is the
  hub tool's own result: lossless, with the identifiers and counts of the original checked
  in it. The other 5 come from the SDK's transform for that kind of output, run behind the
  same boundary; they are not verified to hold everything, and every error line is kept.
- Five samples have no Headroom transform in this setup and got the plain view: the first
  and last thirty lines and a count of what is between. That saves 93.3% on these five,
  but by leaving the middle out, not by compressing it. It is only acceptable because the
  original is one `hr get` away. The overall figure of 84.2% is mostly this lock file and
  should not be quoted as Headroom's saving.

These figures are from the one Headroom integration the hub now has: the hub's tool keeps
the original and gives the lossless result, and `hr` is its command-line front end. Before
the two were made one, `hr` had its own install of 0.44.0 and its own store, and the same
seven samples came to 19,303 tokens (62.7%) at 0.16 to 0.49 seconds per command. The
unified path takes 0.47 to 1.18 seconds per command, because it starts the hub tool and
then, when that has no lossless result, the transform worker.

Checks that passed in the same run (`evidence/headroom.json`, `checks`):

- the stored original of every sample came back byte for byte and matched its SHA-256;
- a second session could not read the first session's store;
- a view passed in again was returned untouched;
- output under 1,500 characters was printed unchanged and not stored;
- with the SDK missing, and with the hub tool timing out, the plain view was used and the
  error line was still there;
- the wrapped command's exit status was passed on and shown;
- `hr get REF --lines 1999:2001` returned exactly those three lines.

Every import of the SDK ran behind the hub worker's kernel filter, which refuses IP
sockets, and inside a network namespace with no interfaces. These results needed no network.

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
| B. With Headroom through `hr` | 24,413 tokens for the same twelve; 66.3% saved on the seven Headroom handled; 0.47 to 1.18 seconds added per command; no error line lost |
| C. With Context Mode | standalone only: search replies of 700 to 4,000 characters with exact lines; not usable in that session |
| D. With Serena | a symbol overview at about 2% of the file; a definition at 9% to 29%; 3 seconds for a cold question |
| E. All together, routed by content | not measured as one run. It is B for command output, D for code questions, ripgrep and ast-grep for search, and a script when the question is specific |

Configuration E is the one adopted, on the strength of the separate results above. An
end-to-end comparison on a whole task was not run, to keep the test itself from costing
more than it could save.
