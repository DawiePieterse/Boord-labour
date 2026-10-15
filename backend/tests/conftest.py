"""Test fixtures.

Environment is set BEFORE config/db/main are imported, because they read it
at import time. TZ is pinned to SAST so "the local day of a shift" means the
same thing on every machine that runs this suite.
"""
import os
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="boordlabour-tests-")
os.environ["LABOUR_DATA_DIR"] = _TMP
os.environ["LABOUR_DB_PATH"] = os.path.join(_TMP, "labour.db")
os.environ["BOORD_DB_PATH"] = os.path.join(_TMP, "boord.db")
os.environ["TZ"] = "Africa/Johannesburg"
time.tzset()

import pytest  # noqa: E402
from sqlmodel import Session, create_engine, delete  # noqa: E402

import config  # noqa: E402
from models_boord import Worker  # noqa: E402
from models_labour import PayRate, Scan, ScanEdit  # noqa: E402


def _build_fake_boord_db():
    engine = create_engine(f"sqlite:///{config.BOORD_DB_PATH}")
    Worker.__table__.create(engine)
    with Session(engine) as s:
        s.add(Worker(id="001", first_name="Thandi", last_name="M", name="Thandi M"))
        s.add(Worker(id="002", first_name="Piet", last_name="K", name="Piet K", photo_filename="002.jpg"))
        s.add(Worker(id="003", name="Gone", active=False))
        s.commit()
    engine.dispose()


_build_fake_boord_db()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import admin_auth
    import main
    from db import labour_engine

    # https, because the admin cookie is Secure and httpx will not send a
    # Secure cookie back over plain http.
    with TestClient(main.app, base_url="https://testserver") as c:
        with Session(labour_engine) as s:
            for model in (Scan, ScanEdit, PayRate):
                s.exec(delete(model))
            s.commit()
        if os.path.exists(admin_auth.PIN_FILE):
            os.remove(admin_auth.PIN_FILE)
        admin_auth._failures, admin_auth._locked_until = 0, 0.0
        yield c


ADMIN_PIN = "4321"


@pytest.fixture
def admin_client(client):
    import admin_auth
    admin_auth.set_pin(ADMIN_PIN)
    assert client.post("/api/admin/login", json={"pin": ADMIN_PIN}).status_code == 200
    return client
