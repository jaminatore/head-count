import time
import uuid

import pytest
import requests
from sqlmodel import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db import DATABASE_URL
from app.models import AuditLog
from app.tokens import RELOAD_TIME

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


async def _audit_rows(session_id):
    """Read all audit rows for one session, oldest first. Uses its own
    short-lived engine so it never clashes with the shared engine that
    conftest disposes between tests."""
    engine = create_async_engine(DATABASE_URL)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            result = await db.execute(
                select(AuditLog)
                .where(AuditLog.session_id == uuid.UUID(session_id))
                .order_by(AuditLog.audit_id)
            )
            return result.scalars().all()
    finally:
        await engine.dispose()


def audit_rows(session_id):
    """Sync wrapper so tests (which use requests) can read audit rows."""
    import asyncio
    return asyncio.run(_audit_rows(session_id))


def _one(rows, event_type, reason=None):
    """Return the single row matching event_type (and reason, if given),
    asserting exactly one exists."""
    matches = [
        r for r in rows
        if r.event_type == event_type and (reason is None or r.reason == reason)
    ]
    assert len(matches) == 1, (
        f"expected exactly one {event_type!r}"
        + (f" / {reason!r}" if reason else "")
        + f" row, found {len(matches)}: {[(r.event_type, r.reason) for r in rows]}"
    )
    return matches[0]


def test_audit_accepted(live_session, seed_data):
    """A valid scan writes an 'accepted' row carrying the real user_id."""
    session_id, token = live_session
    result = scan(token, seed_data["student_a_id"], session_id)
    assert result["valid"], f"scan failed: {result}"

    row = _one(audit_rows(session_id), "accepted")
    assert str(row.user_id) == seed_data["student_a_id"]
    assert row.instance_id is not None


def test_audit_stale(live_session, seed_data):
    """A scan with a bad token writes a 'stale' row with no user_id."""
    session_id, _token = live_session
    result = scan("fake-token", seed_data["student_a_id"], session_id)
    assert not result["valid"]

    row = _one(audit_rows(session_id), "stale")
    assert row.user_id is None
    assert row.reason == "token mismatch"


def test_audit_not_enrolled(live_session, seed_data):
    """A scan for a UUID that isn't a real user writes a 'not-enrolled'
    row with no user_id (the id can't go in the FK column)."""
    session_id, token = live_session
    ghost = str(uuid.uuid4())
    result = scan(token, ghost, session_id)
    assert not result["valid"]

    row = _one(audit_rows(session_id), "not-enrolled")
    assert row.user_id is None
    assert ghost in (row.reason or "")


def test_audit_redis_duplicate(live_session, seed_data):
    """Scanning the same student twice while the dedup key is live writes
    a 'duplicate' row caught by Redis, with no user_id."""
    session_id, token = live_session
    assert scan(token, seed_data["student_a_id"], session_id)["valid"]
    dup = scan(token, seed_data["student_a_id"], session_id)
    assert not dup["valid"]

    row = _one(audit_rows(session_id), "duplicate", reason="redis dedup")
    assert row.user_id is None


@pytest.mark.slow
def test_audit_db_duplicate(live_session, seed_data):
    session_id, token = live_session
    assert scan(token, seed_data["student_a_id"], session_id)["valid"]

    # The redis dedup key lives RELOAD_TIME seconds from the first scan.
    # Wait past it so the second scan misses Redis and reaches the DB,
    # where the unique constraint catches the duplicate.
    time.sleep(RELOAD_TIME + 2)

    # token has rotated by now; fetch the current live one
    live = requests.get(f"{BASE}/current", params={"session_id": session_id}).json()["token"]

    dup = scan(live, seed_data["student_a_id"], session_id)
    assert not dup["valid"], f"expected duplicate rejection, got {dup}"

    row = _one(audit_rows(session_id), "duplicate", reason="db constraint")
    assert str(row.user_id) == seed_data["student_a_id"]