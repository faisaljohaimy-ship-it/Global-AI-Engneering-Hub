"""Engineering economics and resource intelligence: GAIE layer L19.

This module is the single entry point for engineering accounting in the hub. It
reuses the swarm's reviewed code (swarm/phase3/adaptive.py, economics.py and
context_budget.py, loaded read-only by path) instead of re-implementing it:

* ledger accounting: `summarize` (schema 1 and 2) and `assess` (typed metrics):
  tokens per verified task; coordinator, worker and reviewer consumption; cache
  reads and writes; retries and their cost; rework; defects; development time and
  quality-adjusted productivity;
* strict units: `Tokens`, `Money`, `Seconds` and `Quota` never mix implicitly
  (`UnitError`), and a measurement that was not taken is `Unknown`, shown as
  "unknown", never 0;
* labelled ESTIMATES (`estimate_scope`, `estimate_infrastructure`,
  `estimate_maintenance`, `estimate_rework`): assumptions and ranges, never
  presented as measurements;
* `recommend_concurrency`: swarm/phase3/adaptive.next_wave plus the GAIE rule
  "more agents only if verified throughput per token improves; shrink on
  conflicts or limits";
* measured inputs: `measured_baseline` and `context_footprint` cite every figure
  with its source path; `engine` and `health` follow the 20-layer contract.

Input tokens include cached input (cache reads and, in schema 2, cache writes);
cached tokens are a priced subset, never added again. Receipt digests are
caller-supplied evidence references, not authenticated provider invoices or proof
of a real test run. Keep the underlying ledger private. No subscription allowance
is inferred, and no model or tool is invoked here.
SPDX-License-Identifier: MIT
"""

import argparse
import functools
import hashlib
import importlib.util
import json
import re
import statistics
import sys
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from .model_router import _finite, _identifier, _integer, _money, select_model
from .orchestration import DIGEST, MAX_BYTES, canonical, sha

SCOPES = ("feature", "mvp", "enterprise")
CATEGORIES = ("human-review", "infrastructure", "maintenance", "rework")
LIMIT = 10000
VERSIONS = (1, 2)
ROLES = {1: ("coordinator", "worker"), 2: ("coordinator", "worker", "reviewer")}
PURPOSES = ("work", "review", "coordination", "rework")
_LEDGER = {1: frozenset({"schema_version", "project", "actors", "tasks", "usage", "overheads"})}
_LEDGER[2] = _LEDGER[1] | {"period"}
_TASK = {1: frozenset({"id", "source_sha256", "scope", "verification"})}
_TASK[2] = _TASK[1] | {"defects"}
_USAGE = {1: frozenset({"id", "actor", "task", "attempt", "model", "tool", "source", "receipt_sha256",
                        "started_at", "ended_at", "input_tokens", "cached_input_tokens", "output_tokens",
                        "pricing", "charge"})}
_USAGE[2] = _USAGE[1] | {"cache_write_tokens", "purpose"}
_PRICING = {1: frozenset({"input_per_million_usd", "cached_input_per_million_usd", "output_per_million_usd"})}
_PRICING[2] = _PRICING[1] | {"cache_write_per_million_usd"}

_ROOT = Path(__file__).resolve().parent.parent
_SWARM = {"adaptive": ("swarm/phase3/adaptive.py", "next_wave"),
          "economics": ("swarm/phase3/economics.py", "factory"),
          "context_budget": ("swarm/phase3/context_budget.py", "budget")}


class EconomicsError(ValueError):
    pass


class UnitError(EconomicsError, TypeError):
    """Tokens, money, seconds or subscription quota were mixed, or an unknown was used as a number."""


def _guarded(function):
    """Public functions raise EconomicsError (or UnitError) only, at 64-digit decimal precision."""
    @functools.wraps(function)
    def run(*args, **kwargs):
        try:
            with localcontext() as context:
                context.prec = 64
                return function(*args, **kwargs)
        except EconomicsError:
            raise
        except (TypeError, KeyError, IndexError, ArithmeticError, RecursionError, ValueError) as error:
            raise EconomicsError(f"Malformed input to {function.__name__}") from error
    return run


def _swarm(name):
    """Load a reviewed swarm module by path, read-only, leaving sys.path as it was."""
    relative = _SWARM[name][0]
    path = _ROOT / relative
    if not path.is_file():
        raise EconomicsError(f"Swarm module not available: {relative}")
    spec = importlib.util.spec_from_file_location(f"engineering_os._swarm_{name}", path)
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


# ---------------------------------------------------------------- units

def _scalar(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise UnitError("A quantity is scaled only by a dimensionless int, float or Decimal")
    number = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    if not number.is_finite():
        raise UnitError("A scale factor must be finite")
    return number


def _unit_of(value):
    if isinstance(value, (Quantity, Unknown)):
        return value.unit
    if isinstance(value, bool):
        raise UnitError("A boolean is not a quantity")
    if isinstance(value, (int, float, Decimal)):
        return None
    raise UnitError(f"Not a quantity: {type(value).__name__}")


def _name(unit):
    return unit or "a plain number"


def _add(left, right, sign):
    first, second = _unit_of(left), _unit_of(right)
    if first != second:
        raise UnitError(f"Cannot {'add' if sign > 0 else 'subtract'} {_name(first)} and {_name(second)}")
    if isinstance(left, Unknown) or isinstance(right, Unknown):
        return Unknown(first)
    return left._make(left.value + sign * right.value)


def _mul(left, right):
    first, second = _unit_of(left), _unit_of(right)
    if first is not None and second is not None:
        raise UnitError(f"Cannot multiply {first} by {second}")
    unit = first or second
    if isinstance(left, Unknown) or isinstance(right, Unknown):
        return Unknown(unit)
    quantity, factor = (left, right) if first else (right, left)
    return quantity._make(quantity.value * _scalar(factor))


def _div(left, right):
    first, second = _unit_of(left), _unit_of(right)
    if second is not None and first != second:
        raise UnitError(f"Cannot divide {_name(first)} by {second}; use an explicit conversion")
    unit = None if second is not None else first
    if isinstance(left, Unknown) or isinstance(right, Unknown):
        return Unknown(unit)
    top = left.value if first else _scalar(left)
    bottom = right.value if second else _scalar(right)
    if bottom == 0:
        return Unknown(unit)  # no denominator: unknown, never zero or infinity
    return top / bottom if unit is None else left._make(top / bottom)


def _order(left, right):
    if isinstance(left, Unknown) or isinstance(right, Unknown):
        raise UnitError("An unknown measurement cannot be ordered")
    first, second = _unit_of(left), _unit_of(right)
    if first != second:
        raise UnitError(f"Cannot compare {_name(first)} with {_name(second)}")
    return left.value, right.value


class _Arithmetic:
    __slots__ = ()

    def __add__(self, other):
        return _add(self, other, 1)

    def __radd__(self, other):
        return _add(other, self, 1)

    def __sub__(self, other):
        return _add(self, other, -1)

    def __rsub__(self, other):
        return _add(other, self, -1)

    def __mul__(self, other):
        return _mul(self, other)

    def __rmul__(self, other):
        return _mul(other, self)

    def __truediv__(self, other):
        return _div(self, other)

    def __rtruediv__(self, other):
        return _div(other, self)

    def __lt__(self, other):
        left, right = _order(self, other)
        return left < right

    def __le__(self, other):
        left, right = _order(self, other)
        return left <= right

    def __gt__(self, other):
        left, right = _order(self, other)
        return left > right

    def __ge__(self, other):
        left, right = _order(self, other)
        return left >= right


class Unknown(_Arithmetic):
    """A measurement that was not taken. It is never zero and has no truth value."""
    __slots__ = ("unit",)

    def __init__(self, unit=None):
        object.__setattr__(self, "unit", unit)

    def __setattr__(self, *_):
        raise AttributeError("Unknown is immutable")

    def __reduce__(self):
        return (Unknown, (self.unit,))

    def __repr__(self):
        return "unknown" if self.unit is None else f"unknown {self.unit}"

    def __bool__(self):
        raise UnitError("An unknown measurement has no truth value; test it with is_unknown()")

    def __eq__(self, other):
        return isinstance(other, Unknown) and other.unit == self.unit

    def __hash__(self):
        return hash(("unknown", self.unit))

    def to_json(self):
        return "unknown"


def _rebuild(kind, value, unit):
    result = object.__new__(kind)
    result._set(value, unit)
    return result


class Quantity(_Arithmetic):
    """A measured amount in one unit. Subclasses: Tokens, Money, Seconds, Quota."""
    __slots__ = ("value", "unit")

    def __init__(self, value):
        raise TypeError("Use Tokens, Money, Seconds or Quota")

    def _set(self, value, unit):
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "unit", unit)

    def _make(self, value):
        return _rebuild(type(self), value, self.unit)

    def __setattr__(self, *_):
        raise AttributeError("Quantities are immutable")

    def __reduce__(self):
        return (_rebuild, (type(self), self.value, self.unit))

    def __eq__(self, other):
        if isinstance(other, Quantity) or (isinstance(other, Unknown) and other.unit not in (None, self.unit)):
            if other.unit != self.unit:
                raise UnitError(f"Cannot compare {self.unit} with {_name(other.unit)}")
            return isinstance(other, Quantity) and self.value == other.value
        if isinstance(other, Unknown):
            return False
        if isinstance(other, (int, float, Decimal)):
            raise UnitError(f"Compare {self.unit} with {self.unit}, not with a plain number")
        return NotImplemented

    def __hash__(self):
        return hash((self.unit, self.value))

    def __bool__(self):
        raise UnitError("A quantity has no truth value; compare it with a quantity of the same unit")

    def __repr__(self):
        return f"{type(self).__name__}({_text_number(self.value)!r})"

    def to_json(self):
        return {"unit": self.unit, "value": _text_number(self.value, exact=isinstance(self, Money))}


