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

MIGRATION_VERSION = 1
MIGRATION_LOCK = 7145502026

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

async def migrate_db():
    # One transaction and advisory lock keep concurrent deploys from racing.
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        ))
        current = await conn.scalar(text("SELECT max(version) FROM schema_migrations"))
        if current == MIGRATION_VERSION:
            return
        if current is not None and current > MIGRATION_VERSION:
            raise RuntimeError("Database schema is newer than this application")
        await conn.run_sync(SQLModel.metadata.create_all)
        # create_all does not add columns to tables in an existing Postgres volume.
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
        await conn.execute(text("INSERT INTO schema_migrations (version) VALUES (:version)"), {"version": MIGRATION_VERSION})

async def check_schema():
    async with engine.connect() as conn:
        version = await conn.scalar(text("SELECT max(version) FROM schema_migrations"))
        if version != MIGRATION_VERSION:
            raise RuntimeError(f"Expected database migration {MIGRATION_VERSION}, got {version}")

async def get_session():
    async with async_session() as session:
        yield session
