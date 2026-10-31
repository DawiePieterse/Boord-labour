// Boord Labour - the door scanner. Pay, rates and corrections are NOT here:
// they live at /admin/ behind the admin PIN, because this phone is in the
// hands of whoever is on the door.
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
const LONG_SHIFT_MS = 12 * 3600 * 1000;  // an OUT this long after the IN may be tomorrow's arrival (admin.js)
const SYNC_EVERY_MS = 10 * 1000;
const RESULT_SHOW_MS = 5000;
const RECENT_MS = 24 * 3600 * 1000;      // the recent list's window (scans.py RECENT_HOURS agrees)
const RECENT_SHOWN = 10;                 // rows before "Show all", so the Scan button stays near the top

let workers = new Map();     // id -> {id, name, photo}
let serverPresence = [];     // [{worker_id, in_ts}] as last fetched
let serverRecent = [];       // every phone's scans, last 24h, from /api/scans/recent as last fetched
let recentAll = false;       // "Show all" pressed on the recent list
let inside = new Map();      // worker_id -> in time (ms): server presence + local unsynced scans
const lastScanAt = new Map(); // worker_id -> ms, for the duplicate window
let scanner = null;
let decoded = false;          // this camera session already read its badge
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
  } catch (e) { /* offline - keep the cached list */ }
  workers = new Map(cachedJSON("labour_workers", []).map((w) => [w.id, w]));
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
      // The scans as sent, not the uuids: a scan flipped while this request
      // was out must stay pending (see IDB.markSynced).
      const accepted = new Set(res.accepted);
      await IDB.markSynced(pending.filter((s) => accepted.has(s.uuid)));
      // A rejection is permanent (worker no longer active in Boord), so it
      // stops retrying - but it stays on the phone, flagged, for the admin.
      for (const r of res.rejected) await IDB.markSynced(pending.filter((s) => s.uuid === r.uuid), r.reason);
      if (res.rejected.length) Boord.toast(`${res.rejected.length} scan(s) refused: ${res.rejected[0].reason}`);
    }
    serverPresence = await Boord.api("/api/presence");
    localStorage.setItem("labour_presence", JSON.stringify(serverPresence));
    serverRecent = await Boord.api("/api/scans/recent");
    localStorage.setItem("labour_recent", JSON.stringify(serverRecent));
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
// One badge per tap: Scan Worker QR opens the camera, the first badge read
// closes it again and shows IN/OUT, and the screen is back at the button.
// Cancel (or a tab change) closes it without a scan.
function showCamera(on) {
  $("qrReader").classList.toggle("hidden", !on);
  $("stopBtn").classList.toggle("hidden", !on);
  $("cameraBtn").classList.toggle("hidden", on);
}

async function startCamera() {
  // A browser only hands out the camera on https (or localhost). On the farm
  // that means the Tailscale address - same rule as Boord's Field app.
  if (!window.isSecureContext) {
    Boord.toast("Scanning needs the secure https://...ts.net:8040/ address - check Tailscale is connected");
    return;
  }
  if (scanner) return;
  decoded = false;
  showCamera(true);
  scanner = new Html5Qrcode("qrReader");
  try {
    await scanner.start({ facingMode: "environment" }, { fps: 10, qrbox: 220 }, onDecoded, () => {});
  } catch (e) {
    scanner = null;
    showCamera(false);
    Boord.toast("Camera unavailable - allow camera access, then tap Scan Worker QR");
  }
}

function stopCamera() {
  showCamera(false);
  if (!scanner) return;
  const s = scanner;
  scanner = null;
  try { Promise.resolve(s.stop()).then(() => s.clear()).catch(() => {}); } catch (_) { /* never started */ }
}

async function onDecoded(text) {
  // The camera reports a badge many times a second while it is in view;
  // only the first read of this session counts.
  if (decoded) return;
  decoded = true;
  stopCamera();

  const id = text.trim();
  const now = Date.now();
  let worker = workers.get(id);
  if (!worker) {
    // Not in this phone's copy of the list - maybe added in Boord since the
    // last 15-minute refresh. Ask the server before turning them away.
    // Offline, loadWorkers keeps the cached list and they are refused below.
    await loadWorkers();
    worker = workers.get(id);
  }
  // Scanned again straight after - someone tapped twice at the door. Saying
  // so beats silently recording an OUT ten seconds after the IN (pay.py
  // would drop it anyway, but this phone would then show them as gone).
  if (worker && now - (lastScanAt.get(id) || 0) < DUPLICATE_MS) {
    Boord.toast(`${worker.name} was scanned a moment ago - wait a minute to scan again`);
    return;
  }
  lastScanAt.set(id, now);

  if (!worker) {
    Boord._tone(220, 0.35);
    showResult({ bad: true, name: `Badge "${id}" is not an active Boord worker` });
    return;
  }
  const inAt = inside.get(id);  // their IN, when this scan is about to be an OUT
  const scan = {
    uuid: Boord.uuid(), worker_id: id, timestamp: new Date(now).toISOString(),
    direction: inside.has(id) ? "out" : "in", device_label: deviceLabel(), synced: 0,
  };
  await IDB.put(scan);
  await rebuildInside();
  Boord.beepScanned();
  showResult({ scan, worker, inAt });
  renderScanPanel();
  syncNow();
}

