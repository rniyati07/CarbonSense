from __future__ import annotations

import uuid

import pytest

from apps.api.rate_limit import RateLimitExceededError, TenantRateLimiter
from shared.config.auth import AuthSettings


@pytest.mark.unit
class TestTenantRateLimiter:
    def test_allows_requests_within_limit(self) -> None:
        settings = AuthSettings(rate_limit_freemium_per_minute=5)
        limiter = TenantRateLimiter(settings)
        tenant_id = uuid.uuid4()

        for _ in range(5):
            limiter.check(tenant_id, "freemium")  # must not raise

    def test_raises_once_limit_exceeded(self) -> None:
        settings = AuthSettings(rate_limit_freemium_per_minute=3)
        limiter = TenantRateLimiter(settings)
        tenant_id = uuid.uuid4()

        for _ in range(3):
            limiter.check(tenant_id, "freemium")

        with pytest.raises(RateLimitExceededError):
            limiter.check(tenant_id, "freemium")

    def test_tenants_have_independent_budgets(self) -> None:
        settings = AuthSettings(rate_limit_freemium_per_minute=1)
        limiter = TenantRateLimiter(settings)
        tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()

        limiter.check(tenant_a, "freemium")
        limiter.check(tenant_b, "freemium")  # must not raise -- independent budget

        with pytest.raises(RateLimitExceededError):
            limiter.check(tenant_a, "freemium")

    def test_higher_tier_gets_higher_limit(self) -> None:
        settings = AuthSettings(
            rate_limit_freemium_per_minute=1, rate_limit_enterprise_per_minute=10
        )
        limiter = TenantRateLimiter(settings)
        tenant_id = uuid.uuid4()

        for _ in range(5):
            limiter.check(tenant_id, "enterprise")  # well within the enterprise limit

    def test_unknown_tier_falls_back_to_freemium_limit(self) -> None:
        settings = AuthSettings(rate_limit_freemium_per_minute=1)
        limiter = TenantRateLimiter(settings)
        tenant_id = uuid.uuid4()

        limiter.check(tenant_id, "made-up-tier")
        with pytest.raises(RateLimitExceededError):
            limiter.check(tenant_id, "made-up-tier")
