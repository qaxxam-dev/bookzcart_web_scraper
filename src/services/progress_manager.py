"""
In-memory progress manager for scraping jobs.

Stores live counters, status, and log entries.  Exposes an async SSE
generator so the dashboard can stream real-time updates to the browser.
Logs are also persisted to disk under ``output/logs/``.

Thread-safety: scraper methods run inside ``asyncio.to_thread`` so their
progress callbacks execute on worker threads.  A ``threading.Lock`` guards
all mutations; the SSE generator is woken via ``asyncio.Event``.
"""

import asyncio
import json
import os
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator

# Log directory — created once at import time
LOG_DIR = Path("output/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


class JobStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ProgressManager:
    """Singleton-style progress store for the current scraping job."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._async_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.reset()

    # ------------------------------------------------------------------ #
    #  State management
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        """Reset all counters to the idle state."""
        with self._lock if hasattr(self, "_lock") else _noop_ctx():
            self.job_id: str = ""
            self.status: JobStatus = JobStatus.IDLE
            self.endpoint: str = ""
            self.input_params: dict[str, Any] = {}
            self.started_at: float = 0.0
            self.finished_at: float = 0.0

            # Publisher pages
            self.publisher_pages_total: int = 0
            self.publisher_pages_done: int = 0

            # List pages
            self.list_pages_total: int = 0
            self.list_pages_done: int = 0

            # Product URLs
            self.product_urls_total: int = 0

            # Products
            self.products_processed: int = 0
            self.products_failed: int = 0
            self.current_product_url: str = ""

            # Per-product sub-task counters
            self.scraping_done: int = 0
            self.ai_done: int = 0
            self.ai_failed: int = 0
            self.images_done: int = 0
            self.images_failed: int = 0

            # Log
            self.log_entries: list[str] = []
            self.error_message: str = ""
            self._log_file: Any = None  # file handle for disk persistence

    # ------------------------------------------------------------------ #
    #  Job lifecycle
    # ------------------------------------------------------------------ #

    def start_job(self, job_id: str, endpoint: str, params: dict[str, Any]) -> None:
        with self._lock:
            self.reset.__wrapped__(self) if hasattr(self.reset, "__wrapped__") else object.__getattribute__(self, "_do_reset")()  # noqa: E501
            self.job_id = job_id
            self.status = JobStatus.RUNNING
            self.endpoint = endpoint
            self.input_params = params
            self.started_at = time.time()
            self.finished_at = 0.0
            self.log_entries = []
            self.error_message = ""

            # Open log file for this job
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = LOG_DIR / f"{ts}_{job_id}.log"
            try:
                self._log_file = open(log_path, "a", encoding="utf-8")
            except OSError:
                self._log_file = None

            self._log(f"Job started — endpoint: /{endpoint}")
            self._log(f"Log file: {log_path}")
        self._notify()

    def _do_reset(self) -> None:
        """Internal reset without lock (called from within locked context)."""
        # Close previous log file if any
        if hasattr(self, "_log_file") and self._log_file:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

        self.job_id = ""
        self.status = JobStatus.IDLE
        self.endpoint = ""
        self.input_params = {}
        self.started_at = 0.0
        self.finished_at = 0.0
        self.publisher_pages_total = 0
        self.publisher_pages_done = 0
        self.list_pages_total = 0
        self.list_pages_done = 0
        self.product_urls_total = 0
        self.products_processed = 0
        self.products_failed = 0
        self.current_product_url = ""
        self.scraping_done = 0
        self.ai_done = 0
        self.ai_failed = 0
        self.images_done = 0
        self.images_failed = 0
        self.log_entries = []
        self.error_message = ""

    def complete_job(self) -> None:
        with self._lock:
            self.status = JobStatus.COMPLETED
            self.finished_at = time.time()
            self.current_product_url = ""
            self._log("Job completed ✅")
            self._close_log_file()
        self._notify()

    def fail_job(self, error: str) -> None:
        with self._lock:
            self.status = JobStatus.FAILED
            self.finished_at = time.time()
            self.error_message = error
            self.current_product_url = ""
            self._log(f"Job failed ❌ — {error}")
            self._close_log_file()
        self._notify()

    # ------------------------------------------------------------------ #
    #  Publisher-level updates
    # ------------------------------------------------------------------ #

    def set_publisher_pages(self, total: int) -> None:
        with self._lock:
            self.publisher_pages_total = total
            self._log(f"Publisher pages discovered: {total}")
        self._notify()

    def complete_publisher_page(self, page_index: int) -> None:
        with self._lock:
            self.publisher_pages_done = page_index + 1
            self._log(f"Publisher page {page_index + 1}/{self.publisher_pages_total} fetched")
        self._notify()

    # ------------------------------------------------------------------ #
    #  List-page-level updates
    # ------------------------------------------------------------------ #

    def set_list_page_products(self, count: int) -> None:
        with self._lock:
            self.product_urls_total += count
            self.list_pages_total += 1
            self._log(f"List page yielded {count} product URLs (total: {self.product_urls_total})")
        self._notify()

    def complete_list_page(self) -> None:
        with self._lock:
            self.list_pages_done += 1
            self._log(f"List page {self.list_pages_done}/{self.list_pages_total} processed")
        self._notify()

    # ------------------------------------------------------------------ #
    #  Product-level updates
    # ------------------------------------------------------------------ #

    def start_product(self, url: str) -> None:
        with self._lock:
            self.current_product_url = url
            self._log(f"Scraping product: {url}")
        self._notify()

    def complete_product(self) -> None:
        with self._lock:
            self.products_processed += 1
            self._log(f"Product done ({self.products_processed}/{self.product_urls_total})")
        self._notify()

    def fail_product(self, url: str, error: str) -> None:
        with self._lock:
            self.products_failed += 1
            self._log(f"Product FAILED: {url} — {error}")
        self._notify()

    # ------------------------------------------------------------------ #
    #  Per-product sub-task updates
    # ------------------------------------------------------------------ #

    def complete_scraping(self) -> None:
        """Data scraping (page fetch + extract) completed for one product."""
        with self._lock:
            self.scraping_done += 1
            self._log(f"  ↳ Data scraped ({self.scraping_done})")
        self._notify()

    def complete_ai(self) -> None:
        """AI processing (taxonomy + SEO) completed for one product."""
        with self._lock:
            self.ai_done += 1
            self._log(f"  ↳ AI processed ({self.ai_done})")
        self._notify()

    def fail_ai(self, error: str) -> None:
        """AI processing failed for one product."""
        with self._lock:
            self.ai_failed += 1
            self._log(f"  ↳ AI FAILED ({self.ai_failed}): {error}")
        self._notify()

    def complete_image(self) -> None:
        """Image processing completed for one product."""
        with self._lock:
            self.images_done += 1
            self._log(f"  ↳ Image saved ({self.images_done})")
        self._notify()

    def fail_image(self, url: str, error: str) -> None:
        """Image processing failed for one product."""
        with self._lock:
            self.images_failed += 1
            self._log(f"  ↳ Image FAILED ({self.images_failed}) for {url}: {error}")
        self._notify()

    # ------------------------------------------------------------------ #
    #  Snapshot (thread-safe read)
    # ------------------------------------------------------------------ #

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed = 0.0
            if self.started_at:
                end = self.finished_at if self.finished_at else time.time()
                elapsed = end - self.started_at

            overall_pct = 0.0
            if self.product_urls_total > 0:
                overall_pct = round(
                    (self.products_processed + self.products_failed)
                    / self.product_urls_total
                    * 100,
                    1,
                )

            return {
                "job_id": self.job_id,
                "status": self.status.value,
                "endpoint": self.endpoint,
                "input_params": self.input_params,
                "started_at": (
                    datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat()
                    if self.started_at
                    else None
                ),
                "elapsed_seconds": round(elapsed, 1),
                "publisher_pages_total": self.publisher_pages_total,
                "publisher_pages_done": self.publisher_pages_done,
                "list_pages_total": self.list_pages_total,
                "list_pages_done": self.list_pages_done,
                "product_urls_total": self.product_urls_total,
                "products_processed": self.products_processed,
                "products_failed": self.products_failed,
                "products_remaining": max(
                    0,
                    self.product_urls_total
                    - self.products_processed
                    - self.products_failed,
                ),
                "current_product_url": self.current_product_url,
                "overall_progress": overall_pct,
                # Per-product sub-task counters
                "scraping_done": self.scraping_done,
                "ai_done": self.ai_done,
                "ai_failed": self.ai_failed,
                "images_done": self.images_done,
                "images_failed": self.images_failed,
                "error_message": self.error_message,
                "log_entries": list(self.log_entries[-500:]),  # last 500
            }

    # ------------------------------------------------------------------ #
    #  SSE generator
    # ------------------------------------------------------------------ #

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the event-loop so worker threads can wake the SSE generator."""
        self._loop = loop
        self._async_event = asyncio.Event()

    async def sse_generator(self) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted snapshots whenever state changes."""
        if self._async_event is None:
            self.bind_loop(asyncio.get_running_loop())

        last_snapshot = ""
        while True:
            snap_json = json.dumps(self.snapshot())
            if snap_json != last_snapshot:
                last_snapshot = snap_json
                yield f"data: {snap_json}\n\n"

            # Wait for a notification or timeout (heartbeat every 2 s)
            try:
                self._async_event.clear()
                await asyncio.wait_for(self._async_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                # Send heartbeat comment to keep connection alive
                yield ": heartbeat\n\n"

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _log(self, message: str) -> None:
        """Append a timestamped log entry (must be called under lock)."""
        ts = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] {message}"
        self.log_entries.append(entry)

        # Persist to disk
        if self._log_file:
            try:
                self._log_file.write(entry + "\n")
                self._log_file.flush()
            except OSError:
                pass

    def _close_log_file(self) -> None:
        """Close the log file handle (must be called under lock)."""
        if self._log_file:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

    def _notify(self) -> None:
        """Wake the SSE generator from any thread."""
        if self._async_event and self._loop:
            self._loop.call_soon_threadsafe(self._async_event.set)


class _noop_ctx:
    """No-op context manager for initial reset before lock exists."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# Module-level singleton
progress = ProgressManager()
