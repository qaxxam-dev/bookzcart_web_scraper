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



    # Automatically recycle the underlying TCP connection after this many
    # requests.  The target site appears to silently kill keep-alive sockets
    # around the 150-request mark; rotating before that prevents the stall.
    CONNECTION_RECYCLE_LIMIT = 100

    def __init__(self):
        self._client: httpx.Client | None = None
        self._request_count: int = 0
        self._create_client()

    def _create_client(self) -> None:
        """Create a fresh httpx.Client, closing any existing one first."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = httpx.Client(
            headers=self.HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )
        self._request_count = 0

    def reset_connection(self) -> None:
        """Manually recycle the HTTP connection pool."""
        print("🔄 Recycling HTTP connection pool...")
        self._create_client()

    def _maybe_recycle(self) -> None:
        """Recycle the client if the request count has reached the limit."""
        if self._request_count >= self.CONNECTION_RECYCLE_LIMIT:
            print(
                f"🔄 Auto-recycling HTTP connection after "
                f"{self._request_count} requests"
            )
            self._create_client()



    def extract_html_content(self, url: str):
        """Fetch a single URL — no retries.  Raises on any failure so the
        caller can decide whether to abort the job."""
        self._maybe_recycle()

        try:
            self._request_count += 1
            response = self._client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"HTTP {e.response.status_code} fetching {url}: {e}",
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Request error fetching {url}: {e}",
            )
