# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Boord Labour is a packhouse time clock. Admin phones scan workers' existing Boord badges at the warehouse door, and the app pays hourly with overtime. It is a sibling of **Boord** (`../Boord`, pays pickers per kg) and follows the **BoordOwner** pattern (`../BoordOwner`):

- its own uvicorn process on port **8040**, bound to 127.0.0.1 and published only via `tailscale serve --https=8040`;
- its own SQLite `data/labour.db`;
- Boord's `boord.db` opened **read-only**, for the worker register only.

Access has two layers:
- **Tailscale** gets you to the app at all. It binds 127.0.0.1; never bind 0.0.0.0.
- **The admin PIN** separates the door phone from the admin. Tailscale can't do that, because the door phone must be on the tailnet for its camera.
  - The door page `/` (`frontend/index.html`, `app.js`) uses only `GET /api/workers`, `POST /api/scans/sync`, `GET /api/presence` and `GET /api/version`. Those stay open.
  - **Every other endpoint must depend on `admin_auth.require_admin`**, which checks the `labour_admin` cookie. That includes any new one you add. The admin page `/admin/` (`frontend/admin/`) shows a PIN screen on any 401.
  - The PIN is pbkdf2-hashed in `data/admin_pin.txt` and set only from the server console (`backend/set_pin.py`, also run by `install.ps1`), never via the web.
  - The cookie has no expiry. It carries a fingerprint of the PIN hash, so changing the PIN revokes every phone.
  - In tests, use the `admin_client` fixture for admin endpoints. The TestClient runs on https because the cookie is Secure.

## Commands

```bash
cd backend
/usr/bin/python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # Python 3.9: the farm's minimum
.venv/bin/python -m pytest                       # all tests
.venv/bin/python -m pytest tests/test_pay.py -k overtime   # one test
BOORD_DB_PATH=../../Boord/data/boord.db .venv/bin/python run_preview.py   # dev server, http://localhost:8040/
scripts/release.sh v1.1    # signed release tag (VERSION in frontend/shared/api.js must match)
.venv/bin/python set_pin.py   # set/reset the admin PIN (signs every phone out)
```

Keep code Python 3.9-compatible: no `X | None`, no `match`.

## Architecture

- **Scans carry a direction recorded on the phone** (`models_labour.Scan.direction`). It is not derived from scan order. A day worker's overnight gap looks like a long shift, so order-based pairing flips every IN/OUT after one missed scan. The phone decides IN/OUT from server presence plus its own unsynced scans (`frontend/app.js: rebuildInside`). The operator sees it full screen and can flip it, and a re-sync of the same uuid updates the direction.
- **`backend/pay.py` is the money path**, pure functions tested in `tests/test_pay.py`:
  - `pair_shifts`: drops repeat scans within 60s; IN then OUT within `MAX_SHIFT` (18h) makes a shift; anything unpaired becomes a `missing_exit`/`missing_entry` exception and is not paid.
  - `day_pay`: daily OT past `daily_ot_after_h`, then weekly OT past `weekly_ot_after_h` on the remaining regular hours, never double counted.
  - Shifts belong to the farm-local day of their IN (`timeutil.to_local`). Timestamps are stored naive UTC.
  - `DUPLICATE_MS`/`MAX_SHIFT_MS` in `frontend/app.js` mirror the pay.py constants. Change them together.
- **Reports widen to whole Mon–Sun weeks** (`routers/reports.py`) before cutting back to the requested span, because weekly OT needs the full week.
- **Rates are append-only** (`PayRate`); the newest row effective on a day applies (same-date tie → highest id). With no rate, reports return 409 rather than guess.
- **Corrections** (add/change/delete scan) require a reason and write a `ScanEdit` audit row. Deletes are soft.
- **Sync is idempotent by client uuid** (`POST /api/scans/sync`). The phone's IndexedDB queue (`frontend/idb.js`) is the write-ahead log, and scans keep their scan-time timestamp.
- **Boord coupling:** `models_boord.Worker` is a partial read-only mirror. `main._BOORD_SCHEMA_CHECK` refuses to boot if Boord drops a column it reads. The badge QR holds exactly `worker.id` (see `../Boord/frontend/admin/print-badge.html`). Photos come from Boord's `data/photos`, mounted read-only at `/photos`.
- **Schema changes:** `db.init_labour_db()` only creates tables. Adding a column to an existing table needs an additive top-up first; copy `_ensure_owner_columns` from `../BoordOwner/backend/db.py`.
- **Frontend:** a single vanilla-JS PWA, no build step. `frontend/shared/` (api.js, sw-core.js, styles.css, tailwind.js, vendor/) is vendored from Boord. Only `VERSION` in api.js is ours. Bump `CACHE` in `service-worker.js` when shell files change.
- **Deployment files** (`install.ps1`, `install.bat`, `update_labour_server.bat`) are adapted from BoordOwner's. Keep fixes flowing between the sibling repos.
- **`stop_server.ps1` is the reference copy.** The updater and installer stop the server with it, never with a bare `schtasks /end`, because the uvicorn process outlives the launcher and keeps port 8040. Boord Owner (1.9.3) and Boord Notes (2.18) carry adapted copies, with their own port and task name. A fix here belongs in those two copies as well. The watchdog/heartbeat app lists and the `tailscale serve` port table live in **Boord's** repo (`watchdog.ps1`, `heartbeat.ps1`, MANUAL.md).
