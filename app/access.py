"""Object-level authorization for instructor-owned courses and sessions."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Course, Session, User


async def owned_course(db, course_id: str, instructor: User) -> Course:
    try:
        course_uuid = uuid.UUID(course_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Course not found")
    course = await db.get(Course, course_uuid)
    if course is None or course.user_id != instructor.user_id:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


async def owned_session(db, session_id: str, instructor: User, lock: bool = False) -> Session:
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found")
    if lock:
        result = (await db.execute(select(Session).where(Session.session_id == session_uuid).with_for_update())).scalar_one_or_none()
    else:
        result = await db.get(Session, session_uuid)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    course = await db.get(Course, result.course_id)
    if course is None or course.user_id != instructor.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return result
