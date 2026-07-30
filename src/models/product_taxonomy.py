from enum import Enum
from typing import Optional, TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel, Column, Enum as SqlEnum

if TYPE_CHECKING:
    from src.models.product_term_link import Term


class TaxonomySlug(str, Enum):
    AUTHOR = "author"
    TRANSLATOR = "translator"
    PUBLISHER = "publisher"
    LANGUAGE = "language"
    BOOK_FORMAT = "book_format"
    PUBLISHED_ON = "published_on"
    CATEGORY = "category"
    SUBJECT = "subject"
    TARGET_AUDIENCE = "target_audience"
    LITERARY_FORM = "literary_form"
    GENRE = "genre"
    TOPIC = "topic"


class Taxonomy(SQLModel, table=True):
    """
    One row per taxonomy type (author, genre, topic...). Stored as DB rows
    rather than hardcoded so a new taxonomy can be added later without a
    migration touching every table — seed these once, TaxonomySlug just
    gives you type-safe lookup by name.
    """

    __tablename__ = "taxonomy"

    id: int | None = Field(default=None, primary_key=True)
    name: TaxonomySlug = Field(
        sa_column=Column(SqlEnum(TaxonomySlug), unique=True, nullable=False, index=True)
    )
    label: Optional[str] = Field(default=None)  # display name, e.g. "Author"

    terms: list["Term"] = Relationship(back_populates="taxonomy")
