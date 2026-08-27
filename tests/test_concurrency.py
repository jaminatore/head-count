# Test created by claude and reviewed
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests
import pytest
from sqlalchemy import select, delete

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db import DATABASE_URL
from app.models import User, Attendance, AuditLog

from app.tokens import try_acquire_session_lock

BASE_URL = "http://localhost:1234"


def start_session_and_get_token(course_id):
    r = requests.post(f"{BASE_URL}/session/start", params={"course_id": course_id})
    assert r.status_code == 200
    session_id = r.json()["session_id"]
    data = requests.get(f"{BASE_URL}/current", params={"session_id": session_id}).json()
    assert data["active"]
    return session_id, data["token"]


def scan(token, student, session_id):
    return requests.post(f"{BASE_URL}/scan", json={
        "token": token,
        "student": student,
        "session": session_id,
    }).json()


async def _create_load_students(n):
    # A dedicated, short-lived engine -- created just for this call to imitate students
    # Note: IF IT PERSISTS PAST THIS FUNCTION IT WILL MESS WITH THE TESTS!
    engine = create_async_engine(DATABASE_URL)
    try:
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            users = [
                User(username=f"loadtest_{i}", email=f"loadtest_{i}@example.com", password_hash="x")
                for i in range(n)
            ]
            session.add_all(users)
            await session.commit()
            for u in users:
                await session.refresh(u)
            return [str(u.user_id) for u in users]
    finally:
        await engine.dispose()


async def _cleanup_load_students():
    engine = create_async_engine(DATABASE_URL)
    try:
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            # attendance rows reference these users via FK — delete children first
            loadtest_user_ids = select(User.user_id).where(User.username.like("loadtest_%"))
            await session.execute(delete(AuditLog).where(AuditLog.user_id.in_(loadtest_user_ids)))
            await session.execute(delete(Attendance).where(Attendance.user_id.in_(loadtest_user_ids)))
            await session.execute(delete(User).where(User.user_id.in_(loadtest_user_ids)))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def load_students():
    ids = asyncio.run(_create_load_students(RUSH_SIZE))
    yield ids
    asyncio.run(_cleanup_load_students())


def test_concurrent_duplicate_scans_exactly_one_accepted(seed_data):
    """The core anti-spoofing: N threads racing the identical
    scan simultaneously must produce exactly one acceptance, no matter
    how the timing lands."""
    session_id, token = start_session_and_get_token(seed_data["bio_course_id"])
    student = seed_data["student_a_id"]
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