function showResult({ scan, worker, bad, name, inAt }) {
  clearTimeout(resultTimer);
  const el = $("result");
  const isIn = scan && scan.direction === "in";
  el.style.background = bad ? "#7f1d1d" : isIn ? "#15803d" : "#b91c1c";
  $("resultDir").textContent = bad ? "?" : isIn ? "IN" : "OUT";
  $("resultName").textContent = bad ? name : worker.name;
  $("resultTime").textContent = scan ? Boord.fmtTime(scan.timestamp) : "";
  // An OUT long after the IN is usually someone who forgot to scan out last
  // time and is arriving now. Say so while the operator can still flip it.
  const longAgo = scan && !isIn && inAt && Date.parse(scan.timestamp) - inAt > LONG_SHIFT_MS;
  $("resultHint").classList.toggle("hidden", !longAgo);
  if (longAgo) {
    const h = Math.floor((Date.parse(scan.timestamp) - inAt) / 3600000);
    $("resultHint").textContent = `Their IN was ${h}h ago (${Boord.fmtTime(new Date(inAt).toISOString())}). ` +
      "Forgot to scan out? If they are arriving now, tap Make it IN.";
  }
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
      showResult({ scan, worker, inAt });
      renderScanPanel();
      syncNow();
    };
  }
  el.classList.remove("hidden");
  // Long enough to read the warning before it goes.
  resultTimer = setTimeout(hideResult, $("resultHint").classList.contains("hidden") ? RESULT_SHOW_MS : 3 * RESULT_SHOW_MS);
}

function hideResult() { $("result").classList.add("hidden"); }

// The last 24 hours from every phone, not just this one. A second door
// phone used to say "Nothing scanned yet" while Door 1 had scanned half the
// packhouse in, which left whoever held it wondering if it was working.
// The server's list is every phone's synced scans; this phone's own unsent
// or refused ones are laid over it by uuid, so a scan shows the moment it is
// made (and offline), and a flip not yet sent shows its new direction.
// A synced scan the server no longer lists was deleted under Fix, or is
// older than the window, so it is left out.
async function renderScanPanel() {
  const local = await IDB.all();
  $("pendingCount").textContent = local.filter((s) => !s.synced).length;

  const mine = new Set(local.map((s) => s.uuid));
  const rows = new Map(serverRecent.map((r) => [r.uuid, {
    ...r, at: Boord.parseServerDate(r.ts).getTime(), mine: mine.has(r.uuid), pending: false, error: "",
  }]));
  for (const s of local) {
    if (s.synced && !s.error) continue;
    rows.set(s.uuid, {
      uuid: s.uuid, worker_id: s.worker_id, direction: s.direction, device_label: s.device_label,
      source: "scan", at: Date.parse(s.timestamp), mine: true, pending: !s.synced, error: s.error || "",
    });
  }
  const since = Date.now() - RECENT_MS;
  const recent = [...rows.values()].filter((r) => r.at >= since).sort((a, b) => b.at - a.at);

  renderDevices(recent);
  const shown = recentAll ? recent : recent.slice(0, RECENT_SHOWN);
  $("recentList").innerHTML = shown.map((r) => {
    const w = workers.get(r.worker_id);
    const status = r.error ? `<span class="text-red-600">${esc(r.error)}</span>`
      : r.pending ? `<i class="fa-solid fa-clock text-amber-500"></i>`
      : r.mine ? `<i class="fa-solid fa-check text-green-600"></i>` : "";
    return `<li class="py-1 flex justify-between gap-2">
      <span><b class="${r.direction === "in" ? "text-green-700" : "text-red-700"}">${r.direction.toUpperCase()}</b>
      ${esc(w ? w.name : r.name || r.worker_id)}</span>
      <span class="text-slate-500 whitespace-nowrap">
        <span class="text-xs px-1.5 py-0.5 rounded ${r.mine ? "bg-blue-100 text-blue-800" : "bg-slate-100"}">${esc(deviceName(r))}</span>
        ${dayTime(r.at)} ${status}</span></li>`;
  }).join("") || `<li class="py-1 text-slate-500">Nothing scanned in the last 24 hours.</li>`;

  const more = $("recentMore");
  more.classList.toggle("hidden", recent.length <= RECENT_SHOWN);
  more.textContent = recentAll ? "Show fewer" : `Show all ${recent.length}`;
}

