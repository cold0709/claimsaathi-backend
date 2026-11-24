import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp}/test.db", DEMO_MODE="true", REQUIRE_AUTH="false",
    ANTHROPIC_API_KEY="", GEMINI_API_KEY="", AI_PROVIDER="auto", GEMINI_SOURCE_LABEL="gemini",
    JWT_SECRET="test-secret-test-secret-test-secret-0123456789",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import OtpRequest  # noqa: E402
from app.ratelimit import limiter  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    with SessionLocal() as db:
        db.query(OtpRequest).delete()
        db.commit()
    limiter.reset()