"""The Boord Labour service: packhouse time clock and hourly pay.

One `uvicorn main:app` process beside Boord on the farm server. Admin phones
scan a worker's existing Boord badge at the warehouse door; this turns the
scans into hours and pay. Reads Boord's data/boord.db read-only for the
worker register.

There is no sign-in. Every endpoint answers anyone who can reach the port,
and the installer binds it to 127.0.0.1 so that "anyone" means the tailnet
`tailscale serve` publishes it to. Read MANUAL.md's Access section before
changing how this is served.
"""
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

import config
from backup import start_backup_scheduler
from db import boord_engine, init_labour_db
from routers import reports, scans, settings, version, workers

app = FastAPI(title="Boord Labour")

for module in (workers, scans, reports, settings, version):
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


@app.on_event("startup")
def on_startup():
    if not os.path.exists(config.BOORD_DB_PATH):
        raise RuntimeError(
            f"BOORD_DB_PATH not found: {config.BOORD_DB_PATH}\n"
            f"Install Boord first, or set BOORD_DB_PATH to its data/boord.db.")
    with boord_engine.connect() as conn:
        _assert_boord_schema(conn)
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
