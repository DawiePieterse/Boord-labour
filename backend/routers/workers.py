from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from db import get_boord_session
from models_boord import Worker

router = APIRouter(prefix="/api/workers", tags=["workers"])


def display_name(w: Worker) -> str:
    return w.name or f"{w.first_name} {w.last_name}".strip() or w.id


def worker_names(session: Session) -> dict:
    """id -> display name for every worker, active or not - history keeps
    resolving after Boord deactivates someone."""
    return {w.id: display_name(w) for w in session.exec(select(Worker)).all()}


@router.get("")
def list_workers(session: Session = Depends(get_boord_session)):
    """Active Boord workers - the phone caches this so it can name a badge
    and refuse an unknown one with no signal."""
    workers = session.exec(select(Worker).where(Worker.active == True)).all()  # noqa: E712
    return [{"id": w.id, "name": display_name(w),
             "photo": f"/photos/{w.photo_filename}" if w.photo_filename else ""}
            for w in sorted(workers, key=lambda w: w.id)]
