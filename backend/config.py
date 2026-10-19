"""Paths and environment for the Boord Labour service.

This app runs beside Boord on the farm server as its own process, the same
way Boord Owner does. It owns one database (data/labour.db - scans, edits,
pay rates) and reads Boord's database (data/boord.db) read-only for the
worker register. Every path can be overridden by an environment variable so
the Windows installer can point the service at wherever Boord actually lives.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, ".."))

# Unlike Owner's data/, this one holds the only copy of who worked when -
# nothing here can be rebuilt from Boord - so backup.py archives it nightly.
DATA_DIR = os.environ.get("LABOUR_DATA_DIR", os.path.join(REPO_ROOT, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

LABOUR_DB_PATH = os.environ.get("LABOUR_DB_PATH", os.path.join(DATA_DIR, "labour.db"))

# Boord's live SQLite file, opened read-only. The default assumes Boord is
# checked out beside this repo (../Boord); on the farm server the installer
# sets BOORD_DB_PATH to the real absolute path (e.g. C:\Boord\data\boord.db).
BOORD_DB_PATH = os.path.abspath(os.environ.get(
    "BOORD_DB_PATH", os.path.join(REPO_ROOT, "..", "Boord", "data", "boord.db")))

# Worker photos live beside Boord's database. Served read-only so the scan
# screen can show the face that belongs to the badge.
BOORD_PHOTOS_DIR = os.path.join(os.path.dirname(BOORD_DB_PATH), "photos")

# Clear of Boord 8000, Owner 8010, Notes 8020, Kudde 8030.
#
# The installer binds this to 127.0.0.1 only, and `tailscale serve` is what
# publishes it to the tailnet. That binding decides who can reach the app at
# all; the admin PIN (admin_auth.py) then separates the door phone from the
# admin - see MANUAL.md.
LABOUR_PORT = int(os.environ.get("LABOUR_PORT", "8040"))

FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
