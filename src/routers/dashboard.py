"""
Dashboard router — serves the Jinja2 frontend and handles job launching + SSE streaming.
"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio.session import AsyncSession

from src.database import get_session
from src.dependency.services import get_scraper_service
from src.services.progress_manager import progress, JobStatus
from src.services.scraper_service import ScraperService

router = APIRouter(tags=["Dashboard"])

templates = Jinja2Templates(directory="src/templates")

# Global lock — only one job at a time
_job_lock = asyncio.Lock()


# ------------------------------------------------------------------ #
#  Endpoint metadata (used to auto-generate the form in the template)
# ------------------------------------------------------------------ #

ENDPOINTS = [
    {
        "id": "single",
        "name": "Single Product (Full Two-Phase)",
        "path": "/api/scrape/single",
        "description": "Scrape raw payload to DB, then trigger warm-up & AI extraction.",
        "fields": [
            {
                "name": "single_url",
                "label": "Product URL",
                "type": "url",
                "placeholder": "https://example.com/book/123",
                "required": True,
            }
        ],
    },
    {
        "id": "list",
        "name": "List Page (Full Two-Phase)",
        "path": "/api/scrape/list",
        "description": "Bulk scrape list page items into raw DB, followed by warm GPU concurrent AI processing.",
        "fields": [
            {
                "name": "list_url",
                "label": "List URL",
                "type": "url",
                "placeholder": "https://example.com/publisher?page=1",
                "required": True,
            }
        ],
    },
    {
        "id": "publisher",
        "name": "Publisher (Full Two-Phase)",
        "path": "/api/scrape/publisher",
        "description": "Full pipeline: Phase 1 bulk scrape all publisher pages to DB → Phase 2 GPU warmup & concurrent AI processing.",
        "fields": [
            {
                "name": "publisher_url",
                "label": "Publisher URL",
                "type": "url",
                "placeholder": "https://example.com/publisher/seermai",
                "required": True,
            }
        ],
    },
    {
        "id": "process_ai",
        "name": "Phase 2 Only: Concurrent AI Processing",
        "path": "/api/scrape/process_ai",
        "description": "Warm up DeepInfra GPU and process all unprocessed raw database records concurrently.",
        "fields": [],
    },
    {
        "id": "taxonomy",
        "name": "Taxonomy (List)",
        "path": "/api/scrape/taxonomy",
        "description": "Run taxonomy classification on all products from a list page.",
        "fields": [
            {
                "name": "list_url",
                "label": "List URL",
                "type": "url",
                "placeholder": "https://example.com/publisher?page=1",
                "required": True,
            }
        ],
    },
]


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Serve the main dashboard HTML."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "endpoints": ENDPOINTS,
            "status": progress.snapshot(),
        },
    )


@router.post("/dashboard/start")
async def start_job(
    request: Request,
    session: AsyncSession = Depends(get_session),
    scraper_service: ScraperService = Depends(get_scraper_service),
):
    """Launch a scraping job as a background task."""

    # Parse form data
    form = await request.form()
    endpoint = form.get("endpoint", "")
    params = {k: v for k, v in form.items() if k != "endpoint"}

    if not endpoint:
        return JSONResponse({"error": "Missing endpoint"}, status_code=400)

    if _job_lock.locked():
        return JSONResponse(
            {"error": "A job is already running. Please wait for it to finish."},
            status_code=409,
        )

    job_id = uuid.uuid4().hex[:12]

    # Bind the event loop for SSE notifications
    progress.bind_loop(asyncio.get_running_loop())
    progress._do_reset()
    progress.start_job(job_id, endpoint, params)

    async def _run_job():
        async with _job_lock:
            try:
                if endpoint == "single":
                    await scraper_service.scrape_single_product(
                        url=params.get("single_url", ""),
                        session=session,
                        progress=progress,
                    )
                elif endpoint == "list":
                    await scraper_service.scrape_list_product(
                        list_url=params.get("list_url", ""),
                        session=session,
                        progress=progress,
                    )
                elif endpoint == "publisher":
                    await scraper_service.scrape_publisher(
                        publisher_url=params.get("publisher_url", ""),
                        session=session,
                        progress=progress,
                    )
                elif endpoint == "process_ai":
                    await scraper_service.process_ai_pipeline(
                        session=session,
                        concurrency=25,
                        progress=progress,
                    )
                elif endpoint == "taxonomy":
                    await asyncio.to_thread(
                        scraper_service.scrape_list_taxonomy,
                        list_url=params.get("list_url", ""),
                    )

                progress.complete_job()

            except Exception as exc:
                progress.fail_job(str(exc))

    asyncio.create_task(_run_job())

    return JSONResponse({"job_id": job_id, "status": "started"}, status_code=202)


@router.get("/dashboard/sse")
async def sse_stream():
    """Server-Sent Events stream for live progress updates."""
    progress.bind_loop(asyncio.get_running_loop())

    return StreamingResponse(
        progress.sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/dashboard/status")
async def get_status():
    """JSON snapshot of the current job state (polling fallback)."""
    return JSONResponse(progress.snapshot())
