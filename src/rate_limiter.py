"""In-memory sliding window rate limiter."""

import time
from collections import defaultdict
from typing import Dict, List

from fastapi import HTTPException, status


class SlidingWindowRateLimiter:
    """Rate limiter using a sliding window of timestamps per caller."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def check(self, caller_id: str) -> None:
        """Check if the caller is within rate limits.

        Raises HTTPException(429) when the limit is exceeded.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        # Prune expired timestamps
        timestamps = self._requests[caller_id]
        self._requests[caller_id] = [t for t in timestamps if t > cutoff]

        if len(self._requests[caller_id]) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {self.max_requests} requests per {self.window_seconds}s",
            )

        self._requests[caller_id].append(now)


# Singleton instance
rate_limiter = SlidingWindowRateLimiter(max_requests=60, window_seconds=60)
