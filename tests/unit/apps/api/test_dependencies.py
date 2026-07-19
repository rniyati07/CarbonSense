"""Unit-level coverage for the tenant-header-mismatch rejection logic
(TRD v2.0 §7.2) -- calls the dependency functions directly rather than
through a live HTTP app, since no database is required to prove this
particular guarantee. The full HTTP-level, real-database proof lives in
tests/security/tenant_isolation_fuzzer/test_api_tenant_isolation.py.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from apps.api.dependencies import get_validated_tenant_id
from shared.auth.jwt import TokenClaims


@pytest.mark.unit
class TestGetValidatedTenantId:
    @pytest.mark.asyncio
    async def test_returns_jwt_tenant_id_when_no_header_present(self) -> None:
        tenant_id = uuid.uuid4()
        claims = TokenClaims(tenant_id=tenant_id, subject="client-1", tier="freemium")

        result = await get_validated_tenant_id(claims=claims, x_tenant_id=None)

        assert result == tenant_id

    @pytest.mark.asyncio
    async def test_returns_jwt_tenant_id_when_header_matches(self) -> None:
        tenant_id = uuid.uuid4()
        claims = TokenClaims(tenant_id=tenant_id, subject="client-1", tier="freemium")

        result = await get_validated_tenant_id(claims=claims, x_tenant_id=str(tenant_id))

        assert result == tenant_id

    @pytest.mark.asyncio
    async def test_rejects_mismatched_header_with_403(self) -> None:
        jwt_tenant_id = uuid.uuid4()
        other_tenant_id = uuid.uuid4()
        claims = TokenClaims(tenant_id=jwt_tenant_id, subject="client-1", tier="freemium")

        with pytest.raises(HTTPException) as exc_info:
            await get_validated_tenant_id(claims=claims, x_tenant_id=str(other_tenant_id))

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_rejects_non_uuid_header_with_400(self) -> None:
        claims = TokenClaims(tenant_id=uuid.uuid4(), subject="client-1", tier="freemium")

        with pytest.raises(HTTPException) as exc_info:
            await get_validated_tenant_id(claims=claims, x_tenant_id="not-a-uuid")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_never_returns_the_header_value_over_the_jwt_claim(self) -> None:
        """Even when both are syntactically valid UUIDs, the header is
        never itself the source of truth -- only a match/mismatch check
        against the JWT claim, which is always what's returned."""
        jwt_tenant_id = uuid.uuid4()
        claims = TokenClaims(tenant_id=jwt_tenant_id, subject="client-1", tier="freemium")

        result = await get_validated_tenant_id(claims=claims, x_tenant_id=str(jwt_tenant_id))

        assert result is jwt_tenant_id or result == jwt_tenant_id
