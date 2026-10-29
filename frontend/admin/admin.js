// Boord Labour Admin - who is inside, fixing unpaired scans, the pay report
// and rates. Behind the admin PIN: the server refuses every call here
// without the cookie a correct PIN hands out (backend/admin_auth.py), and a
// 401 from any of them brings the PIN screen back.

const $ = (id) => document.getElementById(id);
const esc = (v) => Boord.escapeHtml(v);

// Inside longer than this is probably a forgotten exit: shown red and listed
// under Fix. A warning only - pay still pairs up to MAX_SHIFT (18h, pay.py),
// so a real night or overtime shift is paid once they scan out.
const LONG_SHIFT_MS = 12 * 3600 * 1000;

let workers = [];
let currentTab = "today";

function deviceLabel() { return localStorage.getItem("labour_device_label") || "Admin"; }

async function api(path, opts) {
  try {
    return await Boord.api(path, opts);
  } catch (e) {
    if (e.status === 401 && path !== "/api/admin/login") showPin();
    throw e;
  }
}

// --------------------------------------------------------------------------
// PIN
// --------------------------------------------------------------------------
function showPin() {
  $("pinScreen").classList.remove("hidden");
  ["adminMain", "adminNav"].forEach((id) => $(id).classList.add("hidden"));
  $("pinInput").value = "";
  $("pinInput").focus();
}

async function showAdmin() {
  $("pinScreen").classList.add("hidden");
  ["adminMain", "adminNav"].forEach((id) => $(id).classList.remove("hidden"));
  try { workers = await api("/api/workers"); } catch (_) { /* shown when needed */ }
  showTab(currentTab);
  Promise.all([api("/api/exceptions"), api("/api/presence")])
    .then(([l, p]) => setFixBadge(l.length + longInside(p).length)).catch(() => {});
}

async function signIn(ev) {
  ev.preventDefault();
  $("pinError").textContent = "";
  try {
    await api("/api/admin/login", { method: "POST", body: { pin: $("pinInput").value } });
    await showAdmin();
  } catch (e) {
    $("pinError").textContent = Boord.errorDetail(e, "No connection to the server");
  }
}

// --------------------------------------------------------------------------
// Today
// --------------------------------------------------------------------------
function longInside(presence) {
  return presence.filter((p) => Date.now() - Boord.parseServerDate(p.in_ts).getTime() > LONG_SHIFT_MS);
}

function hoursSince(ms) {
  const mins = Math.floor((Date.now() - ms) / 60000);
  return `${Math.floor(mins / 60)}h${String(mins % 60).padStart(2, "0")}`;
}

async function renderToday() {
  let rows = [];
  try { rows = await api("/api/presence"); } catch (_) { return; }
  $("presenceList").innerHTML = rows.map((p) => {
    const t = Boord.parseServerDate(p.in_ts);
    const long = Date.now() - t.getTime() > LONG_SHIFT_MS;
    return `<li class="py-2 flex justify-between ${long ? "text-red-700 font-semibold" : ""}"><span>${esc(p.name)}
      <span class="${long ? "" : "text-slate-400"}">#${esc(p.worker_id)}</span></span>
      <span class="${long ? "" : "text-slate-600"}">in ${Boord.fmtTime(t)} · ${hoursSince(t.getTime())}${long ? " · scanned out?" : ""}</span></li>`;
  }).join("") || `<li class="py-2 text-slate-500">Nobody is scanned in.</li>`;
}