def _measure(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise UnitError(f"{field}: a non-negative number")
    number = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    if not number.is_finite() or number < 0:
        raise UnitError(f"{field}: a finite, non-negative number")
    return number


class Tokens(Quantity):
    """A token count reported by a provider or counted by a stated method."""
    __slots__ = ()
    UNIT = "tokens"

    def __init__(self, value):
        if type(value) is not int or value < 0:
            raise UnitError("Tokens: a non-negative integer count")
        self._set(Decimal(value), self.UNIT)


class Money(Quantity):
    """US dollars from a supplied rate or a billed line item; never inferred from tokens or quota."""
    __slots__ = ()
    UNIT = "USD"

    def __init__(self, value):
        if isinstance(value, (bool, float)) or not isinstance(value, (int, str, Decimal)):
            raise UnitError("Money: an int, a Decimal or a decimal string, never a float")
        try:
            amount = Decimal(value.strip() if isinstance(value, str) else value)
        except InvalidOperation:
            raise UnitError("Money: not a decimal amount") from None
        if not amount.is_finite() or amount < 0:
            raise UnitError("Money: a finite, non-negative amount")
        self._set(amount, self.UNIT)


class Seconds(Quantity):
    """Elapsed time in seconds."""
    __slots__ = ()
    UNIT = "seconds"

    def __init__(self, value):
        self._set(_measure(value, "Seconds"), self.UNIT)


class Quota(Quantity):
    """Subscription quota in the plan's own named unit; never tokens, money or another quota."""
    __slots__ = ()

    def __init__(self, value, name):
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", name):
            raise UnitError("Quota: a lowercase name for its unit, such as weekly-percent")
        self._set(_measure(value, "Quota"), f"quota:{name}")


def is_unknown(value):
    return isinstance(value, Unknown)


def measured(value, kind, name=None):
    """Wrap a raw measurement in its unit; None or "unknown" becomes Unknown, never 0."""
    unit = f"quota:{name}" if kind is Quota else kind.UNIT
    if value is None or (isinstance(value, str) and value == "unknown"):
        return Unknown(unit)
    if isinstance(value, (Quantity, Unknown)):
        if value.unit != unit:
            raise UnitError(f"Expected {unit}, got {_name(value.unit)}")
        return value
    return kind(value, name) if kind is Quota else kind(value)


def total(values, kind, name=None):
    """Sum measurements of one unit; any unknown makes the total unknown; mixing raises."""
    result = kind(0, name) if kind is Quota else kind(0)
    for value in values:
        result = result + measured(value, kind, name)
    return result


def price(tokens, usd_per_million_tokens):
    """The only bridge from tokens to money: an explicit, supplied rate."""
    count = measured(tokens, Tokens)
    rate = measured(usd_per_million_tokens, Money)
    if is_unknown(count) or is_unknown(rate):
        return Unknown(Money.UNIT)
    return rate._make(count.value * rate.value / Decimal(1000000))


def per_million_tokens(count, tokens):
    """A dimensionless count (such as verified tasks) per million tokens, or Unknown."""
    if count is None or is_unknown(count):
        return Unknown()
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise UnitError("Count: a non-negative integer")
    amount = measured(tokens, Tokens)
    if is_unknown(amount) or amount.value == 0:
        return Unknown()
    return Decimal(count) * Decimal(1000000) / amount.value


def _text_number(value, exact=False):
    if not isinstance(value, Decimal):
        return value
    with localcontext() as context:
        context.prec = 64
        if not exact and value == value.to_integral_value() and abs(value) < 2 ** 53:
            return int(value)
        if not exact:
            value = value.quantize(Decimal("0.000001"))
        text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def as_json(value):
    """Plain JSON for typed results: quantities keep their unit; unknown stays "unknown"."""
    if isinstance(value, (Quantity, Unknown)):
        return value.to_json()
    if isinstance(value, Decimal):
        return str(_text_number(value))
    if isinstance(value, dict):
        return {key: as_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [as_json(item) for item in value]
    return value


# ---------------------------------------------------------------- ledger accounting

def _object(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise EconomicsError("Unknown or missing ledger fields")
    return value


def _rows(value):
    if not isinstance(value, list) or len(value) > LIMIT:
        raise EconomicsError("Ledger collection exceeds bounded schema")
    return value


def _digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise EconomicsError("Evidence digest required")
    return value


def _count(value):
    return _integer(value, 0, 2**53 - 1)


def _charge(value, used_receipts):
    if value is None:
        return None
    _object(value, {"amount_usd", "receipt_sha256"})
    digest = _digest(value["receipt_sha256"])
    if digest in used_receipts:
        raise EconomicsError("Duplicate billed line-item receipt")
    used_receipts.add(digest)
    return _money(value["amount_usd"])


def _ratio(numerator, denominator):
    return None if denominator == 0 else str(Decimal(numerator) / denominator)


def _new_bucket():
    return {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
            "cache_write_tokens_known": 0, "cache_write_missing_items": 0,
            "request_count": 0, "estimated_usd_known": Decimal(0),
            "estimated_usd_missing_items": 0, "charged_usd_known": Decimal(0),
            "charged_usd_missing_items": 0, "overhead_seconds": Decimal(0),
            "call_elapsed_seconds_sum": Decimal(0), "tasks": set(),
            "verified_tasks": set()}


def _add_item(bucket, *, task=None, verified=False, usage=None, estimated=None,
              charged=None, overhead_seconds=0):
    if task is not None:
        bucket["tasks"].add(task)
        if verified:
            bucket["verified_tasks"].add(task)
    if usage is not None:
        bucket["request_count"] += 1
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            bucket[key] += usage[key]
        written = usage.get("cache_write_tokens")
        if written is None:
            bucket["cache_write_missing_items"] += 1
        else:
            bucket["cache_write_tokens_known"] += written
        bucket["call_elapsed_seconds_sum"] += Decimal(str(usage["ended_at"])) - Decimal(str(usage["started_at"]))
    bucket["overhead_seconds"] += Decimal(str(overhead_seconds))
    for kind, value in (("estimated", estimated), ("charged", charged)):
        if value is None:
            bucket[kind + "_usd_missing_items"] += 1
        else:
            bucket[kind + "_usd_known"] += value


def _finish(bucket):
    result = {key: value for key, value in bucket.items()
              if key not in {"tasks", "verified_tasks"}}
    for key in ("estimated_usd_known", "charged_usd_known", "overhead_seconds", "call_elapsed_seconds_sum"):
        result[key] = str(result[key])
    for kind in ("estimated", "charged"):
        result[kind + "_usd"] = (result[kind + "_usd_known"]
                                  if result[kind + "_usd_missing_items"] == 0 else None)
    result["cache_write_tokens"] = (result["cache_write_tokens_known"]
                                    if result["cache_write_missing_items"] == 0 else None)
    result["total_tokens"] = bucket["input_tokens"] + bucket["output_tokens"]
    result["task_count"] = len(bucket["tasks"])
    result["verified_task_count"] = len(bucket["verified_tasks"])
    result["observed_tokens_per_verified_task"] = _ratio(result["total_tokens"], result["verified_task_count"])
    return result


def _estimate(row, version):
    if row["pricing"] is None:
        return None
    pricing = _object(row["pricing"], _PRICING[version])
    regular, cached, output = (_money(pricing[name]) for name in
                              ("input_per_million_usd", "cached_input_per_million_usd", "output_per_million_usd"))
    written, write_rate = 0, Decimal(0)
    if version == 2:
        write_rate = _money(pricing["cache_write_per_million_usd"])
        if row["cache_write_tokens"] is None:
            return None  # the premium-priced share of input is not known
        written = row["cache_write_tokens"]
    uncached = row["input_tokens"] - row["cached_input_tokens"] - written
    return (uncached * regular + row["cached_input_tokens"] * cached + written * write_rate
            + row["output_tokens"] * output) / Decimal(1000000)


def _summarize(ledger):
    if not isinstance(ledger, dict) or type(ledger.get("schema_version")) is not int \
            or ledger["schema_version"] not in VERSIONS:
        raise EconomicsError("Unsupported ledger schema")
    version = ledger["schema_version"]
    _object(ledger, _LEDGER[version])
    project = _identifier(ledger["project"])
    actors, tasks, usage, overheads = {}, {}, _rows(ledger["usage"]), _rows(ledger["overheads"])
    for row in _rows(ledger["actors"]):
        _object(row, {"id", "role", "complete"})
        identity = _identifier(row["id"])
        if identity in actors or row["role"] not in ROLES[version] or type(row["complete"]) is not bool:
            raise EconomicsError("Duplicate actor or malformed role/completeness")
        actors[identity] = row
    if not actors or not any(row["role"] == "coordinator" for row in actors.values()):
        raise EconomicsError("Coordinator accounting required")
    verification_receipts = set()
    for row in _rows(ledger["tasks"]):
        _object(row, _TASK[version])
        identity = _identifier(row["id"])
        if identity in tasks:
            raise EconomicsError("Duplicate task")
        _digest(row["source_sha256"])
        _object(row["scope"], SCOPES)
        for value in row["scope"].values():
            if value is not None:
                _identifier(value)
        verification = row["verification"]
        if verification is not None:
            _object(verification, {"status", "source_sha256", "receipt_sha256"})
            if verification["status"] != "passed" or verification["source_sha256"] != row["source_sha256"]:
                raise EconomicsError("Verification must pass at the task source digest")
            receipt = _digest(verification["receipt_sha256"])
            if receipt in verification_receipts:
                raise EconomicsError("Verification receipt cannot count multiple tasks")
            verification_receipts.add(receipt)
        if version == 2 and row["defects"] is not None:
            _integer(row["defects"], 0, 1000000)
        tasks[identity] = row

    period = None
    if version == 2 and ledger["period"] is not None:
        _object(ledger["period"], {"started_at", "ended_at"})
        started, ended = _finite(ledger["period"]["started_at"]), _finite(ledger["period"]["ended_at"])
        if ended < started:
            raise EconomicsError("Development period ends before it starts")
        period = str(Decimal(str(ended)) - Decimal(str(started)))

    total_bucket, by_role, by_actor = _new_bucket(), {}, {}
    by_scope = {kind: {} for kind in SCOPES}
    unallocated = {kind: _new_bucket() for kind in SCOPES}
    by_tool, by_model, by_category, by_attempt, by_purpose = {}, {}, {}, {}, {}
    waste = _new_bucket()
    seen_ids, usage_receipts, charged_receipts, seen_actors = set(), set(), set(), set()
    span_start, span_end = None, None
    approximate = False
    role_seconds = {role: Decimal(0) for role in ROLES[version]}

    # Empty completed tasks still count in denominators; failed/retried work and
    # unassigned coordinator work remain in the whole-ledger numerator.
    for identity, row in tasks.items():
        total_bucket["tasks"].add(identity)
        if row["verification"] is not None:
            total_bucket["verified_tasks"].add(identity)
        for kind, scope in row["scope"].items():
            bucket = unallocated[kind] if scope is None else by_scope[kind].setdefault(scope, _new_bucket())
            bucket["tasks"].add(identity)
            if row["verification"] is not None:
                bucket["verified_tasks"].add(identity)

    def task_for(row):
        identity = row["task"]
        if identity is None:
            return None
        if not isinstance(identity, str) or identity not in tasks:
            raise EconomicsError("Unknown task in accounting item")
        return tasks[identity]

    def distribute(row, buckets, **values):
        task = task_for(row)
        options = {"task": None if task is None else task["id"],
                   "verified": task is not None and task["verification"] is not None, **values}
        for bucket in [total_bucket, *buckets]:
            _add_item(bucket, **options)
        for kind in SCOPES:
            scope = None if task is None else task["scope"][kind]
            target = unallocated[kind] if scope is None else by_scope[kind].setdefault(scope, _new_bucket())
            _add_item(target, **options)

    for row in usage:
        _object(row, _USAGE[version])
        identity = _identifier(row["id"])
        receipt = _digest(row["receipt_sha256"])
        if identity in seen_ids or receipt in usage_receipts:
            raise EconomicsError("Duplicate request identity or usage receipt")
        seen_ids.add(identity)
        usage_receipts.add(receipt)
        attempt = _integer(row["attempt"], 1, 1000000)
        actor_id = _identifier(row["actor"])
        if actor_id not in actors:
            raise EconomicsError("Unknown usage actor")
        seen_actors.add(actor_id)
        if row["source"] not in {"provider-reported", "proxy"}:
            raise EconomicsError("Usage provenance required")
        approximate |= row["source"] == "proxy"
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            _count(row[key])
        written = 0
        if version == 2:
            if row["purpose"] not in PURPOSES:
                raise EconomicsError("Unknown usage purpose")
            if row["cache_write_tokens"] is not None:
                written = _count(row["cache_write_tokens"])
        if row["cached_input_tokens"] + written > row["input_tokens"]:
            raise EconomicsError("Cached input exceeds inclusive input total")
        started, ended = _finite(row["started_at"]), _finite(row["ended_at"])
        if ended < started:
            raise EconomicsError("Usage interval ends before it starts")
        span_start = started if span_start is None else min(span_start, started)
        span_end = ended if span_end is None else max(span_end, ended)
        role = actors[actor_id]["role"]
        role_seconds[role] += Decimal(str(ended)) - Decimal(str(started))
        model, tool = _identifier(row["model"]), _identifier(row["tool"])
        groups = [by_role.setdefault(role, _new_bucket()), by_actor.setdefault(actor_id, _new_bucket()),
                  by_model.setdefault(model, _new_bucket()), by_tool.setdefault(tool, _new_bucket()),
                  by_attempt.setdefault("first" if attempt == 1 else "retry", _new_bucket())]
        if version == 2:
            groups.append(by_purpose.setdefault(row["purpose"], _new_bucket()))
        if attempt > 1 or (version == 2 and row["purpose"] == "rework"):
            groups.append(waste)
        distribute(row, groups, usage=row, estimated=_estimate(row, version),
                   charged=_charge(row["charge"], charged_receipts))

    for row in overheads:
        _object(row, {"id", "task", "category", "seconds", "estimate_usd", "charge"})
        identity = _identifier(row["id"])
        if identity in seen_ids or row["category"] not in CATEGORIES:
            raise EconomicsError("Duplicate item identity or unknown overhead category")
        seen_ids.add(identity)
        seconds = _finite(row["seconds"])
        estimate = None if row["estimate_usd"] is None else _money(row["estimate_usd"])
        distribute(row, [by_category.setdefault(row["category"], _new_bucket())],
                   overhead_seconds=seconds, estimated=estimate, charged=_charge(row["charge"], charged_receipts))

    missing_actors = sorted(set(actors) - seen_actors)
    incomplete_actors = sorted(identity for identity, row in actors.items() if not row["complete"])
    complete = not missing_actors and not incomplete_actors
    result = _finish(total_bucket)
    result["tokens_per_verified_task"] = result["observed_tokens_per_verified_task"] if complete and not approximate else None
    for kind in ("estimated", "charged"):
        result["observed_" + kind + "_usd"] = result[kind + "_usd"]
        if not complete:
            result[kind + "_usd"] = None
    result["scope"] = "all recorded coordinator, worker and reviewer usage, including retries and unverified work"
    verified_ids = [identity for identity, row in tasks.items() if row["verification"] is not None]
    defects = {identity: (row["defects"] if version == 2 else None) for identity, row in tasks.items()}
    quality = {"defects_known": sum(value for value in defects.values() if value is not None),
               "tasks_with_unknown_defects": sum(value is None for value in defects.values()),
               "verified_tasks_with_unknown_defects": sum(defects[i] is None for i in verified_ids),
               "verified_tasks_with_defects": sum(defects[i] is not None and defects[i] > 0 for i in verified_ids),
               "verified_tasks_without_defects": sum(defects[i] == 0 for i in verified_ids)}
    notes = ["Receipt references are supplied assertions; review original evidence independently.",
             "USD estimates use supplied rates; charges use supplied billed line items. Neither infers subscription allowance.",
             "Scope groups overlap across levels and are not additive; unattributed coordinator/overhead costs remain unallocated.",
             "Call elapsed sums include overlap; observed wall span is not full development time or CPU time."]
    if version == 1:
        notes.append("Schema 1 records no cache writes, usage purpose, reviewers or defects; those stay unknown.")
    elif result["cache_write_missing_items"]:
        notes.append("Some requests did not report cache writes; their cost estimate and the cache-write total are unknown.")
    if approximate:
        notes.append("Proxy tokens are approximate; exact tokens per verified task is unavailable.")
    if not complete:
        notes.append("Actor accounting is incomplete; observed totals are lower bounds, not whole-project measurements.")
    recommendations = []
    if not complete:
        recommendations.append("Collect final usage for every declared actor before comparing runs.")
    if result["estimated_usd_missing_items"]:
        recommendations.append("Supply reviewed explicit rates or overhead estimates before publishing a total cost estimate.")
    if result["charged_usd_missing_items"]:
        recommendations.append("Reconcile each item with a billed line-item receipt before reporting actual monetary cost.")
    if not result["verified_task_count"]:
        recommendations.append("Obtain source-bound passed test receipts before reporting verified-task efficiency.")
    timing = {"observed_call_wall_span_seconds": None if span_start is None else str(Decimal(str(span_end)) - Decimal(str(span_start))),
              "full_development_time_seconds": period}
    for role, seconds in role_seconds.items():
        timing[role + "_call_seconds_sum"] = str(seconds)
    return {"schema_version": 1, "ledger_schema_version": version, "project": project, "ledger_sha256": sha(ledger),
            "accounting_complete": complete, "missing_usage_actors": missing_actors,
            "incomplete_actors": incomplete_actors, "token_basis": "proxy-present" if approximate else "provider-reported",
            "summary": result, "by_role": {key: _finish(value) for key, value in sorted(by_role.items())},
            "by_actor": {key: _finish(value) for key, value in sorted(by_actor.items())},
            "by_scope": {kind: {key: _finish(value) for key, value in sorted(groups.items())} for kind, groups in by_scope.items()},
            "unallocated_by_scope": {kind: _finish(value) for kind, value in unallocated.items()},
            "by_model": {key: _finish(value) for key, value in sorted(by_model.items())},
            "by_tool": {key: _finish(value) for key, value in sorted(by_tool.items())},
            "by_attempt": {key: _finish(value) for key, value in sorted(by_attempt.items())},
            "by_purpose": None if version == 1 else {key: _finish(value) for key, value in sorted(by_purpose.items())},
            "waste": _finish(waste), "quality": quality,
            "overheads_by_category": {key: _finish(value) for key, value in sorted(by_category.items())},
            "time": timing, "recommendations": recommendations, "notes": notes,
            "provider_calls": 0, "subscription_allowance": None}


def summarize(ledger):
    """Validate and aggregate bounded metadata; never load a prompt or execute a tool.

    Schema 1 is unchanged. Schema 2 adds a reviewer role, per-request cache writes
    (an inclusive subset of input, priced at `cache_write_per_million_usd`), a usage
    purpose (work, review, coordination, rework), per-task defect counts and a
    caller-asserted development period. A task verification reference binds to its
    exact source digest. It does not authenticate the originating tester. Each
    completed task needs a distinct per-task verification receipt; shared test
    suites can issue task-specific receipts. Completed actor declarations are
    likewise caller assertions and should be reconciled with trusted host exports.
    """
    try:
        if len(canonical(ledger)) > MAX_BYTES:
            raise EconomicsError("Ledger exceeds bounded byte size")
        with localcontext() as context:
            context.prec = 64
            return _summarize(ledger)
    except (TypeError, KeyError, ArithmeticError, RecursionError, ValueError) as error:
        if isinstance(error, EconomicsError):
            raise
        raise EconomicsError("Malformed engineering accounting metadata") from error


def _tokens_of(value):
    return Unknown(Tokens.UNIT) if value is None else Tokens(int(value))


def _usd_of(value):
    return Unknown(Money.UNIT) if value is None else Money(value)


def _seconds_of(value):
    return Unknown(Seconds.UNIT) if value is None else Seconds(Decimal(value))


def _share(part, whole):
    return Unknown() if is_unknown(part) or is_unknown(whole) else part / whole


def _consumption(bucket, total_tokens):
    used = Tokens(bucket["total_tokens"])
    return {"input": Tokens(bucket["input_tokens"]), "cache_read": Tokens(bucket["cached_input_tokens"]),
            "cache_write": _tokens_of(bucket["cache_write_tokens"]), "output": Tokens(bucket["output_tokens"]),
            "total": used, "share_of_all_tokens": _share(used, total_tokens), "requests": bucket["request_count"],
            "call_seconds": _seconds_of(bucket["call_elapsed_seconds_sum"]),
            "estimated_cost": _usd_of(bucket["estimated_usd"]), "charged_cost": _usd_of(bucket["charged_usd"])}


def _empty_consumption(known):
    if not known:
        unknown = {key: Unknown(Tokens.UNIT) for key in ("input", "cache_read", "cache_write", "output", "total")}
        return {**unknown, "share_of_all_tokens": Unknown(), "requests": Unknown(),
                "call_seconds": Unknown(Seconds.UNIT), "estimated_cost": Unknown(Money.UNIT),
                "charged_cost": Unknown(Money.UNIT)}
    zero = {key: Tokens(0) for key in ("input", "cache_read", "cache_write", "output", "total")}
    return {**zero, "share_of_all_tokens": Decimal(0), "requests": 0, "call_seconds": Seconds(0),
            "estimated_cost": Money(0), "charged_cost": Money(0)}


def _per(count, denominator):
    if is_unknown(count) or is_unknown(denominator) or denominator == 0:
        return Unknown()
    return Decimal(count) / denominator


@_guarded
def assess(ledger):
    """Typed L19 metrics over a schema 1 or 2 ledger: every figure has a unit, gaps are "unknown".

    Quality-adjusted productivity = verified tasks without known defects
    x (1 - waste token share) / development hours, where waste is every retry
    (attempt > 1) and every request whose purpose is rework.
    """
    report = summarize(ledger)
    version, summary = report["ledger_schema_version"], report["summary"]
    exact = report["accounting_complete"] and report["token_basis"] == "provider-reported"
    all_tokens = Tokens(summary["total_tokens"])
    verified = summary["verified_task_count"]
    roles = {}
    for role in ROLES[2]:
        if role in report["by_role"]:
            roles[role] = _consumption(report["by_role"][role], all_tokens)
        else:  # schema 2 can declare reviewers, so a complete schema 2 ledger without one used none
            roles[role] = _empty_consumption(version == 2 and report["accounting_complete"])
    retry = report["by_attempt"].get("retry")
    rework_overhead = report["overheads_by_category"].get("rework")
    if version == 1:
        rework_usage, waste_tokens = _empty_consumption(False), Unknown(Tokens.UNIT)
    else:
        bucket = report["by_purpose"].get("rework")
        rework_usage = _consumption(bucket, all_tokens) if bucket else _empty_consumption(True)
        waste_tokens = Tokens(report["waste"]["total_tokens"])
    waste_share = _share(waste_tokens, all_tokens)
    development = _seconds_of(report["time"]["full_development_time_seconds"])
    span = _seconds_of(report["time"]["observed_call_wall_span_seconds"])
    hours, span_hours = development / Seconds(3600), span / Seconds(3600)
    quality = report["quality"]
    clean = (quality["verified_tasks_without_defects"] if quality["verified_tasks_with_unknown_defects"] == 0
             else Unknown())
    defect_rate = (Unknown() if quality["verified_tasks_with_unknown_defects"] or not verified
                   else Decimal(quality["verified_tasks_with_defects"]) / verified)
    adjusted = (Unknown() if is_unknown(clean) or is_unknown(waste_share)
                else _per(clean * (1 - waste_share), hours))
    return as_json({
        "kind": "measured" if exact else "partial",
        "ledger_sha256": report["ledger_sha256"], "ledger_schema_version": version,
        "accounting_complete": report["accounting_complete"], "token_basis": report["token_basis"],
        "verified_tasks": verified, "tasks": summary["task_count"],
        "tokens_per_verified_task": all_tokens / verified if exact else Unknown(Tokens.UNIT),
        "observed_tokens_per_verified_task": all_tokens / verified,
        "verified_tasks_per_million_tokens": per_million_tokens(verified, all_tokens) if exact else Unknown(),
        "consumption_by_role": roles,
        "cache": {"reads": Tokens(summary["cached_input_tokens"]), "writes": _tokens_of(summary["cache_write_tokens"]),
                  "read_share_of_input": _share(Tokens(summary["cached_input_tokens"]), Tokens(summary["input_tokens"]))},
        "retries": _consumption(retry, all_tokens) if retry else _empty_consumption(True),
        "rework": {"usage": rework_usage,
                   "overhead_seconds": _seconds_of(rework_overhead["overhead_seconds"]) if rework_overhead else Seconds(0),
                   "overhead_estimated_cost": _usd_of(rework_overhead["estimated_usd"]) if rework_overhead else Money(0)},
        "waste": {"tokens": waste_tokens, "share_of_all_tokens": waste_share},
        "defects": {"known": quality["defects_known"], "verified_tasks_with_defects": quality["verified_tasks_with_defects"],
                    "defect_rate": defect_rate},
        "time": {"development": development, "observed_call_wall_span": span},
        "productivity": {
            "unit": "verified tasks per hour",
            "verified_per_development_hour": _per(verified, hours),
            "verified_per_call_span_hour_upper_bound": _per(verified, span_hours),
            "quality_adjusted_per_development_hour": adjusted,
            "formula": "verified tasks without known defects x (1 - waste token share) / development hours"},
        "money": {"estimated": _usd_of(summary["estimated_usd"]), "charged": _usd_of(summary["charged_usd"])},
        "subscription_quota": Unknown("quota:subscription"),
        "notes": report["notes"] + ["Subscription quota is not observable from a usage ledger and is never derived from tokens or money."],
        "provider_calls": 0})


# ---------------------------------------------------------------- adaptive concurrency

_WAVE_REQUIRED = ("agents", "duration_seconds", "tasks_verified", "tokens", "conflicts", "failures")
_WAVE_OPTIONAL = ("batch", "limit_errors", "peak_concurrent_agents", "label", "source")


def _whole(value, field, low=0, high=10**9):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise EconomicsError(f"{field}: an integer from {low} to {high}")
    return value


def _maybe(value, field):
    return Unknown() if value is None or (isinstance(value, str) and value == "unknown") else _whole(value, field)


def _wave_record(row):
    if not isinstance(row, dict) or not set(_WAVE_REQUIRED) <= set(row) \
            or set(row) - set(_WAVE_REQUIRED) - set(_WAVE_OPTIONAL):
        raise EconomicsError("Wave: needs " + ", ".join(_WAVE_REQUIRED) + "; optional " + ", ".join(_WAVE_OPTIONAL))
    for field in ("label", "source"):
        if field in row and (not isinstance(row[field], str) or not 0 < len(row[field]) <= 200):
            raise EconomicsError(f"Wave {field}: short text")
    wave = {"agents": _whole(row["agents"], "agents", 1, 100000),
            "batch": _whole(row.get("batch", 1), "batch", 1, 64),
            "duration": measured(row["duration_seconds"], Seconds),
            "tokens": measured(row["tokens"], Tokens),
            "label": row.get("label")}
    for field in ("tasks_verified", "conflicts", "failures", "limit_errors", "peak_concurrent_agents"):
        wave[field] = _maybe(row.get(field), field)
    done = wave["tasks_verified"]
    wave["tasks_per_minute"] = _per(done, wave["duration"] / Seconds(60))
    wave["efficiency"] = per_million_tokens(done, wave["tokens"])
    attempted = Unknown() if is_unknown(done) or is_unknown(wave["failures"]) else done + wave["failures"]
    wave["success_rate"] = _per(Unknown() if is_unknown(done) else 100 * done, attempted)
    wave["tokens_per_agent"] = wave["tokens"] / wave["agents"]
    return wave


def _plain(value):
    return None if is_unknown(value) else round(float(value), 2)


def _shown(value, digits=2):
    return "unknown" if is_unknown(value) else f"{float(value):,.{digits}f}"


def _limits(limits):
    if not isinstance(limits, dict) or "start" not in limits:
        raise EconomicsError("Limits: start is required")
    if set(limits) - {"start", "max_agents", "max_batch", "tokens_left", "tasks_left", "min_efficiency_gain"}:
        raise EconomicsError("Limits: unknown field")
    tokens_left = measured(limits.get("tokens_left"), Tokens)
    gain = _fraction(limits.get("min_efficiency_gain", "0"), "min_efficiency_gain", "0", "10")
    plain = {"start": _whole(limits["start"], "start", 1, 100000)}
    for field, low, high in (("max_agents", 1, 100000), ("max_batch", 1, 64), ("tasks_left", 0, 10**9)):
        value = limits.get(field)
        plain[field] = None if value is None else _whole(value, field, low, high)
    plain["tokens_left"] = None if is_unknown(tokens_left) else int(tokens_left.value)
    return plain, gain


def _cap(agents, batch, wave, limits):
    """The same task and token caps next_wave applies to its own decisions."""
    why = []
    if limits["tasks_left"] is not None and limits["tasks_left"] // batch < agents:
        agents = limits["tasks_left"] // batch
        why.append(f"only {limits['tasks_left']} tasks are left at a batch of {batch}")
    per = wave["tokens_per_agent"]
    if limits["tokens_left"] is not None and not is_unknown(per) and per.value > 0 \
            and int(Decimal(limits["tokens_left"]) // per.value) < agents:
        agents = int(Decimal(limits["tokens_left"]) // per.value)
        why.append(f"only {limits['tokens_left']:,} tokens are left at {_shown(per.value, 0)} tokens an agent")
    return agents, " and ".join(why)


@_guarded
def recommend_concurrency(waves, limits):
    """Next agent count and batch from measured waves, with a one-sentence reason.

    Built on swarm/phase3/adaptive.next_wave (start, limit-error stop, halving under
    90 percent verified, host peak, 10 percent throughput rule, batch steps, task and
    token caps), plus the GAIE rule: more agents only if verified tasks per million
    tokens improved on the previous wave; halve on any conflict; a limit error stops.
    Deterministic; nothing is executed. Agents 0 means stop.
    """
    plain, gain = _limits(limits)
    if not isinstance(waves, list) or len(waves) > 1000:
        raise EconomicsError("Waves: a list of up to 1000 measured waves")
    rows = [_wave_record(row) for row in waves]
    history = [{"agents": w["agents"], "batch": w["batch"],
                "peak_concurrent_agents": None if is_unknown(w["peak_concurrent_agents"]) else w["peak_concurrent_agents"],
                "tasks_per_minute": _plain(w["tasks_per_minute"]),
                "verified_success_rate": _plain(w["success_rate"]),
                "agents_with_limit_error": None if is_unknown(w["limit_errors"]) else w["limit_errors"],
                "input_tokens_per_agent": None if is_unknown(w["tokens_per_agent"]) else float(w["tokens_per_agent"].value)}
               for w in rows]
    base = _swarm("adaptive").next_wave(history, plain)
    last = rows[-1] if rows else None
    previous = rows[-2] if len(rows) > 1 else None
    unknown = [] if last is None else sorted(
        field for field in ("duration", "tokens", "tasks_verified", "conflicts", "failures",
                            "limit_errors", "peak_concurrent_agents") if is_unknown(last[field]))

    def decide(agents, batch, reason, rule):
        ceiling = plain["max_agents"]
        if ceiling is not None and agents > ceiling:  # GAIE: a limit always shrinks, whichever rule spoke
            reason = f"{reason.rstrip('.')}, but the limit is {_agents(ceiling)}, so cap it at {ceiling}."
            agents, rule = ceiling, rule + "+max-agents-cap"
        return _decision(agents, batch, reason, rule, base, last, previous, unknown)

    if last is None:
        return decide(base["agents"], base["batch"], base["reason"], "start")
    if not is_unknown(last["limit_errors"]) and last["limit_errors"] > 0:
        return decide(base["agents"], base["batch"], base["reason"], "limit-stop")
    agents, batch = last["agents"], last["batch"]
    if not is_unknown(last["conflicts"]) and last["conflicts"] > 0:
        fit, note = _cap(max(1, agents // 2), batch, last, plain)
        conflicts = f"{last['conflicts']} conflict{'s' if last['conflicts'] > 1 else ''}"
        if fit < 1:
            return decide(0, batch, f"{conflicts} in the last wave and {note}, so stop.", "conflict-stop")
        reason = (f"{conflicts} in the last wave of {_agents(agents)}, so shrink to {_agents(fit)} "
                  f"and keep the batch at {batch}" + (f", capped because {note}." if note else "."))
        return decide(fit, batch, reason, "conflict-shrink")
    if base["agents"] <= agents:
        return decide(base["agents"], base["batch"], base["reason"], "next-wave")
    before = Unknown() if previous is None else previous["efficiency"]
    after = last["efficiency"]
    if not is_unknown(before) and not is_unknown(after) and before > 0 and after > before * (1 + gain):
        reason = (f"Verified tasks per million tokens improved from {_shown(before)} to {_shown(after)} and "
                  + base["reason"][0].lower() + base["reason"][1:])
        return decide(base["agents"], base["batch"], reason, "grow-efficiency-improved")
    fit, note = _cap(agents, batch, last, plain)
    why = ("there is no earlier wave to compare it with" if previous is None else
           f"it went from {_shown(before)} to {_shown(after)}, which is not an improvement")
    if fit < 1:
        return decide(0, batch, f"Growth is refused because {why}, and {note}, so stop.", "hold-stop")
    reason = (f"Throughput alone would grow to {_agents(base['agents'])}, but verified tasks per million tokens "
              f"cannot justify it because {why}, so hold at {_agents(fit)} and a batch of {batch}"
              + (f", capped because {note}." if fit < agents else "."))
    return decide(fit, batch, reason, "hold-efficiency-not-improved")


def _agents(count):
    return f"{count} agent" + ("" if count == 1 else "s")


def _decision(agents, batch, reason, rule, base, last, previous, unknown):
    def figures(wave):
        if wave is None:
            return None
        return {"label": wave["label"], "agents": wave["agents"], "batch": wave["batch"],
                "tasks_per_minute": wave["tasks_per_minute"], "verified_tasks_per_million_tokens": wave["efficiency"],
                "verified_success_rate_percent": wave["success_rate"], "conflicts": wave["conflicts"],
                "limit_errors": wave["limit_errors"], "tokens": wave["tokens"]}
    return as_json({"agents": int(agents), "batch": int(batch), "reason": reason, "rule": rule,
                    "stop": int(agents) == 0, "last_wave": figures(last), "previous_wave": figures(previous),
                    "unknown_inputs": unknown, "next_wave_base": base,
                    "basis": "measured waves; deterministic rules; nothing executed"})


def _tokens_of_stage(stage):
    agent = stage.get("agent_tokens") if isinstance(stage.get("agent_tokens"), dict) else {}
    orchestrator = stage.get("orchestrator_tokens") if isinstance(stage.get("orchestrator_tokens"), dict) else {}
    parts = [agent.get("input_total"), agent.get("output")]
    if orchestrator:
        parts += [orchestrator.get("input_total"), orchestrator.get("output")]
    return sum(parts) if all(type(part) is int for part in parts) else None


@_guarded
def waves_from_evidence(document, source):
    """Measured waves from a swarm evidence file: a ladder/stages document or a team document.

    Stage waves count worker plus orchestrator tokens; conflicts are not recorded in
    those files and stay unknown. A team wave counts lanes joined cleanly as verified,
    lanes rejected for changing paths outside their lane as conflicts, and lanes whose
    own tests failed as failures; any other lane state makes those counts unknown.
    """
    if not isinstance(document, dict) or not isinstance(source, str):
        raise EconomicsError("Evidence: an object and its source path")
    if isinstance(document.get("lanes"), list) and isinstance(document.get("totals"), dict):
        totals, lanes = document["totals"], document["lanes"]
        states = [lane.get("state") if isinstance(lane, dict) else None for lane in lanes]
        conflicts = sum(isinstance(s, str) and "outside its lane" in s for s in states)
        failures = sum(isinstance(s, str) and "tests fail" in s for s in states)
        clean = sum(s == "joined" for s in states)
        recognised = clean + conflicts + failures == len(states)
        tokens = (totals["input_tokens"] + totals["output_tokens"]
                  if all(type(totals.get(k)) is int for k in ("input_tokens", "output_tokens")) else None)
        return [{"label": f"team-{len(lanes)}-lanes", "source": source,
                 "agents": totals.get("agents_started"), "batch": 1,
                 "peak_concurrent_agents": totals.get("ran_at_once"),
                 "duration_seconds": totals.get("wall_seconds"), "tokens": tokens,
                 "tasks_verified": clean if recognised else None,
                 "conflicts": conflicts if recognised else None,
                 "failures": failures if recognised else None,
                 "limit_errors": totals.get("agents_that_met_a_limit")}]
    stages = document.get("stages", document.get("ladder"))
    if not isinstance(stages, list):
        raise EconomicsError("Evidence: no stages, ladder or lanes")
    waves = []
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("kind") not in (None, "task") or stage.get("skipped"):
            continue
        agents, tasks, verified = stage.get("actual_agents"), stage.get("tasks"), stage.get("verified_tasks")
        if type(agents) is not int or agents < 1:
            continue
        counted = type(tasks) is int and type(verified) is int and tasks >= verified
        waves.append({"label": str(stage.get("label")), "source": source, "agents": agents,
                      "batch": max(1, tasks // agents) if type(tasks) is int else 1,
                      "peak_concurrent_agents": stage.get("peak_concurrent_agents"),
                      "duration_seconds": stage.get("wall_seconds"), "tokens": _tokens_of_stage(stage),
                      "tasks_verified": verified if counted else None,
                      "failures": tasks - verified if counted else None, "conflicts": None,
                      "limit_errors": stage.get("agents_with_limit_error")})
    return waves


# ---------------------------------------------------------------- labelled estimates

ESTIMATE = "ESTIMATE: computed from the stated assumptions and measured per-task rows; not a measurement"
ENTERPRISE_SYSTEMS = 10  # assumption: an enterprise system is ten MVP-sized systems
DEFAULT_TASK_SPREAD = {"feature": ("0.5", "2"), "mvp": ("0.5", "2"), "enterprise": ("0.5", "3")}
DEFAULT_MAINTENANCE_PER_YEAR = ("0.15", "0.25")


def _fraction(value, field, low="0", high="1"):
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal, float)):
        raise EconomicsError(f"{field}: a decimal number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise EconomicsError(f"{field}: a decimal number") from None
    if not number.is_finite() or not Decimal(low) <= number <= Decimal(high):
        raise EconomicsError(f"{field}: from {low} to {high}")
    return number


def _range(pair, field, low="0", high="1000000"):
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        raise EconomicsError(f"{field}: [low, high]")
    first, second = _fraction(pair[0], field, low, high), _fraction(pair[1], field, low, high)
    if first > second:
        raise EconomicsError(f"{field}: low above high")
    return first, second


def _assumptions(value, allowed):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise EconomicsError("Assumptions: unknown field")
    return value


def _rates(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"input_per_million_usd", "output_per_million_usd"}:
        raise EconomicsError("Rates: input_per_million_usd and output_per_million_usd")
    return {key: measured(item, Money) for key, item in value.items()}


def _coordinator_shares(document):
    shares = [s["orchestrator_share_of_all_tokens"] for s in document.get("stages", [])
              if isinstance(s, dict) and s.get("kind") == "task" and type(s.get("actual_agents")) is int
              and s["actual_agents"] >= 10 and isinstance(s.get("orchestrator_share_of_all_tokens"), (int, float))]
    return (min(shares), max(shares)) if shares else None


@_guarded
def estimate_scope(scope, evidence, assumptions=None, *, source="swarm/phase2/evidence/stages.json"):
    """ESTIMATE of tokens, money and time for one feature, one MVP or one enterprise system.

    Reuses swarm/phase3/economics.factory: the cheapest measured configuration per
    task size that verified at least 90 percent, and its measured failure rate for
    second attempts. Adds the coordinator's share and a task-count spread. Money is
    "unknown" unless reviewed rates are supplied; all input is priced at the
    uncached rate, an upper bound.
    """
    if scope not in SCOPES:
        raise EconomicsError("Scope: feature, mvp or enterprise")
    if not isinstance(evidence, dict):
        raise EconomicsError("Evidence: a stages document")
    options = _assumptions(assumptions, {"task_multiplier", "coordinator_share", "rates"})
    swarm_economics = _swarm("economics")
    system = swarm_economics.RECIPES["one system"]
    recipe = {"feature": dict(swarm_economics.RECIPES["one feature"]), "mvp": dict(system),
              "enterprise": {size: count * ENTERPRISE_SYSTEMS for size, count in system.items()}}[scope]
    spread = _range(options.get("task_multiplier", DEFAULT_TASK_SPREAD[scope]), "task_multiplier", "0.01", "1000")
    measured_shares = _coordinator_shares(evidence)
    if "coordinator_share" in options:
        shares, share_basis = _range(options["coordinator_share"], "coordinator_share", "0", "0.99"), "supplied"
    elif measured_shares:
        shares = tuple(Decimal(str(s)) for s in measured_shares)
        share_basis = f"lowest and highest measured in task stages of 10 or more agents ({source})"
    else:
        shares, share_basis = None, "unknown: no measured stage of 10 or more agents"
    rates = _rates(options.get("rates"))
    rows = swarm_economics.per_task(evidence)
    plan = swarm_economics.factory(rows, recipe)
    totals, best_retry = plan["totals"], plan["share_needing_second_attempt"]
    failures = [r["failure_rate"] for r in rows if r.get("size") in recipe and r.get("failure_rate") is not None]
    retry = None if best_retry is None or not failures else (Decimal(str(best_retry)), Decimal(str(max(failures))))
    minutes = Decimal(0)
    for size, count in recipe.items():
        chosen = plan["sizes"][size]["configuration"]
        row = next((r for r in rows if chosen and r.get("label") == chosen["label"]), None)
        wall = None if row is None else swarm_economics.project(row, count)["wall_minutes"]["value"]
        minutes = None if minutes is None or wall is None else minutes + Decimal(str(wall))
    known = (not plan["sizes_without_a_figure"] and shares is not None and retry is not None
             and all(totals[key] is not None for key in ("input_tokens", "output_tokens", "agent_minutes")))
    tokens, money, agent_time, wall_time = {"input": {}, "output": {}}, {}, {}, {}
    for end, i in (("low", 0), ("high", 1)):
        factor = None if not known else spread[i] * (1 + retry[i])
        for kind in tokens:
            tokens[kind][end] = (Tokens(int((Decimal(totals[kind + "_tokens"]) * factor / (1 - shares[i])).to_integral_value()))
                                 if known else Unknown(Tokens.UNIT))
        money[end] = (Unknown(Money.UNIT) if rates is None or not known else
                      price(tokens["input"][end], rates["input_per_million_usd"])
                      + price(tokens["output"][end], rates["output_per_million_usd"]))
        agent_time[end] = Seconds(Decimal(str(totals["agent_minutes"])) * 60 * factor) if known else Unknown(Seconds.UNIT)
        wall_time[end] = Seconds(minutes * 60 * factor) if known and minutes is not None else Unknown(Seconds.UNIT)
    return as_json({
        "kind": "ESTIMATE", "label": ESTIMATE, "measured": False, "scope": scope, "recipe": recipe,
        "tokens": tokens, "money": money, "agent_time": agent_time, "wall_time": wall_time,
        "assumptions": {
            "recipe": "feature and mvp are swarm/phase3/economics.RECIPES 'one feature' and 'one system'; "
                      f"enterprise is {ENTERPRISE_SYSTEMS} x 'one system'",
            "task_multiplier": list(spread),
            "coordinator_share_of_all_tokens": None if shares is None else list(shares),
            "coordinator_share_basis": share_basis,
            "second_attempt_share": None if retry is None else list(retry),
            "second_attempt_basis": "low: measured failure share of the configurations used (factory); high: the worst "
                                    "measured failure rate of any stage of these sizes; a failed task is attempted once "
                                    "more at the same cost",
            "wall_time_basis": "each size run in turn at the measured tasks per minute of its configuration "
                               "(swarm/phase3/economics.project), not in parallel",
            "rates": "unknown: none supplied" if rates is None else rates,
            "pricing_basis": "all input at the uncached input rate (cache discounts not applied: an upper bound)",
            "validity": "the measured tasks are generated stand-ins (a function, a module-sized feature, a fix in an "
                        "existing system), not product work; read the result as an order of magnitude for agent "
                        "work of that shape, not as a quote for a real feature, MVP or enterprise system",
            "excluded": ["human review", "infrastructure", "maintenance", "work the generated tasks do not stand in for"]},
        "basis": {"evidence": source, "configurations": {size: z["configuration"] for size, z in plan["sizes"].items()},
                  "sizes_without_a_figure": plan["sizes_without_a_figure"], "stand_ins": swarm_economics.STAND_IN}})


@_guarded
def estimate_infrastructure(assumptions):
    """ESTIMATE of infrastructure cost from supplied monthly component ranges (USD)."""
    options = _assumptions(assumptions, {"components", "months"})
    months = _whole(options.get("months"), "months", 1, 600)
    components = options.get("components")
    if not isinstance(components, list) or not 0 < len(components) <= 100:
        raise EconomicsError("Components: 1-100 entries")
    low, high, names, unknown = Money(0), Money(0), [], []
    for item in components:
        if not isinstance(item, dict) or set(item) != {"name", "monthly_usd_low", "monthly_usd_high"}:
            raise EconomicsError("Component: name, monthly_usd_low, monthly_usd_high")
        name = _identifier(item["name"])
        if name in names:
            raise EconomicsError("Component: duplicate name")
        names.append(name)
        first, second = measured(item["monthly_usd_low"], Money), measured(item["monthly_usd_high"], Money)
        if is_unknown(first) or is_unknown(second):
            unknown.append(name)
        elif first > second:
            raise EconomicsError("Component: low above high")
        low, high = low + first * months, high + second * months
    return as_json({"kind": "ESTIMATE", "label": ESTIMATE, "measured": False, "months": months,
                    "money": {"low": low, "high": high}, "components_with_unknown_cost": unknown,
                    "assumptions": {"components": names, "source": "supplied monthly ranges; no provider price is built in"}})


def _from_json(value, kind):
    return measured("unknown" if value == "unknown" else value["value"], kind)


def _scaled(build, shares):
    if not isinstance(build, dict) or build.get("kind") != "ESTIMATE" or not isinstance(build.get("tokens"), dict):
        raise EconomicsError("Build: an ESTIMATE from estimate_scope")
    tokens, money = {}, {}
    for end, share in zip(("low", "high"), shares):
        amount = total([_from_json(build["tokens"][k][end], Tokens) for k in ("input", "output")], Tokens) * share
        tokens[end] = amount if is_unknown(amount) else Tokens(int(amount.value.to_integral_value()))
        money[end] = _from_json(build["money"][end], Money) * share
    return tokens, money


@_guarded
def estimate_maintenance(build, assumptions=None):
    """ESTIMATE of maintenance as a yearly share of a build estimate (a planning assumption)."""
    options = _assumptions(assumptions, {"share_per_year", "years"})
    shares = _range(options.get("share_per_year", DEFAULT_MAINTENANCE_PER_YEAR), "share_per_year", "0", "5")
    years = _whole(options.get("years", 1), "years", 1, 50)
    tokens, money = _scaled(build, (shares[0] * years, shares[1] * years))
    return as_json({"kind": "ESTIMATE", "label": ESTIMATE, "measured": False, "years": years,
                    "tokens": tokens, "money": money,
                    "assumptions": {"share_per_year": list(shares),
                                    "basis": "supplied, or the default planning range 0.15-0.25 of build per year; "
                                             "a planning assumption, not measured in this repository"}})


@_guarded
def estimate_rework(build, assumptions=None, *, measured_waste_share=None):
    """ESTIMATE of rework as a share of a build estimate; a measured ledger waste share wins over defaults."""
    options = _assumptions(assumptions, {"rework_share"})
    if measured_waste_share is not None and "rework_share" not in options:
        share = _fraction(measured_waste_share, "measured_waste_share")
        shares, basis = (share, share), "measured waste share (retries and rework) of a ledger"
    else:
        measured_range = build["assumptions"]["second_attempt_share"] if isinstance(build, dict) else None
        if "rework_share" not in options and measured_range is None:
            raise EconomicsError("Rework share: supply rework_share; the build has no measured second-attempt share")
        shares = _range(options.get("rework_share", measured_range), "rework_share", "0", "1")
        basis = "supplied" if "rework_share" in options else (
            "the build estimate's measured second-attempt share: its configurations' failure share to the worst "
            "measured failure rate of any stage of those sizes")
    tokens, money = _scaled(build, shares)
    return as_json({"kind": "ESTIMATE", "label": ESTIMATE, "measured": False, "tokens": tokens, "money": money,
                    "assumptions": {"rework_share": list(shares), "basis": basis}})


# ---------------------------------------------------------------- measured inputs

SOURCES = {
    "phase1_ladder": "swarm/evidence/ladder.json",
    "phase1_tool_audit": "swarm/evidence/tool-audit.json",
    "phase2_stages": "swarm/phase2/evidence/stages.json",
    "phase2_results": "swarm/phase2/RESULTS.md",
    "phase2_readme": "swarm/phase2/README.md",
    "phase2_plan": "swarm/phase2/PLAN.json",
    "phase3_team": "swarm/phase3/evidence/team.json",
    "phase3_team2": "swarm/phase3/evidence/team2.json",
    "phase3_coordinator_scale": "swarm/phase3/evidence/coordinator-scale.json",
}
PENDING = {"phase3_1000_agent_run": {
    "status": "pending (owned by swarm session)",
    "expected_sources": ["swarm/phase3/evidence/stages.json", "swarm/phase3/RESULTS-FINAL.md"],
    "note": "Not read by this baseline; cite it only after the swarm session publishes it."}}
TOKENIZER_MODULES = ("anthropic", "litellm", "sentencepiece", "tiktoken", "tokenizers", "transformers")
APPROXIMATE = "characters / 4 (approximate; not a tokenizer count)"


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(root, key):
    path = Path(root) / SOURCES[key]
    try:
        text = path.read_text(encoding="utf-8")
        return text if path.suffix == ".md" else json.loads(text)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise EconomicsError(f"Evidence not readable: {SOURCES[key]}") from error


def _cell(text):
    text = text.strip().replace(",", "")
    if re.fullmatch(r"\d+", text):
        return int(text)
    if re.fullmatch(r"\d+\.\d+", text):
        return float(text)
    if re.fullmatch(r"\d+/\d+", text):
        done, of = text.split("/")
        return {"verified": int(done), "of": int(of)}
    return text


@_guarded
def read_results_table(text):
    """Rows of the generated Markdown table in swarm/phase2/RESULTS.md, keyed by its header."""
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        raise EconomicsError("Results table not found")
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:
        cells = line.strip("|").split("|")
        if len(cells) != len(header):
            raise EconomicsError("Results table row has the wrong number of cells")
        rows.append({name: _cell(cell) for name, cell in zip(header, cells)})
    return rows


def _stage(document, label, key="stages"):
    for stage in document.get(key, []):
        if isinstance(stage, dict) and stage.get("label") == label:
            return stage
    raise EconomicsError(f"Stage {label} not in evidence")


def _cite(value, source, field):
    return {"value": value, "source": source, "field": field}


def _tokenizers_importable():
    found = []
    for name in TOKENIZER_MODULES:
        try:
            if importlib.util.find_spec(name) is not None:
                found.append(name)
        except (ImportError, ValueError):
            continue
    return found


@_guarded
def context_footprint(root=None):
    """Re-measure what a session in `root` loads from the repository, by a stated method.

    Always loaded: CLAUDE.md with its one-level @ imports (swarm/phase3/
    context_budget's rule) and the name + description of every project skill and
    agent (the listing a session carries). Loaded on demand: full skill bodies and
    agent definitions. Host system prompt, tool schemas and connectors are not in
    the tree and are reported as unknown. Tokens are characters / 4.
    """
    root = Path(root) if root else _ROOT
    budget = _swarm("context_budget")

    def entry(path, label):
        text = path.read_text(encoding="utf-8")
        return {"file": label, "chars": len(text), "utf8_bytes": len(text.encode("utf-8")),
                "non_ascii_chars": sum(ord(c) > 127 for c in text), "sha256": _file_sha(path),
                "tokens_approx": len(text) // 4}

    instructions = []
    for row in budget._instruction_files(root):
        item = entry(root / row["file"], row["file"])
        if "via" in row:
            item["via"] = row["via"]
        instructions.append(item)
    listings, bodies = {"skills": [], "agents": []}, {"skills": [], "agents": []}
    for kind, pattern in (("skills", ".claude/skills/*/SKILL.md"), ("agents", ".claude/agents/*.md")):
        for path in sorted(root.glob(pattern)):
            front, _ = budget._split(path.read_text(encoding="utf-8"))
            name, description = budget._field(front, "name") or "", budget._field(front, "description") or ""
            label = path.relative_to(root).as_posix()
            listing = len(name) + len(description)
            listings[kind].append({"file": label, "name": name, "listing_chars": listing,
                                   "listing_tokens_approx": listing // 4, "sha256": _file_sha(path)})
            bodies[kind].append(entry(path, label))
    always = (sum(r["chars"] for r in instructions) + sum(r["listing_chars"] for r in listings["skills"])
              + sum(r["listing_chars"] for r in listings["agents"]))
    demand = sum(r["chars"] for r in bodies["skills"]) + sum(r["chars"] for r in bodies["agents"])
    workers = {a["name"]: {"chars": a["chars"], "tokens_approx": a["chars"] // 4}
               for a in budget.budget(root)["agents"] if a["name"].startswith("swarm-light")}
    found = _tokenizers_importable()
    return {"method": {"tokens": APPROXIMATE, "rule": "tokens_approx = characters // 4, per item and on each total",
                       "tokenizers_importable": found,
                       "why": ("no tokenizer module is installed, and no Claude tokenizer is available offline" if not found
                               else "a tokenizer module is importable but none is Claude's; characters / 4 is kept"),
                       "includes": "repository files only; not the host's system prompt, tool schemas or connectors",
                       "listing_rule": "a skill or agent listing counts its name and description characters only",
                       "non_ascii_note": "characters / 4 tends to undercount non-ASCII (for example Arabic) text"},
            "always_loaded": {"instruction_files": instructions, "skill_listing": listings["skills"],
                              "agent_listing": listings["agents"], "chars": always, "tokens_approx": always // 4},
            "on_demand": {"skill_bodies": bodies["skills"], "agent_definitions": bodies["agents"],
                          "chars": demand, "tokens_approx": demand // 4},
            "lean_worker_definitions": workers,
            "host_controlled_context": "unknown"}


@_guarded
def measured_baseline(root=None):
    """Every measured L19 input with its source path; reproduced, cited or unknown, and why."""
    root = Path(root) if root else _ROOT
    ladder, audit = _load(root, "phase1_ladder"), _load(root, "phase1_tool_audit")
    stages, results = _load(root, "phase2_stages"), read_results_table(_load(root, "phase2_results"))
    team, team2 = _load(root, "phase3_team"), _load(root, "phase3_team2")
    coordinator, plan = _load(root, "phase3_coordinator_scale"), _load(root, "phase2_plan")
    swarm_economics = _swarm("economics")
    rows = {row["label"]: row for row in swarm_economics.per_task(stages)}
    p1, p2 = _stage(ladder, "s20", "ladder"), _stage(stages, "s20")
    general, lean = audit["first_request_context_tokens"]["median"], p2["first_request_context"]["median"]

    def tpm(stage):
        return round(stage["verified_tasks"] / stage["wall_seconds"] * 60, 2)

    per_task_before, per_task_after = p1["per_verified_task"]["input_total"], p2["per_verified_task"]["input_total"]
    headline = {
        "first_request_context_tokens": {
            "before": _cite(general, SOURCES["phase1_tool_audit"], "first_request_context_tokens.median"),
            "after": _cite(lean, SOURCES["phase2_stages"], "stages[s20].first_request_context.median"),
            "reduction_percent": round((1 - lean / general) * 100, 2),
            "status": "cited, not reproduced",
            "why": "a host-reported size of a whole first request (host system prompt, tool schemas, connectors and the "
                   "worker definition); it needs live agents on the host, so it cannot be re-measured offline. The part "
                   "this tree controls is re-measured under context_footprint."},
        "input_tokens_per_verified_small_task_20_agents": {
            "before": _cite(per_task_before, SOURCES["phase1_ladder"], "ladder[s20].per_verified_task.input_total"),
            "after": _cite(per_task_after, SOURCES["phase2_stages"], "stages[s20].per_verified_task.input_total"),
            "recomputed": {"before": round(p1["agent_tokens"]["input_total"] / p1["verified_tasks"]),
                           "after": round(p2["agent_tokens"]["input_total"] / p2["verified_tasks"]),
                           "rule": "agent_tokens.input_total / verified_tasks, rounded"},
            "reduction_percent": round((1 - per_task_after / per_task_before) * 100, 2),
            "status": "arithmetic reproduced from the evidence files; not re-measured (needs live agents)"},
        "tasks_per_minute_20_agents": {
            "before": _cite(p1["tasks_per_minute"], SOURCES["phase1_ladder"], "ladder[s20].tasks_per_minute"),
            "after": _cite(p2["tasks_per_minute"], SOURCES["phase2_stages"], "stages[s20].tasks_per_minute"),
            "recomputed": {"before": tpm(p1), "after": tpm(p2),
                           "rule": "verified_tasks / wall_seconds x 60 from the rounded wall_seconds in the file"},
            "ratio": round(p2["tasks_per_minute"] / p1["tasks_per_minute"], 2),
            "status": "arithmetic reproduced to the rounding of the published wall seconds; not re-measured (needs live agents)"},
    }
    table_checks = []
    for row in results:
        stage = _stage(stages, row["Stage"])
        checks = {"Tasks/min": stage.get("tasks_per_minute"), "Input tokens": stage["agent_tokens"]["input_total"],
                  "Per verified task": stage["per_verified_task"]["input_total"],
                  "Cost units per task": stage.get("per_verified_task_cost_units")}
        mismatched = sorted(name for name, value in checks.items() if row.get(name) != value)
        table_checks.append({"stage": row["Stage"], "agrees_with_stages_json": not mismatched, "mismatched": mismatched})
    split = {}
    for stage in stages["stages"]:
        if stage.get("kind") != "task":
            continue
        agent, orchestrator = stage["agent_tokens"], stage.get("orchestrator_tokens") or {}
        split[stage["label"]] = {
            "agents": stage["actual_agents"], "verified": stage["verified_tasks"],
            "worker": {"input": agent["input_total"], "cache_read": agent["cache_read"], "cache_write": agent["cache_write"],
                       "output": agent["output"]},
            "coordinator": {"input": orchestrator.get("input_total"), "cache_read": orchestrator.get("cache_read"),
                            "cache_write": orchestrator.get("cache_write"), "output": orchestrator.get("output")},
            "reviewer": "unknown",
            "coordinator_share_of_all_tokens": stage.get("orchestrator_share_of_all_tokens"),
            "cache_read_share_of_worker_input": stage.get("cache_read_share"),
            "worker_tokens_per_verified_task": (round((agent["input_total"] + agent["output"]) / stage["verified_tasks"])
                                                if stage["verified_tasks"] else "unknown"),
            "cost_units_per_verified_task": rows[stage["label"]]["cost_units_per_task"],
            "not_verified": len(stage.get("not_verified") or []), "retries": "unknown"}
    team_waves = waves_from_evidence(team, SOURCES["phase3_team"]) + waves_from_evidence(team2, SOURCES["phase3_team2"])
    small = {w["label"]: w for w in waves_from_evidence(stages, SOURCES["phase2_stages"])
             if w["label"] in ("c1", "s10", "s20", "s25", "s50", "s75", "s100")}
    budget_left = stages["caps"]["cumulative_input_tokens"] - stages["figures"]["input_tokens_counted"]
    limits = {"start": 4, "max_agents": 20, "max_batch": 8, "tokens_left": budget_left}
    demos = {
        "phase2_c1_then_s10": recommend_concurrency([small["c1"], small["s10"]], limits),
        "phase2_s10_then_s20": recommend_concurrency([small["s10"], small["s20"]], limits),
        "phase2_s20_then_s25": recommend_concurrency([small["s20"], small["s25"]], limits),
        "phase3_team_then_team2": recommend_concurrency(team_waves, {"start": 4, "max_agents": 20, "max_batch": 1}),
        "limits_note": "max_agents 20 is the host's measured ceiling (swarm/phase2/README.md finding 2); tokens_left is "
                       "the phase-2 cap minus its counted input tokens (swarm/phase2/evidence/stages.json caps, figures)"}
    lanes = {}
    for key, document in (("phase3_team", team), ("phase3_team2", team2)):
        used = sorted(lane["agent"]["input_tokens"] + lane["agent"]["output_tokens"] for lane in document["lanes"])
        seconds = sorted(lane["agent"]["seconds"] for lane in document["lanes"])
        lanes[key] = {"lanes": len(used), "tokens_per_lane": {"min": used[0], "median": statistics.median(used),
                                                              "max": used[-1]},
                      "agent_seconds_per_lane": {"min": seconds[0], "median": statistics.median(seconds),
                                                 "max": seconds[-1]},
                      "tests_added": document["totals"]["tests_added_joined"],
                      "suite_after_joining_passed": document["suite_after_joining"]["passed"],
                      "source": SOURCES[key]}
    rework = {"lanes": len(team2["lanes"]),
              "lanes_needing_repair_by_the_setting_session": sum(lane["state"] != "joined" for lane in team2["lanes"]),
              "of_which_conflicts": team_waves[1]["conflicts"], "of_which_own_tests_failed": team_waves[1]["failures"],
              "rework_tokens": "unknown", "suite_after_joining_passed": team2["suite_after_joining"]["passed"],
              "source": SOURCES["phase3_team2"]}
    return {
        "headline_comparisons": headline,
        "results_table_cross_check": {"source": SOURCES["phase2_results"], "against": SOURCES["phase2_stages"],
                                      "rows": table_checks},
        "consumption_by_stage": {"source": SOURCES["phase2_stages"], "stages": split},
        "development_waves": team_waves,
        "development_lanes": {**lanes, "note": "each lane built one module of this repository with its tests: real "
                                                "development work, unlike the generated stand-in tasks"},
        "rework_measured": rework,
        "small_task_waves": list(small.values()),
        "recommender_on_measured_waves": demos,
        "coordinator_machinery": {"gate": coordinator["measured"]["gate"], "ledger_build": coordinator["measured"]["ledger_build"],
                                  "source": SOURCES["phase3_coordinator_scale"],
                                  "note": "CPU-side cost of the queue, gate and ledger; no agent and no model ran"},
        "cost_weights": {**plan["cost_weights"], "source": SOURCES["phase2_plan"]},
        "pending": PENDING}


@_guarded
def baseline_document(root=None, *, date):
    """The public-safe evidence document: measurements, method, date and source paths with digests."""
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise EconomicsError("Date: YYYY-MM-DD")
    root = Path(root) if root else _ROOT
    footprint = context_footprint(root)
    baseline = measured_baseline(root)
    evidence = _load(root, "phase2_stages")
    estimates = {scope: estimate_scope(scope, evidence) for scope in SCOPES}
    estimates["maintenance_of_mvp"] = estimate_maintenance(estimates["mvp"])
    estimates["rework_of_mvp"] = estimate_rework(estimates["mvp"])
    first = baseline["headline_comparisons"]["first_request_context_tokens"]
    return {
        "schema_version": 1, "kind": "economics-baseline", "layer": "L19", "measured_on": date,
        "about": "Counts, sizes and figures only; no prompt, record content, secret or customer data.",
        "method": {"code": "engineering_os/economics.py (baseline_document)",
                   "command": f"python3 -m engineering_os.economics baseline --date {date} "
                              "--out docs/evidence/gaie-20-layers/economics-baseline.json",
                   "deterministic": True, "provider_calls": 0, "agents_run": 0,
                   "context_tokens": footprint["method"]},
        "sources": {key: {"path": path, "sha256": _file_sha(root / path)} for key, path in sorted(SOURCES.items())},
        "context_footprint": footprint,
        "context_comparison": {
            "repository_always_loaded_tokens_approx": footprint["always_loaded"]["tokens_approx"],
            "previously_reported_general_worker_first_request_tokens": first["before"],
            "previously_reported_lean_worker_first_request_tokens": first["after"],
            "reading": "The previously reported figures are host-reported whole-request sizes and are cited, not "
                       "reproduced; the repository-controlled part of a session in this tree is measured above. "
                       "The difference is host-controlled context, unknown offline."},
        "measured": baseline,
        "estimates": estimates,
        "units": {"tokens": "tokens", "money": "USD, only from supplied rates or billed items (unknown here)",
                  "quota": "unknown (not observable)", "time": "seconds", "unknown": "\"unknown\", never 0"}}


# ---------------------------------------------------------------- engine contract

ACTIONS = {
    "summarize": "Aggregate a schema 1 or 2 usage ledger.",
    "assess": "Typed L19 metrics of a ledger, with units and unknowns.",
    "recommend-concurrency": "Next agent count and batch from measured waves.",
    "estimate-scope": "ESTIMATE for a feature, an MVP or an enterprise system.",
    "estimate-infrastructure": "ESTIMATE of infrastructure cost from supplied ranges.",
    "estimate-maintenance": "ESTIMATE of maintenance from a build estimate.",
    "estimate-rework": "ESTIMATE of rework from a build estimate.",
    "context-footprint": "Re-measure the repository context a session loads.",
    "measured-baseline": "Measured inputs from the swarm evidence, with sources.",
}


def engine(action, payload, ctx=None):
    """Contract entrypoint (action, payload, ctx) -> dict. Read-only; no model or tool is invoked.

    The repository root is never taken from the payload: file-reading actions use
    this checkout, or ctx["root"] when the control plane supplies one.
    """
    if action not in ACTIONS:
        raise EconomicsError("Unknown economics action")
    if not isinstance(payload, dict) or (ctx is not None and not isinstance(ctx, dict)):
        raise EconomicsError("Payload and context: objects")
    root = Path((ctx or {}).get("root") or _ROOT)
    if action == "summarize":
        return summarize(payload.get("ledger"))
    if action == "assess":
        return assess(payload.get("ledger"))
    if action == "recommend-concurrency":
        return recommend_concurrency(payload.get("waves"), payload.get("limits"))
    if action == "estimate-infrastructure":
        return estimate_infrastructure(payload.get("assumptions"))
    if action in ("estimate-scope", "estimate-maintenance", "estimate-rework"):
        key = "assumptions" if action == "estimate-scope" else "build_assumptions"
        build = estimate_scope(payload.get("scope"), _load(root, "phase2_stages"), payload.get(key))
        if action == "estimate-scope":
            return build
        if action == "estimate-maintenance":
            return estimate_maintenance(build, payload.get("assumptions"))
        return estimate_rework(build, payload.get("assumptions"))
    if action == "context-footprint":
        return context_footprint(root)
    return measured_baseline(root)


def health():
    """Side-effect free check that the reused swarm code is present and callable."""
    missing = []
    for name, (relative, attribute) in _SWARM.items():
        try:
            if not callable(getattr(_swarm(name), attribute, None)):
                missing.append(f"{relative}:{attribute}")
        except (EconomicsError, OSError, SyntaxError, ImportError):
            missing.append(relative)
    if missing:
        return {"ok": False, "detail": "swarm code not usable: " + ", ".join(missing)}
    return {"ok": True, "detail": "ledger, units, estimates and recommender ready; "
                                  "swarm adaptive, economics and context_budget loaded read-only"}


def recommend_model(registry, request, evidence=None, *, environ=None, now=None):
    """Reuse the existing gated model router; selection is not usage or spending."""
    return select_model(registry, request, evidence, environ=environ, now=now)


def main(argv=None):
    parser = argparse.ArgumentParser(description="GAIE L19 engineering economics (offline, read-only).")
    sub = parser.add_subparsers(dest="command", required=True)
    base = sub.add_parser("baseline", help="Measured baseline document with sources")
    base.add_argument("--date", required=True)
    base.add_argument("--root", type=Path, default=_ROOT)
    base.add_argument("--out", type=Path)
    base.add_argument("--check", action="store_true", help="Exit 1 if --out differs from a fresh measurement")
    foot = sub.add_parser("footprint", help="Repository context a session loads")
    foot.add_argument("--root", type=Path, default=_ROOT)
    args = parser.parse_args(argv)
    if args.command == "footprint":
        print(json.dumps(context_footprint(args.root), ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    text = json.dumps(baseline_document(args.root, date=args.date), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out and args.out.is_file() else None
        print("baseline is current" if current == text else "baseline is stale; regenerate it")
        return 0 if current == text else 1
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
