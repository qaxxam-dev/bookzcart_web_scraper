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

    def extract_html_content(self, url: str):
        try:
            response = self._client.get(url)
            response.raise_for_status()

            return response.text

        except httpx.RequestError as e:
            raise HTTPException(status_code=400, detail=f"Error fetching URL: {e}")
