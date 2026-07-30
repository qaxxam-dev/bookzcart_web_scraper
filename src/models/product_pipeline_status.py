from enum import Enum
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, Column, Enum as SqlEnum


class PipelineStage(str, Enum):
    SCRAPED = "scraped"
    CATEGORIZED = "categorized"
    SEO_DONE = "seo_done"
    EXPORTED = "exported"
    FAILED = "failed"


class ProductPipelineStatus(SQLModel, table=True):
    __tablename__ = "product_pipeline_status"

    product_id: int = Field(foreign_key="product.id", primary_key=True)
    stage: PipelineStage = Field(
        sa_column=Column(
            SqlEnum(PipelineStage), nullable=False, default=PipelineStage.SCRAPED
        )
    )
    error: Optional[str] = Field(default=None)
    retry_count: int = Field(default=0)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(),
        nullable=False,
    )
