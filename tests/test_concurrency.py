# Created by Claude
# Runs multiple threads to test all instances at once instead of one at a time - this is why we use ThreadPoolExecutor

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import requests
import pytest
from sqlalchemy import delete

from app.db import async_session
from app.models import User, Attendance

BASE_URL = "http://localhost:1234"
RUSH_SIZE = 30  # number of distinct students in the throughput test


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


async def _cleanup_load_students():
    async with async_session() as session:
        # attendance rows reference these users via FK — delete children first
        await session.execute(delete(Attendance).where(Attendance.username.like("loadtest_%")))
        await session.execute(delete(User).where(User.username.like("loadtest_%")))
        await session.commit()


@pytest.fixture(scope="module")
def load_students():
    ids = asyncio.run(_create_load_students(RUSH_SIZE))
    yield ids
    asyncio.run(_cleanup_load_students())


def test_concurrent_duplicate_scans_exactly_one_accepted(seed_data):
    """The core anti-spoofing guarantee: N threads racing the identical
    scan simultaneously must produce exactly one acceptance, no matter
    how the timing lands."""
    session_id, token = start_session_and_get_token(seed_data["bio_course_id"])
    student = seed_data["student_a_id"]

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: scan(token, student, session_id), range(20)))

    accepted = [r for r in results if r["valid"]]
    assert len(accepted) == 1, f"expected exactly 1 acceptance, got {len(accepted)}: {results}"


def test_concurrent_rush_all_distinct_students_accepted(seed_data, load_students):
    """Simulates a classroom rush: many different students scanning the
    same live token at once. All should succeed — this is throughput
    under load, not a dedup test. Reports scans/sec as evidence for the
    throughput artifact."""
    session_id, token = start_session_and_get_token(seed_data["bio_course_id"])

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda sid: scan(token, sid, session_id), load_students))
    elapsed = time.perf_counter() - start

    accepted = [r for r in results if r["valid"]]
    assert len(accepted) == len(load_students), f"some legitimate scans were rejected: {results}"

    scans_per_sec = len(load_students) / elapsed
    print(f"\n{len(load_students)} concurrent scans in {elapsed:.2f}s -> {scans_per_sec:.1f} scans/sec")