"""Minimal fixed-window in-memory rate limiter (per process). Enough for a single-node deployment."""
from __future__ import annotations

import threading
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, limit_per_minute: int):
        self.limit = limit_per_minute
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        window = int(time.time() // 60)
        with self._lock:
            w, count = self._buckets[key]
            if w != window:
                w, count = window, 0
            count += 1
            self._buckets[key] = (w, count)
            return count <= self.limit
