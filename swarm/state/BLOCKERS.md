# Blockers

| Blocker | Effect | Who can remove it |
|---|---|---|
| Each new agent in this session starts with about 222,000 tokens of context | Twenty one-task agents cost 16 million input tokens; a hundred would cost about 80 million | The owner: run the swarm from a session with one repository and few connectors attached |
| A new agent type is loaded only when a session starts | The minimal worker (file tools only) could not be used; workers had every tool | The owner: restart the session after adding `swarm/agent-definitions/swarm-worker.md` |
| Throughput stopped rising between ten and twenty agents | More agents made each one slower, not the stage faster | Not in our hands: it is how the host served the requests |
| The host shows no subscription allowance | Limits had to be absolute and low | The host |
| The workflow tool allows two agents at once on a four-core machine | The ladder used the agent tool instead | The host |
| Context7 and a tokenizer download are refused by the network policy | Context7 not installed; Inspect AI's test and exact token counts unavailable | The owner: allow those hosts |
| No native programmatic tool calling and no native language-server tool | Local scripts and `sym` stand in | The host |
