import time
from fastapi import HTTPException
import httpx


class PageScraperService:

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self):
        # Persistent client reuses TCP connections across calls (HTTP keep-alive)
        self._client = httpx.Client(
            headers=self.HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )

    def extract_html_content(self, url: str, max_retries: int = 3):
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self._client.get(url)
                response.raise_for_status()
                return response.text
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt < max_retries:
                    print(f"Fetch attempt {attempt}/{max_retries} failed for {url}: {e}. Retrying after backoff...")
                    time.sleep(1.5 * attempt)

        raise HTTPException(
            status_code=500, detail=f"Error fetching URL after {max_retries} attempts: {last_error}"
        )
