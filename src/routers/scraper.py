from fastapi import APIRouter, Depends
from src.dependency.services import get_scraper_service
from src.services.scraper_service import ScraperService

router = APIRouter(
    prefix="/api/scrape",
    tags=["Scraper"],
)


@router.get("/")
def scraper_single_url(
    url: str,
    scraper_service: ScraperService = Depends(get_scraper_service),
):
    status_code, html_content = scraper_service.http_get_content(url)
    return scraper_service.extract_product_info(html_content)
