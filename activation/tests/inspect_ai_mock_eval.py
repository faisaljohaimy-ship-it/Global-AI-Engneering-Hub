"""Inspect AI: run a small evaluation end to end against its built-in mock model.

Runs inside the tool's own environment. No provider is configured and no key is read.
Prints one JSON object; exit status 1 if any case fails.

Cases, from the acceptance line of the "agent-evaluation" pack: an evaluation scores a
right and a wrong answer correctly, a sample that runs past its time limit is stopped and
recorded as such, and a solver that fails is reported as an error instead of a score.
"""
import json
import sys
import tempfile
import time

import anyio
import inspect_ai
from inspect_ai import Task, eval as run_eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import match
from inspect_ai.solver import generate, solver


def mock(*answers):
    return get_model("mockllm/model", custom_outputs=[ModelOutput.from_content("mockllm/model", text) for text in answers])


@solver
def sleeper(seconds):
    async def solve(state, generate):
        await anyio.sleep(seconds)
        return state

    return solve


@solver
def broken():
    async def solve(state, generate):
        raise RuntimeError("solver failed on purpose")

    return solve


def run(task, model, **options):
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as logs:
        log = run_eval(task, model=model, display="none", log_dir=logs, log_format="json", **options)[0]
        return log, round(time.perf_counter() - started, 2)


def main():
    cases = {}
    questions = [Sample(input="What is 2 + 2? Answer with the number.", target="4"),
                 Sample(input="What is the capital of France? One word.", target="Paris")]

    log, seconds = run(Task(dataset=questions, solver=generate(), scorer=match()), mock("4", "London"))
    grades = [next(iter(sample.scores.values())).value for sample in log.samples]
    accuracy = log.results.scores[0].metrics["accuracy"].value
    cases["right_and_wrong_answers_are_scored"] = {"status": log.status, "grades": grades, "accuracy": accuracy, "seconds": seconds,
        "passed": log.status == "success" and grades == ["C", "I"] and accuracy == 0.5}

    log, seconds = run(Task(dataset=questions[:1], solver=sleeper(30), scorer=match(), time_limit=1), mock("4"))
    limit = log.samples[0].limit.type if log.samples and log.samples[0].limit else None
    cases["slow_sample_is_stopped_by_its_time_limit"] = {"status": log.status, "limit": limit, "seconds": seconds,
        "passed": limit == "time" and seconds < 15}

    log, seconds = run(Task(dataset=questions[:1], solver=broken(), scorer=match()), mock("4"), fail_on_error=True)
    message = log.error.message if log.error else ""
    cases["failing_solver_is_reported_as_an_error"] = {"status": log.status, "error": message[:60], "seconds": seconds,
        "passed": log.status == "error" and "solver failed on purpose" in message}

    passed = all(case["passed"] for case in cases.values())
    print(json.dumps({"tool": "inspect-ai", "version": inspect_ai.__version__, "model": "mockllm/model",
                      "status": "passed" if passed else "failed", "cases": cases}, indent=1))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
