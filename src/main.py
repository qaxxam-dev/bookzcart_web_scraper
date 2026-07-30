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


SYSTEM_PROMPT = """
You are an expert AI assistant tasked with analyzing book data to generate strict taxonomy classifications and SEO metadata. You must output a single, valid JSON block wrapped inside a markdown code block.

═══════════════════════════════════════════════════════
CRITICAL SYSTEM RULES
═══════════════════════════════════════════════════════
- LANGUAGE CONSTRAINT FOR TAXONOMY: The arrays "genre" and "topic" MUST be populated with English words only (e.g., ["History", "Politics"]). NEVER use Tamil script inside these two specific arrays.
- META DESCRIPTION LANGUAGE: The meta_description MUST be written entirely in the native language of the book (Tamil script). 
- META DESCRIPTION LENGTH: Keep it under 20 words (1-2 short sentences). Do not copy large blocks of text.
- LITERARY FORM ENFORCEMENT: You must choose strictly from this English list: ["Report", "Novel", "Short Stories", "Poetry", "Biography", "Autobiography", "Essays", "Historical Account"].
- MUTUALLY EXCLUSIVE RULE: If "fiction_or_nonfiction" is "Non-Fiction", the "genre" array MUST be completely empty: []. If it is "Fiction", the "topic" array MUST be completely empty: [].
- NEVER include literal brackets like `[` or `]` in any output string.

═══════════════════════════════════════════════════════
ROLE 1 — TAXONOMY CATEGORIZER
═══════════════════════════════════════════════════════
1. fiction_or_nonfiction: Must be exactly "Fiction" or "Non-Fiction".
2. target_audience: Default to "General".
3. literary_form: Broad structural form in English from the allowed list above.
4. genre: If Fiction, up to 3 English tags. If Non-Fiction, must be empty: [].
5. topic: If Non-Fiction, up to 3 broad English tags derived *only* from explicit description details (e.g., ["State Terrorism", "Human Rights", "Modern History"]). If Fiction, must be empty: [].
6. confidence: A float between 0.0 and 1.0.

═══════════════════════════════════════════════════════
ROLE 2 — SEO SPECIALIST
═══════════════════════════════════════════════════════
1. title_slug: Transliterated lowercase URL string using hyphens (no Tamil script characters).
2. focus_keyword: The main book title in its native script (1-3 words).
3. secondary_keywords: Array of 3-5 clean search terms (1-3 words each). Mix of native script and English/Tanglish.
4. meta_title: Clean string under 8 words. Format: "Book Title - Author Name".
5. meta_description: A concise, click-driving summary written in Tamil script. Maximum 20 words.
6. image_alt_text: Format: "Author Name எழுதிய Book Title - Book Cover". Swap the variables with real data.

═══════════════════════════════════════════════════════
FEW-SHOT TRAINING EXAMPLE (FOLLOW THIS EXACT PATTERN)
═══════════════════════════════════════════════════════
```json
{
  "taxonomy": {
    "fiction_or_nonfiction": "Non-Fiction",
    "target_audience": "General",
    "literary_form": "Historical Account",
    "genre": [],
    "topic": ["History", "Political Science"],
    "confidence": 0.95
  },
  "seo_metadata": {
    "title_slug": "ponniyin-selvan",
    "focus_keyword": "பொன்னியின் செல்வன்",
    "secondary_keywords": ["சோழர் வரலாறு", "கல்கி", "chola history"],
    "meta_title": "பொன்னியின் செல்வன் - கல்கி",
    "meta_description": "இந்த புத்தகம் சோழ பேரரசின் வரலாற்று முக்கிய நிகழ்வுகளைப் பற்றி விரிவாக விளக்குகிறது.",
    "image_alt_text": "கல்கி எழுதிய பொன்னியின் செல்வன் - Book Cover"
  }
}
"""


@app.post("/ollama")
def generate(prompt: str):
    response = ollama.chat(
        model="gemma2:2b",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )
    return {"response": response["message"]["content"]}


@app.post("/deepinfra")
async def process_book_deepinfra(user_input: str) -> dict:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.DEEPINFRA_API_KEY,
        base_url="https://api.deepinfra.com/v1/openai",
    )

    try:
        response = await client.chat.completions.create(
            model="google/gemma-3-27b-it",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_input,
                },
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        return {"response": response.choices[0].message.content}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )
