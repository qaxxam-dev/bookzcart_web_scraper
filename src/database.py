from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlmodel import SQLModel

from src.config import settings

async_engine = create_async_engine(settings.DATABASE_URL, echo=True, future=True)

# 2. Bind the factory explicitly to SQLModel's AsyncSession class
AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,  # This assigns the correct wrapper attributes like .exec()
    expire_on_commit=False,
)


async def create_db_and_tables() -> None:
    from sqlalchemy import text
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS raw_data_id INTEGER REFERENCES raw_book_data(id);"))



async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
