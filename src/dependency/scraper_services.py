from src.services.scraper.taxonomy_scraper_service import TaxonomyScraperService
from src.services.scraper.single_scraper_service import SingleScraperService
from src.services.scraper.page_scraper_service import PageScraperService
from src.services.scraper.list_scraper_service import ListScraperService
from src.services.image_processor.image_processor_service import ImageProcessorService
from src.services.ai_integration.book_ai_processor import BookAiProcessor
from src.services.ai_integration.api_key_cycle import ApiKeyCycle
from src.services.scraper.publisher_scraper_service import PublisherScraperService


def get_api_key_cycle() -> ApiKeyCycle:
    return ApiKeyCycle()


def get_taxonomy_scraper_service() -> TaxonomyScraperService:
    return TaxonomyScraperService()


def get_single_scraper_service() -> SingleScraperService:
    return SingleScraperService()


def get_page_scraper_service() -> PageScraperService:
    return PageScraperService()


def get_list_scraper_service() -> ListScraperService:
    return ListScraperService()


def get_publisher_scraper_service() -> PublisherScraperService:
    return PublisherScraperService()


def get_image_processor_service() -> ImageProcessorService:
    return ImageProcessorService()


def get_book_ai_processor() -> BookAiProcessor:
    return BookAiProcessor(get_api_key_cycle())
