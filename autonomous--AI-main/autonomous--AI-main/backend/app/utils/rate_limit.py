"""
Minimal in-process token-bucket rate limiter. Good enough for a single-process
hackathon deployment; for multi-instance production deployments, swap the
in-memory bucket for a Redis-backed one without changing the call sites.
"""
import time
import threading
from collections import defaultdict


class TokenBucket:
    def __init__(self, rate_per_minute: int):
        self.capacity = max(1, rate_per_minute)
        self.tokens = self.capacity
        self.refill_rate = self.capacity / 60.0  # tokens per second
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def try_consume(self, n: int = 1) -> bool:
        with self._lock:
            self._refill()
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False

    def wait_time(self, n: int = 1) -> float:
        with self._lock:
            self._refill()
            if self.tokens >= n:
                return 0.0
            missing = n - self.tokens
            return missing / self.refill_rate


class KeyedRateLimiter:
    """Per-key (e.g. per-IP, or a single global 'llm' key) token buckets."""

    def __init__(self, rate_per_minute: int):
        self.rate_per_minute = rate_per_minute
        self._buckets: dict[str, TokenBucket] = defaultdict(lambda: TokenBucket(rate_per_minute))

    def allow(self, key: str) -> bool:
        return self._buckets[key].try_consume()

    def wait_time(self, key: str) -> float:
        return self._buckets[key].wait_time()