// --------------------------------------------------------------------------
// Fix: exceptions and hand corrections
// --------------------------------------------------------------------------
async function renderFix() {
  let list = [], presence = [];
  try { [list, presence] = await Promise.all([api("/api/exceptions"), api("/api/presence")]); } catch (e) { return; }
  const long = longInside(presence);
  setFixBadge(list.length + long.length);
  $("longList").innerHTML = long.map((p) => `<li class="py-2">
      <div><b>${esc(p.name)}</b> <span class="text-slate-400">#${esc(p.worker_id)}</span></div>
      <div class="text-red-700">Scanned IN ${Boord.fmtDateTime(p.in_ts)} - inside ${hoursSince(Boord.parseServerDate(p.in_ts).getTime())}</div>
      <div class="mt-1"><button class="border rounded-lg px-2 py-1" data-add="${esc(p.worker_id)}" data-dir="out"
        data-ts="${esc(p.in_ts)}">Add exit time</button></div></li>`).join("") ||
    `<li class="py-2 text-slate-500">Nobody.</li>`;
  $("exceptionList").innerHTML = list.map((e) => {
    const missingExit = e.kind === "missing_exit";
    return `<li class="py-2">
      <div><b>${esc(e.name)}</b> <span class="text-slate-400">#${esc(e.worker_id)}</span></div>
      <div class="text-slate-600">${missingExit ? "Scanned IN" : "Scanned OUT"} ${Boord.fmtDateTime(e.ts)} -
        no ${missingExit ? "exit" : "entry"} scan</div>
      <div class="flex gap-2 mt-1">
        <button class="border rounded-lg px-2 py-1" data-add="${esc(e.worker_id)}" data-dir="${missingExit ? "out" : "in"}"
          data-ts="${esc(e.ts)}">Add ${missingExit ? "exit" : "entry"} time</button>
        <button class="border rounded-lg px-2 py-1 text-red-700" data-del="${esc(e.uuid)}">Delete this scan</button>
      </div></li>`;
  }).join("") || `<li class="py-2 text-slate-500">Nothing to fix.</li>`;
  await renderDayScans();
}

function setFixBadge(n) {
  $("fixBadge").textContent = n;
  $("fixBadge").classList.toggle("hidden", !n);
}

// The day's scans as one row per shift, IN beside OUT, so a missing or
// stray scan stands out. Pairs the way pay.py does (repeat within 60s
// ignored, IN then OUT within 18h), over the day either side so a night
// shift's other half is found; a row shows when either half is on the day.
const DUPLICATE_MS = 60 * 1000;
const MAX_SHIFT_MS = 18 * 3600 * 1000;

function shiftRows(scans) {
  const byWorker = new Map();
  scans.forEach((s) => byWorker.set(s.worker_id, [...(byWorker.get(s.worker_id) || []), s]));
  const rows = [];
  for (const list of byWorker.values()) {
    list.sort((a, b) => a.ts.localeCompare(b.ts));
    let open = null, last = null;
    for (const s of list) {
      const t = Boord.parseServerDate(s.ts).getTime();
      if (last !== null && t - last < DUPLICATE_MS) { rows.push({ repeat: s }); continue; }
      last = t;
      if (s.direction === "in") {
        if (open) rows.push({ in: open });
        open = s;
      } else if (open && t - Boord.parseServerDate(open.ts).getTime() <= MAX_SHIFT_MS) {
        rows.push({ in: open, out: s });
        open = null;
      } else {
        if (open) rows.push({ in: open });
        rows.push({ out: s });
        open = null;
      }
    }
    if (open) rows.push({ in: open, inside: Date.now() - Boord.parseServerDate(open.ts).getTime() <= MAX_SHIFT_MS });
  }
  return rows;
}

function scanCell(s, day) {
  const d = Boord.parseServerDate(s.ts);
  const other = Boord.localDateStr(d) !== day
    ? ` <span class="text-slate-400 text-xs">${d.toLocaleDateString("en-ZA", { day: "numeric", month: "short" })}</span>` : "";
  return `<div class="flex items-center gap-1 whitespace-nowrap">
      <b class="${s.direction === "in" ? "text-green-700" : "text-red-700"}">${s.direction.toUpperCase()}</b>
      ${Boord.fmtTime(d)}${other}${s.source === "admin" ? ` <i class="fa-solid fa-hand text-slate-400 text-xs" title="Added by hand"></i>` : ""}
      <button class="border rounded px-1.5 ml-auto" data-edit="${esc(s.uuid)}" data-ts="${esc(s.ts)}" data-dir="${s.direction}"
        data-name="${esc(s.name)}"><i class="fa-solid fa-pen"></i></button>
      <button class="border rounded px-1.5 text-red-700" data-del="${esc(s.uuid)}"><i class="fa-solid fa-trash"></i></button>
    </div>`;
}

function missingCell(other, dir) {
  return `<div class="flex items-center gap-1 text-red-700 font-semibold">no ${dir.toUpperCase()}
      <button class="border rounded px-1.5 ml-auto font-normal" data-add="${esc(other.worker_id)}" data-dir="${dir}"
        data-ts="${esc(other.ts)}">Add</button></div>`;
}

