"""Test bootstrap: isolated SQLite database and signed API requests."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TEMP_DIR = Path(tempfile.mkdtemp(prefix="bids-tests-"))
# Isolated SQLite by default; set BIDS_TEST_DATABASE_URL to run the same suite
# against PostgreSQL (e.g. postgresql://postgres:postgres@127.0.0.1:5432/bids_test).
os.environ["DATABASE_URL"] = os.environ.get("BIDS_TEST_DATABASE_URL") or (
    f"sqlite:///{(TEMP_DIR / 'test.db').as_posix()}"
)
os.environ["BIDS_INTERNAL_SECRET"] = "pytest-internal-secret"
os.environ["GEMINI_API_KEY"] = ""


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def owner() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture
def auth():
    """Return a function that produces freshly signed headers for an owner."""
    from security import sign_message

    def headers(who: str) -> dict[str, str]:
        timestamp = str(int(time.time()))
        return {
            "X-BIDS-User": who,
            "X-BIDS-Timestamp": timestamp,
            "X-BIDS-Signature": sign_message(who, timestamp),
        }

    return headers


def csv_bytes(frame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")
