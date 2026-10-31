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
    // `sent` is the scans as they were SENT, not just their uuids. A row is
    // marked synced only if it still says what the server was told: the
    // operator can tap "Wrong? Make it OUT" while the sync request is in
    // flight (the result screen is up for exactly that long, and on weak
    // signal a request takes seconds), and that flip puts the row back to
    // synced = 0 with the other direction. Marking by uuid alone buried the
    // flip - the server kept the IN, the phone showed OUT until the next
    // refresh, and the pay report paired the day the wrong way round. A
    // flipped row is left pending and goes out on the next pass. One
    // readwrite transaction, so a flip lands either before (direction
    // differs, left alone) or after (its own put wins) - never in between.
    async markSynced(sent, error = "") {
      await run("readwrite", (store) => sent.forEach((was) => {
        const req = store.get(was.uuid);
        req.onsuccess = () => {
          const row = req.result;
          if (row && row.direction === was.direction) store.put({ ...row, synced: 1, error });
        };
      }));
    },
    async prune() {
      const cutoff = new Date(Date.now() - PRUNE_AFTER_DAYS * 864e5).toISOString();
      const stale = (await this.all()).filter((s) => s.synced && s.timestamp < cutoff);
      await run("readwrite", (s) => stale.forEach((r) => s.delete(r.uuid)));
    },
  };
})();
