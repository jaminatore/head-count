# Simple Test for seeding created by Claude
# REMOVE LATER

import asyncio
from sqlalchemy import select
from app.db import async_session, init_db
from app.models import User, Course, Enrollment, Session

async def seed():
    await init_db()

    async with async_session() as session:
        student = User(
            username="test_student",
            email="student@example.com",
            password_hash="not_a_real_hash",
        )
        session.add(student)
        await session.commit()
        await session.refresh(student)  # reloads the row so student.user_id is populated

        course = Course(
            user_id=student.user_id,   # the student owns this course
            course_name="Intro to Distributed Systems",
            code="CS411",
        )
        session.add(course)
        await session.commit()
        await session.refresh(course)

        sess = Session(course_id=course.course_id)
        session.add(sess)
        await session.commit()
        await session.refresh(sess)

        print(f"session_id: {sess.session_id}")
        print(f"user_id: {student.user_id}")

        enrollment = Enrollment(course_id=course.course_id, user_id=student.user_id)
        session.add(enrollment)
        await session.commit()

        users = (await session.execute(select(User))).scalars().all()
        courses = (await session.execute(select(Course))).scalars().all()
        enrollments = (await session.execute(select(Enrollment))).scalars().all()

        print(f"users: {len(users)}  courses: {len(courses)}  enrollments: {len(enrollments)}")
        print(f"  {users[0].username} owns '{courses[0].course_name}' and is enrolled in it")


asyncio.run(seed())