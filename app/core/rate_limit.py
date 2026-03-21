import asyncio
from collections import defaultdict, deque
from time import time

from fastapi import HTTPException, Request, status


class InMemoryRateLimiter:
    """Simple per-key sliding-window rate limiter for low-traffic endpoints."""

    def __init__(self, *, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str) -> bool:
        now = time()
        cutoff = now - self.window_seconds

        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= self.limit:
                return False

            events.append(now)
            return True


_google_auth_rate_limiter = InMemoryRateLimiter(limit=5, window_seconds=60)


async def enforce_google_auth_rate_limit(request: Request) -> None:
    """Protect Google auth endpoint from brute-force bursts."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"google-auth:{client_ip}"

    allowed = await _google_auth_rate_limiter.hit(key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Try again in a minute.",
        )
