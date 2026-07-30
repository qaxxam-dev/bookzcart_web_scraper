from typing import Optional, TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from src.models.product_term import ProductTerm

if TYPE_CHECKING:
    from src.models.product import Product
    from src.models.product_taxonomy import Taxonomy


class Term(SQLModel, table=True):
    """
    One row per distinct term value under a taxonomy, e.g.
    (taxonomy=AUTHOR, tamil_name="விபூதி நாராயண் ராய்") or
    (taxonomy=TOPIC, english_name="State Terrorism"). Reused across products.
    """

    __tablename__ = "term"
    __table_args__ = (
        UniqueConstraint("taxonomy_id", "tamil_name", name="uq_term_taxonomy_tamil"),
        UniqueConstraint("taxonomy_id", "english_name", name="uq_term_taxonomy_english"),
    )

    id: int | None = Field(default=None, primary_key=True)
    taxonomy_id: int = Field(foreign_key="taxonomy.id", index=True)
    tamil_name: Optional[str] = Field(default=None, index=True)
    english_name: Optional[str] = Field(default=None, index=True)
    slug: Optional[str] = Field(default=None, index=True)   

    taxonomy: "Taxonomy" = Relationship(back_populates="terms")
    products: list["Product"] = Relationship(
        back_populates="terms", link_model=ProductTerm
    )
