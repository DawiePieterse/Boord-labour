# Boord Labour - manual

Boord Labour is the packhouse time clock. An admin phone at the warehouse
door scans each worker's **existing Boord badge** on the way in and on the
way out, and the app turns those scans into hours and pay at an hourly
rate. Boord itself is unchanged: it still pays pickers per kg, and Boord
Labour only *reads* Boord's worker list.

## 1. Installing on the farm server

Boord must already be installed on the same PC.

1. Put this folder beside Boord (e.g. `C:\Boord` and `C:\Boord-labour`).
2. Double-click **install.bat** and accept the administrator prompt. It
   installs Python if needed, finds Boord's `data\boord.db` (or asks you for
   it), asks you to choose the **admin PIN** (see 1a), and registers the
   **Boord Labour Server** task, which starts with Windows on port **8040**.
3. Publish the app on Tailscale. Boord keeps 443, and Labour takes 8040:
   ```
   tailscale serve --bg --https=8040 http://localhost:8040
   ```
   If you ever run `tailscale serve reset`, run the full block from
   Boord's MANUAL.md ("If other apps are on this machine too") with this
   line added. `reset` unpublishes every app it isn't told to put back.
4. Open `https://<server>.<tailnet>.ts.net:8040/` on a phone to check it.

### Access

The app has two parts:

| Address | Who | What |
| --- | --- | --- |
| `…ts.net:8040/` | the phone at the door | the scanner, and who is inside now |
| `…ts.net:8040/admin/` | the admin, **with the PIN** | Today, Fix, Pay, Settings |

The server listens on `127.0.0.1` only, so the only way in at all is
through Tailscale. Use `serve`, never `funnel`. Tailscale alone cannot keep
the door phone out of pay, because that phone has to be on Tailscale for
its camera. That is the PIN's job: the server refuses every pay, rate and
correction request without it, whatever page asked.

Boord Admin has a **Packhouse labour** link next to its tabs that opens
`/admin/` on the same server.

### 1a. Admin PIN

- **Set at install.** The installer asks for it (at least 4 characters).
  The web page can never set the first PIN, so a fresh install can't be
  claimed by whichever phone opens it first.
- **Signing in** on a phone keeps it signed in until someone taps **Sign
  out** (Admin → Settings), or the PIN changes.
- **Change it** under Admin → Settings. That signs out **every other
  phone**, which is how you lock out a lost phone or someone who has left.
- **Forgot it?** On the server, in the `backend` folder:
  ```
  .venv\Scripts\python set_pin.py
  ```
  This sets a new PIN and signs every phone out.
- **Five wrong PINs** lock Admin sign-in for 5 minutes.

## 2. Setting up a phone

**The door phone** (the person scanning never gets the PIN):

1. Open `https://<server>.<tailnet>.ts.net:8040/` in Chrome (Android) or
   Safari (iPhone), and **Add to Home screen**.
2. Allow the camera when asked. The camera only works on the `https://`
   Tailscale address, never on a plain `http://` one.
3. Tap the phone's name under **Boord Labour** in the header and call it
   something like "Door 1". Every scan carries that name.

**The admin's phone or PC:** open `…ts.net:8040/admin/` (or the Packhouse
labour link in Boord Admin) and sign in with the PIN.

## 3. At the door

For each worker, tap **Scan Worker QR** and point the camera at the badge.
The camera closes as soon as it reads the badge, and the screen turns:

- **green IN** when the worker was not inside, or
- **red OUT** when they were.

It shows the worker's name and photo, then goes back to the **Scan Worker
QR** button for the next person. **Cancel** closes the camera without
scanning.

**If the direction is wrong** (say the screen says IN but they are leaving),
tap **"Wrong? Make it OUT"** while the screen is still showing. If the same
badge is scanned again within a minute, the phone says so and records
nothing, so a double tap at the door can't turn an IN into an OUT.

**No connection?** Keep scanning. Scans are saved on the phone with the time
they were scanned and are sent when the connection returns. The header says
"offline - scans saved", and *Waiting to sync* counts them.

The **Inside** tab lists who is in the building now, with the time they
came in. It shows no hours or pay.

If a worker says the screen showed IN when they were leaving, they missed
their morning scan. Tell the admin, who adds it under **Fix**.

## 4. Fixing missed scans (Admin)

**Fix** lists every scan that has no partner: an IN with no OUT, or an OUT
with no IN. **Those hours are not paid until they are fixed.**

- **Add exit time / Add entry time**: enter the real time and say why.
- **Delete this scan**: for a stray or double scan.
- **Scans on [date]**: every scan that day. Use the pencil to correct a
  time or direction, or **Add** to enter a scan by hand.

Every correction asks for a reason and is kept on record with the time and
the phone that made it.

An IN with no OUT after 18 hours counts as a forgotten exit.

## 5. Rates and overtime (Admin)

**Admin → Settings → Hourly rate.** Nothing is paid until a rate exists. A rate
applies from its date onward, and earlier days keep the rate they had. To
change the rate, add a new one; don't edit the old one.

Overtime follows the BCEA pattern:

- Hours past **9 a day** are overtime.
- Of the remaining hours, any that take the **Monday-Sunday week past 45**
  are overtime, on the day they happen.
- Overtime is paid at **1.5×** the rate.

All three numbers are set with the rate. A shift counts on the day it
started, so a night shift is paid on its first day.

## 6. The pay report (Admin)

**Pay**: pick a period (This week, Last week, or any dates) and tap
**Show**. **Export** downloads an Excel file with three sheets:

- **Pay**: totals per worker.
- **Shifts**: every in/out pair.
- **Unresolved**: scans still needing a fix.

A period that starts mid-week still counts the whole week's hours toward
the 45-hour overtime threshold.

## 7. Backups

`data\labour.db` is the only record of who worked when, and nothing in it
can be rebuilt from Boord. Every night at 02:00 the server zips it into
`data\backups\` (keeping 30) if it changed. If Boord has an off-site folder
set in `Boord\data\backup_copy_to.txt`, each archive is also copied there as
`labour_backup_*.zip`.

To restore: stop the **Boord Labour Server** task, unzip `labour.db` from
an archive over `data\labour.db`, and start the task again.

## 8. Updates

**update_labour_server.bat** installs the newest **signed** release and
restarts the server. It uses the same release key as Boord. Before the
first update, write the key's fingerprint into `data\release_key.fpr` (the
installer prints the command, reusing Boord's fingerprint if it finds one).

**Installed before 1.0.3? Run install.bat once more.** Older installers
registered the **Boord Labour Server** task with Windows' default limit of
72 hours, so Windows stopped the server three days after each restart, and
did not start it again if it crashed. The installer now removes that limit
and has the task restart the server (up to 10 times, a minute apart).
Updating does not change the task: only re-running **install.bat** does.
It keeps your data and PIN.

## 9. Uptime

The watchdog and heartbeat scripts live in the **Boord** folder and cover
every app on the PC, Boord Labour (port 8040) included.
