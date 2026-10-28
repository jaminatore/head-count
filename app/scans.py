from app.tokens import claim_scan
from app.models import User, Attendance, Session, Enrollment

from sqlmodel import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

import uuid


async def validate_scan(token, student, session_id, db):
    try:
        student_uuid = uuid.UUID(student)
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        return False, "Invalid student or session id", "invalid_identifier"

    session_result = await db.execute(select(Session).where(Session.session_id == session_uuid).with_for_update())
    session = session_result.scalar_one_or_none()
    if session is None or session.status != "active":
        return False, "Session closed", "session_closed"
    enrollment = await db.execute(select(Enrollment).where(
        Enrollment.course_id == session.course_id,
        Enrollment.user_id == student_uuid,
    ))
    if enrollment.scalar_one_or_none() is None:
        return False, "Not enrolled in this course", "not_enrolled"

    result = await run_in_threadpool(claim_scan, session_id, student, token, session.reload_time)
    if result == "closed":
        return False, "Session closed", "session_closed"
    if result == "invalid":
        return False, "Invalid or expired code", "invalid_token"
    if result == "duplicate":
        return False, "Already scanned", "duplicate"
    return await record_attendance(session_id, student, db)

async def record_attendance(session_id, student, db):
    try:
        student_uuid = uuid.UUID(student)
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        return False, "Invalid student or session id", "invalid_identifier"

    user = (await db.execute(select(User).where(User.user_id == student_uuid))).scalar_one_or_none()
    if user is None:
        return False, "Student not found", "student_not_found"
    attendance = Attendance(
        session_id=session_uuid,
        user_id=user.user_id,
        username=user.username
    )
    try:
        db.add(attendance)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return False, "Already scanned", "duplicate"
    
    return True, "Scan Successful", "accepted"
