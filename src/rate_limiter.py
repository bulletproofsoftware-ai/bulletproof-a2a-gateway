"""In-memory sliding window rate limiter.

The per-caller limit is read from ``RATE_LIMIT_RPM`` (requests per minute,
default 60). Because the window is in-process, the limit applies per gateway
worker — run a single worker, or put a shared limiter in front, if you need a
cluster-wide guarantee.
"""

import logging
import os
import time
from collections import defaultdict
from typing import Dict, List

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT_RPM = 60


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


def rate_limit_rpm() -> int:
    """Read the per-caller requests-per-minute limit from the environment."""
    raw = os.environ.get("RATE_LIMIT_RPM", str(DEFAULT_RATE_LIMIT_RPM))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "RATE_LIMIT_RPM=%r is not an integer; using %d",
            raw,
            DEFAULT_RATE_LIMIT_RPM,
        )
        return DEFAULT_RATE_LIMIT_RPM
    if value < 1:
        logger.warning(
            "RATE_LIMIT_RPM=%r must be >= 1; using %d", raw, DEFAULT_RATE_LIMIT_RPM
        )
        return DEFAULT_RATE_LIMIT_RPM
    return value


# Singleton instance — limit driven by RATE_LIMIT_RPM.
rate_limiter = SlidingWindowRateLimiter(
    max_requests=rate_limit_rpm(), window_seconds=60
)
