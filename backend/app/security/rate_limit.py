import asyncio
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.observability import record_metric


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str, max_requests: int, window_seconds: int) -> None:
        now = time.time()
        threshold = now - window_seconds

        async with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < threshold:
                bucket.popleft()

            if len(bucket) >= max_requests:
                record_metric("rate_limit_rejections")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                )

            bucket.append(now)


rate_limiter = InMemoryRateLimiter()


def rate_limit(max_requests: int, window_seconds: int, action: str):
    async def dependency(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        key = f"{action}:{client}"
        await rate_limiter.hit(key, max_requests=max_requests, window_seconds=window_seconds)

    return dependency
