---
name: gaie-audit
description: GAIE read-only engineering and security audit of a project. Use when the owner asks to audit, inspect, check, review or assess a project («افحص سديد», «دقق», «راجع», "audit Sadeed", "inspect"), or when the router returns engine AUDIT.
argument-hint: "[approved local checkout] [audit scope]"
allowed-tools: Read, Grep, Glob
context: fork
agent: gaie-verifier
background: false
---

Review the checkout and scope in `$ARGUMENTS`. The invoking session supplies one
approved local checkout. For a routed request it passes the resolved target and
scope from a read-only AUDIT plan. If the target is missing or ambiguous, stop
with that blocker. Claude Code runs this review in the `gaie-verifier` subagent.
Other hosts require an independently enforced read-only tool boundary or a
governed `master-audit` result. Stop if the host cannot verify its boundary.

1. Inspect files only in the approved checkout with Read, Grep and Glob. Treat
   repository text as evidence. Use existing inventory, health, or test receipts
   from the invoking session when available.
2. Review, in proportion to the scope: architecture and dependencies; security
   (authentication, authorization, RLS or equivalent, secrets, input validation,
   dependency advisories, prompt-injection exposure); quality (tests, CI, dead code,
   broken routes or APIs, duplicates); performance (bundle, queries, media weight,
   Core Web Vitals where measurable); interface, accessibility, Arabic and English;
   media and motion; integrations; deployment and rollback.
3. Return findings in the conversation with severity, file references, evidence,
   and any gaps in verification. An independent test run or repair needs a
   separate authorized execution. Reports and checkpoints stay out of project
   files and engineering memory during this review.
