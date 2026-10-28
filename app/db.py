import os 
from dotenv import load_dotenv
load_dotenv()

from sqlmodel import SQLModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
 
from app import models # Unsure if needed...

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://counter:counter@localhost:5432/counter",
)

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

async def migrate_db():
    await init_db()
    # create_all does not add columns to tables in an existing Postgres volume.
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS reload_time INTEGER NOT NULL DEFAULT 5"
        ))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS oidc_issuer TEXT"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS oidc_subject TEXT"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'student'"))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_oidc_identity ON users (oidc_issuer, oidc_subject)"
        ))
        await conn.execute(text("ALTER TABLE courses ADD COLUMN IF NOT EXISTS join_code TEXT"))
        await conn.execute(text(
            "UPDATE courses SET join_code = upper(substr(md5(random()::text || course_id::text), 1, 10)) WHERE join_code IS NULL"
        ))
        await conn.execute(text("ALTER TABLE courses ALTER COLUMN join_code SET NOT NULL"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_courses_join_code ON courses (join_code)"))
        await conn.execute(text("ALTER TABLE enrollments ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'approved'"))
        await conn.execute(text("ALTER TABLE attendances ADD COLUMN IF NOT EXISTS voided_at TIMESTAMPTZ"))
        await conn.execute(text("ALTER TABLE attendances ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'scan'"))
        await conn.execute(text("ALTER TABLE \"auditLogs\" ADD COLUMN IF NOT EXISTS actor_user_id UUID REFERENCES users(user_id)"))
        await conn.execute(text("ALTER TABLE \"auditLogs\" ADD COLUMN IF NOT EXISTS details TEXT"))

async def get_session():
    async with async_session() as session:
        yield session
