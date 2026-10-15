"""The money path. Times below are written in SAST (UTC+2) and converted, so
each case reads the way the farm would describe it."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from pay import NoRateError, day_pay, pair_shifts, within

SAST = timedelta(hours=2)
NOW = datetime(2026, 10, 20, 12, 0) - SAST


def scan(uuid, local, direction, worker="001"):
    return NS(uuid=uuid, worker_id=worker, timestamp=local - SAST, direction=direction)


def rate(eff=date(2026, 1, 1), hourly=30.0, mult=1.5, daily=9.0, weekly=45.0, id=1):
    return NS(id=id, effective_date=eff, hourly_rate=hourly, ot_multiplier=mult,
              daily_ot_after_h=daily, weekly_ot_after_h=weekly)


def d(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm)


def test_in_out_makes_a_shift():
    p = pair_shifts([scan("a", d(12, 7), "in"), scan("b", d(12, 16), "out")], NOW)
    assert [(s.day, s.hours) for s in p.shifts] == [(date(2026, 10, 12), 9.0)]
    assert not p.exceptions and not p.open


def test_duplicate_within_60s_is_dropped():
    p = pair_shifts([scan("a", d(12, 7), "in"), scan("dup", d(12, 7) + timedelta(seconds=30), "out"),
                     scan("b", d(12, 16), "out")], NOW)
    assert len(p.shifts) == 1 and p.shifts[0].out_uuid == "b"
    assert not p.exceptions


def test_missed_exit_flags_one_shift_and_nothing_else_moves():
    p = pair_shifts([scan("a", d(12, 7), "in"),                       # forgot to scan out
                     scan("b", d(13, 7), "in"), scan("c", d(13, 17), "out")], NOW)
    assert [(e.kind, e.uuid) for e in p.exceptions] == [("missing_exit", "a")]
    assert [(s.in_uuid, s.out_uuid) for s in p.shifts] == [("b", "c")]


def test_missed_entry_is_flagged():
    p = pair_shifts([scan("a", d(12, 17), "out"), scan("b", d(13, 7), "in"), scan("c", d(13, 17), "out")], NOW)
    assert [(e.kind, e.uuid) for e in p.exceptions] == [("missing_entry", "a")]
    assert len(p.shifts) == 1


def test_open_shift_today_is_present_and_old_one_is_missing():
    p = pair_shifts([scan("a", d(20, 7), "in")], NOW)
    assert [o[1] for o in p.open] == ["a"] and not p.exceptions
    p = pair_shifts([scan("a", d(18, 7), "in")], NOW)
    assert not p.open and p.exceptions[0].kind == "missing_exit"


def test_night_shift_counts_on_the_day_it_started():
    p = pair_shifts([scan("a", d(12, 22), "in"), scan("b", d(13, 6), "out")], NOW)
    assert p.shifts[0].day == date(2026, 10, 12) and p.shifts[0].hours == 8.0


def test_local_day_not_utc_day():
    # 01:00 SAST is 23:00 UTC the previous day - must still be the 13th.
    p = pair_shifts([scan("a", d(13, 1), "in"), scan("b", d(13, 5), "out")], NOW)
    assert p.shifts[0].day == date(2026, 10, 13)


def shifts_for(days_hours):
    """[(day, hours)] -> shifts starting 06:00 local."""
    scans = []
    for i, (day, h) in enumerate(days_hours):
        start = d(day, 6)
        scans += [scan(f"i{i}", start, "in"), scan(f"o{i}", start + timedelta(hours=h), "out")]
    return pair_shifts(scans, NOW).shifts


def test_daily_overtime():
    [row] = day_pay(shifts_for([(12, 11)]), [rate()])
    assert (row.regular, row.overtime) == (9.0, 2.0)
    assert row.amount == 9 * 30 + 2 * 30 * 1.5


def test_weekly_overtime_lands_on_the_day_it_happens():
    # Mon-Fri 9h each = 45h regular, then Sat 5h is all weekly overtime.
    rows = day_pay(shifts_for([(12, 9), (13, 9), (14, 9), (15, 9), (16, 9), (17, 5)]), [rate()])
    assert [r.overtime for r in rows] == [0, 0, 0, 0, 0, 5.0]
    assert sum(r.regular for r in rows) == 45.0


def test_daily_and_weekly_overtime_are_not_double_counted():
    # 6 x 10h: 1h daily OT each day; regular 9h/day reaches 45 on Fri, so
    # Saturday's 9 regular hours become weekly OT. Total OT = 6 + 9.
    rows = day_pay(shifts_for([(12, 10), (13, 10), (14, 10), (15, 10), (16, 10), (17, 10)]), [rate()])
    assert sum(r.overtime for r in rows) == 15.0
    assert sum(r.regular for r in rows) == 45.0


def test_week_split_by_pay_period_still_counts_whole_week():
    rows = day_pay(shifts_for([(12, 9), (13, 9), (14, 9), (15, 9), (16, 9), (17, 5)]), [rate()])
    # A period that starts on the Saturday still sees the week's earlier hours.
    [sat] = within(rows, date(2026, 10, 17), date(2026, 10, 31))
    assert sat.overtime == 5.0


def test_rate_change_mid_period_and_same_day_tie():
    rates = [rate(hourly=30), rate(eff=date(2026, 10, 14), hourly=35, id=2),
             rate(eff=date(2026, 10, 14), hourly=40, id=3)]
    rows = day_pay(shifts_for([(13, 8), (14, 8)]), rates)
    assert [r.rate for r in rows] == [30, 40]


def test_no_rate_refuses():
    with pytest.raises(NoRateError):
        day_pay(shifts_for([(13, 8)]), [rate(eff=date(2026, 12, 1))])
