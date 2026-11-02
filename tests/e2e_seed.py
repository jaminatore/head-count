"""Seed only the test instructor identity in the disposable E2E database."""

import asyncio

from sqlalchemy import select

from app.db import async_session
from app.models import User


async def main():
    async with async_session() as db:
        existing = await db.scalar(select(User).where(User.oidc_issuer == "http://oidc:9000", User.oidc_subject == "e2e-teacher"))
        if existing is None:
            db.add(User(
                email="teacher@headcount.test",
                username="Test Teacher",
                password_hash="",
                oidc_issuer="http://oidc:9000",
                oidc_subject="e2e-teacher",
                role="instructor",
            ))
            await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
