"""Nightly backup of labour.db - a trimmed copy of Boord's backup.py.

Unlike Boord Owner's database, nothing in labour.db can be rebuilt from
Boord: it is the only record of who worked which hours. So at 02:00 every
night, when it changed since the last archive, it is snapshotted with
SQLite's backup API (a plain file copy mid-write can be unrecoverable - see
Boord's _snapshot_db), zipped into data/backups/, and the newest MAX_BACKUPS
are kept.

Off-site copy reuses Boord's setting rather than adding a second one: the
folder named in Boord's data/backup_copy_to.txt. Labour archives are named
labour_backup_*.zip so they sit beside Boord's backup_*.zip without either
app's pruner touching the other's.
"""
import hashlib
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Optional

import config

BACKUPS_DIR = os.path.join(config.DATA_DIR, "backups")
MAX_BACKUPS = 30
PREFIX = "labour_backup_"
LAST_HASH = os.path.join(BACKUPS_DIR, "last_hash.txt")
COPY_DEST_FILE = os.path.join(os.path.dirname(config.BOORD_DB_PATH), "backup_copy_to.txt")


def _snapshot(destination: str) -> None:
    source = sqlite3.connect(config.LABOUR_DB_PATH)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _read_first_line(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    return None


def _copy_offsite(archive: str) -> None:
    """Never raises: an unplugged USB stick must not kill the scheduler or
    make a good local backup look like a failure. Same rules as Boord: the
    folder must already exist (a missing one is usually an unplugged drive),
    and the copy lands under a .part name first so a half-copied file is
    never mistaken for an archive."""
    dest = _read_first_line(COPY_DEST_FILE)
    if not dest:
        return
    if not os.path.isdir(dest):
        print(f"[backup] off-site folder {dest} not found - check the drive is plugged in", flush=True)
        return
    name = os.path.basename(archive)
    partial = os.path.join(dest, name + ".part")
    try:
        shutil.copy2(archive, partial)
        os.replace(partial, os.path.join(dest, name))
    except OSError as e:
        print(f"[backup] off-site copy to {dest} FAILED: {e}", flush=True)
        try:
            os.remove(partial)
        except OSError:
            pass


def create_backup(skip_if_unchanged: bool = False) -> Optional[str]:
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    fd, snap = tempfile.mkstemp(suffix=".db", dir=BACKUPS_DIR)
    os.close(fd)
    os.remove(snap)  # sqlite3 wants to create the file itself
    try:
        _snapshot(snap)
        with open(snap, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        if skip_if_unchanged and _read_first_line(LAST_HASH) == digest:
            return None
        archive = os.path.join(BACKUPS_DIR, f"{PREFIX}{datetime.now():%Y%m%d_%H%M%S}.zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap, arcname="labour.db")
    finally:
        if os.path.exists(snap):
            os.remove(snap)
    with open(LAST_HASH, "w", encoding="utf-8") as fh:
        fh.write(digest)
    archives = sorted(f for f in os.listdir(BACKUPS_DIR) if f.startswith(PREFIX) and f.endswith(".zip"))
    for stale in archives[:-MAX_BACKUPS]:
        os.remove(os.path.join(BACKUPS_DIR, stale))
    _copy_offsite(archive)
    return os.path.basename(archive)


def list_backups() -> list:
    """Newest first, for the admin Settings tab."""
    names = sorted((f for f in os.listdir(BACKUPS_DIR) if f.startswith(PREFIX) and f.endswith(".zip")), reverse=True) \
        if os.path.isdir(BACKUPS_DIR) else []
    result = []
    for name in names:
        stat = os.stat(os.path.join(BACKUPS_DIR, name))
        # Tagged UTC so the browser shows it in farm time, as Boord does.
        result.append({"filename": name, "size_bytes": stat.st_size,
                       "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()})
    return result


def _seconds_until_next_2am() -> float:
    now = datetime.now()
    target = now.replace(hour=2, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _scheduler_loop() -> None:
    while True:
        time.sleep(_seconds_until_next_2am())
        try:
            create_backup(skip_if_unchanged=True)
        except Exception as e:  # noqa: BLE001 - one bad night must not kill the thread
            print(f"[backup] nightly backup FAILED: {e!r}", flush=True)


def start_backup_scheduler() -> None:
    threading.Thread(target=_scheduler_loop, daemon=True).start()
