import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="cc-test-")
os.environ["CC_DATA_DIR"] = _tmp
os.environ["CC_WORKER_ENABLED"] = "false"
os.environ["CC_INBOX_DIR"] = os.path.join(_tmp, "inbox")

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine, init_db
from app.main import app

SAMPLE_REPORT = """CLINICAL PROFILE: Known case of carcinoma of tongue. Post operative status.
DATE: 02-11-2026

18 F-FDG WHOLE BODY PET-CT STUDY

NECK: Thickening of left lateral border of tongue now measures 18 x 18 mm (SUV Max 10.8), previously 34 x 26 mm.
Right level III lymph node measures 6 x 4 mm.

IMPRESSION: Partial response compared with previous MRI.
"""


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS cc_chunk_fts")
    init_db()
    from app.services import jobs

    jobs._seen.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
