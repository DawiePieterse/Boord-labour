"""The door phone must not reach pay, rates or corrections: every admin
endpoint wants the cookie only a correct PIN hands out."""
import admin_auth
from tests.conftest import ADMIN_PIN

ADMIN_GETS = ["/api/exceptions", "/api/scans", "/api/edits", "/api/settings/rates",
              "/api/reports/hours?start=2026-10-12&end=2026-10-18", "/api/admin/me"]


def test_door_endpoints_open_admin_endpoints_closed(client):
    assert client.get("/api/workers").status_code == 200
    assert client.get("/api/presence").status_code == 200
    assert client.post("/api/scans/sync", json={"scans": []}).status_code == 200
    for path in ADMIN_GETS:
        assert client.get(path).status_code == 401, path
    assert client.post("/api/settings/rates", json={"effective_date": "2026-01-01",
                                                    "hourly_rate": 99}).status_code == 401
    assert client.post("/api/scans", json={"worker_id": "001", "timestamp": "2026-10-12T07:00:00Z",
                                           "direction": "in", "reason": "x"}).status_code == 401


def test_login_refused_until_pin_set_on_server(client):
    assert client.post("/api/admin/login", json={"pin": "0000"}).status_code == 409


def test_wrong_pin_then_lockout(client):
    admin_auth.set_pin(ADMIN_PIN)
    for _ in range(admin_auth.MAX_FAILURES):
        assert client.post("/api/admin/login", json={"pin": "0000"}).status_code == 401
    # Locked: even the right PIN is refused for now.
    assert client.post("/api/admin/login", json={"pin": ADMIN_PIN}).status_code == 429


def test_right_pin_unlocks_and_logout_locks(admin_client):
    for path in ADMIN_GETS:
        assert admin_client.get(path).status_code in (200, 409), path  # 409 = report with no rate yet
    admin_client.post("/api/admin/logout")
    assert admin_client.get("/api/admin/me").status_code == 401


def test_changing_pin_signs_other_phones_out(admin_client):
    other_phone_cookie = admin_client.cookies.get(admin_auth.COOKIE)
    r = admin_client.post("/api/admin/pin", json={"current": ADMIN_PIN, "new": "9876"})
    assert r.status_code == 200
    assert admin_client.get("/api/admin/me").status_code == 200  # this phone got a fresh cookie
    assert not admin_auth.token_valid(other_phone_cookie)


def test_pin_change_rules(admin_client):
    # A wrong current PIN is a 400, not a 401: a 401 would make admin.js show
    # the PIN screen and sign out the phone that is mid-change.
    assert admin_client.post("/api/admin/pin", json={"current": "1111", "new": "9876"}).status_code == 400
    assert admin_client.get("/api/admin/me").status_code == 200  # still signed in
    assert admin_client.post("/api/admin/pin", json={"current": ADMIN_PIN, "new": "123"}).status_code == 422


def test_tampered_cookie_rejected(admin_client):
    fingerprint, sig = admin_client.cookies.get(admin_auth.COOKIE).split(".")
    admin_client.cookies.clear()
    for forged in (f"{fingerprint}.{'0' * len(sig)}", "garbage", ""):
        r = admin_client.get("/api/admin/me", headers={"Cookie": f"{admin_auth.COOKIE}={forged}"})
        assert r.status_code == 401, forged


def test_backup_now_list_and_download(admin_client):
    made = admin_client.post("/api/settings/backups").json()["filename"]
    assert made.startswith("labour_backup_")
    assert made in [b["filename"] for b in admin_client.get("/api/settings/backups").json()]
    r = admin_client.get(f"/api/settings/backups/{made}/download")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert admin_client.get("/api/settings/backups/last_hash.txt/download").status_code == 404


def test_backups_need_admin(client):
    assert client.get("/api/settings/backups").status_code == 401
    assert client.post("/api/settings/backups").status_code == 401
