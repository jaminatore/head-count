import uuid

import pytest

from app import records
from app.models import Attendance, Enrollment, Session, User


def test_csv_escapes_spreadsheet_formulas():
    for value in ("=1+1", "+SUM(A1)", "-4", "@function", "\tcmd", "\rcmd"):
        assert records.spreadsheet_safe(value) == "'" + value
    assert records.spreadsheet_safe("normal@example.edu") == "normal@example.edu"


@pytest.mark.asyncio
async def test_attendance_count_excludes_removed_students(monkeypatch):
    course_id = uuid.uuid4()
    first = User(user_id=uuid.uuid4(), email="first@example.edu", username="First", password_hash="")
    second = User(user_id=uuid.uuid4(), email="second@example.edu", username="Second", password_hash="")
    roster = [
        (Enrollment(course_id=course_id, user_id=first.user_id, status="approved"), first),
        (Enrollment(course_id=course_id, user_id=second.user_id, status="removed"), second),
    ]
    session = Session(session_id=uuid.uuid4(), course_id=course_id)
    attendances = [
        Attendance(session_id=session.session_id, user_id=first.user_id, username="First"),
        Attendance(session_id=session.session_id, user_id=second.user_id, username="Second"),
    ]

    async def fake_roster(db, requested_course_id):
        assert requested_course_id == course_id
        return roster

    class Result:
        def scalars(self):
            return attendances

    class Db:
        async def execute(self, query):
            return Result()

    monkeypatch.setattr(records, "roster_rows", fake_roster)
    data = await records.attendance_data(Db(), session)
    assert data["roster_count"] == 1
    assert data["present_count"] == 1
    assert len(data["students"]) == 2
