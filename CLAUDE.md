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
  - The door page `/` (`frontend/index.html`, `app.js`) uses only `GET /api/workers`, `POST /api/scans/sync`, `GET /api/presence`, `GET /api/scans/recent` and `GET /api/version`. Those stay open.
  - **Every other endpoint must depend on `admin_auth.require_admin`**, which checks the `labour_admin` cookie. That includes any new one you add. The admin page `/admin/` (`frontend/admin/`) shows a PIN screen on any 401.
  - The PIN is pbkdf2-hashed in `data/admin_pin.txt` and set only from the server console (`backend/set_pin.py`, also run by `install.ps1`), never via the web.
  - The cookie has no expiry. It carries a fingerprint of the PIN hash, so changing the PIN revokes every phone.
  - In tests, use the `admin_client` fixture for admin endpoints. The TestClient runs on https because the cookie is Secure.

## The Boord suite

This app is one of seven that run together on the farm PC (`bekfontein-server`), each its own repo, process, port and database. They are reached only over Tailscale, and each binds `127.0.0.1` and is published with `tailscale serve`. The same section is in every app's `CLAUDE.md`. When a fact here changes, change it in all seven.

| App | Repo (`DawiePieterse/…`) | What it does | Port | Tailnet address | Mac folder | Farm PC folder |
|---|---|---|---|---|---|---|
| Boord | `Boord` | Harvest capture and picker pay per kg: field tablets, pack-house receiving, admin office. The hub. | 8000 | `https://bekfontein-server.taile32cb0.ts.net/` | `~/Documents/Projects/Boord` | `C:\Boord` |
| Boord Owner | `boordowner` | The owner's view: season vs history, weather, risk, crop estimate, optional AI. | 8010 | `https://bekfontein-server.taile32cb0.ts.net:8443/` | `~/Documents/Projects/BoordOwner` | `C:\BoordOwner` |
| Boord Notes | `boord-notes` | Private farm notebook for Andre and his son, offline-first, optional AI. | 8020 | `https://bekfontein-server.taile32cb0.ts.net:9443/` | `~/Documents/Projects/BoordNotes` | `C:\bekfontein-farm-notebook` |
| Kudde | `Kudde` | Cattle records: animals and their events. | 8030 | `https://bekfontein-server.taile32cb0.ts.net:8030/` | `~/Documents/Projects/Kudde` | `C:\Kudde` |
| **Boord Labour** (this app) | `Boord-labour` | Packhouse time clock: badge scans at the door, hourly pay with overtime. | 8040 | `https://bekfontein-server.taile32cb0.ts.net:8040/` | `~/Documents/Projects/Boord-labour` | `C:\Boord-labour` |
| Boord Monitor | `Boord-monitor` | Watches the PC and the other apps: status page, SLOs, incidents, Web Push alerts, a Restart button; runs the watchdog and heartbeat. | 8050 | `https://bekfontein-server.taile32cb0.ts.net:8050/` | `~/Documents/Projects/Boord-monitor` | `C:\boord-monitor` |
| Boord Packhouse | `boord-packhouse` | After receiving to the truck: sulfur, acid, lines, pre-pack, cold store and PPECB, dispatch. | 8060 | `https://bekfontein-server.taile32cb0.ts.net:8060/` | `~/Documents/Projects/Boord-packhouse` | `C:\Boord-packhouse` |

