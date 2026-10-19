"""What release this server is running. Public, like Boord's: the heartbeat
script asks it, and so does whoever is looking at a phone wondering why a
screen looks wrong.

It reports the tag, the checkout state and the frontend VERSION line only.
Boord's version.py also reports schema revision, backups and pending updates;
port those if this app grows an update check.
"""
import os
import re
import shutil
import subprocess

from fastapi import APIRouter

import config

router = APIRouter(prefix="/api/version", tags=["version"])

API_JS = os.path.join(config.FRONTEND_DIR, "shared", "api.js")
# Same anchored expression scripts/release.sh greps with - keep them identical.
_VERSION_RE = re.compile(r'^  VERSION: "(.*)",$', re.MULTILINE)


def _frontend_version() -> str:
    try:
        with open(API_JS, encoding="utf-8") as fh:
            m = _VERSION_RE.search(fh.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def _git(args: list) -> str:
    git = shutil.which("git")
    if not git:
        return ""
    try:
        proc = subprocess.run([git] + args, cwd=config.REPO_ROOT,
                              capture_output=True, text=True, timeout=5,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


@router.get("")
def get_version():
    """Same field names as Boord's /api/version, because Boord's
    heartbeat.ps1 reads tag/state/frontend_version from every app."""
    tag = _git(["describe", "--tags", "--exact-match"])
    if tag:
        state = "release"
    else:
        tag = _git(["describe", "--tags", "--always"])
        state = "ahead" if tag else "unknown"
    return {"app": "Boord Labour", "tag": tag or None, "state": state,
            "frontend_version": _frontend_version()}
