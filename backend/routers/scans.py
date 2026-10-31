import uuid as uuidlib
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import field_validator
from sqlmodel import Session, SQLModel, select

from admin_auth import require_admin
from db import get_boord_session, get_labour_session
from models_boord import Worker
from models_labour import Scan, ScanEdit
from pay import MAX_SHIFT, pair_shifts
from routers.workers import worker_names
from timeutil import day_bounds

router = APIRouter(prefix="/api", tags=["scans"])

# Everything below the door section is admin-only. sync, presence and
# scans/recent stay open: they are what the door phone runs on.
ADMIN = [Depends(require_admin)]


def naive_utc(dt: datetime) -> datetime:
    """What the database stores. A phone sends ISO with a Z; a naive value
    is taken to be UTC already."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def scans_between(session: Session, start: datetime, end: datetime) -> list:
    return list(session.exec(select(Scan).where(
        Scan.deleted == False, Scan.timestamp >= start, Scan.timestamp <= end)).all())  # noqa: E712


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """Naive UTC out of the database -> ISO with Z, so the phone's Date()
    reads it as UTC rather than as its own local time."""
    return dt.isoformat() + "Z" if dt else None


# --------------------------------------------------------------------------- #
# From the door
# --------------------------------------------------------------------------- #
class ScanIn(SQLModel):
    uuid: str
    worker_id: str
    timestamp: datetime
    direction: Literal["in", "out"]
    device_label: str = ""


class SyncBatch(SQLModel):
    scans: list[ScanIn]


@router.post("/scans/sync")
def sync_scans(batch: SyncBatch, session: Session = Depends(get_labour_session),
               boord: Session = Depends(get_boord_session)):
    """Idempotent by uuid: a phone re-sending a batch it never heard back
    about changes nothing. The one field a re-send may change is direction -
    that is the operator tapping "wrong, it's OUT" on the scan screen. A
    deleted scan stays deleted."""
    active = set(boord.exec(select(Worker.id).where(Worker.active == True)).all())  # noqa: E712
    accepted, rejected = [], []
    now = utcnow()
    for s in batch.scans:
        if s.worker_id not in active:
            rejected.append({"uuid": s.uuid, "reason": f"{s.worker_id} is not an active Boord worker"})
            continue
        existing = session.get(Scan, s.uuid)
        if existing is None:
            session.add(Scan(uuid=s.uuid, worker_id=s.worker_id, timestamp=naive_utc(s.timestamp),
                             direction=s.direction, device_label=s.device_label, synced_at=now))
        elif not existing.deleted:
            existing.direction = s.direction
            session.add(existing)
        accepted.append(s.uuid)
    session.commit()
    return {"accepted": accepted, "rejected": rejected}


@router.get("/presence")
def presence(session: Session = Depends(get_labour_session),
             boord: Session = Depends(get_boord_session)):
    """Who is inside right now. The phone seeds its IN/OUT guess from this."""
    now = utcnow()
    paired = pair_shifts(scans_between(session, now - 2 * MAX_SHIFT, now + timedelta(hours=1)), now)
    names = worker_names(boord)
    return sorted(({"worker_id": w, "name": names.get(w, w), "uuid": u, "in_ts": iso_utc(ts)}
                   for w, u, ts in paired.open), key=lambda r: r["in_ts"])


RECENT_HOURS = 24
RECENT_LIMIT = 1000  # a full packhouse day is a few hundred; this only stops a runaway


@router.get("/scans/recent")
def recent_scans(session: Session = Depends(get_labour_session),
                 boord: Session = Depends(get_boord_session)):
    """Every phone's scans from the last 24 hours, newest first, with the
    phone that made each one. Open, like presence: a second door phone used
    to show "Nothing scanned yet" all morning because each phone only knew
    its own scans, and the person on the door had no way to see that Door 1
    was busy. It says no more than presence already does - who came and
    went, never hours or pay - so the door page may have it. Admin entries
    are included (source "admin"), so a fix shows up at the door too."""
    now = utcnow()
    rows = session.exec(select(Scan).where(
        Scan.deleted == False, Scan.timestamp >= now - timedelta(hours=RECENT_HOURS),  # noqa: E712
        Scan.timestamp <= now + timedelta(hours=1),
    ).order_by(Scan.timestamp.desc()).limit(RECENT_LIMIT)).all()
    names = worker_names(boord)
    return [{"uuid": r.uuid, "worker_id": r.worker_id, "name": names.get(r.worker_id, r.worker_id),
             "ts": iso_utc(r.timestamp), "direction": r.direction, "source": r.source,
             "device_label": r.device_label}
            for r in rows]


# --------------------------------------------------------------------------- #
# Admin: exceptions and corrections
# --------------------------------------------------------------------------- #
@router.get("/exceptions", dependencies=ADMIN)
def exceptions(start: Optional[date] = None, end: Optional[date] = None,
               session: Session = Depends(get_labour_session),
               boord: Session = Depends(get_boord_session)):
    """Scans that did not pair: an IN with no OUT, or an OUT with no IN.
    Their hours are not paid until somebody adds the missing scan or deletes
    the stray one. Default: the last 14 days."""
    end = end or date.today()
    start = start or end - timedelta(days=14)
    lo, hi = day_bounds(start, end)
    paired = pair_shifts(scans_between(session, lo - MAX_SHIFT, hi + MAX_SHIFT), utcnow())
    names = worker_names(boord)
    return sorted(({"worker_id": e.worker_id, "name": names.get(e.worker_id, e.worker_id),
                    "kind": e.kind, "uuid": e.uuid, "ts": iso_utc(e.ts)}
                   for e in paired.exceptions if lo <= e.ts <= hi), key=lambda r: r["ts"])


@router.get("/scans", dependencies=ADMIN)
def scans_on_day(day: Optional[date] = None, worker_id: Optional[str] = None,
                 session: Session = Depends(get_labour_session),
                 boord: Session = Depends(get_boord_session)):
    lo, hi = day_bounds(day or date.today())
    rows = scans_between(session, lo, hi)
    if worker_id:
        rows = [r for r in rows if r.worker_id == worker_id]
    names = worker_names(boord)
    return [{"uuid": r.uuid, "worker_id": r.worker_id, "name": names.get(r.worker_id, r.worker_id),
             "ts": iso_utc(r.timestamp), "direction": r.direction, "source": r.source,
             "device_label": r.device_label}
            for r in sorted(rows, key=lambda r: r.timestamp)]


class _Reasoned(SQLModel):
    reason: str
    device_label: str = ""

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Say why - pay is calculated from these scans")
        return v.strip()


class ScanAdd(_Reasoned):
    worker_id: str
    timestamp: datetime
    direction: Literal["in", "out"]


class ScanChange(_Reasoned):
    timestamp: Optional[datetime] = None
    direction: Optional[Literal["in", "out"]] = None


class ScanDelete(_Reasoned):
    pass


# How far ahead of the server's clock a hand-entered time may be. A scan is
# something that already happened, so a time in the future is a slip - the
# wrong day picked, or a shift typed into next week - and it used to be kept:
# the pay report then showed the person as never paired (an OUT a week from
# now is more than MAX_SHIFT after its IN), and the stray scan sat outside the
# 14-day Fix window where nobody saw it. The door phone's own scans are not
# checked here: a phone whose clock is wrong still saw a real person at the
# door, and refusing would lose the scan. The grace covers an admin phone a
# few minutes ahead of the farm PC; admin.js warns from the same 5 minutes.
FUTURE_GRACE = timedelta(minutes=5)


def _not_in_future(ts: datetime) -> datetime:
    if ts > utcnow() + FUTURE_GRACE:
        raise HTTPException(422, "That time is in the future - check the date and time")
    return ts


def _audit(session: Session, scan: Scan, action: str, body: _Reasoned, old_ts=None, old_dir=""):
    session.add(ScanEdit(scan_uuid=scan.uuid, action=action, reason=body.reason, at=utcnow(),
                         device_label=body.device_label, old_ts=old_ts, old_direction=old_dir,
                         new_ts=None if action == "delete" else scan.timestamp,
                         new_direction="" if action == "delete" else scan.direction))


@router.post("/scans", dependencies=ADMIN)
def add_scan(body: ScanAdd, session: Session = Depends(get_labour_session),
             boord: Session = Depends(get_boord_session)):
    if boord.get(Worker, body.worker_id) is None:
        raise HTTPException(404, f"No Boord worker {body.worker_id}")
    scan = Scan(uuid=str(uuidlib.uuid4()), worker_id=body.worker_id,
                timestamp=_not_in_future(naive_utc(body.timestamp)),
                direction=body.direction, device_label=body.device_label, source="admin", synced_at=utcnow())
    session.add(scan)
    _audit(session, scan, "add", body)
    session.commit()
    return {"uuid": scan.uuid}


def _live_scan(session: Session, uuid: str) -> Scan:
    scan = session.get(Scan, uuid)
    if scan is None or scan.deleted:
        raise HTTPException(404, "No such scan")
    return scan


@router.patch("/scans/{uuid}", dependencies=ADMIN)
def change_scan(uuid: str, body: ScanChange, session: Session = Depends(get_labour_session)):
    scan = _live_scan(session, uuid)
    old_ts, old_dir = scan.timestamp, scan.direction
    if body.timestamp is not None:
        scan.timestamp = _not_in_future(naive_utc(body.timestamp))
    if body.direction is not None:
        scan.direction = body.direction
    session.add(scan)
    _audit(session, scan, "change", body, old_ts, old_dir)
    session.commit()
    return {"ok": True}


@router.post("/scans/{uuid}/delete", dependencies=ADMIN)
def delete_scan(uuid: str, body: ScanDelete, session: Session = Depends(get_labour_session)):
    """POST rather than DELETE: it carries a body (the reason), and a DELETE
    body is something proxies and fetch() treat inconsistently."""
    scan = _live_scan(session, uuid)
    scan.deleted = True
    session.add(scan)
    _audit(session, scan, "delete", body, scan.timestamp, scan.direction)
    session.commit()
    return {"ok": True}


@router.get("/edits", dependencies=ADMIN)
def edits(limit: int = 200, session: Session = Depends(get_labour_session)):
    rows = session.exec(select(ScanEdit).order_by(ScanEdit.at.desc()).limit(limit)).all()
    return [{**r.model_dump(), "at": iso_utc(r.at), "old_ts": iso_utc(r.old_ts), "new_ts": iso_utc(r.new_ts)}
            for r in rows]
