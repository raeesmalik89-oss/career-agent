"""Fixed-window rate limiter. In-process for Milestone 1; swapped for Redis in Milestone 11."""

import threading
import time


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Record one attempt; return False when the key is over its limit."""
        now = time.monotonic()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            count += 1
            self._hits[key] = (start, count)
            return count <= self.limit

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
