from collections import defaultdict
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from admin_auth import require_admin
from db import get_boord_session, get_labour_session, rates_by_date
from excel_io import xlsx_response
from pay import MAX_SHIFT, NoRateError, day_pay, monday, pair_shifts, within
from routers.scans import scans_between, utcnow
from routers.workers import worker_names
from timeutil import day_bounds, local_str

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(require_admin)])


def _r2(x: float) -> float:
    return round(x, 2)


@router.get("/hours")
def hours_report(start: date, end: date, format: Literal["json", "xlsx"] = "json",
                 session: Session = Depends(get_labour_session),
                 boord: Session = Depends(get_boord_session)):
    """Hours and pay per worker for any span of days.

    Overtime is weekly as well as daily, so the query is widened to the
    whole Mon-Sun weeks the span touches (plus MAX_SHIFT either side, for a
    shift that crosses the edge) and only then cut back to the span - a pay
    period starting on a Thursday still knows about Monday's hours."""
    if end < start:
        raise HTTPException(422, "end is before start")
    week_lo, week_hi = monday(start), monday(end) + timedelta(days=6)
    lo, hi = day_bounds(week_lo, week_hi)
    paired = pair_shifts(scans_between(session, lo - MAX_SHIFT, hi + MAX_SHIFT), utcnow())
    shifts = [s for s in paired.shifts if week_lo <= s.day <= week_hi]
    try:
        days = within(day_pay(shifts, rates_by_date(session)), start, end)
    except NoRateError as e:
        raise HTTPException(409, str(e))
    shifts = within(shifts, start, end)
    span_lo, span_hi = day_bounds(start, end)
    unresolved = [e for e in paired.exceptions if span_lo <= e.ts <= span_hi]
    names = worker_names(boord)

    per_worker = defaultdict(lambda: {"days": 0, "hours": 0.0, "regular": 0.0, "overtime": 0.0, "amount": 0.0})
    for d in days:
        w = per_worker[d.worker_id]
        w["days"] += 1
        w["hours"] += d.hours
        w["regular"] += d.regular
        w["overtime"] += d.overtime
        w["amount"] += d.amount
    workers = [{"worker_id": wid, "name": names.get(wid, wid), "days": v["days"],
                "hours": _r2(v["hours"]), "regular": _r2(v["regular"]),
                "overtime": _r2(v["overtime"]), "amount": _r2(v["amount"])}
               for wid, v in sorted(per_worker.items())]
    shift_rows = [{"worker_id": s.worker_id, "name": names.get(s.worker_id, s.worker_id),
                   "day": s.day.isoformat(), "in": local_str(s.in_ts), "out": local_str(s.out_ts),
                   "hours": _r2(s.hours)}
                  for s in sorted(shifts, key=lambda s: (s.worker_id, s.in_ts))]
    total = _r2(sum(w["amount"] for w in workers))

    if format == "xlsx":
        return xlsx_response([
            ("Pay", ["Employee no.", "Name", "Days", "Hours", "Regular h", "Overtime h", "Amount (R)"],
             [[w["worker_id"], w["name"], w["days"], w["hours"], w["regular"], w["overtime"], w["amount"]]
              for w in workers] + [["", "TOTAL", "", "", "", "", total]]),
            ("Shifts", ["Employee no.", "Name", "Day", "In", "Out", "Hours"],
             [[r["worker_id"], r["name"], r["day"], r["in"], r["out"], r["hours"]] for r in shift_rows]),
            ("Unresolved", ["Employee no.", "Name", "Problem", "Scan time"],
             [[e.worker_id, names.get(e.worker_id, e.worker_id),
               "No exit scan" if e.kind == "missing_exit" else "No entry scan", local_str(e.ts)]
              for e in unresolved]),
        ], f"labour-hours-{start.isoformat()}-to-{end.isoformat()}")

    return {"start": start.isoformat(), "end": end.isoformat(), "workers": workers,
            "total": total, "shifts": shift_rows, "unresolved": len(unresolved)}
