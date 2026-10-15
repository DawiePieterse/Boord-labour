// Write-ahead log for door scans. Every scan lands here first with
// synced = 0, so a scan is never lost to a dropped connection; app.js sends
// the unsynced ones every 10 seconds. Same idea as Boord's field/idb.js.
//
// Every request settles - an IndexedDB request with no onerror would leave
// its promise pending forever and freeze whatever awaited it.
const IDB = (() => {
  const DB_NAME = "boord_labour_db";
  const STORE = "scans";
  // The server has held a synced scan since it synced; keeping a fortnight
  // on the phone is only for the recent list and troubleshooting.
  const PRUNE_AFTER_DAYS = 14;
  let dbPromise = null;

  function open() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "uuid" });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => { dbPromise = null; reject(req.error); };
    });
    return dbPromise;
  }

  async function run(mode, fn) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const result = fn(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(result && "result" in result ? result.result : undefined);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  }

  return {
    put: (scan) => run("readwrite", (s) => s.put(scan)),
    all: () => run("readonly", (s) => s.getAll()),
    async pending() {
      return (await this.all()).filter((s) => !s.synced).sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    },
    async markSynced(uuids, error = "") {
      const want = new Set(uuids);
      const rows = (await this.all()).filter((s) => want.has(s.uuid));
      await run("readwrite", (s) => rows.forEach((r) => s.put({ ...r, synced: 1, error })));
    },
    async prune() {
      const cutoff = new Date(Date.now() - PRUNE_AFTER_DAYS * 864e5).toISOString();
      const stale = (await this.all()).filter((s) => s.synced && s.timestamp < cutoff);
      await run("readwrite", (s) => stale.forEach((r) => s.delete(r.uuid)));
    },
  };
})();
