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