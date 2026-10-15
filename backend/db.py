"""Database access. Two engines, on purpose - the same split as Boord Owner:

  labour_engine - data/labour.db, READ-WRITE. This process is its only writer.

  boord_engine  - Boord's data/boord.db, READ-ONLY. Boord is the sole writer
                  and migrates that file on its own startup, so every read here
                  is short-lived (NullPool, request-scoped session).

Read-only is enforced with `PRAGMA query_only=ON` rather than sqlite's
`?mode=ro`: a true read-only handle cannot open the -wal/-shm sidecars if
Boord ever runs in WAL mode. query_only rejects writes at the SQL layer while
letting SQLite journal normally.
"""
from datetime import date
from typing import Optional

from sqlalchemy import event, pool
from sqlmodel import Session, SQLModel, create_engine, select

import config
import models_boord  # noqa: F401 - registers the Worker mirror on the shared metadata
from models_labour import PayRate, Scan, ScanEdit

labour_engine = create_engine(
    f"sqlite:///{config.LABOUR_DB_PATH}",
    connect_args={"check_same_thread": False},
)

boord_engine = create_engine(
    f"sqlite:///{config.BOORD_DB_PATH}",
    connect_args={"check_same_thread": False},
    poolclass=pool.NullPool,  # never hold a Boord connection between requests
)


@event.listens_for(boord_engine, "connect")
def _boord_readonly(dbapi_conn, _rec):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA query_only=ON")      # reject every write at the SQL layer
    cur.execute("PRAGMA busy_timeout=3000")  # wait briefly on Boord's write lock, don't error
    cur.close()


def get_labour_session():
    with Session(labour_engine) as session:
        yield session


def get_boord_session():
    """Request-scoped and short - a long read held across one of Boord's
    startup migrations would see the schema change underneath it."""
    with Session(boord_engine) as session:
        yield session


# The explicit list is load-bearing: models_boord registers Worker on the SAME
# metadata, and a bare create_all() would create a stray worker table here.
_LABOUR_TABLES = [Scan.__table__, ScanEdit.__table__, PayRate.__table__]


def init_labour_db() -> None:
    # ponytail: create-only, no migrations. The first column added to an
    # existing table needs a top-up - copy BoordOwner/backend/db.py:
    # _ensure_owner_columns() when that day comes.
    SQLModel.metadata.create_all(labour_engine, tables=_LABOUR_TABLES)


def rates_by_date(session: Session) -> list[PayRate]:
    """Every rate, oldest first - pay.rate_for() picks the one in force."""
    return list(session.exec(select(PayRate).order_by(PayRate.effective_date, PayRate.id)).all())


def current_rate(session: Session, on: Optional[date] = None) -> Optional[PayRate]:
    on = on or date.today()
    return session.exec(
        select(PayRate).where(PayRate.effective_date <= on)
        .order_by(PayRate.effective_date.desc(), PayRate.id.desc())
    ).first()