**How they depend on each other:**
- **Boord is the hub.** Its `data/boord.db` is opened read-only by Owner (harvest, lots, blocks, suppliers), Labour (the worker register, and Boord's `data/photos` for faces), Monitor (tablet station, last sync and outbox) and Packhouse (received lots, blocks, suppliers, workers).
  - Boord is that database's only writer and migrates it at startup.
  - Owner, Labour and Packhouse refuse to boot if a column they read disappears. A Boord migration that drops or renames a column needs those apps updated in step.
- **Labour's badges are Boord's.** The badge QR holds exactly `worker.id` (`Boord/frontend/admin/print-badge.html`), and Labour and Packhouse vendor Boord's `frontend/shared/`.
- **Owner asks Notes.** The "Ask the farm notes" bridge calls Notes' `/api/ai/ask` at `OWNER_NOTES_URL` (`http://127.0.0.1:8020`) and can share Notes' `data/anthropic_key.txt`.
- **Monitor keeps the others running.** Since Monitor 2.0 its `watchdog.ps1` (restarts an app that stops answering) and `heartbeat.ps1` (pings healthchecks.io) cover all seven, as the scheduled tasks "Boord Watchdog" and "Boord Heartbeat". Until then they lived in Boord's repo; Boord's copies are now forwarders to Monitor's.
  - **The app table is Monitor's `apps.json`, the one copy.** Monitor's `backend/apps.py`, `watchdog.ps1` and `heartbeat.ps1` all read it. Adding or moving an app is one line there plus the port table above; the `tailscale serve` ports are also in Boord's MANUAL.md.
  - The watchdog stands down while any app's updater (its `updater` in `apps.json`) or an installer runs, and its `-Restart "<Name>"` is what Monitor's Restart button runs. It exits 2 when it stands down.
- **Monitor watches everything.** It shows each app's up/down state and `/api/version`, Tailscale and the PC, keeps uptime history, SLOs and incidents, and pushes an alert after three failed checks in a row.
  - Every app's `/api/version` keeps the same field names (`tag`, `state`, `frontend_version`), because Monitor and the heartbeat read them all.
  - An off-site copy of the monitor on the owner's Mac alerts when the whole farm PC is unreachable.
- **Kudde and Notes stand alone.** No other app reads their data. They are only watched and restarted.

**What they share by convention, not code:**
- One release key: fingerprint `67C64CFDD584DD140E58AF6E329C9B9DD0562A9D` in each app's `data\release_key.fpr`.
- Releases are signed tags, made from an up-to-date `main` on the Mac and installed by each app's updater on the farm PC.
- `stop_server.ps1` stops each server, never a bare `schtasks /end`. Labour's copy is the reference.
- Each installer adds a Git `safe.directory` exception so SYSTEM's Git can read the repo folder.
- Python 3.9-compatible code, plain JS with no CDNs (the phones are tailnet-only), and `VERSION` plus the service-worker `CACHE` bumped with every frontend change.
- Fixes to the copied deployment files (`install.ps1`, the updaters, `stop_server.ps1`, `release.sh`) flow between the repos.

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
- **`stop_server.ps1` is the reference copy.** The updater and installer stop the server with it, never with a bare `schtasks /end`, because the uvicorn process outlives the launcher and keeps port 8040. Boord Owner (1.9.3) and Boord Notes (2.18) carry adapted copies, with their own port and task name. A fix here belongs in those two copies as well. The app table the watchdog and heartbeat read is **Boord Monitor's** `apps.json`; the `tailscale serve` port table is in **Boord's** MANUAL.md.

## Installing and deploying

### Where it lives

| | |
|---|---|
| Your Mac (the only clone to release from) | `~/Documents/Projects/Boord-labour` |
| Farm PC folder | `C:\Boord-labour` |
| Farm PC scheduled task | "Boord Labour Server", runs as SYSTEM at boot |
| Port on the farm PC | `127.0.0.1:8040` |
| Address on the tailnet | `https://bekfontein-server.taile32cb0.ts.net:8040/` |

### First install on the farm PC (once)

Only for a new PC or a reinstall. An app that is already running is updated, not reinstalled.

1. Open a Command Prompt and clone the repo into the folder above:
   ```bat
   git clone https://github.com/DawiePieterse/Boord-labour.git C:\Boord-labour
   ```
2. In `C:\Boord-labour`, double-click **`install.bat`** and accept the administrator prompt. It asks for the full path to Boord's `data\boord.db` and for the admin PIN (`backend\set_pin.py` changes the PIN later and signs every phone out).
   It installs Python if needed, builds the app's environment, writes the launcher, registers the scheduled task, reserves the port so Windows can't hand it to Hyper-V, WSL or Docker at boot, and starts the server. Re-running it is safe and keeps the data.
3. Tell the updater which release key to trust. In the same folder, type it exactly like this, with the redirect first:
   ```bat
   >data\release_key.fpr echo 67C64CFDD584DD140E58AF6E329C9B9DD0562A9D
   ```
4. Publish it on the tailnet, in a Command Prompt opened as administrator:
   ```bat
   tailscale serve --bg --https=8040 http://localhost:8040
   ```
5. If the installer did not already add it, let SYSTEM's Git read the folder, as administrator (forward slashes):
   ```bat
   git config --system --add safe.directory C:/Boord-labour
   ```
6. Check it from your Mac: `curl -s https://bekfontein-server.taile32cb0.ts.net:8040/api/version` should show the release tag.

### Deploying a change (every release)

Merging to `main` changes nothing on the farm. A release is a signed tag, and the farm PC installs it when its updater runs.

1. **Merge the PR on GitHub.** A frontend change must already bump `VERSION` in `frontend/shared/api.js` and the service worker's `CACHE`.
2. **On your Mac, bring the clone up to date.** This step is what stops a tag landing on an old commit:
   ```sh
   cd ~/Documents/Projects/Boord-labour && git checkout main && git pull --ff-only origin main
   git log -1 --format='%h %s'                  # the merge you expect
   grep -m1 'VERSION:' frontend/shared/api.js   # the version you are releasing
   ```
3. **Sign and push the tag** (`vX.Y` must equal `VERSION`):
   ```sh
   scripts/release.sh vX.Y && git push origin vX.Y
   ```
   Never move or reuse a released tag. Fix a wrong one with the next version.
4. **On the farm PC**, in `C:\Boord-labour`, double-click **`update_labour_server.bat`**. It verifies the signature, stops the server with `stop_server.ps1`, installs dependencies, copies and migrates the database, and starts it again. If it stops with an error, nothing has changed. Read the message; never check the tag out by hand.
5. **If the release changed `install.ps1`** (its notes say "run install.bat once more"), double-click `install.bat` as well. The updater does not rewrite the launcher or the task.
6. **Check from your Mac:** `curl -s https://bekfontein-server.taile32cb0.ts.net:8040/api/version` should show `"tag":"vX.Y","state":"release"`.
7. **Close and reopen the door page and the admin page on each phone so they load the new version.**
