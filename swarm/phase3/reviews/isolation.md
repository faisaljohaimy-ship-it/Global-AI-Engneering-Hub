# Isolation of stages, workers and homes: findings of lane H7

Tested black-box in `tests/test_p3_isolation.py`: the worker's command `swarm/phase3/kit3.py` run as a subprocess, with stages made by `tasks.make` and `taskqueue.create` under a temporary `SWARM_HOME`. Who may hand in whose task is not tested (another lane is changing it).

## Properties

| Property | Holds | Test |
|---|---|---|
| While stage B is open, show, read, grep, submit, test, def, callers, select, setline and answer on a task of stage A exit 2, show no text of A and change nothing | yes | StageToStage.test_open_stage_b_reaches_nothing_of_stage_a |
| The queue of the open stage hands out only its own tasks | yes | StageToStage.test_the_queue_of_the_open_stage_hands_out_only_its_own_tasks |
| A `current` file naming `../../outside` does not lead to a task outside the work folder | yes (the task needs a `.kit` state file, which is missing there) | StageToStage.test_a_stage_name_with_path_tricks_in_current_is_not_followed_out |
| Two `SWARM_HOME` folders see neither tasks nor queue of each other; work in one changes nothing in the other | yes | HomeToHome |
| Task ids with `../x`, `M-0003/..`, absolute paths, 5,000 characters, look-alike digits (fullwidth, Arabic-Indic), a Cyrillic letter, a trailing newline, empty, `.hidden`: exit 2, nothing created or changed anywhere under the home | yes | Tricks.test_task_ids_* |
| File names with `../`, `inv/..`, absolute paths, symbolic links to a file or folder outside, 5,000 characters, look-alike letters, `inv//m0.py`, a trailing newline, `.git/config`, `TASK.md`: exit 2 (read, grep, setline), nothing created or changed | yes | Tricks.test_file_names_* |
| `grep` over the whole project does not follow a symbolic link out of the task folder | yes | Tricks.test_a_symbolic_link_in_the_project_is_not_followed_by_grep |
| A NUL byte in an id or a file name is refused (exit 2) | yes. A real command line cannot carry a NUL byte at all (the operating system refuses it); the call was made inside a subprocess through `kit3.main` | Tricks.test_nul_byte_is_refused |
| No verb reads `.hidden`, `.kit` or `.queue` (read, grep, select, show with those names) | yes | Withheld.test_no_verb_names_a_withheld_folder |
| No output of show, grep, test, submit, next or status holds a string of the withheld tests that the task text does not already show | yes | Withheld.test_no_output_holds_the_withheld_tests_or_the_state |
| A hand-in whose `solution.py` is a folder is refused (exit 2) and the folder stays | yes | HandIn.test_a_solution_that_is_a_folder_is_refused |
| A hand-in whose `solution.py` is a symbolic link does not write through the link | NO, fault 1 | HandIn.test_a_solution_that_is_a_symbolic_link_is_not_written_through |
| An answer whose `ANSWER.json` is a symbolic link does not write through the link | NO, fault 2 | HandIn.test_an_answer_that_is_a_symbolic_link_is_not_written_through |
| Standard input of 5 MB to submit, setline and answer is refused (exit 2), no file grows by 100 KB, no `solution.py` is written | yes | HandIn.test_input_of_5_megabytes_* |
| Input one character over the 40,000 limit is refused and costs no attempt | yes | HandIn.test_input_just_over_the_limit_* |
| The state folders `.hidden`, `.kit`, `.queue` are not accessible to others (mode, umask 022) | NO, fault 3 | Modes.test_the_private_state_folders_are_not_readable_by_others |
| A refused call never loosens a mode | yes | Modes.test_a_refused_call_never_loosens_a_mode |
| The output of every verb for one task holds no line of another task (task text, project files) | yes | NoMixing |
| `next` gives each worker the text of its own task only | yes | NoMixing.test_next_gives_each_worker_its_own_task_text_only |

## Open faults

1. A link already lying at `solution.py` in a task folder is written through: the hand-in overwrites the file it points to. File and function: `swarm/phase2/kit.py`, `submit` (`(folder / "solution.py").write_text(...)`). A worker cannot make a link (its only tool is `swk`); the risk is a host-side or earlier step that leaves one. Repair: refuse when the path is a link (`is_symlink()`), or open with `O_NOFOLLOW`.
2. The same for `ANSWER.json`. File and function: `swarm/phase2/kit.py`, `answer`.
3. The folders `.hidden`, `.kit` and `.queue` (and the task folders, the files in them) are made with the default mode (0755 and 0644 under umask 022), so another user of the machine can read the withheld tests. Files: `swarm/phase2/tasks.py` `make`, `swarm/phase3/taskqueue.py` `create`; and `swarm/phase2/kit.py` `emit`, which rewrites the state file with the default mode. Repair: create them with mode 0700 and files with 0600, or make `SWARM_HOME/p3` itself 0700 when it is made (not tested here: the stage setup of `stage3.py` was not read by this lane, so whether the parent folder is closed there is unknown).

## Limits of this review

- A task folder that is itself a link (replaced by the host) is followed by `show`; the test only records that it answers. A worker cannot make it.
- Not tested: who may hand in whose task; a worker running as another user.
- Timing: the file runs in about 21 seconds here (each call starts a new interpreter); that is a measurement of one run on this machine.
