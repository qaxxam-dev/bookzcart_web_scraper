from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, JSON, SQLModel


class RawBookData(SQLModel, table=True):
    __tablename__ = "raw_book_data"

    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(index=True, unique=True)
    title: Optional[str] = Field(default=None)
    raw_data: dict = Field(sa_column=Column(JSON))
    is_ai_processed: bool = Field(default=False, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), nullable=False
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), nullable=False
    )
