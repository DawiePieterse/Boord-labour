// Boord Labour - the door scanner and the admin screens around it.
//
// A scan is decided on the phone, from what it knows: if this worker is
// inside (server presence + this phone's own unsynced scans) it is an OUT,
// otherwise an IN. The direction is shown full screen and stored with the
// scan, and the operator can flip it there and then - see the note at the
// top of backend/models_labour.py for why it is recorded, not derived later.

const $ = (id) => document.getElementById(id);
const esc = (v) => Boord.escapeHtml(v);

const DUPLICATE_MS = 60 * 1000;          // same badge again within this = ignored (pay.py agrees)
const MAX_SHIFT_MS = 18 * 3600 * 1000;   // an IN older than this is a forgotten exit, not "inside" (pay.py)
const SYNC_EVERY_MS = 10 * 1000;
const RESULT_SHOW_MS = 5000;

let workers = new Map();     // id -> {id, name, photo}
let serverPresence = [];     // [{worker_id, in_ts}] as last fetched
let inside = new Map();      // worker_id -> in time (ms): server presence + local unsynced scans
const lastScanAt = new Map(); // worker_id -> ms, for the duplicate window
let scanner = null;
let resultTimer = null;
let currentTab = "scan";

// --------------------------------------------------------------------------
// Local state
// --------------------------------------------------------------------------
function deviceLabel() { return localStorage.getItem("labour_device_label") || "Phone"; }

function cachedJSON(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (_) { return fallback; }
}

async function loadWorkers() {
  try {
    const list = await Boord.api("/api/workers");
    localStorage.setItem("labour_workers", JSON.stringify(list));
    localStorage.setItem("labour_workers_at", new Date().toISOString());
  } catch (e) { /* offline - keep the cached list */ }
  workers = new Map(cachedJSON("labour_workers", []).map((w) => [w.id, w]));
  const at = localStorage.getItem("labour_workers_at");
  $("workerCacheInfo").textContent = `${workers.size} workers known on this phone` +
    (at ? `, list from ${Boord.fmtDateTime(at)}` : "");
}

// Who is inside = the server's view, then this phone's not-yet-synced scans
// replayed on top in order. Synced scans are already in the server's view.
async function rebuildInside() {
  inside = new Map(serverPresence.map((p) => [p.worker_id, Boord.parseServerDate(p.in_ts).getTime()]));
  for (const s of await IDB.pending()) {
    if (s.direction === "in") inside.set(s.worker_id, Date.parse(s.timestamp));
    else inside.delete(s.worker_id);
  }
  const now = Date.now();
  for (const [w, t] of inside) if (now - t > MAX_SHIFT_MS) inside.delete(w);
  $("insideCount").textContent = inside.size;
}

// --------------------------------------------------------------------------
// Sync
// --------------------------------------------------------------------------
let syncBusy = false;
async function syncNow() {
  if (syncBusy) return;
  syncBusy = true;
  try {
    const pending = await IDB.pending();
    if (pending.length) {
      const res = await Boord.api("/api/scans/sync", {
        method: "POST",
        body: { scans: pending.map(({ uuid, worker_id, timestamp, direction, device_label }) =>
          ({ uuid, worker_id, timestamp, direction, device_label })) },
      });
      await IDB.markSynced(res.accepted);
      // A rejection is permanent (worker no longer active in Boord), so it
      // stops retrying - but it stays on the phone, flagged, for the admin.
      for (const r of res.rejected) await IDB.markSynced([r.uuid], r.reason);
      if (res.rejected.length) Boord.toast(`${res.rejected.length} scan(s) refused: ${res.rejected[0].reason}`);
    }
    serverPresence = await Boord.api("/api/presence");
    localStorage.setItem("labour_presence", JSON.stringify(serverPresence));
    setSyncStatus(true);
  } catch (e) {
    setSyncStatus(false);
  } finally {
    syncBusy = false;
    await rebuildInside();
    await renderScanPanel();
  }
}

function setSyncStatus(ok) {
  const el = $("syncStatus");
  el.textContent = ok ? "online" : "offline - scans saved";
  el.className = `px-2 py-1 rounded-full ${ok ? "bg-green-500/80" : "bg-amber-500/90"}`;
}

