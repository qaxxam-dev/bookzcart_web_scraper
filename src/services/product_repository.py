from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlmodel import select

from src.models.product import Product, StockStatus
from src.models.product_pipeline_status import PipelineStage, ProductPipelineStatus
from src.models.product_taxonomy import Taxonomy, TaxonomySlug
from src.models.product_term import ProductTerm
from src.models.product_term_link import Term
from src.models.raw_book_data import RawBookData


class ProductRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_or_create_term(
        self,
        taxonomy_slug: TaxonomySlug,
        tamil_name: str | None = None,
        english_name: str | None = None,
    ) -> Term:
        """
        Find an existing Term by taxonomy + name, or create one.
        Looks up the Taxonomy row by its enum slug first.
        """
        taxonomy = await self._get_taxonomy(taxonomy_slug)

        if tamil_name:
            stmt = select(Term).where(
                Term.taxonomy_id == taxonomy.id,
                Term.tamil_name == tamil_name,
            )
        else:
            stmt = select(Term).where(
                Term.taxonomy_id == taxonomy.id,
                Term.english_name == english_name,
            )

        result = await self.session.execute(stmt)
        term = result.scalars().first()

        if not term:
            term = Term(
                taxonomy_id=taxonomy.id,
                tamil_name=tamil_name,
                english_name=english_name,
            )
            self.session.add(term)
            await self.session.flush()  # get term.id, no commit yet

        return term

    async def _get_taxonomy(self, slug: TaxonomySlug) -> Taxonomy:
        """Fetch a Taxonomy by its enum slug, creating it if missing."""
        stmt = select(Taxonomy).where(Taxonomy.name == slug)
        result = await self.session.execute(stmt)
        taxonomy = result.scalars().first()

        if not taxonomy:
            taxonomy = Taxonomy(
                name=slug,
                label=slug.value.replace("_", " ").title(),
            )
            self.session.add(taxonomy)
            await self.session.flush()

        return taxonomy

    async def save_raw_book_data(self, url: str, raw_data: dict) -> RawBookData:
        """
        Save or update raw scrape payload in raw_book_data table.
        If record exists, updates raw_data and title without overwriting is_ai_processed.
        """
        stmt = select(RawBookData).where(RawBookData.url == url)
        result = await self.session.execute(stmt)
        raw_book = result.scalars().first()

        if raw_book:
            raw_book.raw_data = raw_data
            raw_book.title = raw_data.get("title")
            raw_book.updated_at = datetime.utcnow()
            self.session.add(raw_book)
        else:
            raw_book = RawBookData(
                url=url,
                title=raw_data.get("title"),
                raw_data=raw_data,
                is_ai_processed=False,
            )
            self.session.add(raw_book)

        await self.session.commit()
        await self.session.refresh(raw_book)
        return raw_book

    async def get_unprocessed_raw_books(self, limit: int | None = None) -> list[RawBookData]:
        """Fetch all raw_book_data records where is_ai_processed is False."""
        stmt = select(RawBookData).where(RawBookData.is_ai_processed == False)
        if limit:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_raw_book_by_url(self, url: str) -> RawBookData | None:
        """Find RawBookData by URL."""
        stmt = select(RawBookData).where(RawBookData.url == url)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def mark_raw_book_processed(self, raw_book_id: int) -> None:
        """Mark a raw_book_data row as processed by AI."""
        raw_book = await self.session.get(RawBookData, raw_book_id)
        if raw_book:
            raw_book.is_ai_processed = True
            raw_book.updated_at = datetime.utcnow()
            self.session.add(raw_book)
            await self.session.commit()

    async def save_scraped_product(
        self, result: dict, raw_data_id: int | None = None
    ) -> Product:
        """
        Persists the full scrape result (raw_data + ai_categorizer + seo_optimizer)
        into Product, Term, and ProductTerm tables within a single transaction.
        Idempotent: re-saving the same book (by title_slug) updates it in place
        instead of creating a duplicate row.
        """
        raw_data = result["raw_data"][0]
        ai_data = result["ai_categorizer"][0]
        seo_data = result["seo_optimizer"][0]

        title_slug = seo_data["title_slug"]

        # --- 1. Find existing product by dedupe key, or start a new one ---
        existing = await self.session.execute(
            select(Product).where(Product.source_key == title_slug)
        )
        product = existing.scalars().first()

        product_fields = dict(
            source_key=title_slug,
            title=raw_data["title"],
            sub_title=raw_data.get("sub_title"),
            price=Decimal(str(raw_data.get("regular_price", 0))),
            status=StockStatus(raw_data["stock_info"]["status"]),
            description=raw_data.get("description"),
            img_url_high=raw_data.get("img_url_high"),
            img_url_low=raw_data.get("img_url_low"),
            final_img=raw_data.get("final_img"),
            raw_data=raw_data,
            raw_data_id=raw_data_id,
            is_fiction=ai_data.get("fiction_or_nonfiction") == "Fiction",
            ai_confidence=ai_data.get("confidence"),
            title_slug=title_slug,
            seo_meta_title=seo_data["meta_title"],
            seo_focus_keyword=seo_data.get("focus_keyword"),
            seo_secondary_keywords=seo_data.get("secondary_keywords"),
            seo_meta_description=seo_data["meta_description"],
            seo_image_alt_text=seo_data.get("image_alt_text"),
        )

        if product:
            for field, value in product_fields.items():
                setattr(product, field, value)
            # drop old term links so a re-categorized book doesn't accumulate
            # stale terms alongside the new ones
            old_links = await self.session.execute(
                select(ProductTerm).where(ProductTerm.product_id == product.id)
            )
            for link in old_links.scalars().all():
                await self.session.delete(link)
        else:
            product = Product(**product_fields)
            self.session.add(product)

        await self.session.flush()  # populate product.id, no commit yet

        # --- 2. Map response fields → taxonomy terms ---
        single_term_mappings: list[tuple[TaxonomySlug, str | None]] = [
            (TaxonomySlug.AUTHOR, raw_data.get("author")),
            (TaxonomySlug.TRANSLATOR, raw_data.get("translator")),
            (TaxonomySlug.PUBLISHER, raw_data.get("publisher")),
            (TaxonomySlug.LANGUAGE, raw_data.get("language")),
            (TaxonomySlug.BOOK_FORMAT, raw_data.get("book_format")),
            (TaxonomySlug.PUBLISHED_ON, raw_data.get("published_on")),
            (TaxonomySlug.CATEGORY, raw_data.get("category")),
            (TaxonomySlug.SUBJECT, raw_data.get("subject")),
            # Single-value AI taxonomy fields
            (TaxonomySlug.TARGET_AUDIENCE, ai_data.get("target_audience")),
            (TaxonomySlug.LITERARY_FORM, ai_data.get("literary_form")),
        ]

        for taxonomy_slug, term_name in single_term_mappings:
            if term_name:
                term = await self._get_or_create_term(
                    taxonomy_slug, tamil_name=str(term_name)
                )
                self.session.add(ProductTerm(product_id=product.id, term_id=term.id))

        # Multi-value taxonomy fields from ai_categorizer
        multi_term_mappings: list[tuple[TaxonomySlug, list[str]]] = [
            (TaxonomySlug.GENRE, ai_data.get("genre", [])),
            (TaxonomySlug.TOPIC, ai_data.get("topic", [])),
        ]

        for taxonomy_slug, names in multi_term_mappings:
            for name in names or []:
                if name:
                    term = await self._get_or_create_term(
                        taxonomy_slug, english_name=str(name)
                    )
                    self.session.add(
                        ProductTerm(product_id=product.id, term_id=term.id)
                    )

        # --- 3. Update pipeline status — this payload already carries
        # categorization + SEO output, so it's done through seo_done ---
        status_row = await self.session.execute(
            select(ProductPipelineStatus).where(
                ProductPipelineStatus.product_id == product.id
            )
        )
        pipeline_status = status_row.scalars().first()
        if pipeline_status:
            pipeline_status.stage = PipelineStage.SEO_DONE
            pipeline_status.error = None
        else:
            self.session.add(
                ProductPipelineStatus(
                    product_id=product.id,
                    stage=PipelineStage.SEO_DONE,
                    updated_at=datetime.utcnow(),
                )
            )

        await self.session.commit()
        await self.session.refresh(product)
        return product
