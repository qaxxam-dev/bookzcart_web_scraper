from decimal import Decimal
from enum import Enum
from typing import Optional, TYPE_CHECKING

from sqlmodel import JSON, Field, Relationship, SQLModel, Column, Enum as SqlEnum

from src.models.product_term import ProductTerm

if TYPE_CHECKING:
    from src.models.product_term_link import Term


class StockStatus(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    COMING_SOON = "coming_soon"
    PRE_ORDER = "pre_order"
    SOLE_ORDER = "sole_order"


class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    # dedupe key so re-running the scraper updates existing rows instead of
    # duplicating them — using seo_data["title_slug"] since it's already
    # guaranteed unique by your pipeline
    source_key: str = Field(index=True, unique=True)

    title: str = Field(index=True)
    sub_title: Optional[str] = Field(default=None)
    price: Decimal = Field(default=0.00, max_digits=10, decimal_places=2)
    status: StockStatus = Field(
        sa_column=Column(
            SqlEnum(StockStatus), default=StockStatus.IN_STOCK, nullable=False
        )
    )
    description: Optional[str] = Field(default=None)
    no_of_pages: Optional[int] = Field(default=None)
    img_url_high: Optional[str] = Field(default=None)
    img_url_low: Optional[str] = Field(default=None)
    final_img: Optional[str] = Field(default=None)

    # full original scrape payload, kept for audit / re-derivation
    raw_data: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    raw_data_id: Optional[int] = Field(default=None, foreign_key="raw_book_data.id")

    # --- ai_categorizer scalar fields only.
    # target_audience, literary_form, book_format, genre, topic all live as
    # Terms now (see product_term_link.Term) since your repo treats them as
    # taxonomy values, not product columns ---
    is_fiction: bool = False
    ai_confidence: Optional[float] = Field(default=None)

    # --- seo_optimizer ---
    title_slug: str = Field(index=True, unique=True)
    seo_meta_title: str
    seo_focus_keyword: Optional[str] = Field(default=None)
    seo_secondary_keywords: list[str] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    seo_meta_description: str
    seo_image_alt_text: Optional[str] = Field(default=None)

    terms: list["Term"] = Relationship(back_populates="products", link_model=ProductTerm)
