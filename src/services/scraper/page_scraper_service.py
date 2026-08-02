import random
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

    # Minimum gap enforced between the START of any two requests, successful
    # or not. This is what was missing before: previously only failed
    # requests paused at all, so 200+ back-to-back successes could fire as
    # fast as the network allowed. Jitter avoids a perfectly metronomic
    # pattern that's itself easy to fingerprint as a bot.
    MIN_REQUEST_INTERVAL = 1.5  # seconds
    REQUEST_JITTER = 1.0  # up to +1.0s extra, randomized

    # Automatically recycle the underlying TCP connection after this many
    # requests.  The target site appears to silently kill keep-alive sockets
    # around the 150-request mark; rotating before that prevents the stall.
    CONNECTION_RECYCLE_LIMIT = 100

    def __init__(self):
        self._client: httpx.Client | None = None
        self._last_request_at: float | None = None
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

    def _throttle(self):
        """Ensure at least MIN_REQUEST_INTERVAL (+jitter) has passed since
        the last request was issued, regardless of whether it succeeded."""
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            wait_for = self.MIN_REQUEST_INTERVAL + random.uniform(
                0, self.REQUEST_JITTER
            )
            remaining = wait_for - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def extract_html_content(self, url: str):
        """Fetch a single URL — no retries.  Raises on any failure so the
        caller can decide whether to abort the job."""
        self._maybe_recycle()
        self._throttle()

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
