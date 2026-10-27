import os
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field
from sqlmodel import Session, SQLModel

from admin_auth import require_admin
from backup import BACKUPS_DIR, PREFIX, create_backup, list_backups
from db import get_labour_session, rates_by_date
from models_labour import PayRate

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])


class RateIn(SQLModel):
    effective_date: date
    hourly_rate: float = Field(gt=0)
    ot_multiplier: float = Field(default=1.5, ge=1)
    daily_ot_after_h: float = Field(default=9.0, gt=0)
    weekly_ot_after_h: float = Field(default=45.0, gt=0)


@router.get("/rates")
def list_rates(session: Session = Depends(get_labour_session)):
    """Newest first. Rates are append-only history: a correction is a new row,
    so last month's pay report still reproduces what was paid."""
    return list(reversed(rates_by_date(session)))


@router.post("/rates")
def add_rate(body: RateIn, session: Session = Depends(get_labour_session)):
    session.add(PayRate(**body.model_dump()))
    session.commit()
    return {"ok": True}


@router.get("/backups")
def get_backups():
    return list_backups()


@router.post("/backups")
def backup_now():
    """Always makes one, even when nothing changed since the last."""
    return {"filename": create_backup()}


@router.get("/backups/{filename}/download")
def download_backup(filename: str):
    name = os.path.basename(filename)
    path = os.path.join(BACKUPS_DIR, name)
    if not name.startswith(PREFIX) or not os.path.isfile(path):
        raise HTTPException(404, "Backup not found")
    return FileResponse(path, media_type="application/zip", filename=name)
