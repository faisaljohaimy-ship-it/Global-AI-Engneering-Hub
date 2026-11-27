# Implementation plan

1. Add a versioned component manifest mapped one-to-one to catalog IDs.
2. Implement the initial motion batch and a local-only Motion Lab.
3. Add deterministic Remotion/Three adapters without importing optional engines.
4. Harden JSON and CSS parsing, add security and byte-budget gates.
5. Add shared discovery and compare-and-swap pin update commands.
6. Record sanitized integration and recovery evidence.
7. Rebuild onboarding branches from each repository's current default branch.
8. Run local and browser checks, open a PR, wait for CI, then merge.
