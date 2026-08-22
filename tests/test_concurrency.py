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


def test_many_concurrent_sessions_all_rotate_independently(seed_data):
    """Stress test: create a plethora of sessions at once and confirm every
    single one keeps rotating on schedule. Proves the loop doesn't starve
    some sessions while servicing others, and that isolation still holds
    once there are many active sessions in play at once, not just two."""
    N = 25 # arbitrary number of workers - change as needed
    reload_time = 2
    course_id = seed_data["bio_course_id"]

    def start_one(_):
        r = requests.post(f"{BASE_URL}/session/start", params={
            "course_id": course_id, "reload_time": reload_time,
        })
        assert r.status_code == 200
        return r.json()["session_id"]

    with ThreadPoolExecutor(max_workers=N) as pool:
        session_ids = list(pool.map(start_one, range(N)))

    assert len(set(session_ids)) == N, "expected N distinct session ids"

    def get_token(session_id):
        data = requests.get(f"{BASE_URL}/current", params={"session_id": session_id}).json()
        assert data["active"], f"session {session_id} not active: {data}"
        return data["token"]

    with ThreadPoolExecutor(max_workers=N) as pool:
        first_tokens = dict(zip(session_ids, pool.map(get_token, session_ids)))

    time.sleep(reload_time + 1)  # let at least one more rotation happen for everyone

    with ThreadPoolExecutor(max_workers=N) as pool:
        second_tokens = dict(zip(session_ids, pool.map(get_token, session_ids)))

    not_rotated = [sid for sid in session_ids if first_tokens[sid] == second_tokens[sid]]
    assert not not_rotated, f"{len(not_rotated)}/{N} sessions failed to rotate: {not_rotated}"

    # Isolation spot-check at scale: one session's current token must not
    # validate under a completely different session, even with N others
    # simultaneously active.
    a, b = session_ids[0], session_ids[1]
    result = requests.post(f"{BASE_URL}/scan", json={
        "token": second_tokens[a],
        "student": seed_data["student_a_id"],
        "session": b,
    }).json()
    assert result["valid"] is False

    with ThreadPoolExecutor(max_workers=N) as pool:
        list(pool.map(
            lambda sid: requests.post(f"{BASE_URL}/session/end", params={"session_id": sid}),
            session_ids,
        ))