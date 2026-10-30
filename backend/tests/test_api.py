"""Sync, presence, exceptions, corrections and the report, end to end
through the HTTP API against a fake boord.db (see conftest.py)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError


def local(day, hh, mm=0):
    """A SAST wall-clock time as an aware datetime."""
    return datetime(2026, 10, day, hh, mm, tzinfo=timezone(timedelta(hours=2)))


def sync(client, *scans):
    body = {"scans": [{"uuid": u, "worker_id": w, "timestamp": ts.isoformat(), "direction": d,
                       "device_label": "door-1"} for u, w, ts, d in scans]}
    r = client.post("/api/scans/sync", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_workers_lists_only_active(client):
    ids = [w["id"] for w in client.get("/api/workers").json()]
    assert ids == ["001", "002"]


def test_sync_is_idempotent_and_rejects_unknown(admin_client):
    client = admin_client
    first = sync(client, ("a", "001", local(12, 7), "in"), ("x", "999", local(12, 7), "in"),
                 ("y", "003", local(12, 7), "in"))
    assert first["accepted"] == ["a"]
    assert {r["uuid"] for r in first["rejected"]} == {"x", "y"}
    again = sync(client, ("a", "001", local(12, 7), "in"))
    assert again["accepted"] == ["a"]
    assert len(client.get("/api/scans", params={"day": "2026-10-12"}).json()) == 1


def test_resync_can_flip_direction_but_not_resurrect(admin_client):
    client = admin_client
    sync(client, ("a", "001", local(12, 7), "in"))
    sync(client, ("a", "001", local(12, 7), "out"))
    [row] = client.get("/api/scans", params={"day": "2026-10-12"}).json()
    assert row["direction"] == "out"
    assert client.post("/api/scans/a/delete", json={"reason": "test"}).status_code == 200
    sync(client, ("a", "001", local(12, 7), "in"))
    assert client.get("/api/scans", params={"day": "2026-10-12"}).json() == []


def test_presence_shows_who_is_in_now(client):
    now = datetime.now(timezone.utc)
    sync(client, ("a", "001", now - timedelta(hours=2), "in"),
         ("b", "002", now - timedelta(hours=3), "in"), ("c", "002", now - timedelta(hours=1), "out"))
    assert [p["worker_id"] for p in client.get("/api/presence").json()] == ["001"]


def test_recent_lists_every_phone_for_24h_newest_first(admin_client):
    client = admin_client
    now = datetime.now(timezone.utc)
    sync(client, ("old", "001", now - timedelta(hours=25), "in"),
         ("a", "001", now - timedelta(hours=3), "in"))
    client.post("/api/scans/sync", json={"scans": [
        {"uuid": "b", "worker_id": "002", "timestamp": (now - timedelta(hours=1)).isoformat(),
         "direction": "in", "device_label": "door-2"},
        {"uuid": "gone", "worker_id": "002", "timestamp": (now - timedelta(hours=2)).isoformat(),
         "direction": "in", "device_label": "door-2"}]})
    assert client.post("/api/scans/gone/delete", json={"reason": "double scan"}).status_code == 200
    client.post("/api/admin/logout")  # the door phone has no cookie
    rows = client.get("/api/scans/recent").json()
    assert [(r["uuid"], r["device_label"], r["name"]) for r in rows] == [
        ("b", "door-2", "Piet K"), ("a", "door-1", "Thandi M")]
    assert rows[0]["ts"].endswith("Z") and rows[0]["source"] == "scan"


def test_exception_fixed_by_admin_scan_with_audit(admin_client):
    client = admin_client
    client.post("/api/settings/rates", json={"effective_date": "2026-01-01", "hourly_rate": 30})
    sync(client, ("a", "001", local(12, 7), "in"))  # never scanned out
    exc = client.get("/api/exceptions", params={"start": "2026-10-12", "end": "2026-10-12"}).json()
    assert [(e["kind"], e["uuid"]) for e in exc] == [("missing_exit", "a")]

    report = client.get("/api/reports/hours", params={"start": "2026-10-12", "end": "2026-10-12"}).json()
    assert report["total"] == 0 and report["unresolved"] == 1

    assert client.post("/api/scans", json={"worker_id": "001", "timestamp": local(12, 15).isoformat(),
                                           "direction": "out", "reason": " "}).status_code == 422
    r = client.post("/api/scans", json={"worker_id": "001", "timestamp": local(12, 15).isoformat(),
                                        "direction": "out", "reason": "forgot to scan out, per supervisor"})
    assert r.status_code == 200
    assert client.get("/api/exceptions", params={"start": "2026-10-12", "end": "2026-10-12"}).json() == []
    report = client.get("/api/reports/hours", params={"start": "2026-10-12", "end": "2026-10-12"}).json()
    assert report["workers"][0]["hours"] == 8.0 and report["total"] == 240.0
    [edit] = client.get("/api/edits").json()
    assert edit["action"] == "add" and edit["new_direction"] == "out"


def test_report_refuses_without_rate_and_exports_xlsx(admin_client):
    client = admin_client
    sync(client, ("a", "001", local(12, 7), "in"), ("b", "001", local(12, 17), "out"))
    r = client.get("/api/reports/hours", params={"start": "2026-10-12", "end": "2026-10-18"})
    assert r.status_code == 409
    client.post("/api/settings/rates", json={"effective_date": "2026-01-01", "hourly_rate": 30})
    r = client.get("/api/reports/hours", params={"start": "2026-10-12", "end": "2026-10-18", "format": "xlsx"})
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_boord_db_is_read_only(client):
    from db import boord_engine
    with boord_engine.connect() as conn, pytest.raises(OperationalError):
        conn.execute(text("INSERT INTO worker (id) VALUES ('hack')"))


def test_nightly_backup_skips_when_unchanged(client):
    import zipfile

    from backup import BACKUPS_DIR, create_backup
    name = create_backup()
    assert zipfile.ZipFile(f"{BACKUPS_DIR}/{name}").namelist() == ["labour.db"]
    assert create_backup(skip_if_unchanged=True) is None
    sync(client, ("a", "001", local(12, 7), "in"))
    assert create_backup(skip_if_unchanged=True) is not None
