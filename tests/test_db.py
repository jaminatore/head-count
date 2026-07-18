# tests/test_db.py
import pytest
from sqlalchemy import text
from app.db import engine, init_db

@pytest.mark.asyncio
async def test_tables_created():
    await init_db()
    async with engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        ))
        tables = {row[0] for row in result}

    expected = {"users", "courses", "enrollments", "sessions", "attendances", "auditLogs"}
    assert expected.issubset(tables), f"missing tables: {expected - tables}"