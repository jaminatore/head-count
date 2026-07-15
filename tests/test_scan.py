import requests
import time
import uuid
import pytest



BASE = "http://localhost:1234"
SEED_USER = "a119f041-e589-433e-b759-4d77c59582c1"
SEED_SESSION = "ddc5f191-97f7-44c7-958e-cbb60e57501f"

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

def wait_for_rotation(previous_token, timeout=30):
    """Poll /current until the token changes; return the old (stale) token."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = requests.get(f"{BASE}/current").json()
        current = data.get("token")
        if current is not None and current != previous_token:
            return previous_token          # the old token, now stale
        time.sleep(0.2)                    # small poll interval, don't hammer
    raise TimeoutError("Token did not rotate within timeout")

def test_valid_scan_accepted(live_token, session_id):
    """A valid scan should be accepted."""
    result = scan(live_token, SEED_USER, SEED_SESSION)
    assert result["valid"], f"Scan failed: {result}"

def test_duplicate_scan_rejected(live_token, session_id):
    """A duplicate scan should be rejected."""
    result1 = scan(live_token, SEED_USER, SEED_SESSION)
    assert result1["valid"], f"Scan failed: {result1}"

    result2 = scan(live_token, SEED_USER, SEED_SESSION)
    assert not result2["valid"], f"Duplicate scan accepted: {result2}"

def test_fake_token_rejected(session_id):
    """A scan with a fake token should be rejected."""
    result = scan("fake-token", SEED_USER, SEED_SESSION)
    assert not result["valid"], f"Fake token accepted: {result}"

def test_stale_token_rejected(live_token, session_id):
    """A scan with a stale token should be rejected."""
    stale = wait_for_rotation(live_token)
    result = scan(stale, SEED_USER, SEED_SESSION)
    assert not result["valid"], f"Stale token accepted: {result}"

