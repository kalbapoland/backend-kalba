import asyncio
from collections import defaultdict, deque
from time import time
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from app.core.security import get_current_user_id


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

    def reset(self) -> None:
        """Drop all recorded events. Intended for test isolation; the
        process-wide in-memory state would otherwise leak across tests."""
        self._events.clear()


_google_auth_rate_limiter = InMemoryRateLimiter(limit=5, window_seconds=60)
_push_token_rate_limiter = InMemoryRateLimiter(limit=10, window_seconds=60)
_password_reset_rate_limiter = InMemoryRateLimiter(limit=3, window_seconds=300)


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


async def enforce_password_reset_rate_limit(request: Request) -> None:
    """Cap password-reset requests per client to curb email-bombing / probing."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"password-reset:{client_ip}"

    allowed = await _password_reset_rate_limiter.hit(key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests. Try again in a few minutes.",
        )


async def enforce_push_token_rate_limit(
    user_id: UUID = Depends(get_current_user_id),
) -> None:
    """Cap per-user writes to push-token endpoints (called on every app launch)."""
    allowed = await _push_token_rate_limiter.hit(f"push-token:{user_id}")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many push token updates. Try again in a minute.",
        )
