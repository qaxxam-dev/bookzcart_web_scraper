from src.dependency.scraper_services import (
    get_single_scraper_service,
    get_page_scraper_service,
    get_image_processor_service,
    get_list_scraper_service,
    get_taxonomy_scraper_service,
    get_book_ai_processor,
    get_publisher_scraper_service,
)
from src.services.scraper_service import ScraperService


def get_scraper_service() -> ScraperService:
    return ScraperService(
        image_processor=get_image_processor_service(),
        list_scraper=get_list_scraper_service(),
        page_scraper=get_page_scraper_service(),
        single_scraper=get_single_scraper_service(),
        taxonomy_scraper=get_taxonomy_scraper_service(),
        book_ai_processor=get_book_ai_processor(),
        publisher_scraper=get_publisher_scraper_service(),
    )