async function renderDayScans() {
  const day = $("scanDay").value;
  const shift = (n) => { const d = new Date(`${day}T12:00`); d.setDate(d.getDate() + n); return Boord.localDateStr(d); };
  let scans = [];
  try {
    scans = (await Promise.all([-1, 0, 1].map((n) => api(`/api/scans?day=${shift(n)}`)))).flat();
  } catch (e) { return; }
  const onDay = (s) => s && Boord.localDateStr(Boord.parseServerDate(s.ts)) === day;
  const rows = shiftRows(scans).filter((r) => onDay(r.in) || onDay(r.out) || onDay(r.repeat))
    .sort((a, b) => {
      const x = a.in || a.out || a.repeat, y = b.in || b.out || b.repeat;
      return x.name.localeCompare(y.name) || x.ts.localeCompare(y.ts);
    });
  $("dayScanList").innerHTML = rows.map((r) => {
    const s = r.in || r.out || r.repeat;
    const bad = r.repeat || !r.in || (!r.out && !r.inside);
    const hours = r.in && r.out
      ? `${((Boord.parseServerDate(r.out.ts) - Boord.parseServerDate(r.in.ts)) / 3600000).toFixed(1)}h` : "";
    return `<li class="py-2 ${bad ? "bg-red-50 -mx-3 px-3" : ""}">
      <div class="flex justify-between"><span><b>${esc(s.name)}</b> <span class="text-slate-400">#${esc(s.worker_id)}</span></span>
        <span class="text-slate-500">${r.repeat ? "repeat scan, ignored" : r.inside ? "still inside" : hours}</span></div>
      ${r.repeat ? scanCell(r.repeat, day) : `<div class="grid grid-cols-2 gap-3 mt-1">
        ${r.in ? scanCell(r.in, day) : missingCell(r.out, "in")}
        ${r.out ? scanCell(r.out, day) : r.inside ? "<div></div>" : missingCell(r.in, "out")}</div>`}
    </li>`;
  }).join("") || `<li class="py-2 text-slate-500">No scans that day.</li>`;
}

// datetime-local wants "YYYY-MM-DDTHH:MM" in local time.
function toLocalInput(date) {
  const d = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return d.toISOString().slice(0, 16);
}

let scanFormSubmit = null;
function openScanForm({ title, workerId, ts, direction, onSubmit }) {
  $("scanFormTitle").textContent = title;
  const sel = $("scanFormWorker");
  $("scanFormWorkerWrap").classList.toggle("hidden", workerId !== undefined);
  sel.innerHTML = workers.map((w) => `<option value="${esc(w.id)}">${esc(w.id)} - ${esc(w.name)}</option>`).join("");
  if (workerId) sel.value = workerId;
  $("scanFormTime").value = toLocalInput(ts || new Date());
  $("scanFormDir").value = direction || "in";
  $("scanFormReason").value = "";
  scanFormSubmit = onSubmit;
  $("scanForm").classList.remove("hidden");
  $("scanForm").classList.add("flex");
}

function closeScanForm() {
  $("scanForm").classList.add("hidden");
  $("scanForm").classList.remove("flex");
}

async function onFixClick(ev) {
  const btn = ev.target.closest("button");
  if (!btn) return;
  try {
    if (btn.dataset.add) {
      openScanForm({
        title: "Add the missing scan", workerId: btn.dataset.add,
        ts: Boord.parseServerDate(btn.dataset.ts), direction: btn.dataset.dir,
        onSubmit: (f) => api("/api/scans", { method: "POST", body: { worker_id: btn.dataset.add, ...f } }),
      });
    } else if (btn.dataset.edit) {
      openScanForm({
        title: `Change scan - ${btn.dataset.name}`, workerId: null,
        ts: Boord.parseServerDate(btn.dataset.ts), direction: btn.dataset.dir,
        onSubmit: (f) => api(`/api/scans/${btn.dataset.edit}`, { method: "PATCH", body: f }),
      });
    } else if (btn.dataset.del) {
      const reason = prompt("Delete this scan. Why? (kept on record)");
      if (!reason || !reason.trim()) return;
      await api(`/api/scans/${btn.dataset.del}/delete`, { method: "POST", body: { reason, device_label: deviceLabel() } });
      Boord.toast("Scan deleted");
      renderFix();
    }
  } catch (e) {
    Boord.toast(Boord.errorDetail(e));
  }
}

// --------------------------------------------------------------------------
// Pay report
// --------------------------------------------------------------------------
function mondayOf(d) {
  const m = new Date(d);
  m.setHours(12, 0, 0, 0);
  m.setDate(m.getDate() - ((m.getDay() + 6) % 7));
  return m;
}

