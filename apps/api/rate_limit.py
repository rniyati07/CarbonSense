"""ENG-5a — tenant-scoped rate limiting (TRD v2.0 §7.2/§9.2).

"Tiered at the gateway... enforced per-tenant... before a request reaches
the service layer." A fixed-window counter per (tenant_id, tier) is
sufficient to satisfy that requirement without introducing Redis or any
other shared store as a new infrastructure dependency -- this repo's stack
(TECH_STACK_LOCK.md) has none today, and ENG-5a's own scope is the gateway
layer, not a new datastore decision.

Known limitation, documented rather than silently accepted: this in-process
counter is per-worker-process. A multi-process/multi-instance API Gateway
deployment would under-enforce the configured limit (each process gets its
own budget) -- correct enough for a single-instance deployment or a
sticky-session load balancer, but a shared store (Redis) is required before
horizontally scaling the gateway. Flagged explicitly in the ENG-5 release
report as ENG-6/7 follow-up, not silently glossed over.
"""

from __future__ import annotations

import time
from collections import defaultdict
from uuid import UUID

from shared.config.auth import AuthSettings

_TIER_LIMITS_ATTR = {
    "freemium": "rate_limit_freemium_per_minute",
    "paid_sme": "rate_limit_paid_sme_per_minute",
    "enterprise": "rate_limit_enterprise_per_minute",
    "integrator": "rate_limit_integrator_per_minute",
}

_WINDOW_SECONDS = 60.0


class RateLimitExceededError(Exception):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit exceeded. Retry after {retry_after_seconds:.0f}s.")


class TenantRateLimiter:
    """Fixed-window counter keyed by (tenant_id, tier). Not thread-safe
    across true OS threads, but FastAPI's async event loop runs this
    single-threaded per worker process, which is the only concurrency
    model this limiter needs to support."""

    def __init__(self, settings: AuthSettings | None = None) -> None:
        self._settings = settings or AuthSettings()
        self._windows: dict[tuple[UUID, str], tuple[float, int]] = defaultdict(lambda: (0.0, 0))

    def _limit_for_tier(self, tier: str) -> int:
        attr = _TIER_LIMITS_ATTR.get(tier, _TIER_LIMITS_ATTR["freemium"])
        return int(getattr(self._settings, attr))

    def check(self, tenant_id: UUID, tier: str) -> None:
        limit = self._limit_for_tier(tier)
        now = time.monotonic()
        key = (tenant_id, tier)
        window_start, count = self._windows[key]

        if now - window_start >= _WINDOW_SECONDS:
            window_start, count = now, 0

        count += 1
        self._windows[key] = (window_start, count)

        if count > limit:
            retry_after = _WINDOW_SECONDS - (now - window_start)
            raise RateLimitExceededError(retry_after_seconds=max(retry_after, 0.0))


_default_limiter: TenantRateLimiter | None = None


def get_rate_limiter() -> TenantRateLimiter:
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = TenantRateLimiter()
    return _default_limiter
