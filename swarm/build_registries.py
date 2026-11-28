#!/usr/bin/env python3
"""Write swarm/capabilities.json and swarm/agents.json from the tables below.

    python3 swarm/build_registries.py [--check]

The hundred capabilities are the owner's list, in the owner's order. They are not a
hundred packages: each row says what kind of thing it is (an outside tool, something the
agent host does, a local script, a hub component or a working rule) and how far it got
here. The status words are:

    USED            used for real work in the recorded session or by agents in the experiment
    TESTED          ran and passed a test, not yet used for real work
    AVAILABLE       exists in the hub or on the machine; not exercised here
    HOST            done by the agent host; observed, not controlled by these scripts
    RULE            a working rule with no software of its own
    BLOCKED         could not run here, with the reason
    NOT IMPLEMENTED nothing here does this yet

--check fails if the committed files differ from what the tables produce.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = "skills/ultra-context-optimization"

GROUPS = {
    "A": "Context compression", "B": "Context isolation", "C": "Semantic code intelligence",
    "D": "Knowledge intelligence", "E": "Cache and reuse", "F": "Tool execution",
    "G": "Model and reasoning", "H": "Multi-agent", "I": "Incremental engineering",
    "J": "Memory and resource governance",
}

# name | kind | what does it here | how to call it | status | task classes that need it
CAPABILITIES = """
Headroom Compression|tool|Headroom through hr (0.44.0) and the hub tool tools/headroom_context.py (0.45.0)|hr run -- CMD|USED|log,json,search
Reversible Context Compression|script|hr keeps every original by SHA-256 and returns it on request|hr get REF --all|USED|log,json,search
JSON Structural Compression|tool|Headroom's JSON transform: arrays become a table with every row|hr put --kind json FILE|TESTED|json
Repetitive Log Compression|tool|Headroom's log transform, called directly by hr|hr run -- TESTCMD|USED|log
Tool Output Compression|script|hr wraps a command and prints a view of its output|hr run -- CMD|USED|log,json,search
Selective Context Retrieval|script|hr get by line range or pattern; Read with offset and limit|hr get REF --grep RE|USED|log,json,search,code
Context Fidelity Verification|script|hr appends every error line a view lost; hr verify rechecks the checksum|hr verify REF|USED|log,json
Context Deduplication|script|hr never compresses a view twice; the store is content-addressed|automatic in hr|TESTED|log,json
Context Budget Management|script|bands in the skill; swarm/protect.py holds the experiment's limits|python3 swarm/protect.py|USED|orchestration
Adaptive Compression Routing|script|hr picks the transform from the command and the shape of the text|automatic in hr|USED|log,json,search
Context Mode|tool|context-mode 2.1.10 as a standalone stdio server on its own Node 24|context-mode-server via mcp_probe.py|TESTED|docs
Local Output Indexing|tool|Context Mode ctx_index (full-text index per project)|ctx_index|TESTED|docs
Selective Log Retrieval|script|hr get --grep and --lines on the stored original|hr get REF --lines A:B|USED|log
External Context Storage|script|~/.gaie-store per session and log files outside the conversation|automatic in hr|USED|log,json
Search-based Context Recovery|script|hr get --grep; Context Mode ctx_search where it is installed|hr get REF --grep RE|USED|log,docs
Scoped Document Retrieval|host|Read with offset and limit; search with a result limit|Read, Grep|USED|code,docs
Native Context Compaction|host|the host compacts the conversation by itself; observed twice in the recorded session|none: host decides|HOST|orchestration
Deferred Context Loading|host|tool definitions are loaded only when asked for|ToolSearch|USED|orchestration
Progressive Disclosure|rule|a short SKILL.md with references read on demand|read references/ when needed|USED|docs
Context Lifecycle Management|rule|the bands in the skill; compaction and clearing are user commands|none|RULE|orchestration
Serena|tool|serena-agent 2.1.0, one question per run through sym|sym overview FILE|USED|code
TypeScript LSP|tool|typescript-language-server, started by Serena|sym def NAME FILE.ts|TESTED|code
Python LSP|tool|pyright, started by Serena; pyright CLI is also on the machine|sym refs NAME FILE.py|USED|code
JavaScript Language Intelligence|tool|the TypeScript server reading .mjs modules through Serena|sym overview FILE.mjs|TESTED|code
ast-grep|tool|ast-grep 0.51.2|ast-grep run -p PATTERN -l LANG|USED|code,search
Tree-sitter|tool|inside ast-grep and Repomix; the Python binding 0.26.1 parsed one module and counted its 33 functions, the same as Python's own parser|python -c 'import tree_sitter'|TESTED|code
Ripgrep|tool|ripgrep 14.1.0 and the host's search tool|rg -n PATTERN|USED|search,code
Symbol-level Retrieval|tool|sym def returns one definition instead of a file|sym def NAME FILE|USED|code
Reference Graph Analysis|script|sym refs; swarm/bench.py writes a call index for its project|sym refs NAME FILE|USED|code
Dependency-aware Code Retrieval|script|the hub copies a motion with exactly the modules it imports (PR #16)|python3 hub.py register PROJECT --capability engine-motion:ID|TESTED|code
Context7|tool|not installed: its hosts are refused by the session's network policy|none|BLOCKED|docs
Version-specific Documentation Retrieval|script|read the pinned version from the lock, then inspect the installed package|python -c 'import inspect, PKG'|USED|docs
Selective API Documentation|script|print one signature or one help section, not a manual|python -c inspect.signature|USED|docs
Repomix Scoped Analysis|tool|repomix 1.19.0 with --include and --compress|repomix --include GLOB --compress|TESTED|code,review
Local Knowledge Indexing|script|a per-project call index given to an agent as INDEX.json; Context Mode's index|python3 swarm/bench.py build DIR|USED|code
Verified Documentation Cache|none|nothing here caches outside documentation|none|NOT IMPLEMENTED|docs
Architecture Knowledge Retrieval|hub|hub.py architecture and ARCHITECTURE.md|python3 hub.py architecture|AVAILABLE|architecture
Skill Discovery|hub|hub.py recommend scans skills/*/SKILL.md|python3 hub.py recommend QUERY|USED|orchestration
On-demand Skill Activation|host|a skill's text is loaded when it is invoked|Skill tool|USED|orchestration
Shared Knowledge References|script|agent packets name shared files by path instead of copying them|packet field shared|USED|orchestration
Prompt Caching|host|done by the host; read and write counts are in every agent's record|none: measured by swarm/measure.py|HOST|orchestration
Stable Context Prefixes|rule|every worker got the same instructions first; even so the host wrote a fresh cache of about 182,000 tokens for each agent|packet layout|RULE|orchestration
Content Fingerprinting|script|SHA-256 of originals, of motion sources and of tasks|automatic|USED|orchestration
Git Blob-based Reuse|script|the hub reads files at a revision from Git objects|hublink.read(revision, path)|TESTED|code
File Checksum Verification|hub|hub.py verify --strict and hr verify|python3 hub.py verify --strict|USED|release
Dependency Lockfile Caching|script|bootstrap skips a tool whose lock has not changed; uv reuses downloads|skills/ultra-context-optimization/scripts/bootstrap.sh|USED|setup
Build Cache Optimization|none|the hub has no build step to cache|none|NOT IMPLEMENTED|build
Test Result Reuse|script|motion evidence is bound to source hashes, so unchanged motions are not re-run (the motion package, PR #16)|node packages/motion-engines/verify/browser.mjs --module KEY|USED|test
Cache Invalidation|script|evidence is void when its source or the core changes; lock stamps|automatic|TESTED|test
Shared Artifact Reuse|script|one tool install under ~/.gaie-tools serves every agent|GAIE_TOOLS|USED|setup
Programmatic Tool Calling|host|the host exposed no native programmatic tool calling; local scripts stand in|none|BLOCKED|orchestration
Deterministic Local Scripts|script|measuring, checking, generating and scheduling are scripts, not model calls|python3 swarm/*.py|USED|orchestration
Batched Tool Execution|host|several tool calls in one message and several steps in one command|parallel tool calls|USED|orchestration
Tool Search|host|the host's on-demand tool lookup|ToolSearch|USED|orchestration
Deferred MCP Loading|host|connector tool definitions stay unloaded until needed|ToolSearch|USED|orchestration
Intelligent Output Filtering|script|commands print the answer, not the raw output|pipe to a filter or hr|USED|log,json
Adaptive Tool Routing|script|the table in the skill; swarm/route.py picks capabilities for a task class|python3 swarm/route.py CLASS|USED|orchestration
Tool Call Deduplication|script|the scheduler drops duplicate tasks; measure.py counts repeated reads|python3 swarm/scheduler.py simulate|TESTED|orchestration
Structured Result Extraction|script|agents answer in a fixed JSON file that a checker reads|ANSWER.json|USED|orchestration
Minimal Tool Response Policy|rule|an agent's final reply is one word; its work is in files|packet rule|USED|orchestration
Adaptive Model Selection|host|a model can be named for each agent|agent model option|USED|orchestration
Adaptive Reasoning Allocation|host|a reasoning effort can be named for each agent|agent effort option|USED|orchestration
Complexity-aware Routing|script|swarm/route.py maps a task class to a model tier and an effort|python3 swarm/route.py CLASS|USED|orchestration
Task Classification|script|swarm/route.py classes: routine, investigate, design, security, review|python3 swarm/route.py CLASS|USED|orchestration
Resource-aware Model Routing|hub|engineering_os/model_router.py; it needs evaluator receipts that do not exist yet|python3 -m engineering_os.model_router|AVAILABLE|orchestration
Usage-aware Scheduling|script|swarm/protect.py decides between stages whether to go on|python3 swarm/protect.py|USED|orchestration
Inference Loop Optimization|rule|a packet holds everything a worker needs, so it asks for nothing|packet layout|USED|orchestration
Model Roundtrip Reduction|rule|the same; roundtrips per task are measured|measured by swarm/measure.py|USED|orchestration
Cost-aware Task Allocation|script|swarm/route.py gives routine work the lightest tier|python3 swarm/route.py routine|USED|orchestration
Performance-based Model Selection|none|no comparison of models on the same tasks was kept as a selection rule|none|NOT IMPLEMENTED|orchestration
Adaptive Agent Scheduling|script|swarm/scheduler.py plans waves from the task graph|python3 swarm/scheduler.py simulate|TESTED|orchestration
Dynamic Concurrency|script|the scheduler plans to any limit; the real stages used the fixed sizes of the ladder|scheduler --limit N|TESTED|orchestration
Task Ownership|hub|engineering_os.orchestration: claim with a lease, one owner per task|TaskStore.claim|USED|orchestration
Task Deduplication|script|tasks with the same fingerprint are scheduled once|scheduler dedup|TESTED|orchestration
Dependency-aware Task Graph|script|tasks run only after the tasks they depend on|scheduler waves|TESTED|orchestration
Git Worktree Isolation|host|each line of work, and each benchmark agent, has its own worktree|git worktree add|USED|orchestration
Shared Context References|script|packets point at shared files and indexes by path|packet field shared|USED|orchestration
Specialized Agent Routing|script|the scheduler gives a task to an agent of the matching team and role|scheduler assign|TESTED|orchestration
Cross-Agent Handover|hub|TaskStore handover and submit with receipts; pull-request descriptions|TaskStore.handover|USED|orchestration
Conflict Prevention|hub|one active task per branch; every agent writes only in its own folder|TaskStore.claim|USED|orchestration
Incremental Testing|rule|run the test for what changed first, the full suite before a merge|unittest -p, --module KEY|USED|test
Affected-module Detection|none|nothing here maps a change to the tests it affects|none|NOT IMPLEMENTED|test
Dependency-aware Testing|none|the same gap|none|NOT IMPLEMENTED|test
Change-aware Builds|none|the hub has no build step|none|NOT IMPLEMENTED|build
Selective Regression Testing|script|the browser harness runs one module or one motion (the motion package, PR #16)|node packages/motion-engines/verify/browser.mjs --id ID|USED|test
Reproducible Build Artifacts|script|hash-checked locks and seeded generators give the same files again|locks/, --seed|USED|setup
Deterministic Quality Gates|hub|unit tests, the secret scan, the dependency scan and the harness|scripts/security_scan.py scan|USED|release
Parallel Independent Testing|script|the checker runs each agent's hidden tests in its own process|python3 swarm/workload.py check|USED|test
Incremental Static Analysis|script|the checker parses each solution and rejects imports outside a short list|python3 swarm/workload.py check|USED|security
Root-cause Debugging|rule|reproduce, isolate, fix, add a regression test|none|RULE|debug
Persistent Task State|script|swarm/state/TASK_STATE.json and the TaskStore file|swarm/state/|USED|orchestration
Engineering Checkpoints|hub|TaskStore.checkpoint and one commit per finished stage|TaskStore.checkpoint|USED|orchestration
Architecture Decision Records|rule|decisions are written in swarm/state/ENGINEERING_HANDOVER.md|swarm/state/|USED|architecture
Session Recovery|hub|TaskStore.restore into an empty store reproduces the state|TaskStore.restore|TESTED|orchestration
Lightweight Lifecycle Hooks|none|none installed: a hook on every tool call costs more than calling hr when needed|none|NOT IMPLEMENTED|orchestration
Token Measurement|script|swarm/measure.py sums the usage the API reported for every agent|python3 swarm/measure.py|USED|orchestration
Cache Efficiency Measurement|script|cache reads as a share of all input, from the same records|python3 swarm/measure.py|USED|orchestration
Agent Resource Monitoring|script|a sampler records load, memory and the host process during a stage|python3 swarm/measure.py sample|USED|orchestration
Net Efficiency Benchmarking|script|speedup, efficiency and tokens per verified task|python3 swarm/measure.py|USED|orchestration
Automatic Budget Protection|script|swarm/protect.py stops the ladder when a limit is reached|python3 swarm/protect.py|USED|orchestration
""".strip().splitlines()

# team | hub role | model tier | effort | skills | capability numbers every member gets
TEAMS = [
    ("Architecture intelligence", "architecture", "top", "high", ["system-builder", "saas-platform"], [37, 28, 34, 93]),
    ("Software engineering", "development", "middle", "medium", ["engineering-sdk", "project-onboarding"], [21, 25, 27, 81]),
    ("Context and resource intelligence", "performance", "middle", "medium", ["ultra-context-optimization", "headroom-context-engineering"], [1, 6, 96, 100]),
    ("AI and agent engineering", "development", "middle", "medium", ["ai-integration", "priority-capability-selection"], [59, 61, 62, 64]),
    ("Database and data intelligence", "database", "middle", "medium", ["security-review"], [3, 52, 87, 43]),
    ("Cinematic and GPU engineering", "cinematic", "middle", "medium", ["universal-motion", "chromium-engineering", "digital-motion", "cinematic-production"], [48, 85, 30, 25]),
    ("Defensive security and governance", "security", "top", "high", ["security-review"], [87, 89, 45, 80]),
    ("Quality and performance", "testing", "light", "low", ["chromium-engineering"], [4, 81, 85, 88]),
    ("Cloud and DevOps", "devops", "light", "low", ["release-engineering"], [46, 86, 87, 92]),
    ("Research and engineering evolution", "research", "middle", "medium", ["hub-capabilities", "priority-capability-selection"], [38, 32, 33, 99]),
]

# ten members per team: role | what the agent may be asked to do | extra capability numbers
MEMBERS = """
Enterprise platform architect|decide module boundaries and interfaces for one named system|75
Integration architect|design one contract between two named services|40
Data architect|shape entities, ownership and retention for one bounded context|43
Frontend architect|set structure, routing and state rules for one web application|16
Security architect|draw trust boundaries and the checks at each one|80
Multi-agent systems architect|split one goal into owned tasks with dependencies|75
Performance architect|set budgets and the measurements that prove them|99
Reliability architect|define failure modes, recovery and what is checkpointed|92
Motion platform architect|decide which engine serves which kind of motion|30
Architecture reviewer|review one design against its stated constraints|34
Frontend engineer|implement one component with its states and tests|16
Backend engineer|implement one endpoint or job with validation and tests|52
Full-stack engineer|carry one small feature from interface to storage|6
Mobile engineer|implement one screen with offline and small-screen behaviour|16
API engineer|write one typed interface with its error cases|59
Library engineer|implement one pure function or class from a written specification|52
Refactoring engineer|change structure without changing behaviour, proven by tests|29
Bug-fix engineer|find the cause of one failing test and fix it with a minimal change|90
Internationalisation engineer|add right-to-left and bilingual behaviour to one view|16
Code reviewer|review one diff for correctness and report findings with evidence|34
Context compression engineer|choose and verify the view for one kind of large output|7
Retrieval engineer|answer one question from a large file by fetching only what is needed|13
Cache engineer|measure cache reads and writes for one workload and explain them|97
Token accountant|sum reported usage for a set of agents and check the totals|96
Budget guard|evaluate the stop rules for one stage and say go or stop|100
Packet designer|write the smallest packet that lets a worker finish one task|77
Roundtrip analyst|count model roundtrips and tool calls and find the avoidable ones|68
Output filter engineer|turn one noisy command into one that prints only the answer|56
Index builder|build a shared symbol or call index for one project|35
Efficiency benchmarker|compare two configurations on the same tasks|99
Agent designer|define one agent: role, tools, limits, output contract|78
Tool-calling engineer|write one typed tool with authorisation and time limits|59
Retrieval-augmentation engineer|build one retrieval step with stated sources and limits|35
MCP engineer|start one MCP server and prove its tools answer|11
Evaluation engineer|write one offline evaluation with a pass and a fail case|88
Prompt engineer|write one instruction set and test it against fixed cases|42
Model router engineer|map task classes to model tiers with the evidence for each|63
Structured-output engineer|define one output schema and reject what does not fit|59
Workflow engineer|write one orchestration script with a defined fan-out|71
Agent safety reviewer|check one agent's permissions against its task|80
PostgreSQL engineer|write one schema change with its rollback|86
Query-plan analyst|read one query plan and name the costly step|56
Row-level-security engineer|write one policy and the negative tests that prove it|87
Data-quality engineer|find the anomalous records in one synthetic data set|3
Migration engineer|order a set of migrations so each can be undone|75
Analytics engineer|compute one metric from synthetic events with a stated definition|52
Data-contract engineer|define and validate one data contract|59
Backup and recovery engineer|prove one restore from a checkpoint|94
Seed-data engineer|generate reproducible synthetic data from a seed|86
Database reviewer|review one schema for isolation and index use|34
Shader engineer|implement one fragment-shader motion that passes the harness|85
WebGPU engineer|implement one WGSL motion with a WebGL2 fallback|85
Particle-systems engineer|implement one GPU point-cloud motion|85
Typography motion engineer|implement one bilingual text motion, Arabic moved by word|16
Interface motion engineer|implement one DOM or SVG micro-interaction|85
Composition engineer|layer verified motions into one sequence|30
Render-export engineer|export one motion frame-exactly and verify the frames|52
Digital-twin engineer|load one synthetic scene with selectable overlays|35
Browser-verification engineer|run the harness for one module and read its evidence|4
Motion reviewer|look at one contact sheet and say what is blank or duplicated|34
Secret-scan engineer|scan one change for credentials and private paths|89
Dependency auditor|check one lock for advisories and unpinned entries|46
Licence reviewer|state what one licence allows for a named use|32
Permission reviewer|check one agent or script against its allowed paths|80
Isolation engineer|prove two tenants or sessions cannot read each other|87
Supply-chain reviewer|verify one install: pinned, hashed, no install script|86
Threat modeller|list the abuse cases for one feature and the control for each|93
Sandbox engineer|run one tool with no network and no inherited credentials|52
Governance recorder|record one decision with its owner and evidence|93
Security reviewer|review one diff for injection, traversal and unsafe execution|34
Unit-test engineer|write the tests for one function from its specification|88
Regression-test engineer|turn one fixed bug into a test that fails without the fix|90
Visual-test engineer|compare rendered frames of one motion across settings|85
Accessibility tester|check one view for reduced motion, contrast and labels|16
Performance tester|measure one operation and report the method with the number|99
Compatibility tester|run one check across the browsers the machine has|85
Hidden-test checker|run withheld tests against one submission and score it|88
Flaky-test analyst|decide whether one failure is in the change or in the test|90
Coverage analyst|name the behaviour that no test exercises|27
Quality gatekeeper|run the mandatory gates and report pass or fail|87
Continuous-integration engineer|add one job that runs an existing check|87
Release engineer|prepare one release note from merged changes|92
Pull-request steward|keep one pull request green and mergeable|79
Branch-hygiene engineer|merge the base into one branch and resolve conflicts|76
Lockfile engineer|regenerate one lock with hashes and a waiting period|46
Environment engineer|report what one machine supports before work starts|52
Artifact engineer|package one result with its checksum|45
Rollback engineer|write the steps that undo one change|94
Pipeline analyst|read one failed run and name the failing step|4
Deployment reviewer|check one deployment target against the project it belongs to|80
Tool scout|find one candidate tool and report its source and licence|32
Version tracker|report the newest stable release older than a waiting period|32
Skill author|write one skill with triggers, steps and limits|19
Capability reviewer|move one tool through the lifecycle with evidence|45
Benchmark designer|design one fair comparison with equal work on both sides|99
Compatibility cartographer|record which host supports which capability|52
Documentation retriever|fetch the documented behaviour for one pinned version|33
Evidence curator|keep one result with how it was measured|43
Blocker analyst|state one blocker, its cause and the owner's action|93
Methodology reviewer|check that one report claims only what was measured|34
""".strip().splitlines()

TIERS = {"light": "the lightest available model", "middle": "the middle model", "top": "the session's model"}
EFFORT_LIMITS = {"low": (12, 4000), "medium": (30, 12000), "high": (60, 30000)}


def capabilities() -> list[dict]:
    rows = []
    for number, line in enumerate(CAPABILITIES, 1):
        name, kind, does, call, status, classes = line.split("|")
        group = "ABCDEFGHIJ"[(number - 1) // 10]
        rows.append({"id": f"C{number:03d}", "group": group, "group_name": GROUPS[group], "name": name, "kind": kind,
                     "implementation": does, "invoke": None if call == "none" else call, "status": status,
                     "task_classes": classes.split(",")})
    return rows


def agents() -> list[dict]:
    rows = []
    for index, line in enumerate(MEMBERS):
        role, scope, extra = line.split("|")
        team_number, member = index // 10 + 1, index % 10 + 1
        team, hub_role, tier, effort, skills, shared = TEAMS[team_number - 1]
        reviewer = role.endswith("reviewer") or role.endswith("gatekeeper")
        roundtrips, output = EFFORT_LIMITS[effort]
        rows.append({
            "id": f"T{team_number:02d}-A{member:02d}", "team": team, "role": role, "hub_role": hub_role,
            "task_scope": scope[0].upper() + scope[1:] + ".",
            "required_capabilities": sorted({f"C{number:03d}" for number in [*shared, int(extra)]}),
            "required_skills": skills,
            "minimum_context": "Its task packet, the files the packet names, and the shared index. No other part of the repository.",
            "resource_budget": {"model": TIERS[tier], "effort": effort, "max_roundtrips": roundtrips, "max_output_tokens": output},
            "permission_boundaries": {"read": "the packet's paths only", "write": "none" if reviewer else "its own task folder only",
                                      "network": "none", "git": "no commit, push or branch change", "credentials": "none"},
            "output_contract": "A findings file in its task folder." if reviewer else "The files the packet asks for, in its task folder. Final reply: DONE or FAILED.",
            "acceptance_criteria": "A checker script accepts the output; for a review, every finding names a file, a line and the evidence.",
            "checkpoint_policy": "The orchestrator records the task as submitted with the checksum of the output before the next task starts.",
            "stop_conditions": ["the roundtrip or output limit is reached", "the same error repeats twice", "the task needs a path or permission outside its packet"],
        })
    return rows


def main() -> int:
    wanted = {"capabilities.json": {"schema_version": 1, "note": __doc__.split("\n\n")[2].strip(), "capabilities": capabilities()},
              "agents.json": {"schema_version": 1, "note": "A registry of roles. Registering an agent here starts nothing: an agent exists only while a host runs it.", "agents": agents()}}
    stale = []
    for name, data in wanted.items():
        text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
        path = HERE / name
        if "--check" in sys.argv:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8")
    if stale:
        print("stale:", ", ".join(stale))
        return 1
    statuses: dict[str, int] = {}
    for row in capabilities():
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    print(len(capabilities()), "capabilities", statuses, "|", len(agents()), "agents in", len(TEAMS), "teams")
    return 0


if __name__ == "__main__":
    sys.exit(main())
