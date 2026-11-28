"""Pydantic AI: one typed tool call with authorisation and bounded execution.

Runs inside the tool's own environment. The model is a scripted stand-in
(FunctionModel) and real provider requests are switched off, so no key is needed and no
request leaves the machine. Prints one JSON object; exit status 1 if any case fails.

Cases, from the acceptance line of the "ai-intelligence" pack: a valid typed result, an
invalid output that the model corrects, an invalid output it never corrects, a tool that
runs past its time limit, a model that never stops calling tools, and a tool call the
caller was not authorised to make.
"""
import asyncio
import json
import sys
import time
from dataclasses import dataclass

import pydantic_ai
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, UnexpectedModelBehavior, UsageLimitExceeded, UsageLimits, models
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

models.ALLOW_MODEL_REQUESTS = False
TOOL_SECONDS = 0.2


class Reading(BaseModel):
    sensor: str
    celsius: float = Field(ge=-90, le=60)


class Refused(Exception):
    pass


@dataclass
class Caller:
    may_read: frozenset
    tool_delay: float = 0.0


SENSORS = {"roof": 21.5, "vault": 4.0}


def agent_for(script):
    agent = Agent(FunctionModel(script), output_type=Reading, deps_type=Caller, retries=1)

    @agent.tool
    async def read_sensor(ctx: RunContext[Caller], sensor: str) -> float:
        """Read one temperature sensor by name."""
        if sensor not in ctx.deps.may_read:
            raise Refused(f"caller may not read {sensor}")

        async def read():
            await asyncio.sleep(ctx.deps.tool_delay)
            return SENSORS[sensor]

        return await asyncio.wait_for(read(), TOOL_SECONDS)

    return agent


def returned(messages):
    """What the sensor tool has returned so far in this run."""
    return [part for message in messages for part in getattr(message, "parts", [])
            if isinstance(part, ToolReturnPart) and part.tool_name == "read_sensor"]


def scripted(sensor, answers):
    """Call the tool once, then give the answers one after another as the final output."""
    state = {"given": 0}

    def script(messages, info):
        if not returned(messages):
            return ModelResponse(parts=[ToolCallPart(tool_name="read_sensor", args={"sensor": sensor})])
        value = answers[min(state["given"], len(answers) - 1)]
        state["given"] += 1
        celsius = returned(messages)[-1].content if value == "tool" else value
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args={"sensor": sensor, "celsius": celsius})])

    return script, state


def looping(messages, info):
    return ModelResponse(parts=[ToolCallPart(tool_name="read_sensor", args={"sensor": "roof"})])


async def attempt(script, caller, limits=None):
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(agent_for(script).run("How warm is it?", deps=caller, usage_limits=limits), 5)
        outcome = {"output": result.output.model_dump(), "requests": result.usage.requests}
    except Exception as problem:  # the kind of failure is the result
        outcome = {"raised": type(problem).__name__}
    outcome["seconds"] = round(time.perf_counter() - started, 3)
    return outcome


async def main():
    everyone = Caller(frozenset(SENSORS))
    cases = {}

    script, _ = scripted("roof", ["tool"])
    got = await attempt(script, everyone)
    cases["valid_typed_result"] = {**got, "passed": got.get("output") == {"sensor": "roof", "celsius": 21.5}}

    script, state = scripted("roof", [999, "tool"])
    got = await attempt(script, everyone)
    cases["invalid_output_corrected_after_one_retry"] = {**got, "final_answers_given": state["given"],
        "passed": got.get("output") == {"sensor": "roof", "celsius": 21.5} and state["given"] == 2}

    script, state = scripted("roof", [999])
    got = await attempt(script, everyone)
    cases["invalid_output_never_corrected_is_rejected"] = {**got, "final_answers_given": state["given"],
        "passed": got.get("raised") == UnexpectedModelBehavior.__name__}

    script, _ = scripted("roof", ["tool"])
    got = await attempt(script, Caller(frozenset(SENSORS), tool_delay=2.0))
    cases["slow_tool_is_stopped"] = {**got, "limit_seconds": TOOL_SECONDS,
        "passed": got.get("raised") == "TimeoutError" and got["seconds"] < 1.0}

    got = await attempt(looping, everyone, UsageLimits(request_limit=3))
    cases["endless_tool_calls_are_stopped"] = {**got, "passed": got.get("raised") == UsageLimitExceeded.__name__}

    script, _ = scripted("vault", ["tool"])
    got = await attempt(script, Caller(frozenset({"roof"})))
    cases["unauthorised_call_is_refused"] = {**got, "passed": got.get("raised") == Refused.__name__}

    passed = all(case["passed"] for case in cases.values())
    print(json.dumps({"tool": "pydantic-ai-slim", "version": pydantic_ai.__version__, "provider_requests_allowed": models.ALLOW_MODEL_REQUESTS,
                      "status": "passed" if passed else "failed", "cases": cases}, indent=1))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
