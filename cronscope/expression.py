"""A parsed cron expression, and the computation of when it next fires.

The subtle part — the one nearly every home-grown cron parser gets wrong — is
the day matching rule:

    If BOTH day-of-month and day-of-week are restricted (neither is '*'), the
    job runs when EITHER matches, not both. If only one is restricted, only that
    one applies.

This is why `0 0 13 * 5` runs every Friday AND on the 13th of every month, not
only on Friday the 13th. Vixie cron documents it; most reimplementations miss
it and silently run jobs on the wrong days. `day_matches` encodes it explicitly,
and the test suite pins the exact cases.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta

from .field import (
    DAY_OF_MONTH,
    DAY_OF_WEEK,
    HOUR,
    MINUTE,
    MONTH,
    FieldError,
    parse_field,
)

# @-shortcuts, expanded to their canonical five-field form.
MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

# @reboot has no schedule — it fires once when cron starts. It is valid but has
# no "next run", so it is represented explicitly rather than parsed as fields.
REBOOT = "@reboot"


class CronError(ValueError):
    """Raised when an expression cannot be parsed."""


@dataclass(frozen=True)
class CronExpression:
    minutes: frozenset[int]
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]
    raw: str
    dom_restricted: bool     # was day-of-month something other than '*'?
    dow_restricted: bool     # was day-of-week something other than '*'?
    is_reboot: bool = False

    @classmethod
    def parse(cls, expr: str) -> CronExpression:
        expr = expr.strip()
        if not expr:
            raise CronError("empty expression")

        if expr == REBOOT:
            empty = frozenset()
            return cls(empty, empty, empty, empty, empty, expr, False, False, True)

        if expr.startswith("@"):
            if expr not in MACROS:
                raise CronError(f"unknown macro {expr!r}")
            fields_src = MACROS[expr]
        else:
            fields_src = expr

        parts = fields_src.split()
        if len(parts) != 5:
            raise CronError(
                f"expected 5 fields, got {len(parts)}: {expr!r}")

        try:
            minutes = parse_field(parts[0], MINUTE)
            hours = parse_field(parts[1], HOUR)
            doms = parse_field(parts[2], DAY_OF_MONTH)
            months = parse_field(parts[3], MONTH)
            dows = parse_field(parts[4], DAY_OF_WEEK)
        except FieldError as exc:
            raise CronError(str(exc)) from exc

        return cls(
            minutes, hours, doms, months, dows, expr,
            dom_restricted=parts[2].strip() != "*",
            dow_restricted=parts[4].strip() != "*",
        )

    # ── matching ────────────────────────────────────────────────────────────

    def day_matches(self, when: datetime) -> bool:
        """Apply the day-of-month / day-of-week OR rule."""
        dom_ok = when.day in self.days_of_month
        # Python weekday(): Monday=0..Sunday=6. Cron: Sunday=0..Saturday=6.
        cron_dow = (when.weekday() + 1) % 7
        dow_ok = cron_dow in self.days_of_week

        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok      # the surprising, correct behaviour
        if self.dom_restricted:
            return dom_ok
        if self.dow_restricted:
            return dow_ok
        return True                      # both '*'

    def matches(self, when: datetime) -> bool:
        return (
            when.minute in self.minutes
            and when.hour in self.hours
            and when.month in self.months
            and self.day_matches(when)
        )

    # ── next run ──────────────────────────────────────────────────────────────

    def next_run(self, after: datetime) -> datetime | None:
        """The first fire time strictly after `after`.

        @reboot has no scheduled time, so returns None. The search walks forward
        a minute at a time but skips whole days and months that cannot match, so
        even a once-a-year job resolves in well under a second rather than
        scanning 525,600 minutes.
        """
        if self.is_reboot:
            return None

        # Start at the next whole minute after `after`.
        t = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)

        # A cap so a pathologically impossible expression (e.g. Feb 30) returns
        # None instead of looping forever. Eight years covers every leap-year
        # and weekday alignment a valid expression could need.
        limit = t + timedelta(days=366 * 8)
        while t <= limit:
            if t.month not in self.months:
                t = _first_of_next_month(t)
                continue
            if not self.day_matches(t):
                t = (t + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if t.hour not in self.hours:
                t = (t + timedelta(hours=1)).replace(minute=0)
                continue
            if t.minute not in self.minutes:
                t = t + timedelta(minutes=1)
                continue
            return t
        return None

    def next_runs(self, after: datetime, count: int) -> list[datetime]:
        out = []
        cur = after
        for _ in range(count):
            nxt = self.next_run(cur)
            if nxt is None:
                break
            out.append(nxt)
            cur = nxt
        return out


def _first_of_next_month(t: datetime) -> datetime:
    days_in_month = calendar.monthrange(t.year, t.month)[1]
    return t.replace(day=days_in_month, hour=23, minute=59) + timedelta(minutes=1)
