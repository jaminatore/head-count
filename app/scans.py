from app.audit import safe_audit
from app.tokens import RELOAD_TIME, get_current_token
from app.redis_client import redis_client
from app.models import User, Attendance

from sqlmodel import select
from sqlalchemy.exc import IntegrityError

import uuid


async def validate_scan(token, student, session_id, db, instance_id):
    try:
        session_uuid = uuid.UUID(session_id)
        student_uuid = uuid.UUID(student)
    except (ValueError, TypeError):
        return False, "Invalid session id"
    
    live_token = get_current_token(session_id=session_id)
    if live_token is None or token != live_token:
        await safe_audit("stale", session_id=session_uuid, reason="token mismatch", instance_id=instance_id)
        return False, "Invalid token"
    
    record = f"scan:{session_id}:{student}"
    claimed = redis_client.set(record, "1", nx=True, ex=RELOAD_TIME)

    if not claimed:
        await safe_audit("duplicate", session_id=session_uuid, reason="redis dedup", instance_id=instance_id)
        return False, "Already scanned"
    return await record_attendance(session_uuid, student_uuid, db, instance_id)

async def record_attendance(session_uuid, student_uuid, db, instance_id):
    user = (await db.execute(select(User).where(User.user_id == student_uuid))).scalar_one_or_none()

    if user is None:
        await safe_audit("not-enrolled", session_id=session_uuid, reason=f'student not found: {student_uuid}', instance_id=instance_id)

        return False, "Student not found"

    user_id = user.user_id
    username = user.username

    
    attendance = Attendance(session_id=session_uuid, user_id=user_id, username=username)

    try:
        db.add(attendance)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        await safe_audit("duplicate", session_id=session_uuid, user_id = user_id, reason="db constraint", instance_id=instance_id)
        return False, "Already scanned"
    
    await safe_audit("accepted", session_id=session_uuid, user_id=user_id,instance_id=instance_id)

    return True, "Scan Successful"
