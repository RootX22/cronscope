"""Parse a single cron field into the concrete set of values it matches.

A cron field is one of the five columns (minute, hour, day-of-month, month,
day-of-week). Each supports the same grammar:

    *            every value in range
    5            a single value
    1,3,5        a list
    1-5          a range
    */15         a step over the whole range
    1-20/2       a step over a sub-range
    JAN / MON    three-letter names (month and weekday only)

The parser is deliberately strict: a field that does not fit the grammar or
falls outside its range raises FieldError, because a crontab that "sort of"
parses is how a job silently never runs. Returning the matched values as a
frozenset keeps membership testing trivial for the next-run search.
"""

from __future__ import annotations

from dataclasses import dataclass

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# Cron accepts both 0 and 7 for Sunday. We normalise 7 -> 0 on the way in so the
# matched set is always in 0..6, which the schedule search relies on.
WEEKDAYS = {d: i for i, d in enumerate(
    ["sun", "mon", "tue", "wed", "thu", "fri", "sat"], start=0)}


class FieldError(ValueError):
    """Raised when a field does not match the cron grammar or is out of range."""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    min_val: int
    max_val: int
    names: dict[str, int] | None = None   # month/weekday name lookups
    # Day-of-week 7 is an alias for 0 (Sunday); normalised during parsing.
    sunday_alias: bool = False


MINUTE = FieldSpec("minute", 0, 59)
HOUR = FieldSpec("hour", 0, 23)
DAY_OF_MONTH = FieldSpec("day-of-month", 1, 31)
MONTH = FieldSpec("month", 1, 12, names=MONTHS)
DAY_OF_WEEK = FieldSpec("day-of-week", 0, 6, names=WEEKDAYS, sunday_alias=True)


def _resolve(token: str, spec: FieldSpec) -> int:
    """Turn a single token — a number or a name — into an int in range."""
    key = token.strip().lower()
    if spec.names and key in spec.names:
        return spec.names[key]
    try:
        value = int(key)
    except ValueError as exc:
        raise FieldError(f"{spec.name}: {token!r} is not a number or a known name") from exc

    if spec.sunday_alias and value == 7:
        value = 0
    if not (spec.min_val <= value <= spec.max_val):
        raise FieldError(
            f"{spec.name}: {value} is outside {spec.min_val}-{spec.max_val}")
    return value


def parse_field(raw: str, spec: FieldSpec) -> frozenset[int]:
    """Expand one field into the full set of matching values."""
    raw = raw.strip()
    if not raw:
        raise FieldError(f"{spec.name}: empty field")

    matched: set[int] = set()
    for part in raw.split(","):
        matched |= _parse_part(part.strip(), spec)
    return frozenset(matched)


def _parse_part(part: str, spec: FieldSpec) -> set[int]:
    if not part:
        raise FieldError(f"{spec.name}: empty list element")

    step = 1
    if "/" in part:
        base, _, step_s = part.partition("/")
        try:
            step = int(step_s)
        except ValueError as exc:
            raise FieldError(f"{spec.name}: step {step_s!r} is not an integer") from exc
        if step <= 0:
            raise FieldError(f"{spec.name}: step must be positive, got {step}")
    else:
        base = part

    # Determine the range this part covers before applying the step.
    if base == "*":
        lo, hi = spec.min_val, spec.max_val
    elif "-" in base and not base.lstrip("-").startswith("-"):
        lo_s, _, hi_s = base.partition("-")
        lo, hi = _resolve(lo_s, spec), _resolve(hi_s, spec)
        # A bare "5/15" (single value with a step) means "from 5 to max step 15".
    else:
        lo = _resolve(base, spec)
        hi = spec.max_val if "/" in part else lo

    if lo > hi:
        raise FieldError(f"{spec.name}: range {base!r} runs backwards ({lo} > {hi})")

    values = set(range(lo, hi + 1, step))

    # Sunday-as-7 inside a range (e.g. "0-7") would have produced a 7; fold it.
    if spec.sunday_alias and 7 in values:
        values.discard(7)
        values.add(0)
    return values
