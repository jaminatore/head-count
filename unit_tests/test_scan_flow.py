import uuid

import pytest

from app import scans
from app.models import Session


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDb:
    def __init__(self, session, enrolled=True):
        self.session = session
        self.enrolled = enrolled
        self.calls = 0

    async def execute(self, query):
        self.calls += 1
        return Result(self.session if self.calls == 1 else (object() if self.enrolled else None))


@pytest.mark.asyncio
async def test_scan_rejects_closed_and_unenrolled_before_redis(monkeypatch):
    student_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    session = Session(session_id=uuid.UUID(session_id), course_id=uuid.uuid4(), status="ended")
    monkeypatch.setattr(scans, "claim_scan", lambda *args: pytest.fail("Redis should not be called"))
    assert (await scans.validate_scan("code", student_id, session_id, FakeDb(session)))[2] == "session_closed"

    session.status = "active"
    assert (await scans.validate_scan("code", student_id, session_id, FakeDb(session, enrolled=False)))[2] == "not_enrolled"


@pytest.mark.asyncio
async def test_scan_accepts_only_atomic_live_claim(monkeypatch):
    student_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    session = Session(session_id=uuid.UUID(session_id), course_id=uuid.uuid4(), reload_time=5)

    async def record(*args):
        return True, "Scan Successful", "accepted"

    monkeypatch.setattr(scans, "record_attendance", record)
    for claim, expected in (("closed", "session_closed"), ("invalid", "invalid_token"), ("duplicate", "duplicate"), ("accepted", "accepted")):
        monkeypatch.setattr(scans, "claim_scan", lambda *args: claim)
        result = await scans.validate_scan("code", student_id, session_id, FakeDb(session))
        assert result[2] == expected