// --------------------------------------------------------------------------
// Scanning
// --------------------------------------------------------------------------
async function startCamera() {
  // A browser only hands out the camera on https (or localhost). On the farm
  // that means the Tailscale address - same rule as Boord's Field app.
  if (!window.isSecureContext) {
    $("cameraBtn").classList.add("hidden");
    $("qrReader").innerHTML = `<div class="text-white p-6 text-center">Scanning needs the secure
      https://...ts.net:8040/ address - check Tailscale is connected on this phone.</div>`;
    return;
  }
  if (scanner) return;
  scanner = new Html5Qrcode("qrReader");
  try {
    await scanner.start({ facingMode: "environment" }, { fps: 10, qrbox: 220 }, onDecoded, () => {});
    $("cameraBtn").classList.add("hidden");
  } catch (e) {
    scanner = null;
    $("cameraBtn").classList.remove("hidden");
    Boord.toast("Camera unavailable - allow camera access, then tap Start camera");
  }
}

function stopCamera() {
  if (!scanner) return;
  const s = scanner;
  scanner = null;
  try { Promise.resolve(s.stop()).then(() => s.clear()).catch(() => {}); } catch (_) { /* never started */ }
}

async function onDecoded(text) {
  const id = text.trim();
  const now = Date.now();
  // The camera reports the same badge many times a second while it is in view.
  if (now - (lastScanAt.get(id) || 0) < DUPLICATE_MS) return;
  lastScanAt.set(id, now);

  const worker = workers.get(id);
  if (!worker) {
    Boord._tone(220, 0.35);
    showResult({ bad: true, name: `Badge "${id}" is not an active Boord worker` });
    return;
  }
  const scan = {
    uuid: Boord.uuid(), worker_id: id, timestamp: new Date(now).toISOString(),
    direction: inside.has(id) ? "out" : "in", device_label: deviceLabel(), synced: 0,
  };
  await IDB.put(scan);
  await rebuildInside();
  Boord.beepScanned();
  showResult({ scan, worker });
  renderScanPanel();
  syncNow();
}

function showResult({ scan, worker, bad, name }) {
  clearTimeout(resultTimer);
  const el = $("result");
  const isIn = scan && scan.direction === "in";
  el.style.background = bad ? "#7f1d1d" : isIn ? "#15803d" : "#b91c1c";
  $("resultDir").textContent = bad ? "?" : isIn ? "IN" : "OUT";
  $("resultName").textContent = bad ? name : worker.name;
  $("resultTime").textContent = scan ? Boord.fmtTime(scan.timestamp) : "";
  const photo = $("resultPhoto");
  photo.classList.toggle("hidden", !(worker && worker.photo));
  if (worker && worker.photo) photo.src = worker.photo;
  const flip = $("resultFlip");
  flip.classList.toggle("hidden", !scan);
  if (scan) {
    flip.textContent = `Wrong? Make it ${isIn ? "OUT" : "IN"}`;
    flip.onclick = async () => {
      scan.direction = isIn ? "out" : "in";
      scan.synced = 0;  // re-sent; the server takes the new direction for this uuid
      await IDB.put(scan);
      await rebuildInside();
      showResult({ scan, worker });
      renderScanPanel();
      syncNow();
    };
  }
  el.classList.remove("hidden");
  resultTimer = setTimeout(hideResult, RESULT_SHOW_MS);
}

function hideResult() { $("result").classList.add("hidden"); }

async function renderScanPanel() {
  const all = await IDB.all();
  $("pendingCount").textContent = all.filter((s) => !s.synced).length;
  const recent = all.sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 8);
  $("recentList").innerHTML = recent.map((s) => {
    const w = workers.get(s.worker_id);
    const status = s.error ? `<span class="text-red-600">${esc(s.error)}</span>`
      : s.synced ? `<i class="fa-solid fa-check text-green-600"></i>` : `<i class="fa-solid fa-clock text-amber-500"></i>`;
    return `<li class="py-1 flex justify-between gap-2">
      <span><b class="${s.direction === "in" ? "text-green-700" : "text-red-700"}">${s.direction.toUpperCase()}</b>
      ${esc(w ? w.name : s.worker_id)}</span>
      <span class="text-slate-500">${Boord.fmtTime(s.timestamp)} ${status}</span></li>`;
  }).join("") || `<li class="py-1 text-slate-500">Nothing scanned yet.</li>`;
}

