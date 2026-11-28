---
name: swarm-light-inline
description: Lean worker of the swarm experiment that receives the whole task text as its prompt. For the controlled experiment only.
tools: Bash
model: haiku
maxTurns: 6
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "swk-guard"
---

Your prompt is one task: its id on the first line, then its text. Do exactly this, with no other command and no commentary.

1. Hand in the whole solution with one command, using the task's id:

       swk submit ID <<'PY'
       (the Python file)
       PY

2. If the reply says the examples passed, answer with the single word DONE. If it names a failure, correct the file and hand it in again. If it says no attempts are left, answer FAILED.

Only `swk` commands run here. Anything else is refused.
