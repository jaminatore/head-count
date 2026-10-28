"""Instructor course, roster, attendance, and correction APIs."""

import csv
import io
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth
from app.access import owned_course, owned_session
from app.db import get_session
from app.models import Attendance, AuditLog, Course, Enrollment, Session, User, utcnow


router = APIRouter()


class CourseInput(BaseModel):
    course_name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=2, max_length=20)


class JoinInput(BaseModel):
    join_code: str = Field(min_length=6, max_length=20)


class EnrollmentDecision(BaseModel):
    status: str


class CorrectionInput(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def course_json(course: Course) -> dict:
    return {
        "course_id": str(course.course_id),
        "course_name": course.course_name,
        "code": course.code,
        "join_code": course.join_code,
    }


async def roster_rows(db: AsyncSession, course_id: uuid.UUID):
    result = await db.execute(
        select(Enrollment, User)
        .join(User, Enrollment.user_id == User.user_id)
        .where(Enrollment.course_id == course_id)
        .order_by(User.username)
    )
    return result.all()


async def attendance_data(db: AsyncSession, session: Session) -> dict:
    roster = await roster_rows(db, session.course_id)
    result = await db.execute(select(Attendance).where(Attendance.session_id == session.session_id))
    attendance_by_user = {item.user_id: item for item in result.scalars()}
    students = []
    for enrollment, user in roster:
        item = attendance_by_user.get(user.user_id)
        students.append({
            "user_id": str(user.user_id),
            "username": user.username,
            "email": user.email,
            "enrollment_status": enrollment.status,
            "present": item is not None and item.voided_at is None,
            "marked_at": item.marked_at.isoformat() if item is not None and item.voided_at is None else None,
            "source": item.source if item is not None and item.voided_at is None else None,
        })
    return {
        "session_id": str(session.session_id),
        "course_id": str(session.course_id),
        "status": session.status,
        "started_at": session.started_at.isoformat(),
        "ends_at": session.ends_at.isoformat() if session.ends_at else None,
        "roster_count": sum(student["enrollment_status"] == "approved" for student in students),
        "present_count": sum(student["present"] and student["enrollment_status"] == "approved" for student in students),
        "students": students,
    }


@router.post("/courses", status_code=201)
async def create_course(payload: CourseInput, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    course_name, code = payload.course_name.strip(), payload.code.strip().upper()
    if len(course_name) < 2 or len(code) < 2:
        raise HTTPException(status_code=422, detail="Course name and code are required")
    course = Course(user_id=context.user.user_id, course_name=course_name, code=code)
    db.add(course)
    try:
        await db.commit()
        await db.refresh(course)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Could not create course; try again")
    return course_json(course)


@router.get("/my-courses")
async def my_courses(db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_auth)):
    result = await db.execute(
        select(Enrollment, Course)
        .join(Course, Enrollment.course_id == Course.course_id)
        .where(Enrollment.user_id == context.user.user_id)
        .order_by(Course.code)
    )
    return [{"course_id": str(course.course_id), "course_name": course.course_name, "code": course.code, "status": enrollment.status} for enrollment, course in result]


@router.post("/join")
async def request_join(payload: JoinInput, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_auth)):
    result = await db.execute(select(Course).where(Course.join_code == payload.join_code.strip().upper()))
    course = result.scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Class code not found")
    result = await db.execute(select(Enrollment).where(Enrollment.course_id == course.course_id, Enrollment.user_id == context.user.user_id))
    enrollment = result.scalar_one_or_none()
    if enrollment is None:
        enrollment = Enrollment(course_id=course.course_id, user_id=context.user.user_id, status="pending")
        db.add(enrollment)
    elif enrollment.status == "removed":
        enrollment.status = "pending"
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Join request already exists; refresh the page")
    return {"course_name": course.course_name, "code": course.code, "status": enrollment.status}


