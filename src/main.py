from fastapi import FastAPI
from scalar_fastapi import get_scalar_api_reference
from src.routers import scraper

app = FastAPI(
    title="BookzCart Web Scraper",
    version="1.0.0",
    summary="Microservice web scraper, AI integrated SEO content creation, Auto publish",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
)


app.include_router(scraper.router)


@app.get("/api/", tags=["Health"])
def home():
    return {
        "message": "T2S LMS is running!",
        "openapi": "/api/openapi.json",
        "docs": "/api/docs",
        # "environment": settings.ENVIRONMENT,
    }


@app.get("/api/scalar", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
    )
