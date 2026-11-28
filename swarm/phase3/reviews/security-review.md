# Security review of the worker's path (lane H11)

Scope: `phase2/guard.py`, `phase2/kit.py`, `phase3/kit3.py`, `phase3/taskqueue.py`, `phase3/compact.py` read as a worker that can only issue shell calls passing `guard.allowed`; `phase3/lane_guard.py` read as a development agent. Not reviewed: `hook.py`, `cage.py`. Nothing was changed outside the two files of this lane.

Every finding has a proof in `tests/test_p3_review_security.py`. Run all: `python3 -m unittest tests.test_p3_review_security`. A finding is an `@unittest.expectedFailure` test: when it is fixed the test reports "unexpected success" and the marker is to be removed. Severity: high = a worker reads or changes what is not its own; medium = denial of service or waste; low = hardening.

## Findings

### F1 (high) A worker can read the withheld answer of its own large task
File and function: `phase2/kit.py` `setline` and `test`; `workload.isolated`.
`setline` accepts any one line that parses as Python into `inv/mN.py`, with no screening (`workload.inspect` runs only in `submit`). `swk test` imports that module in a subprocess that runs as the same user, with the task folder as working directory. A line such as `raise AssertionError(open('../.hidden/ID.json').read())` makes the unittest error output print `.hidden/ID.json`, which holds `truth`: the whole expected answer (fixed function, callers, failed event ids, error code). Observed: the full truth appeared in `swk test` output in a lean stage. The same line can read or write any other task's folder, `.kit`, `.queue` and `.hidden` of the stage.
Reproduce: `python3 -m unittest tests.test_p3_review_security.WorkerFaults.test_a_changed_module_cannot_print_the_withheld_truth` (the test fails as expected).
Smallest fix: run `swk test` through `cage.run` (another user, no read access to `.hidden`, `.kit`, `.queue`) with only the task folder visible; failing that, move `.hidden` and `.kit` to a folder mode 0700 owned by the orchestrator. Also run `workload.inspect` on the line given to `setline`. State this limit in the runbook until done.

### F2 (high) Any worker can act on any task: nothing ties a caller to the task it claimed
File and function: `phase2/kit.py` `locate`; `phase3/kit3.py` `submit`.
`locate` only checks that the id is in the open stage. A worker may `show`, `read`, `setline`, `answer` and `submit` a task claimed by another. In `kit3.submit` the queue is released in the name of the holder, so one worker's passing hand-in settles another worker's task, and failing hand-ins use up the holder's three attempts and overwrite its `solution.py`. Proof: `w1` claims a task, a call naming it from nobody in particular raises `attempts` from 0 to 1.
Reproduce: `python3 -m unittest tests.test_p3_review_security.WorkerFaults.test_a_worker_cannot_use_a_task_it_does_not_hold`.
Smallest fix: the hand-in ticket of the other lane, checked in `locate` for every verb that takes an id, with a ticket of at least 64 random bits stored in `.queue/claimed/ID` and compared in constant time; refuse without it. Without a queue (second-phase stages) the stage has one worker per task and is not exposed.

### F3 (medium) Worker names are not authenticated: batch and impersonation
File and function: `phase3/kit3.py` `next_task`, `phase3/taskqueue.py` `claim`.
`swk next NAME` takes any name. One worker can fill another's batch (`swk next victim`; the victim then gets nothing) and can beat the batch by changing its name each call, taking tasks that other workers need while each claim holds for the lease.
Reproduce: `...WorkerFaults.test_a_worker_cannot_fill_another_workers_batch` and `...test_a_worker_cannot_beat_the_batch_with_a_new_name`.
Smallest fix: the orchestrator assigns the name and a secret with the worker's first `swk next` (the ticket), and later `next` calls must present it. Cap the number of distinct names by the planned worker count.

### F4 (medium) Uncaught exceptions in `answer` print a traceback
File and function: `phase2/kit.py` `answer`, `main`.
`[[[[...` of 19,000 characters raises `RecursionError`; a `direct_callers` list of objects makes `sorted` raise `TypeError`. `main` catches only `OSError`, `ValueError`, `KeyError`: the worker gets a traceback with file paths of the host, and the call is not counted.
Reproduce: `...test_deeply_nested_answer_is_refused`, `...test_unsortable_answer_is_refused`.
Smallest fix: add `RecursionError` and `TypeError` to the caught tuple in `main`, and require the list items to be strings or ints.