function setWeek(offsetWeeks) {
  const mon = mondayOf(new Date());
  mon.setDate(mon.getDate() + 7 * offsetWeeks);
  const sun = new Date(mon);
  sun.setDate(mon.getDate() + 6);
  $("repStart").value = Boord.localDateStr(mon);
  $("repEnd").value = Boord.localDateStr(sun);
}

// en-ZA, like every amount on Boord's screens: "R 1 234,50". The export
// keeps plain numbers - it is built server-side for Excel, not from these.
const money = (n) => Boord.fmtRand(n);

async function showReport() {
  const warn = $("repWarning");
  try {
    const r = await api(`/api/reports/hours?start=${$("repStart").value}&end=${$("repEnd").value}`);
    $("repBody").innerHTML = r.workers.map((w) => `<tr class="border-t">
        <td>${esc(w.worker_id)}</td><td>${esc(w.name)}</td><td class="text-right">${w.days}</td>
        <td class="text-right">${Boord.fmtNum(w.hours, 2)}</td><td class="text-right">${Boord.fmtNum(w.overtime, 2)}</td>
        <td class="text-right">${money(w.amount)}</td></tr>`).join("") +
      `<tr class="border-t font-bold"><td></td><td>Total</td><td></td><td></td><td></td>
        <td class="text-right">${money(r.total)}</td></tr>`;
    warn.classList.toggle("hidden", !r.unresolved);
    warn.textContent = `${r.unresolved} unpaired scan(s) in this period are not paid yet - see Fix.`;
  } catch (e) {
    $("repBody").innerHTML = "";
    warn.classList.remove("hidden");
    warn.textContent = Boord.errorDetail(e, "Needs a connection to the server");
  }
}

