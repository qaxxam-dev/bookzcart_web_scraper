import threading
from itertools import cycle

from src.config import settings


class ApiKeyCycle:
    _instance: "ApiKeyCycle | None" = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, api_keys=None):
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialised = False
                    cls._instance = instance
        return cls._instance

    def __init__(self, api_keys=None):
        if self._initialised:
            return

        if api_keys is None:
            api_keys = [
                settings.GENAI_API_KEY_01,
                settings.GENAI_API_KEY_02,
                settings.GENAI_API_KEY_03,
                settings.GENAI_API_KEY_04,
                settings.GENAI_API_KEY_05,
                settings.GENAI_API_KEY_06,
                settings.GENAI_API_KEY_07,
                settings.GENAI_API_KEY_08,
                settings.GENAI_API_KEY_09,
            ]
        self._api_keys = [key for key in api_keys if key]
        self._iterator = cycle(self._api_keys) if self._api_keys else iter(())
        self._iter_lock = threading.Lock()
        self._initialised = True

    def get_next_api_key(self) -> str:
        """Return the next API key in round-robin order (thread-safe)."""
        if not self._api_keys:
            raise ValueError("No API keys configured")
        with self._iter_lock:
            return next(self._iterator)
