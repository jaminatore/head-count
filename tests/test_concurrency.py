# Test created by claude and reviewed
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

from app.tokens import try_acquire_session_lock

BASE_URL = "http://localhost:1234"


def test_session_lock_exactly_one_winner():
    """Many 'instances' (fake ids) race to acquire the same session's
    rotation lock at once. Exactly one should win."""
    session_id = f"test-lock-{uuid.uuid4()}"
    fake_instance_ids = [f"fake-instance-{i}" for i in range(20)]

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(
            lambda iid: try_acquire_session_lock(session_id, iid, 5),
            fake_instance_ids,
        ))

    winners = sum(1 for r in results if r)
    assert winners == 1, f"expected exactly 1 lock winner, got {winners}: {results}"


def test_fast_session_rotates_more_than_slow_session(seed_data):
    """Two sessions with different professor-configured reload_time values,
    running concurrently, should rotate at independent rates"""
    fast = requests.post(f"{BASE_URL}/session/start", params={
        "course_id": seed_data["bio_course_id"], "reload_time": 2,
    }).json()
    slow = requests.post(f"{BASE_URL}/session/start", params={
        "course_id": seed_data["cs_course_id"], "reload_time": 10,
    }).json()

    fast_id, slow_id = fast["session_id"], slow["session_id"]
    fast_seen, slow_seen = set(), set()

    deadline = time.time() + 9  # long enough for fast(2s) to rotate several
                                  # times and slow(10s) to rotate at most once
    while time.time() < deadline:
        fast_seen.add(requests.get(f"{BASE_URL}/current", params={"session_id": fast_id}).json()["token"])
        slow_seen.add(requests.get(f"{BASE_URL}/current", params={"session_id": slow_id}).json()["token"])
        time.sleep(0.5)

    requests.post(f"{BASE_URL}/session/end", params={"session_id": fast_id})
    requests.post(f"{BASE_URL}/session/end", params={"session_id": slow_id})

    assert len(fast_seen) >= 3, f"fast session should have rotated several times, saw: {fast_seen}"
    assert len(slow_seen) <= 2, f"slow session rotated too often, saw: {slow_seen}"
    assert len(fast_seen) > len(slow_seen), "fast session should rotate strictly more than slow session"