import os
import tempfile

import pytest

_fd, _path = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DATABASE_PATH"] = _path
os.environ["API_TOKEN"] = "test-token"
os.environ["API_TOKEN_READONLY"] = "test-readonly-token"
os.environ["ENABLE_SCHEDULER"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db_file():
    yield
    os.remove(_path)


@pytest.fixture
def db_session():
    """A raw session for tests that exercise a service function directly,
    without going through HTTP."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    # base_url is https so the auth cookie's Secure flag round-trips in tests
    # the same way it does in production (real HTTPS, per ADR 0011).
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def readonly_headers():
    return {"Authorization": "Bearer test-readonly-token"}
