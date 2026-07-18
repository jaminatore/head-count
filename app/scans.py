from app.tokens import RELOAD_TIME, get_current_token
from app.redis_client import redis_client
from app.models import User, Attendance

from sqlmodel import select
from sqlalchemy.exc import IntegrityError

import uuid


async def validate_scan(token, student, session_id, db):
    live_token = get_current_token(session_id=session_id)
    if live_token is None or token != live_token:
        return False, "Invalid token"
    record = f"scan:{session_id}:{student}"
    # if the token rotates and expires, the student will be able to scan again and create duplicate attendance records
    claimed = redis_client.set(record, "1", nx=True, ex=RELOAD_TIME)
    if not claimed:
        return False, "Already scanned"
    return await record_attendance(session_id, student, db)

async def record_attendance(session_id, student, db):
    try:
        student_uuid = uuid.UUID(student)
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        return False, "Invalid student or session id"

    user = (await db.execute(select(User).where(User.user_id == student_uuid))).scalar_one_or_none()
    if user is None:
        return False, "Student not found"
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
        return False, "Already scanned"
    
    return True, "Scan Successful"