// A season's workbook can take a while to build, and a button that looks
// untouched after a tap gets tapped again - each tap another export queued on
// the farm PC. So it is disabled and says what it is doing until it is done.
async function exportReport() {
  const btn = $("repExport");
  if (btn.disabled) return;
  const start = $("repStart").value, end = $("repEnd").value;
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Exporting...`;
  try {
    const blob = await api(`/api/reports/hours?start=${start}&end=${end}&format=xlsx`, { timeoutMs: 60000 });
    Boord.downloadBlob(blob, `labour-hours-${start}-to-${end}.xlsx`);
  } catch (e) {
    Boord.toast(Boord.errorDetail(e));
  } finally {
    btn.disabled = false;
    btn.innerHTML = label;
  }
}

// --------------------------------------------------------------------------
// Settings
// --------------------------------------------------------------------------
async function renderSettings() {
  try {
    const rates = await api("/api/settings/rates");
    $("rateList").innerHTML = rates.map((r) => `<li class="py-1">From <b>${esc(Boord.fmtDate(r.effective_date, r.effective_date))}</b>:
      ${money(r.hourly_rate)}/h, overtime ×${r.ot_multiplier} after ${r.daily_ot_after_h}h/day or
      ${r.weekly_ot_after_h}h/week</li>`).join("") ||
      `<li class="py-1 text-red-700">No rate set - the pay report will refuse to calculate until one is added.</li>`;
  } catch (e) { /* 401 shows the PIN screen; offline leaves the list as it was */ }
  await renderBackups();
}

async function renderBackups() {
  let rows = [];
  try { rows = await api("/api/settings/backups"); } catch (e) { return; }
  $("backupList").innerHTML = rows.map((b) => `<tr>
      <td class="py-1">${Boord.fmtDateTime(b.created_at)}</td>
      <td>${(b.size_bytes / 1024).toFixed(0)} KB</td>
      <td class="text-right"><button class="text-blue-700" data-download="${esc(b.filename)}">Download</button></td>
    </tr>`).join("") || `<tr><td class="py-1 text-slate-500" colspan="3">No backups yet</td></tr>`;
}

async function runBackup() {
  try {
    await api("/api/settings/backups", { method: "POST", timeoutMs: Boord.UPLOAD_TIMEOUT_MS });
    Boord.toast("Backup created");
    renderBackups();
  } catch (e) {
    Boord.toast(`Backup failed: ${Boord.errorDetail(e)}`);
  }
}

async function downloadBackup(ev) {
  const name = ev.target.closest("[data-download]")?.dataset.download;
  if (!name) return;
  try {
    const blob = await api(`/api/settings/backups/${encodeURIComponent(name)}/download`, { timeoutMs: Boord.UPLOAD_TIMEOUT_MS });
    Boord.downloadBlob(blob, name);
  } catch (e) {
    Boord.toast(Boord.errorDetail(e));
  }
}

async function saveRate() {
  try {
    await api("/api/settings/rates", { method: "POST", body: {
      effective_date: $("rateDate").value, hourly_rate: Number($("rateHourly").value),
      ot_multiplier: Number($("rateMult").value), daily_ot_after_h: Number($("rateDaily").value),
      weekly_ot_after_h: Number($("rateWeekly").value),
    } });
    Boord.toast("Rate saved");
    renderSettings();
  } catch (e) {
    Boord.toast(Boord.errorDetail(e));
  }
}

async function changePin() {
  try {
    await api("/api/admin/pin", { method: "POST", body: { current: $("pinCurrent").value, new: $("pinNew").value } });
    $("pinCurrent").value = $("pinNew").value = "";
    Boord.toast("PIN changed - other phones must sign in again");
  } catch (e) {
    Boord.toast(Boord.errorDetail(e));
  }
}

async function signOut() {
  await Boord.api("/api/admin/logout", { method: "POST" }).catch(() => {});
  showPin();
}

// --------------------------------------------------------------------------
// Tabs and start-up
// --------------------------------------------------------------------------
function showTab(name) {
  currentTab = name;
  document.querySelectorAll("[data-tab]").forEach((s) => s.classList.toggle("hidden", s.dataset.tab !== name));
  // .tab-active (shared/styles.css) is the brand blue, the same as the header.
  document.querySelectorAll("[data-nav]").forEach((b) => b.classList.toggle("tab-active", b.dataset.nav === name));
  if (name === "today") renderToday();
  if (name === "fix") renderFix();
  if (name === "report") showReport();
  if (name === "settings") renderSettings();
}

Boord.boot(async () => {
  $("appVersion").textContent = `v${Boord.VERSION}`;
  // Every list here swallows a failed fetch and keeps what it showed last, so
  // without the banner an admin with no signal reads stale presence and
  // exceptions as current. The door page (app.js) does the same.
  Boord.offlineBanner("No connection to the server - showing what was loaded last");
  $("pinForm").addEventListener("submit", signIn);
  document.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.nav)));
  $("exceptionList").addEventListener("click", onFixClick);
  $("longList").addEventListener("click", onFixClick);
  $("dayScanList").addEventListener("click", onFixClick);
  $("scanDay").value = Boord.localDateStr();
  $("scanDay").addEventListener("change", renderDayScans);
  $("addScanBtn").addEventListener("click", () => openScanForm({
    title: "Add a scan by hand", ts: new Date(),
    onSubmit: (f) => api("/api/scans", { method: "POST", body: { worker_id: $("scanFormWorker").value, ...f } }),
  }));
  $("scanFormCancel").addEventListener("click", closeScanForm);
  $("scanFormEl").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await scanFormSubmit({
        timestamp: new Date($("scanFormTime").value).toISOString(),
        direction: $("scanFormDir").value, reason: $("scanFormReason").value, device_label: deviceLabel(),
      });
      closeScanForm();
      Boord.toast("Saved");
      renderFix();
    } catch (e) {
      Boord.toast(Boord.errorDetail(e));
    }
  });
  document.querySelectorAll("[data-preset]").forEach((b) =>
    b.addEventListener("click", () => { setWeek(b.dataset.preset === "this" ? 0 : -1); showReport(); }));
  $("repShow").addEventListener("click", showReport);
  $("repExport").addEventListener("click", exportReport);
  $("rateDate").value = Boord.localDateStr();
  $("saveRate").addEventListener("click", saveRate);
  $("runBackup").addEventListener("click", runBackup);
  $("backupList").addEventListener("click", downloadBackup);
  $("changePin").addEventListener("click", changePin);
  $("signOut").addEventListener("click", signOut);
  setWeek(0);
  setInterval(() => { if (currentTab === "today" && !$("adminMain").classList.contains("hidden")) renderToday(); }, 30000);

  try {
    await api("/api/admin/me");
    await showAdmin();
  } catch (e) {
    if (e.status !== 401) {
      showPin();
      $("pinError").textContent = "No connection to the server";
    }
  }
});
