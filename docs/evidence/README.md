# Evidence files

Each file here records one run: what was run, where, and what came back. A dated file
describes the host and the revision it was made on, not the current state of every host.

## Current activation state

`gaie-20-layers/activation.json` is the receipt for what runs on the host that generated it:
the priority tools in `activation/tools.json`, the Headroom SDK, every registered engine
through `python3 hub.py invoke`, the wave-2 engines through their own entry points, and the
GAIE skills. It is written by `scripts/activation_receipt.py`; the command that regenerates it
is at the top of that script. `tests/test_activation_receipt.py` binds it to the generator,
the locks and its schema.

## Dated history

These two files are kept exactly as they were measured. They are history, not current state:

| File | What it records | Why it is not current |
|---|---|---|
| `capability-activation-2026-11-28.json` | The priority-tool run of an earlier session on 2026-11-28 (the receipt `activation/tools.json` points to). | It was made on another host. The tools section of `gaie-20-layers/activation.json` holds the results on the current host. |
| `2026-11-28-operational-capability-validation.json` | The validation recorded for release tag `engineering-os-v0.1.3`. | Several versions it names (for example pydantic-ai, inspect-ai, Context7, Chrome DevTools MCP, ffmpeg, node, ripgrep) match neither the committed locks nor the current host. |

`hub.py capabilities` and `hub.py motions` print values recorded in the catalogue (such as
`installed`, `operational`, `runtime_verified`, `live_recheck_performed`). They are not host
detection and are not evidence that something runs on a given host.