### F5 (medium) Counters are rewritten in place without a lock
File and function: `phase2/kit.py` `emit`, `submit`.
`emit` reads the state, changes it and `write_text`s it (truncate, then write). Two calls on one task (made possible by F2, or by a worker's parallel calls) lose counts, including `attempts`, and a reader between truncate and write sees an empty file and answers `refused: JSONDecodeError`. Proof is by construction (the state is written in place); a race is not reproduced here.
Reproduce: `...test_state_is_replaced_not_rewritten_in_place`.
Smallest fix: write a temporary file in the same folder and `os.replace` it; hold `fcntl.flock` on a lock file during read-change-write of `.kit/ID.json`.

### F6 (low) A claim with no lease is never reclaimed
File and function: `phase3/taskqueue.py` `claim` and `reclaim`.
`claim` renames the file and writes the lease after. A process killed between the two leaves `claimed/ID` empty; `reclaim` skips it because no time is written, so the task is lost for the stage and `status` hides it from `oldest_claim_age`. A killed worker at the wrong moment is likely over 1,000 workers.
Reproduce: `...test_a_claim_without_a_lease_is_reclaimed`.
Smallest fix: write the lease into the `waiting` file's replacement first (write `claimed/ID.tmp`, then rename into `claimed/ID`), or let `reclaim` use the file's modification time when no lease is written.

### F7 (high for a development agent, by the net's own words) `lane_guard.visible` hides a shell fed by a here-document
File and function: `phase3/lane_guard.py` `visible` and `WRITES_A_FILE`.
Any line starting with `cat` and holding `<<TAG` hides its body, including `cat <<'EOF' | sh`. The body then runs unjudged: `curl`, `git push` and the rest.
Reproduce: `...LaneGuard.test_a_here_document_piped_to_a_shell_is_judged`.
Smallest fix: hide the body only when the line matches `cat >[>] PATH <<TAG` with nothing after the tag; keep everything else in view.

### F8 (medium) `DENIED` names words, not effects
File and function: `phase3/lane_guard.py` `DENIED`, `allowed`.
Each of these passes: `/usr/bin/curl x`, `bash -c 'curl x'`, ``echo `curl x` ``, `timeout 5 curl x`, `nohup curl x`; network by `python3 -c` (urllib), `socat`, `telnet`, `rsync`, `git ls-remote`, `perl`; `git -c alias.p=push p`, `git --no-pager push`, `git config alias.p push`, `git --git-dir=.git push`; `export -p`, `declare -x`, `set`, `python3 -c 'print(os.environ)'`; and `echo x > /etc/motd` (no Bash path is checked). The file's docstring says it is a net, which is true; these show how coarse it is.
Reproduce: `...test_network_command_by_path_or_wrapper`, `...test_network_by_another_tool`, `...test_git_alias_and_option_forms`, `...test_other_environment_listings`, `...test_redirection_outside_the_lanes`.
Smallest fix: the pattern cannot be made complete. Run development agents' shells without a network (`unshare -n`, which `workload.isolated` already uses) and with the worktree as the only writable folder; keep the pattern as a hint. Until then do not claim that the net stops network or outside writes.

### F9 (low) Glob with no path takes an absolute pattern
File and function: `phase3/lane_guard.py` `allowed`, tools `Grep`/`Glob`.
A search with no `path` is let through "starting in the repository", but a Glob `pattern` of `/root/.ssh/*` or `../../../etc/*` lists any folder, which the Read rule was written to prevent. Names only, not contents.
Reproduce: `...test_glob_pattern_cannot_leave_the_repository`.
Smallest fix: for Glob refuse a pattern that is absolute or holds `..`.

## Checked and found sound (a normal test each, unless marked)

- `guard.allowed`: a table of 19 shapes is refused (chaining by `;`, `&&`, `|`, `$()`, backticks, redirection, double quotes, a second here-document, text after the closing tag, a tag repeated in the body, `submit` with no here-document, environment prefixes, comments, trailing backslash). The usual shapes pass. Test: `GuardHolds`.
- Path arguments (`read`, `grep`, `select`, `setline`) with `..`, absolute paths, `inv/..`, and ids with a slash are refused, and the reply does not hold the host path. The word set allows `.` and `/`, so `kit.inside` and `PROJECT_FILE` are what hold, not the gate. Test: `KitHolds.test_paths_cannot_leave_the_project`.
- A catastrophic regular expression on a line the worker made (`(a|aa)+$` on a 51-character line) is stopped by the 5 s alarm, because the regular-expression engine lets the handler run. Test: `test_a_slow_regular_expression_is_stopped` (run with the limit set to 1 s).
- `swk answer` replies the same whatever the answer, so it cannot be used as a judge; the worker's `.kit` state holds no `truth`, `suite` or `fingerprint`. Tests in `KitHolds`.
- Two or more workers drawing in parallel (8 threads, 40 tasks) never get one task twice and none is lost. Test: `test_no_two_workers_get_one_task`. The rename is atomic; `release` re-checks the holder after the move.
- `compact.render` is a plain string replace and one linear regex over text the worker does not write; no finding.
- `lane_guard`: Write/Edit outside the lanes, Read outside the repository and the lanes, other tools, and the listed commands (`curl`, `sudo`, `git push`, `git -C x push`, `git -c a=b fetch`, `env`, `printenv`, `/proc/self/environ`, package managers, `git checkout`, `~/.ssh`) are refused. Test: `LaneGuard`.

## Not checked

- `hook.py` and `cage.py` (other lanes); whether the host really runs `guard` for each worker call.
- A real race between two processes on `emit` or `claim` (the claim batch check has a window between `_net` and the append, so two simultaneous `swk next` of one name can exceed the batch by one; reasoned, not run).
- `workload.inspect` and `tasks.run_suite` (the screen and the run of a submitted solution, which also runs as the same user: F1 applies to it if the screen can be bypassed); the Headroom front end in `kit.test`; timing differences that might tell a worker about the hidden suite (the replies do not depend on the hidden data in anything read, but no timing was measured); disk or memory use by a worker that writes many files (only `solution.py`, one line per `setline` and `ANSWER.json` can be written by the verbs).
- Behaviour after the hand-in tickets arrive: F2 and F3 are written for the code as it is.

## What was done about each finding

Added by the session that set the review, after it. The review above is left as it was written.

| Finding | State | Where | Proof |
|---|---|---|---|
| F1 withheld answer readable through `setline` and `test` | closed | `kit3.main` runs worker-written code through `handin.isolated`: another user, a copy of the task folder only. `tasks.make` and `taskqueue.create` make `.hidden`, `.kit` and `.queue` for their owner only. The run's plan refuses to open a stage where the cage cannot be had. | `test_a_changed_module_cannot_print_the_withheld_truth`, `tests/test_p3_handin.py` |
| F2 any worker can act on any task | closed where there is a queue; found afterwards where there is none | A stage with a queue runs `next` and `submit` only, and a hand-in needs the ticket of its claim. In a stage given by id, `stage3.finish` reads the records: a command on another worker's task ends the run. | `test_a_worker_cannot_use_a_task_it_does_not_hold`, `tests/test_p3_tickets.py`, `RunTests.test_a_worker_given_a_task_by_id_that_acts_on_anothers_task_ends_the_run` |
| F3 worker names not authenticated | closed through the gate | `hook.py` lets each agent the host names draw a first task once and never under a name it chose; a later draw needs the ticket of the worker's last task; the queue has as many places as the stage has agents. | `test_a_worker_draws_its_first_task_once_and_never_under_a_name_it_chose`, `test_a_worker_cannot_beat_the_batch_with_a_new_name`, `test_a_worker_cannot_fill_another_workers_batch` |
| F4 tracebacks from `answer` | closed | `kit.main` and `kit3.main` answer every fault with `refused` and its kind; list items of an answer must be names or numbers. | `test_deeply_nested_answer_is_refused`, `test_unsortable_answer_is_refused` |
| F5 state rewritten in place | closed | `kit.keep` writes a file beside the state and replaces it whole. No lock: two calls on one task can still lose a count, and tickets now keep a second caller away. | `test_state_is_replaced_not_rewritten_in_place` |
| F6 a claim with no lease is never reclaimed | closed | `taskqueue._made` takes the file's own time when no lease is written. | `test_a_claim_without_a_lease_is_reclaimed` |
| F7 a here-document piped to a shell is hidden | closed | `lane_guard.WRITES_A_FILE` hides a body only when `cat` writes it to a named file and nothing else is on the line. | `test_a_here_document_piped_to_a_shell_is_judged` |
| F8 the net names words, not effects | open, by nature | Five proofs stay marked as expected failures. The net is a list of refused commands. Development agents are not the experiment's workers, and their work is joined only after a check of the paths they changed. | `LaneGuard`, five expected failures |
| F9 Glob with an absolute pattern | closed | `lane_guard.allowed` refuses a pattern that is absolute or holds `..`. | `test_glob_pattern_cannot_leave_the_repository` |
