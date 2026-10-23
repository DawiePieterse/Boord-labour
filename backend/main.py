"""The Boord Labour service: packhouse time clock and hourly pay.

One `uvicorn main:app` process beside Boord on the farm server. Admin phones
scan a worker's existing Boord badge at the warehouse door; this turns the
scans into hours and pay. Reads Boord's data/boord.db read-only for the
worker register.

Access has two layers. The installer binds the port to 127.0.0.1, so only
the tailnet that `tailscale serve` publishes it to can reach it at all. On
top of that, everything except the door page's few endpoints needs the admin
PIN (admin_auth.require_admin), because the door phone is on the tailnet too.
Read MANUAL.md's Access section before changing how this is served.
"""
import os
import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

import config
from backup import start_backup_scheduler
from db import boord_engine, init_labour_db
from routers import admin, reports, scans, settings, version, workers

app = FastAPI(title="Boord Labour")

for module in (workers, scans, reports, settings, admin, version):
    app.include_router(module.router)


# Every column this app reads from Boord. If Boord renames or drops one, refuse
# to boot with a clear message rather than 500 at the warehouse door.
_BOORD_SCHEMA_CHECK = {"worker": "id, first_name, last_name, name, photo_filename, active"}


def _assert_boord_schema(conn) -> None:
    for table, columns in _BOORD_SCHEMA_CHECK.items():
        try:
            conn.execute(text(f"SELECT {columns} FROM {table} LIMIT 1"))
        except Exception as e:  # noqa: BLE001 - re-raised with context
            raise RuntimeError(
                f"Boord's database at {config.BOORD_DB_PATH} is missing something this "
                f"app reads from `{table}` ({columns}). Boord may have migrated its "
                f"schema past what this Labour release supports. Underlying error: {e}"
            ) from e


# How long startup waits for Boord's database to be readable before giving up.
# At boot every app's task starts at once, and Boord migrates boord.db on its
# own startup: while it does, the file is write-locked, and an Alembic batch
# migration briefly has no `worker` table at all (it copies the table to a
# temp one, drops the original and renames the copy). Labour starting in that
# window used to refuse to boot and stay down until the watchdog noticed,
# five or more minutes later - a morning at the door with no time clock.
# Kept well under the watchdog's 60 second "did it come back?" allowance, and
# the launcher (install.ps1) starts the process again if this does give up.
BOORD_WAIT_S = 30.0
BOORD_RETRY_S = 2.0


def _wait_for_boord() -> None:
    """Check Boord's database, retrying until BOORD_WAIT_S has passed.

    Everything is retried, including a missing column: it cannot tell a
    migration in flight from a real schema mismatch, and a real mismatch only
    costs half a minute before the same clear error is raised."""
    deadline = time.monotonic() + BOORD_WAIT_S
    while True:
        try:
            if not os.path.exists(config.BOORD_DB_PATH):
                raise RuntimeError(
                    f"BOORD_DB_PATH not found: {config.BOORD_DB_PATH}\n"
                    f"Install Boord first, or set BOORD_DB_PATH to its data/boord.db.")
            with boord_engine.connect() as conn:
                _assert_boord_schema(conn)
            return
        except Exception as e:  # noqa: BLE001 - re-raised once the wait is over
            if time.monotonic() >= deadline:
                raise
            print(f"Waiting for Boord's database ({e}); retrying in {BOORD_RETRY_S:g}s.", flush=True)
            time.sleep(BOORD_RETRY_S)


@app.on_event("startup")
def on_startup():
    _wait_for_boord()
    init_labour_db()
    start_backup_scheduler()


class NoCacheStaticFiles(StaticFiles):
    """Phones keep the scan screen open for days, so force revalidation - a
    browser must not keep serving JS from before the last deploy. Copied from
    Boord's main.py."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Boord's photo folder, read-only. Mounted only if it is there: a farm that
# never took photos should get a missing face, not a server that won't boot.
if os.path.isdir(config.BOORD_PHOTOS_DIR):
    app.mount("/photos", StaticFiles(directory=config.BOORD_PHOTOS_DIR), name="photos")

# Catch-all, must be last.
app.mount("/", NoCacheStaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