@router.get("/courses/{course_id}/roster")
async def get_roster(course_id: str, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    course = await owned_course(db, course_id, context.user)
    rows = await roster_rows(db, course.course_id)
    return {
        "course": course_json(course),
        "students": [{"user_id": str(user.user_id), "username": user.username, "email": user.email, "status": enrollment.status} for enrollment, user in rows],
    }


@router.post("/courses/{course_id}/enrollments/{student_id}")
async def decide_enrollment(course_id: str, student_id: str, payload: EnrollmentDecision, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    if payload.status not in ("approved", "removed"):
        raise HTTPException(status_code=422, detail="Status must be approved or removed")
    course = await owned_course(db, course_id, context.user)
    try:
        user_uuid = uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    result = await db.execute(select(Enrollment).where(Enrollment.course_id == course.course_id, Enrollment.user_id == user_uuid).with_for_update())
    enrollment = result.scalar_one_or_none()
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    old_status = enrollment.status
    enrollment.status = payload.status
    db.add(AuditLog(user_id=user_uuid, actor_user_id=context.user.user_id, event_type="enrollment_change", details=json.dumps({"course_id": course_id, "before": old_status, "after": payload.status})))
    await db.commit()
    return {"status": enrollment.status}


@router.get("/courses/{course_id}/sessions")
async def list_sessions(course_id: str, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    course = await owned_course(db, course_id, context.user)
    result = await db.execute(select(Session).where(Session.course_id == course.course_id).order_by(Session.started_at.desc()).limit(100))
    return [{"session_id": str(item.session_id), "status": item.status, "started_at": item.started_at.isoformat(), "ends_at": item.ends_at.isoformat() if item.ends_at else None} for item in result.scalars()]


@router.get("/sessions/{session_id}/attendance")
async def get_attendance(session_id: str, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    session = await owned_session(db, session_id, context.user)
    return await attendance_data(db, session)


async def correction_target(db: AsyncSession, session_id: str, student_id: str, instructor: User):
    session = await owned_session(db, session_id, instructor, lock=True)
    try:
        student_uuid = uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Student not found")
    enrollment = (await db.execute(select(Enrollment).where(Enrollment.course_id == session.course_id, Enrollment.user_id == student_uuid, Enrollment.status == "approved"))).scalar_one_or_none()
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Approved student not found")
    user = await db.get(User, student_uuid)
    item = (await db.execute(select(Attendance).where(Attendance.session_id == session.session_id, Attendance.user_id == student_uuid).with_for_update())).scalar_one_or_none()
    return session, user, item


@router.post("/sessions/{session_id}/attendance/{student_id}")
async def mark_present(session_id: str, student_id: str, payload: CorrectionInput, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    if len(payload.reason.strip()) < 3:
        raise HTTPException(status_code=422, detail="A correction reason is required")
    session, user, item = await correction_target(db, session_id, student_id, context.user)
    if item is not None and item.voided_at is None:
        raise HTTPException(status_code=409, detail="Student already marked present")
    before = {"marked_at": item.marked_at.isoformat(), "source": item.source, "voided_at": item.voided_at.isoformat()} if item else None
    now = utcnow()
    if item is None:
        item = Attendance(session_id=session.session_id, user_id=user.user_id, username=user.username, marked_at=now, source="manual")
        db.add(item)
    else:
        item.marked_at = now
        item.voided_at = None
        item.source = "manual"
    db.add(AuditLog(session_id=session.session_id, user_id=user.user_id, actor_user_id=context.user.user_id, event_type="manual_add", reason=payload.reason.strip(), details=json.dumps({"before": before, "after": {"marked_at": now.isoformat(), "source": "manual", "voided_at": None}})))
    await db.commit()
    return {"status": "present"}


@router.post("/sessions/{session_id}/attendance/{student_id}/void")
async def void_attendance(session_id: str, student_id: str, payload: CorrectionInput, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    if len(payload.reason.strip()) < 3:
        raise HTTPException(status_code=422, detail="A correction reason is required")
    session, user, item = await correction_target(db, session_id, student_id, context.user)
    if item is None or item.voided_at is not None:
        raise HTTPException(status_code=409, detail="No active attendance record")
    before = {"marked_at": item.marked_at.isoformat(), "source": item.source, "voided_at": None}
    item.voided_at = utcnow()
    db.add(AuditLog(session_id=session.session_id, user_id=user.user_id, actor_user_id=context.user.user_id, event_type="manual_void", reason=payload.reason.strip(), details=json.dumps({"before": before, "after": {"voided_at": item.voided_at.isoformat()}})))
    await db.commit()
    return {"status": "voided"}


@router.get("/sessions/{session_id}/audit")
async def session_audit(session_id: str, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    session = await owned_session(db, session_id, context.user)
    result = await db.execute(select(AuditLog).where(AuditLog.session_id == session.session_id).order_by(AuditLog.created_at.desc()).limit(200))
    return [{"event_type": item.event_type, "user_id": str(item.user_id) if item.user_id else None, "actor_user_id": str(item.actor_user_id) if item.actor_user_id else None, "reason": item.reason, "details": json.loads(item.details) if item.details else None, "created_at": item.created_at.isoformat()} for item in result.scalars()]


def spreadsheet_safe(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


@router.get("/sessions/{session_id}/export")
async def export_attendance(session_id: str, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    session = await owned_session(db, session_id, context.user)
    data = await attendance_data(db, session)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("session_id", "course_id", "student_id", "name", "email", "enrollment_status", "present", "marked_at", "source"))
    for student in data["students"]:
        writer.writerow([spreadsheet_safe(value) for value in (
            session_id, data["course_id"], student["user_id"], student["username"], student["email"], student["enrollment_status"], student["present"], student["marked_at"], student["source"],
        )])
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="attendance-{session_id}.csv"', "Cache-Control": "no-store"},
    )
