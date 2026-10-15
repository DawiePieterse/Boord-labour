"""This app's own tables, in labour.db.

A scan carries the direction the phone showed at the door. It is NOT derived
from scan order afterwards: a day worker's overnight gap (17:00 -> 07:00) is
as long as a long shift, so no time rule can tell "came back next morning"
from "left after a long day", and one missed scan would flip every IN/OUT
after it. Recorded directions keep a missed scan local - pay.pair_shifts()
turns it into one exception (IN with no OUT, or OUT with no IN) and nothing
else moves. The operator sees the big green IN / red OUT and can flip it on
the spot, which is the check that makes the recorded direction trustworthy.
"""
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Scan(SQLModel, table=True):
    uuid: str = Field(primary_key=True)  # made on the phone; re-syncing the same scan is a no-op
    worker_id: str = Field(index=True)
    timestamp: datetime = Field(index=True)  # naive UTC, when the badge was scanned, not when it synced
    direction: str  # "in" | "out"
    device_label: str = ""
    source: str = "scan"  # "scan" from the door, "admin" when entered by hand to fix an exception
    synced_at: Optional[datetime] = None
    deleted: bool = False  # soft delete, so the audit trail keeps resolving


class ScanEdit(SQLModel, table=True):
    """One row per hand correction. Pay comes from these scans, so every
    change says what it was, when, from which phone, and why."""
    id: Optional[int] = Field(default=None, primary_key=True)
    scan_uuid: str = Field(index=True)
    action: str  # "add" | "change" | "delete"
    old_ts: Optional[datetime] = None
    new_ts: Optional[datetime] = None
    old_direction: str = ""
    new_direction: str = ""
    reason: str
    at: datetime
    device_label: str = ""


class PayRate(SQLModel, table=True):
    """Append-only rate history; the newest row effective on a day applies
    to that day. Nothing is seeded - see db.py."""
    id: Optional[int] = Field(default=None, primary_key=True)
    effective_date: date
    hourly_rate: float
    ot_multiplier: float = 1.5
    daily_ot_after_h: float = 9.0
    weekly_ot_after_h: float = 45.0
