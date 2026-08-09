"""
Async retry with exponential backoff + jitter, used to wrap every network/LLM
call in the system (LLM providers, web research fetches). Kept dependency-light
on top of `tenacity` so call sites stay declarative:

    @retryable(max_attempts=3, base_delay=0.5)
    async def call_llm(...): ...
"""
import asyncio
import functools
import logging
import random
from typing import Callable, TypeVar, Awaitable

logger = logging.getLogger("agent.retry")

T = TypeVar("T")


class RetryExhaustedError(Exception):
    def __init__(self, attempts: int, last_error: Exception):
        super().__init__(f"Retry exhausted after {attempts} attempts: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


def retryable(max_attempts: int = 3, base_delay: float = 0.5, max_delay: float = 8.0):
    def decorator(func: Callable[..., Awaitable[T]]):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 - intentionally broad, retried
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    delay += random.uniform(0, delay * 0.25)  # jitter
                    logger.warning(
                        "%s failed on attempt %s/%s (%s) — retrying in %.2fs",
                        func.__qualname__, attempt, max_attempts, exc, delay,
                    )
                    await asyncio.sleep(delay)
            raise RetryExhaustedError(max_attempts, last_exc)
        return wrapper
    return decorator
