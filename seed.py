import asyncio
import sys
import json
from pathlib import Path

from sqlalchemy import delete
from app.db import async_session, init_db
from app.models import User, Course, Enrollment

SEED_DATA_PATH = Path(__file__).parent / "seed_data.json"


async def clear_existing(session):
    """Wipe seed data so this script can be rerun cleanly during dev.
    Deletes in FK-safe order: children before parents."""
    await session.execute(delete(Enrollment))
    await session.execute(delete(Course))
    await session.execute(delete(User))
    await session.commit()


async def seed():
    await init_db()

    async with async_session() as session:
        if "--reset" in sys.argv:
            await clear_existing(session)

        professor = User(username="prof_ada", email="prof.ada@example.com", password_hash="not_a_real_hash")
        student_a = User(username="student_a", email="student.a@example.com", password_hash="not_a_real_hash")
        student_b = User(username="student_b", email="student.b@example.com", password_hash="not_a_real_hash")
        student_c = User(username="student_c", email="student.c@example.com", password_hash="not_a_real_hash")

        session.add_all([professor, student_a, student_b, student_c])
        await session.commit()
        for u in (professor, student_a, student_b, student_c):
            await session.refresh(u)

        bio = Course(user_id=professor.user_id, course_name="Intro to Biology", code="BIO101")
        cs = Course(user_id=professor.user_id, course_name="Intro to Distributed Systems", code="CS411")
        session.add_all([bio, cs])
        await session.commit()
        for c in (bio, cs):
            await session.refresh(c)

        # Enrollment doesn't gate anything yet — everyone's enrolled in both
        # courses. Rows exist so the FK is populated for whenever the gate
        # does get built.
        session.add_all([
            Enrollment(course_id=bio.course_id, user_id=student_a.user_id),
            Enrollment(course_id=cs.course_id, user_id=student_a.user_id),
            Enrollment(course_id=bio.course_id, user_id=student_b.user_id),
            Enrollment(course_id=cs.course_id, user_id=student_b.user_id),
            Enrollment(course_id=bio.course_id, user_id=student_c.user_id),
            Enrollment(course_id=cs.course_id, user_id=student_c.user_id),
        ])
        await session.commit()

        data = {
            "professor_id": str(professor.user_id),
            "student_a_id": str(student_a.user_id),
            "student_b_id": str(student_b.user_id),
            "student_c_id": str(student_c.user_id),
            "bio_course_id": str(bio.course_id),
            "cs_course_id": str(cs.course_id),
        }
        SEED_DATA_PATH.write_text(json.dumps(data, indent=2))

        print(f"Seed complete. IDs written to {SEED_DATA_PATH}\n")
        for key, value in data.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(seed())