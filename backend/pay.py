"""Scans -> shifts -> hours -> pay. Pure functions, no database: this is the
money path, and tests/test_pay.py drives it directly.

Timestamps in are naive UTC (as stored). A shift belongs to the farm-local
day its IN was scanned on, so a night shift is paid on the day it started.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from timeutil import to_local

# Two scans of one badge this close together are one person at the door,
# whether it was the same phone twice or two phones at once.
DUPLICATE_WINDOW = timedelta(seconds=60)

# An IN left open longer than this is a forgotten exit, not a shift still in
# progress. Calibration knob: comfortably past the longest real packhouse
# day, short enough that yesterday's forgotten exit is flagged by morning.
MAX_SHIFT = timedelta(hours=18)


class NoRateError(Exception):
    """Hours fell on a day with no hourly rate in force. Wages are refused
    rather than guessed - Boord's rule: a wrong rate makes a plausible
    payslip that only the underpaid person ever notices."""


@dataclass
class Shift:
    worker_id: str
    in_uuid: str
    in_ts: datetime
    out_uuid: str
    out_ts: datetime

    @property
    def day(self) -> date:
        return to_local(self.in_ts).date()

    @property
    def hours(self) -> float:
        return (self.out_ts - self.in_ts).total_seconds() / 3600


@dataclass
class Exception_:
    worker_id: str
    kind: str  # "missing_exit" | "missing_entry"
    uuid: str
    ts: datetime


@dataclass
class Paired:
    shifts: list = field(default_factory=list)
    open: list = field(default_factory=list)        # (worker_id, uuid, in_ts) - in the building now
    exceptions: list = field(default_factory=list)


def pair_shifts(scans, now: datetime) -> Paired:
    """`scans`: objects with uuid, worker_id, timestamp, direction - deleted
    ones already filtered out. `now` is naive UTC."""
    by_worker = defaultdict(list)
    for s in scans:
        by_worker[s.worker_id].append(s)

    out = Paired()
    for worker_id, rows in by_worker.items():
        rows.sort(key=lambda s: (s.timestamp, s.uuid))
        kept = []
        for s in rows:
            if kept and s.timestamp - kept[-1].timestamp < DUPLICATE_WINDOW:
                continue
            kept.append(s)

        open_in = None
        for s in kept:
            if s.direction == "in":
                if open_in is not None:
                    out.exceptions.append(Exception_(worker_id, "missing_exit", open_in.uuid, open_in.timestamp))
                open_in = s
            elif open_in is not None and s.timestamp - open_in.timestamp <= MAX_SHIFT:
                out.shifts.append(Shift(worker_id, open_in.uuid, open_in.timestamp, s.uuid, s.timestamp))
                open_in = None
            else:
                if open_in is not None:
                    out.exceptions.append(Exception_(worker_id, "missing_exit", open_in.uuid, open_in.timestamp))
                    open_in = None
                out.exceptions.append(Exception_(worker_id, "missing_entry", s.uuid, s.timestamp))
        if open_in is not None:
            if now - open_in.timestamp > MAX_SHIFT:
                out.exceptions.append(Exception_(worker_id, "missing_exit", open_in.uuid, open_in.timestamp))
            else:
                out.open.append((worker_id, open_in.uuid, open_in.timestamp))
    return out


def rate_for(rates, day: date):
    """The newest rate effective on `day`. `rates` is oldest-first
    (db.rates_by_date), so the last match wins - including the second of two
    rates entered on the same day."""
    found = None
    for r in rates:
        if r.effective_date <= day:
            found = r
    return found


@dataclass
class DayPay:
    worker_id: str
    day: date
    hours: float
    regular: float
    overtime: float
    rate: float
    amount: float


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def day_pay(shifts, rates) -> list:
    """Per worker per day: regular and overtime hours and the amount due.

    Overtime, BCEA-style and never counted twice: hours past the daily
    threshold are overtime; of what is left, hours that take the Mon-Sun
    week past the weekly threshold are overtime on the day they happen.
    Each week is always evaluated whole, so callers must pass every shift in
    the weeks they report on (reports.py widens the query to whole weeks)."""
    hours = defaultdict(float)  # (worker, day) -> hours
    for s in shifts:
        hours[(s.worker_id, s.day)] += s.hours

    result = []
    week_regular = defaultdict(float)  # (worker, monday) -> regular hours so far
    for (worker_id, day) in sorted(hours, key=lambda k: (k[0], k[1])):
        h = hours[(worker_id, day)]
        r = rate_for(rates, day)
        if r is None:
            raise NoRateError(f"No hourly rate is set for {day.isoformat()} - add one under Settings")
        daily_ot = max(0.0, h - r.daily_ot_after_h)
        regular = h - daily_ot
        wk = (worker_id, monday(day))
        room = max(0.0, r.weekly_ot_after_h - week_regular[wk])
        weekly_ot = max(0.0, regular - room)
        regular -= weekly_ot
        week_regular[wk] += regular
        ot = daily_ot + weekly_ot
        amount = regular * r.hourly_rate + ot * r.hourly_rate * r.ot_multiplier
        result.append(DayPay(worker_id, day, h, regular, ot, r.hourly_rate, round(amount, 2)))
    return result


def within(rows, start: date, end: Optional[date] = None):
    end = end or start
    return [r for r in rows if start <= r.day <= end]