// --------------------------------------------------------------------------
// Today
// --------------------------------------------------------------------------
function hoursSince(ms) {
  const mins = Math.floor((Date.now() - ms) / 60000);
  return `${Math.floor(mins / 60)}h${String(mins % 60).padStart(2, "0")}`;
}

function renderToday() {
  const rows = [...inside].sort((a, b) => a[1] - b[1]);
  $("presenceList").innerHTML = rows.map(([id, t]) => {
    const w = workers.get(id);
    return `<li class="py-2 flex justify-between"><span>${esc(w ? w.name : id)}
      <span class="text-slate-400">#${esc(id)}</span></span>
      <span class="text-slate-600">in ${Boord.fmtTime(new Date(t))} · ${hoursSince(t)}</span></li>`;
  }).join("") || `<li class="py-2 text-slate-500">Nobody is scanned in.</li>`;
}

// --------------------------------------------------------------------------
// Fix: exceptions and hand corrections
// --------------------------------------------------------------------------
async function renderFix() {
  let list = [];
  try { list = await Boord.api("/api/exceptions"); } catch (e) {
    $("exceptionList").innerHTML = `<li class="py-2 text-slate-500">Needs a connection to the server.</li>`;
    return;
  }
  setFixBadge(list.length);
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

async function renderDayScans() {
  const day = $("scanDay").value;
  let rows = [];
  try { rows = await Boord.api(`/api/scans?day=${day}`); } catch (e) { return; }
  $("dayScanList").innerHTML = rows.map((s) => `<li class="py-2 flex justify-between items-center gap-2">
      <span><b class="${s.direction === "in" ? "text-green-700" : "text-red-700"}">${s.direction.toUpperCase()}</b>
        ${Boord.fmtTime(s.ts)} ${esc(s.name)}
        <span class="text-slate-400">${esc(s.device_label)}${s.source === "admin" ? " · by hand" : ""}</span></span>
      <span class="flex gap-1">
        <button class="border rounded px-2" data-edit="${esc(s.uuid)}" data-ts="${esc(s.ts)}" data-dir="${s.direction}"
          data-name="${esc(s.name)}"><i class="fa-solid fa-pen"></i></button>
        <button class="border rounded px-2 text-red-700" data-del="${esc(s.uuid)}"><i class="fa-solid fa-trash"></i></button>
      </span></li>`).join("") || `<li class="py-2 text-slate-500">No scans that day.</li>`;
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
  sel.innerHTML = [...workers.values()].map((w) =>
    `<option value="${esc(w.id)}">${esc(w.id)} - ${esc(w.name)}</option>`).join("");
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
        onSubmit: (f) => Boord.api("/api/scans", { method: "POST", body: { worker_id: btn.dataset.add, ...f } }),
      });
    } else if (btn.dataset.edit) {
      openScanForm({
        title: `Change scan - ${btn.dataset.name}`, workerId: null,
        ts: Boord.parseServerDate(btn.dataset.ts), direction: btn.dataset.dir,
        onSubmit: (f) => Boord.api(`/api/scans/${btn.dataset.edit}`, { method: "PATCH", body: f }),
      });
    } else if (btn.dataset.del) {
      const reason = prompt("Delete this scan. Why? (kept on record)");
      if (!reason || !reason.trim()) return;
      await Boord.api(`/api/scans/${btn.dataset.del}/delete`, {
        method: "POST", body: { reason, device_label: deviceLabel() } });
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

const money = (n) => `R ${Number(n).toFixed(2)}`;

async function showReport() {
  const q = `start=${$("repStart").value}&end=${$("repEnd").value}`;
  const warn = $("repWarning");
  try {
    const r = await Boord.api(`/api/reports/hours?${q}`);
    $("repBody").innerHTML = r.workers.map((w) => `<tr class="border-t">
        <td>${esc(w.worker_id)}</td><td>${esc(w.name)}</td><td class="text-right">${w.days}</td>
        <td class="text-right">${w.hours.toFixed(2)}</td><td class="text-right">${w.overtime.toFixed(2)}</td>
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

async function exportReport() {
  const start = $("repStart").value, end = $("repEnd").value;
  try {
    const blob = await Boord.api(`/api/reports/hours?start=${start}&end=${end}&format=xlsx`, { timeoutMs: 60000 });
    Boord.downloadBlob(blob, `labour-hours-${start}-to-${end}.xlsx`);
  } catch (e) {
    Boord.toast(Boord.errorDetail(e));
  }
}

// --------------------------------------------------------------------------
// Settings
// --------------------------------------------------------------------------
async function renderSettings() {
  $("deviceLabelInput").value = deviceLabel();
  try {
    const rates = await Boord.api("/api/settings/rates");
    $("rateList").innerHTML = rates.map((r) => `<li class="py-1">From <b>${esc(r.effective_date)}</b>:
      ${money(r.hourly_rate)}/h, overtime ×${r.ot_multiplier} after ${r.daily_ot_after_h}h/day or
      ${r.weekly_ot_after_h}h/week</li>`).join("") ||
      `<li class="py-1 text-red-700">No rate set - the pay report will refuse to calculate until one is added.</li>`;
  } catch (e) { /* offline */ }
}

async function saveRate() {
  try {
    await Boord.api("/api/settings/rates", { method: "POST", body: {
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

// --------------------------------------------------------------------------
// Tabs and start-up
// --------------------------------------------------------------------------
function showTab(name) {
  currentTab = name;
  document.querySelectorAll("[data-tab]").forEach((s) => s.classList.toggle("hidden", s.dataset.tab !== name));
  document.querySelectorAll("[data-nav]").forEach((b) =>
    b.classList.toggle("text-blue-800", b.dataset.nav === name));
  // The camera only runs on the Scan tab - it is the battery's biggest cost.
  if (name === "scan") startCamera(); else stopCamera();
  if (name === "today") renderToday();
  if (name === "fix") renderFix();
  if (name === "report") showReport();
  if (name === "settings") renderSettings();
}

Boord.boot(async () => {
  $("appVersion").textContent = `v${Boord.VERSION}`;
  $("deviceLabel").textContent = deviceLabel();
  Boord.offlineBanner("No connection to the server - scans are saved on this phone and will sync");
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("service-worker.js").catch(() => {});

  document.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.nav)));
  $("cameraBtn").addEventListener("click", startCamera);
  $("resultClose").addEventListener("click", hideResult);
  $("exceptionList").addEventListener("click", onFixClick);
  $("dayScanList").addEventListener("click", onFixClick);
  $("scanDay").value = Boord.localDateStr();
  $("scanDay").addEventListener("change", renderDayScans);
  $("addScanBtn").addEventListener("click", () => openScanForm({
    title: "Add a scan by hand", ts: new Date(),
    onSubmit: (f) => Boord.api("/api/scans", { method: "POST", body: { worker_id: $("scanFormWorker").value, ...f } }),
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
  $("saveDeviceLabel").addEventListener("click", () => {
    localStorage.setItem("labour_device_label", $("deviceLabelInput").value.trim() || "Phone");
    $("deviceLabel").textContent = deviceLabel();
    Boord.toast("Saved");
  });
  $("rateDate").value = Boord.localDateStr();
  $("saveRate").addEventListener("click", saveRate);
  setWeek(0);

  serverPresence = cachedJSON("labour_presence", []);
  await loadWorkers();
  await rebuildInside();
  await renderScanPanel();
  showTab("scan");
  await syncNow();
  setInterval(syncNow, SYNC_EVERY_MS);
  setInterval(() => { if (currentTab === "today") renderToday(); }, 30000);
  setInterval(loadWorkers, 15 * 60 * 1000);
  IDB.prune().catch(() => {});
  Boord.api("/api/exceptions").then((l) => setFixBadge(l.length)).catch(() => {});
});
