import json
import re
import os

from fastapi import HTTPException
from google import genai
from google.genai import types
from openai import AsyncOpenAI
import requests

from src.services.ai_integration.api_key_cycle import ApiKeyCycle
from src.config import settings

# Pre-compiled regex for stripping markdown JSON fences
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)


class BookAiProcessor:
    """Unified AI processor that handles both taxonomy categorization and SEO
    optimization in a single Gemini request."""

    _SYSTEM_PROMPT = """\
You are an expert AI assistant with two roles:

═══════════════════════════════════════════════════════
ROLE 1 — TAXONOMY CATEGORIZER
═══════════════════════════════════════════════════════
You are an expert taxonomist and librarian specializing in Tamil literature and global publications. Analyze the provided book metadata (title, subtitle, description, existing tags) and re-categorize the book into a strict, faceted taxonomy.

RULES:
1. FICTION VS. NON-FICTION: Determine if the book is a factual account (Non-Fiction) or a creative/imagined story (Fiction).
2. TARGET AUDIENCE: Assign an audience tier. Default to "General". Only assign "Children" or "Early Learning" if the description or title explicitly implies it.
3. LITERARY FORM: Identify how the book is written (e.g., Novel, Short Story, Poetry, Report, Essay, Biography).
4. MUTUALLY EXCLUSIVE TAGGING:
   - If the book is Fiction, assign up to 3 tags under "Genre" (e.g., Thriller, Fantasy). You MUST leave "Topic" empty.
   - If the book is Non-Fiction, assign up to 3 tags under "Topic" (e.g., State Terrorism, History, Politics). You MUST leave "Genre" empty.
5. PRESERVE ORIGINAL INTENT: Use the provided `category` and `subject` as hints, but override them if the `description` strongly contradicts them.
6. CONFIDENCE SCORING: Assign a confidence score (0.0 to 1.0) based on how much information is available to make a definitive categorization.

═══════════════════════════════════════════════════════
ROLE 2 — SEO SPECIALIST
═══════════════════════════════════════════════════════
You are an Expert SEO Specialist for a massive Tamil e-commerce book catalog. Generate highly optimized SEO fields to rank the product page on Google and attract high click-through rates.

RULES:
1. TITLE URL SLUG: Lowercase English/Transliterated Tamil only. Separate words with hyphens. No native Tamil characters. Format: [book-title].
2. FOCUS KEYWORD: Identify the primary search intent (1-3 words). Ideally the Tamil title or a highly searched topic (e.g., "நபித்தோழியர் வரலாறு").
3. SECONDARY KEYWORDS (LSI): Array of 3-5 related keywords, including a mix of Tamil and "Tanglish" (English transliteration).
4. META TITLE: Maximum 60 characters. Catchy, include book title, author exact language only(if space permits).
5. META DESCRIPTION: Maximum 100 characters. Compelling, click-driving summary with the focus keyword. Do not copy the book description; summarize its unique selling point.
6. IMAGE ALT TEXT: Format: "[Author] எழுதிய [Book Title] - Book Cover".

═══════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════
You must strictly output the response in the exact JSON schema below. Do not include any markdown formatting or conversational text outside of the JSON block.

{
  "taxonomy": {
    "fiction_or_nonfiction": "string",
    "target_audience": "string",
    "literary_form": "string",
    "genre": ["string"],
    "topic": ["string"],
    "confidence": 0.0
  },
  "seo_metadata": {
    "title_slug": "string",
    "focus_keyword": "string",
    "secondary_keywords": ["string"],
    "meta_title": "string",
    "meta_description": "string",
    "image_alt_text": "string"
  }
}"""

    _SEARCH_TOOL = types.Tool(google_search=types.GoogleSearch())

    _CONFIG = types.GenerateContentConfig(
        system_instruction=_SYSTEM_PROMPT,
        tools=[_SEARCH_TOOL],
        temperature=0.1,
    )

    def __init__(self, api_key_cycle: ApiKeyCycle):
        self.api_key_cycle = api_key_cycle
        # Cache genai.Client instances per API key to avoid re-creation overhead
        self._clients: dict[str, genai.Client] = {}
        # Async OpenAI client pointing directly to DeepInfra's OpenAI-compatible endpoint
        self._async_deepinfra_client = AsyncOpenAI(
            api_key=settings.DEEPINFRA_API_KEY,
            base_url="https://api.deepinfra.com/v1/openai",
        )

    def _get_client(self, api_key: str) -> genai.Client:
        """Return a cached client for the given API key."""
        client = self._clients.get(api_key)
        if client is None:
            client = genai.Client(api_key=api_key)
            self._clients[api_key] = client
        return client

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract JSON from raw model output, stripping markdown fences if present."""
        match = _JSON_FENCE_RE.search(text)
        return json.loads(match.group(1) if match else text)

    def _prepare_user_input(self, user_input) -> str:
        if isinstance(user_input, dict):
            return json.dumps(user_input, ensure_ascii=False)
        if isinstance(user_input, (list, tuple)):
            return json.dumps(list(user_input), ensure_ascii=False)
        return str(user_input)

    def process_book(self, user_input) -> dict | None:
        """Process book metadata through Gemini to get both taxonomy and SEO
        metadata in a single API call.

        Returns a dict with "taxonomy" and "seo_metadata" keys, or None on failure.
        """
        payload = self._prepare_user_input(user_input)

        last_error = None
        for _ in range(len(self.api_key_cycle._api_keys)):
            try:
                my_api_key = self.api_key_cycle.get_next_api_key()
                client = self._get_client(my_api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash-lite", contents=payload, config=self._CONFIG
                )
                return self._extract_json(response.text)
            except json.JSONDecodeError as exc:
                print("Error: The model did not return valid JSON.")
                print(f"Raw output: {getattr(response, 'text', '')}")
                last_error = exc
                continue
            except Exception as exc:
                last_error = exc
                print(f"An API error occurred with key {my_api_key}: {exc}")
                continue

        if last_error is not None:
            print(f"All API keys failed. Last error: {last_error}")
        return None

    async def warmup_deepinfra(self, model: str = "google/gemma-3-27b-it") -> bool:
        """
        Send a quick throwaway API ping to DeepInfra to force the serverless container
        to spin up and load weights into VRAM before processing real data.
        """
        print(f"🔥 Sending GPU warmup ping to DeepInfra model ({model})...")
        try:
            await self._async_deepinfra_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": "ping"}
                ],
                max_tokens=10,
                temperature=0.1,
            )
            print("⚡ DeepInfra GPU warmed up successfully!")
            return True
        except Exception as exc:
            print(f"⚠️ Warmup ping failed (non-fatal, proceeding anyway): {exc}")
            return False

    async def process_book_deepinfra(self, user_input) -> dict:
        """Async API request using DeepInfra AsyncOpenAI client with google/gemma-3-27b-it model."""
        payload = self._prepare_user_input(user_input)

        try:
            response = await self._async_deepinfra_client.chat.completions.create(
                model="google/gemma-3-27b-it",
                messages=[
                    {
                        "role": "system",
                        "content": self._SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": payload,
                    },
                ],
                max_tokens=300,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if not content:
                raise HTTPException(
                    status_code=500,
                    detail={"error": "empty_response_from_deepinfra"},
                )

            return self._extract_json(content)

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=str(exc),
            ) from exc
