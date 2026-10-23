"""Startup waits out Boord's own boot instead of refusing to start.

At boot Boord migrates boord.db while Labour is starting; the schema check
used to fail once and take the time clock down until the watchdog noticed.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

import main


@pytest.fixture
def fast_wait(monkeypatch):
    monkeypatch.setattr(main, "BOORD_WAIT_S", 0.5)
    monkeypatch.setattr(main, "BOORD_RETRY_S", 0.01)


def test_waits_while_boord_is_locked(fast_wait, monkeypatch):
    calls = []
    real = main._assert_boord_schema

    def locked_twice(conn):
        calls.append(1)
        if len(calls) <= 2:
            raise OperationalError("SELECT", {}, Exception("database is locked"))
        real(conn)

    monkeypatch.setattr(main, "_assert_boord_schema", locked_twice)
    main._wait_for_boord()
    assert len(calls) == 3


def test_real_schema_mismatch_still_refuses(fast_wait, monkeypatch, tmp_path):
    path = os.path.join(str(tmp_path), "old_boord.db")
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE worker (id TEXT PRIMARY KEY)"))
    monkeypatch.setattr(main.config, "BOORD_DB_PATH", path)
    monkeypatch.setattr(main, "boord_engine", engine)
    with pytest.raises(RuntimeError, match="missing something"):
        main._wait_for_boord()
    engine.dispose()


def test_missing_boord_db_refuses_after_wait(fast_wait, monkeypatch, tmp_path):
    monkeypatch.setattr(main.config, "BOORD_DB_PATH", os.path.join(str(tmp_path), "nope.db"))
    with pytest.raises(RuntimeError, match="BOORD_DB_PATH not found"):
        main._wait_for_boord()
