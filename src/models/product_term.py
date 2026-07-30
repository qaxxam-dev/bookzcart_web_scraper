from sqlmodel import Field, SQLModel


class ProductTerm(SQLModel, table=True):
    __tablename__ = "product_term"

    product_id: int | None = Field(
        default=None, foreign_key="product.id", primary_key=True
    )
    term_id: int | None = Field(
        default=None, foreign_key="term.id", primary_key=True
    )
