"""Choose the size of the next wave of workers from what the last wave measured.

Pure and deterministic: no files, no clock, no network. From a script or a test:

    from adaptive import next_wave
    next_wave(history, limits)  # -> {"agents": n, "batch": k, "reason": "one sentence"}

`history` lists the waves so far, oldest first. Each has agents, batch,
peak_concurrent_agents, tasks_per_minute, verified_success_rate (percent),
agents_with_limit_error and input_tokens_per_agent. `limits` has start,
max_agents, max_batch, tokens_left and tasks_left. A missing number is None
and the rule that needs it is skipped; nothing is guessed.
Zero agents means stop. Run `python3 adaptive.py` for a small demonstration.
"""
import json

STEPS = (1, 2, 4, 8)


def _wave(agents, batch, reason):
    return {"agents": int(agents), "batch": int(batch), "reason": reason}


def _next_step(batch, max_batch):
    for s in STEPS:
        if s > batch and s <= max_batch:
            return s
    return None


def _decide(history, limits):
    start = limits.get("start")
    max_agents = limits.get("max_agents")
    max_batch = limits.get("max_batch") or 1
    if not history:
        n = start if max_agents is None else min(start, max_agents)
        return _wave(n, 1, f"No wave has run yet, so start with {n} agents and a batch of 1.")
    last = history[-1]
    agents, batch = last.get("agents") or 0, last.get("batch") or 1
    errors = last.get("agents_with_limit_error")
    if errors:
        return _wave(0, batch, f"{errors} agents hit a limit error in the last wave, so stop.")
    rate = last.get("verified_success_rate")
    if rate is not None and rate < 90:
        n = max(1, agents // 2)
        return _wave(n, batch, f"Verified success was {rate:g} percent, under 90, so halve {agents} agents to {n} and keep the batch at {batch}.")
    peak = last.get("peak_concurrent_agents")
    if peak is not None and agents and peak < 0.8 * agents:
        n = max(1, peak)
        return _wave(n, batch, f"The host ran at most {peak} of {agents} agents at once, under 80 percent, so ask for {n} next.")
    tpm = last.get("tasks_per_minute")
    prev = history[-2].get("tasks_per_minute") if len(history) > 1 else None
    if len(history) == 1 and tpm is not None:
        n = min(agents * 2, max_agents) if max_agents is not None else agents * 2
        return _wave(n, batch, f"This was the first measured wave at {tpm:g} tasks a minute, so double {agents} agents to {n}.")
    if tpm is not None and prev is not None and prev > 0 and tpm * 10 >= prev * 11:
        n = min(agents * 2, max_agents) if max_agents is not None else agents * 2
        return _wave(n, batch, f"Throughput rose from {prev:g} to {tpm:g} tasks a minute, at least 10 percent, so double {agents} agents to {n}.")
    nb = _next_step(batch, max_batch)
    if nb is None:
        return _wave(0, batch, f"Throughput was {tpm if tpm is not None else 'unmeasured'} against {prev if prev is not None else 'unmeasured'} tasks a minute and the batch is already at its limit of {max_batch}, so more agents and bigger batches both stopped paying.")
    return _wave(agents, nb, f"Throughput did not rise by 10 percent ({prev if prev is not None else 'unmeasured'} to {tpm if tpm is not None else 'unmeasured'} tasks a minute), so keep {agents} agents and raise the batch from {batch} to {nb}.")


def next_wave(history: list, limits: dict) -> dict:
    """Return {"agents", "batch", "reason"} for the next wave; agents 0 means stop."""
    out = _decide(history, limits)
    if out["agents"] == 0:
        return out
    agents, batch = out["agents"], out["batch"]
    fit, why = agents, []
    tasks_left = limits.get("tasks_left")
    if tasks_left is not None:
        cap = tasks_left // batch
        if cap < fit:
            fit = cap
            why.append(f"only {tasks_left} tasks are left at a batch of {batch}")
    tokens_left = limits.get("tokens_left")
    per = history[-1].get("input_tokens_per_agent") if history else None
    if tokens_left is not None and per:
        cap = int(tokens_left // per)
        if cap < fit:
            fit = cap
            why.append(f"only {tokens_left} tokens are left at {per:g} input tokens an agent")
    if fit == agents:
        return out
    note = " and ".join(why)
    if fit < 1:
        return _wave(0, batch, f"Not even one agent fits because {note}, so stop.")
    return _wave(fit, batch, f"{out['reason'].rstrip('.')}, but {note}, so cap it at {fit} agents.")


def main():
    limits = {"start": 4, "max_agents": 64, "max_batch": 8, "tokens_left": 10**7, "tasks_left": 10**4}
    print(json.dumps(next_wave([], limits), indent=1))


if __name__ == "__main__":
    main()
