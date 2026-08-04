import json

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import requests
from scalar_fastapi import get_scalar_api_reference
from src.config import settings
from src.routers import scraper, dashboard

from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.database import async_engine, create_db_and_tables
from src.models import SQLModel

import ollama


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Initializing database tables from separate files...")
    await create_db_and_tables()
    print("✅ Database tables initialized")
    yield
    print("🛑 Shutting down backend service...")
    await async_engine.dispose()


app = FastAPI(
    lifespan=lifespan,
    title="BookzCart Web Scraper",
    version="1.0.0",
    summary="Microservice web scraper, AI integrated SEO content creation, Auto publish",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
)


# Mount static files for the dashboard frontend
app.mount("/static", StaticFiles(directory="src/static"), name="static")

app.include_router(dashboard.router)
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