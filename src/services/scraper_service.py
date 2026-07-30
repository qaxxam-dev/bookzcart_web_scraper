import aiohttp
import asyncio
from pathlib import Path
import uuid

from sqlalchemy.ext.asyncio.session import AsyncSession

from src.database import AsyncSessionLocal, seed_taxonomies
from src.models.product_taxonomy import TaxonomySlug
from src.models.raw_book_data import RawBookData
from src.services.scraper.list_scraper_service import ListScraperService
from src.services.scraper.page_scraper_service import PageScraperService
from src.services.scraper.single_scraper_service import SingleScraperService
from src.services.scraper.taxonomy_scraper_service import TaxonomyScraperService
from src.services.image_processor.image_processor_service import ImageProcessorService
from src.services.ai_integration.book_ai_processor import BookAiProcessor
from src.services.product_repository import ProductRepository
from src.services.scraper.publisher_scraper_service import PublisherScraperService
from src.services.progress_manager import ProgressManager


class ScraperService:
    def __init__(
        self,
        image_processor: ImageProcessorService,
        list_scraper: ListScraperService,
        page_scraper: PageScraperService,
        single_scraper: SingleScraperService,
        taxonomy_scraper: TaxonomyScraperService,
        book_ai_processor: BookAiProcessor,
        publisher_scraper: PublisherScraperService,
    ):
        self.image_processor = image_processor
        self.list_scraper = list_scraper
        self.page_scraper = page_scraper
        self.single_scraper = single_scraper
        self.taxonomy_scraper = taxonomy_scraper
        self.book_ai_processor = book_ai_processor
        self.publisher_scraper = publisher_scraper

    # ------------------------------------------------------------------ #
    #  PHASE 1: BULK SCRAPING & RAW DATA PERSISTENCE
    # ------------------------------------------------------------------ #

    async def scrape_single_raw(
        self,
        url: str,
        session: AsyncSession,
        img_low: str | None = None,
        progress: ProgressManager | None = None,
    ) -> RawBookData | None:
        """
        Phase 1 (Single): Scrape HTML payload and save directly into raw_book_data table.
        Skips scraping if already processed by AI to prevent redundant operations.
        """
        repo = ProductRepository(session)
        existing_raw = await repo.get_raw_book_by_url(url)
        if existing_raw:
            if existing_raw.is_ai_processed:
                print(f"Skipping {url} — already processed by AI.")
                if progress:
                    progress.complete_scraping()
                return existing_raw
            if existing_raw.raw_data is not None:
                print(f"Skipping {url} raw fetch — raw data already extracted.")
                if progress:
                    progress.complete_scraping()
                return existing_raw

        if progress:
            progress.start_product(url)

        try:
            html_content = self.page_scraper.extract_html_content(url)
            book_data = self.single_scraper.extract_product_info(html_content, img_low)
            raw_book = await repo.save_raw_book_data(url, book_data)

            if progress:
                progress.complete_scraping()

            return raw_book

        except Exception as exc:
            print(f"Failed to scrape raw data for {url}: {exc}")
            try:
                await repo.save_raw_book_data(url, None)
            except Exception as save_exc:
                print(f"Failed to save skipped record for {url}: {save_exc}")
            if progress:
                progress.fail_product(url, str(exc))
            return None

    async def reprocess_skipped_urls(
        self,
        session: AsyncSession,
        progress: ProgressManager | None = None,
    ) -> dict:
        """
        Query all skipped URLs (where raw_data is NULL), attempt to re-scrape them,
        and run Phase 2 AI processing pipeline on newly scraped books.
        """
        repo = ProductRepository(session)
        skipped_books = await repo.get_skipped_raw_books()

        if not skipped_books:
            print("No skipped URLs found in database.")
            return {"skipped_total": 0, "reprocessed_raw": 0, "ai_processed": 0, "ai_failed": 0}

        print(f"🔄 Reprocessing {len(skipped_books)} skipped URLs...")

        if progress:
            progress.set_list_page_products(len(skipped_books))

        reprocessed_count = 0
        for item in skipped_books:
            raw_book = await self.scrape_single_raw(item.url, session, progress=progress)
            if raw_book and raw_book.raw_data is not None:
                reprocessed_count += 1

        ai_summary = await self.process_ai_pipeline(
            session, concurrency=25, progress=progress
        )

        return {
            "skipped_total": len(skipped_books),
            "reprocessed_raw": reprocessed_count,
            "ai_processed": ai_summary["processed"],
            "ai_failed": ai_summary["failed"],
        }

    async def scrape_list_product_raw(
        self,
        list_url: str,
        session: AsyncSession,
        progress: ProgressManager | None = None,
    ) -> list[RawBookData]:
        """
        Phase 1 (List): Extract all product URLs on list page and save their raw payloads.
        """
        html_content = self.page_scraper.extract_html_content(list_url)
        list_products = self.list_scraper.extract_book_list_single_page(html_content)

        if progress:
            progress.set_list_page_products(len(list_products["books"]))

        raw_books: list[RawBookData] = []
        for product in list_products["books"]:
            product_url = product["url"]
            product_img = product["img_low"]
            raw_book = await self.scrape_single_raw(
                product_url, session, product_img, progress=progress
            )
            if raw_book:
                raw_books.append(raw_book)

        if progress:
            progress.complete_list_page()

        return raw_books

    async def scrape_publisher_raw(
        self,
        publisher_url: str,
        session: AsyncSession,
        progress: ProgressManager | None = None,
    ) -> dict:
        """
        Phase 1 (Publisher): Discover all publisher pages and scrape all raw product items.
        """
        html_content = self.page_scraper.extract_html_content(publisher_url)
        url_data = self.publisher_scraper.extract_publisher_list_url(html_content)

        total_list_urls = len(url_data["list_url"])
        total_raw_books = 0

        if progress:
            progress.set_publisher_pages(total_list_urls)

        for i, item in enumerate(url_data["list_url"]):
            list_url = item["url"]
            if progress:
                progress.complete_publisher_page(i)

            raw_books = await self.scrape_list_product_raw(
                list_url, session, progress=progress
            )
            total_raw_books += len(raw_books)

        return {"total_list_urls": total_list_urls, "total_raw_books": total_raw_books}

    # ------------------------------------------------------------------ #
    #  PHASE 2: WARM-UP & CONCURRENT AI PROCESSING
    # ------------------------------------------------------------------ #

    async def process_ai_pipeline(
        self,
        session: AsyncSession,
        concurrency: int = 25,
        progress: ProgressManager | None = None,
    ) -> dict:
        """
        Phase 2:
        1. Warm up DeepInfra GPU container with a lightweight throwaway ping.
        2. Query unprocessed raw_book_data records.
        3. Execute AI extraction, watermark processing, image uploading, and persistence
           concurrently using coroutines (up to `concurrency` parallel tasks).
        """
        repo = ProductRepository(session)
        unprocessed_books = await repo.get_unprocessed_raw_books()

        if not unprocessed_books:
            print("No unprocessed raw books found in database.")
            return {"processed": 0, "failed": 0}

        print(f"🚀 Phase 2 Starting: {len(unprocessed_books)} unprocessed books found.")

        # Pre-seed taxonomy rows to prevent race conditions during concurrent inserts
        await seed_taxonomies()

        # 1. Warm-Up DeepInfra serverless container
        await self.book_ai_processor.warmup_deepinfra()

        # 2. Setup concurrency control
        semaphore = asyncio.Semaphore(concurrency)
        processed_count = 0
        failed_count = 0

        async def _process_single_item(raw_book: RawBookData):
            nonlocal processed_count, failed_count
            async with semaphore:
                # Use a fresh dedicated session per coroutine for thread/task safety
                async with AsyncSessionLocal() as task_session:
                    task_repo = ProductRepository(task_session)
                    book_data = raw_book.raw_data.copy()
                    temp_name = f"untitled_{uuid.uuid4().hex}"

                    # Run AI processing and image watermark concurrently
                    ai_task = self.book_ai_processor.process_book_deepinfra(book_data)
                    img_task = asyncio.to_thread(
                        self.image_processor.process_watermark,
                        front_url=book_data.get("img_url_high"),
                        back_url=book_data.get("img_url_low"),
                        file_name=temp_name,
                    )

                    ai_result, img_result_or_exc = await asyncio.gather(
                        ai_task, img_task, return_exceptions=True
                    )

                    if isinstance(ai_result, Exception):
                        print(
                            f"AI processing failed for Raw #{raw_book.id}: {ai_result}"
                        )
                        if progress:
                            progress.fail_ai(str(ai_result))
                        ai_result = None
                    else:
                        if progress:
                            progress.complete_ai()

                    if isinstance(img_result_or_exc, Exception):
                        print(
                            f"Image processing failed for Raw #{raw_book.id}: {img_result_or_exc}"
                        )
                        if progress:
                            progress.fail_image(raw_book.url, str(img_result_or_exc))
                        img_result_or_exc = None
                    else:
                        if progress:
                            progress.complete_image()

                    if not ai_result:
                        failed_count += 1
                        if progress:
                            progress.fail_product(raw_book.url, "AI extraction failed")
                        return

                    ai_categorizer = ai_result.get("taxonomy")
                    seo_result = ai_result.get("seo_metadata")
                    title_slug = seo_result.get("title_slug") if seo_result else None

                    # Image upload
                    if title_slug and img_result_or_exc:
                        image_path = Path(img_result_or_exc)
                        try:
                            form = aiohttp.FormData()
                            form.add_field("title", title_slug)
                            form.add_field(
                                "image",
                                image_path.open("rb"),
                                filename=image_path.name,
                                content_type="image/webp",
                            )

                            async with aiohttp.ClientSession() as client:
                                async with client.post(
                                    "https://app.bookzcart.in/image.php",
                                    data=form,
                                ) as resp:
                                    resp.raise_for_status()
                                    upload_result = await resp.json()

                            book_data["final_img"] = upload_result.get("url")

                        except Exception as exc:
                            print(f"Image upload failed for Raw #{raw_book.id}: {exc}")
                        finally:
                            self.image_processor.delete_output_image(image_path)

                    scrape_result = {
                        "raw_data": [book_data],
                        "ai_categorizer": [ai_categorizer],
                        "seo_optimizer": [seo_result],
                    }

                    # Persist product and mark RawBookData as processed
                    try:
                        product = await task_repo.save_scraped_product(
                            scrape_result, raw_data_id=raw_book.id
                        )
                        await task_repo.mark_raw_book_processed(raw_book.id)
                        processed_count += 1
                        if progress:
                            progress.complete_product()
                    except Exception as exc:
                        print(f"Database save failed for Raw #{raw_book.id}: {exc}")
                        failed_count += 1
                        if progress:
                            progress.fail_product(raw_book.url, str(exc))

        # Launch all item processing coroutines concurrently
        tasks = [_process_single_item(b) for b in unprocessed_books]
        await asyncio.gather(*tasks, return_exceptions=True)

        return {"processed": processed_count, "failed": failed_count}

    # ------------------------------------------------------------------ #
    #  DECOUPLED TWO-PHASE PIPELINE ORCHESTRATOR
    # ------------------------------------------------------------------ #

    async def scrape_single_product(
        self,
        url: str,
        session: AsyncSession,
        img_low: str | None = None,
        progress: ProgressManager | None = None,
    ):
        """Phase 1 -> Phase 2 pipeline for a single product."""
        raw_book = await self.scrape_single_raw(
            url, session, img_low=img_low, progress=progress
        )
        if raw_book:
            await self.process_ai_pipeline(session, concurrency=1, progress=progress)
        return {"status": "success", "url": url}

    async def scrape_list_product(
        self,
        list_url: str,
        session: AsyncSession,
        progress: ProgressManager | None = None,
    ):
        """Phase 1 -> Phase 2 pipeline for a list page."""
        raw_books = await self.scrape_list_product_raw(
            list_url, session, progress=progress
        )
        ai_summary = await self.process_ai_pipeline(
            session, concurrency=25, progress=progress
        )
        return {
            "total_raw_scraped": len(raw_books),
            "ai_processed": ai_summary["processed"],
            "ai_failed": ai_summary["failed"],
        }

    async def scrape_publisher(
        self,
        publisher_url: str,
        session: AsyncSession,
        progress: ProgressManager | None = None,
    ):
        """Phase 1 -> Phase 2 pipeline for an entire publisher catalog."""
        pub_summary = await self.scrape_publisher_raw(
            publisher_url, session, progress=progress
        )
        ai_summary = await self.process_ai_pipeline(
            session, concurrency=25, progress=progress
        )
        return {
            "total_list_urls": pub_summary["total_list_urls"],
            "total_raw_books": pub_summary["total_raw_books"],
            "ai_processed": ai_summary["processed"],
            "ai_failed": ai_summary["failed"],
        }

    async def scrape_list_authors_taxonomy(
        self, list_url: str, session: AsyncSession
    ):
        html_content = self.page_scraper.extract_html_content(list_url)
        taxonomies = self.taxonomy_scraper.extract_taxonomise_authors_detailed(
            html_content
        )
        repo = ProductRepository(session)
        await repo.save_taxonomy_terms(
            TaxonomySlug.AUTHOR, taxonomies.get("taxonomise", [])
        )
        return taxonomies

    async def scrape_list_publishers_taxonomy(
        self, list_url: str, session: AsyncSession
    ):
        html_content = self.page_scraper.extract_html_content(list_url)
        taxonomies = self.taxonomy_scraper.extract_taxonomise_publishers_detailed(
            html_content
        )
        repo = ProductRepository(session)
        await repo.save_taxonomy_terms(
            TaxonomySlug.PUBLISHER, taxonomies.get("taxonomise", [])
        )
        return taxonomies
