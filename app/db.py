import os 
from dotenv import load_dotenv
load_dotenv()

from sqlmodel import SQLModel
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

async def get_session():
    async with async_session() as session:
        yield session