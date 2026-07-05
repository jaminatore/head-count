# Simple test for ensuring db exists created by Claude
# REMOVE LATER

import asyncio
from sqlalchemy import text
from app.db import engine, init_db

async def main():
    await init_db()
    print("init_db() ran — tables created")

    async with engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        ))
        tables = [row[0] for row in result]

    print("tables in the database:")
    for t in tables:
        print("  -", t)

asyncio.run(main())