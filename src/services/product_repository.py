import asyncio
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlmodel import select

from src.models.product import Product, StockStatus
from src.models.product_pipeline_status import PipelineStage, ProductPipelineStatus
from src.models.product_taxonomy import Taxonomy, TaxonomySlug
from src.models.product_term import ProductTerm
from src.models.product_term_link import Term
from src.models.raw_book_data import RawBookData


class ProductRepository:
    _taxonomy_cache: ClassVar[dict[TaxonomySlug, int]] = {}

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_taxonomy(self, slug: TaxonomySlug) -> Taxonomy:
        """Fetch a Taxonomy by its enum slug, creating it if missing."""
        if slug in ProductRepository._taxonomy_cache:
            tax_id = ProductRepository._taxonomy_cache[slug]
            taxonomy = await self.session.get(Taxonomy, tax_id)
            if taxonomy:
                return taxonomy

        stmt = select(Taxonomy).where(Taxonomy.name == slug)
        result = await self.session.execute(stmt)
        taxonomy = result.scalars().first()

        if not taxonomy:
            insert_stmt = (
                pg_insert(Taxonomy)
                .values(
                    name=slug,
                    label=slug.value.replace("_", " ").title(),
                )
                .on_conflict_do_nothing(index_elements=["name"])
                .returning(Taxonomy.id)
            )
            try:
                async with self.session.begin_nested():
                    insert_res = await self.session.execute(insert_stmt)
                    inserted_id = insert_res.scalar_one_or_none()
            except Exception:
                inserted_id = None

            if inserted_id is not None:
                taxonomy = await self.session.get(Taxonomy, inserted_id)
            else:
                result = await self.session.execute(stmt)
                taxonomy = result.scalars().first()

        if taxonomy and taxonomy.id:
            ProductRepository._taxonomy_cache[slug] = taxonomy.id
            return taxonomy

        raise RuntimeError(f"Could not get or create taxonomy for slug {slug}")

    async def _get_or_create_term(
        self,
        taxonomy_slug: TaxonomySlug,
        tamil_name: str | None = None,
        english_name: str | None = None,
        slug: str | None = None,
    ) -> Term:
        """
        Find an existing Term by taxonomy + name/slug, or create one.
        Handles concurrent insertions using PostgreSQL ON CONFLICT DO NOTHING.
        """
        tamil_name = tamil_name.strip() if tamil_name else None
        english_name = english_name.strip() if english_name else None
        slug = slug.strip() if slug else None

        if not tamil_name and not english_name and not slug:
            raise ValueError("Either tamil_name, english_name, or slug must be provided")

        taxonomy = await self._get_taxonomy(taxonomy_slug)

        if tamil_name:
            stmt = select(Term).where(
                Term.taxonomy_id == taxonomy.id,
                Term.tamil_name == tamil_name,
            )
            conflict_target = ["taxonomy_id", "tamil_name"]
        elif english_name:
            stmt = select(Term).where(
                Term.taxonomy_id == taxonomy.id,
                Term.english_name == english_name,
            )
            conflict_target = ["taxonomy_id", "english_name"]
        else:
            stmt = select(Term).where(
                Term.taxonomy_id == taxonomy.id,
                Term.slug == slug,
            )
            conflict_target = ["taxonomy_id", "slug"]

        # Step 1: Check existing term
        result = await self.session.execute(stmt)
        term = result.scalars().first()
        if term:
            updated = False
            if slug and term.slug != slug:
                term.slug = slug
                updated = True
            if english_name and not term.english_name:
                term.english_name = english_name
                updated = True
            if tamil_name and not term.tamil_name:
                term.tamil_name = tamil_name
                updated = True
            if updated:
                self.session.add(term)
            return term

        # Step 2: Atomic insertion handling concurrent conflicts
        insert_stmt = (
            pg_insert(Term)
            .values(
                taxonomy_id=taxonomy.id,
                tamil_name=tamil_name,
                english_name=english_name,
                slug=slug,
            )
            .on_conflict_do_nothing(index_elements=conflict_target)
            .returning(Term.id)
        )

        try:
            async with self.session.begin_nested():
                insert_res = await self.session.execute(insert_stmt)
                inserted_id = insert_res.scalar_one_or_none()
        except Exception:
            inserted_id = None

        if inserted_id is not None:
            term = await self.session.get(Term, inserted_id)
            if term:
                return term

        # Step 3: Re-query after potential conflict resolution
        result = await self.session.execute(stmt)
        term = result.scalars().first()
        if term:
            updated = False
            if slug and term.slug != slug:
                term.slug = slug
                updated = True
            if english_name and not term.english_name:
                term.english_name = english_name
                updated = True
            if tamil_name and not term.tamil_name:
                term.tamil_name = tamil_name
                updated = True
            if updated:
                self.session.add(term)
            return term

        # Step 4: Retry loop for edge case timing delays
        for _ in range(3):
            await asyncio.sleep(0.05)
            result = await self.session.execute(stmt)
            term = result.scalars().first()
            if term:
                return term

        raise RuntimeError(
            f"Could not get or create term for taxonomy {taxonomy_slug}: "
            f"tamil='{tamil_name}', english='{english_name}', slug='{slug}'"
        )

    async def save_taxonomy_terms(
        self,
        taxonomy_slug: TaxonomySlug,
        terms_data: list[dict],
    ) -> None:
        """
        Check and create taxonomy terms (authors, publishers, etc.) in the database in batch.
        Each dict in terms_data contains 'english_name', 'tamil_name', and optional 'slug'.
        """
        if not terms_data:
            return

        taxonomy = await self._get_taxonomy(taxonomy_slug)

        records_with_tamil = []
        records_english_only = []

        seen_tamil = set()
        seen_english = set()

        for item in terms_data:
            tamil = item.get("tamil_name").strip() if item.get("tamil_name") else None
            english = item.get("english_name").strip() if item.get("english_name") else None
            slug = item.get("slug").strip() if item.get("slug") else None

            if not tamil and not english and not slug:
                continue

            row = {
                "taxonomy_id": taxonomy.id,
                "tamil_name": tamil,
                "english_name": english,
                "slug": slug,
            }

            if tamil:
                if (taxonomy.id, tamil) not in seen_tamil:
                    seen_tamil.add((taxonomy.id, tamil))
                    records_with_tamil.append(row)
            elif english:
                if (taxonomy.id, english) not in seen_english:
                    seen_english.add((taxonomy.id, english))
                    records_english_only.append(row)
            elif slug:
                records_english_only.append(row)

        chunk_size = 500
        for i in range(0, len(records_with_tamil), chunk_size):
            chunk = records_with_tamil[i : i + chunk_size]
            stmt = (
                pg_insert(Term)
                .values(chunk)
                .on_conflict_do_nothing(index_elements=["taxonomy_id", "tamil_name"])
            )
            await self.session.execute(stmt)

        for i in range(0, len(records_english_only), chunk_size):
            chunk = records_english_only[i : i + chunk_size]
            stmt = (
                pg_insert(Term)
                .values(chunk)
                .on_conflict_do_nothing(index_elements=["taxonomy_id", "english_name"])
            )
            await self.session.execute(stmt)

        await self.session.commit()

    async def save_raw_book_data(self, url: str, raw_data: dict | None) -> RawBookData:
        """
        Save or update raw scrape payload in raw_book_data table.
        Supports saving None raw_data for skipped URLs.
        If record exists, updates raw_data and title without overwriting is_ai_processed.
        """
        stmt = select(RawBookData).where(RawBookData.url == url)
        result = await self.session.execute(stmt)
        raw_book = result.scalars().first()

        title = raw_data.get("title") if raw_data else None

        if raw_book:
            raw_book.raw_data = raw_data
            if title:
                raw_book.title = title
            raw_book.updated_at = datetime.utcnow()
            self.session.add(raw_book)
        else:
            raw_book = RawBookData(
                url=url,
                title=title,
                raw_data=raw_data,
                is_ai_processed=False,
            )
            self.session.add(raw_book)

        await self.session.commit()
        await self.session.refresh(raw_book)
        return raw_book

    async def get_unprocessed_raw_books(self, limit: int | None = None) -> list[RawBookData]:
        """Fetch all raw_book_data records where is_ai_processed is False and raw_data is not None."""
        stmt = select(RawBookData).where(
            RawBookData.is_ai_processed == False, RawBookData.raw_data != None
        )
        if limit:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_skipped_raw_books(self, limit: int | None = None) -> list[RawBookData]:
        """Fetch all raw_book_data records where raw_data is NULL."""
        stmt = select(RawBookData).where(RawBookData.raw_data == None)
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

        added_term_ids: set[int] = set()

        for taxonomy_slug, term_name in single_term_mappings:
            if term_name and str(term_name).strip():
                term = await self._get_or_create_term(
                    taxonomy_slug, tamil_name=str(term_name).strip()
                )
                if term.id and term.id not in added_term_ids:
                    self.session.add(ProductTerm(product_id=product.id, term_id=term.id))
                    added_term_ids.add(term.id)

        # Multi-value taxonomy fields from ai_categorizer
        multi_term_mappings: list[tuple[TaxonomySlug, list[str]]] = [
            (TaxonomySlug.GENRE, ai_data.get("genre", [])),
            (TaxonomySlug.TOPIC, ai_data.get("topic", [])),
        ]

        for taxonomy_slug, names in multi_term_mappings:
            for name in names or []:
                if name and str(name).strip():
                    term = await self._get_or_create_term(
                        taxonomy_slug, english_name=str(name).strip()
                    )
                    if term.id and term.id not in added_term_ids:
                        self.session.add(
                            ProductTerm(product_id=product.id, term_id=term.id)
                        )
                        added_term_ids.add(term.id)

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
