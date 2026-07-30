from datetime import datetime
from typing import Optional
from sqlmodel import Column, Field, JSON, SQLModel


class RawBookData(SQLModel, table=True):
    __tablename__ = "raw_book_data"

    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(index=True, unique=True, nullable=False)
    title: Optional[str] = Field(default=None, nullable=True)
    raw_data: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    is_ai_processed: Optional[bool] = Field(default=False, index=True, nullable=True)
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.utcnow(), nullable=True
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.utcnow(), nullable=True
    )
