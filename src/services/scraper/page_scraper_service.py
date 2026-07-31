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

    # Cooldown specifically for HTTP 500s. Logs showed 1.5s/3s backoff
    # between retries was NOT enough to clear a 500 — but stopping the job
    # entirely cleared it within seconds. That points to a short-window
    # rate limiter that the retries themselves were still feeding (each
    # retry is another request against a still-tripped window). So a 500
    # gets a longer, quiet pause before the next attempt, separate from the
    # normal pacing above.
    RATE_LIMIT_COOLDOWN = 20.0  # seconds, base
    RATE_LIMIT_COOLDOWN_JITTER = 10.0

    def __init__(self):
        # Persistent client reuses TCP connections across calls (HTTP keep-alive)
        self._client = httpx.Client(
            headers=self.HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )
        self._last_request_at: float | None = None

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

    def extract_html_content(self, url: str, max_retries: int = 3):
        last_error = None
        for attempt in range(1, max_retries + 1):
            self._throttle()
            try:
                response = self._client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPStatusError as e:
                last_error = e
                is_rate_limited = e.response.status_code == 500
                if attempt < max_retries:
                    if is_rate_limited:
                        cooldown = self.RATE_LIMIT_COOLDOWN + random.uniform(
                            0, self.RATE_LIMIT_COOLDOWN_JITTER
                        )
                        print(
                            f"Fetch attempt {attempt}/{max_retries} failed for {url}: {e}. "
                            f"500 suggests rate limiting — cooling down {cooldown:.1f}s before retry..."
                        )
                        time.sleep(cooldown)
                    else:
                        print(
                            f"Fetch attempt {attempt}/{max_retries} failed for {url}: {e}. Retrying after backoff..."
                        )
                        time.sleep(1.5 * attempt)
            except httpx.RequestError as e:
                last_error = e
                if attempt < max_retries:
                    print(
                        f"Fetch attempt {attempt}/{max_retries} failed for {url}: {e}. Retrying after backoff..."
                    )
                    time.sleep(1.5 * attempt)

        raise HTTPException(
            status_code=500,
            detail=f"Error fetching URL after {max_retries} attempts: {last_error}",
        )
