"""The heart of the tool: field parsing and next-run computation.

next_run correctness is checked against hand-verified datetimes, with the
day-of-month / day-of-week OR rule pinned explicitly because it is the thing
reimplementations get wrong.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from cronscope.expression import CronError, CronExpression
from cronscope.field import (
    DAY_OF_WEEK,
    MINUTE,
    MONTH,
    FieldError,
    parse_field,
)


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def nxt(expr: str, after: str) -> datetime | None:
    return CronExpression.parse(expr).next_run(dt(after))


# ── field parsing ───────────────────────────────────────────────────────────

def test_star_expands_to_full_range():
    assert parse_field("*", MINUTE) == frozenset(range(60))


def test_step_over_star():
    assert parse_field("*/15", MINUTE) == frozenset({0, 15, 30, 45})


def test_range():
    assert parse_field("1-5", MINUTE) == frozenset({1, 2, 3, 4, 5})


def test_list_and_range_combined():
    assert parse_field("1,3,10-12", MINUTE) == frozenset({1, 3, 10, 11, 12})


def test_range_with_step():
    assert parse_field("0-20/5", MINUTE) == frozenset({0, 5, 10, 15, 20})


def test_single_value_with_step_runs_to_max():
    # "5/15" means from 5 to the field max, stepping 15.
    assert parse_field("5/15", MINUTE) == frozenset({5, 20, 35, 50})


def test_month_names():
    assert parse_field("jan", MONTH) == frozenset({1})
    assert parse_field("JAN-mar", MONTH) == frozenset({1, 2, 3})


def test_weekday_sunday_alias():
    # 7 and 0 both mean Sunday and must land on the same value.
    assert parse_field("7", DAY_OF_WEEK) == frozenset({0})
    assert parse_field("0", DAY_OF_WEEK) == frozenset({0})


@pytest.mark.parametrize("bad", ["", "99", "5-2", "*/0", "abc", "60"])
def test_bad_fields_raise(bad):
    with pytest.raises(FieldError):
        parse_field(bad, MINUTE)


# ── expression parsing ──────────────────────────────────────────────────────

def test_macro_expansion():
    # @daily must match the same times as "0 0 * * *". The `raw` string is
    # deliberately preserved as-typed, so compare the matched fields, not the
    # whole dataclass.
    macro = CronExpression.parse("@daily")
    explicit = CronExpression.parse("0 0 * * *")
    assert (macro.minutes, macro.hours, macro.days_of_month,
            macro.months, macro.days_of_week) == (
        explicit.minutes, explicit.hours, explicit.days_of_month,
        explicit.months, explicit.days_of_week)


def test_reboot_has_no_next_run():
    expr = CronExpression.parse("@reboot")
    assert expr.is_reboot
    assert expr.next_run(datetime.now()) is None


@pytest.mark.parametrize("bad", ["", "1 2 3", "1 2 3 4 5 6", "@nope", "* * * *"])
def test_bad_expressions_raise(bad):
    with pytest.raises(CronError):
        CronExpression.parse(bad)


# ── next_run: the core ──────────────────────────────────────────────────────

def test_every_15_minutes():
    assert nxt("*/15 * * * *", "2026-01-01T10:07") == dt("2026-01-01T10:15")


def test_daily_time_rolls_to_next_day():
    assert nxt("30 2 * * *", "2026-01-01T10:00") == dt("2026-01-02T02:30")


def test_strictly_after_never_returns_the_input():
    # 10:15 is a fire minute; asking "after 10:15" must give the next one.
    assert nxt("*/15 * * * *", "2026-01-01T10:15") == dt("2026-01-01T10:30")


def test_dom_and_dow_both_set_is_OR_not_and():
    """0 0 13 * 5 must fire every Friday AND on the 13th.

    From 2026-01-01 (a Thursday), Friday the 2nd comes before the 13th, so the
    next run is the 2nd — proving OR, not AND. Under a wrong AND implementation
    this would jump to the first Friday-the-13th instead.
    """
    assert nxt("0 0 13 * 5", "2026-01-01T00:00") == dt("2026-01-02T00:00")


def test_dom_only_restricted_uses_dom():
    assert nxt("0 0 13 * *", "2026-01-01T00:00") == dt("2026-01-13T00:00")


def test_dow_only_restricted_uses_dow():
    assert nxt("0 0 * * 5", "2026-01-01T00:00") == dt("2026-01-02T00:00")


def test_sunday_as_7_matches_sunday():
    assert nxt("0 0 * * 7", "2026-01-01T00:00").weekday() == 6   # Sunday


def test_named_month_and_weekday():
    result = nxt("0 12 * jul mon", "2026-06-01T00:00")
    assert result == dt("2026-07-06T12:00")
    assert result.strftime("%A") == "Monday"


def test_impossible_schedule_returns_none():
    # 30 February never occurs.
    assert nxt("0 0 30 2 *", "2026-01-01T00:00") is None


def test_leap_day_resolves_in_a_leap_year():
    # Feb 29 exists in 2028; from 2026 the next run is 2028-02-29.
    assert nxt("0 0 29 2 *", "2026-03-01T00:00") == dt("2028-02-29T00:00")


def test_yearly_crosses_the_year_boundary():
    assert nxt("@yearly", "2026-06-01T00:00") == dt("2027-01-01T00:00")


def test_next_runs_returns_sequence_in_order():
    runs = CronExpression.parse("0 * * * *").next_runs(dt("2026-01-01T10:30"), 3)
    assert runs == [dt("2026-01-01T11:00"), dt("2026-01-01T12:00"),
                    dt("2026-01-01T13:00")]


def test_next_runs_stops_on_impossible_schedule():
    assert CronExpression.parse("0 0 31 2 *").next_runs(datetime.now(), 5) == []
