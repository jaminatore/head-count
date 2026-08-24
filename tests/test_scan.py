import requests
import time
import pytest

BASE = "http://localhost:1234"


def scan(token, student, session):
    return requests.post(f"{BASE}/scan", json={
        "token": token,
        "student": student,
        "session": session,
    }).json()


def wait_for_rotation(session_id, previous_token, timeout=30):
    """Poll /current until this session's token changes; return the old
    (now stale) token."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = requests.get(f"{BASE}/current", params={"session_id": session_id}).json()
        current = data.get("token")
        if current is not None and current != previous_token:
            return previous_token
        time.sleep(0.2)
    raise TimeoutError("Token did not rotate within timeout")


@pytest.fixture
def live_session(seed_data):
    """Start a fresh session per test and return (session_id, token), so
    tests never collide with each other or with leftover state."""
    r = requests.post(f"{BASE}/session/start", params={"course_id": seed_data["bio_course_id"]})
    assert r.status_code == 200, f"Failed to start session: {r.text}"
    session_id = r.json()["session_id"]

    data = requests.get(f"{BASE}/current", params={"session_id": session_id}).json()
    assert data.get("active"), f"No active session: {data}"

    return session_id, data["token"]


def test_valid_scan_accepted(live_session, seed_data):
    session_id, token = live_session
    result = scan(token, seed_data["student_a_id"], session_id)
    assert result["valid"], f"Scan failed: {result}"


def test_duplicate_scan_rejected(live_session, seed_data):
    session_id, token = live_session
    result1 = scan(token, seed_data["student_a_id"], session_id)
    assert result1["valid"], f"Scan failed: {result1}"

    result2 = scan(token, seed_data["student_a_id"], session_id)
    assert not result2["valid"], f"Duplicate scan accepted: {result2}"


def test_fake_token_rejected(live_session, seed_data):
    session_id, _ = live_session
    result = scan("fake-token", seed_data["student_a_id"], session_id)
    assert not result["valid"], f"Fake token accepted: {result}"


def test_stale_token_rejected(live_session, seed_data):
    session_id, token = live_session
    stale = wait_for_rotation(session_id, token)
    result = scan(stale, seed_data["student_a_id"], session_id)
    assert not result["valid"], f"Stale token accepted: {result}"