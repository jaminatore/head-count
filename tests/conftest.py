import json
from pathlib import Path

import pytest
import pytest_asyncio
import requests

from app.db import engine

BASE_URL = "http://localhost:1234"
SEED_DATA_PATH = Path(__file__).parent.parent / "seed_data.json"

@pytest.fixture
def live_session(seed_data):
    """Start a fresh session per test and return (session_id, token), so
    tests never collide with each other or with leftover state."""
    r = requests.post(f"{BASE_URL}/session/start", params={"course_id": seed_data["bio_course_id"]})
    assert r.status_code == 200, f"Failed to start session: {r.text}"
    session_id = r.json()["session_id"]

    data = requests.get(f"{BASE_URL}/current", params={"session_id": session_id}).json()
    assert data.get("active"), f"No active session: {data}"

    return session_id, data["token"]

@pytest.fixture(scope="session", autouse=True)
def ensure_stack_running():
    """Fail fast with a clear message if docker compose isn't up, instead
    of every test timing out individually with a connection error."""
    try:
        r = requests.get(f"{BASE_URL}/healthz", timeout=3)
        r.raise_for_status()
    except Exception as e:
        pytest.exit(
            f"Could not reach {BASE_URL}/healthz — is `docker compose up` running?\n({e})",
            returncode=1,
        )


@pytest_asyncio.fixture(autouse=True)
async def _dispose_shared_engine_after_test():
    """Ensure that every thread is destroyed after a test -- otherwise will mess with future tests"""
    yield
    await engine.dispose()


@pytest.fixture(scope="session")
def seed_data():
    """Ids created by seed.py. Run `python seed.py --reset` before the
    test session if this file doesn't exist yet or looks stale."""
    if not SEED_DATA_PATH.exists():
        pytest.exit(
            f"{SEED_DATA_PATH} not found — run `python seed.py --reset` before running tests.",
            returncode=1,
        )
    return json.loads(SEED_DATA_PATH.read_text())