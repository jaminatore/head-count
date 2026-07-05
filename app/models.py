import uuid 
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import UniqueConstraint, BigInteger, Column, DateTime

def utcnow():
    return datetime.now(timezone.utc)

class User(SQLModel, table=True):
    __tablename__ = "users"

    user_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    username: str
    password_hash: str 
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))

    # relationship fields: navigation only, they are NOT columns
    courses: list["Course"] = Relationship(back_populates="owner")
    enrollments: list["Enrollment"] = Relationship(back_populates="user")
    attendances: list["Attendance"] = Relationship(back_populates="user")

class Course(SQLModel, table=True):
    __tablename__ = "courses"

    course_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.user_id", index=True)
    course_name: str
    code: str
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True))) 

    # relationship fields
    owner: User = Relationship(back_populates="courses")
    sessions: list["Session"] = Relationship(back_populates="course")
    enrollments: list["Enrollment"] = Relationship(back_populates="course")


class Enrollment(SQLModel, table=True):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("course_id", "user_id", name="uq_enrollment_course_user"),
    )

    enrollment_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True) 
    course_id: uuid.UUID = Field(foreign_key="courses.course_id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.user_id", index=True)
    enrolled_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))

    # relationship fields
    course: Course = Relationship(back_populates="enrollments")
    user: User = Relationship(back_populates="enrollments")


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    session_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    course_id: uuid.UUID = Field(foreign_key="courses.course_id", index=True)
    status: str = "active" # options: active | ended
    started_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))
    ends_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    
    # relationship fields
    course: Course = Relationship(back_populates="sessions")
    attendances: list["Attendance"] = Relationship(back_populates="session")

class Attendance(SQLModel, table=True):
    __tablename__ = "attendances"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_attendance_session_user"),
    )

    attendance_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(foreign_key="sessions.session_id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.user_id", index=True)
    username: str # user's name at marked time
    marked_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))

    # relationship fields
    session: Session = Relationship(back_populates="attendances")
    user: User = Relationship(back_populates="attendances")


class AuditLog(SQLModel, table=True):
    __tablename__ = "auditLogs"

    audit_id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    session_id: uuid.UUID | None = Field(default=None, foreign_key="sessions.session_id")
    user_id: uuid.UUID | None = Field(default=None, foreign_key="users.user_id")  # nullable
    event_type: str # accepted | stale | duplicate | session-closed | not-enrolled
    reason: str | None = None  # optional free-text detail
    instance_id: str | None = None   # str: "app-1" or a hostname
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))