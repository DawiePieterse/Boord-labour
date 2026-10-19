# Boord Labour — Training Guide

For the packhouse: the person scanning workers at the warehouse door, and
the admin who checks the hours and runs the pay.

Packhouse workers are paid by the hour. Each worker's existing Boord badge
is scanned when they come in and again when they leave, and Boord Labour
works out the hours and the pay from those two scans. The badge is the
same one they already use in Boord, so there is nothing new to print.

---

## Part 1 — At the door

### Getting the phone ready (once)

Your supervisor usually does this when the phone is first set up.

1. Open the Labour address on the phone (ending in **:8040/**) and choose
   **Add to Home screen**. A **Labour** icon with a violet leaf appears.
2. Open Labour from that icon and allow the camera when the phone asks.
3. Tap the phone's name under **Boord Labour** at the top and call it
   something like **Door 1**. Every scan is marked with this name.

### Scanning a worker

Do this for every worker, every time they come in and every time they
leave.

1. Tap **Scan Worker QR**. The camera opens.
2. Hold the worker's badge in front of the camera.
3. The camera closes and the screen turns **green IN** when they are
   arriving, or **red OUT** when they are leaving.
4. Check that the **name and photo** match the person in front of you.
5. After a few seconds the screen goes back to **Scan Worker QR**, ready
   for the next person. Tap **Done** to go back straight away.

Tap **Cancel** if you opened the camera by mistake.

> **Only scan the badge of the person standing in front of you.** Never
> scan a badge for someone who isn't there. Pay is worked out from these
> scans, so a badge scanned for an absent worker pays them for hours they
> didn't work.

### If the screen shows the wrong direction

Say the screen shows **IN** but the worker is leaving. While that screen is
still showing, tap **Wrong? Make it OUT**. The scan is changed straight
away.

If a worker says the screen showed IN when they were leaving, they
probably forgot to scan in that morning. Tell the admin, who will fix it.

### Messages you might see

| What you see | What it means | What to do |
| --- | --- | --- |
| *"… was scanned a moment ago"* | That badge was already scanned less than a minute ago. Nothing new was saved. | Nothing. If it really needs scanning again, wait a minute. |
| Red **?** screen, *"not an active Boord worker"* | The badge isn't in Boord, or that worker was switched off there. | Write down the person's name and the time, and tell your supervisor. |
| *"offline - scans saved"* at the top | The phone can't reach the server right now. | Keep scanning. Scans are kept on the phone and sent when the connection comes back. *Waiting to sync* shows how many are waiting. |
| *"Camera unavailable"* | The phone has blocked the camera for Labour. | Allow the camera for Labour in the phone's settings, then tap **Scan Worker QR** again. |
| *"Scanning needs the secure address"* | Tailscale isn't connected on this phone. | Open the Tailscale app, switch it on, then try again. |

### The Inside tab

Tap **Inside** at the bottom to see who is in the building right now and
what time they came in. Use it when a worker asks "did I scan in?". It
shows no hours and no pay.

### Golden rules at the door

1. Scan **every** worker, **in and out**, every time.
2. Look at the **name and photo** before they walk off.
3. If the direction is wrong, fix it on the spot with **Wrong? Make it…**
4. If anything else goes wrong, tell the admin the **name and the time**.

<div style="page-break-before: always"></div>

## Part 2 — Admin

Admin is where hours are checked, missed scans fixed and pay worked out.
It needs the **admin PIN**. Never give the PIN to the person on the door.

### Signing in

Open the Labour address with **/admin/** on the end, or tap **Packhouse
labour** next to the tabs in Boord Admin. Enter the PIN.

A phone or PC stays signed in until someone taps **Sign out**
(under **Settings**) or the PIN is changed.

### Today

Lists everyone inside the packhouse now, with the time they came in and
how long they have been there. It refreshes by itself.

### Fix: missed scans

A worker who scanned **in but not out**, or **out but not in**, appears
here. **Those hours are not paid until they are fixed.** A red number on
the **Fix** tab shows how many are waiting.

For each one, either:

- **Add exit time** (or **Add entry time**): enter the real time the worker
  left or arrived, and a reason, such as *"Forgot to scan out, supervisor
  confirmed 17:00"*.
- **Delete this scan**: for a stray scan, such as a badge scanned twice by
  mistake. You will be asked for a reason.

**Scans on** shows every scan on the day you choose:

- The **pencil** changes a scan's time or direction.
- The **bin** deletes a scan.
- **Add** enters a scan by hand, for example when the door phone was out of
  action.

Every change asks **why**, and Labour keeps a record of what changed, when,
from which phone, and the reason given.

### Pay

1. Tap **This week** or **Last week**, or choose your own dates.
2. Tap **Show** to see each worker's days, hours, overtime and amount.
3. Tap **Export** to download an Excel file with three sheets: **Pay**
   (totals per worker), **Shifts** (every in and out) and **Unresolved**
   (scans still waiting to be fixed).

If a yellow message says some scans are *not paid yet*, go to **Fix**
first, then come back.

**How the pay is worked out:**

- Hours = time between a worker's IN and their OUT.
- **Overtime** is anything over **9 hours in a day**, plus anything over
  **45 hours in the week** (Monday to Sunday). Overtime is paid at
  **1.5×** the hourly rate. No hour is counted as overtime twice.
- A shift counts on the day it **started**, so a night shift that ends
  after midnight belongs to the day it began.

### Settings

**Hourly rate.** Nothing can be paid until a rate exists. To change the
rate, **add a new one** with the date it starts. Days before that date keep
the old rate, so earlier pay reports still show what was actually paid.
The overtime rules (1.5×, 9 hours, 45 hours) are set with each rate.

**Admin PIN.** **Change PIN** asks for the current PIN and a new one (at
least 4 characters). Changing it **signs every other phone out of
Admin**. That is how you lock out a lost phone, or someone who no longer
works here. If the PIN is forgotten, whoever looks after the farm server
can set a new one there.

### The weekly routine

1. Open **Fix** and clear the list, so nobody is left unpaid.
2. Open **Pay**, choose **Last week**, and tap **Show**.
3. Check for anything unusual, such as a 14-hour day.
4. Tap **Export** and use the Excel file for the payroll.