// What a scan's phone is called on the list. An admin entry under Fix
// carries the admin phone's name, if any; a door phone never renamed is
// "Phone", which is the hint to tap the name in the header.
function deviceName(r) {
  if (r.source === "admin") return r.device_label ? `Admin (${r.device_label})` : "Admin";
  return r.device_label || "Unnamed phone";
}

// The window crosses midnight, so last night's scans say so.
function dayTime(ms) {
  const d = new Date(ms);
  const t = Boord.fmtTime(d);
  return d.toDateString() === new Date().toDateString() ? t : `yesterday ${t}`;
}

function ago(ms) {
  const mins = Math.max(0, Math.floor((Date.now() - ms) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  return `${Math.floor(mins / 60)}h${String(mins % 60).padStart(2, "0")} ago`;
}

// One line per phone: how many scans it made in the window and when it last
// scanned. A phone that went quiet an hour ago while the others kept going is
// the one to check (battery, Tailscale, or someone forgot it on a shelf).
function renderDevices(recent) {
  const devices = new Map();
  for (const r of recent) {
    const name = deviceName(r);
    const d = devices.get(name) || { name, ins: 0, outs: 0, last: 0, mine: false, pending: 0 };
    if (r.direction === "in") d.ins += 1; else d.outs += 1;
    d.last = Math.max(d.last, r.at);
    d.mine = d.mine || r.mine;
    if (r.pending) d.pending += 1;
    devices.set(name, d);
  }
  const list = [...devices.values()].sort((a, b) => b.last - a.last);
  $("deviceList").classList.toggle("hidden", !list.length);
  $("deviceList").innerHTML = list.map((d) => `<li class="py-1.5 flex justify-between gap-2">
      <span><i class="fa-solid fa-mobile-screen text-slate-400"></i> <b>${esc(d.name)}</b>
        ${d.mine ? `<span class="text-xs text-blue-700">this phone</span>` : ""}
        <span class="block text-xs text-slate-500">${d.ins} in · ${d.outs} out${d.pending ? ` · ${d.pending} waiting to sync` : ""}</span></span>
      <span class="text-right text-slate-600 whitespace-nowrap">last ${dayTime(d.last)}
        <span class="block text-xs text-slate-500">${ago(d.last)}</span></span></li>`).join("");
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

function renamePhone() {
  const name = prompt("Name for this phone, shown on its scans (e.g. Door 1)", deviceLabel());
  if (name === null) return;
  localStorage.setItem("labour_device_label", name.trim() || "Phone");
  $("deviceLabel").textContent = deviceLabel();
}

// --------------------------------------------------------------------------
// Tabs and start-up
// --------------------------------------------------------------------------
function showTab(name) {
  currentTab = name;
  document.querySelectorAll("[data-tab]").forEach((s) => s.classList.toggle("hidden", s.dataset.tab !== name));
  // .tab-active (shared/styles.css) is the brand blue, the same as the header.
  document.querySelectorAll("[data-nav]").forEach((b) =>
    b.classList.toggle("tab-active", b.dataset.nav === name));
  // Leaving the Scan tab stops the camera - it is the battery's biggest cost.
  // Coming back does not restart it; that waits for the button.
  if (name !== "scan") stopCamera();
  if (name === "today") renderToday();
}

Boord.boot(async () => {
  $("appVersion").textContent = `v${Boord.VERSION}`;
  $("deviceLabel").textContent = deviceLabel();
  Boord.offlineBanner("No connection to the server - scans are saved on this phone and will sync");
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("service-worker.js").catch(() => {});

  document.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.nav)));
  $("cameraBtn").addEventListener("click", startCamera);
  $("stopBtn").addEventListener("click", stopCamera);
  $("resultClose").addEventListener("click", hideResult);
  $("deviceLabel").addEventListener("click", renamePhone);
  $("recentMore").addEventListener("click", () => { recentAll = !recentAll; renderScanPanel(); });

  serverPresence = cachedJSON("labour_presence", []);
  serverRecent = cachedJSON("labour_recent", []);
  await loadWorkers();
  await rebuildInside();
  await renderScanPanel();
  showTab("scan");
  await syncNow();
  setInterval(syncNow, SYNC_EVERY_MS);
  setInterval(() => { if (currentTab === "today") renderToday(); }, 30000);
  setInterval(loadWorkers, 15 * 60 * 1000);
  IDB.prune().catch(() => {});
});
