from fastapi import APIRouter, Depends, HTTPException
import traceback
from sqlalchemy.ext.asyncio.session import AsyncSession

from src.database import get_session
from src.dependency.services import get_scraper_service
from src.services.scraper_service import ScraperService

router = APIRouter(
    prefix="/api/scrape",
    tags=["Scraper"],
)


@router.get("/single")
async def scraper_single_url(
    single_url: str,
    session: AsyncSession = Depends(get_session),
    scraper_service: ScraperService = Depends(get_scraper_service),
):
    try:
        return await scraper_service.scrape_single_product(single_url, session)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/list")
async def scrape_list_url(
    list_url: str,
    session: AsyncSession = Depends(get_session),
    scrape_service: ScraperService = Depends(get_scraper_service),
):
    return await scrape_service.scrape_list_product(list_url, session)


@router.get("/publisher")
async def scrape_publisher(
    publisher_url: str,
    session: AsyncSession = Depends(get_session),
    scrape_service: ScraperService = Depends(get_scraper_service),
):
    return await scrape_service.scrape_publisher(publisher_url, session)


@router.post("/process_ai")
async def process_ai_unprocessed(
    concurrency: int = 25,
    session: AsyncSession = Depends(get_session),
    scrape_service: ScraperService = Depends(get_scraper_service),
):
    """Trigger Phase 2 AI warm-up and concurrent processing for all unprocessed raw books."""
    try:
        return await scrape_service.process_ai_pipeline(
            session, concurrency=concurrency
        )
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/authors")
async def scrape_list_taxonomise_authors(
    list_url: str,
    session: AsyncSession = Depends(get_session),
    scrape_service: ScraperService = Depends(get_scraper_service),
):
    return await scrape_service.scrape_list_authors_taxonomy(list_url, session)


@router.get("/publishers")
async def scrape_list_taxonomise_publishers(
    list_url: str,
    session: AsyncSession = Depends(get_session),
    scrape_service: ScraperService = Depends(get_scraper_service),
):
    return await scrape_service.scrape_list_publishers_taxonomy(list_url, session)
