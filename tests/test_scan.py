import requests
import time
import uuid
import pytest

BASE = "http://localhost:1234"
RELOAD_TIME = 2

requests.post(f"{BASE}/session/start")

@pytest.fixture
def session_id():
    """A unique session id per test, so tests don't collide in Redis."""
    return f"test-{uuid.uuid4()}"

@pytest.fixture
def live_token():
    """Start a session and return the currently-live token."""
    requests.post(f"{BASE}/session/start")
    data = requests.get(f"{BASE}/current").json()
    assert data.get("active"), f"No active session: {data}"
    return data["token"]

def scan(token, student, session):
    return requests.post(f"{BASE}/scan", json={
        "token": token,
        "student": student,
        "session": session
    }).json()

def test_valid_scan_accpeted(live_token, session_id):
    """A valid scan should be accepted."""
    result = scan(live_token, "student1", session_id)
    assert result["valid"], f"Scan failed: {result}"

def test_duplicate_scan_rejected(live_token, session_id):
    """A duplicate scan should be rejected."""
    result1 = scan(live_token, "student2", session_id)
    assert result1["valid"], f"Scan failed: {result1}"

    result2 = scan(live_token, "student2", session_id)
    assert not result2["valid"], f"Duplicate scan accepted: {result2}"

def test_fake_token_rejected(session_id):
    """A scan with a fake token should be rejected."""
    result = scan("fake-token", "", session_id)
    assert not result["valid"], f"Fake token accepted: {result}"

def test_stale_token_rejected(live_token, session_id):
    """A scan with a stale token should be rejected."""
    time.sleep(RELOAD_TIME + 1)  # wait for token to expire
    result = scan(live_token, "student4", session_id)
    assert not result["valid"], f"Stale token accepted: {result}"

