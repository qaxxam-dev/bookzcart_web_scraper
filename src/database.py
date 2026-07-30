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


async def seed_taxonomies() -> None:
    """Pre-seed all Taxonomy rows into DB using ON CONFLICT DO NOTHING."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from src.models.product_taxonomy import Taxonomy, TaxonomySlug

    async with AsyncSessionLocal() as session:
        for slug in TaxonomySlug:
            stmt = (
                pg_insert(Taxonomy)
                .values(
                    name=slug,
                    label=slug.value.replace("_", " ").title(),
                )
                .on_conflict_do_nothing(index_elements=["name"])
            )
            await session.execute(stmt)
        await session.commit()


async def create_db_and_tables() -> None:
    from sqlalchemy import text
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS raw_data_id INTEGER REFERENCES raw_book_data(id);"))
        await conn.execute(text("ALTER TABLE term ADD COLUMN IF NOT EXISTS slug VARCHAR;"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_term_slug ON term (slug);"))
        await conn.execute(text("ALTER TABLE raw_book_data ALTER COLUMN raw_data DROP NOT NULL;"))
        await conn.execute(text("ALTER TABLE raw_book_data ALTER COLUMN title DROP NOT NULL;"))
        await conn.execute(text("ALTER TABLE raw_book_data ALTER COLUMN is_ai_processed DROP NOT NULL;"))
        await conn.execute(text("ALTER TABLE raw_book_data ALTER COLUMN created_at DROP NOT NULL;"))
        await conn.execute(text("ALTER TABLE raw_book_data ALTER COLUMN updated_at DROP NOT NULL;"))
    await seed_taxonomies()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

