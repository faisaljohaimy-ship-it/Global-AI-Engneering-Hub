---
name: gaie-audit
description: GAIE read-only engineering and security audit of a project — no changes made. Use when the owner asks to audit, inspect, check, review or assess a project («افحص سديد», «دقق», «راجع», "audit Sadeed", "inspect"), or when the router returns engine AUDIT.
argument-hint: "[project]"
allowed-tools: Read, Grep, Glob, Bash
---

This skill is read-only. Do not edit, create or delete project files, commit, push,
run migrations, deploy, or mutate any provider. Commands may only read or run tests
and builds that do not change tracked files or remote state.

1. If no router plan is in context, run `gaie-master-router` first; continue only
   when it returns `engine: AUDIT` with a resolved target.
2. Run the inventory (`hub.py inventory <checkout>` or `gaie_inventory.py`) and
   `hub.py health --project <checkout>`; for hub-linked projects also
   `hub.py verify <checkout> --strict`.
3. Review, in proportion to the project: architecture and dependencies; security
   (authentication, authorization, RLS or equivalent, secrets, input validation,
   dependency advisories, prompt-injection exposure); quality (tests, CI, dead code,
   broken routes or APIs, duplicates); performance (bundle, queries, media weight,
   Core Web Vitals where measurable); interface, accessibility, Arabic and English;
   media and motion; integrations; deployment and rollback.
4. Use `security-review` and `chromium-engineering` when their checks apply.
5. Report findings by severity with file references, evidence, root cause where
   known and a recommended fix. Separate what was measured from what was only read.
   State what could not be checked. Save the result to project memory as a
   `test-result` entry. Fixing is a separate, owner-requested `gaie-upgrade` run.
